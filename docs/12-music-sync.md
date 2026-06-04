# Getting music onto the HAP — `hap_sync` (a FreeFileSync replacement)

This is the practical guide to [`tools/hap_sync.py`](../tools/hap_sync.py): a small tool that copies
your music to the HAP-Z1ES / HAP-S1 and keeps it in sync — purpose-built for the HAP, so it does the
things a generic sync tool (FreeFileSync, rsync, drag-and-drop) can't.

> **Prefer a window to a command line?** [`tools/hap_gui.py`](../tools/hap_gui.py) (**HAP Sync**) is a
> one-click Windows GUI over this exact engine: auto-detect the device, pick your two folders (remembered
> between runs), Analyze, then Sync with a live progress bar. Run `python tools/hap_gui.py`, or build a
> standalone `HapSync.exe` with [`tools/build_gui.ps1`](../tools/build_gui.ps1). Everything below applies
> equally — the GUI just drives the same code with buttons.

## What it does that FreeFileSync doesn't

- **Transfers to the HAP's own SMB1 share** via `pysmb`, so you **don't have to turn on the insecure
  SMB1 client in Windows** (the thing modern Windows disables for good reasons).
- **Handles your two folders → two shares in one command.** The HAP exposes `HAP_Internal` (built-in
  disk) and `HAP_External` (USB drive); you feed each from a different PC folder.
- **Auto-skips junk** that otherwise gets indexed as phantom "tracks" — FreeFileSync `.ffs_tmp` temp
  files, `Thumbs.db`, `.DS_Store`, `._*`, `.part`… (we found 68 such ghosts on a real unit).
- **Auto-skips formats the HAP can't play**, and warns about PCM over 192 kHz.
- **Incremental:** copies only new/changed files. The HAP re-indexes them on its own within seconds.
- **Fast on huge libraries** thanks to a remote-index cache (below).
- **Never deletes** anything on the HAP. Add/update only.

> A few small tools, easy to mix up — here's the split:
>
> | Tool | What it's for |
> |---|---|
> | **`hap_gui.py`** | the **HAP Sync** Windows app — `hap_sync` with buttons, a progress bar and auto-detect |
> | **`hap_sync.py`** | **transfer** your music to the HAP (CLI) — the FreeFileSync replacement |
> | `library_browser.py` | **browse/view** your library in a web page (see [`09-disk-layout.md`](09-disk-layout.md)) |
> | `hap_companion.py` | standalone pre-flight checks (the same filtering is already built into `hap_sync`) |

## 1. Install pysmb (once)

```bash
pip install pysmb
```

On Windows, if `pip` is missing ("No module named pip"), enable it first:

```bash
python -m ensurepip --upgrade
python -m pip install pysmb
```

## 2. Configure your two folders

Copy [`tools/hap_sync.json.example`](../tools/hap_sync.json.example) to `tools/hap_sync.json` and set
your paths. This file stays on your machine — it's git-ignored, so your personal paths never leave it.

```json
{
  "host": "192.168.1.28",
  "mac":  "80:56:F2:85:0E:27",
  "maps": [
    {"local": "D:/Music/Internal", "share": "HAP_Internal"},
    {"local": "D:/Music/External", "share": "HAP_External"}
  ]
}
```

- `host` — your HAP's IP. `mac` — its Ethernet MAC (only needed for `wake`).
- `maps` — one line per folder→share pair. Each local folder's contents go to the **root** of its
  share, so lay them out as `D:/Music/Internal/<Artist>/<Album>/<tracks>`.

## 3. Daily workflow

```bash
# ONE time (or after you've changed the HAP by other means): build the index cache.
python tools/hap_sync.py refresh        # full scan of the device — a few minutes on a big library

# Every time you add music:
python tools/hap_sync.py plan           # dry-run: shows exactly what's new (instant, from cache)
python tools/hap_sync.py sync           # transfers only the new/changed files
```

Useful flags/commands:

| Command | What it does |
|---|---|
| `plan` | preview only — never writes |
| `sync` | transfer new/changed files to all shares |
| `sync --only HAP_External` | just one share |
| `sync --dry-run` | same as `plan` |
| `sync --all` | also copy files normally flagged unsupported |
| `sync --refresh` / `plan --refresh` | ignore the cache and re-scan the HAP first |
| `refresh` | rebuild the cache (full re-scan) |
| `list HAP_Internal` | list what's on a share |
| `wake` | Wake-on-LAN (if the HAP is in network standby) |
| `check` | is the HAP reachable? |

## The cache — why the first run is slow and the rest are instant

The HAP only speaks **SMB1**, and listing a real library (60–70k files) over SMB1 takes **several
minutes**. We don't want to pay that on every run, so `hap_sync` keeps a **cache of the remote file
index** (each file's path + size) on disk, in a git-ignored `.hap_sync_cache/` folder next to your
config:

- The **first** `refresh`/`sync` scans the device and writes the cache.
- After that, `plan` and `sync` read the cache **instantly** instead of re-listing.
- When `sync` uploads files, it **folds them into the cache** — so the next run already knows about
  them and still doesn't need to re-scan.
- If the HAP changed by some other route (you added files via FreeFileSync, or the device itself),
  run `refresh` (or `sync --refresh`) to rebuild the cache.

Measured on a real unit: a full `refresh` took ~8 minutes (67,106 files); after that, `plan` ran in
**0.6 s** and a `sync` in ~8 s (almost all of it the actual upload).

## What counts as "junk" or "unsupported"

- **Junk (always skipped):** `*.ffs_tmp`, `*.ffs_lock`, `*.part`, `*.partial`, `*.tmp`,
  `*.crdownload`, `Thumbs.db`, `.DS_Store`, `desktop.ini`, AppleDouble `._*`.
- **Playable (copied):** FLAC, WAV, AIFF, ALAC, DSF/DFF (DSD), MP3, AAC/M4A, WMA, ATRAC.
- **Sidecars (copied, harmless — the indexer ignores them):** `cover.jpg`/`folder.jpg`, `.cue`,
  `.m3u`, `.log`, `.nfo`, `.pdf`, etc.
- **Unsupported (skipped unless `--all`):** anything else.

## Troubleshooting

- **"pysmb is required"** → `pip install pysmb` (see step 1; on Windows you may need `ensurepip` first).
- **First run is slow** → that's the one-time full scan; subsequent runs use the cache. See above.
- **A file didn't transfer / you changed the HAP elsewhere** → `sync --refresh` to rebuild the cache.
- **HAP asleep** → `python tools/hap_sync.py wake`, then sync.
- **Connection fails** → `python tools/hap_sync.py check`; confirm the IP in your config and that the
  HAP is on the LAN.

Background on the share layout, permissions, and the SMB security boundary: [`04-smb.md`](04-smb.md).
