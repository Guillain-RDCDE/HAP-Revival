# 2026-06-02 — Direct HDD read: on-disk layout, ground-truth DB schema, corrections

The internal disk was pulled and read over USB (JMicron adapter) on a Windows box via WSL2.
This is the first time the HAP's disk has been examined directly rather than inferred from the
APK or the API. It **confirms** the schema reverse-engineered on 2026-05-25 from
`assets/demo_browse.db`, fills several gaps with ground truth, and **corrects two long-standing
assumptions** in the docs.

## TL;DR

- The HDD has **two ext4 partitions**, mounting on the device as **`/data`** (3 GB, the SQLite
  databases) and **`/mnt/internal`** (928 GB, the music files + cover-art cache).
- **There is no rootfs on the HDD.** Neither partition is a Linux root. This narrows
  `02-software-stack.md` Open Question #1: the OS/userland lives on internal flash (NAND/eMMC),
  not the disk. The disk is pure application data.
- **The music library metadata is SQLite, not Tokyo Cabinet.** Format version `ver 14.00`.
  This corrects `02-software-stack.md` and `06-hdd-swap.md`.
- The music tree is **`/mnt/internal/storage/<Artist>/<Album (year)>/<NN - Artist - Title.ext>`**
  — not `/mnt/internal/Music/...` as the audio-path diagram guessed.
- Full-resolution cover art is cached separately at **`/mnt/internal/db_storage/cover_art/A00xxxxx/`**
  (keyed by object id in hex); the `PROP78D9` BLOB in the DB is only a small thumbnail.

## Method

```text
Windows 11 + WSL2 (Ubuntu). Disk attached raw to WSL:
  wsl --mount \\.\PHYSICALDRIVE2 --bare      (admin)
Imaged partition 1 (the small data partition) as a backup, sha256-verified bit-for-bit:
  sudo dd if=/dev/sde1 of=p1_data.img bs=4M conv=noerror,sync
  sha256: 60433f46…52f7b4ab  (device == image, verified)
Mounted everything READ-ONLY for inspection:
  mount -o ro,loop p1_data.img /mnt/hap        # /data
  mount -o ro /dev/sde2        /mnt/hap2        # /mnt/internal
```

No writes were ever made to the disk. The 928 GB music partition was not imaged (size); only
its structure was walked.

## Partition table (MBR, disk id `0xae864d33`)

| Part | Start sector | Size | FS | Mounts on device as | UUID | Role |
|---|---|---|---|---|---|---|
| `p1` | 64 | 3 GiB | ext4 | **`/data`** | `715f1f90-…3a3c7e` | SQLite databases |
| `p2` | 6 291 520 | 928.5 GiB | ext4 | **`/mnt/internal`** | `276f1c6e-…189e6b6f` | music + cover art |

