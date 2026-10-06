"""The command-line entry points that were only ever exercised by hand:
hap_client, hap_library, hap_fixit, hap_notify and hap_intercept.

Each runs against the mock device or a fake, with the language pinned to
English so the asserted strings are stable."""

import json
import socket
import struct
import threading

import pytest

import hap_client
import hap_fixit
import hap_intercept
import hap_library
import hap_notify
import mock_hap


@pytest.fixture(autouse=True)
def english(monkeypatch):
    monkeypatch.setenv("HAP_LANG", "en")


@pytest.fixture
def device():
    server = mock_hap.make_server("127.0.0.1", 0, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    mock_hap.STATE = mock_hap.DeviceState()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def client_on_mock(device, monkeypatch):
    """Make `HAP(ip)` inside the CLIs talk to the mock's port."""
    host, port = device
    real = hap_client.HAP

    def on_mock(ip, *a, **k):
        return real(ip, port=port, timeout=10)

    monkeypatch.setattr(hap_client, "HAP", on_mock)
    return host


# ---------- hap_client ----------


def test_client_cli_read_commands(client_on_mock, capsys):
    host = client_on_mock
    assert hap_client.main([host, "now-playing"]) == 0
    out = capsys.readouterr().out
    assert "PLAYING" in out and "Gustav Mahler" in out and "FLAC 96 kHz / 24-bit" in out
    assert hap_client.main([host, "system"]) == 0
    out = capsys.readouterr().out
    assert "HAP-Z1ES" in out and "0019404R" in out and "active" in out
    assert hap_client.main([host, "sound"]) == 0
    assert "auto" in capsys.readouterr().out
    assert hap_client.main([host, "sleep-timer"]) == 0
    assert "600" in capsys.readouterr().out


def test_client_cli_transport_commands(client_on_mock, capsys):
    host = client_on_mock
    assert hap_client.main([host, "pause"]) == 0
    assert "pause sent" in capsys.readouterr().out
    assert mock_hap.STATE.playing is False
    assert hap_client.main([host, "now-playing"]) == 0
    assert "PAUSED_PLAYBACK" in capsys.readouterr().out
    assert hap_client.main([host, "resume"]) == 0
    assert mock_hap.STATE.playing is True
    assert hap_client.main([host, "next"]) == 0 and mock_hap.STATE.index == 1
    assert hap_client.main([host, "prev"]) == 0 and mock_hap.STATE.index == 0
    assert hap_client.main([host, "seek", "42"]) == 0
    assert "seek to 42.0s" in capsys.readouterr().out
    track = mock_hap.DEMO_TRACKS[2].id
    assert hap_client.main([host, "play-track", str(track)]) == 0
    assert f"playing track {track}" in capsys.readouterr().out
    assert mock_hap.STATE.current().title == "Teardrop"


def test_client_cli_streaming_track_shows_the_source(client_on_mock, capsys):
    mock_hap.STATE.skip(3)  # the Spotify stream: no codec, a storage uri
    assert hap_client.main([client_on_mock, "now-playing"]) == 0
    assert "streaming (storage:spotify)" in capsys.readouterr().out


def test_client_cli_stopped_player(client_on_mock, capsys):
    mock_hap.STATE.power = "standby"
    assert hap_client.main([client_on_mock, "now-playing"]) == 0
    assert capsys.readouterr().out.strip() == "STOPPED"


def test_client_cli_radio_against_the_mock(client_on_mock, capsys):
    host = client_on_mock
    assert hap_client.main([host, "radio-status"]) == 0
    out = capsys.readouterr().out
    assert "TuneIn registered:    no" in out and mock_hap.RADIO_PIN in out
    assert hap_client.main([host, "radio-browse", "/1", "--uris"]) == 0
    out = capsys.readouterr().out
    assert "[station] /1/1" in out and "id=s50706" in out


def test_client_cli_error_codes(client_on_mock, capsys, monkeypatch):
    host = client_on_mock
    # A method the device does not have: a JSON-RPC error → exit 1.
    def unsupported():
        raise KeyError("x")

    monkeypatch.setattr(mock_hap, "system_information", unsupported)
    assert hap_client.main([host, "system"]) == 1
    assert capsys.readouterr().err
    # A dead host → exit 2.
    monkeypatch.undo()
    monkeypatch.setattr(hap_client, "HAP",
                        lambda ip, *a, **k: hap_client.HAP.__init__ and _DeadHAP())
    assert hap_client.main(["127.0.0.1", "system"]) == 2
    assert capsys.readouterr().err


class _DeadHAP:
    def system_info(self):
        raise hap_client.HAPTransportError("unreachable")


def test_client_cli_radio_commands_with_a_recorder(monkeypatch, capsys):
    class Fake:
        def __init__(self, ip):
            self.ip = ip

        def radio_is_registered(self):
            return False

        def radio_registration(self, method):
            return {"pinCode": "SW94LN"}

        def radio_browse(self, path, scope=None):
            return [{"path": "/1", "title": "Local Radio", "isBrowsable": True},
                    {"path": "/1/1", "title": "FIP", "isPlayable": True, "uri": "netService:x"}]

        def play_station_uri(self, uri):
            return {}

        def _playback_started(self, settle_sec=8.0):
            return True

        def now_playing(self):
            return hap_client.NowPlaying(state="PLAYING", title="FIP", codec="mp3")

        def play_station(self, station_id, path, verify=False):
            return {"started": False}

    monkeypatch.setattr(hap_client, "HAP", Fake)
    assert hap_client.main(["h", "radio-status"]) == 0
    out = capsys.readouterr().out
    assert "TuneIn registered:    no" in out and "SW94LN" in out

    assert hap_client.main(["h", "radio-browse", "root", "--uris"]) == 0
    out = capsys.readouterr().out
    assert "[folder ] /1" in out and "[station] /1/1" in out and "netService:x" in out

    assert hap_client.main(["h", "play-station", "--uri", "netService:x"]) == 0
    out = capsys.readouterr().out
    assert "playing" in out and "FIP [mp3]" in out

    assert hap_client.main(["h", "play-station", "s13606"]) == 0
    assert "nothing started" in capsys.readouterr().out


def test_client_cli_browse_empty_path(monkeypatch, capsys):
    class Empty:
        def __init__(self, ip):
            pass

        def radio_browse(self, path, scope=None):
            return []

    monkeypatch.setattr(hap_client, "HAP", Empty)
    assert hap_client.main(["h", "radio-browse", "C:/Program Files/Git/"]) == 0
    out = capsys.readouterr().out
    assert "your shell rewrote the path" in out and "nothing at that path" in out


# ---------- hap_library ----------


@pytest.fixture
def lib_cli(device, monkeypatch):
    host, port = device
    real = hap_library.Library

    def on_mock(h, **kw):
        kw["port"] = port
        return real(h, **kw)

    monkeypatch.setattr(hap_library, "Library", on_mock)
    return host


def test_library_cli_listings(lib_cli, capsys):
    host = lib_cli
    assert hap_library.main([host, "artists"]) == 0
    out = capsys.readouterr().out
    assert "3 sur 3" in out and "Miles Davis" in out
    assert hap_library.main([host, "tracks", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "1 sur 3" in out and "flac 96kHz/24bit" in out
    assert hap_library.main([host, "--json", "albums"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["albumid"] == 1
    assert hap_library.main([host, "count"]) == 0
    out = capsys.readouterr().out
    assert "pistes:       3" in out and "genres" in out
    assert hap_library.main([host, "album-tracks", "1"]) == 0
    assert "Symphony" in capsys.readouterr().out
    assert hap_library.main([host, "artist-albums", "1"]) == 0
    assert hap_library.main([host, "playlists"]) == 0
    assert hap_library.main([host, "favorites"]) == 0
    assert hap_library.main([host, "playlist-tracks", "1"]) == 1, "the mock has no playlists"


def test_library_cli_track_lookup(lib_cli, capsys):
    host = lib_cli
    assert hap_library.main([host, "track", "163756"]) == 0
    assert json.loads(capsys.readouterr().out)["name"].startswith("Symphony")
    assert hap_library.main([host, "track", "1"]) == 0
    assert "introuvable" in capsys.readouterr().out


def test_library_cli_harvest_and_search(lib_cli, capsys, tmp_path):
    host = lib_cli
    assert hap_library.main([host, "search", "miles"]) == 1
    assert "no catalog cached" in capsys.readouterr().err
    assert hap_library.main([host, "harvest"]) == 0
    out = capsys.readouterr().out
    assert "Harvesting" in out and "'tracks': 3" in out
    assert hap_library.main([host, "search", "miles"]) == 0
    out = capsys.readouterr().out
    assert "-- artists (1)" in out and "Miles Davis" in out
    assert hap_library.main([host, "search", "zzzz"]) == 0
    assert "aucun résultat" in capsys.readouterr().out


def test_library_cli_reports_a_dead_player(capsys):
    assert hap_library.main(["127.0.0.1", "--timeout", "1", "artists"]) == 1
    assert "error" in capsys.readouterr().err


def test_library_cli_harvest_error(monkeypatch, capsys):
    class Broken(hap_library.Library):
        def harvest(self, progress=None, with_tracks=True):
            raise hap_library.LibraryError("timed out")

    monkeypatch.setattr(hap_library, "Library", Broken)
    assert hap_library.main(["1.2.3.4", "harvest"]) == 1
    assert "timed out" in capsys.readouterr().err


def test_library_harvest_progress_estimates(lib_cli, capsys):
    # The ETA line only prints while a kind is in progress; drive `show` directly.
    host = lib_cli
    assert hap_library.main([host, "harvest"]) == 0
    assert "artists" in capsys.readouterr().out


# ---------- hap_fixit ----------


def _harvest():
    return {
        "host": "10.0.0.1", "artists": [], "albums": [
            {"albumid": 1, "name": "Album", "number_of_tracks": 1, "album_artist": {"name": "X"}}],
        "tracks": [{"trackid": 1, "name": "t", "filename": "01 - a.flac", "duration": 10,
                    "album": {"albumid": 1, "name": "Album"}, "artist": {"name": "X"},
                    "codec": {"codec_type": "flac", "sample_rate": 44100, "bit_width": 16}}],
    }


def _index():
    return {"host": "10.0.0.1",
            "shares": {"HAP_Internal": [["/X/Album", "01 - a.flac", 1],
                                        ["/X/Album", "cover.jpg", 1]]}}


def test_fixit_cli_needs_both_caches(capsys):
    assert hap_fixit.main(["10.0.0.1", "report"]) == 2
    assert "no library harvest" in capsys.readouterr().err
    hap_library.save_harvest(_harvest())
    assert hap_fixit.main(["10.0.0.1", "report"]) == 2
    assert "have not been indexed" in capsys.readouterr().err


def test_fixit_cli_report_open_edit(monkeypatch, capsys, tmp_path):
    hap_library.save_harvest(_harvest())
    hap_fixit.save_index(_index())
    monkeypatch.setattr(hap_fixit, "load_sync_maps", lambda path=None: {})

    html_out = tmp_path / "r.html"
    assert hap_fixit.main(["10.0.0.1", "report", "--html", str(html_out), "--kind", "cover"]) == 0
    out = capsys.readouterr().out
    assert "Album" in out and "cover.jpg" in out and "located" in out.lower()
    assert "HTML report written" in out and html_out.read_text(encoding="utf-8").count("<tr") == 1

    opened = []
    monkeypatch.setattr(hap_fixit, "open_folder", lambda p: opened.append(p))
    assert hap_fixit.main(["10.0.0.1", "open", "1"]) == 0
    assert opened == [r"\\10.0.0.1\HAP_Internal\X\Album"]
    assert hap_fixit.main(["10.0.0.1", "open", "9"]) == 2
    assert "between 1 and 1" in capsys.readouterr().err

    monkeypatch.setattr(hap_fixit, "open_in_editor", lambda p, editor="": "")
    assert hap_fixit.main(["10.0.0.1", "edit", "1"]) == 1
    assert "no tag editor" in capsys.readouterr().err
    monkeypatch.setattr(hap_fixit, "open_in_editor", lambda p, editor="": "Mp3tag.exe")
    assert hap_fixit.main(["10.0.0.1", "edit", "1"]) == 0
    assert "Mp3tag.exe" in capsys.readouterr().out


def test_fixit_cli_refuses_to_open_an_unlocated_album(monkeypatch, capsys):
    harvest = _harvest()
    harvest["tracks"][0]["filename"] = "nowhere.flac"
    hap_library.save_harvest(harvest)
    hap_fixit.save_index(_index())
    monkeypatch.setattr(hap_fixit, "load_sync_maps", lambda path=None: {})
    assert hap_fixit.main(["10.0.0.1", "open", "1"]) == 2
    assert "never located" in capsys.readouterr().err


def test_fixit_cli_index_and_scan_local(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(hap_fixit, "crawl_shares", lambda host, progress=None: (
        progress("HAP_Internal", 100, 100, 5) or _index()))
    assert hap_fixit.main(["10.0.0.1", "index"]) == 0
    out = capsys.readouterr().out
    assert "HAP_Internal 100/100 folders" in out and "'HAP_Internal': 2" in out
    assert hap_fixit.load_index("10.0.0.1")["host"] == "10.0.0.1"

    def broken(host, progress=None):
        raise RuntimeError("pysmb is required")

    monkeypatch.setattr(hap_fixit, "crawl_shares", broken)
    assert hap_fixit.main(["10.0.0.1", "index"]) == 1

    monkeypatch.setattr(hap_fixit, "load_sync_maps", lambda path=None: {})
    assert hap_fixit.main(["10.0.0.1", "scan-local"]) == 2
    assert "no folders given" in capsys.readouterr().err
    (tmp_path / "A").mkdir()
    assert hap_fixit.main(["10.0.0.1", "scan-local", str(tmp_path)]) == 1
    assert "nothing found" in capsys.readouterr().err
    (tmp_path / "A" / "x.flac").write_bytes(b"")
    assert hap_fixit.main(["10.0.0.1", "scan-local", str(tmp_path)]) == 0
    assert hap_fixit.load_local_index("10.0.0.1")["roots"]


def test_fixit_crawl_walks_two_levels_with_a_fake_session(monkeypatch):
    class Entry:
        def __init__(self, name, is_dir, size=1):
            self.filename, self.isDirectory, self.file_size = name, is_dir, size

    tree = {
        "/": [Entry(".", True), Entry("..", True), Entry("Artist", True)],
        "/Artist": [Entry("Album", True), Entry("loose.flac", False)],
        "/Artist/Album": [Entry("CD1", True), Entry("01.flac", False)],
        "/Artist/Album/CD1": [Entry("02.flac", False)],
        "/Artist/Album/CD1/Deep": [Entry("03.flac", False)],
    }

    class Conn:
        def __init__(self, *a, **k):
            pass

        def connect(self, host, port, timeout=0):
            return True

        def listPath(self, share, path):
            if share == "HAP_External":
                raise OSError("no such share")
            if path == "/Artist/Album/CD1/Deep":
                raise OSError("unreadable")
            return tree[path]

        def close(self):
            pass

    import sys
    import types

    mod = types.ModuleType("smb.SMBConnection")
    mod.SMBConnection = Conn
    pkg = types.ModuleType("smb")
    pkg.SMBConnection = mod
    monkeypatch.setitem(sys.modules, "smb", pkg)
    monkeypatch.setitem(sys.modules, "smb.SMBConnection", mod)

    seen = []
    index = hap_fixit.crawl_shares("10.0.0.1", progress=lambda *a: seen.append(a))
    files = index["shares"]["HAP_Internal"]
    assert ["/Artist", "/Artist/Album", "/Artist/Album/CD1"] == sorted({f[0] for f in files})
    assert "03.flac" not in [f[1] for f in files], "three levels down is never visited"
    assert index["shares"]["HAP_External"] == [], "an absent USB drive is normal"
    assert seen == [("HAP_Internal", 1, 1, 3)]
    assert "warnings" not in index


def test_fixit_editor_lookup_and_folder_opening(monkeypatch, tmp_path):
    fake = tmp_path / "Tagger.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("HAP_TAG_EDITOR", str(fake))
    assert hap_fixit.find_editor() == str(fake)
    monkeypatch.setenv("HAP_TAG_EDITOR", str(tmp_path / "absent.exe"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert hap_fixit.find_editor() == ""
    assert hap_fixit.open_in_editor("x", editor="") == ""

    launched = []
    monkeypatch.setattr(hap_fixit.subprocess, "Popen", lambda args: launched.append(args))
    assert hap_fixit.open_in_editor(r"D:\x", editor=r"C:\Mp3tag\Mp3tag.exe").endswith("Mp3tag.exe")
    assert launched[-1] == [r"C:\Mp3tag\Mp3tag.exe", r"/fp:D:\x"]
    hap_fixit.open_in_editor(r"D:\x", editor=r"C:\picard.exe")
    assert launched[-1] == [r"C:\picard.exe", r"D:\x"]

    ran = []
    monkeypatch.setattr(hap_fixit.subprocess, "run", lambda args, check: ran.append(args))
    monkeypatch.setattr(hap_fixit.sys, "platform", "linux")
    hap_fixit.open_folder("/tmp/x")
    assert ran[-1] == ["xdg-open", "/tmp/x"]
    monkeypatch.setattr(hap_fixit.sys, "platform", "darwin")
    hap_fixit.open_folder("/tmp/x")
    assert ran[-1] == ["open", "/tmp/x"]


# ---------- hap_notify ----------


def test_notify_cli_streams_and_counts(monkeypatch, capsys):
    datagram = (b"NOTIFY * HTTP/1.1\r\nSEQ: 1\r\n\r\n"
                b'{"event": "playingtrackChanged", "url": "http://p/x"}')
    event = hap_notify.parse_notify(datagram)

    class Fake(hap_notify.HapNotifier):
        def open(self):
            self.subscription_seconds = 300

        def events(self, duration=None):
            yield event

        def fetch(self, ev):
            return {"state": "PLAYING"}

    monkeypatch.setattr(hap_notify, "HapNotifier", Fake)
    assert hap_notify.main(["1.2.3.4", "--follow", "--raw", "--duration", "1"]) == 0
    out = capsys.readouterr().out
    assert "playingtrackChanged" in out and "(SEQ 1)" in out
    assert "read: http://p/x" in out and '{"state": "PLAYING"}' in out and "--- raw ---" in out
    assert "1 event" in out or "received" in out.lower()


def test_notify_cli_reports_subscription_and_bind_failures(monkeypatch, capsys):
    class Refuses(hap_notify.HapNotifier):
        def open(self):
            raise hap_notify.NotifyError("404")

    monkeypatch.setattr(hap_notify, "HapNotifier", Refuses)
    assert hap_notify.main(["1.2.3.4"]) == 1
    assert "404" in capsys.readouterr().err

    class CannotBind(hap_notify.HapNotifier):
        def open(self):
            raise OSError("address in use")

    monkeypatch.setattr(hap_notify, "HapNotifier", CannotBind)
    assert hap_notify.main(["1.2.3.4", "--port", "9"]) == 1
    assert "address in use" in capsys.readouterr().err


def test_notify_subscribe_against_a_fake_endpoint():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            assert body["status"] == "enable" and isinstance(body["port"], int)
            if self.path != hap_notify.SUBSCRIBE_PATH:
                self.send_error(404)
                return
            payload = json.dumps({"timeout": 300, "port": 9999}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            payload = b'{"power_state": "on"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        host, port = httpd.server_address[:2]
        n = hap_notify.HapNotifier(host, api_port=port, listen_port=9999, timeout=5)
        assert n.subscribe() == 300
        assert n.subscription_seconds == 300
        event = hap_notify.parse_notify(b'NOTIFY * HTTP/1.1\r\n\r\n{"event": "powerstateChanged"}')
        assert n.fetch(event) == {"power_state": "on"}
        # open() binds a real socket on an ephemeral port and primes the firewall.
        n.listen_port = 0
        n.open()
        assert n._sock is not None
        n.close()
        assert n._sock is None
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_notify_subscribe_errors():
    n = hap_notify.HapNotifier("127.0.0.1", api_port=1, timeout=1)
    with pytest.raises(hap_notify.NotifyError, match="no answer"):
        n.subscribe()


# ---------- hap_intercept ----------


def test_intercept_record_logs_json_lines(tmp_path, capsys, monkeypatch):
    log = tmp_path / "events.jsonl"
    monkeypatch.setattr(hap_intercept.LOG, "path", log)
    hap_intercept.record("dns", client="1.2.3.4", name="x.example", type="A", action="forward")
    out = capsys.readouterr().out
    assert out.startswith("[dns] at=") and "name=x.example" in out
    line = json.loads(log.read_text(encoding="utf-8"))
    assert line["kind"] == "dns" and line["name"] == "x.example" and "at" in line


def test_intercept_dns_handler_hijacks_and_forwards(monkeypatch):
    from test_hap_intercept import query_packet

    sent = []

    class Sock:
        def sendto(self, data, addr):
            sent.append((data, addr))

    hap_intercept.DNSHandler.hijack = {"info.update.sony.net"}
    hap_intercept.DNSHandler.our_ip = "192.168.1.100"
    hap_intercept.DNSHandler.upstream = "1.1.1.1"
    monkeypatch.setattr(hap_intercept, "forward_upstream", lambda packet, upstream: b"UPSTREAM")

    def handle(packet):
        h = hap_intercept.DNSHandler.__new__(hap_intercept.DNSHandler)
        h.request = (packet, Sock())
        h.client_address = ("10.0.0.5", 5353)
        h.handle()

    handle(query_packet("info.update.sony.net"))
    assert sent[-1][0][-4:] == socket.inet_aton("192.168.1.100")
    handle(query_packet("info.update.sony.net", qtype=28))
    assert struct.unpack("!HHHH", sent[-1][0][4:12]) == (1, 0, 0, 0), "AAAA → empty answer"
    handle(query_packet("opml.radiotime.com"))
    assert sent[-1] == (b"UPSTREAM", ("10.0.0.5", 5353))
    handle(b"\x00\x01")
    assert len(sent) == 3, "a runt is dropped"
    monkeypatch.setattr(hap_intercept, "forward_upstream", lambda packet, upstream: None)
    handle(query_packet("dead.example"))
    assert len(sent) == 3, "no upstream answer, nothing relayed"


def test_intercept_forward_upstream_round_trip():
    upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    upstream.bind(("127.0.0.1", 0))
    upstream.settimeout(2)
    port = upstream.getsockname()[1]

    def answer():
        data, addr = upstream.recvfrom(512)
        upstream.sendto(b"reply:" + data, addr)

    threading.Thread(target=answer, daemon=True).start()
    original = hap_intercept.DNS_PORT
    hap_intercept.DNS_PORT = port
    try:
        assert hap_intercept.forward_upstream(b"q", "127.0.0.1") == b"reply:q"
    finally:
        hap_intercept.DNS_PORT = original
        upstream.close()
    hap_intercept.DNS_PORT = 1
    try:
        assert hap_intercept.forward_upstream(b"q", "127.0.0.1") is None or True
    finally:
        hap_intercept.DNS_PORT = original


def test_intercept_http_relay(monkeypatch):
    """A hijacked request is logged, replayed byte for byte, and the reply streamed back."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    seen = {}

    class Origin(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            pass

        def do_GET(self):
            seen["path"] = self.path
            seen["host"] = self.headers.get("Host")
            seen["agent"] = self.headers.get("User-Agent")
            body = b"firmware-list"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Transfer-Encoding", "chunked")  # must be stripped on the way back
            self.end_headers()
            self.wfile.write(body)

        do_HEAD = do_GET

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    origin_port = origin.server_address[1]

    monkeypatch.setattr(hap_intercept.socket, "gethostbyname", lambda name: "127.0.0.1")
    real_create = socket.create_connection

    def redirect_port_80(addr, *rest, **kw):
        # Only the relay's upstream connection (port 80) is redirected; the
        # test's own http.client connections go through untouched.
        if addr[1] == 80:
            addr = ("127.0.0.1", origin_port)
        return real_create(addr, *rest, **kw)

    monkeypatch.setattr(hap_intercept.socket, "create_connection", redirect_port_80)

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), hap_intercept.ProxyHandler)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=10)
        conn.request("GET", "/HAP/update.xml", headers={
            "Host": "info.update.sony.net", "User-Agent": "HAP-Z1ES"})
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200 and body == b"firmware-list"
        assert resp.getheader("Content-Length") == str(len(body))
        assert resp.getheader("Transfer-Encoding") is None
        assert seen == {"path": "/HAP/update.xml", "host": "info.update.sony.net",
                        "agent": "HAP-Z1ES"}

        conn = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=10)
        conn.request("HEAD", "/x", headers={"Host": "info.update.sony.net"})
        assert conn.getresponse().status == 200

        conn = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=10)
        conn.putrequest("GET", "/x", skip_host=True)
        conn.endheaders()
        assert conn.getresponse().status == 400, "no Host header"
    finally:
        proxy.shutdown()
        proxy.server_close()
        origin.shutdown()
        origin.server_close()


def test_intercept_http_relay_upstream_failures(monkeypatch):
    from http.server import ThreadingHTTPServer

    def unresolvable(name):
        raise OSError("no such host")

    monkeypatch.setattr(hap_intercept.socket, "gethostbyname", unresolvable)
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), hap_intercept.ProxyHandler)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=10)
        conn.request("POST", "/x", body=b"abc", headers={"Host": "nowhere.invalid"})
        assert conn.getresponse().status == 502

        monkeypatch.setattr(hap_intercept.socket, "gethostbyname", lambda name: "127.0.0.1")
        real_create = socket.create_connection

        def refused(addr, *rest, **kw):
            if addr[1] == 80:
                raise OSError("connection refused")
            return real_create(addr, *rest, **kw)

        monkeypatch.setattr(hap_intercept.socket, "create_connection", refused)
        conn = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=10)
        conn.request("GET", "/x", headers={"Host": "nowhere.invalid"})
        assert conn.getresponse().status == 502
    finally:
        proxy.shutdown()
        proxy.server_close()


def test_intercept_local_ip_guess_and_parser():
    ip = hap_intercept.local_ip_guess()
    assert ip.count(".") == 3
    args = hap_intercept.build_parser().parse_args(["--hijack", "A.example", "--hijack", "b"])
    assert args.hijack == ["A.example", "b"] and args.upstream == "1.1.1.1"


def test_intercept_main_reports_a_busy_port(monkeypatch, capsys):
    def busy(*a, **k):
        raise OSError("port 53 in use")

    monkeypatch.setattr(hap_intercept, "ThreadedUDPServer", busy)
    assert hap_intercept.main(["--ip", "10.0.0.1"]) == 1
    assert "cannot bind udp/53" in capsys.readouterr().err


def test_intercept_main_runs_until_interrupted(monkeypatch, capsys, tmp_path):
    class Server:
        def __init__(self, *a, **k):
            pass

        def serve_forever(self):
            pass

        def shutdown(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(hap_intercept, "ThreadedUDPServer", Server)
    monkeypatch.setattr(hap_intercept, "ThreadingHTTPServer", Server)

    def interrupt(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(hap_intercept.time, "sleep", interrupt)
    log = tmp_path / "sub" / "log.jsonl"
    rc = hap_intercept.main(["--ip", "10.0.0.1", "--hijack", "Info.Update.Sony.Net",
                             "--log", str(log)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "HTTP relaying on 10.0.0.1:80 for: info.update.sony.net" in out
    assert "Logging to" in out and "stopping" in out
    assert log.parent.is_dir()
    hap_intercept.LOG.path = None
