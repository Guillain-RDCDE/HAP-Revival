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

Local copies (backup disks): a map can also point at a local folder instead of a share,
with `"dest"` in place of `"share"`. The HAP maps always run first; the local ones follow,
as many as you like. A local copy carries every format (only junk is left out) and
compares size and modification time. What it does with files that are no longer in the
source is set per map with `"delete"`:

    {"local": "D:/Music/External", "dest": "F:/Backup/External", "delete": "mirror"}

    keep    never delete anything (the default)
    list    show the extra files in the plan, delete nothing
    mirror  delete them, so the copy matches the source exactly

A mirror holds its deletions back when the source is empty, or when they would remove
more than half of the copy: that is a wrong or unplugged source far more often than a
real clean-up. `sync --allow-mass-delete` lets them through once you have checked.

Never deletes anything on the HAP (add/update only). Requires: pip install pysmb
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, NamedTuple

import hap_update

from hap_common import (
    API_PORT,
    SmbConnectError,
    connect_smb,
    force_utf8_stdio,
    human_size,
    local_timestamp,
    read_json_dict,
    safe_name,
    send_wol,
    tcp_port_open,
    write_json,
)
from hap_media import classify

#: How often the slow remote listing reports progress, in files found.
PROGRESS_EVERY = 1000
#: `list` shows at most this many paths; the count line says how many there are.
LIST_PREVIEW = 200

#: What a local copy does with files that are no longer in its source.
DELETE_MODES = ("keep", "list", "mirror")
#: A mirror holds its deletions back above this share of the copy...
MASS_DELETE_RATIO = 0.5
#: ...once the copy holds at least this many files (a tiny copy may legitimately empty out).
MASS_DELETE_MIN = 20
#: FAT and exFAT store modification times to the nearest 2 seconds.
MTIME_SLACK = 2.0
#: A local copy is written under this suffix, then renamed: an interrupted copy never
#: leaves a truncated file under the real name.
PART_SUFFIX = ".hapsync_part"


class SmbError(RuntimeError):
    """The SMB session could not be opened, or pysmb is missing."""


class LocalFile(NamedTuple):
    """One file under a mapped local folder."""

    rel: str  # path relative to the map root, POSIX separators (what the share sees)
    path: str  # absolute local path
    size: int
    kind: str  # 'audio' | 'sidecar' | 'unsupported'
    mtime: float = 0.0  # only local copies compare it; the HAP index has sizes only


class DestFile(NamedTuple):
    """One file already in a local destination folder."""

    rel: str
    path: str
    size: int
    mtime: float


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
    data = read_json_dict(Path(path))  # None on a missing or corrupt file: neither blocks startup
    if data:
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
    cfg = read_json_dict(target)
    if cfg is None:
        raise ValueError(f"config is not valid JSON: {target}")
    if not cfg.get("host") or not cfg.get("maps"):
        raise ValueError("config must contain 'host' and a non-empty 'maps' list")
    for m in cfg["maps"]:
        if not m.get("local") or bool(m.get("share")) == bool(m.get("dest")):
            raise ValueError(
                "each map needs 'local' and either 'share' (a HAP share) or 'dest' (a local folder)"
            )
        if m.get("delete", "keep") not in DELETE_MODES:
            raise ValueError(f"'delete' must be one of {', '.join(DELETE_MODES)}")
    cfg["_path"] = str(target.resolve())
    return cfg


def is_local_map(m: dict) -> bool:
    """A map feeding a local folder (a backup disk) rather than a HAP share."""
    return bool(m.get("dest"))


def map_target(m: dict) -> str:
    """Where a map sends its files: the share name, or the destination folder."""
    return m.get("dest") or m.get("share", "")


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
    data = read_json_dict(cache_file(cfg, share))
    if data is None or not isinstance(data.get("files"), dict):
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

    def __init__(self, host: str):
        self.host = host
        self.conn: Any = None
        self.open()

    def open(self) -> None:
        try:
            self.conn, _port = connect_smb(self.host, "hap-sync")
        except ImportError as exc:
            raise SmbError("pysmb is required.  Install it with:  pip install pysmb") from exc
        except SmbConnectError as exc:
            raise SmbError(str(exc)) from exc

    def reconnect(self) -> None:
        self.close()
        self.open()

    def close(self) -> None:
        if self.conn is None:
            return
        with contextlib.suppress(Exception):
            self.conn.close()
        self.conn = None


