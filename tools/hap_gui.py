#!/usr/bin/env python3
"""
HAP Sync — a tiny native Windows GUI over the hap_sync engine.

Same brains as `hap_sync.py` (SMB1 transfer + remote-index cache + HAP-aware junk/format
filtering) and `hap_companion.py` (pre-flight validation + library diff), but wrapped in a
double-click window instead of a command line. No JSON to hand-edit, no terminal: pick a
folder, hit a button, watch the progress bar.

Three tabs:
  - Transfer        : map local folders -> HAP shares, Analyze (dry-run) then Sync, with a
                      live progress bar and a cancel button.
  - Validate        : scan a folder *before* transfer for junk / unsupported / >192 kHz /
                      missing cover.
  - Compare library : semantic diff of a local <Artist>/<Album>/ tree against the HAP's
                      SQLite catalog.

The connection bar (IP / MAC, Auto-detect, Check, Wake, Save config) is shared by every tab.
"Auto-detect" scans the local subnet for the HAP (port 60200) and reads its IP + MAC from the
device's ScalarWebAPI — SSDP is intentionally not used (multicast is unreliable on multi-homed
Windows and the HAP did not answer M-SEARCH in testing). Settings persist to `hap_sync.json`
next to this script — the exact file the CLI reads, so the GUI and `python hap_sync.py` stay
interchangeable.

Run from source:
    pip install pysmb           # only needed for the actual transfer
    python tools/hap_gui.py

Build a standalone HapSync.exe (no Python needed on the target machine):
    powershell -ExecutionPolicy Bypass -File tools\build_gui.ps1
    # -> dist/HapSync.exe  (bundles pysmb, the icon and tools/locales/)

tkinter is stdlib (no extra dependency for the UI itself). All blocking work (SMB listing,
uploads, folder walks, the subnet scan) runs on a worker thread and reports back through a
queue, so the window never freezes — tkinter is only ever touched from the main thread.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import discover
import hap_common
import hap_companion as comp
import hap_fixit
import hap_library
import hap_sync as core
import i18n
import smb_doctor
from hap_common import API_PORT, SHARES, human_size


def _set_window_icon(root: tk.Tk) -> None:
    """Apply the HapSync vinyl icon to the window/taskbar, silently if missing.

    The .ico lives next to this script in source, and PyInstaller bundles it
    into the frozen exe's temp dir (sys._MEIPASS) — try both locations.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    ico = base / "HapSync.ico"
    if not ico.exists():
        ico = Path(__file__).resolve().parent / "HapSync.ico"
    try:
        if ico.exists():
            root.iconbitmap(default=str(ico))
    except Exception:
        pass  # icon is cosmetic; never let it break startup


