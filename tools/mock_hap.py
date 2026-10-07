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
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import hap_update

from hap_common import API_PORT
from hap_png import COLOR_RGB, encode_png, lerp_rgb
from hap_screen import KEYS as KEYEVENTS

# ---------------------------------------------------------------------------
# Cover art (the shared stdlib PNG encoder, so no Pillow)
# ---------------------------------------------------------------------------


def gradient_png(top: tuple[int, int, int], bottom: tuple[int, int, int], size: int = 320,
                 height: int | None = None) -> bytes:
    """A vertical gradient PNG from `top` to `bottom`, `size`×`height`, RGB.

    Square by default, which is what a cover wants. `height` makes it oblong —
    the front panel is 480×272, and a client that crops or scales the display
    should meet the real aspect ratio here too.

    Enough to make the now-playing cover and the ambient background look like a
    real album, with zero image dependencies."""
    height = size if height is None else height
    pixels = bytearray()
    for y in range(height):
        pixels.extend(lerp_rgb(top, bottom, y / max(1, height - 1)) * size)
    return encode_png(size, height, bytes(pixels), color_type=COLOR_RGB)


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


CONTENTDB_BASE = "/sony/contentdb/v100"
# The front-panel keys the mock accepts are exactly the ones hap_screen knows
# (the nine from the player's own /haplib.js plus `next` and `prev`).


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
# The REST library API (/sony/contentdb/v100)
# ---------------------------------------------------------------------------
#
# Shapes copied from a real 19404R player, 2026-08-29. What matters for anything
# built on top: every collection is wrapped under its own plural key alongside a
# `paging` object, a single-object lookup reuses that same plural key with one
# element — except `genres/{id}`, which answers with a singular `genre` instead.
# That inconsistency is the device's, not ours, and clients have to handle it.
#
# The streaming demo track is excluded: Spotify Connect content is not in the
# player's library database, so it must not appear here either.


def _library_tracks() -> list[Track]:
    return [t for t in DEMO_TRACKS if not t.streaming]


def _distinct(attr: str) -> list[str]:
    """Unique values in first-seen order, so ids stay stable across calls."""
    seen: list[str] = []
    for t in _library_tracks():
        value = getattr(t, attr)
        if value and value not in seen:
            seen.append(value)
    return seen


def _artist_id(name: str) -> int:
    return _distinct("artist").index(name) + 1


def _album_id(name: str) -> int:
    return _distinct("album").index(name) + 1


def _track_json(t: Track, host: str) -> dict:
    base = f"http://{host}{CONTENTDB_BASE}"
    return {
        "trackid": t.id,
        "name": t.title,
        "filename": t.file_name,
        "filepath": "",
        "url": f"{base}/audio/tracks/{t.id}",
        "duration": int(t.duration),
        "track_number": 1,
        "disk_number": 1,
        "release_date": "2014",
        "number_of_plays": 0,
        "favorite_type": t.favorite_type,
        "playable": "true",
        "codec": {
            "codec_type": t.codec,
            "sample_rate": t.frequency,
            "bit_width": t.bandwidth,
            "bit_rate": t.bitrate,
        },
        "artist": {
            "artistid": _artist_id(t.artist),
            "name": t.artist,
            "url": f"{base}/audio/artists/{_artist_id(t.artist)}",
        },
        "album": {
            "albumid": _album_id(t.album),
            "name": t.album,
            "url": f"{base}/audio/albums/{_album_id(t.album)}",
            "release_date": "2014",
            "number_of_tracks": 1,
            "duration": int(t.duration),
            "album_artist": {"name": t.artist},
            "image": {
                "url": f"{base}/audio/albums/images/cover_art/{t.cover_id}"
            },
        },
        "genre": {"genreid": 1, "name": "Demo", "url": f"{base}/audio/genres/1"},
    }


def _album_json(name: str, host: str) -> dict:
    base = f"http://{host}{CONTENTDB_BASE}"
    tracks = [t for t in _library_tracks() if t.album == name]
    aid = _album_id(name)
    return {
        "albumid": aid,
        "name": name,
        "url": f"{base}/audio/albums/{aid}",
        "tracks_url": f"{base}/audio/albums/{aid}/tracks",
        "release_date": "2014",
        "number_of_tracks": len(tracks),
        "duration": int(sum(t.duration for t in tracks)),
        "album_artist": {"name": tracks[0].artist if tracks else ""},
        "image": {
            "url": f"{base}/audio/albums/images/cover_art/"
            f"{tracks[0].cover_id if tracks else '00000000'}"
        },
    }