class LazySmb:
    """Open the SMB connection only when a live scan/upload actually needs it."""

    def __init__(self, host: str):
        self.host = host
        self._smb: Smb | None = None
        # One index per share for the whole run: two maps feeding the same share then
        # share one dict, so the uploads of both are folded into the cache that is saved.
        self.remotes: dict[str, tuple[dict[str, int], str]] = {}

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
                st = os.stat(ap)
            except OSError:
                continue
            files.append(LocalFile(rel, ap, st.st_size, kind, st.st_mtime))
    return files, skipped


def path_key(rel: str) -> str:
    """How two relative paths are compared in a local folder: Windows and macOS ignore case,
    so `Album/A.flac` and `album/a.flac` are the same file there, not a copy plus an orphan."""
    return rel.casefold() if os.name == "nt" or sys.platform == "darwin" else rel


def dest_index(root: str) -> dict[str, DestFile]:
    """Every file already under a local destination, keyed by `path_key`. Nothing is
    filtered: junk left in a copy is part of what a mirror cleans up."""
    out: dict[str, DestFile] = {}
    for dirpath, _dirs, names in os.walk(root):
        for fn in names:
            ap = os.path.join(dirpath, fn)
            rel = os.path.relpath(ap, root).replace(os.sep, "/")
            try:
                st = os.stat(ap)
            except OSError:
                continue
            out[path_key(rel)] = DestFile(rel, ap, st.st_size, st.st_mtime)
    return out


def ensure_dirs(smb: Smb, share: str, rel: str, made: set[str]) -> None:
    """Create every parent folder of `rel` on the share (once per session)."""
    parts = rel.split("/")[:-1]
    cur = ""
    for p in parts:
        cur = f"{cur}/{p}"
        if cur in made:
            continue
        with contextlib.suppress(Exception):
            smb.conn.createDirectory(share, cur)
        made.add(cur)


# ---------- planning ----------


def get_remote(
    cfg: dict, lazy: LazySmb, share: str, refresh: bool, on_progress=None
) -> tuple[dict[str, int], str]:
    """Return (index dict, source label). Uses the cache unless refresh; rebuilds + saves on miss.
    `on_progress(file_count)` is forwarded to the live SMB listing (no-op on a cache hit)."""
    memo = getattr(lazy, "remotes", None)
    if memo is not None and share in memo:
        return memo[share]
    result = None
    if not refresh:
        c = load_cache(cfg, share)
        if c is not None:
            result = c["files"], f"cache {c['built']}"
    if result is None:
        idx, skipped = remote_index(lazy.smb, share, on_progress=on_progress)
        save_cache(cfg, share, idx)
        src = f"live scan, {len(idx)} files" + (f", {skipped} dirs unreadable" if skipped else "")
        result = idx, src
    if memo is not None:
        memo[share] = result
    return result


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


def plan_local_entries(local: Iterable[LocalFile], dest: dict[str, DestFile]) -> list[PlanEntry]:
    """Which source files are absent from a local copy, or differ in size or date.

    Unlike the HAP, a local folder gives us modification times, and copies keep them
    (`shutil.copy2`), so a re-tag that happens to keep the byte size is still caught.
    """
    todo: list[PlanEntry] = []
    for f in local:
        d = dest.get(path_key(f.rel))
        if d is None:
            todo.append(PlanEntry(f.rel, f.path, f.size, "new"))
        elif d.size != f.size or abs(d.mtime - f.mtime) > MTIME_SLACK:
            todo.append(PlanEntry(f.rel, f.path, f.size, "changed"))
    return todo