ext4 details (both): block size 4096, `has_journal`, created 2019-10-08, mounted ~1424 times.
`p1` last-mounted-on `/data`, `p2` last-mounted-on `/mnt/internal` (recorded in the superblock —
this is how we know the device's mount points without a shell). Default mount options
`user_xattr acl`. Lifetime writes: 365 GB (p1), 2608 GB (p2).

## Partition 1 = `/data` (the databases)

All SQLite 3.x. Nothing else but `lost+found`, an empty `mmlib2/`, and `dbmanager/`
(two counter files `restoredatabase_skip_count`, `syncdatabase_skip_count`).

| File | Size | Role |
|---|---|---|
| `master.db` | 44 MB | master library — **generic property-bag schema** (raw `PROPxxxx` columns, no comments) |
| `hdd_browse.db` | 59 MB | browse view — **same data, fully commented schema** (the Rosetta stone) |
| `hdd_browse_for_disp.db` | 59 MB | display-optimized copy of the browse DB (the one `downloadByDiff` almost certainly serves) |
| `hdd_history.db` | 64 KB | playback history |
| `local_master.db`, `management.db` | | internal management |
| `spotify_preset.db`, `spotify_lastplayback.dat` | | Spotify Connect |
| `tunein_browse.db` | 2 MB | TuneIn |
| `netradio_browse.db` / `_for_disp` / `netradio_management.db` | | web radios |
| `radiko_browse.db` | | Radiko (JP) |
| `bivlPersistent.db` | | BIVL (Bravia Internet Video Link, Sony's net-service framework) |

`master.db`'s `Internals` table carries `ver 14.00` (DB format version) and an `OK` health flag.

### Schema is confirmed identical to the APK demo DB

Every table and PROP column matches the 2026-05-25 reverse from `demo_browse.db`. The live DB
just has the data: **77 668 tracks** vs 3 demo rows. Table → entity → real row counts:

| Table | Entity | Rows (this unit) |
|---|---|---|
| `FT0002` | tracks | 77 668 |
| `FT5202` | artists | 21 849 |
| `FT6F02` | composers | 7 167 |
| `FT0000` | folders | 7 409 |
| `FT000A` | albums | 5 677 |
| `FT4502` | genres | 622 |
| `FT7002` | lyricists | 1 |
| `FTF003` / `FTF004` | playlists / playlist tracks | 0 / 0 |

Full `.schema` dumps for every DB committed under [`research/db-schema/`](../db-schema/).

### Ground-truth enums (new — these were guesses before)

**Codec (`FT0002.PROP304B`)** — resolved by joining against file extension:

| Value | Codec | Count |
|---|---|---|
| 49 (0x31) | FLAC | 72 188 |
| 81 (0x51) | MP3 | 5 207 |
| 97 (0x61) | AAC (.m4a) | 77 |
| 65 (0x41) | ALAC (.m4a) | 20 |
| 129 (0x81) | WMA | 43 |
| 17 (0x11) | WAV/PCM | 25 |
| 33 (0x21) | AIFF | 19 |
| 0 | unscanned / unknown | 89 |

The high nibble groups by family (0x10 PCM-WAV, 0x20 AIFF, 0x30 FLAC, 0x40 ALAC, 0x50 MP3,
0x60 AAC, 0x80 WMA). DSD codes not present in this library (it's all PCM).

- **`PROP6844` release date = plain YEAR integer** (1900, 1985, …), NOT epoch and NOT YYYYMMDD.
  Corrects the 2026-05-25 guess.
- **`PROP3047` duration = seconds** (min 2, max 4474 ≈ 74 min, avg 264 ≈ 4:24). Confirmed.
- **`PROP1086` import type**: two values observed — `0` (22 392 rows) and `131073` = `0x00020001`
  (55 276 rows). Semantics still inferred (likely distinguishes import path/source); bitfield-shaped.
- **Resolution spread**: 44.1 kHz/16-bit dominates (73 459), with 24-bit hi-res at 44.1/48/88.2/96/192 kHz.

## Partition 2 = `/mnt/internal` (music + art)

Top level:

| Entry | Notes |
|---|---|
| `storage/` | **the music library** — 543 artist folders, perms 0777 at top |
| `db_storage/` | art & icon caches (see below) |
| `import_tmp/` | empty staging dir for imports |
| `internal/` | empty, owned `nobody:root` |
| `POWERON_COUNT` | a counter file (read `1397` on this unit) |
| `lost+found/` | |

**Music layout**: `storage/<Artist>/<Album (year)>/<NN - Artist - Title.flac>` plus a `Cover.jpg`
per album. This mirrors the `FT0000` folder table exactly: `PROP7023` encodes the tree as an
ID-path (`/9199/9200/`), root folder id `4100` = `storage/` (its parent is the sentinel
`0x10000000`). 21 702 FLAC + 969 MP3 + 2 562 JPG + cue/m3u/nfo/pdf in the walked sample.

**`db_storage/` caches**:

- `cover_art/A00xxxxx/` — full-resolution album art, one dir per object id (hex). This is where
  real artwork lives; the DB's `PROP78D9` BLOB is only a ~1–2 KB thumbnail.
- `tmp_cover_art/`, `service_icon/<id>_logo.png`, `radio_icon/{tunein,radiko,vTuner}/`.
- `fuse_storage/HDD1-6`, `HDD2-1` — **FUSE mount points**. The device presents storage through a
  FUSE layer (consistent with the `unfs3` package of unknown purpose in the GPL bundle). Worth a
  closer look when we have a shell.

### Permissions reality (matters for any write tool)

The top `storage/` dir is 0777, but **actual album dirs and files are `0700 root:root`**
(`-rwx------`). The library scanner therefore runs as **root**. A direct-to-disk transfer tool
must write files as `root:root` mode `0700` to match the device's own convention (trivial when
the disk is mounted as root under WSL).

## Corrections to existing docs (made in this commit)

1. `02-software-stack.md` + `06-hdd-swap.md`: "Tokyo Cabinet" as the **library metadata store**
   → it is **SQLite** (`/data/*.db`, format `ver 14.00`). Tokyo Cabinet is in the GPL package
   list but is not the library DB; its actual use (if any) is now an open question.
2. `02-software-stack.md` audio-path diagram: `/mnt/internal/Music/...` → `/mnt/internal/storage/...`;
   the inferred `library.tch` path is wrong — metadata is `/data/*.db`.
3. `02-software-stack.md` Open Question #1 (rootfs location): the HDD holds **no rootfs** — only
   `/data` + `/mnt/internal`. Rootfs is on internal flash. Partially answered.

## Why this matters for the project

- **Library browser, unblocked locally.** The `downloadByDiff` empty-`location` blocker
  (2026-05-26) was the only path we had to the library DB *over the network*. We now have the DB
  itself, and we know its exact contents and the schema's ground truth — so a client's local
  mirror can be built and validated against a real DB today, independent of solving `downloadByDiff`.
- **Direct-to-disk bulk transfer is viable.** Writing albums straight into
  `/mnt/internal/storage/<Artist>/<Album>/` over USB (then re-docking and letting the device
  rescan) should be dramatically faster than SMBv1 over the network for bulk loads. Design + the
  rescan-on-mount assumption still need validation on the live device — see follow-up.

## Open follow-ups

- Confirm the device performs a full/diff rescan of `storage/` on cold mount (not only on
  SMB-drop). Can't be verified without re-docking the disk in the unit.
- `PROP1086` import-type bitfield semantics.
- What, if anything, uses Tokyo Cabinet on the device.
- Inspect `fuse_storage` semantics with a shell.

Related: [`docs/09-disk-layout.md`](../../docs/09-disk-layout.md),
[`research/notes/2026-05-25-database-service-and-db-schema.md`](2026-05-25-database-service-and-db-schema.md).
