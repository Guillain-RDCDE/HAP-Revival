#!/usr/bin/env python3
"""
Turn the library audit into something you can act on: every finding, with the
real folder it lives in, ready to open in Explorer or a tag editor.

The audit tells you 274 albums have no cover art. It cannot tell you *where*
they are, and that is the whole difficulty: the REST catalog returns an empty
`filepath` on every track, album folders are not named after the album tag
(`Dummy (1994)` on disk, `Dummy` in the tag), and many albums have no album
artist at all. Matching on names resolves almost nothing — measured 0 out of 12.

**Matching on `filename` resolves 97%.** Every track carries the exact file name,
so indexing both SMB shares once and voting per album finds the folder: 267 of
274 albums, 7 ambiguous, none missed. The seven ambiguous ones are albums that
genuinely exist twice on disk, which is worth knowing in its own right.

A tie is reported as ambiguous and never resolved by picking one. Saying "your
album is here" when it is in three places is worse than saying nothing.

**About cover art specifically.** Several albums the player reports as coverless
already have a `cover.jpg` or `folder.jpg` sitting in the folder. The HAP reads
artwork **embedded in the file tags**, not loose images — so the fix is to write
that image into the tags, which is exactly what a tag editor does. This tool
reports the loose image when it finds one, because it means the artwork is
already to hand.

Requires: `pip install pysmb` for indexing. Everything else is stdlib.

Usage:
    python tools/hap_fixit.py <ip> index              # crawl both shares, ~4 min
    python tools/hap_fixit.py <ip> report             # what needs fixing, where
    python tools/hap_fixit.py <ip> report --html f.html
    python tools/hap_fixit.py <ip> open 3             # open finding 3's folder
    python tools/hap_fixit.py <ip> edit 3             # ... in your tag editor

Needs a library harvest first:
    python tools/hap_library.py <ip> harvest
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hap_library  # noqa: E402
import library_audit  # noqa: E402

SHARES = ("HAP_Internal", "HAP_External")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".gif")
AUDIO_SUFFIXES = (".flac", ".mp3", ".wav", ".m4a", ".aiff", ".aif", ".wma", ".dsf", ".dff")

# How much of an album has to be in one folder before that folder is "the" one.
MATCH_THRESHOLD = 0.5


# ---------------------------------------------------------------- share index


def index_path(host: str) -> Path:
    return hap_library.CACHE_DIR / f"shares-{host.replace(':', '_')}.json"


def crawl_shares(host: str, progress=None) -> dict:
    """Walk both music shares and record every file. About two minutes each.

    Uses pysmb rather than a native Windows path: the player only speaks SMB1,
    which modern Windows disables, and a stale mapped drive to the same host is
    enough to make the native path prompt for a password (see smb_doctor.py).
    """
    try:
        from smb.SMBConnection import SMBConnection
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise RuntimeError("pysmb is required to index the shares: pip install pysmb") from e

    out: dict = {"host": host, "shares": {}, "indexed_at": time.time()}
    for share in SHARES:
        # A fresh connection per share, deliberately. Reusing one across both
        # silently lost 90% of the second share: a long recursive listing
        # desyncs pysmb's SMB1 session, after which every listPath fails and the
        # per-folder error handling below swallows it. Measured — 5 931 files
        # instead of 66 716. hap_sync.py documents the same trap.
        conn = SMBConnection("", "", "hap-fixit", "HAP", use_ntlm_v2=False, is_direct_tcp=True)
        conn.connect(host, 445, timeout=30)
        files: list[list] = []
        failures = 0
        try:
            try:
                roots = [e.filename for e in _ls(conn, share, "/") if e.isDirectory]
            except Exception:  # noqa: BLE001 - an absent external drive is normal
                out["shares"][share] = []
                continue
            for i, artist in enumerate(roots, 1):
                failures += _walk(conn, share, "/" + artist, files, depth=2)
                if progress:
                    progress(share, i, len(roots), len(files))
        finally:
            conn.close()
        if failures:
            # Never report a partial index as a complete one.
            out.setdefault("warnings", []).append(
                f"{share}: {failures} folder(s) could not be listed")
        out["shares"][share] = files
    return out


def _ls(conn, share: str, path: str):
    return [e for e in conn.listPath(share, path) if e.filename not in (".", "..")]


def _walk(conn, share: str, path: str, files: list, depth: int) -> int:
    """Collect files under `path`, descending at most `depth` levels.

    Two levels is what real libraries need: <Artist>/<Album>/ plus the occasional
    <Artist>/<Album>/CD02 or /Face A. Deeper than that has not been observed, and
    an unbounded walk over SMB1 is slow enough to matter.

    Returns the number of folders that could not be listed — one bad folder must
    not stop the crawl, but a silent partial index is worse than a slow one.
    """
    try:
        entries = _ls(conn, share, path)
    except Exception:  # noqa: BLE001 - one unreadable folder must not stop the crawl
        return 1
    failures = 0
    for e in entries:
        if e.isDirectory:
            if depth > 0:
                failures += _walk(conn, share, f"{path}/{e.filename}", files, depth - 1)
        else:
            files.append([path, e.filename, e.file_size])
    return failures


def save_index(index: dict, path: Path | None = None) -> Path:
    target = path or index_path(index["host"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(json.dumps(index, ensure_ascii=False).encode("utf-8"))
    return target


def load_index(host: str, path: Path | None = None) -> dict | None:
    target = path or index_path(host)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


# ------------------------------------------------------------------- the join


class Locator:
    """Finds the folder an album lives in, by voting on its file names."""

    def __init__(self, index: dict):
        self.host = index.get("host", "")
        self.where: dict[str, set[str]] = collections.defaultdict(set)
        self.contents: dict[str, list[str]] = collections.defaultdict(list)
        for share, files in (index.get("shares") or {}).items():
            for folder, name, _size in files:
                key = f"{share}{folder}"
                self.where[name].add(key)
                self.contents[key].append(name)

    def locate(self, filenames: list[str]) -> tuple[list[str], int]:
        """Return (candidate folders, how many of the files each holds).

        More than one candidate means the album is on the disk more than once.
        """
        votes: collections.Counter = collections.Counter()
        for name in filenames:
            for folder in self.where.get(name, ()):
                votes[folder] += 1
        if not votes:
            return [], 0
        best = votes.most_common(1)[0][1]
        if best < max(1, len(filenames) * MATCH_THRESHOLD):
            return [], best
        return sorted(f for f, n in votes.items() if n == best), best

    def loose_images(self, folder: str) -> list[str]:
        return [f for f in self.contents.get(folder, ()) if f.lower().endswith(IMAGE_SUFFIXES)]

    def audio_count(self, folder: str) -> int:
        return sum(1 for f in self.contents.get(folder, ()) if f.lower().endswith(AUDIO_SUFFIXES))


def unc(host: str, folder: str) -> str:
    r"""`HAP_Internal/Portishead/Dummy (1994)` -> `\\host\HAP_Internal\...`."""
    return "\\\\" + host + "\\" + folder.replace("/", "\\")


# --------------------------------------------------------------- the findings


class Finding:
    """One thing to fix, and where it is."""

    def __init__(self, kind: str, title: str, detail: str, folders: list[str], host: str):
        self.kind = kind
        self.title = title
        self.detail = detail
        self.folders = folders
        self.host = host

    @property
    def paths(self) -> list[str]:
        return [unc(self.host, f) for f in self.folders]

    @property
    def path(self) -> str:
        return self.paths[0] if self.paths else ""

    @property
    def ambiguous(self) -> bool:
        return len(self.folders) > 1


def build_findings(harvest: dict, index: dict, top: int = 0) -> list[Finding]:
    """Join the audit's findings to real folders. Ordered worst-first."""
    loc = Locator(index)
    host = harvest.get("host") or index.get("host", "")
    audit = library_audit.RestAudit(harvest)

    by_album: dict = collections.defaultdict(list)
    for t in harvest.get("tracks") or []:
        by_album[(t.get("album") or {}).get("albumid")].append(t)

    findings: list[Finding] = []

    for alb in audit.albums_missing_cover():
        names = [t.get("filename") or "" for t in by_album.get(alb["id"], [])]
        folders, _ = loc.locate([n for n in names if n])
        if not folders:
            findings.append(
                Finding("cover", alb["name"] or "?",
                        f"{alb['trks']} tracks · folder not found on either share",
                        [], host))
            continue
        images = loc.loose_images(folders[0])
        detail = f"{alb['trks']} tracks"
        if images:
            # The artwork is already there — it just is not in the tags, which
            # is the only place the player looks.
            detail += f" · {images[0]} is in the folder but not embedded in the tags"
        else:
            detail += " · no artwork in the folder either"
        if len(folders) > 1:
            detail += f" · {len(folders)} copies on disk"
        findings.append(Finding("cover", alb["name"] or "?", detail, folders, host))

    for dup in audit.duplicates():
        names = [
            t.get("filename") or ""
            for t in harvest.get("tracks") or []
            if t.get("name") == dup["title"]
        ]
        folders, _ = loc.locate([n for n in names if n][:4])
        findings.append(
            Finding("duplicate", f"{dup['title']} ×{dup['n']}",
                    f"{dup['artist'] or '?'} — {dup['album'] or '?'}", folders, host))

    report = library_audit.build_report(audit, 9999)
    for bad in report.get("corrupt") or []:
        findings.append(
            Finding("corrupt", bad["title"] or "?",
                    f"{bad['artist'] or '?'} · unreadable metadata, will likely not play",
                    [], host))

    order = {"cover": 0, "corrupt": 1, "duplicate": 2}
    findings.sort(key=lambda f: (order.get(f.kind, 9), f.title.lower()))
    return findings[:top] if top else findings


