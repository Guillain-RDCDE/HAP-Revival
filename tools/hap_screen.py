#!/usr/bin/env python3
"""
Mirror the Sony HAP-Z1ES / HAP-S1 front panel and press its keys, over HTTP.

Both live on an undocumented namespace on port 60200, found in the player's own
legacy web pages (`/HAP_v1.0.html` + `/haplib.js`) and confirmed live on 19404R:

    GET /sony/hap?target=screen&cmd=display_png    -> the framebuffer, 480x272 PNG
    GET /sony/hap?target=screen&cmd=download_png   -> same image, as a download
    GET /sony/hap?target=screen&cmd=capture_png    -> writes it to the SMB share
    GET /sony/hap?target=keyevent&cmd=<key>        -> injects one front-panel key

See research/notes/2026-08-27-hap-tool-endpoint.md.

`show` is read-only. `capture` writes a file to HAP_Internal/anap/capture/ on the
player, and `key` drives the player's UI — both change state on the device.

Requires: Python 3.10+, stdlib only.

Usage:
    python tools/hap_screen.py <ip> show                    # -> screen.png
    python tools/hap_screen.py <ip> show -o now.png
    python tools/hap_screen.py <ip> key option
    python tools/hap_screen.py <ip> key down down enter     # keys in sequence
    python tools/hap_screen.py <ip> capture
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

TOOL_PORT = 60200
HTTP_TIMEOUT_SEC = 20

# The nine keys the player's own page wires up, plus two the page never mentions.
#
# `next` and `prev` were found by probing the handler on 2026-08-30: it answers
# "None" for them and "server error" for everything else tried (stop, pause,
# previous, menu, display, input, select, ok, return, exit, top, info, function,
# favorite, repeat, shuffle, add, options, settings). So the accepted set is
# eleven, not nine.
#
# **Accepted is not the same as acts**, and the two differ here. Tested against a
# live multi-track queue with a control reading (same track, position 25 s → 32 s
# while untouched):
#   `next` — advances. Twice in a row, each time a different title at ~7 s in.
#   `prev` — accepted, but the track did not change. Effect unconfirmed.
# So `prev` is kept out of the UI until somebody can show it doing something.
KEYS = ("home", "up", "down", "left", "right", "enter", "back", "option", "play",
        "next", "prev")
KEYS_UNVERIFIED = ("prev",)

# The pages leave this long between a key and the follow-up screen grab.
KEY_SETTLE_SEC = 1.0


def tool_url(host: str, target: str, cmd: str) -> str:
    """Build a /sony/hap URL, cache-busted the way the player's own pages are."""
    query = urllib.parse.urlencode(
        {"target": target, "cmd": cmd, "nocache": str(int(time.time() * 1000))}
    )
    return f"http://{host}:{TOOL_PORT}/sony/hap?{query}"


def tool_get(host: str, target: str, cmd: str) -> tuple[bytes, str]:
    """GET one tool command. Returns (body, content-type)."""
    with urlopen(tool_url(host, target, cmd), timeout=HTTP_TIMEOUT_SEC) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def cmd_show(host: str, out: Path) -> int:
    body, ctype = tool_get(host, "screen", "display_png")
    if not body.startswith(b"\x89PNG"):
        print(
            f"not a PNG (Content-Type: {ctype or 'none'}, {len(body)} bytes): "
            f"{body[:64]!r}",
            file=sys.stderr,
        )
        return 1
    out.write_bytes(body)
    print(f"{out} ({len(body)} bytes)")
    return 0


def cmd_key(host: str, keys: list[str]) -> int:
    unknown = [k for k in keys if k not in KEYS]
    if unknown:
        print(
            f"unknown key(s): {', '.join(unknown)} - known: {', '.join(KEYS)}",
            file=sys.stderr,
        )
        return 2
    for i, key in enumerate(keys):
        tool_get(host, "keyevent", key)
        print(f"sent {key}")
        if i + 1 < len(keys):
            time.sleep(KEY_SETTLE_SEC)
    return 0


def cmd_capture(host: str) -> int:
    tool_get(host, "screen", "capture_png")
    # The player answers the 4-byte string "None" whether or not it wrote
    # anything, so there is nothing here worth reporting back as a result.
    print("capture requested - look in HAP_Internal/anap/capture/ on the share")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mirror the HAP front panel and press its keys."
    )
    parser.add_argument("host", help="player IP or hostname")
    sub = parser.add_subparsers(dest="action", required=True)

    p_show = sub.add_parser("show", help="fetch the front panel as a PNG")
    p_show.add_argument(
        "-o", "--output", type=Path, default=Path("screen.png"), help="output file"
    )

    p_key = sub.add_parser("key", help="inject one or more front-panel keys")
    p_key.add_argument("keys", nargs="+", metavar="KEY", help=f"one of: {', '.join(KEYS)}")

    sub.add_parser("capture", help="make the player write a PNG to its own share")

    args = parser.parse_args()

    try:
        if args.action == "show":
            return cmd_show(args.host, args.output)
        if args.action == "key":
            return cmd_key(args.host, args.keys)
        return cmd_capture(args.host)
    except HTTPError as exc:
        print(f"HTTP {exc.code} from {args.host}: {exc.reason}", file=sys.stderr)
    except URLError as exc:
        print(f"cannot reach {args.host}: {exc.reason}", file=sys.stderr)
    except TimeoutError:
        print(f"timed out after {HTTP_TIMEOUT_SEC}s - is the player awake?", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
