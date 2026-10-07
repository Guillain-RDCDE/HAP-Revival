"""Drive HAP Sync's other tabs and its worker plumbing without showing a window.

Same shape as test_hap_gui_fix.py: one hidden App for the module, every
handler called directly, every engine call replaced by a fake. The worker
thread is kept but the jobs are instantaneous, so each test drains the queue
and asserts on what reached the log.

Skipped where there is no display; run under `xvfb-run` on Linux.
"""

import gc
import json
import queue
import time

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def _app(tmp_path_factory):
    import hap_gui

    original = hap_gui.CONFIG_PATH
    hap_gui.CONFIG_PATH = tmp_path_factory.mktemp("cfg") / "hap_sync.json"
    try:
        instance = hap_gui.App()
    except tk.TclError:  # pragma: no cover - headless CI
        hap_gui.CONFIG_PATH = original
        pytest.skip("no display")
    instance.root.withdraw()
    try:
        yield instance
    finally:
        for name in [n for n, v in vars(instance).items() if isinstance(v, tk.Variable)]:
            delattr(instance, name)
        gc.collect()
        instance.root.destroy()
        hap_gui.CONFIG_PATH = original


@pytest.fixture
def app(_app, monkeypatch):
    """The shared App, idle, in English, with every dialog silenced."""
    import hap_gui

    _app._set_language("en")
    _app.busy = False
    _app.host_var.set("")
    _app.mac_var.set("")
    _app._clear(_app.transfer_log)
    _app._clear(_app.validate_log)
    _app._clear(_app.diff_log)
    for kind in ("showwarning", "showinfo", "showerror"):
        monkeypatch.setattr(hap_gui.messagebox, kind, lambda *a, **k: None)
    return _app


def drain(app, timeout=5.0):
    """Wait for the worker to finish, then pump every queued event into tkinter."""
    deadline = time.monotonic() + timeout
    while app.busy and time.monotonic() < deadline:
        app._poll()
        time.sleep(0.02)
    app._poll()
    assert not app.busy, "the worker never reported 'finished'"


def log_text(widget) -> str:
    return widget.get("1.0", "end")


# ---------- plumbing ----------


def test_language_switch_retranslates_live_widgets(app):
    app._set_language("fr")
    assert app.root.title() == app._T("gui.window_title")
    assert "Synchro" in app.status_var.get() or "Prêt" in app.status_var.get()
    app._set_language("xx")  # unknown: ignored
    assert app.lang == "fr"
    app._set_language("en")
    assert app.status_var.get() == "Ready."


def test_dispatch_updates_widgets_from_worker_events(app):
    app._active_log = app.transfer_log
    app._dispatch("log", {"line": "hello"})
    app._dispatch("status", {"text": "busy"})
    app._dispatch("progmax", {"total": 10})
    app._dispatch("progress", {"value": 3})
    app._dispatch("conn", {"ok": True})
    app._dispatch("fill", {"ip": "1.2.3.4", "mac": "AA:BB:CC:DD:EE:FF"})
    app._dispatch("fixstate", {"has": True, "findings": ["x"]})
    app._dispatch("error", {"msg": "boom"})
    assert "hello" in log_text(app.transfer_log) and "⚠ boom" in log_text(app.transfer_log)
    assert app.status_var.get() == "busy"
    assert float(app.progress.cget("value")) == 3.0
    assert app.host_var.get() == "1.2.3.4" and app.mac_var.get() == "AA:BB:CC:DD:EE:FF"
    assert app._has_fixes and str(app.fix_btn.cget("state")) == "normal"
    app._dispatch("fixstate", {"has": False, "findings": []})
    assert str(app.fix_btn.cget("state")) == "disabled"


def test_run_async_serialises_jobs_and_reports_errors(app):
    def boom():
        raise RuntimeError("worker exploded")

    app._run_async(boom, app.transfer_log)
    assert app.busy and str(app.stop_btn.cget("state")) == "normal"
    assert app._run_async(lambda: None, app.transfer_log) is None, "busy: a second job is refused"
    drain(app)
    assert "RuntimeError: worker exploded" in log_text(app.transfer_log)
    assert str(app.stop_btn.cget("state")) == "disabled"


