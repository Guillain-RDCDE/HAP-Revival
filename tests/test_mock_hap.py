"""Tests for the mock HAP device.

Two layers:
  - unit: the dispatch() table (set→get round-trips, playback clock, PNG covers)
  - integration: the real hap_client driving the mock over HTTP/JSON-RPC, which
    exercises the transport + response parsing end-to-end without hardware.
"""

import threading

import pytest

import mock_hap


HOST = "127.0.0.1:60200"


@pytest.fixture(autouse=True)
def fresh_state():
    """Reset the module-global device state (and per-track favorites) so tests
    don't leak playback position / settings into each other."""
    mock_hap.STATE = mock_hap.DeviceState()
    for tr in mock_hap.DEMO_TRACKS:
        tr.favorite_type = "normal"
    yield


def _call(service, method, params=None):
    return mock_hap.dispatch(service, method, "1.0", params or [{}], HOST)


# ---------- PNG cover encoder ----------


def test_gradient_png_is_valid():
    png = mock_hap.gradient_png((200, 150, 80), (20, 30, 60), size=32)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")     # PNG signature
    assert b"IHDR" in png and b"IDAT" in png
    # final chunk is the canonical empty IEND, terminated by its fixed CRC
    assert png.endswith(b"IEND\xae\x42\x60\x82")


def test_track_cover_png():
    png = mock_hap.DEMO_TRACKS[0].cover_png()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


# ---------- now_playing ----------


def test_now_playing_shape():
    np = _call("avContent", "getPlayingContentInfo")
    assert np["state"] == "PLAYING"
    assert np["title"] and np["artist"]
    assert "backgroundColorR" in np and "coverArtUrl" in np
    assert np["audioInfo"][0]["codec"] == "flac"     # first demo track is the FLAC


def test_now_playing_streaming_track_has_no_audioinfo():
    # advance to the Spotify stream (index 3) and confirm the streaming branch
    mock_hap.STATE.skip(3)
    np = _call("avContent", "getPlayingContentInfo")
    assert np["storageUri"] == "storage:spotify"
    assert "audioInfo" not in np


# ---------- playback clock ----------


def test_toggle_pauses_and_resumes():
    assert mock_hap.STATE.playing is True
    _call("avContent", "pausePlayingContent")
    assert mock_hap.STATE.playing is False
    np = _call("avContent", "getPlayingContentInfo")
    assert np["state"] == "PAUSED_PLAYBACK"
    _call("avContent", "pausePlayingContent")
    assert mock_hap.STATE.playing is True


def test_seek_sets_position():
    _call("avContent", "setPlayContent", [{"positionSec": 120.0}])
    mock_hap.STATE.playing = False                   # freeze so position is exact
    np = _call("avContent", "getPlayingContentInfo")
    assert abs(np["positionSec"] - 120.0) < 1.0


def test_next_and_previous_change_track():
    first = _call("avContent", "getPlayingContentInfo")["title"]
    _call("avContent", "setPlayNextContent")
    second = _call("avContent", "getPlayingContentInfo")["title"]
    assert second != first
    _call("avContent", "setPlayPreviousContent")
    assert _call("avContent", "getPlayingContentInfo")["title"] == first


# ---------- settings round-trips ----------


def test_sound_settings_roundtrip():
    _call("audio", "setSoundSettings", [{"settings": [{"target": "dsee", "value": "off"}]}])
    settings = _call("audio", "getSoundSettings")
    dsee = next(s for s in settings if s["target"] == "dsee")
    assert dsee["currentValue"] == "off"


def test_repeat_and_shuffle_roundtrip():
    _call("avContent", "setRepeatType", [{"target": "track", "type": "all"}])
    assert _call("avContent", "getRepeatType", [{"target": "track"}])["type"] == "all"
    _call("avContent", "setShuffleType", [{"target": "track", "type": "album"}])
    assert _call("avContent", "getShuffleType", [{"target": "track"}])["type"] == "album"


def test_favorite_roundtrip():
    tid = mock_hap.DEMO_TRACKS[0].id
    _call("avContent", "editContentInfo", [{
        "method": "editTrackInfo",
        "target": [{"uri": f"audio:track?id={tid}", "tagUri": "meta:favorite", "value": "favorite"}],
    }])
    assert mock_hap.DEMO_TRACKS[0].favorite_type == "favorite"
    assert _call("avContent", "getPlayingContentInfo")["favoriteType"] == "favorite"


