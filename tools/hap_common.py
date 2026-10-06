#!/usr/bin/env python3
"""
Shared plumbing for the HAP-Revival tools.

Everything here used to be copied between scripts: the device's port numbers,
the two share names, the Wake-on-LAN packet, the TCP reachability probe, the
tolerant JSON cache files under ``~/.hap-revival``, the capture files under
``research/captures/``, and the UTF-8 console fix for Windows. One copy each,
so a correction lands everywhere at once.

Stdlib only, importable on every OS, and it never talks to a device by itself.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- the device

#: ScalarWebAPI (JSON-RPC), the contentdb / contentplayer REST surfaces and the
#: front-panel ``/sony/hap`` endpoint all live on this one port.
API_PORT = 60200
#: UPnP device description (``/hap.xml``).
UPNP_PORT = 60100
#: SMB over Direct TCP, and SMB over NetBIOS. The HAP's Samba 3.0.37 speaks both.
SMB_DIRECT_PORT = 445
SMB_NETBIOS_PORT = 139
#: The two music shares the player exposes.
SHARES = ("HAP_Internal", "HAP_External")
#: Wake-on-LAN broadcast target (the discard port, as every WoL sender uses).
WOL_TARGET = ("255.255.255.255", 9)

# ---------------------------------------------------------------- locations

#: The repository root, derived from this file so tools work from any cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent
#: Where probe scripts drop their evidence.
CAPTURES_DIR = REPO_ROOT / "research" / "captures"
#: Per-user cache for harvested catalogues and share indexes. Outside the repo
#: on purpose: it is the owner's own library metadata and must never be
#: committed by accident.
USER_CACHE_DIR = Path.home() / ".hap-revival"


def safe_name(text: str) -> str:
    """Turn a host or share name into something that is safe as a file name."""
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in text)


def human_size(n: float) -> str:
    """``1536`` -> ``1.5 KB``; bytes are shown whole, everything else to one decimal."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"  # pragma: no cover - the loop always returns


# ---------------------------------------------------------------- console


def force_utf8_stdio() -> None:
    """Make stdout/stderr emit UTF-8 even on a legacy Windows code page.

    Several tools print accents, CJK and box-drawing characters; a cp1252
    console would otherwise raise on the first of them. Silently a no-op on
    streams that cannot be reconfigured (pipes under some test runners).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


# ---------------------------------------------------------------- network


def tcp_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """True if a TCP connect to ``host:port`` succeeds within ``timeout`` seconds."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def normalize_mac(mac: str) -> str:
    """``80-56-f2-85-0e-27`` -> ``80:56:F2:85:0E:27``. Does not validate."""
    return mac.strip().upper().replace("-", ":")


def mac_to_bytes(mac: str) -> bytes:
    """The six bytes of a MAC written with colons, dashes or nothing at all.

    Raises ValueError when the text is not twelve hex digits.
    """
    hexmac = mac.replace(":", "").replace("-", "").strip()
    if len(hexmac) != 12:
        raise ValueError("MAC must be 12 hex digits (e.g. 80:56:F2:85:0E:27)")
    try:
        return bytes.fromhex(hexmac)
    except ValueError as exc:
        raise ValueError("MAC must be 12 hex digits (e.g. 80:56:F2:85:0E:27)") from exc


def wol_packet(mac: str) -> bytes:
    """The 102-byte magic packet for ``mac``: six 0xFF then the MAC sixteen times."""
    return b"\xff" * 6 + mac_to_bytes(mac) * 16


def send_wol(mac: str, target: tuple[str, int] = WOL_TARGET) -> None:
    """Broadcast a Wake-on-LAN magic packet to ``mac``.

    The HAP sleeps in network standby; this is how the CLI and the GUI both
    wake it. Raises ValueError on a malformed MAC before touching the network.
    """
    packet = wol_packet(mac)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.sendto(packet, target)
    finally:
        sock.close()


# ---------------------------------------------------------------- files


def read_json(path: Path) -> Any | None:
    """Parse a UTF-8 JSON file, or return None when it is absent or unreadable.

    A Windows BOM is tolerated: hand-edited config files often carry one.
    """
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_json(path: Path, data: Any, *, indent: int | None = None, atomic: bool = False) -> Path:
    """Write ``data`` as UTF-8 JSON, creating parent folders as needed.

    Bytes rather than text on purpose: the default text encoding on Windows is
    not UTF-8 and a library full of accents would be mangled on the way out.
    ``atomic`` writes a sibling temp file and renames it over the target, so a
    reader never sees a half-written cache.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=indent).encode("utf-8")
    if not atomic:
        path.write_bytes(payload)
        return path
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)
    return path


def utc_stamp(when: datetime | None = None) -> str:
    """``20260525T183945Z`` — the timestamp format every capture file name uses."""
    return (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def save_capture(prefix: str, payload: dict, *, tool: str, out_dir: Path | None = None) -> Path:
    """Write a probe result under ``research/captures/`` and return its path.

    The file is named ``<prefix>-<utc stamp>.json`` and the payload is stamped
    with the tool that produced it, so a capture can always be traced back.
    """
    target_dir = out_dir or CAPTURES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "tool": tool,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    path = target_dir / f"{prefix}-{utc_stamp()}.json"
    return write_json(path, record, indent=2)


def local_timestamp() -> str:
    """``2026-05-25 18:39:45`` in local time, for human-facing cache metadata."""
    return time.strftime("%Y-%m-%d %H:%M:%S")
