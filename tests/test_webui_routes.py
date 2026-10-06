"""The web UI's HTTP surface, driven end to end against the mock device.

A real `ThreadingHTTPServer` on loopback serves `HAPHandler`, whose `hap`
points at a `mock_hap` instance on another loopback port. No hardware, no push
subscription (the watcher is never started), nothing leaves the machine.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import hap_client
import hap_library
import mock_hap
import webui
from webui import HAPHandler


@pytest.fixture
def device():
    server = mock_hap.make_server("127.0.0.1", 0, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    mock_hap.STATE = mock_hap.DeviceState()
    for tr in mock_hap.DEMO_TRACKS:
        tr.favorite_type = "normal"
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def ui(device, monkeypatch):
    host, port = device
    HAPHandler.hap = hap_client.HAP(host, port=port, timeout=10)
    HAPHandler.library = hap_library.Library(host, port=port, timeout=10)
    HAPHandler.push = None
    monkeypatch.setattr(webui, "HARVEST", webui.HarvestState())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), HAPHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    h, p = httpd.server_address[:2]
    try:
        yield f"http://{h}:{p}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        HAPHandler.library = None


def get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def post(base, path, payload=None, raw=None):
    body = raw if raw is not None else json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(base + path, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw_body)
        except json.JSONDecodeError:
            return e.code, raw_body


# ---------- the page and its assets ----------


def test_index_is_rendered_from_the_template_with_the_cover_accent(ui):
    status, headers, body = get(ui, "/", {"Accept-Language": "fr-FR,fr;q=0.9"})
    text = body.decode("utf-8")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert headers["Cache-Control"].startswith("no-store")
    assert '<html lang="fr">' in text and '"__DEFAULT_LANG__"' not in text
    assert "__ACCENT_R__" not in text and "__I18N_JSON__" not in text
    # The first demo track's accent and cover are baked into the first paint.
    accent = mock_hap.DEMO_TRACKS[0].accent
    assert f"rgb({accent[0]}, {accent[1]}, {accent[2]})" in text
    assert "cover_art/" in text
    assert "/sw.js" in text and "/manifest.webmanifest" in text


def test_index_language_query_wins_over_the_header(ui):
    _, _, body = get(ui, "/index.html?lang=de", {"Accept-Language": "fr"})
    assert '<html lang="de">' in body.decode("utf-8")


def test_index_still_renders_when_the_player_is_unreachable(ui):
    HAPHandler.hap = hap_client.HAP("127.0.0.1", port=1, timeout=1)
    status, _, body = get(ui, "/")
    assert status == 200
    assert f"rgb({webui.FALLBACK_ACCENT[0]}," in body.decode("utf-8")


def test_manifest_and_service_worker_are_served(ui):
    status, headers, body = get(ui, "/manifest.webmanifest")
    assert status == 200 and "manifest+json" in headers["Content-Type"]
    manifest = json.loads(body)
    assert manifest["display"] == "standalone"
    assert [i["src"] for i in manifest["icons"]] == [
        "/pwa/icon-192.png", "/pwa/icon-512.png", "/pwa/icon-maskable-512.png"]
    status, headers, body = get(ui, "/sw.js")
    assert status == 200 and headers["Service-Worker-Allowed"] == "/"
    assert b'startsWith("/api/")' in body, "the worker must never cache device state"


def test_icons_are_served_and_traversal_is_refused(ui):
    status, headers, body = get(ui, "/pwa/icon-192.png")
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert body.startswith(b"\x89PNG")
    assert get(ui, "/pwa/../webui.py")[0] == 404
    assert get(ui, "/pwa/nope.png")[0] == 404
    assert webui.pwa_icon_path("../hap_client.py") is None
    assert webui.pwa_icon_path("icon-512.png") is not None


def test_unknown_paths_are_404(ui):
    assert get(ui, "/nothing")[0] == 404
    assert post(ui, "/api/nothing")[0] == 404


# ---------- state ----------


def test_state_carries_every_section(ui):
    status, _, body = get(ui, "/api/state")
    assert status == 200
    state = json.loads(body)
    assert set(state) == {"now_playing", "system", "sound", "sleep_timer", "volume"}
    np = state["now_playing"]
    assert np["state"] == "PLAYING" and np["artist"] == "Gustav Mahler"
    assert np["sample_rate_hz"] == 96000 and 0 <= np["progress"] <= 1
    assert state["system"]["model"] == "HAP-Z1ES" and state["system"]["power"] == "active"
    assert state["sound"]["dsee"] == "auto"
    assert state["sleep_timer"]["candidate_sec"][0] == 600
    assert state["volume"]["maxVolume"] == -1, "a Z1ES has no volume stage"


def test_state_degrades_per_section_when_the_player_is_gone():
    state = webui.build_state(hap_client.HAP("127.0.0.1", port=1, timeout=1))
    assert state["now_playing"]["state"] == "STOPPED"
    assert all("error" in section for section in state.values())


# ---------- actions ----------


def test_transport_actions_drive_the_device(ui):
    assert post(ui, "/api/toggle-playback") == (200, {"ok": True})
    assert json.loads(get(ui, "/api/state")[2])["now_playing"]["state"] == "PAUSED_PLAYBACK"
    assert post(ui, "/api/resume") == (200, {"ok": True})
    assert json.loads(get(ui, "/api/state")[2])["now_playing"]["state"] == "PLAYING"
    assert post(ui, "/api/next")[0] == 200
    assert json.loads(get(ui, "/api/state")[2])["now_playing"]["title"] == "So What"
    assert post(ui, "/api/previous")[0] == 200
    assert post(ui, "/api/seek", {"position_sec": 120})[0] == 200
    assert json.loads(get(ui, "/api/state")[2])["now_playing"]["position_sec"] >= 120
    assert post(ui, "/api/play-track", {"track_id": mock_hap.DEMO_TRACKS[2].id})[0] == 200
    assert json.loads(get(ui, "/api/state")[2])["now_playing"]["title"] == "Teardrop"
    assert post(ui, "/api/set-sound", {"target": "dsee", "value": "off"})[0] == 200
    assert json.loads(get(ui, "/api/state")[2])["sound"]["dsee"] == "off"
    assert post(ui, "/api/set-sleep-timer", {"status": "on", "sleep_sec": 1800})[0] == 200
    assert json.loads(get(ui, "/api/state")[2])["sleep_timer"]["sleep_sec"] == 1800
    assert post(ui, "/api/set-volume", {"volume": 10})[0] == 200
    assert post(ui, "/api/mute-toggle")[0] == 200
    assert post(ui, "/api/standby")[0] == 200
    assert json.loads(get(ui, "/api/state")[2])["system"]["power"] == "standby"
    assert post(ui, "/api/wake")[0] == 200
    assert json.loads(get(ui, "/api/state")[2])["system"]["power"] == "active"


def test_bad_bodies_are_400(ui):
    status, payload = post(ui, "/api/seek", raw=b"{not json")
    assert status == 400 and "invalid JSON" in payload["error"]
    status, payload = post(ui, "/api/seek", raw=b"[1, 2]")
    assert status == 400 and "object" in payload["error"]
    status, payload = post(ui, "/api/play-track", {})
    assert status == 400 and "bad params" in payload["error"]
    status, payload = post(ui, "/api/seek", {"position_sec": "far"})
    assert status == 400


def test_a_device_error_is_500(ui):
    HAPHandler.hap = hap_client.HAP("127.0.0.1", port=1, timeout=1)
    status, payload = post(ui, "/api/pause")
    assert status == 500 and "error" in payload


def test_favorite_follows_the_current_hdd_track(ui):
    status, payload = post(ui, "/api/set-favorite", {"value": "favorite"})
    assert (status, payload) == (200, {"ok": True})
    assert mock_hap.DEMO_TRACKS[0].favorite_type == "favorite"
    assert json.loads(get(ui, "/api/state")[2])["now_playing"]["favorite_type"] == "favorite"
    mock_hap.STATE.skip(3)  # the Spotify stream: not in the HDD library
    status, payload = post(ui, "/api/set-favorite", {"value": "normal"})
    assert status == 400 and "HDD" in payload["error"]


def test_panel_screen_and_keys_go_through_the_proxy(ui):
    status, headers, body = get(ui, "/api/panel/screen")
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert body.startswith(b"\x89PNG") and headers["Cache-Control"] == "no-store"
    assert post(ui, "/api/panel/key", {"key": "enter"}) == (200, {"pressed": "enter"})
    status, payload = post(ui, "/api/panel/key", {"key": "rm -rf"})
    assert status == 400 and payload["error"] == "unknown key"


def test_panel_screen_reports_an_unreachable_player(ui):
    HAPHandler.hap = hap_client.HAP("127.0.0.1", port=1, timeout=1)
    status, _, body = get(ui, "/api/panel/screen")
    assert status == 502 and "error" in json.loads(body)


# ---------- library ----------


def test_library_listings_and_drill_down(ui):
    status, _, body = get(ui, "/api/library/artists?limit=1")
    assert status == 200
    page = json.loads(body)
    assert page["has_more"] is True and page["total"] == 3 and len(page["items"]) == 1
    artist = page["items"][0]
    _, _, body = get(ui, f"/api/library/artists/{artist['artistid']}/albums")
    albums = json.loads(body)["items"]
    assert albums and albums[0]["name"]
    _, _, body = get(ui, f"/api/library/albums/{albums[0]['albumid']}/tracks")
    assert json.loads(body)["items"][0]["trackid"]
    assert json.loads(get(ui, "/api/library/playlists")[2])["items"] == []
    assert json.loads(get(ui, "/api/library/favorites")[2])["items"] == []
    assert json.loads(get(ui, "/api/library/genres")[2])["items"][0]["name"] == "Demo"
    assert json.loads(get(ui, "/api/library/tracks?offset=abc&limit=zzz")[2])["offset"] == 0
    assert get(ui, "/api/library/nonsense")[0] == 404
    assert get(ui, "/api/library/albums/x/tracks")[0] == 400


def test_library_is_503_without_a_library_object(ui):
    HAPHandler.library = None
    assert get(ui, "/api/library/artists")[0] == 503
    assert post(ui, "/api/library/harvest")[0] == 500


def test_library_device_errors_are_502(ui):
    HAPHandler.library = hap_library.Library("127.0.0.1", port=1, timeout=1)
    status, _, body = get(ui, "/api/library/artists")
    assert status == 502 and "error" in json.loads(body)


def test_search_offers_the_harvest_then_uses_it(ui):
    _, _, body = get(ui, "/api/library/search?q=miles")
    first = json.loads(body)
    assert first["ready"] is False and first["harvesting"] is False

    status, payload = post(ui, "/api/library/harvest")
    assert status == 200 and payload["started"] is True
    for _ in range(100):
        if not webui.HARVEST.running:
            break
        import time

        time.sleep(0.05)
    assert webui.HARVEST.data is not None, webui.HARVEST.error
    assert post(ui, "/api/library/harvest")[1]["started"] in (True, False)

    _, _, body = get(ui, "/api/library/search?q=miles")
    hit = json.loads(body)
    assert hit["ready"] is True
    assert [a["name"] for a in hit["results"]["artists"]] == ["Miles Davis"]
    assert json.loads(get(ui, "/api/library/search?q=")[2])["results"]["artists"] == []


def test_fix_reports_what_is_missing_then_lists_findings(ui, tmp_path, monkeypatch):
    _, _, body = get(ui, "/api/fix?kind=cover")
    assert json.loads(body) == {"ready": False, "needs": ["library", "shares"], "items": []}

    harvest = {
        "host": HAPHandler.library.host, "artists": [], "albums": [
            {"albumid": 1, "name": "Album", "number_of_tracks": 1, "album_artist": {"name": "X"}}],
        "tracks": [{"trackid": 1, "name": "t", "filename": "01 - a.flac", "duration": 10,
                    "album": {"albumid": 1, "name": "Album"}, "artist": {"name": "X"},
                    "codec": {"codec_type": "flac", "sample_rate": 44100, "bit_width": 16}}],
    }
    index = {"host": harvest["host"], "shares": {"HAP_Internal": [["/X/Album", "01 - a.flac", 1]]}}
    webui.HARVEST.data = harvest
    monkeypatch.setattr(webui.hap_fixit, "load_index", lambda host: index)
    monkeypatch.setattr(webui.hap_fixit, "load_sync_maps", lambda path=None: {})
    monkeypatch.setattr(webui.hap_fixit, "load_local_index", lambda host: None)

    _, _, body = get(ui, "/api/fix?kind=cover")
    data = json.loads(body)
    assert data["ready"] is True and data["total"] == 1 and data["located"] == 1
    assert data["items"][0]["title"] == "Album"
    assert data["items"][0]["paths"][0].startswith("\\\\")

    opened = []
    monkeypatch.setattr(webui.hap_fixit, "open_folder", lambda p: opened.append(p))
    status, payload = post(ui, "/api/fix/open", {"path": data["items"][0]["paths"][0]})
    assert status == 200 and opened == [data["items"][0]["paths"][0]]
    status, payload = post(ui, "/api/fix/open", {"path": "C:\\Windows"})
    assert status == 400 and payload["error"] == "unknown path"
    monkeypatch.setattr(webui.hap_fixit, "open_in_editor", lambda p: "Mp3tag.exe")
    status, payload = post(ui, "/api/fix/open", {"path": data["items"][0]["paths"][0], "editor": 1})
    assert (status, payload) == (200, {"editor": "Mp3tag.exe"})


def test_fix_open_is_refused_from_another_machine(ui, monkeypatch):
    monkeypatch.setattr(webui, "is_local_client", lambda address: False)
    status, _payload = post(ui, "/api/fix/open", {"path": "x"})
    assert status == 403
    monkeypatch.undo()
    assert webui.is_local_client("127.0.0.1") and webui.is_local_client("::1")
    assert not webui.is_local_client("10.0.0.9")


# ---------- CLI ----------


def test_main_wires_the_handler_and_serves(monkeypatch, capsys, device):
    host, port = device

    class Server:
        def __init__(self, address, handler):
            self.address, self.closed = address, False

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            self.closed = True

    servers = []
    def fake_server(address, handler):
        servers.append(Server(address, handler))
        return servers[-1]

    monkeypatch.setattr(webui, "ThreadingHTTPServer", fake_server)
    monkeypatch.setattr(webui.hap_library, "load_harvest", lambda h: {"counts": {"tracks": 3}})
    started = []
    monkeypatch.setattr(webui.PushWatcher, "start", lambda self: started.append(self.ip))
    # The mock lives on an ephemeral port; point both client classes at it.
    real, real_lib = hap_client.HAP, hap_library.Library
    monkeypatch.setattr(webui, "HAP", lambda ip: real(ip, port=port, timeout=10))
    monkeypatch.setattr(webui.hap_library, "Library",
                        lambda ip: real_lib(ip, port=port, timeout=10))

    assert webui.main([host, "--port", "0", "--notify-port", "0"]) == 0
    out = capsys.readouterr().out
    assert "Connected: HAP-Z1ES firmware 0019404R" in out and "Stopping" in out
    assert "Library search index loaded from cache" in out
    assert started == [host] and servers[0].closed and servers[0].address == ("127.0.0.1", 0)

    assert webui.main([host, "--port", "0", "--no-push"]) == 0
    assert "Push notifications disabled" in capsys.readouterr().out
    assert len(started) == 1

    monkeypatch.setattr(webui, "HAP", lambda ip: real(ip, port=1, timeout=1))
    assert webui.main(["127.0.0.1", "--port", "0", "--no-push"]) == 0
    assert "could not connect" in capsys.readouterr().err


def test_main_demo_starts_the_mock(monkeypatch, capsys):
    class Server:
        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(webui, "ThreadingHTTPServer", lambda address, handler: Server())
    import mock_hap

    spawned = []
    monkeypatch.setattr(mock_hap, "serve_in_thread",
                        lambda bind, port: spawned.append((bind, port)))
    monkeypatch.setattr(webui, "HAP", lambda ip: hap_client.HAP(ip, port=1, timeout=1))
    assert webui.main(["--demo", "--no-push"]) == 0
    assert spawned == [("127.0.0.1", 60200)]
    assert "Demo mode" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        webui.main(["--no-push"])  # neither an ip nor --demo


def test_parser_defaults():
    args = webui.build_parser().parse_args(["--demo"])
    assert args.port == webui.DEFAULT_HTTP_PORT and args.ip is None and args.demo
    with pytest.raises(SystemExit):
        webui.build_parser().parse_args(["--port", "x"])
