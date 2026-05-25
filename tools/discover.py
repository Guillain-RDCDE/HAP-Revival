#!/usr/bin/env python3
"""
Discover Sony HAP-Z1ES / HAP-S1 devices on the local network and probe their
ScalarWebAPI surface.

No write operations. Outputs to research/captures/discover-<timestamp>.txt.

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
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


SSDP_MULTICAST = ("239.255.255.250", 1900)
SSDP_TIMEOUT_SEC = 4
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


def ssdp_search() -> list[dict]:
    """Send SSDP M-SEARCH and collect responses. Returns one dict per HAP device."""
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_MULTICAST[0]}:{SSDP_MULTICAST[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 3\r\n"
        "ST: ssdp:all\r\n\r\n"
    ).encode("ascii")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(SSDP_TIMEOUT_SEC)
    sock.sendto(msg, SSDP_MULTICAST)

    seen_ips: dict[str, dict] = {}
    deadline = time.time() + SSDP_TIMEOUT_SEC
    while time.time() < deadline:
        try:
            data, (ip, _port) = sock.recvfrom(4096)
        except socket.timeout:
            break
        text = data.decode("ascii", errors="replace")
        if "Sony-HAP" not in text:
            continue
        headers = _parse_ssdp_headers(text)
        if ip not in seen_ips:
            seen_ips[ip] = {"ip": ip, "headers": headers, "services": []}
        st = headers.get("st", "")
        if st and st not in seen_ips[ip]["services"]:
            seen_ips[ip]["services"].append(st)
    sock.close()
    return list(seen_ips.values())


def _parse_ssdp_headers(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    return out


def fetch_hap_xml(ip: str, port: int = 60100) -> Optional[str]:
    url = f"http://{ip}:{port}/hap.xml"
    try:
        with urlopen(url, timeout=HTTP_TIMEOUT_SEC) as r:
            return r.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, socket.timeout) as e:
        print(f"  [hap.xml] error: {e}", file=sys.stderr)
        return None


def jsonrpc_call(
    ip: str,
    service: str,
    method: str,
    version: str,
    params: list,
    port: int = 60200,
) -> dict:
    """POST a JSON-RPC call. Returns the parsed JSON response or {'_error': ...}."""
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
            # Critical: do NOT send Expect: 100-continue (HAP returns 417).
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
        return {"_error": f"HTTP {e.code}: {e.reason}"}
    except (URLError, socket.timeout) as e:
        return {"_error": str(e)}


def probe_device(ip: str) -> dict:
    """Run the standard probe sequence on one HAP device."""
    result: dict = {"ip": ip, "timestamp": datetime.now(timezone.utc).isoformat()}

    print(f"[{ip}] Fetching hap.xml ...")
    hap_xml = fetch_hap_xml(ip)
    result["hap_xml"] = hap_xml

    if hap_xml:
        for key in ("modelName", "friendlyName", "X_HAP_Version"):
            tag_open = f"<{key}>"
            ns_match = None
            for tag in (tag_open, f"<av:{key}>"):
                if tag in hap_xml:
                    start = hap_xml.find(tag) + len(tag)
                    end = hap_xml.find("<", start)
                    ns_match = hap_xml[start:end].strip()
                    break
            if ns_match:
                result[key] = ns_match

    print(f"[{ip}] Probing JSON-RPC methods ...")
    api_results: list[dict] = []
    for service, method, version, params in KNOWN_METHODS:
        resp = jsonrpc_call(ip, service, method, version, params)
        entry = {
            "service": service,
            "method": method,
            "version": version,
            "params": params,
            "response": resp,
        }
        api_results.append(entry)
        ok = "_error" not in resp and "error" not in resp
        marker = "OK " if ok else "ERR"
        snippet = json.dumps(resp)[:120]
        print(f"  [{marker}] {service}.{method} v{version} -> {snippet}")
    result["api_probe"] = api_results

    return result


def save_report(devices: list[dict]) -> Path:
    out_dir = Path(__file__).resolve().parent.parent / "research" / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"discover-{ts}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "tool": "HAP-Revival/tools/discover.py",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "devices": devices,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    return out_path


def main() -> int:
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
    args = parser.parse_args()

    devices: list[dict] = []

    if args.target:
        print(f"Probing direct target {args.target} ...")
        devices.append(probe_device(args.target))
    else:
        print("Sending SSDP M-SEARCH (4s window) ...")
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

    out = save_report(devices)
    print(f"\nReport saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