# When frozen (PyInstaller onefile), __file__ lives in the temp _MEIPASS extraction dir,
# so the config must sit next to the .exe to persist across runs; in source it sits next
# to this script.
_APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent)
CONFIG_PATH = _APP_DIR / "hap_sync.json"
POLL_MS = 80          # how often the UI drains the worker->UI queue
GITHUB_URL = "https://github.com/Guillain-RDCDE/HAP-Revival"


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        # Resolve the UI language once (OS locale / HAP_LANG); the Language menu
        # below lets the user override it live.
        self.lang = i18n.detect_lang()
        self._i18n: list = []  # (apply_fn, key) pairs retranslated on language change
        self.root.title(self._T("gui.window_title"))
        _set_window_icon(self.root)
        self.root.geometry("880x640")
        self.root.minsize(760, 520)

        self.q: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self._active_log: tk.Text | None = None
        self._action_widgets: list = []  # disabled while a job runs
        self._findings: list = []        # last SMB-doctor result (for the Fix button)
        self._has_fixes = False          # are there pending Windows fixes to apply?

        cfg = core.load_config_tolerant(CONFIG_PATH)
        self.host_var = tk.StringVar(value=cfg["host"])
        self.mac_var = tk.StringVar(value=cfg["mac"])
        self.unsupported_var = tk.BooleanVar(value=False)
        self.refresh_var = tk.BooleanVar(value=False)
        # Default OFF: the local library is the source of truth, so a normal sync faithfully
        # mirrors it — re-tagged / re-encoded ("changed") tracks MUST propagate to the HAP, no
        # exceptions. Tick this only for the rare "add without overwriting anything" case.
        self.new_only_var = tk.BooleanVar(value=False)
        self.map_rows: list[dict] = []

        self._build_menu()
        self._build_connection_bar()
        self._build_footer()   # packed bottom before the notebook so it's always reserved
        self._build_tabs()

        # Seed the mapping rows from config. On a first run (no saved maps) start with the
        # two rows already wired to the two shares — the user only fills the local folders
        # once, and they persist from then on.
        for m in cfg["maps"]:
            self._add_map_row(m.get("local", ""), m.get("share", SHARES[0]))
        if not self.map_rows:
            self._add_map_row("", "HAP_Internal")
            self._add_map_row("", "HAP_External")

        # Remember settings without a manual save: persist on close.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- i18n plumbing ----------

    def _T(self, key: str, **kwargs) -> str:
        return i18n.t(key, self.lang, **kwargs)

    def _reg(self, widget, key: str) -> None:
        """Register a ttk/tk widget whose `text=` should follow the language, and
        set it now."""
        self._i18n.append((lambda s: widget.configure(text=s), key))
        widget.configure(text=self._T(key))

    def _reg_tab(self, nb: ttk.Notebook, tab, key: str) -> None:
        """Register a Notebook tab's title for retranslation."""
        self._i18n.append((lambda s: nb.tab(tab, text=s), key))
        nb.tab(tab, text=self._T(key))

    def _retranslate(self) -> None:
        self.root.title(self._T("gui.window_title"))
        for apply_fn, key in self._i18n:
            try:
                apply_fn(self._T(key))
            except tk.TclError:
                pass  # widget destroyed (e.g. a removed mapping row)
        # The idle status line is the one dynamic label worth resetting on switch.
        if not self.busy:
            self.status_var.set(self._T("gui.status.ready"))

    def _set_language(self, code: str) -> None:
        if code not in i18n.CATALOGS:
            return
        self.lang = code
        self.lang_var.set(code)
        self._retranslate()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        lang_menu = tk.Menu(menubar, tearoff=0)
        self.lang_var = tk.StringVar(value=self.lang)
        for opt in i18n.language_options():
            lang_menu.add_radiobutton(
                label=opt["name"], value=opt["code"], variable=self.lang_var,
                command=lambda c=opt["code"]: self._set_language(c),
            )
        menubar.add_cascade(label=self._T("gui.menu.language"), menu=lang_menu)
        self._lang_menubar = menubar
        self._lang_menu_index = menubar.index("end")
        # Keep the cascade label itself translatable.
        self._i18n.append(
            (lambda s: menubar.entryconfigure(self._lang_menu_index, label=s), "gui.menu.language")
        )
        self.root.configure(menu=menubar)

    # ---------- UI construction ----------

    def _build_connection_bar(self) -> None:
        bar = ttk.LabelFrame(self.root, text="HAP")
        bar.pack(fill="x", padx=10, pady=(10, 4))
        ip_lbl = ttk.Label(bar)
        ip_lbl.grid(row=0, column=0, padx=(8, 4), pady=6, sticky="w")
        self._reg(ip_lbl, "gui.lbl.ip")
        ttk.Entry(bar, textvariable=self.host_var, width=18).grid(
            row=0, column=1, pady=6, sticky="w")
        mac_lbl = ttk.Label(bar)
        mac_lbl.grid(row=0, column=2, padx=(12, 4), pady=6, sticky="w")
        self._reg(mac_lbl, "gui.lbl.mac")
        ttk.Entry(bar, textvariable=self.mac_var, width=20).grid(
            row=0, column=3, pady=6, sticky="w")

        btns = ttk.Frame(bar)
        btns.grid(row=0, column=4, padx=8, sticky="e")
        bar.columnconfigure(4, weight=1)
        self.conn_dot = ttk.Label(btns, text="●", foreground="#888")
        self.conn_dot.pack(side="left", padx=(0, 8))
        for key, cmd in (("gui.conn.autodetect", self.on_autodetect),
                         ("gui.conn.check", self.on_check),
                         ("gui.conn.wake", self.on_wake),
                         ("gui.conn.save", self.on_save_config)):
            b = ttk.Button(btns, command=cmd)
            b.pack(side="left", padx=3)
            self._reg(b, key)
            self._action_widgets.append(b)
        # Appears after a Check that finds fixable Windows SMB problems. Managed on its own
        # (not in _action_widgets) so it stays disabled until there is actually something to fix.
        self.fix_btn = ttk.Button(btns, command=self.on_fix, state="disabled")
        self.fix_btn.pack(side="left", padx=3)
        self._reg(self.fix_btn, "gui.conn.fix")

    def _build_footer(self) -> None:
        footer = ttk.Frame(self.root)
        footer.pack(side="bottom", fill="x", padx=10, pady=(0, 6))
        link = ttk.Label(footer, text=GITHUB_URL.replace("https://", ""),
                         foreground="#5a7fb5", cursor="hand2", font=("Segoe UI", 8))
        link.pack(side="right")
        link.bind("<Button-1>", lambda _e: webbrowser.open(GITHUB_URL))

    def _build_tabs(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=4)
        self._build_transfer_tab(nb)
        self._build_validate_tab(nb)
        self._build_diff_tab(nb)
        self._build_fix_tab(nb)

    def _build_transfer_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="Transfer")
        self._reg_tab(nb, tab, "gui.tab.transfer")

        maps_box = ttk.LabelFrame(tab)
        self._reg(maps_box, "gui.folders_box")
        maps_box.pack(fill="x", padx=8, pady=8)
        self.maps_frame = ttk.Frame(maps_box)
        self.maps_frame.pack(fill="x", padx=4, pady=4)
        add = ttk.Button(maps_box, command=lambda: self._add_map_row())
        self._reg(add, "gui.add_folder")
        add.pack(anchor="w", padx=6, pady=(0, 6))
        self._action_widgets.append(add)

        opts = ttk.Frame(tab)
        opts.pack(fill="x", padx=8)
        cb_new = ttk.Checkbutton(opts, variable=self.new_only_var)
        self._reg(cb_new, "gui.opt.new_only")
        cb_new.pack(side="left")
        cb_unsup = ttk.Checkbutton(opts, variable=self.unsupported_var)
        self._reg(cb_unsup, "gui.opt.unsupported")
        cb_unsup.pack(side="left", padx=16)
        cb_rescan = ttk.Checkbutton(opts, variable=self.refresh_var)
        self._reg(cb_rescan, "gui.opt.rescan")
        cb_rescan.pack(side="left")

        actions = ttk.Frame(tab)
        actions.pack(fill="x", padx=8, pady=8)
        b_plan = ttk.Button(actions, command=self.on_plan)
        self._reg(b_plan, "gui.btn.analyze")
        b_sync = ttk.Button(actions, command=self.on_sync)
        self._reg(b_sync, "gui.btn.sync")
        b_plan.pack(side="left")
        b_sync.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(actions, command=self.on_stop, state="disabled")
        self._reg(self.stop_btn, "gui.btn.stop")
        self.stop_btn.pack(side="left", padx=6)
        self._action_widgets += [b_plan, b_sync]

        self.progress = ttk.Progressbar(tab, mode="determinate")
        self.progress.pack(fill="x", padx=8)
        self.status_var = tk.StringVar(value=self._T("gui.status.ready"))
        ttk.Label(tab, textvariable=self.status_var).pack(anchor="w", padx=8, pady=(2, 4))
        self.transfer_log = self._make_log(tab)

    def _build_validate_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="Validate")
        self._reg_tab(nb, tab, "gui.tab.validate")
        self.validate_dir = tk.StringVar()
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=8, pady=8)
        folder_lbl = ttk.Label(row)
        self._reg(folder_lbl, "gui.lbl.folder")
        folder_lbl.pack(side="left")
        ttk.Entry(row, textvariable=self.validate_dir).pack(
            side="left", fill="x", expand=True, padx=6)
        b_browse = ttk.Button(row, command=lambda: self._pick_dir(self.validate_dir))
        self._reg(b_browse, "gui.btn.browse")
        b_val = ttk.Button(row, command=self.on_validate)
        self._reg(b_val, "gui.btn.validate")
        b_browse.pack(side="left")
        b_val.pack(side="left", padx=6)
        self._action_widgets += [b_browse, b_val]
        help_lbl = ttk.Label(tab, foreground="#888", justify="left", wraplength=700)
        self._reg(help_lbl, "gui.validate_help")
        help_lbl.pack(anchor="w", padx=8, pady=(0, 4))
        self.validate_log = self._make_log(tab)

    def _build_diff_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="Compare library")
        self._reg_tab(nb, tab, "gui.tab.compare")
        self.diff_db = tk.StringVar()
        self.diff_dir = tk.StringVar()
        r1 = ttk.Frame(tab)
        r1.pack(fill="x", padx=8, pady=(8, 2))
        db_lbl = ttk.Label(r1, width=18)
        self._reg(db_lbl, "gui.lbl.db")
        db_lbl.pack(side="left")
        ttk.Entry(r1, textvariable=self.diff_db).pack(side="left", fill="x", expand=True, padx=6)
        b_db = ttk.Button(r1, command=self._pick_db)
        self._reg(b_db, "gui.btn.browse")
        b_db.pack(side="left")
        r2 = ttk.Frame(tab)
        r2.pack(fill="x", padx=8, pady=2)
        local_lbl = ttk.Label(r2, width=18)
        self._reg(local_lbl, "gui.lbl.local_folder")
        local_lbl.pack(side="left")
        ttk.Entry(r2, textvariable=self.diff_dir).pack(side="left", fill="x", expand=True, padx=6)
        b_dir = ttk.Button(r2, command=lambda: self._pick_dir(self.diff_dir))
        self._reg(b_dir, "gui.btn.browse")
        b_dir.pack(side="left")
        b_diff = ttk.Button(tab, command=self.on_diff)
        self._reg(b_diff, "gui.btn.compare")
        b_diff.pack(anchor="w", padx=8, pady=6)
        self._action_widgets += [b_db, b_dir, b_diff]
        help_lbl = ttk.Label(tab, foreground="#888", justify="left", wraplength=700)
        self._reg(help_lbl, "gui.diff_help")
        help_lbl.pack(anchor="w", padx=8, pady=(0, 4))
        self.diff_log = self._make_log(tab)

    def _build_fix_tab(self, nb: ttk.Notebook) -> None:
        """What the player's own catalog says is wrong, and where those files are.

        This is the tab that turns a report into work: pick a line, open its
        folder, or hand it straight to a tag editor. It needs two one-off scans
        first (the library over REST, the shares over SMB), so the buttons say so
        rather than failing silently.
        """
        tab = ttk.Frame(nb)
        nb.add(tab, text="Fix")
        self._reg_tab(nb, tab, "gui.tab.fix")

        row = ttk.Frame(tab)
        row.pack(fill="x", padx=8, pady=8)
        b_scan = ttk.Button(row, command=self.on_fix_scan)
        self._reg(b_scan, "gui.btn.fix_scan")
        b_scan.pack(side="left")
        b_local = ttk.Button(row, command=self.on_fix_scan_local)
        self._reg(b_local, "gui.btn.fix_scan_local")
        b_local.pack(side="left", padx=6)
        b_load = ttk.Button(row, command=self.on_fix_load)
        self._reg(b_load, "gui.btn.fix_load")
        b_load.pack(side="left", padx=6)
        # The combobox shows translated labels; `fix_kind` keeps the internal key,
        # so the rest of the code never sees a localised string.
        self.fix_kind = tk.StringVar(value="cover")
        self.fix_kind_label = tk.StringVar()
        self.fix_kind_box = ttk.Combobox(row, textvariable=self.fix_kind_label,
                                         state="readonly", width=16)
        self.fix_kind_box.pack(side="left", padx=(16, 0))
        self.fix_kind_box.bind("<<ComboboxSelected>>", self._on_fix_kind_pick)
        self._i18n.append((lambda _s: self._retranslate_fix_kinds(), "gui.fix.kind.cover"))
        self._retranslate_fix_kinds()
        self._action_widgets += [b_scan, b_local, b_load]

        help_lbl = ttk.Label(tab, foreground="#888", justify="left", wraplength=700)
        self._reg(help_lbl, "gui.fix_help")
        help_lbl.pack(anchor="w", padx=8, pady=(0, 4))

        listrow = ttk.Frame(tab)
        listrow.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.fix_list = tk.Listbox(listrow, font=("Consolas", 9), activestyle="none")
        bar = ttk.Scrollbar(listrow, orient="vertical", command=self.fix_list.yview)
        self.fix_list.configure(yscrollcommand=bar.set)
        self.fix_list.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        self.fix_list.bind("<Double-Button-1>", lambda _e: self.on_fix_open())

        acts = ttk.Frame(tab)
        acts.pack(fill="x", padx=8, pady=(0, 8))
        b_open = ttk.Button(acts, command=self.on_fix_open)
        self._reg(b_open, "gui.btn.fix_open")
        b_open.pack(side="left")
        b_edit = ttk.Button(acts, command=self.on_fix_edit)
        self._reg(b_edit, "gui.btn.fix_edit")
        b_edit.pack(side="left", padx=6)
        b_copy = ttk.Button(acts, command=self.on_fix_copy)
        self._reg(b_copy, "gui.btn.fix_copy")
        b_copy.pack(side="left")
        b_html = ttk.Button(acts, command=self.on_fix_html)
        self._reg(b_html, "gui.btn.fix_html")
        b_html.pack(side="left", padx=6)

        self.fix_log = self._make_log(tab)
        self._fix_findings: list = []

    # ---- Fix tab actions ----

    FIX_KINDS = ("cover", "duplicate", "corrupt")

    def _retranslate_fix_kinds(self) -> None:
        """Refill the category box in the current language, keeping the choice."""
        labels = [self._T(f"gui.fix.kind.{k}") for k in self.FIX_KINDS]
        self.fix_kind_box.configure(values=labels)
        current = self.fix_kind.get()
        if current in self.FIX_KINDS:
            self.fix_kind_label.set(labels[self.FIX_KINDS.index(current)])

    def _on_fix_kind_pick(self, _event=None) -> None:
        labels = [self._T(f"gui.fix.kind.{k}") for k in self.FIX_KINDS]
        chosen = self.fix_kind_label.get()
        if chosen in labels:
            self.fix_kind.set(self.FIX_KINDS[labels.index(chosen)])

    def _fix_selected(self):
        """The finding under the cursor, or None (with a message) if there isn't one."""
        sel = self.fix_list.curselection()
        if not sel or not self._fix_findings:
            self._info("gui.fix.pick_one")
            return None
        return self._fix_findings[sel[0]]

    def _fix_show(self, findings: list) -> None:
        kind = self.fix_kind.get()
        self._fix_findings = [f for f in findings if f.kind == kind]
        self.fix_list.delete(0, "end")
        for f in self._fix_findings:
            mark = "?" if f.ambiguous else (" " if f.folders else "!")
            # A leading disc marks an album that also exists in a synced source
            # folder — that is the copy the buttons will open, and editing it is
            # a local write instead of an SMB1 one.
            where = "▪" if f.is_local else " "
            self.fix_list.insert("end", f"{mark}{where} {f.title[:50]:<50} {f.detail[:58]}")
        located = sum(1 for f in self._fix_findings if f.folders)
        self._log(self.fix_log, self._T("gui.fix.summary", n=len(self._fix_findings),
                                        kind=self._T(f"gui.fix.kind.{kind}"), located=located))

    def _fix_load_data(self):
        """Load the two caches. Returns (harvest, index) or (None, None)."""
        ip = self.host_var.get().strip()
        harvest = hap_library.load_harvest(ip)
        index = hap_fixit.load_index(ip)
        if harvest is None or index is None:
            missing = []
            if harvest is None:
                missing.append(self._T("gui.fix.what.harvest"))
            if index is None:
                missing.append(self._T("gui.fix.what.index"))
            self._warn("gui.fix.need_scan", what=", ".join(missing))
            return None, None
        return harvest, index

    def on_fix_load(self) -> None:
        harvest, index = self._fix_load_data()
        if harvest is None:
            return
        self._clear(self.fix_log)
        self._fix_show(hap_fixit.build_findings(harvest, index))

    def on_fix_scan(self) -> None:
        """Index the shares (a few minutes). The library harvest is separate and
        much slower, so it is not triggered from here."""
        ip = self.host_var.get().strip()
        if not ip:
            self._warn("gui.warn.enter_ip")
            return

        def job():
            self._log_t("gui.log.indexing_shares", ip=ip)

            def note(share, i, total, files):
                if i % 100 == 0 or i == total:
                    self._log_t("gui.log.index_progress", share=share, i=i, total=total,
                                files=files)

            index = hap_fixit.crawl_shares(ip, progress=note)
            hap_fixit.save_index(index)
            counts = {s: len(f) for s, f in index["shares"].items()}
            self._log_t("gui.log.index_done", counts=counts)

        self._run_async(job, self.fix_log, use_progress=True)

    def on_fix_scan_local(self) -> None:
        """Index local music folders, for libraries not filed like the player's.

        Only needed when the folders you keep locally are named differently from
        the ones on the shares — otherwise the mapping on the Transfer tab
        already resolves each album directly, with nothing to scan.
        """
        ip = self.host_var.get().strip()
        roots = [m["local"] for m in self._collect_maps() if m.get("local")]
        if not roots:
            picked = filedialog.askdirectory(title=self._T("gui.btn.fix_scan_local"))
            if not picked:
                return
            roots = [picked]

        def job():
            self._log_t("gui.fix.scanning_local", what=", ".join(roots))
            index = hap_fixit.scan_local(roots)
            counts = {r: len(f) for r, f in index["roots"].items()}
            if not any(counts.values()):
                self._emit("log", line=self._T("gui.fix.local_empty"))
                return
            hap_fixit.save_local_index(index, ip or "local")
            self._emit("log", line=f"{counts}")

        self._run_async(job, self.fix_log, use_progress=True)

    def on_fix_open(self) -> None:
        """Open the album's folder — the local source copy when there is one.

        Editing the player's copy over SMB1 works but is slow, and the device
        serialises requests. The synced source folder is the same album on a
        local disk, so the edit is instant and the next Sync carries it over.
        """
        f = self._fix_selected()
        if f is None:
            return
        if not f.folders:
            self._info("gui.fix.not_located")
            return
        hap_fixit.open_folder(f.best_path)
        self._log(self.fix_log, self._fix_where(f))

    def on_fix_edit(self) -> None:
        f = self._fix_selected()
        if f is None:
            return
        if not f.folders:
            self._info("gui.fix.not_located")
            return
        used = hap_fixit.open_in_editor(f.best_path)
        if not used:
            self._warn("gui.fix.no_editor")
            return
        self._log(self.fix_log, f"{used}\n  {self._fix_where(f)}")

    def _fix_where(self, f) -> str:
        """One line saying which copy was opened, and what to do next."""
        if f.is_local:
            return f.local_path + "\n  " + self._T("gui.fix.then_sync")
        return f.path + "\n  " + self._T("gui.fix.on_player")

    def on_fix_copy(self) -> None:
        f = self._fix_selected()
        if f is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(f.best_path or f.title)
        self._log(self.fix_log, f.best_path or f.title)

    def on_fix_html(self) -> None:
        harvest, index = self._fix_load_data()
        if harvest is None:
            return
        target = filedialog.asksaveasfilename(
            defaultextension=".html", filetypes=[("HTML", "*.html")],
            initialfile="hap-to-fix.html")
        if not target:
            return
        findings = hap_fixit.build_findings(harvest, index)
        with open(target, "wb") as fh:
            fh.write(hap_fixit.render_html(findings, self.host_var.get().strip()).encode("utf-8"))
        self._log(self.fix_log, self._T("gui.log.report_written", path=target))
        hap_fixit.open_folder(os.path.dirname(target) or ".")

    def _make_log(self, parent: tk.Widget) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        txt = tk.Text(frame, height=10, wrap="none", font=("Consolas", 9),
                      background="#101014", foreground="#e8e8e8", insertbackground="#e8e8e8")
        sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set, state="disabled")
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return txt

    def _add_map_row(self, local: str = "", share: str = SHARES[0]) -> None:
        row = ttk.Frame(self.maps_frame)
        row.pack(fill="x", pady=2)
        local_var = tk.StringVar(value=local)
        share_var = tk.StringVar(value=share if share in SHARES else SHARES[0])
        ttk.Entry(row, textvariable=local_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="…", width=3,
                   command=lambda: self._pick_dir(local_var)).pack(side="left", padx=4)
        ttk.Label(row, text="→").pack(side="left")
        ttk.Combobox(row, textvariable=share_var, values=SHARES, width=14,
                     state="readonly").pack(side="left", padx=4)
        entry = {"frame": row, "local": local_var, "share": share_var}
        ttk.Button(row, text="✕", width=3,
                   command=lambda: self._remove_map_row(entry)).pack(side="left")
        self.map_rows.append(entry)

    def _remove_map_row(self, entry: dict) -> None:
        entry["frame"].destroy()
        self.map_rows.remove(entry)
        if not self.map_rows:  # always keep at least one row to fill in
            self._add_map_row()

    # ---------- small UI helpers ----------

    def _pick_dir(self, var: tk.StringVar) -> None:
        d = filedialog.askdirectory(initialdir=var.get() or os.getcwd())
        if d:
            var.set(os.path.normpath(d))

    def _pick_db(self) -> None:
        f = filedialog.askopenfilename(
            filetypes=[("HAP SQLite database", "*.db"), ("All files", "*.*")])
        if f:
            self.diff_db.set(os.path.normpath(f))

    def _collect_maps(self) -> list[dict]:
        return [{"local": r["local"].get().strip(), "share": r["share"].get()}
                for r in self.map_rows if r["local"].get().strip()]

    def _cfg(self) -> dict:
        """Build the config dict the engine expects, with _path set so the on-disk
        remote-index cache lands next to hap_sync.json — exactly like the CLI."""
        return {"host": self.host_var.get().strip(), "mac": self.mac_var.get().strip(),
                "maps": self._collect_maps(), "_path": str(CONFIG_PATH)}

    def _log(self, txt: tk.Text, line: str) -> None:
        txt.configure(state="normal")
        txt.insert("end", line + "\n")
        txt.see("end")
        txt.configure(state="disabled")

    def _clear(self, txt: tk.Text) -> None:
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.configure(state="disabled")

    # ---------- worker plumbing ----------

    def _emit(self, tag: str, **data) -> None:
        """Called from the worker thread — never touches tkinter directly."""
        self.q.put((tag, data))

    def _run_async(self, target, log_widget: tk.Text, *, use_progress: bool = False) -> None:
        if self.busy:
            return
        self.busy = True
        self.stop_event.clear()
        self._active_log = log_widget
        self._clear(log_widget)
        if use_progress:
            # Pulse an indeterminate bar until we know a file count — so a multi-minute
            # SMB listing never looks frozen. progmax later flips it to a real gauge.
            self.progress.configure(mode="indeterminate")
            self.progress.start(60)
            self.status_var.set(self._T("gui.status.working"))
        self._set_busy(True)

        def runner():
            try:
                target()
            except core.SmbError as e:
                self._emit("error", msg=str(e))
            except Exception as e:
                self._emit("error", msg=f"{type(e).__name__}: {e}")
            finally:
                self._emit("finished")

        threading.Thread(target=runner, daemon=True).start()
        self.root.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        try:
            while True:
                tag, d = self.q.get_nowait()
                self._dispatch(tag, d)
        except queue.Empty:
            pass
        if self.busy:
            self.root.after(POLL_MS, self._poll)

    def _dispatch(self, tag: str, d: dict) -> None:
        if tag == "log" and self._active_log is not None:
            self._log(self._active_log, d["line"])
        elif tag == "status":
            self.status_var.set(d["text"])
        elif tag == "progmax":
            self.progress.stop()  # leave indeterminate-pulse mode for a real gauge
            self.progress.configure(mode="determinate", value=0, maximum=max(1, d["total"]))
        elif tag == "progress":
            self.progress.configure(value=d["value"])
        elif tag == "conn":
            self.conn_dot.configure(foreground="#3c3" if d["ok"] else "#c33")
        elif tag == "fixstate":
            self._has_fixes = d["has"]
            self._findings = d["findings"]
            if not self.busy:
                self.fix_btn.configure(state="normal" if self._has_fixes else "disabled")
        elif tag == "fill":
            if d.get("ip"):
                self.host_var.set(d["ip"])
            if d.get("mac"):
                self.mac_var.set(d["mac"])
        elif tag == "error":
            if self._active_log is not None:
                self._log(self._active_log, f"⚠ {d['msg']}")
            messagebox.showerror(self._T("gui.app_title"), d["msg"])
        elif tag == "finished":
            self.busy = False
            self._set_busy(False)
            self.progress.stop()  # halt any pulse animation
            self.progress.configure(mode="determinate", value=0)

    def _set_busy(self, busy: bool) -> None:
        for w in self._action_widgets:
            try:
                w.configure(state="disabled" if busy else "normal")
            except tk.TclError:
                pass
        self.stop_btn.configure(state="normal" if busy else "disabled")
        # The Fix button has its own enable rule: only when a check found pending fixes.
        self.fix_btn.configure(
            state="normal" if (not busy and self._has_fixes) else "disabled")

    # ---------- pre-flight ----------

    def _need_host(self) -> bool:
        if not self.host_var.get().strip():
            self._warn("gui.warn.enter_ip")
            return False
        return True

    def _need_pysmb(self) -> bool:
        try:
            import smb  # noqa: F401
            return True
        except ImportError:
            messagebox.showerror(self._T("gui.app_title"), self._T("gui.msg.pysmb_needed"))
            return False

    def _need_maps(self) -> bool:
        if not self._collect_maps():
            self._warn("gui.warn.add_folder")
            return False
        return True

    def _warn(self, key: str, **kwargs) -> None:
        messagebox.showwarning(self._T("gui.app_title"), self._T(key, **kwargs))

    def _info(self, key: str, **kwargs) -> None:
        messagebox.showinfo(self._T("gui.app_title"), self._T(key, **kwargs))

    def _log_t(self, key: str, **kwargs) -> None:
        """Emit one translated line to the active log (worker-thread safe)."""
        self._emit("log", line=self._T(key, **kwargs))

    def _status_t(self, key: str, **kwargs) -> None:
        self._emit("status", text=self._T(key, **kwargs))

    # ---------- button handlers ----------

    def on_save_config(self) -> None:
        try:
            core.save_config(CONFIG_PATH, self.host_var.get().strip(),
                             self.mac_var.get().strip(), self._collect_maps())
            self._info("gui.msg.config_saved", path=CONFIG_PATH)
        except OSError as e:
            messagebox.showerror(self._T("gui.app_title"),
                                 self._T("gui.msg.config_save_failed", err=e))

    def _persist(self) -> None:
        """Silently remember the current host / MAC / folders so they're pre-filled next
        time. Called on Analyze, Sync and on close — no dialog, no manual save needed.
        Skips writing when there's nothing worth saving (fresh, untouched window)."""
        host, maps = self.host_var.get().strip(), self._collect_maps()
        if not host and not maps:
            return
        try:
            core.save_config(CONFIG_PATH, host, self.mac_var.get().strip(), maps)
        except OSError:
            pass  # best-effort; the explicit Save config button surfaces real errors

    def _on_close(self) -> None:
        self._persist()
        self.root.destroy()

    def on_autodetect(self) -> None:
        """Find the HAP on the LAN and fill IP + MAC.

        `discover.find_hap` scans every local /24 for an open ScalarWebAPI port
        and confirms each candidate with getSystemInformation (which also yields
        the MAC; ARP is the fallback). The HAP must be awake and on the same
        network (click Wake first if it's asleep).
        """
        def job():
            prefixes = discover.local_subnet_prefixes()
            if not prefixes:
                self._emit("error", msg=self._T("gui.log.net.no_interface"))
                return
            self._status_t("gui.conn.detecting")
            self._log_t("gui.log.net.scanning", port=API_PORT,
                        subnets=", ".join(p + "0/24" for p in prefixes))
            scan = discover.find_hap(
                prefixes=prefixes,
                on_candidates=lambda hosts: self._log_t("gui.log.net.candidates",
                                                        hosts=", ".join(hosts)))
            if not scan.candidates:
                self._status_t("gui.conn.not_found")
                self._log_t("gui.log.net.no_answer", port=API_PORT)
                return
            found = scan.found
            if found is None:
                self._status_t("gui.conn.not_found")
                self._log_t("gui.log.net.not_a_hap")
                return
            self._emit("fill", ip=found.ip, mac=found.mac)
            self._emit("conn", ok=True)
            summary = self._T("gui.log.net.detected", model=found.model, ip=found.ip) + (
                self._T("gui.log.net.mac", mac=found.mac) if found.mac
                else self._T("gui.log.net.no_mac"))
            self._emit("status", text=summary)
            self._emit("log", line=summary + "  —  " + self._T("gui.log.net.save_hint"))

        self._run_async(job, self.transfer_log)

    def on_check(self) -> None:
        if not self._need_host():
            return
        host = self.host_var.get().strip()

        def job():
            self._log_t("gui.log.check.start", host=host)
            findings = smb_doctor.diagnose(host)
            for line in smb_doctor.format_report(findings):
                self._emit("log", line=line)
            s = smb_doctor.summary(findings)
            # The dot reflects whether *our* transfer will work (the pysmb probe), the thing
            # that actually matters for this app — not the native-Windows-only knobs.
            self._emit("conn", ok=s["transfer_ok"])
            self._emit("log", line="")
            self._log_t("gui.log.check.works" if s["transfer_ok"] else "gui.log.check.broken")
            if s["fixable"]:
                self._log_t("gui.log.check.fixable", n=s["fixable"])
            self._emit("fixstate", has=bool(s["fixable"]), findings=findings)

        self._run_async(job, self.transfer_log)

    def on_fix(self) -> None:
        if self.busy or not self._has_fixes:
            return
        fixes = smb_doctor.pending_fixes(self._findings)
        detail = "\n".join(f"• {f.title}" for f in fixes)
        prompt = self._T("gui.fix_access.prompt", n=len(fixes), detail=detail)
        if any(f.needs_admin for f in fixes):
            prompt += "\n\n" + self._T("gui.fix_access.uac")
        if not messagebox.askyesno(self._T("gui.fix_access.title"), prompt):
            return
        findings = self._findings
        host = self.host_var.get().strip()  # read on the main thread, not in the job

        def job():
            self._log_t("gui.log.fix.applying")
            _changed, msg = smb_doctor.apply_fixes(
                findings, on_log=lambda line: self._emit("log", line=line))
            self._emit("log", line=msg)
            # Re-diagnose so the report and the connection dot reflect the new state.
            after = smb_doctor.diagnose(host)
            s = smb_doctor.summary(after)
            self._emit("conn", ok=s["transfer_ok"])
            self._emit("fixstate", has=bool(s["fixable"]), findings=after)
            if not s["fixable"]:
                self._log_t("gui.log.fix.resolved")

        self._run_async(job, self.transfer_log)

    def on_wake(self) -> None:
        mac = self.mac_var.get().strip()

        def job():
            try:
                hap_common.send_wol(mac)
                self._log_t("gui.log.wol_sent", mac=mac)
            except ValueError as e:
                self._emit("error", msg=str(e))

        self._run_async(job, self.transfer_log)

    def on_stop(self) -> None:
        self.stop_event.set()
        self.status_var.set(self._T("gui.status.stop_requested"))

    def _scan_options(self) -> dict:
        """Everything a scan needs, read from the widgets on the main thread.

        The worker must never touch a tk variable: outside the main loop such a
        call blocks (or raises "main thread is not in main loop").
        """
        return {"cfg": self._cfg(), "maps": self._collect_maps(),
                "include_unsupported": self.unsupported_var.get(),
                "refresh": self.refresh_var.get(), "new_only": self.new_only_var.get()}

    def _scan_maps(self, lazy: core.LazySmb, opts: dict) -> tuple[list[dict], int]:
        """Analyse every mapped folder; returns (scans, number of maps whose folder is gone).

        Runs on the worker thread with the options captured by `_scan_options`.
        """
        cfg, maps = opts["cfg"], opts["maps"]
        include_unsup, refresh, new_only = (opts["include_unsupported"], opts["refresh"],
                                            opts["new_only"])
        scans: list[dict] = []
        missing = 0
        for m in maps:
            self._log_t("gui.log.analyzing", local=m["local"], share=m["share"])
            s = core.scan_map(cfg, lazy, m, include_unsup, refresh, new_only=new_only,
                              on_scan=self._log_scan,
                              on_progress=self._listing_progress(m["share"]))
            if s is None:
                self._log_t("gui.log.folder_missing", local=m["local"])
                missing += 1
            else:
                scans.append(s)
        return scans, missing

    def on_plan(self) -> None:
        if not (self._need_host() and self._need_maps() and self._need_pysmb()):
            return
        self._persist()  # using the app remembers the setup — no manual save needed
        opts = self._scan_options()

        def job():
            lazy = core.LazySmb(opts["cfg"]["host"])
            try:
                scans, _missing = self._scan_maps(lazy, opts)
                total = len(core.jobs_for(scans))
                self._status_t("gui.status.analysis_done", n=total)
                self._emit("log", line="\n" + self._T("gui.log.plan", n=total)
                           + (self._T("gui.log.plan_new_only") if opts["new_only"] else ""))
            finally:
                lazy.close()

        self._run_async(job, self.transfer_log, use_progress=True)

    def on_sync(self) -> None:
        if not (self._need_host() and self._need_maps() and self._need_pysmb()):
            return
        self._persist()  # using the app remembers the setup — no manual save needed
        opts = self._scan_options()
        cfg = opts["cfg"]

        def job():
            lazy = core.LazySmb(cfg["host"])
            try:
                scans, _missing = self._scan_maps(lazy, opts)
                jobs = core.jobs_for(scans)
                if not jobs:
                    self._status_t("gui.status.in_sync")
                    self._emit("log", line="\n" + self._T("gui.log.in_sync"))
                    return
                self._emit("progmax", total=len(jobs))
                smb = lazy.smb
                smb.reconnect()  # a long listing can desync SMB1 — upload on a fresh connection
                self._emit("log", line="\n" + self._T("gui.log.transferring", n=len(jobs)))
                index_by_share = {s["share"]: s["remote"] for s in scans}
                done, failed = core.transfer(smb, jobs, index_by_share,
                                             on_event=self._transfer_event,
                                             should_cancel=self.stop_event.is_set)
                for share, idx in index_by_share.items():
                    core.save_cache(cfg, share, idx)
                self._status_t("gui.status.done", done=done, failed=failed)
                self._emit("log", line="\n" + self._T("gui.log.done", done=done, failed=failed))
                self._log_t("gui.log.reindex")
            finally:
                lazy.close()

        self._run_async(job, self.transfer_log, use_progress=True)

    def _transfer_event(self, kind: str, **e) -> None:
        """Progress callback for `core.transfer` (runs on the worker thread)."""
        if kind == "file_done":
            self._emit("progress", value=e["i"])
            self._emit("status", text=f"{e['i']}/{e['total']} — {e['share']}:/{e['rel']}")
            self._emit("log", line=f"  [{e['i']}/{e['total']}] {e['share']}:/{e['rel']}  "
                                   f"({human_size(e['size'])})")
        elif kind == "file_failed":
            self._emit("progress", value=e["i"])
            self._log_t("gui.log.file_failed", i=e["i"], total=e["total"], share=e["share"],
                        rel=e["rel"], error=e["error"])
        elif kind == "cancelled":
            self._emit("log", line="\n" + self._T("gui.log.cancelled", i=e["i"], total=e["total"]))

    def on_validate(self) -> None:
        folder = self.validate_dir.get().strip()
        if not folder or not os.path.isdir(folder):
            self._warn("gui.warn.valid_folder")
            return

        def job():
            self._emit("log", line=self._T("gui.log.scanning_folder", folder=folder) + "\n")
            r = comp.scan_folder(folder)
            for key, value in (("gui.val.playable", r["n_ok"]),
                               ("gui.val.unsupported", r["n_unsup"]),
                               ("gui.val.junk", r["n_junk"]),
                               ("gui.val.over_ceiling", r["n_hi"]),
                               ("gui.val.missing_cover", len(r["no_cover"]))):
                self._emit("log", line=f"{self._T(key):<32}: {value}")
            self._log_section(self._T("gui.val.sec.junk"), r["junk"])
            self._log_section(self._T("gui.val.sec.unsupported"), r["unsup"])
            self._log_section(self._T("gui.val.sec.hires"), r["hires"])
            self._log_section(self._T("gui.val.sec.no_cover"), r["no_cover"])
            clean = r["n_unsup"] == r["n_junk"] == r["n_hi"] == 0
            self._emit("log", line="\n" + self._T("gui.val.ok" if clean else "gui.val.issues"))

        self._run_async(job, self.validate_log)

    def on_diff(self) -> None:
        db, folder = self.diff_db.get().strip(), self.diff_dir.get().strip()
        if not db or not os.path.isfile(db):
            self._warn("gui.warn.choose_db")
            return
        if not folder or not os.path.isdir(folder):
            self._warn("gui.warn.choose_local")
            return

        def job():
            self._emit("log", line=self._T("gui.log.comparing") + "\n")
            r = comp.diff_library(db, folder)
            self._log_t("gui.diff.have", n=r["have_count"])
            self._emit("log", line=self._T("gui.diff.local", path=os.path.abspath(folder)) + "\n")
            self._log_section(self._T("gui.diff.new", n=len(r["new"])), r["new"], "+",
                              limit=len(r["new"]))
            self._log_section(self._T("gui.diff.existing", n=len(r["existing"])),
                              r["existing"], "=")

        self._run_async(job, self.diff_log)

    # ---------- log formatting (worker thread) ----------

    LOG_CAP = 300  # keep the on-screen log snappy; the FULL list always goes to the plan file

    def _listing_progress(self, share: str):
        """Callback for the slow remote SMB listing — shows a live file count in the status
        line so the user sees the scan is alive (the bar keeps pulsing meanwhile)."""
        return lambda n: self._status_t("gui.status.listing", share=share, n=f"{n:,}")

    def _log_scan(self, s: dict) -> None:
        todo, remote = s["todo"], s["remote"]
        new_only = s.get("new_only")
        to_go = core.actionable(s)
        self._emit("log", line="  " + self._T(
            "gui.log.scan_summary", source=s["source"], remote=len(remote), n=len(to_go),
            size=human_size(sum(t.size for t in to_go)),
            junk=s["skipped"]["junk"], unsupported=s["skipped"]["unsupported"]))

        changed, new = core.split_plan(todo)
        cap = self.LOG_CAP
        # CHANGED first — these are the surprising ones (path already on the HAP, bytes differ).
        if changed:
            head = ("\n  " + self._T("gui.log.changed_head", n=len(changed))
                    + self._T("gui.log.changed_skipped" if new_only else "gui.log.changed_hint")
                    + self._T("gui.log.changed_tail"))
            self._emit("log", line=head)
            for entry in changed[:cap]:
                self._emit("log",
                           line=f"      ~ {entry.rel}  ({core.describe_changed(entry, remote)})")
            if len(changed) > cap:
                self._emit("log", line="      "
                           + self._T("gui.log.more_in_file", n=len(changed) - cap))
        if new:
            self._emit("log", line="\n  " + self._T("gui.log.new_head", n=len(new)))
            for entry in new[:cap]:
                self._emit("log", line=f"      + {entry.rel}  ({human_size(entry.size)})")
            if len(new) > cap:
                self._emit("log", line="      "
                           + self._T("gui.log.more_in_file", n=len(new) - cap))

        # Always dump the COMPLETE plan to a file so nothing is ever hidden behind a cap.
        try:
            plan_path = core.write_plan_file(s, CONFIG_PATH.parent)
            self._emit("log", line="\n  "
                       + self._T("gui.log.plan_saved", n=len(todo), path=plan_path))
        except OSError as e:
            self._emit("log", line="  " + self._T("gui.log.plan_save_failed", err=e))

    def _log_section(self, title: str, items: list, marker: str = "-", limit: int = 25) -> None:
        if not items:
            return
        self._emit("log", line=f"\n{title}:")
        for it in items[:limit]:
            self._emit("log", line=f"  {marker} {it}")
        if len(items) > limit:
            self._emit("log", line="  " + self._T("gui.log.more", n=len(items) - limit))

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    app = App()
    if os.environ.get("HAP_GUI_SMOKE"):  # headless construction check — build, render once, exit
        app.root.withdraw()
        app.root.update()
        app.root.destroy()
        print("smoke OK")
        return 0
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
