#!/usr/bin/env python3
"""
HAP-Revival client library — a clean abstraction over the Sony HAP-Z1ES /
HAP-S1 ScalarWebAPI on port 60200.

Encodes everything we've verified to work live against a HAP-Z1ES on
firmware 19404R. Stdlib-only (no `requests` dependency).

Library usage:
    from hap_client import HAP, NowPlaying

    hap = HAP("192.168.1.28")
    np = hap.now_playing()
    print(f"{np.artist} — {np.title}  [{np.position_sec:.0f}/{np.duration_sec:.0f}s]")

    hap.pause()
    hap.resume()
    hap.seek_seconds(45.0)
    hap.play_track(163756)

    info = hap.system_info()
    print(f"{info.model} firmware {info.version}")

CLI usage:
    python tools/hap_client.py <ip> now-playing
    python tools/hap_client.py <ip> pause
    python tools/hap_client.py <ip> resume
    python tools/hap_client.py <ip> seek 45
    python tools/hap_client.py <ip> play-track 163756
    python tools/hap_client.py <ip> system

Read-only methods are completely safe. State-changing methods affect
the device — read the docstrings before calling.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:  # local sibling module; keep the client importable even if it's absent
    import i18n
except ImportError:  # pragma: no cover
    i18n = None  # type: ignore[assignment]

# Active CLI language, resolved once in main(); None until then.
_LANG: str | None = None


def _t(key: str, **kwargs: object) -> str:
    """Translate a CLI string. Degrades to the key if i18n.py is unavailable."""
    if i18n is None:
        return key
    return i18n.t(key, _LANG, **kwargs)


# ---------- Data classes ----------


@dataclass
class SystemInfo:
    """Output of system.getSystemInformation v1.2."""

    model: str
    name: str
    product: str
    version: str  # firmware version e.g. "0019404R"
    generation: str
    mac: str
    language: str
    cid: str
    area: str
    region: str
    serial: str


@dataclass
class NowPlaying:
    """Output of avContent.getPlayingContentInfo v1.2 — the rich now-playing state."""

    state: str  # device wire values: "PLAYING" | "PAUSED_PLAYBACK" | "STOPPED" | "NO_MEDIA_PRESENT"
    #            (note: paused is "PAUSED_PLAYBACK", not "PAUSED" — verified live 2026-06-03)
    title: str = ""
    artist: str = ""
    album: str = ""
    composer: str = ""
    file_name: str = ""
    uri: str = ""  # e.g. "audio:track?id=163756"
    album_uri: str = ""
    playlist_uri: str = ""
    storage_uri: str = ""  # e.g. "storage:usb1" or "storage:internal"
    position_sec: float = 0.0
    duration_sec: float = 0.0
    codec: str = ""
    sample_rate_hz: int = 0
    bit_depth: int = 0
    bitrate: int = 0
    cover_art_url: str = ""
    background_color_rgba: tuple[int, int, int, int] | None = None
    shuffle_type: str = ""
    repeat_type: str = ""
    playback_control_mode: str = ""
    playlist_modified_version: int = 0
    list_index: int = 0
    list_count: int = 0
    favorite_type: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def progress(self) -> float:
        """Playback progress as 0.0–1.0 (or 0.0 if duration unknown)."""
        if self.duration_sec <= 0:
            return 0.0
        return min(1.0, max(0.0, self.position_sec / self.duration_sec))

    @property
    def is_playing(self) -> bool:
        return self.state == "PLAYING"


@dataclass
class SoundSettings:
    """Output of audio.getSoundSettings v1.1."""

    dsee: str = ""  # "auto" | "off"
    dsd_remastering: str = ""  # "on" | "off"
    gapless_playback: str = ""  # "auto" | "off"
    volume_normalization: str = ""  # "auto" | "off"
    oversampling: str = ""  # "precision" | "normal"
    raw: dict = field(default_factory=dict)


@dataclass
class SleepTimer:
    """Output of system.getSleepTimer v1.0."""

    status: str  # "on" | "off"
    remain_sec: int
    sleep_sec: int
    candidate_sec: list[int]


# ---------- The transport ----------


class HAPError(Exception):
    """Base for HAP client errors."""


class HAPMethodError(HAPError):
    """Server returned a JSON-RPC error."""

    def __init__(self, code: int, message: str, method: str, version: str):
        super().__init__(f"{method}/v{version}: [{code}, {message!r}]")
        self.code = code
        self.message = message
        self.method = method
        self.version = version


class HAPTransportError(HAPError):
    """HTTP / socket-level error."""


DEFAULT_CLIENT_ID = "HAP-Revival:0.1:python_client"


def _first_field(reply: Any, key: str, default: Any = None) -> Any:
    """Read `key` out of whatever shape a call came back in.

    `HAP.call` unwraps a single-element `result` list, so the normal case is a
    plain dict. This also tolerates the wrapped and plural forms rather than
    silently returning the default when the device surprises us.
    """
    if isinstance(reply, dict):
        if key in reply:
            return reply[key]
        for wrapper in ("result", "results"):
            entries = reply.get(wrapper)
            if isinstance(entries, list) and entries and isinstance(entries[0], dict):
                return entries[0].get(key, default)
    elif isinstance(reply, list) and reply and isinstance(reply[0], dict):
        return reply[0].get(key, default)
    return default


class HAP:
    """A connection to one Sony HAP-Z1ES or HAP-S1 device on the LAN."""

    def __init__(
        self,
        ip: str,
        port: int = 60200,
        timeout: float = 6.0,
        client_id: str = DEFAULT_CLIENT_ID,
    ):
        """
        Args:
            ip: device IP address on the local network
            port: ScalarWebAPI port (always 60200 on HAP-Z1ES firmware 19404R)
            timeout: per-request HTTP timeout in seconds
            client_id: value sent in the `x-hap-device-id` header. Sony's
                Android client format is `Android:<os>:<app_ver>:<yyyymmddHHMMSS>_<mac>`
                — we send a stable identifier instead. Optional on most calls
                but required by some database-service methods (per APK).
        """
        if not ip:
            raise ValueError("ip is required")
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.client_id = client_id
        self._base = f"http://{ip}:{port}/sony"

    # ---- Raw JSON-RPC ----

    def call(
        self,
        service: str,
        method: str,
        version: str,
        params: list | None = None,
    ) -> Any:
        """Make a raw JSON-RPC call. Returns the `result` field unwrapped from
        its outer list (since the HAP always wraps result in a 1-element list).

        Raises HAPMethodError on a `error` field, HAPTransportError on HTTP /
        network failure.
        """
        params = params if params is not None else []
        url = f"{self._base}/{service}"
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
                "x-hap-device-id": self.client_id,
            },
        )
        try:
            with urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            raise HAPTransportError(f"HTTP {e.code}: {e.reason} on {url}") from e
        except (URLError, socket.timeout) as e:
            raise HAPTransportError(f"{e} on {url}") from e

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HAPTransportError(f"non-JSON response from {url}: {raw[:200]}") from e

        if "error" in data:
            err = data["error"]
            if isinstance(err, list) and len(err) >= 2:
                raise HAPMethodError(err[0], err[1], method, version)
            raise HAPMethodError(-1, str(err), method, version)

        result = data.get("result", [])
        if isinstance(result, list) and len(result) == 1:
            return result[0]
        return result

    # ---- system ----

    def system_info(self) -> SystemInfo:
        r = self.call("system", "getSystemInformation", "1.2")
        return SystemInfo(
            model=r.get("model", ""),
            name=r.get("name", ""),
            product=r.get("product", ""),
            version=r.get("version", ""),
            generation=r.get("generation", ""),
            mac=r.get("macAddr", ""),
            language=r.get("language", ""),
            cid=r.get("cid", ""),
            area=r.get("area", ""),
            region=r.get("region", ""),
            serial=r.get("serial", ""),
        )

    def power_status(self) -> str:
        """Returns 'active' or 'standby' or other state strings."""
        r = self.call("system", "getPowerStatus", "1.1")
        return r.get("status", "")

    def wake_and_play(self) -> None:
        """setPowerStatus({status:'play'}) — wakes the device and resumes playback."""
        self.call("system", "setPowerStatus", "1.1", [{"status": "play"}])

    def wake(self) -> None:
        """setPowerStatus({status:'active'}) — wakes the device without playback."""
        self.call("system", "setPowerStatus", "1.1", [{"status": "active"}])

    def standby(self) -> None:
        """setPowerStatus({status:'off',standbyDetail:''}) — puts the device in standby."""
        self.call(
            "system",
            "setPowerStatus",
            "1.1",
            [{"status": "off", "standbyDetail": ""}],
        )

    def sleep_timer(self) -> SleepTimer:
        r = self.call("system", "getSleepTimer", "1.0", [{}])
        return SleepTimer(
            status=r.get("status", ""),
            remain_sec=int(r.get("remainTimerSec", -1)),
            sleep_sec=int(r.get("sleepTimerSec", -1)),
            candidate_sec=list(r.get("candidateSec", [])),
        )

    def storage_list(self) -> list[dict]:
        r = self.call("system", "getStorageList", "1.0")
        if isinstance(r, list):
            return r
        return [r] if r else []

    # ---- audio ----

    def sound_settings(self) -> SoundSettings:
        r = self.call("audio", "getSoundSettings", "1.1", [{"target": ""}])
        # r is the inner array - flatten the targets
        result = SoundSettings()
        settings_array = r if isinstance(r, list) else [r]
        for setting in settings_array:
            target = setting.get("target", "")
            value = setting.get("currentValue", "")
            if target == "dsee":
                result.dsee = value
            elif target == "dsdRemastering":
                result.dsd_remastering = value
            elif target == "gaplessPlayback":
                result.gapless_playback = value
            elif target == "volumeNormalization":
                result.volume_normalization = value
            elif target == "oversampling":
                result.oversampling = value
            result.raw[target] = setting
        return result

    def volume_information(self) -> dict:
        """On HAP-Z1ES returns {volume:-1, mute:'toggle', ...} since there's no internal amp.
        On HAP-S1 returns real values."""
        return self.call("audio", "getVolumeInformation", "1.1")

    # ---- avContent ----

    def now_playing(self) -> NowPlaying:
        r = self.call("avContent", "getPlayingContentInfo", "1.2")
        audio_info = (r.get("audioInfo") or [{}])[0]
        bg = None
        if "backgroundColorR" in r:
            bg = (
                int(r.get("backgroundColorR", 0)),
                int(r.get("backgroundColorG", 0)),
                int(r.get("backgroundColorB", 0)),
                int(r.get("backgroundColorA", 255)),
            )
        return NowPlaying(
            state=r.get("state", "STOPPED"),
            title=r.get("title", ""),
            artist=r.get("artist", ""),
            album=r.get("albumName", ""),
            composer=r.get("composer", ""),
            file_name=r.get("fileName", ""),
            uri=r.get("uri", ""),
            album_uri=r.get("albumID", ""),
            playlist_uri=r.get("playlistUri", ""),
            storage_uri=r.get("storageUri", ""),
            position_sec=float(r.get("positionSec", 0.0)),
            duration_sec=float(r.get("durationSec", 0.0)),
            codec=audio_info.get("codec", ""),
            sample_rate_hz=int(audio_info.get("frequency", 0) or 0),
            bit_depth=int(audio_info.get("bandwidth", 0) or 0),
            bitrate=int(audio_info.get("bitrate", 0) or 0),
            cover_art_url=r.get("coverArtUrl", ""),
            background_color_rgba=bg,
            shuffle_type=r.get("shuffleType", ""),
            repeat_type=r.get("repeatType", ""),
            playback_control_mode=r.get("playbackControlMode", ""),
            playlist_modified_version=int(r.get("playlistModifiedVersion", 0)),
            list_index=int(r.get("listIndex", 0)),
            list_count=int(r.get("listCount", 0)),
            favorite_type=r.get("favoriteType", ""),
            raw=r,
        )

    def toggle_playback(self) -> None:
        """Toggle play / pause. Sony's `pausePlayingContent` is misleadingly
        named — it's actually a TOGGLE: pauses when playing, resumes when
        paused. Confirmed live 2026-05-25 with Spotify Connect content.

        This is the only reliable play/pause control for the HAP. Use this
        directly for media-player UI buttons. The companion `pause()` and
        `resume()` methods below check current state first so they behave
        as their name suggests.
        """
        self.call("avContent", "pausePlayingContent", "1.0", [{}])

    def pause(self) -> None:
        """Pause if currently playing. No-op if already paused.

        Adds one round-trip (state check) to avoid the toggle behavior of
        the underlying API. Use `toggle_playback()` to skip the check."""
        np = self.now_playing()
        if np.state == "PLAYING":
            self.toggle_playback()

    def resume(self) -> None:
        """Resume if currently paused. No-op if already playing or stopped.

        Adds one round-trip (state check). Uses the same toggle primitive
        as `pause()` since `setPowerStatus({status:'play'})` does NOT
        reliably resume Spotify Connect playback (confirmed live 2026-05-25).
        """
        np = self.now_playing()
        if np.state in ("PAUSED", "PAUSED_PLAYBACK"):
            self.toggle_playback()

    def seek_seconds(self, position_sec: float) -> None:
        """Seek to position N (seconds) within the current track.

        Sony's app adds +0.01 jitter to force re-trigger; we replicate."""
        self.call(
            "avContent",
            "setPlayContent",
            "1.1",
            [{"positionSec": float(position_sec) + 0.01}],
        )

    def play_track(self, track_id: int) -> dict:
        """Start playback of a single track by its DB id.

        Internally calls createPlayingListAndQuickPlay which builds a 1-track
        play queue and starts. Returns the new playlist URI.
        """
        return self.call(
            "avContent",
            "createPlayingListAndQuickPlay",
            "1.0",
            [
                {
                    "uri": f"audio:track?id={int(track_id)}",
                    "listIndex": 0,
                    "listCount": 1,
                    "playbackControlMode": "folder",
                }
            ],
        )

    # ---------- Internet radio (TuneIn) ----------
    #
    # Reminder for anyone extending this: `call()` already unwraps a
    # single-element `result` list, so it hands back the inner dict. Writing
    # `reply["result"][0]` here would silently read nothing — and a test whose
    # fake `call` returns the wrapped shape will happily agree with you.
    #
    # Discovered from an HTML remote written by a HAP owner on the Steve Hoffman
    # forums, contributed via Amos, 2026-08-21. The call shape is his; the
    # registration gate below is ours, found when it did not work on an
    # unregistered player. See research/api-method-catalog.md.

    def radio_registration(self, method: str = "check") -> dict:
        """Query the TuneIn device-registration state.

        `method` is one of:
          - ``"check"``  → ``{"isRegistered": bool}``
          - ``"getPin"`` → ``{"pinCode": "XXXXXX"}``, the pairing code to enter
            on TuneIn's side. Safe to call; generating a PIN registers nothing.
          - ``"unregister"`` → unbinds the device. **Destructive**; untested.

        LIVE-CONFIRMED 2026-08-21 for ``check`` and ``getPin``.
        """
        if method not in ("check", "getPin", "unregister"):
            raise ValueError(f"unknown registration method: {method!r}")
        return self.call(
            "avContent",
            "registerDevice",
            "1.0",
            [{"uri": "netService:audio?serviceName=tunein", "method": method}],
        )

    def radio_is_registered(self) -> bool:
        """True if this player is linked to a TuneIn *account*.

        This is about **cloud sync of favourites**, not about whether radio
        works. An owner who used TuneIn while Sony supported it reports that
        stations play with no account at all, and that logging in only ever
        synced favourites to and from the cloud — which stopped working when
        Sony withdrew support.

        So do **not** gate playback on this. An earlier version of this client
        did, on the mistaken theory that registration was the reason stations
        would not play on our reference unit, and it refused for people who
        might well have succeeded.
        """
        return bool(_first_field(self.radio_registration("check"), "isRegistered"))

    def play_station(
        self,
        station_id: str,
        path: str = "1/1/1",
        *,
        verify: bool = False,
        settle_sec: float = 8.0,
    ) -> dict:
        """Play a TuneIn station by its station id.

        `station_id` is the ``s#####`` in a tunein.com URL — open the station in
        a browser and read it out of the address bar.

        `path` is an opaque slot whose meaning is unresolved. The script's
        author advises a distinct value per station; on our reference unit it
        makes no observable difference, because station playback does not work
        there at all for a reason upstream of `path`.

        **This call always reports success**, even when it does nothing: it
        returns a playlist URI while leaving the queue empty. Pass
        ``verify=True`` to find out what actually happened. Note also that the
        device does not validate `playbackControlMode` — it echoes back
        whatever it is given.

        Returns the raw reply. With ``verify=True``, returns a dict with an
        added ``"started"`` key.
        """
        if not str(station_id).strip():
            raise ValueError("station_id is required")
        reply = self.call(
            "avContent",
            "createPlayingListAndQuickPlay",
            "1.0",
            [
                {
                    "uri": (
                        "netService:audio?serviceName=tunein"
                        f"&path={path}&id={station_id}"
                    ),
                    "listIndex": 0,
                    "listCount": 0,
                    "playbackControlMode": "station",
                }
            ],
        )
        if not verify:
            return reply
        return {**reply, "started": self._playback_started(settle_sec)}

    def _playback_started(self, settle_sec: float = 8.0) -> bool:
        """Did anything actually start playing? Reads the state back.

        The player needs a few seconds to resolve a stream, so this waits
        before believing a negative.
        """
        import time as _time

        _time.sleep(settle_sec)
        try:
            np = self.now_playing()
        except HAPError:
            return False
        return bool(np.state and np.state.upper() == "PLAYING" and (np.title or np.uri))

    def next_track(self) -> None:
        """Skip to next track in the current play queue."""
        self.call("avContent", "setPlayNextContent", "1.0", [{}])

    def previous_track(self) -> None:
        """Skip to previous track in the current play queue."""
        self.call("avContent", "setPlayPreviousContent", "1.0", [{}])

    def content_info(self, track_id: int) -> dict:
        """Get minimal metadata for a track by id (title, coverArtUrl, bg color)."""
        return self.call(
            "avContent",
            "getContentInfo",
            "1.1",
            [{"uri": f"audio:track?id={int(track_id)}"}],
        )

    def buffer_time(self) -> dict:
        """Get audio buffer setting and candidates."""
        return self.call("avContent", "getBufferTime", "1.0", [{}])

    def repeat_type(self, target: str = "track") -> dict:
        """Get repeat mode.

        target: 'track' (HDD/USB — the canonical value the device echoes; 'audio' is
        also accepted and normalized to 'track') or '' (Spotify — echoed as 'spotify').
        Verified live 2026-06-03.
        """
        return self.call("avContent", "getRepeatType", "1.0", [{"target": target}])

    def shuffle_type(self, target: str = "track") -> dict:
        """Get shuffle mode. target: 'track' (HDD/USB; 'audio' also accepted) or '' (Spotify). See repeat_type."""
        return self.call("avContent", "getShuffleType", "1.0", [{"target": target}])

    # ---- setters (state-changing) ----

    def set_sound_setting(self, target: str, value: str) -> None:
        """Set one of the proprietary audio toggles.

        Valid `target` / `value` combinations:
            dsee                / auto, off
            dsdRemastering      / on, off
            gaplessPlayback     / auto, off
            volumeNormalization / auto, off
            oversampling        / precision, normal
        """
        self.call(
            "audio",
            "setSoundSettings",
            "1.1",
            [{"settings": [{"target": target, "value": value}]}],
        )

    def set_repeat(self, target: str = "track", type: str = "off") -> None:
        """Set repeat mode. type: 'off', 'one', 'all', 'track'. target: 'track' (HDD/USB; 'audio' also accepted) or '' (Spotify)."""
        self.call("avContent", "setRepeatType", "1.0", [{"target": target, "type": type}])

    def set_shuffle(self, target: str = "track", type: str = "off") -> None:
        """Set shuffle mode. type: 'off', 'track', 'album', 'folder'. target: 'track' (HDD/USB; 'audio' also accepted) or '' (Spotify)."""
        self.call("avContent", "setShuffleType", "1.0", [{"target": target, "type": type}])

    def set_buffer_time(self, buffer_sec: int) -> None:
        """Set audio playback buffer length. Must be one of getBufferTime's candidate values (15, 30, 60, 180)."""
        self.call("avContent", "setBufferTime", "1.0", [{"bufferTimeSec": int(buffer_sec)}])

    def set_sleep_timer(self, status: str = "off", sleep_sec: int = 0) -> None:
        """Set sleep timer. status: 'on' or 'off'. sleep_sec: one of candidateSec
        from getSleepTimer (typically 600, 1200, 1800, 2400, 3000, 3600, 5400, 7200)."""
        self.call(
            "system",
            "setSleepTimer",
            "1.0",
            [{"status": status, "sleepTimerSec": int(sleep_sec)}],
        )

    def set_volume(self, volume: int) -> None:
        """Set audio volume. On HAP-Z1ES this is a no-op (no internal amp); on HAP-S1 it actually sets the volume."""
        self.call("audio", "setAudioVolume", "1.0", [{"volume": str(int(volume))}])

    def mute_toggle(self) -> None:
        """Toggle mute. On HAP-Z1ES, Sony's code forces 'toggle' regardless of intent — there is no stateful mute."""
        self.call("audio", "setAudioMute", "1.1", [{"mute": "toggle"}])

    def set_favorite(self, track_id: int, status: str = "favorite") -> None:
        """Set or clear a track's favorite status.

        Wraps Sony's `editContentInfo` with `method=editTrackInfo`.

        Args:
            track_id: the integer track id (PROP3601 in the on-device DB)
            status: 'favorite' (mark as favorite), 'dislike' (mark disliked),
                'normal' (clear both flags)
        """
        if status not in ("favorite", "dislike", "normal"):
            raise ValueError(f"status must be favorite|dislike|normal, got {status!r}")
        self.call(
            "avContent",
            "editContentInfo",
            "1.0",
            [
                {
                    "method": "editTrackInfo",
                    "target": [
                        {
                            "uri": f"audio:track?id={int(track_id)}",
                            "tagUri": "meta:favorite",
                            "value": status,
                        }
                    ],
                }
            ],
        )

    # ---- database ----

    def db_same_version(
        self, db_serial: int = 0, original_version: int = 0, db_type: str = "hdd"
    ) -> dict:
        """Check if a locally-cached library DB version matches the device.

        Returns {isSameVersion: bool, isSameName: bool, type: str}.
        Returned isSameVersion=False means a downloadByDiff should be
        attempted to bring the local cache in sync."""
        uuid_short = self._device_uuid_short()
        uri = (
            f"database:{uuid_short}?dbType={db_type}"
            f"&dbSerial={int(db_serial)}&originalVersion={int(original_version)}"
        )
        return self.call("database", "checkSameDatabase", "1.0", [{"uri": uri}])

    def _device_uuid_short(self) -> str:
        """Get the UDN minus the 'uuid:' prefix (for database URIs).
        Fetched from the UPnP description on port 60100."""
        url = f"http://{self.ip}:60100/hap.xml"
        try:
            with urlopen(url, timeout=self.timeout) as r:
                xml = r.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, socket.timeout) as e:
            raise HAPTransportError(f"could not fetch UPnP description: {e}") from e
        start = xml.find("<UDN>")
        if start < 0:
            raise HAPError("no <UDN> in UPnP description")
        end = xml.find("</UDN>", start)
        udn = xml[start + len("<UDN>") : end].strip()
        if udn.startswith("uuid:"):
            return udn[5:]
        return udn


