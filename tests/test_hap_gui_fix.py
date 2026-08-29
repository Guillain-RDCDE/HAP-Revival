"""Drive the GUI's Fix tab without showing a window.

A tkinter callback that references a widget that does not exist raises only when
a human clicks it â€” `self.ip_var` instead of `self.host_var` shipped exactly that
way and no other test could see it. These build the real App, hide it, and call
the handlers.

Skipped where there is no display (the CI runner is headless Linux).
"""

import gc
import sys

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def _app(tmp_path_factory):
    """One App for the whole module, hidden, writing no config.

    Module-scoped on purpose: building a second `tk.Tk()` after destroying the
    first fails on Windows, which made the second test of the file "skip" with a
    TclError â€” and that test was the one that catches a handler naming a widget
    the App does not have. One root, reset between tests.
    """
    import hap_gui

    # CONFIG_PATH is a Path; a str here fails inside load_config_tolerant.
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
        # Drop the tk.Variables and collect them *before* the root goes: a
        # Variable finalised after the Tcl interpreter is destroyed raises
        # "main thread is not in main loop" from the garbage collector, which
        # pytest then reports against whatever unrelated test happens to be
        # running at the time.
        for name in [n for n, v in vars(instance).items() if isinstance(v, tk.Variable)]:
            delattr(instance, name)
        gc.collect()
        instance.root.destroy()
        hap_gui.CONFIG_PATH = original


@pytest.fixture
def app(_app):
    """The shared App, with the Fix tab back to its initial state."""
    _app.fix_list.delete(0, "end")
    _app._fix_findings = []
    _app.fix_kind.set("cover")
    _app.host_var.set("")
    _app._clear(_app.fix_log)
    return _app


def test_the_fix_tab_exists_and_starts_empty(app):
    assert app.fix_list.size() == 0
    assert app._fix_findings == []
    assert app.fix_kind.get() == "cover"


def test_every_fix_handler_is_wired_to_a_real_attribute(app):
    # The bug this catches: a handler naming a widget the App does not have.
    for name in ("on_fix_scan", "on_fix_load", "on_fix_open",
                 "on_fix_edit", "on_fix_copy", "on_fix_html"):
        assert callable(getattr(app, name)), name
    assert hasattr(app, "host_var"), "the IP lives in host_var, not ip_var"
    assert not hasattr(app, "ip_var")


def test_load_without_caches_warns_instead_of_raising(app, monkeypatch):
    import hap_gui

    warned = []
    monkeypatch.setattr(hap_gui.messagebox, "showwarning",
                        lambda *a, **k: warned.append(a))
    monkeypatch.setattr(hap_gui.hap_library, "load_harvest", lambda *_a, **_k: None)
    monkeypatch.setattr(hap_gui.hap_fixit, "load_index", lambda *_a, **_k: None)
    app.host_var.set("10.0.0.1")

    app.on_fix_load()

    assert warned, "the user must be told which scan is missing"
    assert app.fix_list.size() == 0


def test_load_fills_the_list_from_the_caches(app, monkeypatch):
    import hap_fixit
    import hap_gui

    harvest = {
        "host": "10.0.0.1", "artists": [], "tracks": [
            {"trackid": 1, "name": "t", "filename": "01 - a.flac", "duration": 10,
             "album": {"albumid": 1, "name": "Album"}, "artist": {"name": "X"},
             "codec": {"codec_type": "flac", "sample_rate": 44100, "bit_width": 16}},
        ],
        "albums": [{"albumid": 1, "name": "Album", "number_of_tracks": 1,
                    "album_artist": {"name": "X"}}],
    }
    index = {"host": "10.0.0.1",
             "shares": {"HAP_Internal": [["/X/Album", "01 - a.flac", 1],
                                         ["/X/Album", "cover.jpg", 1]]}}
    monkeypatch.setattr(hap_gui.hap_library, "load_harvest", lambda *_a, **_k: harvest)
    monkeypatch.setattr(hap_gui.hap_fixit, "load_index", lambda *_a, **_k: index)
    app.host_var.set("10.0.0.1")

    app.on_fix_load()

    assert app.fix_list.size() == 1
    assert len(app._fix_findings) == 1
    finding = app._fix_findings[0]
    assert finding.kind == "cover"
    assert finding.path == hap_fixit.unc("10.0.0.1", "HAP_Internal/X/Album")
    # The loose cover.jpg must be mentioned: it is the thirty-second fix.
    assert "cover.jpg" in app.fix_list.get(0)