def _inside(a: str, b: str) -> bool:
    """Is folder `a` the same as, or inside, folder `b`?"""
    a, b = os.path.normcase(os.path.abspath(a)), os.path.normcase(os.path.abspath(b))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def local_map_problem(m: dict) -> str | None:
    """Why a local-copy map cannot run, or None. One of:

    - 'source_missing'   the source folder is not there
    - 'dest_unreachable' the destination's drive is not there (a backup disk unplugged)
    - 'overlap'          one folder is inside the other: copying would feed on itself
    """
    src, dest = os.path.abspath(m["local"]), os.path.abspath(m["dest"])
    if not os.path.isdir(src):
        return "source_missing"
    if not os.path.isdir(dest) and not os.path.isdir(os.path.splitdrive(dest)[0] + os.sep):
        return "dest_unreachable"
    if _inside(src, dest) or _inside(dest, src):
        return "overlap"
    return None


def mass_delete(files: int, dest: int, orphans: int) -> bool:
    """Would a mirror's deletions look like a wrong source rather than a clean-up?"""
    if not orphans:
        return False
    if files == 0:
        return True
    return dest >= MASS_DELETE_MIN and orphans > MASS_DELETE_RATIO * dest


def scan_local_map(
    m: dict, on_scan=None, new_only: bool = False, allow_mass_delete: bool = False
) -> dict | None:
    """Build the plan for one local copy: what to copy, and what is extra in the copy."""
    problem = local_map_problem(m)
    if problem is not None:
        what = {
            "source_missing": f"local folder not found: {os.path.abspath(m['local'])}",
            "dest_unreachable": f"destination not reachable (disk unplugged?): {m['dest']}",
            "overlap": f"source and destination are inside each other: {m['local']} / {m['dest']}",
        }[problem]
        print(f"  ! {what}")
        return None
    local_root, dest_root = os.path.abspath(m["local"]), os.path.abspath(m["dest"])
    mode = m.get("delete", "keep")
    # A backup carries every format; only junk is left out.
    files, skipped = local_index(local_root, include_unsupported=True)
    dest = dest_index(dest_root) if os.path.isdir(dest_root) else {}
    wanted = {path_key(f.rel) for f in files}
    orphans = sorted((d for k, d in dest.items() if k not in wanted), key=lambda d: d.rel.lower())
    s = {
        "kind": "local",
        "local": local_root,
        "dest": dest_root,
        "target": dest_root,
        "delete": mode,
        "remote": {d.rel: d.size for d in dest.values()},
        "source": "local folder",
        "todo": plan_local_entries(files, dest),
        "orphans": orphans if mode != "keep" else [],
        "held": mode == "mirror"
        and not allow_mass_delete
        and mass_delete(len(files), len(dest), len(orphans)),
        "skipped": skipped,
        "new_only": new_only,
    }
    (on_scan or print_scan)(s)
    return s


def is_local_scan(s: dict) -> bool:
    return s.get("kind") == "local"


def scan_target(s: dict) -> str:
    """The share name, or the destination folder of a local copy."""
    return s.get("target") or s["share"]


def deletions(s: dict) -> list[DestFile]:
    """The files a sync will delete: only a mirror's, and only when not held back."""
    if not is_local_scan(s) or s.get("delete") != "mirror" or s.get("held"):
        return []
    return s["orphans"]


def pending(s: dict) -> int:
    """Copies plus deletions still to do for one scan."""
    return len(actionable(s)) + len(deletions(s))


def scan_map(
    cfg: dict,
    lazy: LazySmb,
    m: dict,
    include_unsupported: bool,
    refresh: bool,
    on_scan=None,
    on_progress=None,
    new_only: bool = False,
    allow_mass_delete: bool = False,
) -> dict | None:
    """Build the transfer plan for one map. `on_scan(s)` reports the result (defaults to
    printing it for the CLI; the GUI passes its own callback). `on_progress(file_count)` is
    forwarded to the remote listing so a GUI can show progress during the slow SMB1 scan.
    `new_only` records the add-only intent so the display and the transfer both honor it.
    A map with a `dest` is a local copy and goes to `scan_local_map` (no SMB involved)."""
    if is_local_map(m):
        return scan_local_map(
            m, on_scan=on_scan, new_only=new_only, allow_mass_delete=allow_mass_delete
        )
    local_root = os.path.abspath(m["local"])
    share = m["share"]
    if not os.path.isdir(local_root):
        print(f"  ! local folder not found: {local_root}")
        return None
    remote, source = get_remote(cfg, lazy, share, refresh, on_progress=on_progress)
    files, skipped = local_index(local_root, include_unsupported)
    s = {
        "kind": "hap",
        "local": local_root,
        "share": share,
        "target": share,
        "remote": remote,
        "source": source,
        "todo": plan_entries(files, remote),
        "skipped": skipped,
        "new_only": new_only,
    }
    (on_scan or print_scan)(s)
    return s


