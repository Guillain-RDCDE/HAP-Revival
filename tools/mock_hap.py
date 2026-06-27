#!/usr/bin/env python3
"""
mock_hap.py — a stand-in Sony HAP-Z1ES, in one stdlib-only file.

The real HAP only answers when it's powered on and on your LAN. This server
impersonates its ScalarWebAPI (port 60200) so you can develop, screenshot, and
demo every HAP-Revival tool — the web UI, the CLI client, the library tools —
with **no hardware connected at all**.

What it gives you:
    - A small, *living* demo library: a 4-track play queue that actually
      advances in real time (the progress bar moves, tracks auto-advance,
      pause/seek/next/previous all work), spanning a 24/96 FLAC, a DSD jazz
      cut, a Red-Book FLAC, and a Spotify-Connect stream — so every code path
      in the UI (hi-res / DSD / lossless / streaming) lights up.
    - Cover art generated on the fly as PNGs (a per-track color gradient), with
      the matching dominant-color RGBA the front panel uses — so the web UI's
      ambient background and accent color come alive.
    - Faithful round-tripping of the proprietary toggles (DSEE, DSD remastering,
      gapless, volume normalize, oversampling), the sleep timer, repeat/shuffle,
      and favorites — set them, read them back, they stick.

It is deliberately read-faithful to the shapes captured from a real device
(see research/captures/ and api-spec/), not a guess.

Run it:
    python tools/mock_hap.py                 # listens on 127.0.0.1:60200
    python tools/mock_hap.py --port 60200 --bind 127.0.0.1

Then point any tool at it as if it were a real HAP:
    python tools/hap_client.py 127.0.0.1 now-playing
    python tools/webui.py 127.0.0.1          # then open http://localhost:8080

(The web UI defaults to device port 60200, which is exactly where this listens,
so it's a drop-in. `webui.py --demo` even starts this server for you.)

Stdlib only. No PIL, no Flask — the PNG covers are hand-encoded with zlib.
"""

from __future__ import annotations

import argparse
import json
import struct
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# ---------------------------------------------------------------------------
# Tiny PNG encoder (so cover art needs no Pillow)
# ---------------------------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def gradient_png(top: tuple[int, int, int], bottom: tuple[int, int, int], size: int = 320) -> bytes:
    """A vertical gradient PNG from `top` to `bottom`, `size`×`size`, RGB.

    Enough to make the now-playing cover and the ambient background look like a
    real album, with zero image dependencies."""
    rows = bytearray()
    for y in range(size):
        f = y / (size - 1)
        r = round(top[0] + (bottom[0] - top[0]) * f)
        g = round(top[1] + (bottom[1] - top[1]) * f)
        b = round(top[2] + (bottom[2] - top[2]) * f)
        rows.append(0)  # PNG filter type 0 (none) for this scanline
        rows.extend((r, g, b) * size)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit, color type 2 (RGB)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _png_chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# Demo library — four tracks that exercise every UI path
# ---------------------------------------------------------------------------


class Track:
    def __init__(
        self,
        track_id: int,
        title: str,
        artist: str,
        album: str,
        composer: str,
        file_name: str,
        codec: str,
        frequency: int,
        bandwidth: int,
        bitrate: int,
        duration: float,
        storage: str,
        accent: tuple[int, int, int],
        streaming: bool = False,
    ):
        self.id = track_id
        self.title = title
        self.artist = artist
        self.album = album
        self.composer = composer
        self.file_name = file_name
        self.codec = codec
        self.frequency = frequency
        self.bandwidth = bandwidth
        self.bitrate = bitrate
        self.duration = duration
        self.storage = storage
        self.accent = accent
        self.streaming = streaming
        self.favorite_type = "normal"
        # An opaque 8-hex cover id, exactly like the device's coverArtUrl scheme.
        self.cover_id = f"{(track_id * 2654435761) & 0xFFFFFFFF:08X}"

    def cover_png(self) -> bytes:
        r, g, b = self.accent
        top = (min(255, r + 40), min(255, g + 40), min(255, b + 40))
        bottom = (max(0, r - 50), max(0, g - 50), max(0, b - 50))
        return gradient_png(top, bottom)


