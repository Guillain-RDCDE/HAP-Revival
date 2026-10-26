"""Pure-logic tests for the sync engine: what reaches the HAP, how a plan is
built from a local tree and a remote index, how the cache round-trips, and the
CLI's error handling. The SMB session itself needs a device and is not here."""

import json

import pytest

import hap_sync as core

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


def test_local_index_skips_junk_and_unsupported(tmp_path):
    root = _build_tree(tmp_path)
    files, skipped = core.local_index(str(root), include_unsupported=False)
    rels = {f.rel for f in files}
    assert "Artist/Album/01 - a.flac" in rels
    assert "Artist/Album/02 - b.mp3" in rels
    assert "Artist/Album/cover.jpg" in rels  # sidecar is carried, not skipped
    # junk never appears
    assert not any("Thumbs.db" in r or "._a.flac" in r or "ffs_tmp" in r for r in rels)
    # unsupported excluded by default
    assert "Artist/Album/movie.mkv" not in rels
    assert skipped["junk"] == 3  # Thumbs.db, ._a.flac, notes.ffs_tmp
    assert skipped["unsupported"] == 1  # movie.mkv


def test_local_index_can_include_unsupported(tmp_path):
    root = _build_tree(tmp_path)
    files, skipped = core.local_index(str(root), include_unsupported=True)
    assert "Artist/Album/movie.mkv" in {f.rel for f in files}
    assert skipped["unsupported"] == 0
    assert skipped["junk"] == 3  # junk is ALWAYS skipped


def test_local_index_uses_posix_separators_and_real_sizes(tmp_path):
    root = _build_tree(tmp_path)
    files, _ = core.local_index(str(root), include_unsupported=False)
    assert all("\\" not in f.rel for f in files)  # forward slashes for SMB
    flac = next(f for f in files if f.rel.endswith("a.flac"))
    assert flac.size == 10 and flac.kind == "audio"
    assert flac.path.endswith("a.flac")


# ---------- planning ----------


def _local(rel, size):
    return core.LocalFile(rel, "/abs/" + rel, size, "audio")


def test_plan_entries_finds_new_and_changed_only():
    remote = {"a.flac": 10, "b.flac": 20}
    local = [_local("a.flac", 10), _local("b.flac", 25), _local("c.flac", 5)]
    todo = core.plan_entries(local, remote)
    assert [(t.rel, t.status) for t in todo] == [("b.flac", "changed"), ("c.flac", "new")]


def _scan(todo, new_only):
    return {"todo": todo, "new_only": new_only}


def test_actionable_returns_all_by_default():
    todo = [("a", "/a", 1, "new"), ("b", "/b", 2, "changed")]
    assert core.actionable(_scan(todo, new_only=False)) == todo


def test_actionable_new_only_drops_changed():
    todo = [("a", "/a", 1, "new"), ("b", "/b", 2, "changed"), ("c", "/c", 3, "new")]
    got = core.actionable(_scan(todo, new_only=True))
    assert [t.rel for t in got] == ["a", "c"]


def test_split_plan_sorts_case_insensitively():
    todo = [("b.flac", "/b", 1, "new"), ("A.flac", "/a", 1, "new"), ("z.flac", "/z", 1, "changed")]
    changed, new = core.split_plan(todo)
    assert [t.rel for t in new] == ["A.flac", "b.flac"]
    assert [t.rel for t in changed] == ["z.flac"]


def test_describe_changed_shows_both_sizes_and_the_delta():
    entry = core.PlanEntry("x.flac", "/x", 2048, "changed")
    assert core.describe_changed(entry, {"x.flac": 1024}) == "local 2.0 KB vs HAP 1.0 KB, Δ+1.0 KB"
    assert core.describe_changed(entry, {"x.flac": 2100}).endswith("Δ-52 B")
    assert core.describe_changed(entry, {}) == "2.0 KB"


def test_jobs_for_flattens_every_scan():
    scans = [
        {
            "share": "HAP_Internal",
            "todo": [("a", "/a", 1, "new"), ("b", "/b", 2, "changed")],
            "new_only": True,
        },
        {"share": "HAP_External", "todo": [("c", "/c", 3, "new")], "new_only": False},
    ]
    assert core.jobs_for(scans) == [
        core.Job("HAP_Internal", "a", "/a", 1),
        core.Job("HAP_External", "c", "/c", 3),
    ]