def _as_entries(todo: Iterable) -> list[PlanEntry]:
    """Plan entries as PlanEntry objects; plain 4-tuples (older callers, tests) are wrapped."""
    return [t if isinstance(t, PlanEntry) else PlanEntry(*t) for t in todo]


def actionable(s: dict) -> list[PlanEntry]:
    """The todo entries that will actually transfer. With `new_only`, 'changed' files (already
    on the HAP, just different bytes) are kept as-is and skipped — only genuinely new files go."""
    todo = _as_entries(s["todo"])
    if s.get("new_only"):
        return [t for t in todo if t.status == "new"]
    return todo


def split_plan(todo: Iterable[PlanEntry]) -> tuple[list[PlanEntry], list[PlanEntry]]:
    """(changed, new), each sorted by path, case-insensitively."""
    entries = _as_entries(todo)
    changed = sorted((t for t in entries if t.status == "changed"), key=lambda t: t.rel.lower())
    new = sorted((t for t in entries if t.status == "new"), key=lambda t: t.rel.lower())
    return changed, new


def describe_changed(entry: PlanEntry, remote: dict[str, int], where: str = "HAP") -> str:
    """`local 5.1 MB vs HAP 5.0 MB, Δ+12.0 KB` — so a re-tag and a re-rip look different."""
    rsize = remote.get(entry.rel)
    if rsize is None:
        return human_size(entry.size)
    delta = entry.size - rsize
    if delta == 0 and where != "HAP":
        return f"{human_size(entry.size)}, date differs"
    sign = "+" if delta >= 0 else "-"
    return (
        f"local {human_size(entry.size)} vs {where} {human_size(rsize)}, "
        f"Δ{sign}{human_size(abs(delta))}"
    )


def _where(s: dict) -> str:
    return "copy" if is_local_scan(s) else "HAP"


def orphan_heading(s: dict) -> str | None:
    """The plan's line above the files that are in a local copy but no longer in its source."""
    orphans = s.get("orphans") or []
    if not orphans:
        return None
    n = len(orphans)
    if s.get("delete") == "list":
        return f"EXTRA ({n}) — in the copy, not in the source; listed only, nothing is deleted:"
    if s.get("held"):
        return (
            f"EXTRA ({n} of {len(s['remote'])} files) — deletion HELD BACK: that is more than "
            "half the copy (or the source is empty), so the source may be wrong. Check it, then "
            "run `hap_sync sync --allow-mass-delete`, or delete by hand:"
        )
    return f"EXTRA ({n}) — in the copy, not in the source; will be DELETED (mirror):"


def print_scan(s: dict) -> None:
    todo, remote = s["todo"], s["remote"]
    tot = sum(t[2] for t in todo)
    where = _where(s)
    print(f"  {s['local']}  ->  {scan_target(s)}   [{s['source']}]")
    print(
        f"    {'copy' if is_local_scan(s) else 'remote'} has {len(remote)} files; "
        f"to transfer: {len(todo)} ({human_size(tot)})"
        f"   [skipped junk={s['skipped']['junk']}, unsupported={s['skipped']['unsupported']}]"
    )
    changed, new = split_plan(todo)
    # CHANGED = path already on the HAP but the byte size differs (usually a re-tag). Show both
    # sizes + the delta so it's obvious whether the audio really changed or it's just metadata.
    if changed:
        tag = (
            f"SKIPPED, kept as-is on the {where} (--new-only)"
            if s.get("new_only")
            else f"already on the {where}, bytes differ"
        )
        print(f"    CHANGED ({len(changed)}) — {tag}:")
        for entry in changed:
            print(f"      ~ {entry.rel}  ({describe_changed(entry, remote, where)})")
    if new:
        print(f"    NEW ({len(new)}):")
        for entry in new:
            print(f"      + {entry.rel}  ({human_size(entry.size)})")
    heading = orphan_heading(s)
    if heading:
        print(f"    {heading}")
        for d in s["orphans"]:
            print(f"      - {d.rel}  ({human_size(d.size)})")


