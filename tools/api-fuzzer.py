#!/usr/bin/env python3
"""
Fuzz the Sony HAP ScalarWebAPI by calling candidate method names at multiple
versions and recording which combinations return useful responses.

The candidate method list combines:
  - methods we already know work on the HAP (catalog)
  - methods documented for cousin Sony devices (BRAVIA, STR-DN, python-songpal)
  - speculative variants worth trying

Each call uses an empty `params: []` by default (or a minimal stub). Methods
that need real params will return `error [5, "illegal Request"]` — that's
still useful: it confirms the method *exists* on this service at this version.

Read-only. Does not modify device state.

Usage:
    python tools/api-fuzzer.py --target 192.168.1.28
    python tools/api-fuzzer.py --target 192.168.1.28 --service audio
    python tools/api-fuzzer.py --target 192.168.1.28 --method getContentList
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


HTTP_TIMEOUT_SEC = 6

# Candidate methods grouped by service.
# Add to this list as new method names are discovered.
CANDIDATES: dict[str, list[str]] = {
    "system": [
        "getMethodTypes",
        "getVersions",
        "getSystemInformation",
        "getPowerStatus",
        "setPowerStatus",
        "getInterfaceInformation",
        "getNetworkSettings",
        "setNetworkSettings",
        "getCurrentTime",
        "setCurrentTime",
        "getStorageList",
        "getDeviceMode",
        "setDeviceMode",
        "getSWUpdateInfo",
        "actSWUpdate",
        "getRemoteControllerInfo",
        "getWuTangInfo",  # tested, not implemented
        "getLEDIndicatorStatus",
        "setLEDIndicatorStatus",
        "getColorKeysLayout",
    ],
    "audio": [
        "getMethodTypes",
        "getVersions",
        "getVolumeInformation",
        "setAudioVolume",
        "setAudioMute",
        "getSoundSettings",
        "setSoundSettings",
        "getSpeakerSettings",
        "setSpeakerSettings",
        "getCustomEqualizerSettings",
        "setCustomEqualizerSettings",
        "getAudioOutputs",
    ],
    "avContent": [
        "getMethodTypes",
        "getVersions",
        "getPlayingContentInfo",
        "setPlayContent",
        "pausePlayingContent",
        "stopPlayingContent",
        "setPlayPreviousContent",
        "setPlayNextContent",
        "seekStreamingContent",
        "scanPlayingContent",
        "getSchemeList",
        "getSourceList",
        "getContentList",
        "getContentCount",
        "getContentInfo",
        "getCurrentExternalTerminalsStatus",
        "setActiveTerminal",
        "getPlaybackModeSettings",
        "setPlaybackModeSettings",
        "getSupportedPlaybackFunction",
        "getAvailablePlaybackFunction",
        "getBluetoothSettings",
        "setBluetoothSettings",
        "deleteContent",
        "getFavoriteList",
        "setFavoriteContent",
    ],
    "guide": [
        "getMethodTypes",
        "getVersions",
        "getSupportedApiInfo",
        "getServiceProtocols",
        "switchNotifications",
    ],
}

VERSIONS_TO_TRY = ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7"]


def call(
    ip: str, port: int, service: str, method: str, version: str, params: list
) -> dict[str, Any]:
    url = f"http://{ip}:{port}/sony/{service}"
    body = json.dumps(
        {"method": method, "id": 1, "params": params, "version": version}
    ).encode("utf-8")
    req = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_SEC) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw": raw}
    except HTTPError as e:
        return {"_http_error": e.code, "_reason": e.reason}
    except (URLError, socket.timeout) as e:
        return {"_transport_error": str(e)}


def classify(resp: dict) -> str:
    """Return one of: OK, ILLEGAL_REQUEST, UNSUPPORTED_VERSION, NO_SUCH_METHOD, TRANSPORT, OTHER."""
    if "_transport_error" in resp:
        return "TRANSPORT"
    if "_http_error" in resp:
        return "TRANSPORT"
    err = resp.get("error")
    if err is None:
        return "OK"
    if isinstance(err, list) and len(err) >= 1:
        code = err[0]
        if code == 12:
            return "NO_SUCH_METHOD"
        if code == 14:
            return "UNSUPPORTED_VERSION"
        if code == 5:
            return "ILLEGAL_REQUEST"
    return "OTHER"


def fuzz(ip: str, port: int, only_service: str | None, only_method: str | None) -> list[dict]:
    findings: list[dict] = []

    for service, methods in CANDIDATES.items():
        if only_service and service != only_service:
            continue
        for method in methods:
            if only_method and method != only_method:
                continue
            # Try each version. Stop early per (service, method) once we get OK
            # or a non-version error (those are informative regardless of version).
            stop = False
            for version in VERSIONS_TO_TRY:
                resp = call(ip, port, service, method, version, [])
                klass = classify(resp)
                if klass != "UNSUPPORTED_VERSION":
                    finding = {
                        "service": service,
                        "method": method,
                        "version": version,
                        "class": klass,
                        "response": resp,
                    }
                    findings.append(finding)
                    snippet = json.dumps(resp)[:140]
                    print(f"  [{klass:18s}] {service:10s} {method:35s} v{version}: {snippet}")
                    # If OK or ILLEGAL_REQUEST or NO_SUCH_METHOD, we have enough.
                    if klass in {"OK", "ILLEGAL_REQUEST", "NO_SUCH_METHOD", "OTHER"}:
                        stop = True
                        break
                # Throttle: don't hammer the device.
                time.sleep(0.05)
            if not stop:
                # All versions returned UNSUPPORTED_VERSION — record that.
                findings.append(
                    {
                        "service": service,
                        "method": method,
                        "version": None,
                        "class": "UNSUPPORTED_VERSION_ALL",
                        "response": None,
                    }
                )
                print(f"  [UNSUPPORTED_ALL  ] {service:10s} {method:35s} (all versions tried)")
    return findings


def save(findings: list[dict], target_ip: str) -> Path:
    out_dir = Path(__file__).resolve().parent.parent / "research" / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"fuzz-{target_ip.replace('.', '_')}-{ts}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "tool": "HAP-Revival/tools/api-fuzzer.py",
                "target": target_ip,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "findings": findings,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    return out_path


def summarize(findings: list[dict]) -> None:
    by_class: dict[str, int] = {}
    for f in findings:
        by_class[f["class"]] = by_class.get(f["class"], 0) + 1
    print("\n=== Summary ===")
    for k in sorted(by_class):
        print(f"  {k:25s} {by_class[k]}")
    print("\nMethods that returned OK or ILLEGAL_REQUEST (= method exists):")
    for f in findings:
        if f["class"] in {"OK", "ILLEGAL_REQUEST"}:
            print(f"  {f['service']}.{f['method']} v{f['version']}: {f['class']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="HAP IP address")
    parser.add_argument("--port", type=int, default=60200)
    parser.add_argument("--service", help="Only fuzz this service")
    parser.add_argument("--method", help="Only fuzz this method (across all services in scope)")
    args = parser.parse_args()

    print(f"Fuzzing {args.target}:{args.port} ...")
    findings = fuzz(args.target, args.port, args.service, args.method)
    out = save(findings, args.target)
    summarize(findings)
    print(f"\nReport saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