# ---------- CLI ----------


def _cli_now_playing(hap: HAP, _args) -> None:
    np = hap.now_playing()
    if np.state in ("PLAYING", "PAUSED_PLAYBACK", "PAUSED"):
        prog = f"{np.position_sec:7.1f} / {np.duration_sec:7.1f}s ({np.progress * 100:5.1f}%)"
        if np.sample_rate_hz > 0:
            tech = f"{np.codec.upper()} {np.sample_rate_hz / 1000:g} kHz / {np.bit_depth}-bit"
        elif np.codec:
            tech = np.codec.upper()
        else:
            src = np.storage_uri or "?"
            tech = _t("cli.np.streaming", src=src)
        print(f"{np.state:8s}  {prog}  [{tech}]")
        if np.artist:
            print(f"  {np.artist}")
        if np.title:
            print(f"  {np.title}")
        if np.album:
            print(f"  {np.album}")
        if np.cover_art_url:
            print(f"  {_t('cli.np.art', url=np.cover_art_url)}")
    else:
        print(f"{np.state}")


def _cli_pause(hap: HAP, _args) -> None:
    hap.pause()
    print(_t("cli.sent.pause"))


def _cli_resume(hap: HAP, _args) -> None:
    hap.resume()
    print(_t("cli.sent.resume"))


