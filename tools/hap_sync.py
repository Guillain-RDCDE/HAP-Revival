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

import json
import os
import socket
import sys
import time

# what the HAP plays, and what must never be copied (see docs/04-smb.md, tools/hap_companion.py)
SUPPORTED_EXT = {
    ".flac", ".wav", ".aif", ".aiff", ".alac", ".dsf", ".dff",
    ".m4a", ".mp3", ".aac", ".wma", ".oma", ".aa3", ".at3",
}
SIDECAR_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".pdf", ".txt",
               ".nfo", ".log", ".cue", ".m3u", ".m3u8", ".sfv", ".md5", ".lrc", ""}
JUNK_SUFFIXES = (".ffs_tmp", ".ffs_lock", ".part", ".partial", ".tmp", ".crdownload")
JUNK_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}


def is_junk(name: str) -> bool:
    low = name.lower()
    return low in JUNK_NAMES or low.startswith("._") or low.endswith(JUNK_SUFFIXES)


def classify(name: str) -> str:
    """'audio' | 'sidecar' | 'junk' | 'unsupported'"""
    if is_junk(name):
        return "junk"
    ext = os.path.splitext(name.lower())[1]
    if ext in SUPPORTED_EXT:
        return "audio"
    if ext in SIDECAR_EXT:
        return "sidecar"
    return "unsupported"


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


# ---------- config ----------

def load_config(path: str | None) -> dict:
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hap_sync.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"config not found: {path}\n"
            "Create a hap_sync.json (see the header of this file for the format)."
        )
    with open(path, encoding="utf-8-sig") as f:  # tolerate a Windows BOM
        cfg = json.load(f)
    if not cfg.get("host") or not cfg.get("maps"):
        raise ValueError("config must contain 'host' and a non-empty 'maps' list")
    cfg["_path"] = os.path.abspath(path)
    return cfg


# ---------- remote-index cache ----------
# Listing a 60-70k-file SMB1 share takes minutes, so we cache the remote index
# (relative-path -> size) per (host, share) and reuse it. After a sync we fold the
# files we just uploaded straight into the cache, so steady-state runs never re-scan.
# Use `--refresh` (or the `refresh` command) to force a full re-listing.

def cache_dir(cfg: dict) -> str:
    d = os.path.join(os.path.dirname(cfg.get("_path", os.getcwd())), ".hap_sync_cache")
    os.makedirs(d, exist_ok=True)
    return d


def cache_file(cfg: dict, share: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in f"{cfg['host']}__{share}")
    return os.path.join(cache_dir(cfg), safe + ".json")


def load_cache(cfg: dict, share: str):
    path = cache_file(cfg, share)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 — corrupt cache: ignore, will rescan
        return None


def save_cache(cfg: dict, share: str, files: dict):
    data = {"host": cfg["host"], "share": share,
            "built": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}
    tmp = cache_file(cfg, share) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, cache_file(cfg, share))


# ---------- SMB ----------

class Smb:
    """Anonymous SMB1 connection to the HAP, with reconnect-on-error.

    A long recursive listing can desync pysmb's SMB1 session (a failed `listPath`
    can leave the socket mid-message), which then breaks the next `storeFile`. We
    reconnect on any error and use a *fresh* connection for the upload phase.
    """

    def __init__(self, host: str):
        try:
            from smb.SMBConnection import SMBConnection  # noqa: F401
        except ImportError:
            print("error: pysmb is required.  Install it with:  pip install pysmb", file=sys.stderr)
            raise SystemExit(2)
        self.host = host
        self.conn = None
        self.open()

    def open(self):
        from smb.SMBConnection import SMBConnection
        last = None
        for direct, port in ((True, 445), (False, 139)):  # try direct-TCP then NetBIOS
            try:
                c = SMBConnection("", "", "hap-sync", "HAP", use_ntlm_v2=False, is_direct_tcp=direct)
                if c.connect(self.host, port, timeout=10):
                    self.conn = c
                    return
            except Exception as e:  # noqa: BLE001
                last = e
        raise SystemExit(f"error: SMB connection to {self.host} failed ({last})")

    def reconnect(self):
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
        self.open()

    def close(self):
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass


def remote_index(smb: "Smb", share: str, on_progress=None):
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
        except Exception:  # noqa: BLE001 — reconnect (the session may be desynced) and retry once
            smb.reconnect()
            try:
                entries = smb.conn.listPath(share, d)
            except Exception:  # noqa: BLE001
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
        if on_progress and len(out) - last_reported >= 1000:
            last_reported = len(out)
            on_progress(len(out))
    if on_progress:
        on_progress(len(out))
    return out, skipped


