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

import os
import socket
import struct
import sys
import wave

# ---- what the HAP accepts (docs/04-smb.md + the Forza driver) ----
SUPPORTED_EXT = {
    ".flac", ".wav", ".aif", ".aiff", ".alac",        # lossless PCM
    ".dsf", ".dff",                                    # DSD
    ".m4a", ".mp3", ".aac", ".wma",                    # lossy (m4a = AAC or ALAC)
    ".oma", ".aa3", ".at3",                            # ATRAC family
}
COVER_NAMES = {"cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "front.jpg", "front.jpeg"}
JUNK_SUFFIXES = (".ffs_tmp", ".ffs_lock", ".part", ".partial", ".tmp", ".crdownload")
JUNK_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}
PCM_MAX_HZ = 192000  # Forza PCM path cap


def flac_streaminfo(path: str):
    """Return (sample_rate, bits, channels) from a FLAC STREAMINFO block, or None."""
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"fLaC":
                return None
            # first metadata block header: 1 byte (last-flag+type) + 3 bytes length
            f.read(4)
            info = f.read(34)  # STREAMINFO body
            if len(info) < 18:
                return None
            # layout: minblk16 maxblk16 minframe24 maxframe24 then at byte 10:
            #   sample_rate(20) channels(3) bps-1(5) total(36) md5(128)
            v = struct.unpack(">I", info[10:14])[0]
            sample_rate = v >> 12
            channels = ((v >> 9) & 0x7) + 1
            bits = ((v >> 4) & 0x1F) + 1
            return sample_rate, bits, channels
    except Exception:  # noqa: BLE001
        return None


def wav_info(path: str):
    try:
        with wave.open(path, "rb") as w:
            return w.getframerate(), w.getsampwidth() * 8, w.getnchannels()
    except Exception:  # noqa: BLE001
        return None


def is_junk(name: str) -> bool:
    low = name.lower()
    return low in JUNK_NAMES or low.startswith("._") or low.endswith(JUNK_SUFFIXES)


# ---------- validate ----------

def cmd_validate(folder: str) -> int:
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
            low = fn.lower()
            if is_junk(fn):
                n_junk += 1
                junk.append(os.path.relpath(p, folder))
                continue
            if low in COVER_NAMES:
                dirs_with_cover.add(root)
                continue
            ext = os.path.splitext(low)[1]
            if ext in SUPPORTED_EXT:
                n_ok += 1
                dirs_with_audio.add(root)
                rate = None
                if ext == ".flac":
                    r = flac_streaminfo(p)
                    rate = r[0] if r else None
                elif ext == ".wav":
                    r = wav_info(p)
                    rate = r[0] if r else None
                if rate and rate > PCM_MAX_HZ:
                    n_hi += 1
                    hires.append(f"{os.path.relpath(p, folder)}  ({rate/1000:g} kHz)")
            elif ext in (".jpg", ".jpeg", ".png", ".pdf", ".txt", ".nfo", ".log",
                         ".cue", ".m3u", ".m3u8", ".sfv", ".md5", ""):
                pass  # sidecar files — harmless, the indexer ignores them
            else:
                n_unsup += 1
                unsup.append(os.path.relpath(p, folder))

    no_cover = sorted(dirs_with_audio - dirs_with_cover)

    def section(title, items, limit=25):
        if not items:
            return
        print(f"\n{title} ({len(items)}):")
        for it in items[:limit]:
            print(f"  - {it}")
        if len(items) > limit:
            print(f"  … and {len(items) - limit} more")

    print(f"Scanned: {folder}")
    print(f"  playable audio files : {n_ok}")
    print(f"  unsupported           : {n_unsup}")
    print(f"  junk (would pollute)  : {n_junk}")
    print(f"  PCM over {PCM_MAX_HZ//1000} kHz       : {n_hi}")
    print(f"  album folders w/o cover: {len(no_cover)}")
    section("[JUNK] delete before transfer (gets indexed as phantom tracks)", junk)
    section("[UNSUPPORTED] the HAP will not play these", unsup)
    section("[OVER 192 kHz] exceeds the PCM path; downsample first", hires)
    section("[NO COVER FILE] (embedded art may still work)", no_cover)
    verdict = "clean" if (n_unsup == n_junk == n_hi == 0) else "issues found - see above"
    print(f"\nVerdict: {verdict}")
    return 0 if (n_junk == 0 and n_unsup == 0) else 1


