"""The mock's newer corners: push notifications, the contentplayer REST surface
and the two documented gotchas — and the two clients that depend on them,
`smoke_live.py` and the web UI's PushWatcher, driven end to end.

If the real player ever changes one of these behaviours, docs/16-gotchas.md
and this file have to change together.
"""

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

import hap_client
import hap_notify
import mock_hap
import smoke_live
import webui


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


def _get(base, path, **headers):
    req = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


# ---------- the gotchas ----------


def test_expect_100_continue_is_417(device):
    host, port = device
    req = hap_client.rpc_request(hap_client.rpc_url(host, "avContent", port),
                                 "getPlayingContentInfo", "1.2")
    req.add_header("Expect", "100-continue")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 417


def test_preflight_echoes_origin_but_never_allow_headers(device):
    host, port = device
    req = urllib.request.Request(f"http://{host}:{port}/sony/avContent", method="OPTIONS")
    req.add_header("Origin", "http://example.com")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.headers.get("Access-Control-Allow-Origin") == "http://example.com"
        assert r.headers.get("Access-Control-Allow-Headers") is None
    req = urllib.request.Request(f"http://{host}:{port}/sony/avContent", method="OPTIONS")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.headers.get("Access-Control-Allow-Origin") is None


# ---------- contentplayer REST ----------


def test_contentplayer_surface(device):
    host, port = device
    base = f"http://{host}:{port}/sony/contentplayer/v100"
    assert json.loads(_get(base, "/powerstate")[2]) == {"power_state": "on"}
    status, _, body = _get(base, "/settings/sound/dsee")
    assert status == 200 and json.loads(body)["setting"] == {"target": "dsee", "value": "auto"}
    assert _get(base, "/volumelevel")[0] == 500, "a Z1ES has no volume stage"
    info = json.loads(_get(base, "/playinginfo")[2])
    assert info["state"] == "PLAYING" and info["title"]
    queue = json.loads(_get(base, "/playqueue")[2])
    assert len(queue["queue"]) == 4 and queue["index"] == 0
    assert _get(base, "/settings/sound/nope")[0] == 404
    assert _get(base, "/nothing")[0] == 404
    mock_hap.STATE.power = "standby"
    assert json.loads(_get(base, "/powerstate")[2]) == {"power_state": "standby"}


# ---------- push ----------


def test_subscribe_validates_the_body(device):
    host, port = device
    url = f"http://{host}:{port}/sony/notification/status"

    def post(payload):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    assert post({"status": "enable", "port": 9999}) == (200, {"timeout": 300, "port": 9999})
    assert post({"status": "disable", "port": 9999})[0] == 400
    assert post({"status": "enable", "port": "x"})[0] == 400
    assert post({"status": "enable", "port": 70000})[0] == 400
    assert post([1, 2])[0] == 400
    assert ("127.0.0.1", 9999) in mock_hap.STATE.subscribers


def test_every_change_is_pushed_three_times_under_one_seq(device):
    host, port = device
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(2)
    lport = listener.getsockname()[1]
    try:
        mock_hap.subscribe("127.0.0.1", lport)
        hap = hap_client.HAP(host, port=port, timeout=10)
        hap.next_track()
        datagrams = [listener.recv(4096) for _ in range(3)]
        events = [hap_notify.parse_notify(d) for d in datagrams]
        assert all(e is not None for e in events)
        assert {e.name for e in events} == {"playingtrackChanged"}
        assert {e.seq for e in events} == {1}
        assert events[0].url == f"http://{host}:{port}/sony/contentplayer/v100/playinginfo"
        assert events[0].host_uuid == mock_hap.HOST_UUID
        tracker = hap_notify.SeqTracker()
        assert [tracker.is_new(e) for e in events] == [True, False, False]

        hap.standby()
        assert hap_notify.parse_notify(listener.recv(4096)).name == "powerstateChanged"
        # A read-only call pushes nothing.
        mock_hap.STATE.seq = 0
        hap.now_playing()
        assert mock_hap.push_event("getPlayingContentInfo", "h") == 0
    finally:
        listener.close()