def test_smb_error_from_a_job_is_shown_not_fatal(app):
    import hap_sync

    def no_session():
        raise hap_sync.SmbError("SMB connection to h failed")

    app._run_async(no_session, app.transfer_log, use_progress=True)
    drain(app)
    assert "SMB connection to h failed" in log_text(app.transfer_log)


def test_map_rows_round_trip_and_never_reach_zero(app):
    before = len(app.map_rows)
    app._add_map_row("D:/Music", "HAP_External")
    assert app._collect_maps()[-1] == {"local": "D:/Music", "share": "HAP_External"}
    for entry in list(app.map_rows):
        app._remove_map_row(entry)
    assert len(app.map_rows) == 1, "an empty row is kept to type into"
    assert app._collect_maps() == []
    for _ in range(before - 1):
        app._add_map_row()


def test_save_and_persist_write_the_shared_config(app):
    import hap_gui

    app.host_var.set("1.2.3.4")
    app.mac_var.set("80:56:F2:85:0E:27")
    app.map_rows[0]["local"].set("D:/Music")
    app.on_save_config()
    saved = json.loads(hap_gui.CONFIG_PATH.read_text(encoding="utf-8"))
    assert saved["host"] == "1.2.3.4" and saved["maps"][0]["local"] == "D:/Music"
    assert app._cfg()["_path"] == str(hap_gui.CONFIG_PATH)
    app.host_var.set("")
    app.map_rows[0]["local"].set("")
    app._persist()  # nothing worth saving: must not touch the file
    assert json.loads(hap_gui.CONFIG_PATH.read_text(encoding="utf-8")) == saved


def test_preflight_checks_warn_once_each(app, monkeypatch):
    import hap_gui

    warned = []
    monkeypatch.setattr(hap_gui.messagebox, "showwarning", lambda *a, **k: warned.append(a[1]))
    app.on_check()
    app.on_plan()
    assert len(warned) == 2 and all("IP" in w for w in warned)
    app.host_var.set("1.2.3.4")
    for entry in list(app.map_rows):
        entry["local"].set("")
    app.on_sync()
    assert "folder" in warned[-1]
    app.on_validate()
    app.on_diff()
    assert len(warned) == 5


def test_missing_pysmb_is_explained(app, monkeypatch):
    import sys

    import hap_gui

    errors = []
    monkeypatch.setattr(hap_gui.messagebox, "showerror", lambda *a, **k: errors.append(a[1]))
    monkeypatch.setitem(sys.modules, "smb", None)
    assert app._need_pysmb() is False
    assert "pip install pysmb" in errors[0]


# ---------- connection bar ----------


def test_autodetect_fills_ip_and_mac(app, monkeypatch):
    import discover

    monkeypatch.setattr(discover, "local_subnet_prefixes", lambda: ["10.0.0."])
    found = discover.FoundHap("10.0.0.9", "HAP-Z1ES", "80:56:F2:85:0E:27")
    monkeypatch.setattr(discover, "find_hap", lambda prefixes, on_candidates: (
        on_candidates(["10.0.0.9"]) or discover.LanScan(prefixes, ["10.0.0.9"], found)))
    app.on_autodetect()
    drain(app)
    assert app.host_var.get() == "10.0.0.9" and app.mac_var.get() == "80:56:F2:85:0E:27"
    text = log_text(app.transfer_log)
    assert "Candidate(s)" in text and "Detected: HAP-Z1ES at 10.0.0.9, MAC" in text
    assert str(app.conn_dot.cget("foreground")) == "#3c3"


def test_autodetect_reports_nothing_found(app, monkeypatch):
    import discover

    monkeypatch.setattr(discover, "local_subnet_prefixes", lambda: ["10.0.0."])
    monkeypatch.setattr(discover, "find_hap",
                        lambda prefixes, on_candidates: discover.LanScan(prefixes, [], None))
    app.on_autodetect()
    drain(app)
    assert "No device answered" in log_text(app.transfer_log)
    monkeypatch.setattr(discover, "find_hap", lambda prefixes, on_candidates: (
        discover.LanScan(prefixes, ["10.0.0.3"], None)))
    app.on_autodetect()
    drain(app)
    assert "none was a HAP" in log_text(app.transfer_log)
    monkeypatch.setattr(discover, "local_subnet_prefixes", lambda: [])
    app.on_autodetect()
    drain(app)
    assert "No local network interface" in log_text(app.transfer_log)