def test_open_and_edit_refuse_when_nothing_is_selected(app, monkeypatch):
    import hap_gui

    told = []
    monkeypatch.setattr(hap_gui.messagebox, "showinfo", lambda *a, **k: told.append(a))
    app.on_fix_open()
    app.on_fix_edit()
    app.on_fix_copy()
    assert len(told) == 3, "each action must say 'pick a line' rather than crash"


def test_copy_puts_the_path_on_the_clipboard(app, monkeypatch):
    import hap_fixit
    import hap_gui

    app._fix_findings = [
        hap_fixit.Finding("cover", "Album", "detail", ["HAP_Internal/X/Album"], "10.0.0.1")
    ]
    app.fix_list.insert("end", "Album")
    app.fix_list.selection_set(0)
    monkeypatch.setattr(hap_gui.messagebox, "showinfo", lambda *a, **k: None)

    app.on_fix_copy()

    assert app.root.clipboard_get() == r"\\10.0.0.1\HAP_Internal\X\Album"


def test_open_reports_an_unlocated_album_instead_of_opening_nothing(app, monkeypatch):
    import hap_fixit
    import hap_gui

    told = []
    monkeypatch.setattr(hap_gui.messagebox, "showinfo", lambda *a, **k: told.append(a))
    opened = []
    monkeypatch.setattr(hap_fixit, "open_folder", lambda p: opened.append(p))

    app._fix_findings = [hap_fixit.Finding("cover", "Nowhere", "d", [], "10.0.0.1")]
    app.fix_list.insert("end", "Nowhere")
    app.fix_list.selection_set(0)

    app.on_fix_open()

    assert opened == []
    assert told, "an album with no location must say so"


def test_open_calls_through_for_a_located_album(app, monkeypatch):
    import hap_fixit

    opened = []
    monkeypatch.setattr(hap_fixit, "open_folder", lambda p: opened.append(p))
    app._fix_findings = [
        hap_fixit.Finding("cover", "Album", "d", ["HAP_Internal/X/Album"], "10.0.0.1")
    ]
    app.fix_list.insert("end", "Album")
    app.fix_list.selection_set(0)

    app.on_fix_open()

    assert opened == [r"\\10.0.0.1\HAP_Internal\X\Album"]


def test_open_prefers_the_synced_local_copy(app, monkeypatch, tmp_path):
    # The whole point of the local route: editing a folder on your own disk is
    # instant, and the next Sync carries it over. Opening the player's copy over
    # SMB1 would work but is slow enough to matter across 274 albums.
    import hap_fixit

    (tmp_path / "X" / "Album").mkdir(parents=True)
    maps = {"HAP_Internal": str(tmp_path)}
    opened = []
    monkeypatch.setattr(hap_fixit, "open_folder", lambda p: opened.append(p))

    app._fix_findings = [
        hap_fixit.Finding("cover", "Album", "d", ["HAP_Internal/X/Album"], "10.0.0.1", maps)
    ]
    app.fix_list.insert("end", "Album")
    app.fix_list.selection_set(0)

    app.on_fix_open()

    assert opened == [str(tmp_path / "X" / "Album")]
    assert r"\\10.0.0.1" not in opened[0]
    # And the log must say what to do next, not just print a path.
    assert app._T("gui.fix.then_sync") in app.fix_log.get("1.0", "end")