def test_scan_map_builds_the_plan_from_the_cache(tmp_path, capsys):
    root = _build_tree(tmp_path / "music")
    cfg = {"host": "1.2.3.4", "maps": [], "_path": str(tmp_path / "hap_sync.json")}
    core.save_cache(
        cfg, "HAP_Internal", {"Artist/Album/01 - a.flac": 10, "Artist/Album/cover.jpg": 99}
    )

    class NeverOpened:
        @property
        def smb(self):
            raise AssertionError("a cache hit must not open SMB")

    s = core.scan_map(
        cfg,
        NeverOpened(),
        {"local": str(root), "share": "HAP_Internal"},
        include_unsupported=False,
        refresh=False,
    )
    assert s["source"].startswith("cache ")
    statuses = {t.rel: t.status for t in s["todo"]}
    assert statuses == {"Artist/Album/02 - b.mp3": "new", "Artist/Album/cover.jpg": "changed"}
    out = capsys.readouterr().out
    assert "CHANGED (1)" in out and "NEW (1)" in out and "Δ-96 B" in out


def test_load_config_tolerant_never_raises(tmp_path):
    empty = {"host": "", "mac": "", "maps": []}
    assert core.load_config_tolerant(tmp_path / "absent.json") == empty
    (tmp_path / "bad.json").write_bytes(b"{nope")
    assert core.load_config_tolerant(tmp_path / "bad.json")["host"] == ""
    path = core.save_config(
        tmp_path / "hap_sync.json",
        "1.2.3.4",
        "80:56:F2:85:0E:27",
        [{"local": "D:/x", "share": "HAP_Internal"}],
    )
    cfg = core.load_config_tolerant(path)
    assert cfg["host"] == "1.2.3.4" and cfg["maps"][0]["share"] == "HAP_Internal"
    assert core.load_config(path)["mac"] == "80:56:F2:85:0E:27", "the same file the CLI reads"


def test_plan_file_lists_everything(tmp_path):
    s = {
        "local": "D:/Music",
        "share": "HAP_Internal",
        "source": "cache",
        "remote": {"a.flac": 5},
        "new_only": True,
        "todo": [("a.flac", "/a", 10, "changed"), ("b.flac", "/b", 20, "new")],
        "skipped": {"junk": 0, "unsupported": 0},
    }
    lines = core.plan_file_lines(s)
    assert lines[0] == "Transfer plan   D:/Music  ->  HAP_Internal"
    assert "would transfer: 1 (20 B)" in lines[1] and "new-only" in lines[1]
    assert "CHANGED (1)" in lines[3] and lines[4].startswith("~ a.flac")
    assert "NEW (1)" in lines[6] and lines[7] == "+ b.flac  (20 B)"
    path = core.write_plan_file(s, tmp_path)
    assert path == tmp_path / "hap_plan_HAP_Internal.txt"
    assert path.read_text(encoding="utf-8").splitlines() == lines


def test_scan_map_reports_a_missing_local_folder(tmp_path, capsys):
    cfg = {"host": "1.2.3.4", "maps": [], "_path": str(tmp_path / "hap_sync.json")}
    assert (
        core.scan_map(
            cfg, None, {"local": str(tmp_path / "nope"), "share": "HAP_Internal"}, False, False
        )
        is None
    )
    assert "not found" in capsys.readouterr().out


def test_selected_maps_filters_on_share():
    cfg = {"maps": [{"share": "HAP_Internal"}, {"share": "HAP_External"}]}
    assert [m["share"] for m in core.selected_maps(cfg, None)] == ["HAP_Internal", "HAP_External"]
    assert [m["share"] for m in core.selected_maps(cfg, "HAP_External")] == ["HAP_External"]


# ---------- cache ----------


def test_cache_round_trips_next_to_the_config(tmp_path):
    cfg = {"host": "192.168.1.28", "_path": str(tmp_path / "hap_sync.json")}
    core.save_cache(cfg, "HAP_Internal", {"A/B/c.flac": 123})
    loaded = core.load_cache(cfg, "HAP_Internal")
    assert loaded["files"] == {"A/B/c.flac": 123}
    assert loaded["host"] == "192.168.1.28" and loaded["built"]
    assert core.cache_file(cfg, "HAP_Internal").parent == tmp_path / ".hap_sync_cache"
    assert core.load_cache(cfg, "HAP_External") is None


