#!/usr/bin/env python3
"""
hap_sync — a HAP-aware replacement for FreeFileSync, dedicated to the HAP-Z1ES / HAP-S1.

It transfers music from your PC to the HAP over the device's SMB1 share and keeps it in
sync incrementally (copies only what's new or changed) — while doing what a generic sync
tool can't: skipping junk that would pollute the library (`.ffs_tmp`, `Thumbs.db`, `._*`…),
skipping formats the HAP can't play, preserving the `<Artist>/<Album>/` layout, and (option)
waking the device first.

It speaks SMB1 directly via `pysmb`, so you do NOT have to enable the insecure SMB1 client
in Windows. Anonymous access (the HAP allows guest read/write).

The HAP exposes two shares — `HAP_Internal` (the built-in disk) and `HAP_External` (a USB
drive) — and you feed each from a different PC folder. hap_sync handles both in one run via
a small config file:

    # hap_sync.json  (next to this script, or pass --config PATH)
    {
      "host": "192.168.1.28",
      "mac":  "80:56:F2:85:0E:27",
      "maps": [
        {"local": "D:/Music/Internal", "share": "HAP_Internal"},
        {"local": "D:/Music/External", "share": "HAP_External"}
      ]
    }

Usage:
    python tools/hap_sync.py plan            # dry-run: show exactly what would transfer
    python tools/hap_sync.py sync            # do it (only new/changed files)
    python tools/hap_sync.py sync --only HAP_External
    python tools/hap_sync.py sync --all      # include formats flagged as unsupported
    python tools/hap_sync.py sync --refresh  # re-scan the HAP instead of using the cache
    python tools/hap_sync.py refresh         # rebuild the cached remote index
    python tools/hap_sync.py list HAP_Internal
    python tools/hap_sync.py wake
    python tools/hap_sync.py check

Caching: listing a 60-70k-file SMB1 share takes minutes, so the remote file index is
cached on disk (a `.hap_sync_cache/` folder next to your config). The first run scans
the device; after that, `plan`/`sync` read the cache (instant) and a `sync` folds the
files it just uploaded into the cache — so steady-state runs never re-scan. Pass
`--refresh` (or run `refresh`) to force a full re-listing if the HAP changed by other means.

Never deletes anything on the HAP (add/update only). Requires: pip install pysmb
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, NamedTuple

from hap_common import (
    API_PORT,
    SMB_DIRECT_PORT,
    SMB_NETBIOS_PORT,
    force_utf8_stdio,
    human_size,
    local_timestamp,
    read_json,
    safe_name,
    send_wol,
    tcp_port_open,
    write_json,
)
from hap_media import classify, is_junk

__all__ = [
    "Job", "LazySmb", "LocalFile", "PlanEntry", "Smb", "SmbError",
    "actionable", "classify", "human", "is_junk", "load_config", "local_index",
    "remote_index", "scan_map", "send_wol", "transfer",
]

# Re-exported under the names the GUI and the tests have always used.
human = human_size
port_open = tcp_port_open

#: How often the slow remote listing reports progress, in files found.
PROGRESS_EVERY = 1000
#: `list` shows at most this many paths; the count line says how many there are.
LIST_PREVIEW = 200


class SmbError(RuntimeError):
    """The SMB session could not be opened, or pysmb is missing."""


class LocalFile(NamedTuple):
    """One file under a mapped local folder."""

    rel: str   # path relative to the map root, POSIX separators (what the share sees)
    path: str  # absolute local path
    size: int
    kind: str  # 'audio' | 'sidecar' | 'unsupported'


class PlanEntry(NamedTuple):
    """One file the plan says should go to the HAP, and why."""

    rel: str
    path: str
    size: int
    status: str  # 'new' (absent on the HAP) | 'changed' (present, byte size differs)


class Job(NamedTuple):
    """One upload: which share, which file."""

    share: str
    rel: str
    path: str
    size: int


# ---------- config ----------


def default_config_path() -> Path:
    return Path(__file__).resolve().parent / "hap_sync.json"


def load_config_tolerant(path: str | os.PathLike) -> dict:
    """Read hap_sync.json if present, else an empty skeleton.

    Unlike `load_config` this never raises on a missing or partial file: the GUI
    is how a config gets *created*, so it must start from nothing.
    """
    cfg: dict = {"host": "", "mac": "", "maps": []}
    data = read_json(Path(path))  # None on a missing or corrupt file: neither blocks startup
    if isinstance(data, dict):
        cfg.update({k: data.get(k, cfg[k]) for k in ("host", "mac", "maps")})
    return cfg


def save_config(path: str | os.PathLike, host: str, mac: str, maps: list[dict]) -> Path:
    """Write hap_sync.json in the shape `load_config` reads."""
    return write_json(Path(path), {"host": host, "mac": mac, "maps": maps}, indent=2)


def load_config(path: str | os.PathLike | None) -> dict:
    """Read hap_sync.json. Raises FileNotFoundError / ValueError with a readable message."""
    target = Path(path) if path else default_config_path()
    if not target.exists():
        raise FileNotFoundError(
            f"config not found: {target}\n"
            "Create a hap_sync.json (see the header of this file for the format)."
        )
    cfg = read_json(target)
    if not isinstance(cfg, dict):
        raise ValueError(f"config is not valid JSON: {target}")
    if not cfg.get("host") or not cfg.get("maps"):
        raise ValueError("config must contain 'host' and a non-empty 'maps' list")
    cfg["_path"] = str(target.resolve())
    return cfg


# ---------- remote-index cache ----------
# Listing a 60-70k-file SMB1 share takes minutes, so we cache the remote index
# (relative-path -> size) per (host, share) and reuse it. After a sync we fold the
# files we just uploaded straight into the cache, so steady-state runs never re-scan.
# Use `--refresh` (or the `refresh` command) to force a full re-listing.


def cache_dir(cfg: dict) -> Path:
    """`.hap_sync_cache/` next to the config file (or in the cwd without one)."""
    cfg_path = cfg.get("_path")
    base = Path(cfg_path).parent if cfg_path else Path.cwd()
    d = base / ".hap_sync_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_file(cfg: dict, share: str) -> Path:
    return cache_dir(cfg) / (safe_name(f"{cfg['host']}__{share}") + ".json")


def load_cache(cfg: dict, share: str) -> dict | None:
    data = read_json(cache_file(cfg, share))
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return None  # absent or corrupt: rescan
    return data


def save_cache(cfg: dict, share: str, files: dict) -> None:
    data = {"host": cfg["host"], "share": share, "built": local_timestamp(), "files": files}
    write_json(cache_file(cfg, share), data, atomic=True)


# ---------- SMB ----------


class Smb:
    """Anonymous SMB1 connection to the HAP, with reconnect-on-error.

    A long recursive listing can desync pysmb's SMB1 session (a failed `listPath`
    can leave the socket mid-message), which then breaks the next `storeFile`. We
    reconnect on any error and use a *fresh* connection for the upload phase.

    Raises SmbError (never SystemExit) so a GUI can report the failure in a dialog.
    """

    #: NetBIOS (139) first: the HAP's ancient Samba 3.0.37 desyncs SMB1 framing over
    #: Direct TCP (445) after a file or two ("Invalid protocol header for Direct TCP
    #: session message"), so prefer the transport it handles cleanly; 445 is the fallback.
    TRANSPORTS = ((False, SMB_NETBIOS_PORT), (True, SMB_DIRECT_PORT))
    CONNECT_TIMEOUT_SEC = 10

    def __init__(self, host: str):
        self.host = host
        self.conn: Any = None
        self.open()

    def open(self) -> None:
        try:
            from smb.SMBConnection import SMBConnection
        except ImportError as exc:
            raise SmbError("pysmb is required.  Install it with:  pip install pysmb") from exc
        last: Exception | None = None
        for direct, port in self.TRANSPORTS:
            try:
                c = SMBConnection("", "", "hap-sync", "HAP",
                                  use_ntlm_v2=False, is_direct_tcp=direct)
                if c.connect(self.host, port, timeout=self.CONNECT_TIMEOUT_SEC):
                    self.conn = c
                    return
            except Exception as e:
                last = e
        raise SmbError(f"SMB connection to {self.host} failed ({last})")

    def reconnect(self) -> None:
        self.close()
        self.open()

    def close(self) -> None:
        if self.conn is None:
            return
        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = None


class LazySmb:
    """Open the SMB connection only when a live scan/upload actually needs it."""

    def __init__(self, host: str):
        self.host = host
        self._smb: Smb | None = None

    @property
    def smb(self) -> Smb:
        if self._smb is None:
            self._smb = Smb(self.host)
        return self._smb

    def close(self) -> None:
        if self._smb is not None:
            self._smb.close()
            self._smb = None


def remote_index(
    smb: Smb, share: str, on_progress: Callable[[int], None] | None = None
) -> tuple[dict[str, int], int]:
    """(map of remote 'relative/path' -> size, number of dirs we couldn't read).

    Listing a 60-70k-file SMB1 share takes minutes, so `on_progress(file_count)` fires
    every ~1000 files found — lets a GUI show a live count instead of a frozen window.
    """
    out: dict[str, int] = {}
    skipped = 0
    stack = ["/"]
    last_reported = 0
    while stack:
        d = stack.pop()
        try:
            entries = smb.conn.listPath(share, d)
        except Exception:
            smb.reconnect()
            try:
                entries = smb.conn.listPath(share, d)
            except Exception:
                skipped += 1
                continue
        for f in entries:
            if f.filename in (".", ".."):
                continue
            p = d.rstrip("/") + "/" + f.filename
            if f.isDirectory:
                stack.append(p)
            else:
                out[p.lstrip("/")] = f.file_size
        if on_progress and len(out) - last_reported >= PROGRESS_EVERY:
            last_reported = len(out)
            on_progress(len(out))
    if on_progress:
        on_progress(len(out))
    return out, skipped


def local_index(root: str, include_unsupported: bool) -> tuple[list[LocalFile], dict[str, int]]:
    """Every file under `root` worth transferring, plus how many were skipped and why.

    Junk is always left out; unsupported formats only when `include_unsupported`.
    """
    files: list[LocalFile] = []
    skipped = {"junk": 0, "unsupported": 0}
    for dirpath, _dirs, names in os.walk(root):
        for fn in names:
            kind = classify(fn)
            if kind == "junk":
                skipped["junk"] += 1
                continue
            if kind == "unsupported" and not include_unsupported:
                skipped["unsupported"] += 1
                continue
            ap = os.path.join(dirpath, fn)
            rel = os.path.relpath(ap, root).replace(os.sep, "/")
            try:
                size = os.path.getsize(ap)
            except OSError:
                continue
            files.append(LocalFile(rel, ap, size, kind))
    return files, skipped


def ensure_dirs(smb: Smb, share: str, rel: str, made: set[str]) -> None:
    """Create every parent folder of `rel` on the share (once per session)."""
    parts = rel.split("/")[:-1]
    cur = ""
    for p in parts:
        cur = f"{cur}/{p}"
        if cur in made:
            continue
        try:
            smb.conn.createDirectory(share, cur)
        except Exception:
            pass
        made.add(cur)


# ---------- planning ----------


def get_remote(
    cfg: dict, lazy: LazySmb, share: str, refresh: bool, on_progress=None
) -> tuple[dict[str, int], str]:
    """Return (index dict, source label). Uses the cache unless refresh; rebuilds + saves on miss.
    `on_progress(file_count)` is forwarded to the live SMB listing (no-op on a cache hit)."""
    if not refresh:
        c = load_cache(cfg, share)
        if c is not None:
            return c["files"], f"cache {c['built']}"
    idx, skipped = remote_index(lazy.smb, share, on_progress=on_progress)
    save_cache(cfg, share, idx)
    src = f"live scan, {len(idx)} files" + (f", {skipped} dirs unreadable" if skipped else "")
    return idx, src


def plan_entries(local: Iterable[LocalFile], remote: dict[str, int]) -> list[PlanEntry]:
    """Which local files are absent from the HAP, or present with a different size."""
    todo: list[PlanEntry] = []
    for f in local:
        rsize = remote.get(f.rel)
        if rsize is None:
            todo.append(PlanEntry(f.rel, f.path, f.size, "new"))
        elif rsize != f.size:
            todo.append(PlanEntry(f.rel, f.path, f.size, "changed"))
    return todo


def scan_map(cfg: dict, lazy: LazySmb, m: dict, include_unsupported: bool, refresh: bool,
             on_scan=None, on_progress=None, new_only: bool = False) -> dict | None:
    """Build the transfer plan for one map. `on_scan(s)` reports the result (defaults to
    printing it for the CLI; the GUI passes its own callback). `on_progress(file_count)` is
    forwarded to the remote listing so a GUI can show progress during the slow SMB1 scan.
    `new_only` records the add-only intent so the display and the transfer both honor it."""
    local_root = os.path.abspath(m["local"])
    share = m["share"]
    if not os.path.isdir(local_root):
        print(f"  ! local folder not found: {local_root}")
        return None
    remote, source = get_remote(cfg, lazy, share, refresh, on_progress=on_progress)
    files, skipped = local_index(local_root, include_unsupported)
    s = {"local": local_root, "share": share, "remote": remote, "source": source,
         "todo": plan_entries(files, remote), "skipped": skipped, "new_only": new_only}
    (on_scan or print_scan)(s)
    return s


def actionable(s: dict) -> list[PlanEntry]:
    """The todo entries that will actually transfer. With `new_only`, 'changed' files (already
    on the HAP, just different bytes) are kept as-is and skipped — only genuinely new files go."""
    todo = [PlanEntry(*t) for t in s["todo"]]
    if s.get("new_only"):
        return [t for t in todo if t.status == "new"]
    return todo


def split_plan(todo: Iterable[PlanEntry]) -> tuple[list[PlanEntry], list[PlanEntry]]:
    """(changed, new), each sorted by path, case-insensitively."""
    entries = [PlanEntry(*t) for t in todo]
    changed = sorted((t for t in entries if t.status == "changed"), key=lambda t: t.rel.lower())
    new = sorted((t for t in entries if t.status == "new"), key=lambda t: t.rel.lower())
    return changed, new


def describe_changed(entry: PlanEntry, remote: dict[str, int]) -> str:
    """`local 5.1 MB vs HAP 5.0 MB, Δ+12.0 KB` — so a re-tag and a re-rip look different."""
    rsize = remote.get(entry.rel)
    if rsize is None:
        return human_size(entry.size)
    delta = entry.size - rsize
    sign = "+" if delta >= 0 else "-"
    return (f"local {human_size(entry.size)} vs HAP {human_size(rsize)}, "
            f"Δ{sign}{human_size(abs(delta))}")


def print_scan(s: dict) -> None:
    todo, remote = s["todo"], s["remote"]
    tot = sum(t[2] for t in todo)
    print(f"  {s['local']}  ->  {s['share']}   [{s['source']}]")
    print(f"    remote has {len(remote)} files; to transfer: {len(todo)} ({human_size(tot)})"
          f"   [skipped junk={s['skipped']['junk']}, unsupported={s['skipped']['unsupported']}]")
    changed, new = split_plan(todo)
    # CHANGED = path already on the HAP but the byte size differs (usually a re-tag). Show both
    # sizes + the delta so it's obvious whether the audio really changed or it's just metadata.
    if changed:
        tag = ("SKIPPED, kept as-is on the HAP (--new-only)" if s.get("new_only")
               else "already on the HAP, bytes differ")
        print(f"    CHANGED ({len(changed)}) — {tag}:")
        for entry in changed:
            print(f"      ~ {entry.rel}  ({describe_changed(entry, remote)})")
    if new:
        print(f"    NEW ({len(new)}):")
        for entry in new:
            print(f"      + {entry.rel}  ({human_size(entry.size)})")


def plan_file_lines(s: dict) -> list[str]:
    """The complete plan for one map, as text: nothing hidden behind a display cap."""
    todo, remote = s["todo"], s["remote"]
    actionable_entries = actionable(s)
    xfer = sum(t.size for t in actionable_entries)
    changed, new = split_plan(todo)
    lines = [
        f"Transfer plan   {s['local']}  ->  {s['share']}",
        f"remote library: {len(remote)} files | would transfer: "
        f"{len(actionable_entries)} ({human_size(xfer)})"
        + ("  [new-only: changed files listed below are skipped]" if s.get("new_only") else ""),
        "",
    ]
    if changed:
        lines.append(f"CHANGED ({len(changed)}) — already on the HAP, bytes differ:")
        lines += [f"~ {e.rel}  ({describe_changed(e, remote)})" for e in changed]
        lines.append("")
    if new:
        lines.append(f"NEW ({len(new)}):")
        lines += [f"+ {e.rel}  ({human_size(e.size)})" for e in new]
    return lines


def write_plan_file(s: dict, folder: str | os.PathLike) -> Path:
    """Save `plan_file_lines(s)` as `hap_plan_<share>.txt` in `folder`; returns the path."""
    path = Path(folder) / f"hap_plan_{s['share']}.txt"
    path.write_text("\n".join(plan_file_lines(s)) + "\n", encoding="utf-8")
    return path


def selected_maps(cfg: dict, only: str | None) -> list[dict]:
    """The maps to act on: all of them, or just the one feeding `only`."""
    return [m for m in cfg["maps"] if not only or m["share"] == only]


def scan_all(cfg: dict, lazy: LazySmb, args: argparse.Namespace) -> list[dict]:
    new_only = getattr(args, "new_only", False)
    scans = []
    for m in selected_maps(cfg, getattr(args, "only", None)):
        s = scan_map(cfg, lazy, m, args.all, args.refresh, new_only=new_only)
        if s is not None:
            scans.append(s)
    return scans


def jobs_for(scans: Iterable[dict]) -> list[Job]:
    return [Job(s["share"], t.rel, t.path, t.size) for s in scans for t in actionable(s)]


# ---------- transfer ----------


def transfer(smb: Smb, jobs: list[Job], index_by_share: dict, on_event=None,
             should_cancel=None) -> tuple[int, int]:
    """Upload `jobs` over a fresh SMB1 session.

    Each successful upload is folded into `index_by_share[share]` (the cache map) so the
    caller can persist it and skip these files next run. `on_event(kind, **data)` fires for
    progress — kinds: 'file_done' / 'file_failed' / 'cancelled' (the CLI prints them, the GUI
    drives a progress bar). `should_cancel()` is polled between files for cooperative abort.
    Returns (done, failed). Same retry-on-fresh-connection logic the CLI always used.
    """
    on_event = on_event or (lambda *a, **k: None)
    total = len(jobs)
    made: set[str] = set()
    done = failed = 0
    for i, job in enumerate((Job(*j) for j in jobs), 1):
        if should_cancel and should_cancel():
            on_event("cancelled", i=i, total=total)
            break
        # A fresh session per file: the HAP's SMB1 stack desyncs if a single connection is
        # reused across many stores, so we never let it live long enough to drift.
        smb.reconnect()
        made.clear()
        ensure_dirs(smb, job.share, job.rel, made)
        ok = False
        for attempt in (1, 2):  # retry once on a fresh connection
            try:
                with open(job.path, "rb") as fp:
                    smb.conn.storeFile(job.share, "/" + job.rel, fp)
                ok = True
                break
            except Exception as e:
                if attempt == 1:
                    smb.reconnect()
                    made.clear()
                    ensure_dirs(smb, job.share, job.rel, made)
                else:
                    failed += 1
                    on_event("file_failed", i=i, total=total, share=job.share, rel=job.rel,
                             error=str(e))
        if ok:
            done += 1
            index_by_share[job.share][job.rel] = job.size  # fold into the cache
            on_event("file_done", i=i, total=total, share=job.share, rel=job.rel, size=job.size)
    return done, failed


# ---------- commands ----------


def cmd_plan(cfg: dict, args: argparse.Namespace) -> int:
    lazy = LazySmb(cfg["host"])
    new_only = getattr(args, "new_only", False)
    try:
        total = len(jobs_for(scan_all(cfg, lazy, args)))
        print(f"\nPlan: {total} file(s) would transfer. Run `sync` to do it."
              + ("  (--new-only: 'changed' files are kept as-is on the HAP)" if new_only else "")
              + "\n(remote index came from the on-disk cache where shown; "
              "use --refresh to re-scan)")
    finally:
        lazy.close()
    return 0


def cmd_sync(cfg: dict, args: argparse.Namespace) -> int:
    lazy = LazySmb(cfg["host"])
    try:
        scans = scan_all(cfg, lazy, args)
        jobs = jobs_for(scans)
        if not jobs:
            print("\nNothing to transfer — already in sync.")
            return 0
        if args.dry_run:
            print(f"\n[dry-run] {len(jobs)} file(s) would transfer. Drop --dry-run to do it.")
            return 0
        smb = lazy.smb
        smb.reconnect()  # a long listing can desync SMB1 — upload on a fresh connection
        print(f"\nTransferring {len(jobs)} file(s)…")
        index_by_share = {s["share"]: s["remote"] for s in scans}

        def on_event(kind: str, **d) -> None:
            if kind == "file_done":
                print(f"  [{d['i']}/{d['total']}] {d['share']}:/{d['rel']}  "
                      f"({human_size(d['size'])})")
            elif kind == "file_failed":
                print(f"  [{d['i']}/{d['total']}] FAILED {d['share']}:/{d['rel']} — {d['error']}")

        done, failed = transfer(smb, jobs, index_by_share, on_event=on_event)
        for share, idx in index_by_share.items():
            save_cache(cfg, share, idx)  # persist so the next run doesn't re-scan what we just sent
        print(f"\nDone: {done} transferred, {failed} failed.  (cache updated)")
        print("The HAP auto-reindexes files dropped on the share within seconds.")
        return 1 if failed else 0
    finally:
        lazy.close()


def cmd_list(cfg: dict, args: argparse.Namespace) -> int:
    lazy = LazySmb(cfg["host"])
    try:
        idx, source = get_remote(cfg, lazy, args.share, args.refresh)
        for p in sorted(idx)[:LIST_PREVIEW]:
            print(f"  {human_size(idx[p]):>9}  {p}")
        print(f"\n{len(idx)} files on {args.share}.  [{source}]")
    finally:
        lazy.close()
    return 0


def cmd_refresh(cfg: dict, args: argparse.Namespace) -> int:
    lazy = LazySmb(cfg["host"])
    try:
        shares = {m["share"] for m in selected_maps(cfg, getattr(args, "only", None))}
        for share in sorted(shares):
            _idx, source = get_remote(cfg, lazy, share, refresh=True)
            print(f"  {share}: {source}  -> cached")
    finally:
        lazy.close()
    return 0


def cmd_wake(cfg: dict, _args: argparse.Namespace) -> int:
    try:
        send_wol(cfg.get("mac", ""))
    except ValueError:
        print("error: set a valid 'mac' in the config to use wake", file=sys.stderr)
        return 2
    print(f"Magic packet sent to {cfg.get('mac')}")
    return 0


def cmd_check(cfg: dict, args: argparse.Namespace) -> int:
    """Full SMB access diagnosis via smb_doctor: the authoritative pysmb transfer probe plus,
    on Windows, the native-path SMB-hardening checks. `--fix` applies any remediations."""
    import smb_doctor

    host = cfg["host"]
    findings = smb_doctor.diagnose(host)
    print("\n".join(smb_doctor.format_report(findings)))

    # Bonus line: the ScalarWebAPI port the control app uses (not part of the SMB picture).
    mark = "✓" if tcp_port_open(host, API_PORT) else "·"
    print(f"{mark} ScalarWebAPI (control app) port {API_PORT}")

    s = smb_doctor.summary(findings)
    print()
    print("Transfer (this tool): " + ("WORKS" if s["transfer_ok"] else "NOT WORKING"))
    if s["fixable"]:
        print(f"{s['fixable']} fixable native-Windows issue(s)"
              + (" — admin required." if s["needs_admin"] else "."))
        if getattr(args, "fix", False):
            changed, msg = smb_doctor.apply_fixes(findings, on_log=print)
            print(msg)
            return 0 if changed else 1
        print("Re-run `hap_sync check --fix` to apply them.")
    return 0 if s["transfer_ok"] else 1


COMMANDS: dict[str, Callable[[dict, argparse.Namespace], int]] = {
    "plan": cmd_plan,
    "sync": cmd_sync,
    "list": cmd_list,
    "refresh": cmd_refresh,
    "wake": cmd_wake,
    "check": cmd_check,
}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="hap_sync", description="HAP-aware music sync (replaces FreeFileSync for the HAP).")
    ap.add_argument("--config", help="path to hap_sync.json")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("plan", "sync"):
        p = sub.add_parser(name)
        p.add_argument("--only", help="limit to one share, e.g. HAP_External")
        p.add_argument("--all", action="store_true", help="include unsupported formats too")
        p.add_argument("--refresh", action="store_true",
                       help="re-scan the HAP instead of using the cached index")
        p.add_argument("--new-only", action="store_true",
                       help="add only files missing from the HAP; never overwrite a file that "
                            "is already there (skip 'changed')")
        if name == "sync":
            p.add_argument("--dry-run", action="store_true")
    pl = sub.add_parser("list")
    pl.add_argument("share")
    pl.add_argument("--refresh", action="store_true", help="re-scan instead of using the cache")
    pr = sub.add_parser("refresh", help="rebuild the on-disk remote-index cache")
    pr.add_argument("--only", help="limit to one share")
    sub.add_parser("wake")
    pc = sub.add_parser("check", help="diagnose SMB access (and optionally fix Windows issues)")
    pc.add_argument("--fix", action="store_true",
                    help="apply fixes for any native-Windows SMB problems (asks for admin)")
    return ap


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        return COMMANDS[args.cmd](cfg, args)
    except SmbError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