def test_check_reports_and_arms_the_fix_button(app, monkeypatch):
    import smb_doctor

    findings = [smb_doctor.Finding("pysmb", "Transfer access", smb_doctor.OK),
                smb_doctor.Finding("signing", "Signing", smb_doctor.PROBLEM, fix_cmd="Set-X",
                                   needs_admin=True)]
    monkeypatch.setattr(smb_doctor, "diagnose", lambda host: findings)
    app.host_var.set("1.2.3.4")
    app.on_check()
    drain(app)
    text = log_text(app.transfer_log)
    assert "Diagnosing SMB access to 1.2.3.4" in text and "WORKS" in text
    assert "1 Windows issue(s)" in text
    assert app._has_fixes and str(app.fix_btn.cget("state")) == "normal"


def test_fix_applies_after_confirmation(app, monkeypatch):
    import hap_gui

    import smb_doctor

    app._findings = [smb_doctor.Finding("signing", "Signing", smb_doctor.PROBLEM, fix_cmd="Set-X",
                                        needs_admin=True)]
    app._has_fixes = True
    asked = []
    monkeypatch.setattr(hap_gui.messagebox, "askyesno",
                        lambda title, msg: asked.append(msg) or False)
    app.on_fix()
    assert "UAC" in asked[0] and "• Signing" in asked[0]
    monkeypatch.setattr(hap_gui.messagebox, "askyesno", lambda title, msg: True)
    monkeypatch.setattr(smb_doctor, "apply_fixes",
                        lambda findings, on_log: on_log(">> x") or (True, "Fixes applied."))
    monkeypatch.setattr(smb_doctor, "diagnose", lambda host: [])
    app.on_fix()
    drain(app)
    text = log_text(app.transfer_log)
    assert "Applying fixes" in text and ">> x" in text and "All Windows SMB issues resolved" in text
    assert not app._has_fixes


def test_wake_sends_or_explains(app, monkeypatch):
    import hap_common

    real_send_wol = hap_common.send_wol
    sent = []
    monkeypatch.setattr(hap_common, "send_wol", lambda mac: sent.append(mac))
    app.mac_var.set("80:56:F2:85:0E:27")
    app.on_wake()
    drain(app)
    assert sent == ["80:56:F2:85:0E:27"] and "magic packet sent" in log_text(app.transfer_log)
    monkeypatch.setattr(hap_common, "send_wol", real_send_wol)  # the real validator
    app.mac_var.set("nope")
    app.on_wake()
    drain(app)
    assert "12 hex digits" in log_text(app.transfer_log)


def test_stop_sets_the_flag(app):
    app.stop_event.clear()
    app.on_stop()
    assert app.stop_event.is_set() and "Stop requested" in app.status_var.get()


# ---------- transfer tab ----------


def _ready_to_sync(app, monkeypatch, tmp_path):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "smb", types.ModuleType("smb"))
    app.host_var.set("1.2.3.4")
    music = tmp_path / "Artist" / "Album"
    music.mkdir(parents=True)
    (music / "01.flac").write_bytes(b"0123456789")
    (music / "02.flac").write_bytes(b"new")
    for entry in list(app.map_rows)[1:]:
        app._remove_map_row(entry)
    app.map_rows[0]["local"].set(str(tmp_path))
    app.map_rows[0]["share"].set("HAP_Internal")
    return music