def _cli_seek(hap: HAP, args) -> None:
    hap.seek_seconds(float(args.position))
    print(_t("cli.sent.seek", pos=args.position))


def _cli_play_track(hap: HAP, args) -> None:
    result = hap.play_track(args.track_id)
    print(_t("cli.sent.play_track", id=args.track_id, uri=result.get("uri", "?")))


def _cli_next(hap: HAP, _args) -> None:
    hap.next_track()
    print(_t("cli.sent.next"))


def _cli_prev(hap: HAP, _args) -> None:
    hap.previous_track()
    print(_t("cli.sent.previous"))


def _row(label: str, value: object) -> None:
    """Print an aligned 'label: value' row (label padded to a stable width)."""
    print(f"  {label + ':':<22}{value}")


def _cli_system(hap: HAP, _args) -> None:
    info = hap.system_info()
    _row(_t("cli.sys.model"), info.model)
    _row(_t("cli.sys.name"), info.name)
    _row(_t("cli.sys.product"), info.product)
    _row(_t("cli.sys.version"), info.version)
    _row(_t("cli.sys.gen"), info.generation)
    _row(_t("cli.sys.mac"), info.mac)
    _row(_t("cli.sys.lang"), info.language)
    _row(_t("cli.sys.power"), hap.power_status())