def local_index(root: str, include_unsupported: bool):
    """Yield (relpath_posix, abspath, size, kind) for files worth transferring."""
    skipped = {"junk": 0, "unsupported": 0}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
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
            yield rel, ap, size, kind
    yield ("__skipped__", skipped, 0, "")  # sentinel, last


def ensure_dirs(smb: "Smb", share: str, rel: str, made: set):
    parts = rel.split("/")[:-1]
    cur = ""
    for p in parts:
        cur = f"{cur}/{p}" if cur else f"/{p}"
        if cur in made:
            continue
        try:
            smb.conn.createDirectory(share, cur)
        except Exception:  # noqa: BLE001 — already exists
            pass
        made.add(cur)


# ---------- commands ----------

class LazySmb:
    """Open the SMB connection only when a live scan/upload actually needs it."""

    def __init__(self, host: str):
        self.host = host
        self._smb = None

    @property
    def smb(self) -> "Smb":
        if self._smb is None:
            self._smb = Smb(self.host)
        return self._smb

    def close(self):
        if self._smb is not None:
            self._smb.close()


def get_remote(cfg: dict, lazy: LazySmb, share: str, refresh: bool, on_progress=None):
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


def scan_map(cfg: dict, lazy: LazySmb, m: dict, include_unsupported: bool, refresh: bool,
             on_scan=None, on_progress=None):
    """Build the transfer plan for one map. `on_scan(s)` reports the result (defaults to
    printing it for the CLI; the GUI passes its own callback). `on_progress(file_count)` is
    forwarded to the remote listing so a GUI can show progress during the slow SMB1 scan."""
    local_root = os.path.abspath(m["local"])
    share = m["share"]
    if not os.path.isdir(local_root):
        print(f"  ! local folder not found: {local_root}")
        return None
    remote, source = get_remote(cfg, lazy, share, refresh, on_progress=on_progress)
    todo, skipped = [], {"junk": 0, "unsupported": 0}
    for rel, ap, size, _kind in local_index(local_root, include_unsupported):
        if rel == "__skipped__":
            skipped = ap
            continue
        rsize = remote.get(rel)
        if rsize is None or rsize != size:
            todo.append((rel, ap, size, "new" if rsize is None else "changed"))
    s = {"local": local_root, "share": share, "remote": remote,
         "source": source, "todo": todo, "skipped": skipped}
    (on_scan or print_scan)(s)
    return s


def print_scan(s: dict):
    tot = sum(x[2] for x in s["todo"])
    print(f"  {s['local']}  ->  {s['share']}   [{s['source']}]")
    print(f"    remote has {len(s['remote'])} files; to transfer: {len(s['todo'])} ({human(tot)})"
          f"   [skipped junk={s['skipped']['junk']}, unsupported={s['skipped']['unsupported']}]")
    for rel, _ap, size, why in s["todo"][:12]:
        print(f"      + {rel}  ({human(size)}, {why})")
    if len(s["todo"]) > 12:
        print(f"      … and {len(s['todo']) - 12} more")


def _selected_maps(cfg, args):
    for m in cfg["maps"]:
        if not (getattr(args, "only", None) and m["share"] != args.only):
            yield m


def cmd_plan(cfg, args):
    lazy = LazySmb(cfg["host"])
    try:
        total = sum(len(s["todo"]) for m in _selected_maps(cfg, args)
                    if (s := scan_map(cfg, lazy, m, args.all, args.refresh)) is not None)
        print(f"\nPlan: {total} file(s) would transfer. Run `sync` to do it."
              f"\n(remote index came from the on-disk cache where shown; use --refresh to re-scan)")
    finally:
        lazy.close()
    return 0


def transfer(smb: "Smb", jobs: list, index_by_share: dict, on_event=None, should_cancel=None):
    """Upload `jobs` (list of (share, rel, abspath, size)) over a fresh SMB1 session.

    Each successful upload is folded into `index_by_share[share]` (the cache map) so the
    caller can persist it and skip these files next run. `on_event(kind, **data)` fires for
    progress — kinds: 'file_done' / 'file_failed' / 'cancelled' (the CLI prints them, the GUI
    drives a progress bar). `should_cancel()` is polled between files for cooperative abort.
    Returns (done, failed). Same retry-on-fresh-connection logic the CLI always used.
    """
    on_event = on_event or (lambda *a, **k: None)
    total = len(jobs)
    made: set = set()
    done = failed = 0
    for i, (share, rel, ap, size) in enumerate(jobs, 1):
        if should_cancel and should_cancel():
            on_event("cancelled", i=i, total=total)
            break
        ensure_dirs(smb, share, rel, made)
        ok = False
        for attempt in (1, 2):  # retry once on a fresh connection
            try:
                with open(ap, "rb") as fp:
                    smb.conn.storeFile(share, "/" + rel, fp)
                ok = True
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 1:
                    smb.reconnect()
                    made.clear()
                    ensure_dirs(smb, share, rel, made)
                else:
                    failed += 1
                    on_event("file_failed", i=i, total=total, share=share, rel=rel, error=str(e))
        if ok:
            done += 1
            index_by_share[share][rel] = size  # fold into the cache
            on_event("file_done", i=i, total=total, share=share, rel=rel, size=size)
    return done, failed