def test_power_standby_stops_playback():
    _call("system", "setPowerStatus", [{"status": "off", "standbyDetail": ""}])
    assert mock_hap.STATE.power == "standby"
    assert _call("avContent", "getPlayingContentInfo")["state"] == "STOPPED"


def test_sleep_timer_roundtrip():
    _call("system", "setSleepTimer", [{"status": "on", "sleepTimerSec": 1800}])
    t = _call("system", "getSleepTimer")
    assert t["status"] == "on" and t["sleepTimerSec"] == 1800


def test_unknown_method_raises_keyerror():
    with pytest.raises(KeyError):
        _call("avContent", "noSuchMethod")


def test_setter_returns_empty_sentinel():
    assert _call("audio", "setAudioVolume", [{"volume": "5"}]) is mock_hap.EMPTY


# ---------- integration: the real client over HTTP ----------


@pytest.fixture
def live_mock():
    server = mock_hap.make_server("127.0.0.1", 0, quiet=True)  # port 0 = free port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address  # (host, port)
    finally:
        server.shutdown()
        server.server_close()


def test_front_panel_is_mocked_so_hap_screen_can_be_tried_without_hardware(live_mock):
    """`/sony/hap` — the third API on port 60200.

    Without this the README's claim that every tool but the live smoke test runs
    against the mock was false: hap_screen.py had nothing to talk to.
    """
    import struct
    import urllib.request

    host, port = live_mock
    base = f"http://{host}:{port}/sony/hap"

    with urllib.request.urlopen(f"{base}?target=screen&cmd=display_png", timeout=10) as r:
        png = r.read()
        assert r.headers.get("Content-Type") == "image/png"
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    # The real panel is 480x272; a client that scales or crops must meet that here.
    assert struct.unpack(">II", png[16:24]) == (480, 272)

    for cmd in ("capture_png",):
        with urllib.request.urlopen(f"{base}?target=screen&cmd={cmd}", timeout=10) as r:
            assert r.read() == b"None"

    for key in ("home", "down", "enter", "play"):
        with urllib.request.urlopen(f"{base}?target=keyevent&cmd={key}", timeout=10) as r:
            assert r.read() == b"None"


def test_an_unknown_front_panel_target_is_a_404(live_mock):
    import urllib.error
    import urllib.request

    host, port = live_mock
    try:
        urllib.request.urlopen(f"http://{host}:{port}/sony/hap?target=nonsense", timeout=10)
    except urllib.error.HTTPError as e:
        assert e.code == 404
    else:
        raise AssertionError("an unknown target should 404")


def test_gradient_png_can_be_oblong():
    import struct

    png = mock_hap.gradient_png((10, 20, 30), (200, 210, 220), size=480, height=272)
    assert struct.unpack(">II", png[16:24]) == (480, 272)
    square = mock_hap.gradient_png((10, 20, 30), (200, 210, 220), size=64)
    assert struct.unpack(">II", square[16:24]) == (64, 64), "square stays the default"


def test_client_against_live_mock(live_mock):
    import hap_client
    host, port = live_mock
    hap = hap_client.HAP(host, port=port)

    info = hap.system_info()
    assert info.model == "HAP-Z1ES"
    assert info.version == "0019404R"

    np = hap.now_playing()
    assert np.state == "PLAYING"
    assert np.artist == "Gustav Mahler"
    assert np.sample_rate_hz == 96000 and np.bit_depth == 24

    # set→read a sound toggle through the full HTTP path
    hap.set_sound_setting("dsee", "off")
    assert hap.sound_settings().dsee == "off"

    # toggle play/pause via the real client
    hap.toggle_playback()
    assert hap.now_playing().state == "PAUSED_PLAYBACK"


def test_client_play_track_against_live_mock(live_mock):
    import hap_client
    host, port = live_mock
    hap = hap_client.HAP(host, port=port)
    target = mock_hap.DEMO_TRACKS[2].id           # the Red-Book FLAC
    hap.play_track(target)
    np = hap.now_playing()
    assert np.title == "Teardrop"
    assert np.sample_rate_hz == 44100