# ---------- diff against the HAP library DB ----------

def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def cmd_diff(db_path: str, folder: str) -> int:
    import sqlite3
    import urllib.parse
    uri = f"file:{urllib.parse.quote(db_path)}?immutable=1&mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.text_factory = lambda b: b.decode("utf-8", "replace")  # DB has some latin-1 text
    # build a set of (artist, album) already in the library
    have = set()
    for artist, album in db.execute(
        "SELECT ar.PROP7020, al.PROP7020 FROM FT0002 t "
        "LEFT JOIN FT5202 ar ON ar.PROP3601=t.PROP7052 "
        "LEFT JOIN FT000A al ON al.PROP3601=t.PROPB2BB"
    ):
        if album:
            have.add((_norm(artist or ""), _norm(album)))
    have_albums = {a for _, a in have}

    folder = os.path.abspath(folder)
    new, existing = [], []
    # expect <folder>/<Artist>/<Album>/...  — one level of artist, one of album
    for artist in sorted(os.listdir(folder)):
        ap = os.path.join(folder, artist)
        if not os.path.isdir(ap):
            continue
        for album in sorted(os.listdir(ap)):
            bp = os.path.join(ap, album)
            if not os.path.isdir(bp):
                continue
            key = (_norm(artist), _norm(album))
            # match on (artist, album) or just album name (HAP album-artist may differ)
            if key in have or _norm(album) in have_albums:
                existing.append(f"{artist} / {album}")
            else:
                new.append(f"{artist} / {album}")

    print(f"HAP library: {len(have)} (artist, album) pairs")
    print(f"Local tree : {folder}\n")
    print(f"NEW — not on the HAP ({len(new)}):")
    for x in new:
        print(f"  + {x}")
    print(f"\nALREADY on the HAP ({len(existing)}) — skip these:")
    for x in existing[:40]:
        print(f"  = {x}")
    if len(existing) > 40:
        print(f"  … and {len(existing) - 40} more")
    return 0


# ---------- wake / check ----------

def cmd_wake(mac: str) -> int:
    hexmac = mac.replace(":", "").replace("-", "").strip()
    if len(hexmac) != 12:
        print("error: MAC must be 12 hex digits (e.g. 80:56:F2:85:0E:27)", file=sys.stderr)
        return 2
    packet = b"\xff" * 6 + bytes.fromhex(hexmac) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(packet, ("255.255.255.255", 9))
    s.close()
    print(f"Magic packet sent to {mac}")
    return 0


def cmd_check(ip: str) -> int:
    ok = True
    for port, name in ((445, "SMB"), (60200, "ScalarWebAPI")):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        r = s.connect_ex((ip, port))
        s.close()
        state = "open" if r == 0 else "CLOSED"
        ok = ok and r == 0
        print(f"  {ip}:{port:<6} {name:<14} {state}")
    print("[OK] HAP reachable" if ok else "[FAIL] HAP not fully reachable")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    try:  # never crash on unicode track/artist names on a legacy Windows console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    try:
        if cmd == "validate" and len(argv) > 2:
            return cmd_validate(argv[2])
        if cmd == "diff" and len(argv) > 3:
            return cmd_diff(argv[2], argv[3])
        if cmd == "wake" and len(argv) > 2:
            return cmd_wake(argv[2])
        if cmd == "check" and len(argv) > 2:
            return cmd_check(argv[2])
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