def plan_file_lines(s: dict) -> list[str]:
    """The complete plan for one map, as text: nothing hidden behind a display cap."""
    todo, remote = s["todo"], s["remote"]
    actionable_entries = actionable(s)
    xfer = sum(t.size for t in actionable_entries)
    changed, new = split_plan(todo)
    where = _where(s)
    lines = [
        f"Transfer plan   {s['local']}  ->  {scan_target(s)}",
        f"{'copy' if is_local_scan(s) else 'remote library'}: {len(remote)} files | "
        f"would transfer: {len(actionable_entries)} ({human_size(xfer)})"
        + ("  [new-only: changed files listed below are skipped]" if s.get("new_only") else ""),
        "",
    ]
    if changed:
        lines.append(f"CHANGED ({len(changed)}) — already on the {where}, bytes differ:")
        lines += [f"~ {e.rel}  ({describe_changed(e, remote, where)})" for e in changed]
        lines.append("")
    if new:
        lines.append(f"NEW ({len(new)}):")
        lines += [f"+ {e.rel}  ({human_size(e.size)})" for e in new]
    heading = orphan_heading(s)
    if heading:
        lines += ["", heading]
        lines += [f"- {d.rel}  ({human_size(d.size)})" for d in s["orphans"]]
    return lines


def write_plan_file(s: dict, folder: str | os.PathLike) -> Path:
    """Save `plan_file_lines(s)` as `hap_plan_<target>.txt` in `folder`; returns the path."""
    path = Path(folder) / f"hap_plan_{safe_name(scan_target(s))}.txt"
    path.write_text("\n".join(plan_file_lines(s)) + "\n", encoding="utf-8")
    return path


def selected_maps(cfg: dict, only: str | None) -> list[dict]:
    """The maps to act on: all of them, or just the one feeding `only` (a share or a dest)."""
    return [m for m in cfg["maps"] if not only or map_target(m) == only]


def scan_all(cfg: dict, lazy: LazySmb, args: argparse.Namespace) -> list[dict]:
    new_only = getattr(args, "new_only", False)
    allow_mass_delete = getattr(args, "allow_mass_delete", False)
    # The HAP comes first: keeping the player up to date is the point; copies follow.
    maps = sorted(selected_maps(cfg, getattr(args, "only", None)), key=is_local_map)
    scans = []
    for m in maps:
        s = scan_map(
            cfg,
            lazy,
            m,
            args.all,
            args.refresh,
            new_only=new_only,
            allow_mass_delete=allow_mass_delete,
        )
        if s is not None:
            scans.append(s)
    return scans


def jobs_for(scans: Iterable[dict]) -> list[Job]:
    """The HAP uploads; local copies are done by `sync_local`, one scan at a time."""
    return [
        Job(s["share"], t.rel, t.path, t.size)
        for s in scans
        if not is_local_scan(s)
        for t in actionable(s)
    ]


def plan_totals(scans: Iterable[dict]) -> tuple[int, int]:
    """(files to transfer or copy, files a mirror will delete), across every scan."""
    scans = list(scans)
    return sum(len(actionable(s)) for s in scans), sum(len(deletions(s)) for s in scans)


# ---------- transfer ----------


def transfer(
    smb: Smb, jobs: list[Job], index_by_share: dict, on_event=None, should_cancel=None
) -> tuple[int, int]:
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
    for i, job in enumerate((j if isinstance(j, Job) else Job(*j) for j in jobs), 1):
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
                    on_event(
                        "file_failed", i=i, total=total, share=job.share, rel=job.rel, error=str(e)
                    )
        if ok:
            done += 1
            index_by_share[job.share][job.rel] = job.size  # fold into the cache
            on_event("file_done", i=i, total=total, share=job.share, rel=job.rel, size=job.size)
    return done, failed


