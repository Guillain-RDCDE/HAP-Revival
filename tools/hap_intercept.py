#!/usr/bin/env python3
"""
Watch what the player asks the Internet for, without a mirror port.

The HAP sits on a switched LAN, so a PC on the same network cannot see its
traffic by sniffing. But the player takes its DNS server from its own network
settings, and those are reachable from the front panel — which is scriptable
since `hap_screen.py`. Point the player's DNS at this machine and every name it
looks up lands here, in order, with a timestamp.

Two layers, deliberately separate:

  DNS  (udp/53)  Logs every query, then *forwards it upstream and relays the
                 real answer*. Nothing breaks. This alone answers "which host
                 does the player use for TuneIn?".

  HTTP (tcp/80)  Only sees traffic for names given with --hijack. For those,
                 DNS answers with this machine's address, the request lands
                 here, the full path is logged, and it is then relayed to the
                 real server so the player still gets a genuine reply. This is
                 what answers "what path does Network Update fetch?" —
                 info.update.sony.net is plain HTTP with no HTTPS redirect
                 (docs/07-firmware.md), so relaying it is straightforward.

Only hijack names you know are plain HTTP. A hijacked HTTPS name will fail the
handshake at the player, because this proxy has no certificate for it.

Nothing is written to the player. To undo, put the player's DNS back to your
router's address (or back to DHCP).

Requires: Python 3.10+, stdlib only. Ports 53 and 80 must be free, and inbound
traffic to them allowed through the local firewall.

Usage:
    python tools/hap_intercept.py --ip 192.168.1.100 \
        --hijack info.update.sony.net \
        --log research/captures/2026-08-29-update.jsonl
    python tools/hap_intercept.py --ip 192.168.1.100      # observe only
"""

from __future__ import annotations

import argparse
import json
import socket
import socketserver
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DNS_PORT = 53
HTTP_PORT = 80
UPSTREAM_TIMEOUT_SEC = 5
PROXY_TIMEOUT_SEC = 30
ANSWER_TTL_SEC = 60
DNS_MAX_UDP = 4096

# Query types we bother naming in the log. Anything else is logged by number.
QTYPE_NAMES = {1: "A", 2: "NS", 5: "CNAME", 12: "PTR", 16: "TXT", 28: "AAAA"}
QTYPE_A = 1
QTYPE_AAAA = 28

_log_lock = threading.Lock()
_log_path: Path | None = None


def now_iso() -> str:
    """Timestamp for the log, UTC, second resolution."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(kind: str, **fields: object) -> None:
    """Print one event and, if a log file was given, append it as JSON."""
    event = {"at": now_iso(), "kind": kind, **fields}
    line = "  ".join(f"{k}={v}" for k, v in event.items() if k != "kind")
    with _log_lock:
        print(f"[{kind}] {line}", flush=True)
        if _log_path is not None:
            with _log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def parse_question(packet: bytes) -> tuple[str, int] | None:
    """Read the single question of a DNS query. Returns (name, qtype)."""
    if len(packet) < 12:
        return None
    labels: list[str] = []
    offset = 12
    while offset < len(packet):
        length = packet[offset]
        if length == 0:
            offset += 1
            break
        # A pointer here would mean a compressed question, which no resolver
        # sends. Refuse rather than guess.
        if length & 0xC0:
            return None
        offset += 1
        labels.append(packet[offset : offset + length].decode("ascii", "replace"))
        offset += length
    if offset + 4 > len(packet):
        return None
    qtype = struct.unpack("!H", packet[offset : offset + 2])[0]
    return ".".join(labels), qtype


def build_a_answer(query: bytes, ip: str) -> bytes:
    """Answer a query with one A record pointing at `ip`."""
    transaction_id = query[:2]
    flags = struct.pack("!H", 0x8180)  # response, recursion available
    counts = struct.pack("!HHHH", 1, 1, 0, 0)
    question = query[12:]
    answer = (
        b"\xc0\x0c"  # pointer back to the question's name
        + struct.pack("!HHIH", QTYPE_A, 1, ANSWER_TTL_SEC, 4)
        + socket.inet_aton(ip)
    )
    return transaction_id + flags + counts + question + answer


def build_empty_answer(query: bytes) -> bytes:
    """Answer with NOERROR and no records — used to push the player to IPv4."""
    transaction_id = query[:2]
    flags = struct.pack("!H", 0x8180)
    counts = struct.pack("!HHHH", 1, 0, 0, 0)
    return transaction_id + flags + counts + query[12:]


def forward_upstream(packet: bytes, upstream: str) -> bytes | None:
    """Relay a query verbatim to the real resolver and return its reply."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(UPSTREAM_TIMEOUT_SEC)
        try:
            sock.sendto(packet, (upstream, DNS_PORT))
            reply, _ = sock.recvfrom(DNS_MAX_UDP)
        except OSError:
            return None
    return reply


