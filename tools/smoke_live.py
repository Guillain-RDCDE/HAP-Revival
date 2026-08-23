#!/usr/bin/env python3
"""
Live smoke test — exercise the client against a real HAP and check it actually
reads something.

The offline suite in `tests/` cannot catch a whole class of bug here, and we
proved it: `radio_registration` was fully covered by tests that passed while the
client read nothing at all, because the test double returned a reply shaped
differently from what `HAP.call` really returns. See
`docs/16-gotchas.md#the-green-tests-problem`.

So this asserts on **content**, not on the absence of an exception. A check that
merely calls a method and shrugs would have passed on the broken client too.

    python tools/smoke_live.py 192.168.1.28
    python tools/smoke_live.py 192.168.1.28 --json

Read-only by default. Nothing here changes what the player is doing, its
settings, or its queue. `--include-writes` adds two writes that are idempotent
by construction — each reads a value and writes the *same* value back — and even
those are opt-in.

Never run this from CI: it needs hardware, and it is the owner's hi-fi.
Exit code 0 if every check passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hap_client import HAP, _first_field  # noqa: E402

# The daemon serialises requests; a hung one poisons everything after it.
# See docs/16-gotchas.md#3-never-issue-requests-concurrently.
PAUSE_BETWEEN_CHECKS = 0.4


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False


@dataclass
class Smoke:
    ip: str
    results: list[Result] = field(default_factory=list)

    def check(self, name: str, fn) -> None:
        """Run one check. `fn` returns a detail string, or raises to fail."""
        time.sleep(PAUSE_BETWEEN_CHECKS)
        try:
            detail = fn()
        except SkipCheck as exc:
            self.results.append(Result(name, True, str(exc), skipped=True))
        except Exception as exc:  # noqa: BLE001 — a smoke test reports, never crashes
            self.results.append(Result(name, False, f"{type(exc).__name__}: {exc}"))
        else:
            self.results.append(Result(name, True, detail))

    @property
    def failed(self) -> list[Result]:
        return [r for r in self.results if not r.ok]


class SkipCheck(Exception):
    """Not applicable to this device — not a failure."""


def _nonempty(value, label: str):
    """Assert a value is actually populated. This is the whole point of the file."""
    if value is None or value == "" or value == [] or value == {}:
        raise AssertionError(f"{label} came back empty ({value!r})")
    return value


def _http_get(url: str, timeout: float = 8.0) -> tuple[int, bytes]:
    req = Request(url, headers={"Accept": "application/json", "Connection": "close"})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except HTTPError as e:
        return e.code, e.read()


def build(ip: str, include_writes: bool) -> Smoke:
    hap = HAP(ip)
    s = Smoke(ip)
    base = f"http://{ip}:60200"

    # ---- JSON-RPC, the surface most of our tools use ----

    def system_info():
        info = hap.system_info()
        _nonempty(info.model, "model")
        _nonempty(info.version, "firmware version")
        return f"{info.model} {info.version}"

    s.check("system_info returns a model and firmware", system_info)

    def power():
        return _nonempty(hap.power_status(), "power status")

    s.check("power_status returns a state", power)

    def now_playing():
        np = hap.now_playing()
        _nonempty(np.state, "playback state")
        return f"state={np.state} title={np.title or '(none)'}"

    s.check("now_playing returns a state", now_playing)

    def sound():
        snd = hap.sound_settings()
        # At least one setting must be populated; all-None means we parsed nothing.
        values = [snd.dsee, snd.dsd_remastering, snd.gapless_playback,
                  snd.volume_normalization, snd.oversampling]
        if not any(v for v in values):
            raise AssertionError(f"every sound setting came back empty: {values!r}")
        return f"dsee={snd.dsee} dsd={snd.dsd_remastering} gapless={snd.gapless_playback}"

    s.check("sound_settings parses at least one value", sound)

    # ---- the exact bug the offline suite missed ----

    def registration():
        reply = hap.radio_registration("check")
        found = _first_field(reply, "isRegistered")
        if found is None:
            raise AssertionError(
                f"isRegistered not found in {reply!r} — this is the unwrapping bug "
                "that green unit tests hid once already"
            )
        return f"isRegistered={found}"

    s.check("radio_registration('check') yields isRegistered", registration)

    def pin():
        code = _first_field(hap.radio_registration("getPin"), "pinCode")
        _nonempty(code, "pinCode")
        if not isinstance(code, str) or len(code) < 4:
            raise AssertionError(f"pinCode looks wrong: {code!r}")
        return f"pinCode={code}"

    s.check("radio_registration('getPin') yields a pinCode", pin)

    def registered_flag():
        value = hap.radio_is_registered()
        if not isinstance(value, bool):
            raise AssertionError(f"expected a bool, got {value!r}")
        return f"registered={value}"

    s.check("radio_is_registered returns a real bool", registered_flag)

    # ---- the REST surface ----

    def rest_power():
        status, body = _http_get(f"{base}/sony/contentplayer/v100/powerstate")
        if status != 200:
            raise AssertionError(f"HTTP {status}")
        _nonempty(json.loads(body).get("power_state"), "power_state")
        return json.loads(body)["power_state"]

    s.check("REST powerstate answers 200 with a value", rest_power)

    def rest_sound():
        status, body = _http_get(f"{base}/sony/contentplayer/v100/settings/sound/dsee")
        if status != 200:
            raise AssertionError(f"HTTP {status}")
        setting = json.loads(body).get("setting") or {}
        _nonempty(setting.get("value"), "dsee value")
        return f"dsee={setting['value']}"

    s.check("REST sound setting answers 200 with a value", rest_sound)

    def rest_volume():
        status, body = _http_get(f"{base}/sony/contentplayer/v100/volumelevel")
        if status == 500:
            raise SkipCheck("500 — expected on a Z1ES, which has no volume stage")
        if status != 200:
            raise AssertionError(f"HTTP {status}")
        data = json.loads(body)
        if "volume_level" not in data:
            raise AssertionError(f"no volume_level in {data!r}")
        return f"volume_level={data['volume_level']} (an S1)"

    s.check("REST volumelevel answers or 500s as expected", rest_volume)

    # ---- the traps from docs/16-gotchas.md, asserted as still true ----

    def expect_header():
        """Gotcha 2. If this ever stops being true, the docs are stale."""
        req = Request(
            f"{base}/sony/avContent",
            data=json.dumps(
                {"method": "getPlayingContentInfo", "id": 1, "params": [], "version": "1.2"}
            ).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Expect": "100-continue"},
        )
        try:
            with urlopen(req, timeout=8):
                raise AssertionError("expected 417, got a success — gotcha 2 may be obsolete")
        except HTTPError as e:
            if e.code != 417:
                raise AssertionError(f"expected 417, got {e.code}") from None
            return "417 as documented"

    s.check("Expect: 100-continue still returns 417", expect_header)

    def cors_headers():
        """Gotcha 1. The absence of Allow-Headers is the whole trap."""
        req = Request(f"{base}/sony/avContent", method="OPTIONS")
        req.add_header("Origin", "http://example.com")
        req.add_header("Access-Control-Request-Method", "POST")
        req.add_header("Access-Control-Request-Headers", "content-type")
        with urlopen(req, timeout=8) as r:
            allow_origin = r.headers.get("Access-Control-Allow-Origin")
            allow_headers = r.headers.get("Access-Control-Allow-Headers")
        if allow_origin != "http://example.com":
            raise AssertionError(f"Allow-Origin no longer echoes: {allow_origin!r}")
        if allow_headers is not None:
            raise AssertionError(
                f"Allow-Headers is now sent ({allow_headers!r}) — gotcha 1 may be obsolete"
            )
        return "origin echoed, Allow-Headers absent, as documented"

    s.check("CORS preflight still omits Allow-Headers", cors_headers)

    # ---- optional, idempotent writes ----

    if include_writes:

        def idempotent_sound_write():
            current = _first_field(
                json.loads(
                    _http_get(f"{base}/sony/contentplayer/v100/settings/sound/dsee")[1]
                ).get("setting", {}),
                "value",
            )
            _nonempty(current, "dsee before")
            hap.set_sound_setting("dsee", current)          # same value back
            time.sleep(1.0)
            after = json.loads(
                _http_get(f"{base}/sony/contentplayer/v100/settings/sound/dsee")[1]
            )["setting"]["value"]
            if after != current:
                raise AssertionError(f"dsee changed from {current!r} to {after!r}")
            return f"dsee {current!r} written back unchanged"

        s.check("idempotent sound write round-trips", idempotent_sound_write)

        def unregistered_guard():
            """play_station must not fire on an unregistered player."""
            if hap.radio_is_registered():
                raise SkipCheck("player is registered — guard not exercised")
            before = hap.now_playing().state
            # We deliberately do NOT call play_station here: the point is that the
            # CLI guard exists. Assert the predicate the guard reads instead.
            return f"unregistered, guard would refuse (state stays {before})"

        s.check("radio guard predicate is readable", unregistered_guard)

    return s


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Exercise the client against a real HAP and assert it reads real values.",
        epilog="Read-only unless --include-writes. Never run from CI.",
    )
    p.add_argument("ip", help="player address, e.g. 192.168.1.28")
    p.add_argument(
        "--include-writes",
        action="store_true",
        help="also run idempotent writes (reads a value, writes the same value back)",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    try:
        socket.create_connection((args.ip, 60200), timeout=5).close()
    except OSError as exc:
        print(f"cannot reach {args.ip}:60200 — {exc}", file=sys.stderr)
        return 1

    smoke = build(args.ip, args.include_writes)

    if args.json:
        print(json.dumps(
            {"ip": smoke.ip,
             "passed": len([r for r in smoke.results if r.ok and not r.skipped]),
             "skipped": len([r for r in smoke.results if r.skipped]),
             "failed": len(smoke.failed),
             "checks": [vars(r) for r in smoke.results]},
            indent=2, ensure_ascii=False))
        return 1 if smoke.failed else 0

    print(f"live smoke test against {smoke.ip}\n")
    for r in smoke.results:
        mark = "SKIP" if r.skipped else ("ok  " if r.ok else "FAIL")
        print(f"  [{mark}] {r.name}")
        if r.detail:
            print(f"         {r.detail}")
    passed = len([r for r in smoke.results if r.ok and not r.skipped])
    skipped = len([r for r in smoke.results if r.skipped])
    print(f"\n{passed} passed, {skipped} skipped, {len(smoke.failed)} failed")
    return 1 if smoke.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
