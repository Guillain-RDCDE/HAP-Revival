#!/usr/bin/env python3
"""
HAP push notifications — subscribe to the player's UDP event stream.

The HAP does not need to be polled. Subscribe once and it pushes a datagram
every time the track, the queue, the power state or the volume changes.

    POST http://<ip>:60200/sony/notification/status
    {"status": "enable", "port": 9999}
    -> {"timeout": 300, "port": 9999}

The player then sends pseudo-HTTP datagrams to <your-ip>:<port>:

    NOTIFY * HTTP/1.1
    Content-Length: 112
    Content-Type: application/json
    SEQ: 1
    X-ContentServiceHostUUID: uuid:00000000-0000-1010-8000-104FA86F4B84

    { "event": "playingtrackChanged", "url": ".../v100/playinginfo" }

The event says *what* changed and *where* to read it — it does not carry the
new state. GET the `url` to get that.

Three details that will bite you if you skip them:

  * Every event is transmitted **three times** under the same `SEQ`.
    Deduplicate on `SEQ` or you will act on each change three times.
  * The subscription expires after `timeout` seconds. Re-arm before then.
  * On Windows, the firewall drops the unsolicited inbound UDP. Sending one
    datagram outbound from the listening socket first opens the stateful
    mapping. This module does that automatically.

Discovered by tearing down the Crestron control module and verified live
against a HAP-Z1ES on firmware 19404R. See
`research/notes/2026-08-20-crestron-module-teardown.md` and
`docs/03-network-api.md`.

Library usage:
    from hap_notify import HapNotifier

    with HapNotifier("192.168.1.28") as n:
        for event in n.events():
            print(event.name, "->", n.fetch(event))

CLI usage:
    python tools/hap_notify.py 192.168.1.28              # stream events
    python tools/hap_notify.py 192.168.1.28 --follow     # and read the new state
    python tools/hap_notify.py 192.168.1.28 --duration 60 --raw

Read-only. Subscribing does not change anything on the device; the
subscription lapses on its own when this exits.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:  # local sibling module; keep the client importable even if it's absent
    import i18n
except ImportError:  # pragma: no cover
    i18n = None  # type: ignore[assignment]

# Active CLI language, resolved once in main(); None until then.
_LANG: str | None = None


def _t(key: str, **kwargs: object) -> str:
    """Translate a CLI string. Degrades to the key if i18n.py is unavailable."""
    if i18n is None:
        return key
    return i18n.t(key, _LANG, **kwargs)


DEFAULT_API_PORT = 60200
DEFAULT_LISTEN_PORT = 9999
SUBSCRIBE_PATH = "/sony/notification/status"

# Fraction of the server-declared timeout at which we re-arm. The server
# reports 300 s on 19404R; 0.8 gives a comfortable margin without chattering.
REARM_FRACTION = 0.8

# What to read back for each event, relative to the API root. The player sends
# an absolute `url` in the body and that is what we use — this map is the
# documented fallback for events that arrive without one.
EVENT_READBACK = {
    "playingtrackchanged": "/sony/contentplayer/v100/playinginfo",
    "playinginfochanged": "/sony/contentplayer/v100/playinginfo",
    "playqueuechanged": "/sony/contentplayer/v100/playqueue",
    "powerstatechanged": "/sony/contentplayer/v100/powerstate",
    "volumechanged": "/sony/contentplayer/v100/volumelevel",
}


class NotifyError(RuntimeError):
    """Subscription failed."""


@dataclass
class NotifyEvent:
    """One parsed NOTIFY datagram."""

    name: str
    """Event name as sent, e.g. `playingtrackChanged`."""

    seq: int | None
    """Value of the SEQ header. None if the datagram carried none."""

    url: str | None
    """Absolute URL to read the new state from, as sent by the player."""

    host_uuid: str | None
    """X-ContentServiceHostUUID — identifies which player sent this."""

    body: dict
    """The full decoded JSON body."""

    raw: bytes = field(repr=False, default=b"")

    @property
    def readback_path(self) -> str | None:
        """Path to GET for this event, falling back to the documented map when
        the player sends no `url`."""
        if self.url:
            return self.url
        return EVENT_READBACK.get(self.name.lower())


def parse_notify(datagram: bytes) -> NotifyEvent | None:
    """Parse one NOTIFY datagram. Returns None if it isn't one we understand.

    The datagram is a request line, headers, a blank line, then a JSON body —
    HTTP's shape, carried over UDP. We are deliberately lenient: header case
    varies, and a body may be split across the last lines.
    """
    try:
        text = datagram.decode("utf-8")
    except UnicodeDecodeError:
        return None

    # Split header block from body on the first blank line, tolerating both
    # CRLF and bare LF.
    normalised = text.replace("\r\n", "\n")
    head, _, body_text = normalised.partition("\n\n")
    if not body_text:
        # Some senders omit the blank line; fall back to the first '{'.
        brace = normalised.find("{")
        if brace == -1:
            return None
        head, body_text = normalised[:brace], normalised[brace:]

    lines = [ln for ln in head.split("\n") if ln.strip()]
    if not lines or not lines[0].upper().startswith("NOTIFY"):
        return None

    headers: dict[str, str] = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep:
            headers[key.strip().lower()] = value.strip()

    try:
        body = json.loads(body_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict) or "event" not in body:
        return None

    seq: int | None
    try:
        seq = int(headers["seq"])
    except (KeyError, ValueError):
        seq = None

    return NotifyEvent(
        name=str(body["event"]),
        seq=seq,
        url=body.get("url"),
        host_uuid=headers.get("x-contentservicehostuuid"),
        body=body,
        raw=datagram,
    )


class SeqTracker:
    """Drops the retransmissions the player sends for every event.

    Each event goes out three times under one SEQ. The counter is per-player,
    so we track it per host UUID (falling back to the sender's address) — one
    listener can serve several HAPs.

    A datagram with no SEQ is always processed: we would rather act twice than
    swallow a real event.
    """

    def __init__(self) -> None:
        self._last: dict[str, int] = {}

    def is_new(self, event: NotifyEvent, source: str = "") -> bool:
        if event.seq is None:
            return True
        key = event.host_uuid or source
        previous = self._last.get(key)
        if previous == event.seq:
            return False
        self._last[key] = event.seq
        return True


class HapNotifier:
    """Subscribes to the player's UDP event stream and yields events.

    Handles the three traps: SEQ deduplication, re-arming before the
    subscription expires, and priming the Windows firewall.
    """

    def __init__(
        self,
        ip: str,
        *,
        api_port: int = DEFAULT_API_PORT,
        listen_port: int = DEFAULT_LISTEN_PORT,
        timeout: float = 5.0,
    ) -> None:
        self.ip = ip
        self.api_port = api_port
        self.listen_port = listen_port
        self.timeout = timeout
        self.subscription_seconds: int | None = None
        self._sock: socket.socket | None = None
        self._tracker = SeqTracker()
        self._next_rearm = 0.0

    # ---------- context manager ----------

    def __enter__(self) -> "HapNotifier":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        """Bind the listening socket and subscribe."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.listen_port))
        sock.settimeout(1.0)
        self._sock = sock

        # Prime Windows' stateful UDP filtering: an outbound datagram from this
        # socket to the player makes the inbound notifications acceptable
        # without a firewall rule. Harmless everywhere else — the player
        # ignores it.
        try:
            sock.sendto(b"\x00", (self.ip, self.api_port))
        except OSError:
            pass

        self.subscribe()

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    # ---------- subscription ----------

    def subscribe(self) -> int:
        """(Re-)arm the subscription. Returns the server's timeout in seconds.

        The player only accepts a subscription while it is powered on.
        """
        payload = json.dumps({"status": "enable", "port": self.listen_port})
        url = f"http://{self.ip}:{self.api_port}{SUBSCRIBE_PATH}"
        request = Request(
            url,
            data=payload.encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "Connection": "close",
                "Content-Type": "application/json; charset=UTF-8",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise NotifyError(
                f"{SUBSCRIBE_PATH} returned HTTP {exc.code}. "
                "On firmware 19404R this path is correct; a 404 usually means "
                "the path was mistyped (note: the Crestron module's own "
                "/notification/status, without the /sony prefix, is a 404)."
            ) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise NotifyError(
                f"no answer from {url}. The player may be off, or another "
                "request may have wedged the daemon — it serialises requests, "
                "so one pending call blocks every endpoint until it is "
                "abandoned."
            ) from exc
        except json.JSONDecodeError as exc:
            raise NotifyError(f"unparseable answer from {url}") from exc

        seconds = int(body.get("timeout", 0)) or None
        self.subscription_seconds = seconds
        self._next_rearm = time.monotonic() + (seconds or 60) * REARM_FRACTION
        return seconds or 0

    # ---------- receiving ----------

    def events(self, duration: float | None = None) -> Iterator[NotifyEvent]:
        """Yield deduplicated events, re-arming the subscription as needed.

        Runs until `duration` seconds have elapsed, or forever if None.
        """
        if self._sock is None:
            raise RuntimeError("call open() first, or use as a context manager")

        end = None if duration is None else time.monotonic() + duration
        while end is None or time.monotonic() < end:
            if time.monotonic() >= self._next_rearm:
                self.subscribe()
            try:
                data, address = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            event = self.handle_datagram(data, address[0])
            if event is not None:
                yield event

    def handle_datagram(self, data: bytes, source: str = "") -> NotifyEvent | None:
        """Parse and deduplicate one datagram. Returns None if it should be
        ignored — unparseable, or a retransmission we have already seen."""
        event = parse_notify(data)
        if event is None:
            return None
        if not self._tracker.is_new(event, source):
            return None
        return event

    def fetch(self, event: NotifyEvent) -> dict | None:
        """GET the state the event points at."""
        path = event.readback_path
        if not path:
            return None
        url = (
            path
            if path.startswith("http://")
            else f"http://{self.ip}:{self.api_port}{path}"
        )
        request = Request(url, headers={"Accept": "application/json", "Connection": "close"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, socket.timeout, json.JSONDecodeError):
            return None


# ---------- CLI ----------


def _describe(event: NotifyEvent, state: dict | None, raw: bool) -> str:
    lines = [f"{time.strftime('%H:%M:%S')}  {event.name}  (SEQ {event.seq})"]
    if event.host_uuid:
        lines.append(f"          from {event.host_uuid}")
    if event.readback_path:
        lines.append(f"          read: {event.readback_path}")
    if state is not None:
        lines.append(f"          {json.dumps(state, ensure_ascii=False)}")
    if raw:
        lines.append("          --- raw ---")
        lines.extend(
            "          " + ln
            for ln in event.raw.decode("utf-8", "replace").splitlines()
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Subscribe to the HAP's UDP push notifications.",
        epilog="Read-only: subscribing changes nothing on the device.",
    )
    parser.add_argument("ip", help="player address, e.g. 192.168.1.28")
    parser.add_argument(
        "--lang",
        help="Output language: en, fr, ja, de, es, it (default: auto from OS locale / HAP_LANG).",
    )
    parser.add_argument(
        "--api-port", type=int, default=DEFAULT_API_PORT, help="player API port"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_LISTEN_PORT,
        help="local UDP port to receive notifications on",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="stop after N seconds (default: run until interrupted)",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="GET the state each event points at and print it",
    )
    parser.add_argument("--raw", action="store_true", help="also print the raw datagram")
    args = parser.parse_args(argv)

    global _LANG
    if i18n is not None:
        _LANG = i18n.detect_lang(override=args.lang)

    try:
        notifier = HapNotifier(
            args.ip, api_port=args.api_port, listen_port=args.port
        )
        notifier.open()
    except NotifyError as exc:
        print(_t("notify.err.subscribe", msg=str(exc)), file=sys.stderr)
        return 1
    except OSError as exc:
        print(_t("notify.err.bind", port=args.port, msg=str(exc)), file=sys.stderr)
        return 1

    print(
        _t(
            "notify.subscribed",
            ip=f"{args.ip}:{args.api_port}",
            port=args.port,
            renew=int((notifier.subscription_seconds or 0) * REARM_FRACTION),
        )
    )
    print(_t("notify.waiting") + "\n")

    count = 0
    try:
        with notifier:
            for event in notifier.events(args.duration):
                count += 1
                state = notifier.fetch(event) if args.follow else None
                print(_describe(event, state, args.raw), flush=True)
    except KeyboardInterrupt:
        print()
    except NotifyError as exc:
        print(_t("notify.err.subscribe", msg=str(exc)), file=sys.stderr)
        return 1

    print(_t("notify.received", count=count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
