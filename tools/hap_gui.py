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
  - Validate        : scan a folder *before* transfer for junk / unsupported / >192 kHz / missing cover.
  - Compare library : semantic diff of a local <Artist>/<Album>/ tree against the HAP's SQLite catalog.

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
    pip install pyinstaller pysmb
    pyinstaller --onefile --windowed --name HapSync ^
        --collect-submodules smb tools/hap_gui.py
    # -> dist/HapSync.exe   (see tools/build_gui.ps1 for a one-liner)

tkinter is stdlib (no extra dependency for the UI itself). All blocking work (SMB listing,
uploads, folder walks, the subnet scan) runs on a worker thread and reports back through a
queue, so the window never freezes — tkinter is only ever touched from the main thread.
"""
from __future__ import annotations

import os
import queue
import socket
import sys
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Allow `python tools/hap_gui.py` from anywhere — import the engine modules next to us.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hap_sync as core      # noqa: E402
import hap_companion as comp  # noqa: E402
import smb_doctor             # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "hap_sync.json"
SHARES = ("HAP_Internal", "HAP_External")
POLL_MS = 80          # how often the UI drains the worker->UI queue
API_PORT = 60200      # ScalarWebAPI — the port we scan for to find the HAP
GITHUB_URL = "https://github.com/Guillain-RDCDE/HAP-Revival"


def load_config_tolerant(path: Path) -> dict:
    """Read hap_sync.json if present, else return an empty skeleton. Unlike core.load_config
    this never raises on a missing/partial file — the GUI is how you *create* the config."""
    cfg = {"host": "", "mac": "", "maps": []}
    if path.exists():
        try:
            import json
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
            cfg.update({k: data.get(k, cfg[k]) for k in ("host", "mac", "maps")})
        except Exception:  # noqa: BLE001 — a corrupt file shouldn't block startup
            pass
    return cfg


def save_config(path: Path, host: str, mac: str, maps: list) -> None:
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"host": host, "mac": mac, "maps": maps}, f, indent=2, ensure_ascii=False)


def _norm_mac(mac: str) -> str:
    """Normalise a MAC to the uppercase colon form used in hap_sync.json (80:56:F2:…)."""
    return mac.strip().upper().replace("-", ":")


def arp_mac(ip: str) -> str:
    """Look up `ip`'s MAC in the Windows ARP table (fallback when the API is unreachable).
    Returns '' if not found. Runs `arp` without flashing a console window."""
    import re
    import subprocess
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # keep the windowed .exe console-free
    try:
        out = subprocess.run(["arp", "-a", ip], capture_output=True, text=True,
                             timeout=4, creationflags=flags).stdout
    except Exception:  # noqa: BLE001
        return ""
    m = re.search(r"([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})", out)
    return _norm_mac(m.group(1)) if m else ""


def _primary_lan_ip() -> str | None:
    """The local IPv4 the OS would use to reach the LAN (no packet actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return None
    finally:
        s.close()


def local_subnet_prefixes() -> list[str]:
    """Return the distinct /24 prefixes (e.g. '192.168.1.') of every local IPv4 interface.
    Covers multi-homed machines; skips loopback and link-local."""
    candidates: list[str] = []
    pip = _primary_lan_ip()
    if pip:
        candidates.append(pip)
    try:
        candidates += socket.gethostbyname_ex(socket.gethostname())[2]
    except Exception:  # noqa: BLE001
        pass
    prefixes: list[str] = []
    for ip in candidates:
        if ip.startswith(("127.", "169.254.")):
            continue
        prefix = ip.rsplit(".", 1)[0] + "."
        if prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def scan_for_hap_hosts(port: int = API_PORT, timeout: float = 0.4) -> list[str]:
    """Scan every local /24 for hosts with `port` open (concurrently). Reliable where SSDP
    multicast isn't — these are the HAP candidates the caller then confirms via the API."""
    from concurrent.futures import ThreadPoolExecutor
    hosts = [p + str(i) for p in local_subnet_prefixes() for i in range(1, 255)]

    def probe(h: str):
        s = socket.socket()
        s.settimeout(timeout)
        try:
            return h if s.connect_ex((h, port)) == 0 else None
        finally:
            s.close()

    # High concurrency: most probes hit dead virtual/VPN subnets and block for the full
    # timeout, so width matters more than per-probe speed. One worker per host is fine —
    # they're short-lived socket connects, and it keeps a multi-subnet sweep around ~2 s.
    with ThreadPoolExecutor(max_workers=min(512, len(hosts) or 1)) as ex:
        return [h for h in ex.map(probe, hosts) if h]


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("HAP Sync")
        self.root.geometry("760x620")
        self.root.minsize(680, 520)

        self.q: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self._active_log: tk.Text | None = None
        self._action_widgets: list = []  # disabled while a job runs
        self._findings: list = []        # last SMB-doctor result (for the Fix button)
        self._has_fixes = False          # are there pending Windows fixes to apply?

        cfg = load_config_tolerant(CONFIG_PATH)
        self.host_var = tk.StringVar(value=cfg["host"])
        self.mac_var = tk.StringVar(value=cfg["mac"])
        self.unsupported_var = tk.BooleanVar(value=False)
        self.refresh_var = tk.BooleanVar(value=False)
        self.map_rows: list[dict] = []

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

    # ---------- UI construction ----------

    def _build_connection_bar(self) -> None:
        bar = ttk.LabelFrame(self.root, text="HAP")
        bar.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(bar, text="IP address:").grid(row=0, column=0, padx=(8, 4), pady=6, sticky="w")
        ttk.Entry(bar, textvariable=self.host_var, width=18).grid(row=0, column=1, pady=6, sticky="w")
        ttk.Label(bar, text="MAC:").grid(row=0, column=2, padx=(12, 4), pady=6, sticky="w")
        ttk.Entry(bar, textvariable=self.mac_var, width=20).grid(row=0, column=3, pady=6, sticky="w")

        btns = ttk.Frame(bar)
        btns.grid(row=0, column=4, padx=8, sticky="e")
        bar.columnconfigure(4, weight=1)
        self.conn_dot = ttk.Label(btns, text="●", foreground="#888")
        self.conn_dot.pack(side="left", padx=(0, 8))
        for text, cmd in (("Auto-detect", self.on_autodetect),
                          ("Check", self.on_check),
                          ("Wake", self.on_wake),
                          ("Save config", self.on_save_config)):
            b = ttk.Button(btns, text=text, command=cmd)
            b.pack(side="left", padx=3)
            self._action_widgets.append(b)
        # Appears after a Check that finds fixable Windows SMB problems. Managed on its own
        # (not in _action_widgets) so it stays disabled until there is actually something to fix.
        self.fix_btn = ttk.Button(btns, text="Fix Windows access",
                                  command=self.on_fix, state="disabled")
        self.fix_btn.pack(side="left", padx=3)

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

    def _build_transfer_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="Transfer")

        maps_box = ttk.LabelFrame(tab, text="Folders to sync  (PC → HAP)")
        maps_box.pack(fill="x", padx=8, pady=8)
        self.maps_frame = ttk.Frame(maps_box)
        self.maps_frame.pack(fill="x", padx=4, pady=4)
        add = ttk.Button(maps_box, text="+ Add a folder", command=lambda: self._add_map_row())
        add.pack(anchor="w", padx=6, pady=(0, 6))
        self._action_widgets.append(add)

        opts = ttk.Frame(tab)
        opts.pack(fill="x", padx=8)
        ttk.Checkbutton(opts, text="Include unsupported formats",
                        variable=self.unsupported_var).pack(side="left")
        ttk.Checkbutton(opts, text="Re-scan the HAP (ignore cache)",
                        variable=self.refresh_var).pack(side="left", padx=16)

        actions = ttk.Frame(tab)
        actions.pack(fill="x", padx=8, pady=8)
        b_plan = ttk.Button(actions, text="Analyze", command=self.on_plan)
        b_sync = ttk.Button(actions, text="Sync", command=self.on_sync)
        b_plan.pack(side="left")
        b_sync.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(actions, text="Stop", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self._action_widgets += [b_plan, b_sync]

        self.progress = ttk.Progressbar(tab, mode="determinate")
        self.progress.pack(fill="x", padx=8)
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(tab, textvariable=self.status_var).pack(anchor="w", padx=8, pady=(2, 4))
        self.transfer_log = self._make_log(tab)

    def _build_validate_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="Validate")
        self.validate_dir = tk.StringVar()
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Label(row, text="Folder:").pack(side="left")
        ttk.Entry(row, textvariable=self.validate_dir).pack(side="left", fill="x", expand=True, padx=6)
        b_browse = ttk.Button(row, text="Browse…",
                              command=lambda: self._pick_dir(self.validate_dir))
        b_val = ttk.Button(row, text="Validate", command=self.on_validate)
        b_browse.pack(side="left")
        b_val.pack(side="left", padx=6)
        self._action_widgets += [b_browse, b_val]
        help_txt = (
            "What this does: scans a PC folder before you send it and reports files the HAP "
            "would reject or that would clutter its library — junk (Thumbs.db, .DS_Store, "
            ".ffs_tmp…) the HAP indexes as ghost tracks, unsupported formats, PCM over 192 kHz "
            "(above the HAP's playback limit) and albums with no cover art.\n"
            "When to use it: optional. Sync already skips junk and unsupported files on its own, "
            "so this is just a pre-flight report — most useful to catch >192 kHz files and "
            "missing covers, which Sync won't fix for you.")
        ttk.Label(tab, text=help_txt, foreground="#888", justify="left",
                  wraplength=700).pack(anchor="w", padx=8, pady=(0, 4))
        self.validate_log = self._make_log(tab)

    def _build_diff_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb)
        nb.add(tab, text="Compare library")
        self.diff_db = tk.StringVar()
        self.diff_dir = tk.StringVar()
        r1 = ttk.Frame(tab)
        r1.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Label(r1, text="HAP database (.db):", width=18).pack(side="left")
        ttk.Entry(r1, textvariable=self.diff_db).pack(side="left", fill="x", expand=True, padx=6)
        b_db = ttk.Button(r1, text="Browse…", command=self._pick_db)
        b_db.pack(side="left")
        r2 = ttk.Frame(tab)
        r2.pack(fill="x", padx=8, pady=2)
        ttk.Label(r2, text="Local folder:", width=18).pack(side="left")
        ttk.Entry(r2, textvariable=self.diff_dir).pack(side="left", fill="x", expand=True, padx=6)
        b_dir = ttk.Button(r2, text="Browse…", command=lambda: self._pick_dir(self.diff_dir))
        b_dir.pack(side="left")
        b_diff = ttk.Button(tab, text="Compare", command=self.on_diff)
        b_diff.pack(anchor="w", padx=8, pady=6)
        self._action_widgets += [b_db, b_dir, b_diff]
        help_txt = (
            "What this does: compares a local <Artist>/<Album>/ tree against the HAP's own music "
            "database and lists which albums are NEW vs already on the device — matched by "
            "content (artist + album names), not by filename or date.\n"
            "What it needs: the HAP's SQLite catalog (.db), which you only get by reading the "
            "HAP's internal disk — so this is an advanced/occasional tool. For everyday use, just "
            "use Sync: it already compares against the files actually on the share and transfers "
            "only what's missing.")
        ttk.Label(tab, text=help_txt, foreground="#888", justify="left",
                  wraplength=700).pack(anchor="w", padx=8, pady=(0, 4))
        self.diff_log = self._make_log(tab)

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
            self.status_var.set("Working…")
        self._set_busy(True)

        def runner():
            try:
                target()
            except SystemExit as e:  # core.Smb raises SystemExit on connection failure
                self._emit("error", msg=str(e) or "SMB connection failed")
            except Exception as e:  # noqa: BLE001
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
            messagebox.showerror("HAP Sync", d["msg"])
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
            messagebox.showwarning("HAP Sync", "Enter the HAP's IP address (or click Auto-detect).")
            return False
        return True

    def _need_pysmb(self) -> bool:
        try:
            import smb  # noqa: F401
            return True
        except ImportError:
            messagebox.showerror(
                "HAP Sync",
                "Transferring needs the pysmb library.\n\nInstall it with:\n    pip install pysmb")
            return False

    def _need_maps(self) -> bool:
        if not self._collect_maps():
            messagebox.showwarning("HAP Sync", "Add at least one local folder to transfer.")
            return False
        return True

    # ---------- button handlers ----------

    def on_save_config(self) -> None:
        try:
            save_config(CONFIG_PATH, self.host_var.get().strip(),
                        self.mac_var.get().strip(), self._collect_maps())
            messagebox.showinfo("HAP Sync", f"Configuration saved:\n{CONFIG_PATH}")
        except OSError as e:
            messagebox.showerror("HAP Sync", f"Could not save: {e}")

    def _persist(self) -> None:
        """Silently remember the current host / MAC / folders so they're pre-filled next
        time. Called on Analyze, Sync and on close — no dialog, no manual save needed.
        Skips writing when there's nothing worth saving (fresh, untouched window)."""
        host, maps = self.host_var.get().strip(), self._collect_maps()
        if not host and not maps:
            return
        try:
            save_config(CONFIG_PATH, host, self.mac_var.get().strip(), maps)
        except OSError:
            pass  # best-effort; the explicit Save config button surfaces real errors

    def _on_close(self) -> None:
        self._persist()
        self.root.destroy()

    def on_autodetect(self) -> None:
        """Find the HAP on the LAN and fill IP + MAC. Scans every local /24 for an open
        ScalarWebAPI port, then confirms each candidate with getSystemInformation (which also
        yields the MAC; ARP is the fallback). Stdlib only — works without pysmb. SSDP is not
        used: it's unreliable on multi-homed Windows and the HAP ignored M-SEARCH in testing.
        The HAP must be awake and on the same network (click Wake first if it's asleep)."""
        def job():
            prefixes = local_subnet_prefixes()
            if not prefixes:
                self._emit("error", msg="No local network interface found.")
                return
            self._emit("status", text="Scanning the network…")
            self._emit("log", line=f"Scanning {', '.join(p + '0/24' for p in prefixes)} "
                                   f"for a HAP on port {API_PORT}…")
            hosts = scan_for_hap_hosts()
            if not hosts:
                self._emit("status", text="No HAP found.")
                self._emit("log", line="No device answered on port "
                                       f"{API_PORT}. Make sure the HAP is on and on the same "
                                       "network (click Wake if it's asleep), then retry.")
                return
            self._emit("log", line=f"Candidate(s) with the API port open: {', '.join(hosts)}")
            import hap_client
            for ip in hosts:
                try:
                    info = hap_client.HAP(ip).system_info()
                except Exception:  # noqa: BLE001 — not a HAP / not answering; try the next host
                    continue
                if "HAP" not in (info.model or "").upper():
                    continue
                mac = _norm_mac(info.mac) or arp_mac(ip)
                self._emit("fill", ip=ip, mac=mac)
                self._emit("conn", ok=True)
                summary = (f"Detected: {info.model} at {ip}"
                           + (f", MAC {mac}" if mac else " (MAC not found — enter it manually)"))
                self._emit("status", text=summary)
                self._emit("log", line=summary + "  —  click Save config to remember it.")
                return
            self._emit("status", text="No HAP found.")
            self._emit("log", line="Found open ports but none was a HAP "
                                   "(getSystemInformation didn't confirm an HAP model).")

        self._run_async(job, self.transfer_log)

    def on_check(self) -> None:
        if not self._need_host():
            return
        host = self.host_var.get().strip()

        def job():
            self._emit("log", line=f"Diagnosing SMB access to {host}…")
            findings = smb_doctor.diagnose(host)
            for line in smb_doctor.format_report(findings):
                self._emit("log", line=line)
            s = smb_doctor.summary(findings)
            # The dot reflects whether *our* transfer will work (the pysmb probe), the thing
            # that actually matters for this app — not the native-Windows-only knobs.
            self._emit("conn", ok=s["transfer_ok"])
            self._emit("log", line="")
            self._emit("log", line="Transfer (this app): "
                       + ("WORKS — you can sync." if s["transfer_ok"] else "NOT WORKING."))
            if s["fixable"]:
                self._emit("log", line=f"{s['fixable']} Windows issue(s) block File Explorer / "
                           "HAP Music Transfer. Click “Fix Windows access” to repair them.")
            self._emit("fixstate", has=bool(s["fixable"]), findings=findings)

        self._run_async(job, self.transfer_log)

    def on_fix(self) -> None:
        if self.busy or not self._has_fixes:
            return
        fixes = smb_doctor.pending_fixes(self._findings)
        needs_admin = any(f.needs_admin for f in fixes)
        detail = "\n".join(f"• {f.title}" for f in fixes)
        prompt = (f"Apply {len(fixes)} fix(es) so File Explorer and HAP Music Transfer can "
                  f"reach the HAP?\n\n{detail}")
        if needs_admin:
            prompt += "\n\nWindows will ask for administrator permission (UAC)."
        if not messagebox.askyesno("Fix Windows SMB access", prompt):
            return
        findings = self._findings

        def job():
            self._emit("log", line="Applying fixes…")
            changed, msg = smb_doctor.apply_fixes(
                findings, on_log=lambda line: self._emit("log", line=line))
            self._emit("log", line=msg)
            # Re-diagnose so the report and the connection dot reflect the new state.
            after = smb_doctor.diagnose(self.host_var.get().strip())
            s = smb_doctor.summary(after)
            self._emit("conn", ok=s["transfer_ok"])
            self._emit("fixstate", has=bool(s["fixable"]), findings=after)
            if not s["fixable"]:
                self._emit("log", line="All Windows SMB issues resolved.")

        self._run_async(job, self.transfer_log)

    def on_wake(self) -> None:
        mac = self.mac_var.get().strip()

        def job():
            try:
                core.send_wol(mac)
                self._emit("log", line=f"Wake-on-LAN magic packet sent to {mac}.")
            except ValueError as e:
                self._emit("error", msg=str(e))

        self._run_async(job, self.transfer_log)

    def on_stop(self) -> None:
        self.stop_event.set()
        self.status_var.set("Stop requested — finishing the current file…")

    def on_plan(self) -> None:
        if not (self._need_host() and self._need_maps() and self._need_pysmb()):
            return
        self._persist()  # using the app remembers the setup — no manual save needed
        cfg, maps = self._cfg(), self._collect_maps()
        include_unsup, refresh = self.unsupported_var.get(), self.refresh_var.get()

        def job():
            lazy = core.LazySmb(cfg["host"])
            try:
                total = 0
                for m in maps:
                    self._emit("log", line=f"Analyzing: {m['local']}  →  {m['share']}")
                    s = core.scan_map(cfg, lazy, m, include_unsup, refresh,
                                      on_scan=lambda s: self._log_scan(s),
                                      on_progress=self._listing_progress(m["share"]))
                    if s is None:
                        self._emit("log", line=f"  ! folder not found: {m['local']}")
                    else:
                        total += len(s["todo"])
                self._emit("status", text=f"Analysis done: {total} file(s) to transfer.")
                self._emit("log", line=f"\nPlan: {total} file(s) would transfer. "
                                       "Click Sync to do it.")
            finally:
                lazy.close()

        self._run_async(job, self.transfer_log, use_progress=True)

    def on_sync(self) -> None:
        if not (self._need_host() and self._need_maps() and self._need_pysmb()):
            return
        self._persist()  # using the app remembers the setup — no manual save needed
        cfg, maps = self._cfg(), self._collect_maps()
        include_unsup, refresh = self.unsupported_var.get(), self.refresh_var.get()

        def job():
            lazy = core.LazySmb(cfg["host"])
            try:
                scans = []
                for m in maps:
                    self._emit("log", line=f"Analyzing: {m['local']}  →  {m['share']}")
                    s = core.scan_map(cfg, lazy, m, include_unsup, refresh,
                                      on_scan=lambda s: self._log_scan(s),
                                      on_progress=self._listing_progress(m["share"]))
                    if s is not None:
                        scans.append(s)
                jobs = [(s["share"], rel, ap, size)
                        for s in scans for rel, ap, size, _ in s["todo"]]
                if not jobs:
                    self._emit("status", text="Already in sync.")
                    self._emit("log", line="\nNothing to transfer — already in sync.")
                    return
                self._emit("progmax", total=len(jobs))
                smb = lazy.smb
                smb.reconnect()  # a long listing can desync SMB1 — upload on a fresh connection
                self._emit("log", line=f"\nTransferring {len(jobs)} file(s)…")
                index_by_share = {s["share"]: s["remote"] for s in scans}

                def on_event(kind, **e):
                    if kind == "file_done":
                        self._emit("progress", value=e["i"])
                        self._emit("status",
                                   text=f"{e['i']}/{e['total']} — {e['share']}:/{e['rel']}")
                        self._emit("log",
                                   line=f"  [{e['i']}/{e['total']}] {e['share']}:/{e['rel']}  "
                                        f"({core.human(e['size'])})")
                    elif kind == "file_failed":
                        self._emit("progress", value=e["i"])
                        self._emit("log",
                                   line=f"  [{e['i']}/{e['total']}] FAILED {e['share']}:/{e['rel']} "
                                        f"— {e['error']}")
                    elif kind == "cancelled":
                        self._emit("log", line=f"\nCancelled at {e['i']}/{e['total']}.")

                done, failed = core.transfer(smb, jobs, index_by_share, on_event=on_event,
                                             should_cancel=self.stop_event.is_set)
                for share, idx in index_by_share.items():
                    core.save_cache(cfg, share, idx)
                self._emit("status", text=f"Done: {done} transferred, {failed} failed.")
                self._emit("log", line=f"\nDone: {done} transferred, {failed} failed. "
                                       "(cache updated)")
                self._emit("log", line="The HAP re-indexes new files within seconds.")
            finally:
                lazy.close()

        self._run_async(job, self.transfer_log, use_progress=True)

    def on_validate(self) -> None:
        folder = self.validate_dir.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("HAP Sync", "Choose a valid folder to validate.")
            return

        def job():
            self._emit("log", line=f"Scanning {folder}…\n")
            r = comp.scan_folder(folder)
            self._emit("log", line=f"Playable audio files   : {r['n_ok']}")
            self._emit("log", line=f"Unsupported            : {r['n_unsup']}")
            self._emit("log", line=f"Junk (pollutes library): {r['n_junk']}")
            self._emit("log", line=f"PCM over 192 kHz       : {r['n_hi']}")
            self._emit("log", line=f"Albums without cover   : {len(r['no_cover'])}")
            self._log_section("[JUNK] delete before transfer", r["junk"])
            self._log_section("[UNSUPPORTED] the HAP won't play these", r["unsup"])
            self._log_section("[OVER 192 kHz] exceeds the PCM path — downsample first", r["hires"])
            self._log_section("[NO COVER FILE] (embedded art may still work)", r["no_cover"])
            clean = r["n_unsup"] == r["n_junk"] == r["n_hi"] == 0
            self._emit("log", line="\nVerdict: clean ✓" if clean else "\nVerdict: issues above.")

        self._run_async(job, self.validate_log)

    def on_diff(self) -> None:
        db, folder = self.diff_db.get().strip(), self.diff_dir.get().strip()
        if not db or not os.path.isfile(db):
            messagebox.showwarning("HAP Sync", "Choose the HAP library .db file.")
            return
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("HAP Sync", "Choose a local folder to compare.")
            return

        def job():
            self._emit("log", line="Comparing…\n")
            r = comp.diff_library(db, folder)
            self._emit("log", line=f"HAP library: {r['have_count']} (artist, album) pairs")
            self._emit("log", line=f"Local tree : {os.path.abspath(folder)}\n")
            self._log_section(f"NEW — not on the HAP ({len(r['new'])})", r["new"], "+", limit=10**9)
            self._log_section(f"ALREADY on the HAP ({len(r['existing'])}) — skip these",
                              r["existing"], "=")

        self._run_async(job, self.diff_log)

    # ---------- log formatting (worker thread) ----------

    def _listing_progress(self, share: str):
        """Callback for the slow remote SMB listing — shows a live file count in the status
        line so the user sees the scan is alive (the bar keeps pulsing meanwhile)."""
        return lambda n: self._emit("status", text=f"Listing {share}: {n:,} files so far…")

    def _log_scan(self, s: dict) -> None:
        tot = sum(x[2] for x in s["todo"])
        self._emit("log", line=f"  [{s['source']}] remote library: {len(s['remote'])} files; "
                               f"to transfer: {len(s['todo'])} ({core.human(tot)})  "
                               f"[junk={s['skipped']['junk']}, unsupported={s['skipped']['unsupported']}]")
        for rel, _ap, size, why in s["todo"][:12]:
            self._emit("log", line=f"      + {rel}  ({core.human(size)}, {why})")
        if len(s["todo"]) > 12:
            self._emit("log", line=f"      … and {len(s['todo']) - 12} more")

    def _log_section(self, title: str, items: list, marker: str = "-", limit: int = 25) -> None:
        if not items:
            return
        self._emit("log", line=f"\n{title}:")
        for it in items[:limit]:
            self._emit("log", line=f"  {marker} {it}")
        if len(items) > limit:
            self._emit("log", line=f"  … and {len(items) - limit} more")

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