# ----------------------------------------------------------------- actions


def find_editor() -> str:
    """Locate a tag editor. Mp3tag first — it is the Windows standard for FLAC."""
    from_env = os.environ.get("HAP_TAG_EDITOR", "")
    if from_env and Path(from_env).is_file():
        return from_env
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Mp3tag" / "Mp3tag.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Mp3tag" / "Mp3tag.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Mp3tag" / "Mp3tag.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "MusicBrainz Picard" / "picard.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return ""


def open_folder(path: str) -> None:
    """Show a folder in the system file manager."""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a folder path, not a command line
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def open_in_editor(path: str, editor: str = "") -> str:
    """Open a folder in the tag editor. Returns the editor used, or ''."""
    exe = editor or find_editor()
    if not exe:
        return ""
    # Mp3tag takes a folder as `/fp:<path>`; anything else gets it positionally.
    args = [exe, f"/fp:{path}"] if "mp3tag" in Path(exe).name.lower() else [exe, path]
    subprocess.Popen(args)  # noqa: S603 - both parts are ours or the user's config
    return exe


# ------------------------------------------------------------------ rendering


def print_report(findings: list[Finding], top: int) -> None:
    kinds = collections.Counter(f.kind for f in findings)
    print("=" * 72)
    print("  WHAT TO FIX, AND WHERE")
    print("=" * 72)
    print(f"  {kinds['cover']} albums without embedded artwork · "
          f"{kinds['duplicate']} duplicated titles · {kinds['corrupt']} unreadable")
    unresolved = sum(1 for f in findings if not f.folders)
    print(f"  located: {len(findings) - unresolved}/{len(findings)}")
    print()
    for i, f in enumerate(findings[:top], 1):
        flag = "  ?" if f.ambiguous else ("  ✗" if not f.folders else "   ")
        print(f"{i:>4}.{flag} [{f.kind}] {f.title}")
        print(f"        {f.detail}")
        for p in f.paths:
            print(f"        {p}")
    if len(findings) > top:
        print(f"\n  … and {len(findings) - top} more (use --top)")
    print("=" * 72)


