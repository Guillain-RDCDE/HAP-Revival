"""The LAN sweep behind the GUI's "Auto-detect" (now in discover.py, so it can
be exercised without tkinter), plus the SMB session and remote listing in
hap_sync with pysmb replaced by a fake."""

import sys
import threading
import types

import pytest

import discover
import hap_sync as core
import mock_hap

# ---------- subnet discovery ----------


def test_local_subnet_prefixes_skip_loopback_and_link_local(monkeypatch):
    monkeypatch.setattr(discover, "primary_lan_ip", lambda: "192.168.1.50")
    monkeypatch.setattr(discover.socket, "gethostbyname_ex",
                        lambda name: (name, [], ["127.0.0.1", "169.254.3.3", "10.0.0.7",
                                                "192.168.1.50"]))
    assert discover.local_subnet_prefixes() == ["192.168.1.", "10.0.0."]


def test_local_subnet_prefixes_survive_resolver_failures(monkeypatch):
    monkeypatch.setattr(discover, "primary_lan_ip", lambda: None)

    def boom(name):
        raise OSError("no resolver")

    monkeypatch.setattr(discover.socket, "gethostbyname_ex", boom)
    assert discover.local_subnet_prefixes() == []


def test_primary_lan_ip_is_an_address_or_none():
    ip = discover.primary_lan_ip()
    assert ip is None or ip.count(".") == 3


def test_scan_subnets_finds_the_open_port(monkeypatch):
    probed = []

    def fake_probe(host, port, timeout):
        probed.append(host)
        return host == "192.168.1.28"

    monkeypatch.setattr(discover, "tcp_port_open", fake_probe)
    assert discover.scan_subnets(["192.168.1."]) == ["192.168.1.28"]
    assert len(probed) == 254
    assert discover.scan_subnets([]) == []


