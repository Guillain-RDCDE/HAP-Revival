"""The plumbing every tool shares: Wake-on-LAN, the TCP probe, JSON files and
capture files. Each of these used to exist in two or three copies."""

import json
import socket
import threading

import pytest

import hap_common

# ---------- Wake-on-LAN ----------


@pytest.mark.parametrize("mac", ["zz:zz:zz:zz:zz:zz", "80:56:F2", "", "1234567890123"])
def test_send_wol_rejects_bad_mac(mac):
    with pytest.raises(ValueError):
        hap_common.send_wol(mac)


def test_wol_packet_shape():
    pkt = hap_common.wol_packet("80:56:F2:85:0E:27")
    mac_bytes = bytes.fromhex("8056F2850E27")
    assert pkt == b"\xff" * 6 + mac_bytes * 16
    assert len(pkt) == 6 + 6 * 16          # 102 bytes


@pytest.mark.parametrize("mac", ["80:56:F2:85:0E:27", "80-56-f2-85-0e-27", "8056F2850E27"])
def test_mac_to_bytes_accepts_every_spelling(mac):
    assert hap_common.mac_to_bytes(mac) == bytes.fromhex("8056F2850E27")


def test_normalize_mac():
    assert hap_common.normalize_mac(" 80-56-f2-85-0e-27 ") == "80:56:F2:85:0E:27"


def test_send_wol_broadcasts(monkeypatch):
    sent = {}

    class FakeSock:
        def setsockopt(self, *a):
            sent["broadcast"] = a

        def sendto(self, data, addr):
            sent["data"] = data
            sent["addr"] = addr

        def close(self):
            sent["closed"] = True

    monkeypatch.setattr(hap_common.socket, "socket", lambda *a, **k: FakeSock())
    hap_common.send_wol("80:56:F2:85:0E:27")

    assert sent["data"] == hap_common.wol_packet("80:56:F2:85:0E:27")
    assert sent["addr"] == ("255.255.255.255", 9)
    assert sent["broadcast"] == (socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    assert sent["closed"] is True


# ---------- TCP probe ----------


def test_tcp_port_open_against_a_loopback_listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert hap_common.tcp_port_open("127.0.0.1", port, timeout=2) is True
    finally:
        srv.close()
    assert hap_common.tcp_port_open("127.0.0.1", port, timeout=1) is False


def test_tcp_port_open_handles_an_unresolvable_host():
    assert hap_common.tcp_port_open("no-such-host.invalid", 1, timeout=1) is False


# ---------- JSON files ----------


def test_write_and_read_json_round_trip(tmp_path):
    target = tmp_path / "deep" / "cache.json"
    hap_common.write_json(target, {"name": "Dvořák", "n": 1})
    assert target.is_file()
    assert hap_common.read_json(target) == {"name": "Dvořák", "n": 1}
    # UTF-8 on disk, accents intact, regardless of the platform default encoding.
    assert "Dvořák" in target.read_bytes().decode("utf-8")


def test_read_json_tolerates_a_bom_and_garbage(tmp_path):
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + json.dumps({"host": "1.2.3.4"}).encode())
    assert hap_common.read_json(bom) == {"host": "1.2.3.4"}
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"{not json")
    assert hap_common.read_json(bad) is None
    assert hap_common.read_json(tmp_path / "absent.json") is None


def test_write_json_atomic_leaves_no_temp_file(tmp_path):
    target = tmp_path / "idx.json"
    hap_common.write_json(target, [1, 2, 3], atomic=True)
    assert hap_common.read_json(target) == [1, 2, 3]
    assert list(tmp_path.iterdir()) == [target]


def test_save_capture_stamps_tool_and_time(tmp_path):
    path = hap_common.save_capture("probe-x", {"devices": []}, tool="t/x.py", out_dir=tmp_path)
    assert path.parent == tmp_path
    assert path.name.startswith("probe-x-") and path.suffix == ".json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["tool"] == "t/x.py"
    assert data["devices"] == []
    assert "timestamp" in data


def test_utc_stamp_format():
    from datetime import datetime, timezone

    when = datetime(2026, 5, 25, 18, 39, 45, tzinfo=timezone.utc)
    assert hap_common.utc_stamp(when) == "20260525T183945Z"
    assert len(hap_common.utc_stamp()) == 16


# ---------- small helpers ----------


@pytest.mark.parametrize("n,expected", [
    (0, "0 B"), (512, "512 B"), (1023, "1023 B"),
    (1024, "1.0 KB"), (1536, "1.5 KB"),
    (1024 * 1024, "1.0 MB"), (1024 ** 3, "1.0 GB"), (1024 ** 4, "1.0 TB"),
    (5 * 1024 ** 4, "5.0 TB"),
])
def test_human_size(n, expected):
    assert hap_common.human_size(n) == expected


def test_safe_name():
    assert hap_common.safe_name("192.168.1.28__HAP_Internal") == "192.168.1.28__HAP_Internal"
    assert hap_common.safe_name("a b/c:d") == "a_b_c_d"


def test_force_utf8_stdio_is_harmless(capsys):
    hap_common.force_utf8_stdio()
    print("Dvořák — 日本語")
    assert "Dvořák" in capsys.readouterr().out


def test_constants_match_the_device():
    assert hap_common.API_PORT == 60200
    assert hap_common.UPNP_PORT == 60100
    assert hap_common.SHARES == ("HAP_Internal", "HAP_External")
    assert hap_common.CAPTURES_DIR.name == "captures"
    assert hap_common.USER_CACHE_DIR.name == ".hap-revival"


def test_threads_can_probe_concurrently():
    # scan_for_hap_hosts in the GUI runs hundreds of these at once.
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(hap_common.tcp_port_open("127.0.0.1", 1, 0.5)))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [False] * 8