def unreachable_shares(smb: Smb, shares: Iterable[str]) -> list[str]:
    """The shares the HAP does not serve right now.

    The plan comes from the cache, so it can list fifty files for `HAP_External` while
    the USB disk is not mounted (the HAP waits for a confirmation on its front screen).
    Without this check every one of those uploads fails on its own, fifty times over.
    """
    bad = []
    for share in shares:
        try:
            smb.conn.listPath(share, "/")
        except Exception:
            smb.reconnect()
            try:
                smb.conn.listPath(share, "/")
            except Exception:
                bad.append(share)
    return bad


def _copy_file(src: str, dst: str) -> None:
    """Copy with its dates, under a temporary name first (see PART_SUFFIX)."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + PART_SUFFIX
    shutil.copy2(src, part)
    os.replace(part, dst)


def _prune_empty_dirs(root: str, start: str) -> None:
    """Remove `start` and its parents while they are empty, stopping at `root`."""
    root = os.path.normcase(os.path.abspath(root))
    d = os.path.abspath(start)
    while os.path.normcase(d) != root and _inside(d, root):
        try:
            os.rmdir(d)  # fails, harmlessly, as soon as the folder still holds something
        except OSError:
            return
        d = os.path.dirname(d)


def sync_local(s: dict, on_event=None, should_cancel=None) -> tuple[int, int, int]:
    """Carry out one local-copy scan: copy what is new or changed, then, for a mirror,
    delete what is no longer in the source. Copies come first, so an interrupted run
    never leaves the copy with less than it had.

    `on_event(kind, **data)` reports 'file_done' / 'file_failed' / 'file_deleted' /
    'delete_failed' / 'cancelled', with `share` set to the destination folder so the
    same display code serves both kinds of target. Returns (copied, failed, deleted).
    """
    on_event = on_event or (lambda *a, **k: None)
    dest = s["dest"]
    copies, removals = actionable(s), deletions(s)
    total = len(copies) + len(removals)
    done = failed = deleted = 0
    i = 0
    for entry in copies:
        i += 1
        if should_cancel and should_cancel():
            on_event("cancelled", i=i, total=total)
            return done, failed, deleted
        try:
            _copy_file(entry.path, os.path.join(dest, *entry.rel.split("/")))
        except OSError as e:
            failed += 1
            on_event("file_failed", i=i, total=total, share=dest, rel=entry.rel, error=str(e))
            continue
        done += 1
        on_event("file_done", i=i, total=total, share=dest, rel=entry.rel, size=entry.size)
    for d in removals:
        i += 1
        if should_cancel and should_cancel():
            on_event("cancelled", i=i, total=total)
            break
        try:
            os.remove(d.path)
        except OSError as e:
            failed += 1
            on_event("delete_failed", i=i, total=total, share=dest, rel=d.rel, error=str(e))
            continue
        deleted += 1
        _prune_empty_dirs(dest, os.path.dirname(d.path))
        on_event("file_deleted", i=i, total=total, share=dest, rel=d.rel, size=d.size)
    return done, failed, deleted


# ---------- commands ----------


def cmd_plan(cfg: dict, args: argparse.Namespace) -> int:
    lazy = LazySmb(cfg["host"])
    new_only = getattr(args, "new_only", False)
    try:
        total, removals = plan_totals(scan_all(cfg, lazy, args))
        print(
            f"\nPlan: {total} file(s) would transfer"
            + (f", {removals} would be deleted from local copies (mirror)" if removals else "")
            + ". Run `sync` to do it."
            + ("  (--new-only: 'changed' files are kept as-is on the HAP)" if new_only else "")
            + "\n(remote index came from the on-disk cache where shown; "
            "use --refresh to re-scan)"
        )
    finally:
        lazy.close()
    return 0


def _print_event(kind: str, **d) -> None:
    where = f"{d.get('share')}:/{d.get('rel')}"
    if kind == "file_done":
        print(f"  [{d['i']}/{d['total']}] {where}  ({human_size(d['size'])})")
    elif kind == "file_failed":
        print(f"  [{d['i']}/{d['total']}] FAILED {where} — {d['error']}")
    elif kind == "file_deleted":
        print(f"  [{d['i']}/{d['total']}] deleted {where}")
    elif kind == "delete_failed":
        print(f"  [{d['i']}/{d['total']}] FAILED to delete {where} — {d['error']}")


def cmd_sync(cfg: dict, args: argparse.Namespace) -> int:
    lazy = LazySmb(cfg["host"])
    try:
        scans = scan_all(cfg, lazy, args)
        jobs = jobs_for(scans)
        local_work = [s for s in scans if is_local_scan(s) and pending(s)]
        if not jobs and not local_work:
            print("\nNothing to transfer — already in sync.")
            return 0
        if args.dry_run:
            total, removals = plan_totals(scans)
            print(
                f"\n[dry-run] {total} file(s) would transfer"
                + (f", {removals} would be deleted" if removals else "")
                + ". Drop --dry-run to do it."
            )
            return 0
        done = failed = deleted = 0
        if jobs:
            smb = lazy.smb
            smb.reconnect()  # a long listing can desync SMB1 — upload on a fresh connection
            for share in unreachable_shares(smb, sorted({j.share for j in jobs})):
                skipped = [j for j in jobs if j.share == share]
                jobs = [j for j in jobs if j.share != share]
                failed += len(skipped)
                print(
                    f"\n! {share} is not served by the HAP right now: its {len(skipped)} file(s) "
                    "are skipped. A USB disk the HAP has not mounted yet does this: look for a "
                    "mount prompt on the HAP's front screen, confirm it, then run sync again."
                )
            if jobs:
                print(f"\nTransferring {len(jobs)} file(s)…")
                index_by_share = {s["share"]: s["remote"] for s in scans if not is_local_scan(s)}
                d, f = transfer(smb, jobs, index_by_share, on_event=_print_event)
                done, failed = done + d, failed + f
                for share, idx in index_by_share.items():
                    save_cache(cfg, share, idx)  # the next run won't re-scan what we just sent
        for s in local_work:
            print(f"\nCopying to {s['dest']}…")
            d, f, rm = sync_local(s, on_event=_print_event)
            done, failed, deleted = done + d, failed + f, deleted + rm
        print(
            f"\nDone: {done} transferred, {failed} failed"
            + (f", {deleted} deleted from local copies" if deleted else "")
            + ".  (cache updated)"
        )
        if jobs:
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
        shares = {
            m["share"] for m in selected_maps(cfg, getattr(args, "only", None)) if m.get("share")
        }
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
        print(
            f"{s['fixable']} fixable native-Windows issue(s)"
            + (" — admin required." if s["needs_admin"] else ".")
        )
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
        prog="hap_sync", description="HAP-aware music sync (replaces FreeFileSync for the HAP)."
    )
    hap_update.add_version_flag(ap)
    ap.add_argument("--config", help="path to hap_sync.json")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("plan", "sync"):
        p = sub.add_parser(name)
        p.add_argument(
            "--only", help="limit to one share (e.g. HAP_External) or one local destination"
        )
        p.add_argument("--all", action="store_true", help="include unsupported formats too")
        p.add_argument(
            "--refresh",
            action="store_true",
            help="re-scan the HAP instead of using the cached index",
        )
        p.add_argument(
            "--new-only",
            action="store_true",
            help="add only files missing from the HAP; never overwrite a file that "
            "is already there (skip 'changed')",
        )
        p.add_argument(
            "--allow-mass-delete",
            action="store_true",
            help="let a mirror delete even when that removes more than half of the copy",
        )
        if name == "sync":
            p.add_argument("--dry-run", action="store_true")
    pl = sub.add_parser("list")
    pl.add_argument("share")
    pl.add_argument("--refresh", action="store_true", help="re-scan instead of using the cache")
    pr = sub.add_parser("refresh", help="rebuild the on-disk remote-index cache")
    pr.add_argument("--only", help="limit to one share")
    sub.add_parser("wake")
    pc = sub.add_parser("check", help="diagnose SMB access (and optionally fix Windows issues)")
    pc.add_argument(
        "--fix",
        action="store_true",
        help="apply fixes for any native-Windows SMB problems (asks for admin)",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    ap = build_parser()
    args = ap.parse_args(argv)
    hap_update.notice_at_exit()
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
