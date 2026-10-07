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
import sys
import time

import hap_update

from hap_client import DEFAULT_TIMEOUT_SEC, RpcReply, rpc_post
from hap_common import API_PORT, safe_name, save_capture

TOOL_NAME = "HAP-Revival/tools/api-fuzzer.py"

# 90 s, not 6. A cold contentdb request takes up to 57 s; the old 6 s ceiling
# turned every one of them into a false negative and had this fuzzer reporting
# a live API as dead. See docs/16-gotchas.md §7.
HTTP_TIMEOUT_SEC = DEFAULT_TIMEOUT_SEC

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

# Sony's JSON-RPC error codes that tell us something about the method itself.
ERR_ILLEGAL_REQUEST = 5
ERR_NO_SUCH_METHOD = 12
ERR_UNSUPPORTED_VERSION = 14

# Classes that settle a (service, method): no point trying further versions.
DECISIVE = frozenset({"OK", "ILLEGAL_REQUEST", "NO_SUCH_METHOD", "OTHER"})
# Classes that prove the method exists.
EXISTS = frozenset({"OK", "ILLEGAL_REQUEST"})

# Throttle between calls: don't hammer the device.
PAUSE_SEC = 0.05


def classify(reply: RpcReply) -> str:
    """One of: OK, ILLEGAL_REQUEST, UNSUPPORTED_VERSION, NO_SUCH_METHOD, TRANSPORT, OTHER."""
    if reply.error is not None:
        return "TRANSPORT"
    err = reply.rpc_error
    if err is None:
        return "OK"
    code = err[0] if err else None
    if code == ERR_NO_SUCH_METHOD:
        return "NO_SUCH_METHOD"
    if code == ERR_UNSUPPORTED_VERSION:
        return "UNSUPPORTED_VERSION"
    if code == ERR_ILLEGAL_REQUEST:
        return "ILLEGAL_REQUEST"
    return "OTHER"


def call(ip: str, port: int, service: str, method: str, version: str, params: list) -> RpcReply:
    return rpc_post(ip, service, method, version, params, port=port, timeout=HTTP_TIMEOUT_SEC)


def fuzz_method(ip: str, port: int, service: str, method: str, sleep=time.sleep) -> list[dict]:
    """Try every version of one method until an answer settles it.

    Every reply other than "unsupported version" is a finding worth keeping
    (a transport error on one version is evidence too), so a method can yield
    several rows; the first decisive one ends the search.
    """
    findings: list[dict] = []
    for version in VERSIONS_TO_TRY:
        reply = call(ip, port, service, method, version, [])
        klass = classify(reply)
        if klass != "UNSUPPORTED_VERSION":
            snippet = json.dumps(reply.as_dict())[:140]
            print(f"  [{klass:18s}] {service:10s} {method:35s} v{version}: {snippet}")
            findings.append({
                "service": service,
                "method": method,
                "version": version,
                "class": klass,
                "response": reply.as_dict(),
            })
            if klass in DECISIVE:
                return findings
        sleep(PAUSE_SEC)
    # Every version answered UNSUPPORTED_VERSION (or only transport noise).
    print(f"  [UNSUPPORTED_ALL  ] {service:10s} {method:35s} (all versions tried)")
    findings.append({
        "service": service,
        "method": method,
        "version": None,
        "class": "UNSUPPORTED_VERSION_ALL",
        "response": None,
    })
    return findings


def fuzz(
    ip: str, port: int, only_service: str | None, only_method: str | None, sleep=time.sleep
) -> list[dict]:
    findings: list[dict] = []
    for service, methods in CANDIDATES.items():
        if only_service and service != only_service:
            continue
        for method in methods:
            if only_method and method != only_method:
                continue
            findings.extend(fuzz_method(ip, port, service, method, sleep=sleep))
    return findings


def summarize(findings: list[dict]) -> str:
    by_class: dict[str, int] = {}
    for f in findings:
        by_class[f["class"]] = by_class.get(f["class"], 0) + 1
    lines = ["", "=== Summary ==="]
    lines += [f"  {k:25s} {by_class[k]}" for k in sorted(by_class)]
    lines += ["", "Methods that returned OK or ILLEGAL_REQUEST (= method exists):"]
    lines += [
        f"  {f['service']}.{f['method']} v{f['version']}: {f['class']}"
        for f in findings
        if f["class"] in EXISTS
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    hap_update.add_version_flag(parser)
    parser.add_argument("--target", required=True, help="HAP IP address")
    parser.add_argument("--port", type=int, default=API_PORT)
    parser.add_argument("--service", help="Only fuzz this service")
    parser.add_argument("--method", help="Only fuzz this method (across all services in scope)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hap_update.notice_at_exit()

    print(f"Fuzzing {args.target}:{args.port} ...")
    findings = fuzz(args.target, args.port, args.service, args.method)
    out = save_capture(
        f"fuzz-{safe_name(args.target)}",
        {"target": args.target, "findings": findings},
        tool=TOOL_NAME,
    )
    print(summarize(findings))
    print(f"\nReport saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