def test_a_corrupt_cache_means_rescan(tmp_path):
    cfg = {"host": "h", "_path": str(tmp_path / "hap_sync.json")}
    core.cache_file(cfg, "HAP_Internal").write_bytes(b"{broken")
    assert core.load_cache(cfg, "HAP_Internal") is None
    core.cache_file(cfg, "HAP_Internal").write_bytes(b'{"files": "not a dict"}')
    assert core.load_cache(cfg, "HAP_Internal") is None


# ---------- config ----------


def test_load_config_reads_and_validates(tmp_path):
    path = tmp_path / "hap_sync.json"
    path.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps(
            {"host": "1.2.3.4", "maps": [{"local": "D:/x", "share": "HAP_Internal"}]}
        ).encode()
    )
    cfg = core.load_config(path)
    assert cfg["host"] == "1.2.3.4" and cfg["_path"] == str(path.resolve())

    with pytest.raises(FileNotFoundError):
        core.load_config(tmp_path / "absent.json")
    path.write_text('{"host": "1.2.3.4"}', encoding="utf-8")
    with pytest.raises(ValueError, match="maps"):
        core.load_config(path)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="valid JSON"):
        core.load_config(path)


# ---------- transfer (with a fake SMB session) ----------


class FakeConn:
    def __init__(self, fail_once_on=()):
        self.stored = []
        self.dirs = []
        self.fail_once_on = set(fail_once_on)

    def createDirectory(self, share, path):
        self.dirs.append((share, path))

    def storeFile(self, share, path, fp):
        if path in self.fail_once_on:
            self.fail_once_on.discard(path)
            raise OSError("desynced")
        self.stored.append((share, path, fp.read()))


class FakeSmb:
    def __init__(self, conn):
        self.conn = conn
        self.reconnects = 0

    def reconnect(self):
        self.reconnects += 1


def test_transfer_uploads_and_folds_into_the_cache(tmp_path):
    src = tmp_path / "a.flac"
    src.write_bytes(b"audio")
    conn = FakeConn()
    index = {"HAP_Internal": {}}
    events = []
    jobs = [core.Job("HAP_Internal", "Artist/Album/a.flac", str(src), 5)]

    done, failed = core.transfer(
        FakeSmb(conn), jobs, index, on_event=lambda kind, **d: events.append((kind, d))
    )

    assert (done, failed) == (1, 0)
    assert conn.stored == [("HAP_Internal", "/Artist/Album/a.flac", b"audio")]
    assert ("HAP_Internal", "/Artist") in conn.dirs
    assert ("HAP_Internal", "/Artist/Album") in conn.dirs
    assert index["HAP_Internal"] == {"Artist/Album/a.flac": 5}
    assert events[0][0] == "file_done" and events[0][1]["i"] == 1


def test_transfer_retries_once_then_counts_a_failure(tmp_path):
    src = tmp_path / "a.flac"
    src.write_bytes(b"audio")
    conn = FakeConn(fail_once_on={"/a.flac"})
    smb = FakeSmb(conn)
    index = {"HAP_Internal": {}}
    done, failed = core.transfer(smb, [core.Job("HAP_Internal", "a.flac", str(src), 5)], index)
    assert (done, failed) == (1, 0), "one retry on a fresh session must succeed"
    assert smb.reconnects == 2

    class AlwaysFails(FakeConn):
        def storeFile(self, share, path, fp):
            raise OSError("dead")

    events = []
    done, failed = core.transfer(
        FakeSmb(AlwaysFails()),
        [core.Job("HAP_Internal", "a.flac", str(src), 5)],
        index,
        on_event=lambda kind, **d: events.append(kind),
    )
    assert (done, failed) == (0, 1)
    assert events == ["file_failed"]