def _cli_sound(hap: HAP, _args) -> None:
    s = hap.sound_settings()
    _row(_t("cli.snd.dsee"), s.dsee)
    _row(_t("cli.snd.dsd"), s.dsd_remastering)
    _row(_t("cli.snd.gapless"), s.gapless_playback)
    _row(_t("cli.snd.volnorm"), s.volume_normalization)
    _row(_t("cli.snd.oversampling"), s.oversampling)


def _cli_radio_status(hap: HAP, _args) -> None:
    registered = hap.radio_is_registered()
    _row("TuneIn registered", "yes" if registered else "no")
    if not registered:
        code = _first_field(hap.radio_registration("getPin"), "pinCode")
        _row("Pairing PIN", code or "-")
        print()
        print("This player is not bound to a TuneIn account, so radio playback")
        print("will silently do nothing. Pair it on TuneIn's site with the PIN")
        print("above, then re-run this command to confirm.")


def _cli_play_station(hap: HAP, args) -> None:
    _row("Station", args.station_id)
    _row("Path", args.path)
    result = hap.play_station(args.station_id, args.path, verify=True)
    if result.get("started"):
        _row("Result", "playing")
        return
    _row("Result", "nothing started")
    print()
    print("The player accepted the request and reported success, as it always")
    print("does, but nothing is playing and any previous playback was cleared.")
    print("On our reference unit every station behaves this way, and neither")
    print("the account state nor the path value changes it — the cause is")
    print("upstream of both and is not yet understood. Known-working players")
    print("are ones that used TuneIn while Sony still supported it.")