def test_the_list_marks_which_albums_have_a_local_copy(app, tmp_path):
    import hap_fixit

    (tmp_path / "X" / "Here").mkdir(parents=True)
    maps = {"HAP_Internal": str(tmp_path)}
    app._fix_show([
        hap_fixit.Finding("cover", "Here", "d", ["HAP_Internal/X/Here"], "10.0.0.1", maps),
        hap_fixit.Finding("cover", "Away", "d", ["HAP_Internal/X/Away"], "10.0.0.1", maps),
    ])

    assert "▪" in app.fix_list.get(0)
    assert "▪" not in app.fix_list.get(1)


def test_edit_warns_when_no_tag_editor_is_installed(app, monkeypatch):
    import hap_fixit
    import hap_gui

    warned = []
    monkeypatch.setattr(hap_gui.messagebox, "showwarning", lambda *a, **k: warned.append(a))
    monkeypatch.setattr(hap_fixit, "open_in_editor", lambda *_a, **_k: "")
    app._fix_findings = [
        hap_fixit.Finding("cover", "Album", "d", ["HAP_Internal/X/Album"], "10.0.0.1")
    ]
    app.fix_list.insert("end", "Album")
    app.fix_list.selection_set(0)

    app.on_fix_edit()

    assert warned


def test_scan_without_an_ip_warns_instead_of_starting_a_job(app, monkeypatch):
    import hap_gui

    warned = []
    monkeypatch.setattr(hap_gui.messagebox, "showwarning", lambda *a, **k: warned.append(a))
    started = []
    monkeypatch.setattr(app, "_run_async", lambda *a, **k: started.append(a))
    app.host_var.set("")

    app.on_fix_scan()

    assert warned and not started


def test_scan_starts_a_background_job_when_the_ip_is_set(app, monkeypatch):
    # The crawl takes minutes; it must never run on the UI thread.
    started = []
    monkeypatch.setattr(app, "_run_async", lambda target, log, **k: started.append((target, log)))
    app.host_var.set("10.0.0.1")

    app.on_fix_scan()

    assert len(started) == 1
    target, log = started[0]
    assert callable(target)
    assert log is app.fix_log


def test_the_kind_selector_shows_labels_but_keeps_internal_keys(app):
    # The box must never put a localised word into fix_kind: everything
    # downstream matches on "cover" / "duplicate" / "corrupt".
    labels = list(app.fix_kind_box.cget("values"))
    assert len(labels) == 3
    assert "cover" not in labels, "the box shows a translated label, not the key"

    app.fix_kind_label.set(labels[1])
    app._on_fix_kind_pick()
    assert app.fix_kind.get() == "duplicate"

    app.fix_kind.set("corrupt")
    app._retranslate_fix_kinds()
    assert app.fix_kind_label.get() == labels[2]


def test_the_summary_line_is_translated(app, monkeypatch):
    import hap_fixit

    app._fix_show([hap_fixit.Finding("cover", "A", "d", ["HAP_Internal/X/A"], "1.2.3.4")])
    line = app.fix_log.get("1.0", "end").strip()
    assert "findings" not in line or app.lang == "en", "the summary must follow the UI language"
    assert "1" in line


def test_the_kind_selector_filters_what_is_listed(app, monkeypatch):
    import hap_fixit

    findings = [
        hap_fixit.Finding("cover", "A", "d", ["HAP_Internal/X/A"], "10.0.0.1"),
        hap_fixit.Finding("duplicate", "B", "d", ["HAP_Internal/X/B"], "10.0.0.1"),
        hap_fixit.Finding("duplicate", "C", "d", [], "10.0.0.1"),
    ]
    app.fix_kind.set("duplicate")
    app._fix_show(findings)

    assert app.fix_list.size() == 2
    assert [f.title for f in app._fix_findings] == ["B", "C"]
    # "!" marks an item that could not be located, "?" one found in several places.
    assert app.fix_list.get(1).startswith("!")


@pytest.mark.skipif(sys.platform != "win32", reason="Mp3tag lookup is Windows-shaped")
def test_the_editor_lookup_prefers_the_env_override(monkeypatch, tmp_path):
    import hap_fixit

    fake = tmp_path / "MyTagger.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("HAP_TAG_EDITOR", str(fake))
    assert hap_fixit.find_editor() == str(fake)