def test_identify_confirms_a_hap_and_rejects_anything_else(monkeypatch):
    server = mock_hap.make_server("127.0.0.1", 0, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        host, port = server.server_address
        found = discover.identify(host, port)
        assert found is not None
        assert found.model == "HAP-Z1ES" and found.mac == "04:5D:4B:DE:AD:BE"
        monkeypatch.setattr(mock_hap, "system_information", lambda: {"model": "BRAVIA"})
        assert discover.identify(host, port) is None
    finally:
        server.shutdown()
        server.server_close()
    assert discover.identify("127.0.0.1", 1) is None


def test_identify_falls_back_to_arp_for_the_mac(monkeypatch):
    class Info:
        model, mac = "HAP-S1", ""

    class FakeHAP:
        def __init__(self, ip, port=0, timeout=0):
            pass

        def system_info(self):
            return Info()

    monkeypatch.setattr(discover, "HAP", FakeHAP)
    monkeypatch.setattr(discover, "arp_mac", lambda ip: "80:56:F2:85:0E:27")
    assert discover.identify("1.2.3.4").mac == "80:56:F2:85:0E:27"


def test_arp_mac_parses_the_table(monkeypatch):
    class Done:
        stdout = "Interface: 192.168.1.50\n  192.168.1.28   80-56-f2-85-0e-27   dynamic\n"

    monkeypatch.setattr(discover.subprocess, "run", lambda *a, **k: Done())
    assert discover.arp_mac("192.168.1.28") == "80:56:F2:85:0E:27"
    Done.stdout = "No ARP Entries Found"
    assert discover.arp_mac("192.168.1.28") == ""

    def missing(*a, **k):
        raise FileNotFoundError("arp")

    monkeypatch.setattr(discover.subprocess, "run", missing)
    assert discover.arp_mac("192.168.1.28") == ""


def test_find_hap_stops_at_the_first_confirmed_player(monkeypatch):
    monkeypatch.setattr(discover, "scan_subnets",
                        lambda prefixes, port: ["10.0.0.2", "10.0.0.3", "10.0.0.4"])
    asked = []

    def fake_identify(ip, port):
        asked.append(ip)
        return discover.FoundHap(ip, "HAP-Z1ES", "") if ip == "10.0.0.3" else None

    monkeypatch.setattr(discover, "identify", fake_identify)
    seen = []
    scan = discover.find_hap(prefixes=["10.0.0."], on_candidates=seen.append)
    assert scan.found.ip == "10.0.0.3"
    assert asked == ["10.0.0.2", "10.0.0.3"], "the fourth host is never asked"
    assert seen == [["10.0.0.2", "10.0.0.3", "10.0.0.4"]]


def test_find_hap_without_subnets_or_candidates(monkeypatch):
    monkeypatch.setattr(discover, "local_subnet_prefixes", lambda: [])
    scan = discover.find_hap()
    assert scan.prefixes == [] and scan.candidates == [] and scan.found is None
    monkeypatch.setattr(discover, "scan_subnets", lambda prefixes, port: [])
    scan = discover.find_hap(prefixes=["10.0.0."])
    assert scan.candidates == [] and scan.found is None


# ---------- hap_sync's SMB session, with pysmb faked ----------


class Entry:
    def __init__(self, name, is_dir, size=1):
        self.filename, self.isDirectory, self.file_size = name, is_dir, size


class FakeConnection:
    """A pysmb SMBConnection whose behaviour the test chooses via class attributes."""

    connect_on = {139}
    fail_paths: set = set()
    tree = {
        "/": [Entry(".", True), Entry("..", True), Entry("Artist", True)],
        "/Artist": [Entry("Album", True), Entry("loose.flac", False, 7)],
        "/Artist/Album": [Entry("01.flac", False, 10), Entry("cover.jpg", False, 2)],
    }
    instances: list = []

    def __init__(self, user, pwd, client, server, use_ntlm_v2=False, is_direct_tcp=False):
        self.direct = is_direct_tcp
        self.closed = False
        FakeConnection.instances.append(self)

    def connect(self, host, port, timeout=0):
        return port in self.connect_on

    def listPath(self, share, path):  # pysmb's spelling
        if path in self.fail_paths:
            raise OSError("desynced")
        return self.tree[path]

    def close(self):
        self.closed = True


@pytest.fixture
def fake_pysmb(monkeypatch):
    mod = types.ModuleType("smb.SMBConnection")
    mod.SMBConnection = FakeConnection
    pkg = types.ModuleType("smb")
    pkg.SMBConnection = mod
    monkeypatch.setitem(sys.modules, "smb", pkg)
    monkeypatch.setitem(sys.modules, "smb.SMBConnection", mod)
    FakeConnection.instances = []
    FakeConnection.connect_on = {139}
    FakeConnection.fail_paths = set()
    return FakeConnection


def test_smb_prefers_netbios_then_direct_tcp(fake_pysmb):
    smb = core.Smb("1.2.3.4")
    assert smb.conn is not None and smb.conn.direct is False, "139 first"
    fake_pysmb.connect_on = {445}
    smb.reconnect()
    assert smb.conn.direct is True and fake_pysmb.instances[0].closed
    smb.close()
    assert smb.conn is None
    smb.close()  # idempotent


def test_smb_reports_a_host_that_answers_on_neither_port(fake_pysmb):
    fake_pysmb.connect_on = set()
    with pytest.raises(core.SmbError, match=r"SMB connection to 1\.2\.3\.4 failed"):
        core.Smb("1.2.3.4")


def test_remote_index_walks_the_share(fake_pysmb):
    smb = core.Smb("1.2.3.4")
    progress = []
    index, skipped = core.remote_index(smb, "HAP_Internal", on_progress=progress.append)
    assert index == {"Artist/loose.flac": 7, "Artist/Album/01.flac": 10,
                     "Artist/Album/cover.jpg": 2}
    assert skipped == 0 and progress == [3]


def test_remote_index_reconnects_then_skips_an_unreadable_folder(fake_pysmb):
    smb = core.Smb("1.2.3.4")
    fake_pysmb.fail_paths = {"/Artist/Album"}
    index, skipped = core.remote_index(smb, "HAP_Internal")
    assert index == {"Artist/loose.flac": 7}
    assert skipped == 1
    assert len(fake_pysmb.instances) >= 2, "a failed listing reopens the session"


def test_ensure_dirs_creates_each_parent_once(fake_pysmb):
    created = []
    smb = core.Smb("1.2.3.4")
    smb.conn.createDirectory = lambda share, path: created.append(path)
    made: set = set()
    core.ensure_dirs(smb, "HAP_Internal", "A/B/c.flac", made)
    core.ensure_dirs(smb, "HAP_Internal", "A/B/d.flac", made)
    assert created == ["/A", "/A/B"]


def test_get_remote_scans_live_and_caches(fake_pysmb, tmp_path):
    cfg = {"host": "1.2.3.4", "_path": str(tmp_path / "hap_sync.json")}
    lazy = core.LazySmb("1.2.3.4")
    index, source = core.get_remote(cfg, lazy, "HAP_Internal", refresh=False)
    assert source.startswith("live scan, 3 files")
    assert core.load_cache(cfg, "HAP_Internal")["files"] == index
    _, source = core.get_remote(cfg, lazy, "HAP_Internal", refresh=False)
    assert source.startswith("cache ")
    fake_pysmb.fail_paths = {"/Artist"}
    _, source = core.get_remote(cfg, lazy, "HAP_Internal", refresh=True)
    assert "1 dirs unreadable" in source
    lazy.close()


def test_cli_list_and_refresh_commands(fake_pysmb, tmp_path, capsys):
    import json

    cfg = tmp_path / "hap_sync.json"
    cfg.write_text(json.dumps({"host": "1.2.3.4",
                               "maps": [{"local": str(tmp_path), "share": "HAP_Internal"}]}))
    assert core.main(["--config", str(cfg), "refresh"]) == 0
    assert "HAP_Internal: live scan, 3 files  -> cached" in capsys.readouterr().out
    assert core.main(["--config", str(cfg), "list", "HAP_Internal"]) == 0
    out = capsys.readouterr().out
    assert "3 files on HAP_Internal" in out and "Artist/Album/01.flac" in out
    # --only names a share no map feeds: nothing to refresh, and nothing claimed.
    assert core.main(["--config", str(cfg), "refresh", "--only", "HAP_External"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_cli_sync_transfers_through_the_fake_session(fake_pysmb, tmp_path, capsys):
    import json

    music = tmp_path / "music" / "Artist" / "Album"
    music.mkdir(parents=True)
    (music / "02.flac").write_bytes(b"new audio")
    (music / "01.flac").write_bytes(b"0123456789")  # same size as on the share
    cfg = tmp_path / "hap_sync.json"
    cfg.write_text(json.dumps({"host": "1.2.3.4",
                               "maps": [{"local": str(tmp_path / "music"),
                                         "share": "HAP_Internal"}]}))
    stored = []
    fake_pysmb.createDirectory = lambda self, share, path: None
    fake_pysmb.storeFile = lambda self, share, path, fp: stored.append((share, path, fp.read()))
    assert core.main(["--config", str(cfg), "sync"]) == 0
    out = capsys.readouterr().out
    assert stored == [("HAP_Internal", "/Artist/Album/02.flac", b"new audio")]
    assert "Done: 1 transferred, 0 failed" in out
    cached = core.load_cache({"host": "1.2.3.4", "_path": str(cfg)}, "HAP_Internal")
    assert cached["files"]["Artist/Album/02.flac"] == 9
    assert core.main(["--config", str(cfg), "sync"]) == 0
    assert "already in sync" in capsys.readouterr().out


def test_cli_check_uses_smb_doctor(fake_pysmb, tmp_path, capsys, monkeypatch):
    import json

    import smb_doctor

    cfg = tmp_path / "hap_sync.json"
    cfg.write_text(json.dumps({"host": "1.2.3.4",
                               "maps": [{"local": str(tmp_path), "share": "HAP_Internal"}]}))
    monkeypatch.setattr(smb_doctor, "diagnose", lambda host: [
        smb_doctor.Finding("pysmb", "transfer", smb_doctor.OK),
        smb_doctor.Finding("signing", "signing", smb_doctor.PROBLEM, fix_cmd="Set-X",
                           needs_admin=True)])
    monkeypatch.setattr(core, "tcp_port_open", lambda host, port, timeout=3.0: True)
    assert core.main(["--config", str(cfg), "check"]) == 0
    out = capsys.readouterr().out
    assert "Transfer (this tool): WORKS" in out and "admin required" in out
    assert "✓ ScalarWebAPI" in out
    monkeypatch.setattr(smb_doctor, "apply_fixes", lambda findings, on_log=None: (True, "done"))
    assert core.main(["--config", str(cfg), "check", "--fix"]) == 0
    assert "done" in capsys.readouterr().out