DEMO_TRACKS: list[Track] = [
    Track(
        163756, "Symphony No. 2 — V. Im Tempo des Scherzos", "Gustav Mahler",
        "Mahler: Symphony No. 2 'Resurrection'", "Gustav Mahler",
        "05 - Im Tempo des Scherzos.flac", "flac", 96000, 24, 4608000, 1487.0,
        "storage:internal", (93, 160, 80),
    ),
    Track(
        163902, "So What", "Miles Davis", "Kind of Blue (DSD)", "Miles Davis",
        "01 - So What.dsf", "dsd", 2822400, 1, 5644800, 562.0,
        "storage:internal", (176, 122, 64),
    ),
    Track(
        164120, "Teardrop", "Massive Attack", "Mezzanine", "R. Del Naja",
        "04 - Teardrop.flac", "flac", 44100, 16, 1001000, 330.0,
        "storage:usb1", (66, 110, 180),
    ),
    Track(
        0, "Black Sands", "Bonobo", "Black Sands", "",
        "", "", 0, 0, 0, 245.0, "storage:spotify", (138, 90, 184),
        streaming=True,
    ),
]


# ---------------------------------------------------------------------------
# Mutable device state
# ---------------------------------------------------------------------------


class DeviceState:
    """Everything the fake HAP remembers between calls. Guarded by a lock since
    ThreadingHTTPServer dispatches each request on its own thread."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.power = "active"  # 'active' | 'standby'
        self.index = 0  # current track in DEMO_TRACKS
        self.playing = True
        self._base_pos = 0.0  # position frozen at last pause/seek/track change
        self._since = time.monotonic()  # monotonic stamp of last play resume
        self.sound = {
            "dsee": "auto",
            "dsdRemastering": "off",
            "gaplessPlayback": "auto",
            "volumeNormalization": "off",
            "oversampling": "precision",
        }
        self.sleep_status = "off"
        self.sleep_sec = -1
        self.repeat = {"track": "off", "": "off"}
        self.shuffle = {"track": "off", "": "off"}
        self.buffer_sec = 30

    # ---- playback clock ----

    def _raw_position(self) -> float:
        if self.playing and self.power == "active":
            return self._base_pos + (time.monotonic() - self._since)
        return self._base_pos

    def position(self) -> float:
        """Current position, auto-advancing tracks when one runs out."""
        track = DEMO_TRACKS[self.index]
        pos = self._raw_position()
        # Auto-advance through the queue so a left-running demo keeps moving.
        while pos >= track.duration and self.playing and self.power == "active":
            pos -= track.duration
            self.index = (self.index + 1) % len(DEMO_TRACKS)
            track = DEMO_TRACKS[self.index]
            self._base_pos = pos
            self._since = time.monotonic()
        return min(pos, track.duration)

    def current(self) -> Track:
        return DEMO_TRACKS[self.index]

    def _freeze(self) -> None:
        self._base_pos = self._raw_position()
        self._since = time.monotonic()

    def toggle(self) -> None:
        self._freeze()
        self.playing = not self.playing

    def seek(self, pos: float) -> None:
        self._base_pos = max(0.0, min(pos, self.current().duration))
        self._since = time.monotonic()

    def skip(self, delta: int) -> None:
        self.index = (self.index + delta) % len(DEMO_TRACKS)
        self._base_pos = 0.0
        self._since = time.monotonic()
        self.playing = True

    def play_id(self, track_id: int) -> None:
        for i, tr in enumerate(DEMO_TRACKS):
            if tr.id == track_id:
                self.index = i
                break
        self._base_pos = 0.0
        self._since = time.monotonic()
        self.playing = True


STATE = DeviceState()


# ---------------------------------------------------------------------------
# Response builders (shapes mirror real-device captures)
# ---------------------------------------------------------------------------


def _state_str() -> str:
    if STATE.power != "active":
        return "STOPPED"
    return "PLAYING" if STATE.playing else "PAUSED_PLAYBACK"


def now_playing(host: str) -> dict:
    tr = STATE.current()
    pos = STATE.position()
    state = _state_str()
    if state == "STOPPED":
        return {"state": "STOPPED"}
    cover_url = f"http://{host}/sony/avContent/storage/cover_art/{tr.cover_id}"
    out: dict[str, Any] = {
        "title": tr.title,
        "artist": tr.artist,
        "albumName": tr.album,
        "composer": tr.composer,
        "fileName": tr.file_name,
        "uri": f"audio:track?id={tr.id}" if not tr.streaming else "spotify:track",
        "albumID": f"audio:album?id={tr.id}",
        "playlistUri": "audio:playinglist?id=70",
        "storageUri": tr.storage,
        "durationMsec": int(tr.duration * 1000),
        "positionMsec": int(pos * 1000),
        "durationSec": round(tr.duration, 1),
        "positionSec": round(pos, 1),
        "state": state,
        "shuffleType": STATE.shuffle["track"],
        "repeatType": STATE.repeat["track"],
        "playbackControlMode": "folder",
        "playlistModifiedVersion": 7,
        "favoriteType": tr.favorite_type,
        "listCount": len(DEMO_TRACKS),
        "listIndex": STATE.index + 1,
        "coverArtUrl": cover_url,
        "backgroundColorR": tr.accent[0],
        "backgroundColorG": tr.accent[1],
        "backgroundColorB": tr.accent[2],
        "backgroundColorA": 255,
    }
    if not tr.streaming:
        out["audioInfo"] = [
            {
                "codec": tr.codec,
                "frequency": str(tr.frequency),
                "bandwidth": str(tr.bandwidth),
                "bitrate": str(tr.bitrate),
            }
        ]
        out["audioCodec"] = [tr.codec]
        out["audioFrequency"] = [str(tr.frequency)]
        out["bandwidth"] = str(tr.bandwidth)
        out["bitrate"] = str(tr.bitrate)
    return out


def system_information() -> dict:
    return {
        "product": "HAP",
        "region": "EUR",
        "model": "HAP-Z1ES",
        "generation": "1.0",
        "serial": "MOCK-0000001",
        "macAddr": "04:5d:4b:de:ad:be",
        "name": "HAP-Z1ES (mock)",
        "version": "0019404R",
        "language": "eng",
        "cid": "HAP",
        "area": "EUR",
    }


def sound_settings() -> list[dict]:
    return [{"target": k, "currentValue": v, "type": "enumTarget"} for k, v in STATE.sound.items()]


def sleep_timer() -> dict:
    return {
        "status": STATE.sleep_status,
        "remainTimerSec": STATE.sleep_sec if STATE.sleep_status == "on" else -1,
        "sleepTimerSec": STATE.sleep_sec,
        "candidateStatus": ["on", "off"],
        "candidateSec": [600, 1200, 1800, 2400, 3000, 3600, 5400, 7200],
    }


def volume_information() -> dict:
    # HAP-Z1ES has no internal amp: the device forces these sentinel values.
    return {"target": "speaker", "volume": -1, "mute": "toggle", "maxVolume": -1, "minVolume": -1, "step": 1}


def storage_list() -> list[dict]:
    return [
        {"uri": "storage:internal", "deviceName": "Internal HDD", "isAvailable": True,
         "freeCapacityMB": 248320, "wholeCapacityMB": 953869, "systemAreaCapacityMB": 0,
         "formattable": "unavailable", "mounted": True, "permission": "rw"},
        {"uri": "storage:usb1", "deviceName": "USB Drive", "isAvailable": True,
         "freeCapacityMB": 102400, "wholeCapacityMB": 512000, "systemAreaCapacityMB": 0,
         "formattable": "unavailable", "mounted": True, "permission": "rw"},
    ]


def content_info(track_id: int, host: str) -> dict:
    for tr in DEMO_TRACKS:
        if tr.id == track_id:
            return {
                "title": tr.title,
                "uri": f"audio:track?id={tr.id}",
                "coverArtUrl": f"http://{host}/sony/avContent/storage/cover_art/{tr.cover_id}",
                "backgroundColorR": tr.accent[0],
                "backgroundColorG": tr.accent[1],
                "backgroundColorB": tr.accent[2],
                "backgroundColorA": 255,
            }
    return {"title": "", "uri": f"audio:track?id={track_id}"}


# A sentinel telling the dispatcher to answer with `result: []` (Sony's reply
# shape for state-changing setters).
EMPTY: object = object()


def dispatch(service: str, method: str, version: str, params: list, host: str) -> Any:
    """Map (service, method) → the *unwrapped* result value. The handler wraps
    it back into `{"id":…, "result":[value]}` (or `result: []` for EMPTY)."""
    p0 = params[0] if params and isinstance(params[0], dict) else {}
    with STATE.lock:
        # ---- system ----
        if service == "system" and method == "getSystemInformation":
            return system_information()
        if service == "system" and method == "getPowerStatus":
            return {"status": STATE.power, "standbyDetail": ""}
        if service == "system" and method == "setPowerStatus":
            status = p0.get("status", "active")
            STATE.power = "standby" if status in ("off", "standby") else "active"
            if status == "play":
                STATE.playing = True
                STATE._since = time.monotonic()
            return EMPTY
        if service == "system" and method == "getSleepTimer":
            return sleep_timer()
        if service == "system" and method == "setSleepTimer":
            STATE.sleep_status = p0.get("status", "off")
            STATE.sleep_sec = int(p0.get("sleepTimerSec", -1))
            return EMPTY
        if service == "system" and method == "getStorageList":
            return storage_list()

        # ---- audio ----
        if service == "audio" and method == "getSoundSettings":
            return sound_settings()
        if service == "audio" and method == "setSoundSettings":
            for s in p0.get("settings", []):
                tgt, val = s.get("target"), s.get("value")
                if tgt in STATE.sound:
                    STATE.sound[tgt] = val
            return EMPTY
        if service == "audio" and method == "getVolumeInformation":
            return volume_information()
        if service == "audio" and method in ("setAudioVolume", "setAudioMute"):
            return EMPTY

        # ---- avContent ----
        if service == "avContent" and method == "getPlayingContentInfo":
            return now_playing(host)
        if service == "avContent" and method == "pausePlayingContent":
            STATE.toggle()
            return EMPTY
        if service == "avContent" and method == "setPlayContent":
            if "positionSec" in p0:
                STATE.seek(float(p0["positionSec"]))
            return EMPTY
        if service == "avContent" and method == "setPlayNextContent":
            STATE.skip(+1)
            return EMPTY
        if service == "avContent" and method == "setPlayPreviousContent":
            STATE.skip(-1)
            return EMPTY
        if service == "avContent" and method == "createPlayingListAndQuickPlay":
            uri = p0.get("uri", "")
            if uri.startswith("audio:track?id="):
                try:
                    STATE.play_id(int(uri.split("=", 1)[1]))
                except ValueError:
                    pass
            return {"uri": "audio:playinglist?id=70"}
        if service == "avContent" and method == "getContentInfo":
            uri = p0.get("uri", "")
            tid = int(uri.split("=", 1)[1]) if "=" in uri else -1
            return content_info(tid, host)
        if service == "avContent" and method == "getBufferTime":
            return {"bufferTimeSec": STATE.buffer_sec, "candidateSec": [15, 30, 60, 180]}
        if service == "avContent" and method == "setBufferTime":
            STATE.buffer_sec = int(p0.get("bufferTimeSec", 30))
            return EMPTY
        if service == "avContent" and method == "getRepeatType":
            tgt = p0.get("target", "track")
            return {"type": STATE.repeat.get("track" if tgt in ("track", "audio") else "", "off")}
        if service == "avContent" and method == "setRepeatType":
            tgt = p0.get("target", "track")
            STATE.repeat["track" if tgt in ("track", "audio") else ""] = p0.get("type", "off")
            return EMPTY
        if service == "avContent" and method == "getShuffleType":
            tgt = p0.get("target", "track")
            return {"type": STATE.shuffle.get("track" if tgt in ("track", "audio") else "", "off")}
        if service == "avContent" and method == "setShuffleType":
            tgt = p0.get("target", "track")
            STATE.shuffle["track" if tgt in ("track", "audio") else ""] = p0.get("type", "off")
            return EMPTY
        if service == "avContent" and method == "editContentInfo":
            for target in p0.get("target", []):
                uri = target.get("uri", "")
                if target.get("tagUri") == "meta:favorite" and "=" in uri:
                    try:
                        tid = int(uri.split("=", 1)[1])
                    except ValueError:
                        continue
                    for tr in DEMO_TRACKS:
                        if tr.id == tid:
                            tr.favorite_type = target.get("value", "normal")
            return EMPTY

    # Unknown method → Sony's generic error tuple.
    raise KeyError(f"{service}.{method}/v{version}")


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class MockHandler(BaseHTTPRequestHandler):
    quiet: bool = True

    def log_message(self, fmt: str, *args: Any) -> None:
        if not self.quiet:
            super().log_message(fmt, *args)

    def _host(self) -> str:
        return self.headers.get("Host") or f"{self.server.server_address[0]}:{self.server.server_address[1]}"

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        # Cover art: /sony/avContent/storage/cover_art/<8-hex-id>
        if "/cover_art/" in self.path:
            cid = self.path.rsplit("/", 1)[-1].split("?", 1)[0]
            for tr in DEMO_TRACKS:
                if tr.cover_id == cid:
                    self._send(200, "image/png", tr.cover_png())
                    return
            # Unknown id → still return *a* cover so the UI never shows a hole.
            self._send(200, "image/png", DEMO_TRACKS[0].cover_png())
            return
        if self.path.rstrip("/") in ("", "/", "/sony"):
            banner = (
                "mock_hap — a fake Sony HAP-Z1ES. POST JSON-RPC to "
                "/sony/<service>. See tools/mock_hap.py.\n"
            ).encode("utf-8")
            self._send(200, "text/plain; charset=utf-8", banner)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not self.path.startswith("/sony/"):
            self.send_error(404)
            return
        service = self.path[len("/sony/"):].split("?", 1)[0].strip("/")
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            req = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send(400, "application/json", b'{"error":[3,"Illegal JSON"]}')
            return

        method = req.get("method", "")
        version = req.get("version", "1.0")
        rid = req.get("id", 1)
        params = req.get("params", []) or []

        try:
            value = dispatch(service, method, version, params, self._host())
        except KeyError:
            # Sony's "unsupported method/version" shape.
            body = json.dumps({"id": rid, "error": [12, "No Such Method"]}).encode("utf-8")
            self._send(200, "application/json", body)
            return
        except Exception as e:  # noqa: BLE001 — a mock should never 500 the client
            body = json.dumps({"id": rid, "error": [1, f"mock error: {e}"]}).encode("utf-8")
            self._send(200, "application/json", body)
            return

        result = [] if value is EMPTY else [value]
        body = json.dumps({"id": rid, "result": result}, ensure_ascii=False).encode("utf-8")
        self._send(200, "application/json", body)


def make_server(bind: str = "127.0.0.1", port: int = 60200, quiet: bool = True) -> ThreadingHTTPServer:
    MockHandler.quiet = quiet
    return ThreadingHTTPServer((bind, port), MockHandler)


def serve_in_thread(bind: str = "127.0.0.1", port: int = 60200) -> ThreadingHTTPServer:
    """Start the mock on a daemon thread and return the server (for `webui --demo`)."""
    server = make_server(bind, port, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=60200, help="Listen port (default 60200, the real HAP port)")
    parser.add_argument("--bind", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    parser.add_argument("--verbose", action="store_true", help="Log each request")
    args = parser.parse_args()

    server = make_server(args.bind, args.port, quiet=not args.verbose)
    print(f"mock HAP-Z1ES listening on http://{args.bind}:{args.port}/sony/")
    print("Point any tool at it, e.g.:")
    print(f"    python tools/hap_client.py {args.bind} now-playing")
    print(f"    python tools/webui.py {args.bind}")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
