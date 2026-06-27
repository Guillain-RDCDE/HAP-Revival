"""Pure-logic tests for the sync engine: the junk / format / classification
filtering that decides what reaches the HAP, plus the Wake-on-LAN packet.

This is the safety net for the rules in the README ("skips the junk", "skips
formats the HAP can't play") — the part a generic copy tool can't do."""

import socket

import pytest

import hap_sync as core


# ---------- is_junk ----------


@pytest.mark.parametrize("name", [
    "Thumbs.db", "THUMBS.DB", ".DS_Store", "desktop.ini",
    "._AppleDouble", "._cover.jpg",
    "track.flac.ffs_tmp", "album.part", "x.partial", "y.tmp", "z.crdownload",
    "scan.ffs_lock",
])
def test_is_junk_true(name):
    assert core.is_junk(name) is True


@pytest.mark.parametrize("name", [
    "01 - Song.flac", "cover.jpg", "folder.png", "notes.txt",
    "temple.flac",   # ends with 'le' not '._' — must not trip the AppleDouble rule
    "thumbs.dbx",    # not exactly thumbs.db
])
def test_is_junk_false(name):
    assert core.is_junk(name) is False


# ---------- classify ----------


@pytest.mark.parametrize("name,kind", [
    ("a.flac", "audio"), ("a.FLAC", "audio"), ("a.dsf", "audio"), ("a.mp3", "audio"),
    ("a.m4a", "audio"), ("a.wav", "audio"), ("a.aiff", "audio"), ("a.at3", "audio"),
    ("cover.jpg", "sidecar"), ("notes.txt", "sidecar"), ("list.m3u", "sidecar"),
    ("README", "sidecar"),                # no extension -> sidecar bucket
    ("Thumbs.db", "junk"), ("._x.flac", "junk"), ("x.ffs_tmp", "junk"),
    ("movie.mkv", "unsupported"), ("a.ogg", "unsupported"), ("a.opus", "unsupported"),
])
def test_classify(name, kind):
    assert core.classify(name) == kind


def test_junk_beats_extension():
    # An AppleDouble shadow of a real audio file is junk, not audio.
    assert core.classify("._track.flac") == "junk"


# ---------- human ----------


@pytest.mark.parametrize("n,expected", [
    (0, "0 B"), (512, "512 B"), (1023, "1023 B"),
    (1024, "1.0 KB"), (1536, "1.5 KB"),
    (1024 * 1024, "1.0 MB"), (1024 ** 3, "1.0 GB"), (1024 ** 4, "1.0 TB"),
    (5 * 1024 ** 4, "5.0 TB"),
])
def test_human(n, expected):
    assert core.human(n) == expected


# ---------- local_index ----------


def _build_tree(root):
    files = {
        "Artist/Album/01 - a.flac": b"x" * 10,
        "Artist/Album/02 - b.mp3": b"y" * 20,
        "Artist/Album/cover.jpg": b"img",
        "Artist/Album/Thumbs.db": b"junk",
        "Artist/Album/._a.flac": b"junk",
        "Artist/Album/movie.mkv": b"video",
        "Artist/Album/notes.ffs_tmp": b"tmp",
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def _collect(root, include_unsupported):
    out = list(core.local_index(str(root), include_unsupported))
    sentinel = out[-1]
    assert sentinel[0] == "__skipped__"
    rels = {rel for rel, _ap, _size, _kind in out[:-1]}
    return rels, sentinel[1]  # set of rels, skipped-counts dict


def test_local_index_skips_junk_and_unsupported(tmp_path):
    root = _build_tree(tmp_path)
    rels, skipped = _collect(root, include_unsupported=False)
    assert "Artist/Album/01 - a.flac" in rels
    assert "Artist/Album/02 - b.mp3" in rels
    assert "Artist/Album/cover.jpg" in rels          # sidecar is carried, not skipped
    # junk never appears
    assert not any("Thumbs.db" in r or "._a.flac" in r or "ffs_tmp" in r for r in rels)
    # unsupported excluded by default
    assert "Artist/Album/movie.mkv" not in rels
    assert skipped["junk"] == 3                       # Thumbs.db, ._a.flac, notes.ffs_tmp
    assert skipped["unsupported"] == 1                # movie.mkv


def test_local_index_can_include_unsupported(tmp_path):
    root = _build_tree(tmp_path)
    rels, skipped = _collect(root, include_unsupported=True)
    assert "Artist/Album/movie.mkv" in rels
    assert skipped["unsupported"] == 0
    assert skipped["junk"] == 3                       # junk is ALWAYS skipped


def test_local_index_uses_posix_separators(tmp_path):
    root = _build_tree(tmp_path)
    rels, _ = _collect(root, include_unsupported=False)
    assert all("\\" not in r for r in rels)           # forward slashes for SMB


# ---------- actionable ----------


def _scan(todo, new_only):
    return {"todo": todo, "new_only": new_only}


def test_actionable_returns_all_by_default():
    todo = [("a", "/a", 1, "new"), ("b", "/b", 2, "changed")]
    assert core.actionable(_scan(todo, new_only=False)) == todo


def test_actionable_new_only_drops_changed():
    todo = [("a", "/a", 1, "new"), ("b", "/b", 2, "changed"), ("c", "/c", 3, "new")]
    got = core.actionable(_scan(todo, new_only=True))
    assert [t[0] for t in got] == ["a", "c"]


# ---------- Wake-on-LAN ----------


@pytest.mark.parametrize("mac", ["zz:zz:zz:zz:zz:zz", "80:56:F2", "", "1234567890123"])
def test_send_wol_rejects_bad_mac(mac):
    with pytest.raises(ValueError):
        core.send_wol(mac)


def test_send_wol_packet(monkeypatch):
    sent = {}

    class FakeSock:
        def setsockopt(self, *a):
            pass

        def sendto(self, data, addr):
            sent["data"] = data
            sent["addr"] = addr

        def close(self):
            sent["closed"] = True

    monkeypatch.setattr(core.socket, "socket", lambda *a, **k: FakeSock())
    core.send_wol("80:56:F2:85:0E:27")

    mac_bytes = bytes.fromhex("8056F2850E27")
    assert sent["data"] == b"\xff" * 6 + mac_bytes * 16
    assert len(sent["data"]) == 6 + 6 * 16          # 102 bytes
    assert sent["addr"] == ("255.255.255.255", 9)
    assert sent["closed"] is True


def test_send_wol_accepts_dash_form(monkeypatch):
    captured = {}
    monkeypatch.setattr(core.socket, "socket",
                        lambda *a, **k: type("S", (), {
                            "setsockopt": lambda self, *a: None,
                            "sendto": lambda self, d, addr: captured.update(data=d),
                            "close": lambda self: None,
                        })())
    core.send_wol("80-56-F2-85-0E-27")
    assert captured["data"].startswith(b"\xff" * 6)


def test_socket_constants_present():
    # send_wol relies on broadcast UDP — guard the constants it uses.
    assert hasattr(socket, "SO_BROADCAST")
    assert hasattr(socket, "AF_INET")