def render_html(findings: list[Finding], host: str) -> str:
    e = html.escape
    kinds = collections.Counter(f.kind for f in findings)
    rows = []
    for i, f in enumerate(findings, 1):
        paths = "".join(
            f'<div class="p"><code>{e(p)}</code>'
            f'<button onclick="cp(this)" data-p="{e(p)}">copy</button></div>'
            for p in f.paths
        ) or '<div class="p none">not found on either share</div>'
        rows.append(
            f'<tr class="{e(f.kind)}"><td class="n">{i}</td>'
            f'<td><span class="k">{e(f.kind)}</span> <b>{e(f.title)}</b>'
            f'<div class="d">{e(f.detail)}</div>{paths}</td></tr>'
        )
    return f"""<!doctype html><meta charset="utf-8">
<title>HAP — what to fix</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,sans-serif;background:#111;color:#eee;
      margin:0;padding:32px;max-width:1100px}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#999;margin-bottom:24px}}
 table{{border-collapse:collapse;width:100%}}
 td{{border-bottom:1px solid #262626;padding:10px 8px;vertical-align:top}}
 td.n{{color:#666;width:48px;text-align:right}}
 .k{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#111;
     background:#c8a44a;border-radius:8px;padding:2px 7px}}
 tr.duplicate .k{{background:#6f9ad4}} tr.corrupt .k{{background:#d46f6f}}
 .d{{color:#999;font-size:12px;margin:4px 0}}
 .p{{display:flex;gap:8px;align-items:center;margin-top:3px}}
 .p code{{background:#1c1c1c;padding:3px 7px;border-radius:4px;font-size:12px;
          word-break:break-all}}
 .p.none{{color:#a66}}
 button{{background:#2a2a2a;color:#ddd;border:0;border-radius:4px;padding:3px 9px;
         font-size:11px;cursor:pointer}} button:hover{{background:#3a3a3a}}
</style>
<h1>What to fix on {e(host)}</h1>
<div class="sub">{kinds['cover']} albums without embedded artwork ·
{kinds['duplicate']} duplicated titles · {kinds['corrupt']} unreadable ·
{sum(1 for f in findings if f.folders)}/{len(findings)} located.
The player reads artwork <b>embedded in the tags</b>, so a cover.jpg sitting in the
folder does not count — open the folder in a tag editor and write it in.</div>
<table>{''.join(rows)}</table>
<script>
function cp(b){{navigator.clipboard.writeText(b.dataset.p);
 const t=b.textContent;b.textContent='copied';setTimeout(()=>b.textContent=t,900);}}
</script>"""


