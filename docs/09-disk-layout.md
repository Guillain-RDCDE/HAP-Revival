# What's on the disk

This page describes exactly what lives on the HAP-Z1ES internal hard drive — the partitions, the
folders, and the databases — based on reading a real unit's disk directly over USB on 2026-06-02.
Before this, the data model was inferred from the Android app and the network API; now it's
ground truth. (Full forensic detail:
[`research/notes/2026-06-02-hdd-direct-read-ondisk-findings.md`](../research/notes/2026-06-02-hdd-direct-read-ondisk-findings.md).)

## For newcomers: the one-paragraph version

The hard drive inside a HAP-Z1ES is **not** where the operating system lives. It holds only two
things: your **music files**, and a set of **databases** that catalog them (artists, albums,
tracks, ratings, play counts, cover art). The OS itself — Linux, the Sony software, the audio
driver — is on a separate flash chip soldered to the mainboard. So you can pull the disk, read it
on any Linux machine, back it up, even replace it, without touching the OS. The catalog is plain
**SQLite**, the same database engine used by your phone and web browser — which means a
third-party app can read and understand your whole library.

## The two partitions

The disk uses an old-style **MBR** partition table with two **ext4** Linux partitions. Read it on
Linux (or WSL2 on Windows) — Windows can't mount ext4 on its own.

| Partition | Size | The device mounts it as | What's in it |
|---|---|---|---|
| 1 | 3 GB | `/data` | the SQLite databases (the catalog) |
| 2 | ~928 GB | `/mnt/internal` | the music files + cover-art cache |

> **There is no operating system on the disk.** Confirmed: neither partition is a Linux root —
> they are pure data. The OS is on internal flash (NAND/eMMC). This is *why* an HDD swap can never
> brick the bootloader (see [`06-hdd-swap.md`](06-hdd-swap.md)).

How do we know the mount points? ext4 records the last mount path in its superblock: partition 1
says `/data`, partition 2 says `/mnt/internal`.

## Partition 2 — your music (`/mnt/internal`)

```text
/mnt/internal/
├── storage/                         ← the music library
│   └── <Artist>/
│       └── <Album (year)>/
│           ├── 01 - <Artist> - <Title>.flac
│           ├── 02 - ...
│           └── Cover.jpg
├── db_storage/
│   ├── cover_art/A00xxxxx/          ← full-res album art (one dir per object id, in hex)
│   ├── tmp_cover_art/
│   ├── service_icon/                ← streaming-service logos
│   ├── radio_icon/{tunein,radiko,vTuner}/
│   └── fuse_storage/HDD1-6, HDD2-1  ← FUSE mount points
├── import_tmp/                      ← staging area for imports
├── internal/
├── POWERON_COUNT                    ← power-on counter
└── lost+found/
```

The music tree is simply **`storage/<Artist>/<Album>/<track files>`**. The database's folder
table mirrors this tree one-to-one. Cover art exists in two places: a small thumbnail embedded in
the database, and the **full-resolution image** under `db_storage/cover_art/`.

> **Permissions note (for anyone writing to the disk):** the album folders and audio files are
> owned by `root` with mode `0700` — the device's library scanner runs as root. A tool that writes
> files directly to the disk should set ownership `root:root` and mode `0700` to match.

## Partition 1 — the catalog (`/data`)

Everything here is **SQLite 3**, internal format version `ver 14.00`.

| Database | What it holds |
|---|---|
| `master.db` | the master library, in a generic "property-bag" form (cryptic `PROPxxxx` columns) |
| `hdd_browse.db` | the **same library, with a fully commented schema** — the human-readable one |
| `hdd_browse_for_disp.db` | a display-optimized copy (almost certainly what the network sync serves) |
| `hdd_history.db` | playback history |
| `management.db`, `local_master.db` | internal bookkeeping |
| `tunein_browse.db`, `netradio_*.db`, `radiko_browse.db` | streaming / web-radio catalogs |
| `spotify_preset.db`, `spotify_lastplayback.dat` | Spotify Connect state |
| `bivlPersistent.db` | Sony BIVL net-service framework state |