def _artist_json(name: str, host: str) -> dict:
    base = f"http://{host}{CONTENTDB_BASE}"
    aid = _artist_id(name)
    return {
        "artistid": aid,
        "name": name,
        "url": f"{base}/audio/artists/{aid}",
        "number_of_tracks": len([t for t in _library_tracks() if t.artist == name]),
    }


def _page(items: list[dict], key: str, query: dict, host: str, path: str) -> dict:
    """Wrap a collection the way the device does, paging object included."""
    try:
        offset = max(0, int(query.get("offset", ["0"])[0]))
        limit = int(query.get("limit", ["200"])[0])
    except (TypeError, ValueError):
        offset, limit = 0, 200
    window = items[offset : offset + limit]
    base = f"http://{host}{CONTENTDB_BASE}/{path}"
    has_next = offset + limit < len(items)
    return {
        key: window,
        "request": f"{base}?offset={offset}&limit={limit}",
        "paging": {
            "offset": offset,
            "limit": limit,
            "total": len(items),
            "next": f"{base}?offset={offset + limit}&limit={limit}" if has_next else "",
            "previous": (
                f"{base}?offset={max(0, offset - limit)}&limit={limit}" if offset else ""
            ),
        },
    }


def contentdb_get(path: str, query: dict, host: str) -> dict | None:
    """Route one GET under /sony/contentdb/v100. None means 404."""
    parts = [p for p in path.split("/") if p]
    tracks = _library_tracks()

    # Anything above the device's ceiling is a 400 there; mirror the refusal so
    # a client that forgets the cap fails the same way here.
    try:
        if int(query.get("limit", ["200"])[0]) > 5000:
            return None
    except (TypeError, ValueError):
        pass

    if parts == ["audio", "tracks"]:
        return _page([_track_json(t, host) for t in tracks], "tracks", query, host, path)
    if parts == ["audio", "albums"]:
        return _page(
            [_album_json(n, host) for n in _distinct("album")], "albums", query, host, path
        )
    if parts == ["audio", "artists"]:
        return _page(
            [_artist_json(n, host) for n in _distinct("artist")],
            "artists",
            query,
            host,
            path,
        )
    if parts == ["audio", "genres"]:
        genre = {
            "genreid": 1,
            "name": "Demo",
            "number_of_tracks": len(tracks),
            "url": f"http://{host}{CONTENTDB_BASE}/audio/genres/1",
        }
        return _page([genre], "genres", query, host, path)
    if parts == ["audio", "playlists"]:
        return _page([], "playlists", query, host, path)
    if parts in (["services", "favorite"], ["services", "favorite", "tracks"]):
        favs = [t for t in tracks if t.favorite_type == "favorite"]
        return _page([_track_json(t, host) for t in favs], "tracks", query, host, path)

    # An unknown id on a known route is `200 {}` on the real device, not a 404
    # (verified 2026-08-29). A client therefore cannot tell "no such track" from
    # a transport problem by status code alone — it has to look at the body.
    if len(parts) == 3 and parts[:2] == ["audio", "tracks"] and parts[2].isdigit():
        match = [t for t in tracks if t.id == int(parts[2])]
        return {"tracks": [_track_json(t, host) for t in match]} if match else {}
    if len(parts) == 3 and parts[:2] == ["audio", "albums"] and parts[2].isdigit():
        names = [n for n in _distinct("album") if _album_id(n) == int(parts[2])]
        return {"albums": [_album_json(n, host) for n in names]} if names else {}
    if len(parts) == 3 and parts[:2] == ["audio", "artists"] and parts[2].isdigit():
        names = [n for n in _distinct("artist") if _artist_id(n) == int(parts[2])]
        return {"artists": [_artist_json(n, host) for n in names]} if names else {}
    if len(parts) == 3 and parts[:2] == ["audio", "genres"] and parts[2].isdigit():
        if parts[2] != "1":
            return {}
        # Singular `genre`, matching the device. Not a typo here either.
        return {
            "genre": {
                "genreid": 1,
                "name": "Demo",
                "number_of_tracks": len(tracks),
                "url": f"http://{host}{CONTENTDB_BASE}/audio/genres/1",
            }
        }

    if len(parts) == 4 and parts[:2] == ["audio", "albums"] and parts[3] == "tracks":
        names = [n for n in _distinct("album") if _album_id(n) == int(parts[2])]
        if not names:
            return None
        rows = [_track_json(t, host) for t in tracks if t.album == names[0]]
        return _page(rows, "tracks", query, host, path)
    if len(parts) == 4 and parts[:2] == ["audio", "artists"] and parts[3] == "albums":
        names = [n for n in _distinct("artist") if _artist_id(n) == int(parts[2])]
        if not names:
            return None
        albums = [
            _album_json(a, host)
            for a in _distinct("album")
            if any(t.album == a and t.artist == names[0] for t in tracks)
        ]
        return _page(albums, "albums", query, host, path)

    return None


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
        # UDP push subscribers: (ip, port) -> expiry. The real player keeps a
        # subscription for `timeout` seconds and sends every event three times.
        self.subscribers: dict[tuple[str, int], float] = {}
        self.seq = 0
        # TuneIn account link. Stations play either way; this only ever synced favourites.
        self.radio_registered = False

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
# Push notifications (/sony/notification/status + NOTIFY datagrams)
# ---------------------------------------------------------------------------
#
# Shapes from a real 19404R capture (research/notes/2026-08-20-crestron-module-
# teardown.md): a POST subscribes a (client ip, port) for `timeout` seconds, then
# every change goes out as a pseudo-HTTP datagram, three times under one SEQ.

