#!/usr/bin/env python3
"""
HAP companion — make any file-copy tool (FreeFileSync, rsync, drag-and-drop) HAP-aware.

This does NOT replace your copy tool. It adds the HAP-specific intelligence around it:
the pre-flight checks and the library-diff that a generic sync tool structurally cannot do,
because it doesn't know what the HAP-Z1ES / HAP-S1 accepts or what's already in its catalog.

Subcommands:

  validate <folder>
      Scan a local music folder *before* you transfer it and report:
        - files the HAP will REJECT (unsupported codec/container)
        - junk that pollutes the library if copied (FreeFileSync `.ffs_tmp`, `.part`,
          `Thumbs.db`, `.DS_Store`, AppleDouble `._*`, etc.) — these get indexed as
          phantom "tracks" (we found 68 such ghosts on a real unit)
        - PCM that exceeds the HAP's limits (> 192 kHz — the Forza driver caps the PCM
          path there; see docs/11-audio-path.md)
        - album folders missing cover art
      Reads FLAC/WAV headers (stdlib only) to check real sample-rate / bit-depth.

  diff <hdd_browse.db> <folder>
      Semantic diff: compare a local <Artist>/<Album>/ tree against the HAP's own SQLite
      catalog (the same hdd_browse.db tools/library_browser.py reads) and report which
      albums are NEW vs ALREADY on the HAP — so you only transfer what's missing, by
      content, not by filename/timestamp.

  wake <mac>            Send a Wake-on-LAN magic packet (the HAP sleeps in network standby).
  check <hap-ip>        Confirm the HAP is reachable (ports 445 / 60200).

Stdlib only. Read-only: it never writes to your files, the DB, or the device.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Iterable

import hap_update

from hap_catalog import open_catalog
from hap_common import API_PORT, SMB_DIRECT_PORT, force_utf8_stdio, send_wol, tcp_port_open
from hap_media import COVER_NAMES, PCM_CEILING_HZ, classify, pcm_sample_rate

#: How many offending paths a section prints before summarising the rest.
SECTION_LIMIT = 25
EXISTING_LIMIT = 40


# ---------- validate ----------


def scan_folder(folder: str) -> dict:
    """Walk a local music folder and classify every file the way the HAP would.

    Returns a dict with counts and the offending relative paths:
        {scanned, n_ok, n_unsup, n_junk, n_hi, junk[], unsup[], hires[], no_cover[]}
    Pure compute, no I/O to stdout — `cmd_validate` prints it, the GUI renders it.
    """
    folder = os.path.abspath(folder)
    n_ok = n_unsup = n_junk = n_hi = 0
    unsup: list[str] = []
    junk: list[str] = []
    hires: list[str] = []
    dirs_with_audio: set[str] = set()
    dirs_with_cover: set[str] = set()

    for root, _dirs, files in os.walk(folder):
        for fn in files:
            p = os.path.join(root, fn)
            kind = classify(fn)
            if kind == "junk":
                n_junk += 1
                junk.append(os.path.relpath(p, folder))
            elif fn.lower() in COVER_NAMES:
                dirs_with_cover.add(root)
            elif kind == "audio":
                n_ok += 1
                dirs_with_audio.add(root)
                rate = pcm_sample_rate(p)
                if rate and rate > PCM_CEILING_HZ:
                    n_hi += 1
                    hires.append(f"{os.path.relpath(p, folder)}  ({rate / 1000:g} kHz)")
            elif kind == "unsupported":
                n_unsup += 1
                unsup.append(os.path.relpath(p, folder))
            # sidecar files are harmless: the indexer ignores them

    return {"scanned": folder, "n_ok": n_ok, "n_unsup": n_unsup, "n_junk": n_junk,
            "n_hi": n_hi, "junk": junk, "unsup": unsup, "hires": hires,
            "no_cover": sorted(dirs_with_audio - dirs_with_cover)}


def print_section(title: str, items: list[str], marker: str = "-",
                  limit: int = SECTION_LIMIT, show_empty: bool = False) -> None:
    """`title (N):` then up to `limit` items; silent when empty unless `show_empty`."""
    if not items and not show_empty:
        return
    print(f"\n{title} ({len(items)}):")
    for it in items[:limit]:
        print(f"  {marker} {it}")
    if len(items) > limit:
        print(f"  … and {len(items) - limit} more")


def cmd_validate(folder: str) -> int:
    r = scan_folder(folder)
    print(f"Scanned: {r['scanned']}")
    print(f"  playable audio files : {r['n_ok']}")
    print(f"  unsupported           : {r['n_unsup']}")
    print(f"  junk (would pollute)  : {r['n_junk']}")
    print(f"  PCM over {PCM_CEILING_HZ // 1000} kHz       : {r['n_hi']}")
    print(f"  album folders w/o cover: {len(r['no_cover'])}")
    print_section("[JUNK] delete before transfer (gets indexed as phantom tracks)", r["junk"])
    print_section("[UNSUPPORTED] the HAP will not play these", r["unsup"])
    print_section("[OVER 192 kHz] exceeds the PCM path; downsample first", r["hires"])
    print_section("[NO COVER FILE] (embedded art may still work)", r["no_cover"])
    clean = r["n_unsup"] == r["n_junk"] == r["n_hi"] == 0
    print(f"\nVerdict: {'clean' if clean else 'issues found - see above'}")
    return 0 if (r["n_junk"] == 0 and r["n_unsup"] == 0) else 1


# ---------- diff against the HAP library DB ----------


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def catalog_albums(db_path: str) -> set[tuple[str, str]]:
    """Every (artist, album) pair in the catalogue, normalised for matching."""
    db = open_catalog(db_path)
    try:
        return {
            (_norm(artist or ""), _norm(album))
            for artist, album in db.execute(
                "SELECT ar.PROP7020, al.PROP7020 FROM FT0002 t "
                "LEFT JOIN FT5202 ar ON ar.PROP3601=t.PROP7052 "
                "LEFT JOIN FT000A al ON al.PROP3601=t.PROPB2BB"
            )
            if album
        }
    finally:
        db.close()


def local_albums(folder: str) -> Iterable[tuple[str, str]]:
    """(artist, album) folder pairs under `<folder>/<Artist>/<Album>/`."""
    for artist in sorted(os.listdir(folder)):
        ap = os.path.join(folder, artist)
        if not os.path.isdir(ap):
            continue
        for album in sorted(os.listdir(ap)):
            if os.path.isdir(os.path.join(ap, album)):
                yield artist, album


def diff_library(db_path: str, folder: str) -> dict:
    """Semantic diff of a local <Artist>/<Album>/ tree against the HAP's SQLite catalog.

    Returns {have_count, new[], existing[]} — albums NEW to the HAP vs already present,
    matched by content (artist+album, or album name alone). Read-only on the DB.
    """
    have = catalog_albums(db_path)
    have_albums = {a for _, a in have}
    new, existing = [], []
    for artist, album in local_albums(os.path.abspath(folder)):
        # match on (artist, album) or just album name (HAP album-artist may differ)
        if (_norm(artist), _norm(album)) in have or _norm(album) in have_albums:
            existing.append(f"{artist} / {album}")
        else:
            new.append(f"{artist} / {album}")
    return {"have_count": len(have), "new": new, "existing": existing}


def cmd_diff(db_path: str, folder: str) -> int:
    r = diff_library(db_path, folder)
    print(f"HAP library: {r['have_count']} (artist, album) pairs")
    print(f"Local tree : {os.path.abspath(folder)}")
    print_section("NEW — not on the HAP", r["new"], "+", limit=len(r["new"]), show_empty=True)
    print_section("ALREADY on the HAP — skip these", r["existing"], "=",
                  limit=EXISTING_LIMIT, show_empty=True)
    return 0


# ---------- wake / check ----------


def cmd_wake(mac: str) -> int:
    try:
        send_wol(mac)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"Magic packet sent to {mac}")
    return 0


def cmd_check(ip: str) -> int:
    ok = True
    for port, name in ((SMB_DIRECT_PORT, "SMB"), (API_PORT, "ScalarWebAPI")):
        is_open = tcp_port_open(ip, port)
        ok = ok and is_open
        print(f"  {ip}:{port:<6} {name:<14} {'open' if is_open else 'CLOSED'}")
    print("[OK] HAP reachable" if ok else "[FAIL] HAP not fully reachable")
    return 0 if ok else 1


# ---------- CLI ----------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="hap_companion",
        description="HAP-aware pre-flight checks and library diff for any copy tool.",
    )
    hap_update.add_version_flag(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate",
                       help="scan a folder for junk / unsupported / >192 kHz / no cover")
    p.add_argument("folder")
    p = sub.add_parser("diff", help="compare a local tree with the HAP's hdd_browse.db")
    p.add_argument("db", help="path to hdd_browse.db")
    p.add_argument("folder")
    p = sub.add_parser("wake", help="send a Wake-on-LAN magic packet")
    p.add_argument("mac")
    p = sub.add_parser("check", help="confirm the HAP answers on ports 445 and 60200")
    p.add_argument("ip")
    return ap


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()  # never crash on unicode track/artist names on a legacy console
    args = build_parser().parse_args(argv)
    hap_update.notice_at_exit()
    try:
        if args.cmd == "validate":
            return cmd_validate(args.folder)
        if args.cmd == "diff":
            return cmd_diff(args.db, args.folder)
        if args.cmd == "wake":
            return cmd_wake(args.mac)
        return cmd_check(args.ip)
    except (FileNotFoundError, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