def test_plan_logs_the_changed_and_new_files(app, monkeypatch, tmp_path):
    import hap_gui

    import hap_sync

    _ready_to_sync(app, monkeypatch, tmp_path)
    monkeypatch.setattr(hap_sync, "get_remote",
                        lambda cfg, lazy, share, refresh, on_progress=None: (
                            {"Artist/Album/01.flac": 5}, "cache 2026"))
    app.new_only_var.set(False)
    app.on_plan()
    drain(app)
    text = log_text(app.transfer_log)
    assert "Analyzing:" in text and "[cache 2026] remote library: 1 files; to transfer: 2" in text
    assert "CHANGED — already on the HAP" in text and "~ Artist/Album/01.flac" in text
    assert "NEW — not on the HAP yet (1)" in text and "+ Artist/Album/02.flac" in text
    assert "Plan: 2 file(s) would transfer" in text
    plan = (hap_gui.CONFIG_PATH.parent / "hap_plan_HAP_Internal.txt").read_text(encoding="utf-8")
    assert "CHANGED (1)" in plan and "NEW (1)" in plan
    assert app.status_var.get() == "Analysis done: 2 file(s) to transfer."

    app.new_only_var.set(True)
    app.on_plan()
    drain(app)
    text = log_text(app.transfer_log)
    assert "SKIPPED (kept as-is)" in text and "Plan: 1 file(s)" in text
    app.new_only_var.set(False)


def test_plan_reports_a_missing_folder(app, monkeypatch, tmp_path):
    import hap_sync

    _ready_to_sync(app, monkeypatch, tmp_path)
    app.map_rows[0]["local"].set(str(tmp_path / "gone"))
    monkeypatch.setattr(hap_sync, "get_remote",
                        lambda *a, **k: pytest.fail("no listing without a local folder"))
    app.on_plan()
    drain(app)
    assert "! folder not found" in log_text(app.transfer_log)


def test_sync_transfers_through_the_engine(app, monkeypatch, tmp_path):
    import hap_sync

    _ready_to_sync(app, monkeypatch, tmp_path)
    monkeypatch.setattr(hap_sync, "get_remote",
                        lambda cfg, lazy, share, refresh, on_progress=None: (
                            {"Artist/Album/01.flac": 10}, "cache"))

    class Session:
        def reconnect(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(hap_sync, "Smb", lambda host: Session())

    def fake_transfer(smb, jobs, index, on_event=None, should_cancel=None):
        on_event("file_done", i=1, total=2, share="HAP_Internal", rel=jobs[0].rel, size=3)
        on_event("file_failed", i=2, total=2, share="HAP_Internal", rel="x.flac", error="dead")
        on_event("cancelled", i=2, total=2)
        return 1, 1

    monkeypatch.setattr(hap_sync, "transfer", fake_transfer)
    saved = []
    monkeypatch.setattr(hap_sync, "save_cache", lambda cfg, share, idx: saved.append(share))
    app.on_sync()
    drain(app)
    text = log_text(app.transfer_log)
    assert "Transferring 1 file(s)" in text and "[1/2] HAP_Internal:/Artist/Album/02.flac" in text
    assert "FAILED HAP_Internal:/x.flac — dead" in text and "Cancelled at 2/2" in text
    assert "Done: 1 transferred, 1 failed" in text and saved == ["HAP_Internal"]


def test_sync_when_nothing_changed(app, monkeypatch, tmp_path):
    import hap_sync

    _ready_to_sync(app, monkeypatch, tmp_path)
    monkeypatch.setattr(hap_sync, "get_remote",
                        lambda cfg, lazy, share, refresh, on_progress=None: (
                            {"Artist/Album/01.flac": 10, "Artist/Album/02.flac": 3}, "cache"))
    app.on_sync()
    drain(app)
    assert "already in sync" in log_text(app.transfer_log)
    assert app.status_var.get() == "Already in sync."


def test_listing_progress_updates_the_status_line(app):
    app._listing_progress("HAP_Internal")(12345)
    app._poll()
    assert app.status_var.get() == "Listing HAP_Internal: 12,345 files so far…"


# ---------- validate and compare tabs ----------


def test_validate_tab_reports_counts_and_sections(app, tmp_path):
    album = tmp_path / "A" / "B"
    album.mkdir(parents=True)
    (album / "song.mp3").write_bytes(b"x")
    (album / "Thumbs.db").write_bytes(b"x")
    app.validate_dir.set(str(tmp_path))
    app.on_validate()
    drain(app)
    text = log_text(app.validate_log)
    assert "Playable audio files" in text and ": 1" in text
    assert "[JUNK]" in text and "Thumbs.db" in text
    assert "[NO COVER FILE]" in text and "Verdict: issues above." in text


def test_compare_tab_lists_new_and_existing(app, tmp_path):
    import sqlite3

    db = tmp_path / "hdd_browse.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE FT5202 (PROP3601 INTEGER, PROP7020 TEXT)")
    conn.execute("CREATE TABLE FT000A (PROP3601 INTEGER, PROP7020 TEXT)")
    conn.execute("CREATE TABLE FT0002 (PROP7052 INTEGER, PROPB2BB INTEGER)")
    conn.execute("INSERT INTO FT5202 VALUES (1, 'Miles Davis')")
    conn.execute("INSERT INTO FT000A VALUES (10, 'Kind of Blue')")
    conn.execute("INSERT INTO FT0002 VALUES (1, 10)")
    conn.commit()
    conn.close()
    music = tmp_path / "music"
    (music / "Miles Davis" / "Kind of Blue").mkdir(parents=True)
    (music / "Bonobo" / "Black Sands").mkdir(parents=True)
    app.diff_db.set(str(db))
    app.diff_dir.set(str(music))
    app.on_diff()
    drain(app)
    text = log_text(app.diff_log)
    assert "HAP library: 1 (artist, album) pairs" in text
    assert "NEW — not on the HAP (1):" in text and "+ Bonobo / Black Sands" in text
    assert "ALREADY on the HAP (1)" in text and "= Miles Davis / Kind of Blue" in text