NOTIFY_TIMEOUT_SEC = 300
NOTIFY_REPEATS = 3
HOST_UUID = "uuid:00000000-0000-1010-8000-104FA86F4B84"
CONTENTPLAYER_BASE = "/sony/contentplayer/v100"

#: Which event a state-changing JSON-RPC method produces, and where to read back.
EVENT_FOR_METHOD = {
    "pausePlayingContent": ("playinginfoChanged", "playinginfo"),
    "setPlayContent": ("playinginfoChanged", "playinginfo"),
    "setPlayNextContent": ("playingtrackChanged", "playinginfo"),
    "setPlayPreviousContent": ("playingtrackChanged", "playinginfo"),
    "createPlayingListAndQuickPlay": ("playqueueChanged", "playqueue"),
    "setPowerStatus": ("powerstateChanged", "powerstate"),
    "setAudioVolume": ("volumeChanged", "volumelevel"),
    "setAudioMute": ("volumeChanged", "volumelevel"),
}


def subscribe(ip: str, port: int) -> dict:
    """Arm (or re-arm) a subscriber. Returns the reply the player sends."""
    with STATE.lock:
        STATE.subscribers[(ip, int(port))] = time.monotonic() + NOTIFY_TIMEOUT_SEC
    return {"timeout": NOTIFY_TIMEOUT_SEC, "port": int(port)}


def notify_datagram(event: str, readback: str, host: str, seq: int) -> bytes:
    body = json.dumps({"event": event, "url": f"http://{host}{CONTENTPLAYER_BASE}/{readback}"})
    head = (
        "NOTIFY * HTTP/1.1\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Content-Type: application/json\r\n"
        f"SEQ: {seq}\r\n"
        f"X-ContentServiceHostUUID: {HOST_UUID}\r\n\r\n"
    )
    return head.encode("utf-8") + body.encode("utf-8")


def push_event(method: str, host: str) -> int:
    """Send the event `method` causes to every live subscriber. Returns the SEQ used, or 0."""
    hit = EVENT_FOR_METHOD.get(method)
    if hit is None:
        return 0
    event, readback = hit
    now = time.monotonic()
    with STATE.lock:
        STATE.subscribers = {k: v for k, v in STATE.subscribers.items() if v > now}
        targets = list(STATE.subscribers)
        if not targets:
            return 0
        STATE.seq += 1
        seq = STATE.seq
    datagram = notify_datagram(event, readback, host, seq)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for target in targets:
            for _ in range(NOTIFY_REPEATS):
                try:
                    sock.sendto(datagram, target)
                except OSError:
                    break
    finally:
        sock.close()
    return seq