def _cli_sleep_timer(hap: HAP, _args) -> None:
    t = hap.sleep_timer()
    _row(_t("cli.sleep.status"), t.status)
    _row(_t("cli.sleep.remain"), f"{t.remain_sec}s")
    _row(_t("cli.sleep.sleep"), f"{t.sleep_sec}s")
    _row(_t("cli.sleep.options"), t.candidate_sec)


def main() -> int:
    # Windows consoles default to cp1252 and choke on accents / CJK; force UTF-8
    # so translated output (Français, 日本語, …) renders without PYTHONUTF8=1.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ip", help="HAP device IP address")
    parser.add_argument(
        "--lang",
        help="Output language: en, fr, ja, de, es, it (default: auto from OS locale / HAP_LANG).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("now-playing", help="Show current playback").set_defaults(
        func=_cli_now_playing
    )
    sub.add_parser("pause").set_defaults(func=_cli_pause)
    sub.add_parser("resume").set_defaults(func=_cli_resume)
    sub.add_parser("next").set_defaults(func=_cli_next)
    sub.add_parser("prev").set_defaults(func=_cli_prev)
    sub.add_parser("system").set_defaults(func=_cli_system)
    sub.add_parser("sound").set_defaults(func=_cli_sound)
    sub.add_parser("sleep-timer").set_defaults(func=_cli_sleep_timer)

    p = sub.add_parser("seek")
    p.add_argument("position", type=float, help="Position in seconds")
    p.set_defaults(func=_cli_seek)

    sub.add_parser(
        "radio-status", help="TuneIn registration state (and a pairing PIN if unbound)"
    ).set_defaults(func=_cli_radio_status)

    p = sub.add_parser("play-station", help="Play a TuneIn station by its s##### id")
    p.add_argument("station_id", help="TuneIn station id, e.g. s13606")
    p.add_argument(
        "--path", default="1/1/1", help="Slot path; must differ per station (default 1/1/1)"
    )
    p.set_defaults(func=_cli_play_station)

    p = sub.add_parser("play-track")
    p.add_argument("track_id", type=int, help="Track ID")
    p.set_defaults(func=_cli_play_track)

    args = parser.parse_args()
    global _LANG
    if i18n is not None:
        _LANG = i18n.detect_lang(override=args.lang)
    hap = HAP(args.ip)
    try:
        args.func(hap, args)
        return 0
    except HAPMethodError as e:
        print(_t("cli.err.api", msg=e), file=sys.stderr)
        return 1
    except HAPTransportError as e:
        print(_t("cli.err.transport", msg=e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
