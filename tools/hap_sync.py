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
    python tools/hap_sync.py list HAP_Internal
    python tools/hap_sync.py wake
    python tools/hap_sync.py check

Never deletes anything on the HAP (add/update only). Requires: pip install pysmb
"""
from __future__ import annotations

import json
import os
import socket
import sys

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
    return cfg


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


def remote_index(smb: "Smb", share: str):
    """(map of remote 'relative/path' -> size, number of dirs we couldn't read)."""
    out: dict[str, int] = {}
    skipped = 0
    stack = ["/"]
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

def plan_map(smb: "Smb", m: dict, include_unsupported: bool):
    local_root = os.path.abspath(m["local"])
    share = m["share"]
    if not os.path.isdir(local_root):
        print(f"  ! local folder not found: {local_root}")
        return []
    remote, skipped_dirs = remote_index(smb, share)
    todo, skipped = [], {"junk": 0, "unsupported": 0}
    for rel, ap, size, _kind in local_index(local_root, include_unsupported):
        if rel == "__skipped__":
            skipped = ap
            continue
        rsize = remote.get(rel)
        if rsize is None or rsize != size:
            todo.append((rel, ap, size, "new" if rsize is None else "changed"))
    tot = sum(s for _, _, s, _ in todo)
    warn = f", unreadable dirs={skipped_dirs}" if skipped_dirs else ""
    print(f"  {local_root}  ->  {share}")
    print(f"    remote has {len(remote)} files; to transfer: {len(todo)} ({human(tot)})"
          f"   [skipped junk={skipped['junk']}, unsupported={skipped['unsupported']}{warn}]")
    for rel, _ap, size, why in todo[:12]:
        print(f"      + {rel}  ({human(size)}, {why})")
    if len(todo) > 12:
        print(f"      … and {len(todo) - 12} more")
    return [(share, rel, ap, size) for rel, ap, size, _ in todo]


def cmd_plan(cfg, args):
    smb = Smb(cfg["host"])
    try:
        total = 0
        for m in cfg["maps"]:
            if args.only and m["share"] != args.only:
                continue
            total += len(plan_map(smb, m, args.all))
        print(f"\nPlan: {total} file(s) would transfer. Run `sync` to do it.")
    finally:
        smb.close()
    return 0


def cmd_sync(cfg, args):
    smb = Smb(cfg["host"])
    try:
        jobs = []
        for m in cfg["maps"]:
            if args.only and m["share"] != args.only:
                continue
            jobs += plan_map(smb, m, args.all)
        if not jobs:
            print("\nNothing to transfer — already in sync.")
            return 0
        if args.dry_run:
            print(f"\n[dry-run] {len(jobs)} file(s) would transfer. Drop --dry-run to do it.")
            return 0
        # the long listing above can desync the SMB1 session — upload on a fresh connection
        smb.reconnect()
        print(f"\nTransferring {len(jobs)} file(s)…")
        made: set = set()
        done = failed = 0
        for i, (share, rel, ap, size) in enumerate(jobs, 1):
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
                        print(f"  [{i}/{len(jobs)}] FAILED {share}:/{rel} — {e}")
            if ok:
                done += 1
                print(f"  [{i}/{len(jobs)}] {share}:/{rel}  ({human(size)})")
        print(f"\nDone: {done} transferred, {failed} failed.")
        print("The HAP auto-reindexes files dropped on the share within seconds.")
        return 1 if failed else 0
    finally:
        smb.close()


def cmd_list(cfg, args):
    smb = Smb(cfg["host"])
    try:
        idx, skipped = remote_index(smb, args.share)
        for p in sorted(idx)[:200]:
            print(f"  {human(idx[p]):>9}  {p}")
        extra = f"  ({skipped} dirs unreadable)" if skipped else ""
        print(f"\n{len(idx)} files on {args.share}.{extra}")
    finally:
        smb.close()
    return 0


def cmd_wake(cfg, _args):
    mac = cfg.get("mac", "")
    hexmac = mac.replace(":", "").replace("-", "").strip()
    if len(hexmac) != 12:
        print("error: set a valid 'mac' in the config to use wake", file=sys.stderr)
        return 2
    pkt = b"\xff" * 6 + bytes.fromhex(hexmac) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(pkt, ("255.255.255.255", 9))
    s.close()
    print(f"Magic packet sent to {mac}")
    return 0


def cmd_check(cfg, _args):
    host = cfg["host"]
    ok = True
    for port, name in ((445, "SMB"), (60200, "ScalarWebAPI")):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        r = s.connect_ex((host, port))
        s.close()
        ok = ok and r == 0
        print(f"  {host}:{port:<6} {name:<14} {'open' if r == 0 else 'CLOSED'}")
    print("[OK] HAP reachable" if ok else "[FAIL] HAP not fully reachable")
    return 0 if ok else 1


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
        if name == "sync":
            p.add_argument("--dry-run", action="store_true")
    pl = sub.add_parser("list"); pl.add_argument("share")
    sub.add_parser("wake"); sub.add_parser("check")
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
        "wake": lambda: cmd_wake(cfg, args),
        "check": lambda: cmd_check(cfg, args),
    }[args.cmd]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