def contentplayer_get(path: str) -> tuple[int, dict]:
    """The small REST surface the push events point at. (status, body)."""
    parts = [p for p in path.split("/") if p]
    with STATE.lock:
        if parts == ["powerstate"]:
            return 200, {"power_state": "on" if STATE.power == "active" else "standby"}
        if parts == ["playinginfo"]:
            info = now_playing("mock")
            return 200, {"state": info.get("state"), "title": info.get("title", ""),
                         "artist": info.get("artist", ""),
                         "position_sec": info.get("positionSec", 0)}
        if parts == ["playqueue"]:
            return 200, {"queue": [{"trackid": t.id, "name": t.title} for t in DEMO_TRACKS],
                         "index": STATE.index}
        if parts == ["volumelevel"]:
            # A Z1ES has no volume stage: the real one answers 500 here.
            return 500, {"error_code": 500, "description": "Internal Server Error"}
        if len(parts) == 3 and parts[:2] == ["settings", "sound"] and parts[2] in STATE.sound:
            return 200, {"setting": {"target": parts[2], "value": STATE.sound[parts[2]]}}
    return 404, {"error_code": 404, "description": "Not Found"}


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
    return {"target": "speaker", "volume": -1, "mute": "toggle",
            "maxVolume": -1, "minVolume": -1, "step": 1}


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

# ---------------------------------------------------------------------------
# Internet radio (TuneIn): registration state and a two-level browse tree
# ---------------------------------------------------------------------------
#
# Shapes from research/api-method-catalog.md. The tree is deliberately tiny and
# locale-free; the real one depends on the player's region, which is the whole
# point of `radio_browse` returning ready-made uris.

TUNEIN_URI = "netService:audio?serviceName=tunein"
RADIO_PIN = "SW94LN"
RADIO_TREE: dict[str, list[dict]] = {
    "/": [
        {"path": "/1", "title": "Local Radio", "isBrowsable": True, "isPlayable": False},
        {"path": "/2", "title": "Music", "isBrowsable": True, "isPlayable": False},
    ],
    "/1": [
        {"path": "/1/1", "title": "FIP", "isBrowsable": False, "isPlayable": True,
         "uri": f"{TUNEIN_URI}&path=/1/1&id=s50706"},
        {"path": "/1/2", "title": "Radio Paradise", "isBrowsable": False, "isPlayable": True,
         "uri": f"{TUNEIN_URI}&path=/1/2&id=s13606"},
    ],
    "/2": [],
}