class DNSHandler(socketserver.BaseRequestHandler):
    """One UDP datagram: log it, then hijack or relay."""

    hijack: set[str] = set()
    our_ip = ""
    upstream = ""

    def handle(self) -> None:
        packet, sock = self.request
        parsed = parse_question(packet)
        if parsed is None:
            return
        name, qtype = parsed
        type_name = QTYPE_NAMES.get(qtype, str(qtype))
        hijacked = name.lower() in self.hijack

        record(
            "dns",
            client=self.client_address[0],
            name=name,
            type=type_name,
            action="hijack" if hijacked else "forward",
        )

        if hijacked and qtype == QTYPE_A:
            sock.sendto(build_a_answer(packet, self.our_ip), self.client_address)
            return
        if hijacked and qtype == QTYPE_AAAA:
            sock.sendto(build_empty_answer(packet), self.client_address)
            return

        reply = forward_upstream(packet, self.upstream)
        if reply is not None:
            sock.sendto(reply, self.client_address)


class ThreadedUDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True


class ProxyHandler(BaseHTTPRequestHandler):
    """Log a hijacked request in full, then relay it to the real server."""

    protocol_version = "HTTP/1.1"
    server_version = "hap-intercept"

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence the default stderr logging; we do our own."""

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        self._relay("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._relay("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._relay("POST")

    def _relay(self, method: str) -> None:
        host = self.headers.get("Host", "")
        hostname = host.split(":")[0]
        body = b""
        length = self.headers.get("Content-Length")
        if length and length.isdigit():
            body = self.rfile.read(int(length))

        record(
            "http",
            client=self.client_address[0],
            method=method,
            host=host,
            path=self.path,
            agent=self.headers.get("User-Agent", ""),
            range=self.headers.get("Range", ""),
            body_bytes=len(body),
        )

        if not hostname:
            self.send_error(400, "no Host header")
            return

        try:
            upstream_ip = socket.gethostbyname(hostname)
        except OSError as exc:
            record("http-error", host=host, path=self.path, error=str(exc))
            self.send_error(502, "cannot resolve upstream")
            return

        try:
            self._pump(method, upstream_ip, host, body)
        except OSError as exc:
            record("http-error", host=host, path=self.path, error=str(exc))
            try:
                self.send_error(502, "upstream failed")
            except OSError:
                pass

    def _pump(self, method: str, upstream_ip: str, host: str, body: bytes) -> None:
        """Replay the request against the real server and stream the reply back."""
        # http.client is deliberately not used: it would re-derive the Host
        # header from the address we connect to, and the whole point is to keep
        # the player's own Host and path byte for byte.
        request = [f"{method} {self.path} HTTP/1.0"]
        for key, value in self.headers.items():
            if key.lower() in ("connection", "proxy-connection", "host"):
                continue
            request.append(f"{key}: {value}")
        request.append(f"Host: {host}")
        raw = ("\r\n".join(request) + "\r\n\r\n").encode("latin-1") + body

        with socket.create_connection((upstream_ip, 80), PROXY_TIMEOUT_SEC) as sock:
            sock.sendall(raw)
            reply = sock.makefile("rb")
            status_line = reply.readline()
            headers: list[bytes] = []
            while True:
                line = reply.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                headers.append(line)
            payload = reply.read()

        status = status_line.decode("latin-1", "replace").strip()
        summary = {
            k.decode("latin-1").split(":", 1)[0].lower(): k.decode(
                "latin-1", "replace"
            ).split(":", 1)[1].strip()
            for k in headers
            if b":" in k
        }
        record(
            "http-reply",
            host=host,
            path=self.path,
            status=status,
            content_type=summary.get("content-type", ""),
            bytes=len(payload),
        )

        self.wfile.write(status_line)
        for line in headers:
            lowered = line.lower()
            # Content-Length is re-derived below: the upstream one would not
            # match if the body arrived chunked, and two of them is malformed.
            if lowered.startswith(
                (b"connection:", b"transfer-encoding:", b"content-length:")
            ):
                continue
            self.wfile.write(line)
        self.wfile.write(b"Content-Length: %d\r\n" % len(payload))
        self.wfile.write(b"Connection: close\r\n\r\n")
        if method != "HEAD":
            self.wfile.write(payload)


def local_ip_guess() -> str:
    """Best guess at the address the player should be told to use."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.168.1.1", 53))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Log what the HAP looks up, and optionally relay one host."
    )
    parser.add_argument(
        "--ip",
        default="",
        help="this machine's LAN address, as the player will see it "
        "(default: guessed)",
    )
    parser.add_argument(
        "--hijack",
        action="append",
        default=[],
        metavar="HOST",
        help="answer this name with our address and relay its HTTP through us; "
        "repeatable. Plain-HTTP hosts only.",
    )
    parser.add_argument(
        "--upstream",
        default="1.1.1.1",
        help="real resolver to forward everything else to (default: 1.1.1.1)",
    )
    parser.add_argument(
        "--log",
        default="",
        metavar="FILE",
        help="append every event to this file as JSON lines",
    )
    args = parser.parse_args(argv)

    global _log_path
    if args.log:
        _log_path = Path(args.log)
        _log_path.parent.mkdir(parents=True, exist_ok=True)

    our_ip = args.ip or local_ip_guess()
    hijack = {h.lower() for h in args.hijack}

    DNSHandler.hijack = hijack
    DNSHandler.our_ip = our_ip
    DNSHandler.upstream = args.upstream

    try:
        dns_server = ThreadedUDPServer(("0.0.0.0", DNS_PORT), DNSHandler)  # noqa: S104
    except OSError as exc:
        print(f"cannot bind udp/{DNS_PORT}: {exc}", file=sys.stderr)
        return 1

    http_server = None
    if hijack:
        try:
            http_server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), ProxyHandler)  # noqa: S104, E501
        except OSError as exc:
            dns_server.server_close()
            print(f"cannot bind tcp/{HTTP_PORT}: {exc}", file=sys.stderr)
            return 1

    print(f"DNS  listening on {our_ip}:{DNS_PORT}, forwarding to {args.upstream}")
    if http_server is not None:
        print(f"HTTP relaying on {our_ip}:{HTTP_PORT} for: {', '.join(sorted(hijack))}")
    else:
        print("HTTP relay off (no --hijack given): observing names only")
    print(f"Set the player's DNS server to {our_ip}, then drive it. Ctrl-C to stop.")
    if _log_path is not None:
        print(f"Logging to {_log_path}")

    threading.Thread(target=dns_server.serve_forever, daemon=True).start()
    if http_server is not None:
        threading.Thread(target=http_server.serve_forever, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        dns_server.shutdown()
        dns_server.server_close()
        if http_server is not None:
            http_server.shutdown()
            http_server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