def test_expired_subscribers_are_dropped(device):
    mock_hap.STATE.subscribers[("127.0.0.1", 1)] = time.monotonic() - 1
    assert mock_hap.push_event("setPlayNextContent", "h") == 0
    assert mock_hap.STATE.subscribers == {}


def test_a_real_notifier_receives_the_mocks_events(device):
    host, port = device
    with hap_notify.HapNotifier(host, api_port=port, listen_port=0, timeout=5) as n:
        assert n.subscription_seconds == 300
        assert n.listen_port != 0, "the OS-picked port is what the player was told"
        hap_client.HAP(host, port=port, timeout=10).toggle_playback()
        got = next(iter(n.events(duration=3)), None)
        assert got is not None and got.name == "playinginfoChanged"
        assert n.fetch(got)["state"] == "PAUSED_PLAYBACK"


def test_push_watcher_end_to_end(device):
    host, port = device
    original_notifier = webui.hap_notify.HapNotifier

    class OnMockPort(original_notifier):
        def __init__(self, ip, *, listen_port=9999, **kw):
            super().__init__(ip, api_port=port, listen_port=0, timeout=5)

    webui.hap_notify.HapNotifier = OnMockPort
    watcher = webui.PushWatcher(host)
    try:
        watcher.start()
        for _ in range(100):
            if watcher.active:
                break
            time.sleep(0.05)
        assert watcher.active, watcher.last_error
        hap_client.HAP(host, port=port, timeout=10).next_track()
        assert watcher.wait_for_change(since=0, timeout=5) >= 1
    finally:
        webui.hap_notify.HapNotifier = original_notifier


# ---------- smoke_live against the mock ----------


def test_smoke_passes_every_read_only_check_against_the_mock(device):
    host, port = device
    smoke = smoke_live.build(host, include_writes=False, port=port)
    failed = [(r.name, r.detail) for r in smoke.failed]
    assert failed == []
    names = [r.name for r in smoke.results]
    assert "Expect: 100-continue still returns 417" in names
    assert "CORS preflight still omits Allow-Headers" in names
    skipped = [r.name for r in smoke.results if r.skipped]
    assert skipped == ["REST volumelevel answers or 500s as expected"], "a Z1ES skips volume"


def test_smoke_idempotent_write_round_trips(device):
    host, port = device
    smoke = smoke_live.build(host, include_writes=True, port=port)
    assert smoke.failed == []
    assert smoke.results[-1].name == "idempotent sound write round-trips"
    assert mock_hap.STATE.sound["dsee"] == "auto", "written back unchanged"


def test_smoke_reports_failures_instead_of_crashing(device, monkeypatch):
    host, port = device
    monkeypatch.setattr(mock_hap, "system_information",
                        lambda: {"model": "", "version": ""})
    smoke = smoke_live.build(host, include_writes=False, port=port)
    names = [r.name for r in smoke.failed]
    assert "system_info returns a model and firmware" in names
    assert any("came back empty" in r.detail for r in smoke.failed)


def test_smoke_main_text_and_json(device, capsys, monkeypatch):
    host, port = device
    monkeypatch.setattr(smoke_live, "PAUSE_BETWEEN_CHECKS", 0)
    assert smoke_live.main([host, "--port", str(port)]) == 0
    out = capsys.readouterr().out
    assert "live smoke test against" in out and "[ok  ]" in out and "0 failed" in out
    assert smoke_live.main([host, "--port", str(port), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["failed"] == 0 and report["skipped"] == 1 and report["passed"] > 5
    assert smoke_live.main(["127.0.0.1", "--port", "1"]) == 1
    assert "cannot reach" in capsys.readouterr().err


def test_smoke_main_exit_code_on_failure(device, capsys, monkeypatch):
    host, port = device
    monkeypatch.setattr(smoke_live, "PAUSE_BETWEEN_CHECKS", 0)
    monkeypatch.setattr(mock_hap, "system_information", lambda: {})
    assert smoke_live.main([host, "--port", str(port)]) == 1
    assert "[FAIL]" in capsys.readouterr().out
