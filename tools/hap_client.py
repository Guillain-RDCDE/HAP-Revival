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

    state: str  # "PLAYING" | "PAUSED" | "STOPPED" | "NO_MEDIA_PRESENT"
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

    def repeat_type(self, target: str = "audio") -> dict:
        """Get repeat mode. target: 'audio' (HDD/USB) or 'spotify'."""
        return self.call("avContent", "getRepeatType", "1.0", [{"target": target}])

    def shuffle_type(self, target: str = "audio") -> dict:
        """Get shuffle mode. target: 'audio' (HDD/USB) or 'spotify'."""
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

    def set_repeat(self, target: str = "audio", type: str = "off") -> None:
        """Set repeat mode. type: 'off', 'one', 'all', 'track'. target: 'audio' or 'spotify'."""
        self.call("avContent", "setRepeatType", "1.0", [{"target": target, "type": type}])

    def set_shuffle(self, target: str = "audio", type: str = "off") -> None:
        """Set shuffle mode. type: 'off', 'track', 'album', 'folder'. target: 'audio' or 'spotify'."""
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
    if np.state == "PLAYING" or np.state == "PAUSED":
        prog = f"{np.position_sec:7.1f} / {np.duration_sec:7.1f}s ({np.progress * 100:5.1f}%)"
        if np.sample_rate_hz > 0:
            tech = f"{np.codec.upper()} {np.sample_rate_hz / 1000:g} kHz / {np.bit_depth}-bit"
        elif np.codec:
            tech = np.codec.upper()
        else:
            src = np.storage_uri or "?"
            tech = f"streaming ({src})"
        print(f"{np.state:8s}  {prog}  [{tech}]")
        if np.artist:
            print(f"  {np.artist}")
        if np.title:
            print(f"  {np.title}")
        if np.album:
            print(f"  {np.album}")
        if np.cover_art_url:
            print(f"  art: {np.cover_art_url}")
    else:
        print(f"{np.state}")


def _cli_pause(hap: HAP, _args) -> None:
    hap.pause()
    print("pause sent")


def _cli_resume(hap: HAP, _args) -> None:
    hap.resume()
    print("resume sent")


def _cli_seek(hap: HAP, args) -> None:
    hap.seek_seconds(float(args.position))
    print(f"seek to {args.position}s sent")


def _cli_play_track(hap: HAP, args) -> None:
    result = hap.play_track(args.track_id)
    print(f"playing track {args.track_id} on {result.get('uri', '?')}")


def _cli_next(hap: HAP, _args) -> None:
    hap.next_track()
    print("next sent")


def _cli_prev(hap: HAP, _args) -> None:
    hap.previous_track()
    print("previous sent")


def _cli_system(hap: HAP, _args) -> None:
    info = hap.system_info()
    print(f"  model:    {info.model}")
    print(f"  name:     {info.name}")
    print(f"  product:  {info.product}")
    print(f"  version:  {info.version}")
    print(f"  gen:      {info.generation}")
    print(f"  mac:      {info.mac}")
    print(f"  lang:     {info.language}")
    print(f"  power:    {hap.power_status()}")


def _cli_sound(hap: HAP, _args) -> None:
    s = hap.sound_settings()
    print(f"  DSEE:               {s.dsee}")
    print(f"  DSD remastering:    {s.dsd_remastering}")
    print(f"  Gapless playback:   {s.gapless_playback}")
    print(f"  Volume normaliz:    {s.volume_normalization}")
    print(f"  Oversampling:       {s.oversampling}")


def _cli_sleep_timer(hap: HAP, _args) -> None:
    t = hap.sleep_timer()
    print(f"  status:   {t.status}")
    print(f"  remain:   {t.remain_sec}s")
    print(f"  sleep:    {t.sleep_sec}s")
    print(f"  options:  {t.candidate_sec}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ip", help="HAP device IP address")
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

    p = sub.add_parser("play-track")
    p.add_argument("track_id", type=int, help="Track ID")
    p.set_defaults(func=_cli_play_track)

    args = parser.parse_args()
    hap = HAP(args.ip)
    try:
        args.func(hap, args)
        return 0
    except HAPMethodError as e:
        print(f"API error: {e}", file=sys.stderr)
        return 1
    except HAPTransportError as e:
        print(f"Transport error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