def cmd_sync(cfg, args):
    lazy = LazySmb(cfg["host"])
    try:
        scans = [s for m in _selected_maps(cfg, args)
                 if (s := scan_map(cfg, lazy, m, args.all, args.refresh)) is not None]
        jobs = [(s["share"], rel, ap, size) for s in scans for rel, ap, size, _ in s["todo"]]
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

        def on_event(kind, **d):
            if kind == "file_done":
                print(f"  [{d['i']}/{d['total']}] {d['share']}:/{d['rel']}  ({human(d['size'])})")
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


def cmd_list(cfg, args):
    lazy = LazySmb(cfg["host"])
    try:
        idx, source = get_remote(cfg, lazy, args.share, args.refresh)
        for p in sorted(idx)[:200]:
            print(f"  {human(idx[p]):>9}  {p}")
        print(f"\n{len(idx)} files on {args.share}.  [{source}]")
    finally:
        lazy.close()
    return 0


def cmd_refresh(cfg, args):
    lazy = LazySmb(cfg["host"])
    try:
        shares = {args.only} if getattr(args, "only", None) else {m["share"] for m in cfg["maps"]}
        for share in sorted(shares):
            _idx, source = get_remote(cfg, lazy, share, refresh=True)
            print(f"  {share}: {source}  -> cached")
    finally:
        lazy.close()
    return 0


def send_wol(mac: str) -> None:
    """Broadcast a Wake-on-LAN magic packet to `mac`. Raises ValueError on a bad MAC.
    The HAP sleeps in network standby; this is how the CLI and the GUI both wake it."""
    hexmac = mac.replace(":", "").replace("-", "").strip()
    if len(hexmac) != 12:
        raise ValueError("MAC must be 12 hex digits (e.g. 80:56:F2:85:0E:27)")
    pkt = b"\xff" * 6 + bytes.fromhex(hexmac) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.sendto(pkt, ("255.255.255.255", 9))
    finally:
        s.close()


def port_open(host: str, port: int, timeout: float = 3) -> bool:
    """True if a TCP connect to host:port succeeds within `timeout` seconds."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def cmd_wake(cfg, _args):
    try:
        send_wol(cfg.get("mac", ""))
    except ValueError:
        print("error: set a valid 'mac' in the config to use wake", file=sys.stderr)
        return 2
    print(f"Magic packet sent to {cfg.get('mac')}")
    return 0


def cmd_check(cfg, args):
    """Full SMB access diagnosis via smb_doctor: the authoritative pysmb transfer probe plus,
    on Windows, the native-path SMB-hardening checks. `--fix` applies any remediations."""
    host = cfg["host"]
    import smb_doctor

    findings = smb_doctor.diagnose(host)
    print("\n".join(smb_doctor.format_report(findings)))

    # Bonus line: the ScalarWebAPI port the control app uses (not part of the SMB picture).
    print(f"{'✓' if port_open(host, 60200) else '·'} ScalarWebAPI (control app) port 60200")

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


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    import argparse
    ap = argparse.ArgumentParser(prog="hap_sync", description="HAP-aware music sync (replaces FreeFileSync for the HAP).")
    ap.add_argument("--config", help="path to hap_sync.json")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("plan", "sync"):
        p = sub.add_parser(name)
        p.add_argument("--only", help="limit to one share, e.g. HAP_External")
        p.add_argument("--all", action="store_true", help="include unsupported formats too")
        p.add_argument("--refresh", action="store_true",
                       help="re-scan the HAP instead of using the cached index")
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
    args = ap.parse_args(argv[1:])
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return {
        "plan": lambda: cmd_plan(cfg, args),
        "sync": lambda: cmd_sync(cfg, args),
        "list": lambda: cmd_list(cfg, args),
        "refresh": lambda: cmd_refresh(cfg, args),
        "wake": lambda: cmd_wake(cfg, args),
        "check": lambda: cmd_check(cfg, args),
    }[args.cmd]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