def test_transfer_honours_cancellation(tmp_path):
    src = tmp_path / "a.flac"
    src.write_bytes(b"audio")
    events = []
    jobs = [core.Job("HAP_Internal", f"{i}.flac", str(src), 5) for i in range(3)]
    done, _ = core.transfer(
        FakeSmb(FakeConn()),
        jobs,
        {"HAP_Internal": {}},
        on_event=lambda kind, **d: events.append(kind),
        should_cancel=lambda: len(events) >= 1,
    )
    assert done == 1
    assert events == ["file_done", "cancelled"]


# ---------- the session ----------


def test_smb_raises_smb_error_not_system_exit(monkeypatch):
    # The GUI shows this in a dialog; SystemExit would have killed its worker.
    import sys

    monkeypatch.setitem(sys.modules, "smb", None)
    monkeypatch.setitem(sys.modules, "smb.SMBConnection", None)
    with pytest.raises(core.SmbError, match="pysmb"):
        core.Smb("127.0.0.1")


def test_lazy_smb_opens_only_on_demand(monkeypatch):
    opened = []

    class FakeSession:
        def __init__(self, host):
            opened.append(host)

        def close(self):
            pass

    monkeypatch.setattr(core, "Smb", FakeSession)
    lazy = core.LazySmb("1.2.3.4")
    assert opened == []
    first, second = lazy.smb, lazy.smb
    assert first is second
    assert opened == ["1.2.3.4"], "one session, opened once"
    lazy.close()


# ---------- CLI ----------


def test_main_without_a_command_prints_help(capsys):
    assert core.main([]) == 2
    assert "usage" in capsys.readouterr().out


def test_main_reports_a_missing_config(tmp_path, capsys):
    assert core.main(["--config", str(tmp_path / "none.json"), "plan"]) == 2
    assert "config not found" in capsys.readouterr().err


