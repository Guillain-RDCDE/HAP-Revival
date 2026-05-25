#!/usr/bin/env python3
"""
Generic JSON-RPC caller for the Sony HAP ScalarWebAPI.

Make a one-off call from the command line. Useful for exploration and for
copy-pasting from issues / PRs.

Usage:
    python tools/call.py --target IP --service SVC --method METHOD --version V --params 'JSON'

Examples:
    # Now playing
    python tools/call.py --target 192.168.1.28 --service avContent --method getPlayingContentInfo --version 1.2 --params '[]'

    # Browse top-level albums
    python tools/call.py --target 192.168.1.28 --service avContent --method getContentList --version 1.3 --params '[{"uri":"audio:album","stIdx":0,"cnt":5}]'

    # Skip to next track
    python tools/call.py --target 192.168.1.28 --service avContent --method setPlayNextContent --version 1.0 --params '[{"output":""}]'

Read-only by default in terms of what this tool DOES (it just POSTs whatever
you give it) — but obviously the call itself may change device state. Don't
call setPlayContent or deleteContent without understanding what you're doing.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def call(
    ip: str,
    port: int,
    service: str,
    method: str,
    version: str,
    params: list,
    timeout: int,
) -> tuple[int, dict | str]:
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
        with urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        return e.code, {"_http_error": str(e), "_body": err_body}
    except (URLError, socket.timeout) as e:
        return -1, {"_transport_error": str(e)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", required=True)
    parser.add_argument("--port", type=int, default=60200)
    parser.add_argument("--service", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--params",
        default="[]",
        help='JSON for the params array. Example: \'[{"uri":"audio:album","stIdx":0,"cnt":5}]\'',
    )
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save request+response to research/captures/.",
    )
    args = parser.parse_args()

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"--params is not valid JSON: {e}", file=sys.stderr)
        return 2

    print(
        f"POST http://{args.target}:{args.port}/sony/{args.service}",
        file=sys.stderr,
    )
    print(
        f'  body: {{"method":"{args.method}","id":1,"params":{json.dumps(params)},"version":"{args.version}"}}',
        file=sys.stderr,
    )

    status, resp = call(
        args.target,
        args.port,
        args.service,
        args.method,
        args.version,
        params,
        args.timeout,
    )

    print(f"\nHTTP {status}", file=sys.stderr)
    if isinstance(resp, dict):
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    else:
        print(resp)

    if args.save:
        out_dir = Path(__file__).resolve().parent.parent / "research" / "captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = out_dir / f"call-{args.service}-{args.method}-v{args.version}-{ts}.json"
        with out.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "tool": "HAP-Revival/tools/call.py",
                    "target": args.target,
                    "port": args.port,
                    "request": {
                        "service": args.service,
                        "method": args.method,
                        "version": args.version,
                        "params": params,
                    },
                    "response": {"status": status, "body": resp},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"\nSaved: {out}", file=sys.stderr)

    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