def radio_browse(uri: str) -> list[list[dict]]:
    """getContentList on a netService uri: the items, wrapped once more like the device."""
    path = urllib.parse.parse_qs(uri.partition("?")[2]).get("path", ["/"])[0] or "/"
    return [RADIO_TREE.get(path, [])]


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
        if service == "avContent" and method == "registerDevice":
            how = p0.get("method", "check")
            if how == "check":
                return {"isRegistered": STATE.radio_registered}
            if how == "getPin":
                return {"pinCode": RADIO_PIN}
            if how == "unregister":
                STATE.radio_registered = False
                return EMPTY
            raise KeyError(f"registerDevice/{how}")
        if service == "avContent" and method == "getContentList":
            uri = p0.get("uri", "")
            if not uri.startswith("netService:"):
                raise KeyError("getContentList is netService-only on this player")
            return radio_browse(uri)
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
    # HTTP/1.1, like the player: it is what makes `Expect: 100-continue` reach
    # handle_expect_100 at all (http.server ignores it on HTTP/1.0).
    protocol_version = "HTTP/1.1"
    quiet: bool = True

    def log_message(self, fmt: str, *args: Any) -> None:
        if not self.quiet:
            super().log_message(fmt, *args)

    def _host(self) -> str:
        host, port = self.server.server_address[:2]
        return self.headers.get("Host") or f"{host}:{port}"

    def _send(self, status: int, content_type: str, body: bytes,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(status, "application/json", json.dumps(payload, ensure_ascii=False).encode())

    def handle_expect_100(self) -> bool:
        # Gotcha 2 (docs/16-gotchas.md): the player answers 417 to
        # `Expect: 100-continue` instead of continuing. So does this.
        self.send_error(417, "Expectation Failed")
        return False

    def do_OPTIONS(self) -> None:
        # Gotcha 1: the preflight echoes the Origin but never sends
        # Access-Control-Allow-Headers, so a browser cannot add Content-Type.
        extra = {"Access-Control-Allow-Methods": "GET, POST, OPTIONS"}
        origin = self.headers.get("Origin")
        if origin:
            extra["Access-Control-Allow-Origin"] = origin
        self._send(200, "text/plain", b"", extra)

    def do_GET(self) -> None:
        # The push readback surface: /sony/contentplayer/v100/...
        if self.path.startswith(CONTENTPLAYER_BASE):
            rest = self.path[len(CONTENTPLAYER_BASE):].partition("?")[0]
            status, payload = contentplayer_get(rest)
            self._send_json(status, payload)
            return

        # The front panel: /sony/hap?target=…&cmd=…
        if self.path.startswith("/sony/hap"):
            query = urllib.parse.parse_qs(self.path.partition("?")[2])
            target = (query.get("target") or [""])[0]
            cmd = (query.get("cmd") or [""])[0]
            if target == "screen" and cmd in ("display_png", "download_png"):
                # 480×272, the real panel's size, tinted by what is playing so a
                # client can see the picture change.
                tr = STATE.current()
                self._send(200, "image/png",
                           gradient_png(tr.accent, (12, 12, 16), size=480, height=272))
                return
            if target == "screen" and cmd == "capture_png":
                self._send(200, "text/plain", b"None")
                return
            if target == "keyevent" and cmd in KEYEVENTS:
                self._send(200, "text/plain", b"None")
                return
            # The device answers 200 "None" for a key it does not know, so an
            # unknown *target* is the only 404 here.
            self.send_error(404)
            return

        # The REST library API: /sony/contentdb/v100/...
        if self.path.startswith(CONTENTDB_BASE):
            rest = self.path[len(CONTENTDB_BASE):]
            path, _, query = rest.partition("?")
            payload = contentdb_get(path.strip("/"), urllib.parse.parse_qs(query), self._host())
            if payload is None:
                body = json.dumps({"error_code": 404, "description": "Not Found"})
                self._send(404, "application/json", body.encode("utf-8"))
                return
            self._send(
                200,
                "application/json",
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
            return

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
            ).encode()
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

        # Push subscription: not JSON-RPC, a plain {"status": "enable", "port": N}.
        if service == "notification/status":
            if not isinstance(req, dict) or req.get("status") != "enable":
                self._send_json(400, {"error_code": 400, "description": "Bad Request"})
                return
            try:
                port = int(req.get("port", 0))
            except (TypeError, ValueError):
                port = 0
            if not 0 < port < 65536:
                self._send_json(400, {"error_code": 400, "description": "Bad Request"})
                return
            self._send_json(200, subscribe(self.client_address[0], port))
            return
        if not isinstance(req, dict):
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
        except Exception as e:
            body = json.dumps({"id": rid, "error": [1, f"mock error: {e}"]}).encode("utf-8")
            self._send(200, "application/json", body)
            return

        result = [] if value is EMPTY else [value]
        body = json.dumps({"id": rid, "result": result}, ensure_ascii=False).encode("utf-8")
        self._send(200, "application/json", body)
        push_event(method, self._host())


def make_server(
    bind: str = "127.0.0.1", port: int = API_PORT, quiet: bool = True
) -> ThreadingHTTPServer:
    MockHandler.quiet = quiet
    return ThreadingHTTPServer((bind, port), MockHandler)


def serve_in_thread(bind: str = "127.0.0.1", port: int = API_PORT) -> ThreadingHTTPServer:
    """Start the mock on a daemon thread and return the server (for `webui --demo`)."""
    server = make_server(bind, port, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    hap_update.add_version_flag(parser)
    parser.add_argument("--port", type=int, default=API_PORT,
                        help=f"Listen port (default {API_PORT}, the real HAP port)")
    parser.add_argument("--bind", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    parser.add_argument("--verbose", action="store_true", help="Log each request")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