def test_log_section_truncates(app):
    app._active_log = app.diff_log
    app._log_section("T", [f"i{n}" for n in range(30)], limit=25)
    app._poll()
    text = log_text(app.diff_log)
    assert "i24" in text and "i25" not in text and "… and 5 more" in text


# ---------- fix tab, the parts the other file does not cover ----------


def test_fix_scan_local_indexes_the_mapped_folders(app, monkeypatch, tmp_path):
    import hap_fixit

    (tmp_path / "A").mkdir()
    (tmp_path / "A" / "x.flac").write_bytes(b"")
    app.host_var.set("1.2.3.4")
    for entry in list(app.map_rows)[1:]:
        app._remove_map_row(entry)
    app.map_rows[0]["local"].set(str(tmp_path))
    saved = []
    monkeypatch.setattr(hap_fixit, "save_local_index", lambda index, host: saved.append(host))
    app.on_fix_scan_local()
    drain(app)
    assert saved == ["1.2.3.4"] and "Scanning" in log_text(app.fix_log)

    app.map_rows[0]["local"].set(str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    app.on_fix_scan_local()
    drain(app)
    assert "No music found" in log_text(app.fix_log)


def test_fix_scan_local_asks_for_a_folder_when_none_is_mapped(app, monkeypatch):
    import hap_gui

    for entry in list(app.map_rows):
        entry["local"].set("")
    monkeypatch.setattr(hap_gui.filedialog, "askdirectory", lambda title: "")
    started = []
    monkeypatch.setattr(app, "_run_async", lambda *a, **k: started.append(1))
    app.on_fix_scan_local()
    assert started == []


def test_fix_scan_runs_the_crawler(app, monkeypatch):
    import hap_fixit

    app.host_var.set("1.2.3.4")
    monkeypatch.setattr(hap_fixit, "crawl_shares", lambda ip, progress: (
        progress("HAP_Internal", 100, 100, 7) or {"host": ip, "shares": {"HAP_Internal": []}}))
    saved = []
    monkeypatch.setattr(hap_fixit, "save_index", lambda index: saved.append(index["host"]))
    app.on_fix_scan()
    drain(app)
    text = log_text(app.fix_log)
    assert "Indexing the shares on 1.2.3.4" in text and "HAP_Internal 100/100 folders" in text
    assert saved == ["1.2.3.4"] and "done:" in text


def test_fix_html_report_is_written(app, monkeypatch, tmp_path):
    import hap_gui

    import hap_fixit
    import hap_library

    harvest = {"host": "1.2.3.4", "artists": [], "albums": [], "tracks": []}
    monkeypatch.setattr(hap_library, "load_harvest", lambda host: harvest)
    monkeypatch.setattr(hap_fixit, "load_index", lambda host: {"host": "1.2.3.4", "shares": {}})
    target = tmp_path / "report.html"
    monkeypatch.setattr(hap_gui.filedialog, "asksaveasfilename", lambda **k: str(target))
    opened = []
    monkeypatch.setattr(hap_fixit, "open_folder", lambda p: opened.append(p))
    app.host_var.set("1.2.3.4")
    app.on_fix_html()
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert opened == [str(tmp_path)] and "wrote" in log_text(app.fix_log)
    monkeypatch.setattr(hap_gui.filedialog, "asksaveasfilename", lambda **k: "")
    app.on_fix_html()  # cancelled: nothing else happens
    assert len(opened) == 1


def test_main_smoke_path(_app, monkeypatch, capsys):
    """`_app` is only here for its skip: without a display there is nothing to smoke."""
    import hap_gui

    monkeypatch.setenv("HAP_GUI_SMOKE", "1")
    assert hap_gui.main() == 0
    assert "smoke OK" in capsys.readouterr().out


def test_queue_is_drained_in_order(app):
    app.q = queue.Queue()
    app._active_log = app.transfer_log
    app._emit("log", line="first")
    app._emit("log", line="second")
    app._poll()
    text = log_text(app.transfer_log)
    assert text.index("first") < text.index("second")


# ---------- updates ----------


def _release(version="9.9.9"):
    import hap_update

    return hap_update.Release(version, f"hap-sync-v{version}",
                              f"https://github.com/x/y/releases/tag/hap-sync-v{version}")


def test_startup_check_is_silent_when_opted_out(app):
    """conftest opts the suite out, so the window came up without a button."""
    deadline = time.monotonic() + 5
    while app._bg_jobs and time.monotonic() < deadline:  # the startup thread's answer
        app._poll()
        time.sleep(0.02)
    assert not app.update_btn.winfo_manager() and app._bg_jobs == 0
    assert "HAP Sync" in app.version_lbl.cget("text")


def test_an_available_update_shows_the_button_and_the_status(app):
    import hap_update

    status = hap_update.Status(current="0.1.0", latest=_release("9.9.9"))
    app._dispatch("update", {"status": status, "interactive": False})
    assert app.update_btn.winfo_manager() == "pack"
    assert "9.9.9" in app.update_btn.cget("text") and "9.9.9" in app.status_var.get()
    app._set_language("fr")
    assert app.update_btn.cget("text").startswith("Mettre à jour")
    assert "0.1.0" not in app.status_var.get(), "the status line was retranslated"
    app._set_language("en")
    app._dispatch("update", {"status": hap_update.Status(), "interactive": False})
    assert not app.update_btn.winfo_manager()


def test_a_menu_check_reports_each_outcome(app, monkeypatch):
    import hap_gui
    import hap_update

    infos, warns, asked = [], [], []
    monkeypatch.setattr(hap_gui.messagebox, "showinfo", lambda t, m: infos.append(m))
    monkeypatch.setattr(hap_gui.messagebox, "showwarning", lambda t, m: warns.append(m))
    monkeypatch.setattr(hap_gui.messagebox, "askyesno", lambda t, m: asked.append(m) or False)
    app._dispatch("update", {"status": hap_update.Status(disabled=True), "interactive": True})
    assert hap_update.OPT_OUT_ENV in infos[-1]
    app._dispatch("update", {"status": hap_update.Status(error="offline"), "interactive": True})
    assert "offline" in warns[-1]
    app._dispatch("update", {"status": hap_update.Status(latest=_release("0.0.1")),
                             "interactive": True})
    assert "latest version" in infos[-1] and app.status_var.get() == "Ready."
    app._dispatch("update", {"status": hap_update.Status(current="0.1.0", latest=_release()),
                             "interactive": True})
    assert "9.9.9" in asked[-1], "an interactive check goes straight to the confirmation"
    assert not app.busy, "and a declined confirmation starts nothing"
    app._dispatch("update", {"status": hap_update.Status(), "interactive": False})


def test_check_for_updates_runs_in_the_background(app, monkeypatch):
    import hap_gui
    import hap_update

    forced = []

    def fake_bg(callback, force=False):
        forced.append(force)
        callback(hap_update.Status(latest=_release("0.0.1")))

    monkeypatch.setattr(hap_update, "check_in_background", fake_bg)
    infos = []
    monkeypatch.setattr(hap_gui.messagebox, "showinfo", lambda t, m: infos.append(m))
    app.on_check_updates()
    assert forced == [True] and app._bg_jobs == 1 and app._polling
    assert "Checking" in app.status_var.get()
    app._poll()
    assert app._bg_jobs == 0 and "latest version" in infos[-1]
    app.on_about()
    assert hap_update.VERSION in infos[-1] and "github.com" in infos[-1]


def test_one_click_update_installs_the_exe_and_closes(app, monkeypatch):
    import hap_gui
    import hap_update

    app._dispatch("update", {"status": hap_update.Status(current="0.1.0", latest=_release()),
                             "interactive": False})
    monkeypatch.setattr(hap_update, "install_kind", lambda root=None: "frozen")
    asked, infos, closed, calls = [], [], [], []
    monkeypatch.setattr(hap_gui.messagebox, "askyesno", lambda t, m: asked.append(m) or True)
    monkeypatch.setattr(hap_gui.messagebox, "showinfo", lambda t, m: infos.append(m))
    monkeypatch.setattr(app, "_on_close", lambda: closed.append(1))

    def fake_apply(status, progress=None, launch=True):
        calls.append(launch)
        for done in (0, 50, 50, 100):
            progress(done, 100)
        progress(1, 0)  # unknown size: ignored
        return hap_update.Result("frozen", "installed HapSync.exe 9.9.9", restart=True,
                                 launched=True)

    monkeypatch.setattr(hap_update, "apply", fake_apply)
    app.on_update()
    drain(app)
    assert "Download and install" in asked[0] and calls == [True]
    assert "installed HapSync.exe 9.9.9" in log_text(app.transfer_log)
    assert closed == [1] and "9.9.9" in infos[-1] and "closes" in infos[-1]
    app._dispatch("update", {"status": hap_update.Status(), "interactive": False})


def test_one_click_update_from_a_clone_offers_a_restart(app, monkeypatch):
    import hap_gui
    import hap_update

    app._dispatch("update", {"status": hap_update.Status(current="0.1.0", latest=_release()),
                             "interactive": False})
    monkeypatch.setattr(hap_update, "install_kind", lambda root=None: "git")
    answers = [False]  # decline the confirmation first
    asked = []
    monkeypatch.setattr(hap_gui.messagebox, "askyesno",
                        lambda t, m: asked.append(m) or answers.pop(0))
    applied, restarted = [], []
    monkeypatch.setattr(hap_update, "apply", lambda status, progress=None, launch=True:
                        applied.append(1) or hap_update.Result("git", "Fast-forward", restart=True))
    monkeypatch.setattr(hap_update, "restart_self", lambda: restarted.append(1))
    app.on_update()
    assert "started again" in asked[-1] and applied == [] and not app.busy

    answers[:] = [True, True]  # confirm, then accept the restart
    app.on_update()
    drain(app)
    assert applied == [1] and "Fast-forward" in asked[-1] and restarted == [1]

    answers[:] = [True, False]  # confirm, then keep running the old code
    app.on_update()
    drain(app)
    assert restarted == [1]
    app._dispatch("update", {"status": hap_update.Status(), "interactive": False})


def test_a_failed_update_is_explained_with_the_download_link(app, monkeypatch):
    import hap_gui
    import hap_update

    app._dispatch("update", {"status": hap_update.Status(current="0.1.0", latest=_release()),
                             "interactive": False})
    monkeypatch.setattr(hap_gui.messagebox, "askyesno", lambda t, m: True)
    errors = []
    monkeypatch.setattr(hap_gui.messagebox, "showerror", lambda t, m: errors.append(m))

    def refuse(status, progress=None, launch=True):
        raise hap_update.UpdateError("checksum mismatch")

    monkeypatch.setattr(hap_update, "apply", refuse)
    app.on_update()
    drain(app)
    assert "checksum mismatch" in errors[-1] and "releases/tag/hap-sync-v9.9.9" in errors[-1]

    app._dispatch("update", {"status": hap_update.Status(), "interactive": False})
    app.on_update()  # nothing to update: nothing happens
    assert not app.busy
    app._dispatch("updated", {"result": hap_update.Result("git", "noop"), "version": "x"})