# ----------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Locate and act on what the audit found.")
    ap.add_argument("host", help="player IP or hostname")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="crawl both SMB shares (~4 min)")
    rep = sub.add_parser("report", help="findings with their real folders")
    rep.add_argument("--top", type=int, default=40)
    rep.add_argument("--html", metavar="FILE")
    rep.add_argument("--kind", choices=("cover", "duplicate", "corrupt"))
    for name in ("open", "edit"):
        p = sub.add_parser(name)
        p.add_argument("number", type=int, help="a number from `report`")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.cmd == "index":
        started = time.time()

        def note(share, i, total, files):
            if i % 100 == 0 or i == total:
                print(f"  {share} {i}/{total} folders, {files} files "
                      f"({time.time() - started:.0f}s)")

        try:
            index = crawl_shares(args.host, progress=note)
        except (RuntimeError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        where = save_index(index)
        counts = {s: len(f) for s, f in index["shares"].items()}
        print(f"\n{counts} → {where}")
        return 0

    harvest = hap_library.load_harvest(args.host)
    if harvest is None:
        print(f"error: no library harvest for {args.host}. Run:\n"
              f"    python tools/hap_library.py {args.host} harvest", file=sys.stderr)
        return 2
    index = load_index(args.host)
    if index is None:
        print(f"error: the shares have not been indexed. Run:\n"
              f"    python tools/hap_fixit.py {args.host} index", file=sys.stderr)
        return 2

    findings = build_findings(harvest, index)

    if args.cmd == "report":
        if args.kind:
            findings = [f for f in findings if f.kind == args.kind]
        if args.html:
            Path(args.html).write_bytes(
                render_html(findings, args.host).encode("utf-8"))
            print(f"HTML report written to {args.html}")
        print_report(findings, args.top)
        return 0

    if not 1 <= args.number <= len(findings):
        print(f"error: pick a number between 1 and {len(findings)}", file=sys.stderr)
        return 2
    target = findings[args.number - 1]
    if not target.folders:
        print("error: that one was never located on either share", file=sys.stderr)
        return 2
    if target.ambiguous:
        print(f"note: {len(target.folders)} copies exist; opening the first.")
    if args.cmd == "open":
        open_folder(target.path)
        print(f"opened {target.path}")
    else:
        used = open_in_editor(target.path)
        if not used:
            print("error: no tag editor found. Set HAP_TAG_EDITOR to its .exe.",
                  file=sys.stderr)
            return 1
        print(f"{used}\n  {target.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
