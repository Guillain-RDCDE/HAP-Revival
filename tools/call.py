#!/usr/bin/env python3
"""
Generic JSON-RPC caller for the Sony HAP ScalarWebAPI.

Make a one-off call from the command line. Useful for exploration and for
copy-pasting from issues / PRs.

Usage:
    python tools/call.py --target IP --service SVC --method METHOD --version V --params 'JSON'

Examples:
    # Now playing
    python tools/call.py --target 192.168.1.28 --service avContent \\
        --method getPlayingContentInfo --version 1.2 --params '[]'

    # System information
    python tools/call.py --target 192.168.1.28 --service system \\
        --method getSystemInformation --version 1.4 --params '[]'

    # Play an HDD track by id (use getContentList on netService for browsing; HDD browse
    # is via the DB, see docs/09-disk-layout.md)
    python tools/call.py --target 192.168.1.28 --service avContent \\
        --method createPlayingListAndQuickPlay --version 1.0 --params '[{"uri":"audio:track?id=1"}]'

    # Pause/resume (this method is a TOGGLE, params are [{}])
    python tools/call.py --target 192.168.1.28 --service avContent \\
        --method pausePlayingContent --version 1.1 --params '[{}]'

Read-only by default in terms of what this tool DOES (it just POSTs whatever
you give it) — but obviously the call itself may change device state. Don't
call setPlayContent or deleteContent without understanding what you're doing.
"""

from __future__ import annotations

import argparse
import json
import sys

from hap_client import DEFAULT_TIMEOUT_SEC, RpcReply, rpc_post, rpc_url
from hap_common import API_PORT, save_capture

TOOL_NAME = "HAP-Revival/tools/call.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", required=True, help="HAP IP address")
    parser.add_argument("--port", type=int, default=API_PORT)
    parser.add_argument("--service", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--params",
        default="[]",
        help='JSON for the params array. Example: \'[{"uri":"audio:album","stIdx":0,"cnt":5}]\'',
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SEC,
        help="seconds to wait; a cold contentdb call needs up to 57 s",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save request+response to research/captures/.",
    )
    return parser


def capture_record(args: argparse.Namespace, params: list, reply: RpcReply) -> dict:
    """The capture payload: the request as sent and the reply as received."""
    return {
        "target": args.target,
        "port": args.port,
        "request": {
            "service": args.service,
            "method": args.method,
            "version": args.version,
            "params": params,
        },
        "response": reply.as_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"--params is not valid JSON: {e}", file=sys.stderr)
        return 2

    envelope = {"method": args.method, "id": 1, "params": params, "version": args.version}
    print(f"POST {rpc_url(args.target, args.service, args.port)}", file=sys.stderr)
    print(f"  body: {json.dumps(envelope, ensure_ascii=False)}", file=sys.stderr)

    reply = rpc_post(
        args.target, args.service, args.method, args.version, params,
        port=args.port, timeout=args.timeout,
    )

    print(f"\nHTTP {reply.status}", file=sys.stderr)
    if reply.error is not None:
        print(reply.error, file=sys.stderr)
    if isinstance(reply.body, (dict, list)):
        print(json.dumps(reply.body, indent=2, ensure_ascii=False))
    elif reply.body is not None:
        print(reply.body)

    if args.save:
        out = save_capture(
            f"call-{args.service}-{args.method}-v{args.version}",
            capture_record(args, params, reply),
            tool=TOOL_NAME,
        )
        print(f"\nSaved: {out}", file=sys.stderr)

    return 0 if reply.status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
