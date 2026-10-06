#!/usr/bin/env python3
"""
Discover Sony HAP-Z1ES / HAP-S1 devices on the local network and probe their
ScalarWebAPI surface.

No write operations. Outputs to research/captures/discover-<timestamp>.json.

Usage:
    python tools/discover.py                 # default: full sweep
    python tools/discover.py --quick         # SSDP only, no API probe
    python tools/discover.py --target IP     # skip SSDP, probe a known IP

Requires: Python 3.10+, stdlib only.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime, timezone

from hap_client import (
    HAPTransportError,
    RpcReply,
    rpc_post,
    upnp_description,
    upnp_field,
)
from hap_common import API_PORT, save_capture

TOOL_NAME = "HAP-Revival/tools/discover.py"

SSDP_MULTICAST = ("239.255.255.250", 1900)
SSDP_TIMEOUT_SEC = 4
# Deliberately short, unlike everywhere else in this repo: discovery sweeps a
# whole subnet and only calls fast system/audio methods. Never point this at
# /sony/contentdb/v100 — those need 90 s (docs/16-gotchas.md §7).
HTTP_TIMEOUT_SEC = 6

# Methods we know about, keyed by (service, method) -> (version, params).
# Pulled from research/api-method-catalog.md. Read-only methods only.
KNOWN_METHODS: list[tuple[str, str, str, list]] = [
    ("system", "getSystemInformation", "1.2", []),
    ("system", "getPowerStatus", "1.1", []),
    ("system", "getInterfaceInformation", "1.0", []),
    ("system", "getStorageList", "1.0", []),
    ("audio", "getVolumeInformation", "1.1", []),
    ("audio", "getSoundSettings", "1.1", [{"target": ""}]),
    ("avContent", "getPlayingContentInfo", "1.2", []),
    ("avContent", "getCurrentExternalTerminalsStatus", "1.0", []),
    ("avContent", "getPlaybackModeSettings", "1.0", [{"target": ""}]),
    ("avContent", "getSchemeList", "1.0", []),
]

# The fields worth lifting out of hap.xml into the report.
UPNP_FIELDS = ("modelName", "friendlyName", "X_HAP_Version")


def ssdp_message() -> bytes:
    """The M-SEARCH datagram, asking every device on the LAN to answer."""
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_MULTICAST[0]}:{SSDP_MULTICAST[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 3\r\n"
        "ST: ssdp:all\r\n\r\n"
    ).encode("ascii")


def parse_ssdp_headers(text: str) -> dict[str, str]:
    """Lower-cased header map from one SSDP response."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    return out


def collect_ssdp(responses: list[tuple[str, bytes]]) -> list[dict]:
    """Fold raw (ip, datagram) pairs into one record per HAP device."""
    seen_ips: dict[str, dict] = {}
    for ip, data in responses:
        text = data.decode("ascii", errors="replace")
        if "Sony-HAP" not in text:
            continue
        headers = parse_ssdp_headers(text)
        device = seen_ips.setdefault(ip, {"ip": ip, "headers": headers, "services": []})
        st = headers.get("st", "")
        if st and st not in device["services"]:
            device["services"].append(st)
    return list(seen_ips.values())


def ssdp_search() -> list[dict]:
    """Send SSDP M-SEARCH and collect responses. Returns one dict per HAP device."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(SSDP_TIMEOUT_SEC)
    responses: list[tuple[str, bytes]] = []
    try:
        sock.sendto(ssdp_message(), SSDP_MULTICAST)
        deadline = time.time() + SSDP_TIMEOUT_SEC
        while time.time() < deadline:
            try:
                data, (ip, _port) = sock.recvfrom(4096)
            except TimeoutError:
                break
            responses.append((ip, data))
    finally:
        sock.close()
    return collect_ssdp(responses)


def fetch_hap_xml(ip: str) -> str | None:
    try:
        return upnp_description(ip, timeout=HTTP_TIMEOUT_SEC)
    except HAPTransportError as e:
        print(f"  [hap.xml] error: {e}", file=sys.stderr)
        return None


def jsonrpc_call(
    ip: str,
    service: str,
    method: str,
    version: str,
    params: list,
    port: int = API_PORT,
) -> RpcReply:
    """POST one JSON-RPC call with discovery's short timeout."""
    return rpc_post(ip, service, method, version, params, port=port, timeout=HTTP_TIMEOUT_SEC)


def probe_device(ip: str) -> dict:
    """Run the standard probe sequence on one HAP device."""
    result: dict = {"ip": ip, "timestamp": datetime.now(timezone.utc).isoformat()}

    print(f"[{ip}] Fetching hap.xml ...")
    hap_xml = fetch_hap_xml(ip)
    result["hap_xml"] = hap_xml

    if hap_xml:
        for key in UPNP_FIELDS:
            value = upnp_field(hap_xml, key)
            if value:
                result[key] = value

    print(f"[{ip}] Probing JSON-RPC methods ...")
    api_results: list[dict] = []
    for service, method, version, params in KNOWN_METHODS:
        reply = jsonrpc_call(ip, service, method, version, params)
        api_results.append(
            {
                "service": service,
                "method": method,
                "version": version,
                "params": params,
                "response": reply.as_dict(),
            }
        )
        marker = "OK " if reply.ok else "ERR"
        snippet = json.dumps(reply.body if reply.error is None else reply.error)[:120]
        print(f"  [{marker}] {service}.{method} v{version} -> {snippet}")
    result["api_probe"] = api_results

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        help="Skip SSDP. Probe this IP address directly.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="SSDP only, no JSON-RPC probe.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    devices: list[dict] = []

    if args.target:
        print(f"Probing direct target {args.target} ...")
        devices.append(probe_device(args.target))
    else:
        print(f"Sending SSDP M-SEARCH ({SSDP_TIMEOUT_SEC}s window) ...")
        found = ssdp_search()
        if not found:
            print(
                "No HAP devices found via SSDP. "
                "Try --target <ip> to probe directly."
            )
            return 1
        print(f"Found {len(found)} HAP device(s): {[d['ip'] for d in found]}")
        for d in found:
            if args.quick:
                devices.append(
                    {"ip": d["ip"], "services": d["services"], "headers": d["headers"]}
                )
            else:
                devices.append(probe_device(d["ip"]))

    out = save_capture("discover", {"devices": devices}, tool=TOOL_NAME)
    print(f"\nReport saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