def test_main_wake_uses_the_configured_mac(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "hap_sync.json"
    cfg.write_text(
        json.dumps(
            {
                "host": "h",
                "mac": "80:56:F2:85:0E:27",
                "maps": [{"local": "x", "share": "HAP_Internal"}],
            }
        )
    )
    sent = []
    monkeypatch.setattr(core, "send_wol", lambda mac: sent.append(mac))
    assert core.main(["--config", str(cfg), "wake"]) == 0
    assert sent == ["80:56:F2:85:0E:27"]

    cfg.write_text(json.dumps({"host": "h", "maps": [{"local": "x", "share": "HAP_Internal"}]}))
    monkeypatch.undo()  # the real sender validates the (missing) MAC before sending
    assert core.main(["--config", str(cfg), "wake"]) == 2
    assert "valid 'mac'" in capsys.readouterr().err


def test_main_plan_reports_an_smb_failure_as_an_error(tmp_path, monkeypatch, capsys):
    root = _build_tree(tmp_path / "music")
    cfg = tmp_path / "hap_sync.json"
    cfg.write_text(
        json.dumps({"host": "h", "maps": [{"local": str(root), "share": "HAP_Internal"}]})
    )

    def boom(host):
        raise core.SmbError("SMB connection to h failed")

    monkeypatch.setattr(core, "Smb", boom)
    assert core.main(["--config", str(cfg), "plan"]) == 2
    assert "SMB connection to h failed" in capsys.readouterr().err


def test_main_plan_from_cache_counts_the_files(tmp_path, monkeypatch, capsys):
    root = _build_tree(tmp_path / "music")
    cfg_path = tmp_path / "hap_sync.json"
    cfg_path.write_text(
        json.dumps({"host": "h", "maps": [{"local": str(root), "share": "HAP_Internal"}]})
    )
    core.save_cache({"host": "h", "_path": str(cfg_path)}, "HAP_Internal", {})
    assert core.main(["--config", str(cfg_path), "plan"]) == 0
    assert "Plan: 3 file(s) would transfer" in capsys.readouterr().out

    assert core.main(["--config", str(cfg_path), "sync", "--dry-run"]) == 0
    assert "[dry-run] 3 file(s)" in capsys.readouterr().out


# ---------- local copies (backup disks) ----------


def _write(root, rel, data, mtime=None):
    import os

    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def _local_map(src, dest, mode="keep"):
    return {"local": str(src), "dest": str(dest), "delete": mode}


def _quiet(_s):
    pass


def test_load_config_accepts_local_maps_and_rejects_bad_ones(tmp_path):
    path = tmp_path / "hap_sync.json"

    def with_maps(maps):
        path.write_text(json.dumps({"host": "h", "maps": maps}), encoding="utf-8")
        return core.load_config(path)

    cfg = with_maps([{"local": "D:/x", "dest": "F:/y", "delete": "mirror"}])
    assert core.is_local_map(cfg["maps"][0]) and core.map_target(cfg["maps"][0]) == "F:/y"
    with pytest.raises(ValueError, match="either 'share'"):
        with_maps([{"local": "D:/x", "share": "HAP_Internal", "dest": "F:/y"}])
    with pytest.raises(ValueError, match="either 'share'"):
        with_maps([{"local": "D:/x"}])
    with pytest.raises(ValueError, match="'delete'"):
        with_maps([{"local": "D:/x", "dest": "F:/y", "delete": "wipe"}])


def test_a_local_copy_carries_every_format_and_compares_dates(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    _build_tree(src)
    _write(src, "Artist/Album/01 - a.flac", b"x" * 10, mtime=2_000_000)
    _write(dest, "Artist/Album/01 - a.flac", b"y" * 10, mtime=1_000_000)  # same size, older
    _write(dest, "Artist/Album/02 - b.mp3", b"y" * 20)
    _write(dest, "Gone/old.flac", b"old")

    s = core.scan_local_map(_local_map(src, dest, "list"), on_scan=_quiet)
    statuses = {t.rel: t.status for t in s["todo"]}
    assert statuses["Artist/Album/01 - a.flac"] == "changed", "a same-size re-tag is caught"
    assert statuses["Artist/Album/movie.mkv"] == "new", "a backup keeps unsupported formats"
    assert "Artist/Album/Thumbs.db" not in statuses, "junk is still left out"
    assert [d.rel for d in s["orphans"]] == ["Gone/old.flac"]
    assert core.deletions(s) == [], "the list mode never deletes"
    assert core.scan_local_map(_local_map(src, dest), on_scan=_quiet)["orphans"] == []


def test_sync_local_copies_then_mirrors(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    _write(src, "A/B/1.flac", b"new audio", mtime=1_500_000)
    _write(src, "A/B/cover.jpg", b"img")
    for i in range(3):
        _write(dest, f"A/B/{i}.extra", b"e")
    _write(dest, "Old/Album/x.flac", b"old")

    s = core.scan_local_map(_local_map(src, dest, "mirror"), on_scan=_quiet)
    assert not s["held"] and core.pending(s) == 6
    events = []
    done, failed, deleted = core.sync_local(s, on_event=lambda kind, **d: events.append(kind))
    assert (done, failed, deleted) == (2, 0, 4)
    assert (dest / "A/B/1.flac").read_bytes() == b"new audio"
    assert (dest / "A/B/1.flac").stat().st_mtime == pytest.approx(1_500_000), "dates are kept"
    assert not (dest / "Old").exists(), "folders emptied by the mirror are removed"
    assert dest.exists(), "the destination itself stays"
    assert events.count("file_done") == 2 and events.count("file_deleted") == 4
    assert not list(dest.rglob("*" + core.PART_SUFFIX))

    again = core.scan_local_map(_local_map(src, dest, "mirror"), on_scan=_quiet)
    assert core.pending(again) == 0, "a second run has nothing left to do"


def test_a_mirror_holds_back_a_mass_deletion(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    _write(src, "keep.flac", b"k")
    for i in range(core.MASS_DELETE_MIN):
        _write(dest, f"other/{i}.flac", b"o")

    s = core.scan_local_map(_local_map(src, dest, "mirror"), on_scan=_quiet)
    assert s["held"] and core.deletions(s) == []
    assert "HELD BACK" in "\n".join(core.plan_file_lines(s))
    s = core.scan_local_map(_local_map(src, dest, "mirror"), on_scan=_quiet, allow_mass_delete=True)
    assert not s["held"] and len(core.deletions(s)) == core.MASS_DELETE_MIN

    empty = tmp_path / "empty"
    empty.mkdir()
    s = core.scan_local_map(_local_map(empty, dest, "mirror"), on_scan=_quiet)
    assert s["held"], "an empty source never wipes a copy, however small"


def test_local_map_problems_are_named(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    assert core.local_map_problem(_local_map(tmp_path / "nope", tmp_path / "d")) == "source_missing"
    assert core.local_map_problem(_local_map(src, src / "backup")) == "overlap"
    assert core.local_map_problem(_local_map(src, tmp_path / "new" / "dest")) is None, (
        "a destination folder that does not exist yet is created"
    )


def test_the_hap_comes_first_and_local_scans_upload_nothing(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    _write(src, "a.flac", b"a")
    cfg = {
        "host": "h",
        "_path": str(tmp_path / "hap_sync.json"),
        "maps": [_local_map(src, dest), {"local": str(src), "share": "HAP_Internal"}],
    }
    core.save_cache(cfg, "HAP_Internal", {})
    args = core.build_parser().parse_args(["plan"])
    scans = core.scan_all(cfg, core.LazySmb("h"), args)
    assert [core.scan_target(s) for s in scans] == ["HAP_Internal", str(dest)]
    assert core.jobs_for(scans) == [core.Job("HAP_Internal", "a.flac", str(src / "a.flac"), 1)]
    assert core.plan_totals(scans) == (2, 0)
    assert core.write_plan_file(scans[1], tmp_path).name.startswith("hap_plan_")


def test_two_maps_on_one_share_share_one_index(tmp_path):
    cfg = {"host": "h", "_path": str(tmp_path / "hap_sync.json")}
    core.save_cache(cfg, "HAP_Internal", {"x": 1})
    lazy = core.LazySmb("h")
    first, _ = core.get_remote(cfg, lazy, "HAP_Internal", refresh=False)
    second, _ = core.get_remote(cfg, lazy, "HAP_Internal", refresh=True)
    assert first is second, "the second map must fold its uploads into the same dict"


def test_unreachable_shares_names_the_unmounted_disk():
    class Conn:
        def listPath(self, share, path):
            if share == "HAP_External":
                raise OSError("Unable to connect to shared device")
            return []

    smb = FakeSmb(Conn())
    assert core.unreachable_shares(smb, ["HAP_Internal", "HAP_External"]) == ["HAP_External"]
    assert smb.reconnects == 1, "one retry on a fresh session before giving up"


def test_main_sync_skips_a_share_the_hap_does_not_serve(tmp_path, monkeypatch, capsys):
    root = _build_tree(tmp_path / "music")
    cfg_path = tmp_path / "hap_sync.json"
    cfg_path.write_text(
        json.dumps({"host": "h", "maps": [{"local": str(root), "share": "HAP_External"}]})
    )
    core.save_cache({"host": "h", "_path": str(cfg_path)}, "HAP_External", {})

    class Dead(FakeConn):
        def listPath(self, share, path):
            raise OSError("Unable to connect to shared device")

    class Session(FakeSmb):
        def __init__(self, host):
            super().__init__(Dead())

        def close(self):
            pass

    monkeypatch.setattr(core, "Smb", Session)
    assert core.main(["--config", str(cfg_path), "sync"]) == 1
    out = capsys.readouterr().out
    assert out.count("HAP_External is not served") == 1 and "FAILED" not in out
    assert "Done: 0 transferred, 3 failed" in out


def test_main_sync_mirrors_a_local_copy_without_touching_the_hap(tmp_path, monkeypatch, capsys):
    src, dest = tmp_path / "src", tmp_path / "dest"
    _write(src, "a.flac", b"a")
    _write(dest, "b.flac", b"b")
    cfg_path = tmp_path / "hap_sync.json"
    cfg_path.write_text(json.dumps({"host": "h", "maps": [_local_map(src, dest, "mirror")]}))
    monkeypatch.setattr(core, "Smb", lambda host: pytest.fail("no SMB for a local copy"))
    assert core.main(["--config", str(cfg_path), "plan"]) == 0
    assert "1 would be deleted" in capsys.readouterr().out
    assert core.main(["--config", str(cfg_path), "sync"]) == 0
    out = capsys.readouterr().out
    assert "Done: 1 transferred, 0 failed, 1 deleted" in out
    assert sorted(p.name for p in dest.iterdir()) == ["a.flac"]