## The library data model (nerd section)

The schema is a Sony-internal property registry: tables named `FT<hex>` (object types), columns
named `PROP<hex>` (property ids, MTP/WMDM-like). `hdd_browse.db` ships the schema **with comments**,
so the codes are decodable. Real entity tables and the row counts from the reference unit:

| Table | Entity | Rows |
|---|---|---|
| `FT0002` | tracks | 77 668 |
| `FT5202` | artists | 21 849 |
| `FT6F02` | composers | 7 167 |
| `FT0000` | folders | 7 409 |
| `FT000A` | albums | 5 677 |
| `FT4502` | genres | 622 |
| `FT7002` | lyricists | 1 |
| `FTF003` / `FTF004` | playlists / playlist tracks | 0 / 0 |

Naming convention: `FT<XX>02` where `<XX>` is the low byte of the entity's id property
(52=artist → `FT5202`, 45=genre → `FT4502`, 6F=composer → `FT6F02`).

### Key PROP columns

| Code | Meaning | | Code | Meaning |
|---|---|-|---|---|
| `PROP3601` | object id (primary key) | | `PROP7020` | name (track/album/artist/folder) |
| `PROP3006` | parent id | | `PROP7065` | name, sort form |
| `PROP304B` | codec (enum, see below) | | `PROP7221` | name, initial letter (A–Z jump) |
| `PROP3047` | duration (**seconds**) | | `PROP7007` | file name |
| `PROP3048` | sample rate (Hz) | | `PROP7023` | folder path, as id chain `/9199/9200/` |
| `PROP304C` | audio bitrate | | `PROP7045` | genre id (→ `FT4502`) |
| `PROP10DE` | bit width (16/24) | | `PROP7052` | artist id (→ `FT5202`) |
| `PROP10A3` | disc number | | `PROP706F` | composer id (→ `FT6F02`) |
| `PROP3046` | play count | | `PROP7055` | album artist (denormalized) |
| `PROP6844` | release date (**year**) | | `PROP78D9` | cover thumbnail (BLOB) |
| `PROP087E` | rating | | `PROP2053` | track number / playlist position |
| `PROP58D3` | DRM flag | | `PROPB2BB` | album id (→ `FT000A`) |
| `PROP1086` | import type | | `PROPAA**` | yomi (Japanese phonetic) + edit flags |

### Codec enum (`PROP304B`) — ground truth

| Value | Codec | | Value | Codec |
|---|---|-|---|---|
| 49 | FLAC | | 65 | ALAC |
| 81 | MP3 | | 129 | WMA |
| 97 | AAC | | 17 | WAV/PCM |
| 33 | AIFF | | 0 | unscanned |

(High nibble groups the family: 0x10 PCM, 0x20 AIFF, 0x30 FLAC, 0x40 ALAC, 0x50 MP3, 0x60 AAC,
0x80 WMA.) On the reference unit: ~72k FLAC, ~5k MP3, the rest a long tail. Resolutions span
44.1 kHz/16-bit (the bulk) up to 24-bit/192 kHz. No DSD in this particular library.

Complete `.schema` dumps: [`research/db-schema/`](../research/db-schema/).

## Why this matters

- **A client can mirror the library locally.** We have the exact schema and a real database to
  validate against, so a HAP-Revival app can build and browse a local copy of the library — no
  longer blocked on the unsolved `downloadByDiff` network sync.
- **Direct-to-disk bulk transfer.** Because music is just files under `storage/<Artist>/<Album>/`,
  writing albums straight to the disk over USB (then re-docking and letting the device rescan)
  promises far faster bulk loading than SMBv1 over the network. Feasibility/validation is tracked
  in the research note.
