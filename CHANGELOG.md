# Changelog

All notable changes to HAP-Revival will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once we ship a versioned release.

## [Unreleased]

### Added (2026-08-21, the 417 trap, and a cousin module ruled out)

- **The `Expect: 100-continue` → `417` quirk now has a fix for every client, and the fix is tested.**
  We had documented the quirk but only given a remedy for Python `requests`. It cost a contributor
  an evening, because it bites *only requests with a body* — reads work, writes fail, and it reads
  like a syntax error. Reproduced against a Z1ES on PowerShell 5.1 (`$true` → 417, `$false` → 200)
  and confirmed at the protocol level: `POST /operation` returns 200 without the header and 417 with
  it. The subtlety that makes the fix fail silently is now written down — `ServicePoint` copies
  `Expect100Continue` when it is created, so the line must come before the *first* request to that
  host. Also noted: in Windows PowerShell 5.1 `curl` is an alias for `Invoke-WebRequest`, so `-X`,
  `-H` and `-d` are misparsed; call `curl.exe`.
- **Crestron STR-DN1050 module: checked and ruled out** (`docs/08-prior-art.md` §6b). Suggested by
  Amos on the reasonable hunch that another 2014-era Sony module might share the HAP's protocol. It
  does not: raw TCP on port 33335, a byte stream with no JSON, no REST, polling only. Verified that
  port 33335 is connection-refused on the HAP. Three Sony generations, three unrelated control
  planes — receivers on 33335, the HAP on 60200, the STR-DN1080 of 2017 on ScalarWebAPI 10000. Only
  the HAP-S1 shares the Z1ES's protocol.
- **Method recorded: any Crestron module's Help PDF is public** — fetch the product page, grep for
  `content/Help/`, fetch that URL. No account. Only the module package needs one. A sweep found 18
  Sony products on the market, none of them in the HAP family; that avenue is exhausted.
- **Reported on a real HAP-S1** (Amos): all three tone-control reads return data, and a
  `tonecontrolbass` write returns `200 {}`. Marked as a contributor report pending the capture
  files, not as verified.
- **The Z1ES/S1 volume divergence is now observed, and it exposes dead code in the module.** An S1
  answers `GET …/volumelevel` with `{"mute":"off","volume_level":7}` where the Z1ES returns `500` —
  but the response carries **no `volume_level_min` / `_max`**, the two fields the Crestron parser
  requires before it will emit any volume feedback at all. Cross-checked against the rest of the
  package: the SIMPL+ module exposes no volume signal, and the Help PDF documents none. Crestron
  wrote volume support against a response shape no shipping HAP produces and left it disconnected.
  Our client must treat `volume_level` as an opaque integer and must not rescale it to a percentage.

### Changed (2026-08-20, the web UI stops polling)

Follow-up to the teardown below, closing the two gaps that commit left open.

- **[`tools/webui.py`](tools/webui.py) is push-driven.** The server subscribes to the player's UDP
  notification stream and the browser long-polls `/api/events`, which is released the moment
  something changes — a track change now appears immediately instead of up to three seconds later.
  Verified end-to-end against a live Z1ES: a real push released the long-poll in 5.6 s of a 25 s
  window and moved the generation counter.
- **The timer stays, with a job.** It advances the progress bar and it is the whole story when push
  is unavailable — player asleep, `--demo`'s mock device, or the new `--no-push`. It ticks at 3 s
  without push and 10 s with it, and retunes itself when push comes or goes. `PushWatcher` retries
  in the background, so a player switched on later starts pushing without restarting the UI.
- **The progress bar is smoother while talking less.** Position is now advanced locally once a
  second from the last anchor the player gave us, instead of jumping on each poll.
- **`--no-push` and `--notify-port`** added for people who would rather not open a UDP port, or who
  need a different one.
- **The six-language claim now holds for the whole surface.** `hap_notify.py`'s CLI strings were
  English-only; they are in the catalogue in all six languages, and the tool takes `--lang` like
  every other. The web footer's `web.footer.polls` ("polls every 3s") became `web.footer.live`,
  since it was describing behaviour the UI no longer has.
- **18 new tests** (146 → **164**), all offline: the generation/long-poll semantics, one event
  releasing every waiting browser tab, junk `since` parameters, the no-watcher fallback, and three
  guards that fail if any of the new strings ever falls back to English.

### Added (2026-08-20, Crestron module teardown — two corrections and a second API)

The Crestron certified module for the HAP-Z1ES, contributed by **Amos**, who bought it for $0.00
from the Crestron Application Market. `docs/08-prior-art.md` had it listed as the single most
valuable missing artefact. It delivered more than the Help PDF: `Crestron.Sony.ContentServiceWebApi.dll`
is a complete, non-obfuscated protocol client that decompiles cleanly. Findings re-verified live
against a Z1ES on 19404R. Full teardown in
[`research/notes/2026-08-20-crestron-module-teardown.md`](research/notes/2026-08-20-crestron-module-teardown.md).

- **The HAP has push notifications — we said it didn't.** `POST /sony/notification/status` with
  `{"status":"enable","port":N}` returns `{"timeout":300,"port":N}` and the device then pushes
  pseudo-HTTP `NOTIFY` datagrams over UDP, each carrying an `event` name and a `url` to read the new
  state from, retransmitted three times under one `SEQ`. Verified live. The earlier "polling-only"
  conclusion came from an APK search for `switchNotifications` and WebSocket — both genuinely
  absent, but the mechanism is neither, and Sony's own app never subscribes. Corrected in
  `docs/03-network-api.md` and `research/api-method-catalog.md`.
- **`/sony/contentplayer/v100` is alive — we had the whole REST surface down as vestigial.** Power,
  transport, now-playing, sound settings, external input, plus one `POST …/operation` endpoint for
  every write, discriminated by a `method` field. Only the `contentdb` half is dead.
- **The `contentdb` hang is a dead handler, not an unknown route.** Unknown paths 404 in
  milliseconds; only `contentdb`'s leaves hang. Combined with the PDF naming vendor firmware
  `0017310R`, this points at a library API that was withdrawn between that firmware and 19404R —
  the first evidence an older firmware is functionally richer. See `docs/07-firmware.md`.
- **Trap documented: the daemon serialises requests.** One pending `contentdb` request makes every
  other endpoint time out, including ones that answered seconds earlier. Concurrent probing
  manufactures false negatives across the entire surface — it produced one on the notification
  endpoint during this very session. Probe sequentially with health checks.
- **New surface**: S1 tone control (`tonecontrolbass`/`treble`/`bypass`, −10…+10), SensMe channels,
  a `spotify_connect` source type absent from the 2016 enum, and an undocumented `streaming`
  content type that Crestron themselves could not parse.

Licence: the binaries are © Crestron Electronics. Protocol facts are documented and re-verified; no
decompiled code enters this repository.

- **New tool: [`tools/hap_notify.py`](tools/hap_notify.py)** — subscribes to the push stream and
  streams events, with `--follow` to read back the new state. Handles the three traps for you:
  `SEQ` deduplication, re-arming at 80% of the server-declared timeout, and priming Windows'
  stateful UDP filter so the firewall stops dropping the inbound datagrams. Smoke-tested against a
  live Z1ES: 15 datagrams in, 5 events out.
- **30 new tests** (116 → **146**), all offline. The parser is tested against a datagram captured
  verbatim from the device, the deduplicator against the real three-times-per-event retransmission
  pattern, and the notifier end-to-end over loopback. One test pins `SUBSCRIBE_PATH` to
  `/sony/notification/status` as a regression guard, since the Crestron module's own path omits the
  `/sony` prefix and 404s.

### Changed (2026-08-15, README rebuilt around what actually ships)

- The landing page opened on the manifesto and buried the working tools in a compressed table, so a
  visitor read *"pre-alpha research project"* before learning that ten finished tools are one click
  away. Rebuilt: hero with call-to-action buttons, **"What you can use today"** directly under it
  (one line per tool, each linked to its source, HAP Sync marked as the entry point), then the
  5-minute quickstart. The manifesto, the SMB story and the reverse-engineering status now sit
  *below* the tools. Dropped the `pre-alpha` badge; added release, test-count and language badges.

## [hap-sync-v0.2.0] — 2026-08-15

First published release with a downloadable binary
([`HapSync.exe`](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest/download/HapSync.exe),
Windows x64, 14.7 MB, self-contained — SHA-256
`8ca8edf7a9cbbed89c96d83a025cadfd9a9066a5cf8c454cefef01efd3d94db3`). The `hap-sync-v0.1.0` tag was
never attached to a GitHub release, so every download link in the README pointed at nothing.

### Fixed (2026-06-29, SMB1 transfer drops)

- **Transfers no longer stall mid-library.** The HAP's Samba 3.0.37 desyncs SMB1 framing over
  Direct TCP (port 445) after a file or two — surfacing as *"Invalid protocol header for Direct TCP
  session message"*. [`tools/hap_sync.py`](tools/hap_sync.py) now connects over **NetBIOS (139)**
  first, falling back to 445, and opens a **fresh session per file** so the connection never lives
  long enough to drift mid-stream. Validated against real hardware: files stuck for years go through.
- **Frozen-app settings persist** — [`tools/hap_gui.py`](tools/hap_gui.py) reads and writes
  `hap_sync.json` next to `sys.executable` instead of PyInstaller's temporary `_MEIPASS` dir.

### Added (2026-06-12, transfer plan: full visibility + add-only mode)

- **`Only add new files` mode** (GUI checkbox, **off by default**; CLI `--new-only` on `plan`/`sync`).
  The local library is the source of truth, so a normal sync faithfully mirrors it — a "changed"
  file (path already on the HAP but byte size differs, e.g. a re-tag or re-encode) **is** pushed by
  default; no exceptions. The opt-in add-only mode is for the rare case of adding files without
  overwriting anything already there. New engine helper `hap_sync.actionable(scan)` centralizes the
  filter; `scan_map` records the intent so the plan and the transfer stay in sync.
- **Plan now shows everything, grouped and explained.** Output is split into **CHANGED** (with
  `local X vs HAP Y, Δ±Z` per file, so it's obvious whether the audio really differs or it's just
  metadata) and **NEW**, sorted, no longer truncated at 12 lines. The GUI also writes the *complete*
  plan to `hap_plan_<share>.txt` next to the config every analysis, so nothing is ever hidden behind
  a cap. Fixes the "it says 100 files changed and I don't know what they are" confusion.

### Added (2026-06-12, built-in SMB doctor — diagnose & fix Windows access)

- **`tools/smb_doctor.py`** — a shared engine that diagnoses SMB access to the HAP and can repair
  the Windows-side breakage that OS updates keep reintroducing. Two independent concerns, kept
  distinct so users aren't misled:
  - **Authoritative transfer probe** — opens the HAP's anonymous SMB1 share via `pysmb` exactly
    like the transfer does. If it connects, syncing works *regardless* of any Windows SMB setting.
  - **Native-path checks (Windows only)** — `RequireSecuritySignature` (the 24H2/25H2 default that
    blocks the HAP), `EnableInsecureGuestLogons`/`AllowInsecureGuestAuth`, the SMB1 client feature
    (read from the `mrxsmb10` driver, no admin), and **genuinely** broken mapped drives. The last
    is verified by *actively* probing each mapping with `Test-Path` rather than trusting
    `Get-SmbMapping`'s Status field — an idle persistent mapping reports "Disconnected" yet
    reconnects fine, so trusting Status would tell users to delete working drives.
  - **One-click fix** — non-admin fixes (clearing stale mappings) run in the user session; admin
    fixes are bundled into a single self-elevating PowerShell (one UAC prompt). The split matters:
    an elevated process sees a different drive-letter namespace and wouldn't find the user's maps.
- **Wired into both surfaces**: the GUI's **Check** button now shows the full diagnosis and reveals
  a **Fix Windows access** button when there's something to repair ([`tools/hap_gui.py`](tools/hap_gui.py));
  the CLI gains `hap_sync check` (rich report) and `hap_sync check --fix` ([`tools/hap_sync.py`](tools/hap_sync.py)).

### Changed (2026-06-12, Windows SMB hardening troubleshooting)

- Expanded [`docs/04-smb.md`](docs/04-smb.md) with a **"Windows updates keep re-breaking access"**
  section. Each Win10/11 update can silently flip an SMB *client* default and lock you out of the
  anonymous HAP share even though nothing changed on the device. Documents the four knobs with check +
  elevated-PowerShell fix commands — **SMB signing now required by default on Win11 24H2/25H2**
  (`RequireSecuritySignature`, the most recent regression), insecure guest logons
  (`EnableInsecureGuestLogons` / `AllowInsecureGuestAuth`), and the SMB1 client feature — plus the
  **stale persistent-mapping gotcha** (a `Disconnected/Unavailable` mapped drive keeps forcing a bogus
  credential prompt; `net use * /delete /y` then reconnect as guest). Reiterates the two clean escapes:
  flip the device to SMB3 via Special Mode, or use `tools/hap_sync.py` (pysmb, bypasses the Windows SMB
  stack entirely).

### Changed (2026-06-03, UART session prep)

- Expanded [`docs/10-uart-console.md`](docs/10-uart-console.md) into a ready-to-run session guide while
  waiting for the USB-serial adapter:
  - **Re-verified the console pins against the authoritative IC101 pin table (p79): M1 = CSI0_DAT10 (TX),
    M3 = CSI0_DAT11 (RX), UART1 / `ttymxc0` @ 115200** — confirmed correct (the LCD RGB bus uses other
    CSI0_DAT balls in the N/P/R/T/U rows; don't confuse them).
  - **Board-level candidate `CN4008`** — the unqualified TXD/RXD console nets route to connector
    `CN4008` (MAIN schematic p47), which also appears on the MAIN PWB (p40): the likely factory debug
    header. Confirm its pinout empirically.
  - **Disassembly order** to reach the MAIN board (it sits under the FPGA-DSP board).
  - **Dump runbook**: interrupt U-Boot → `cat /proc/mtd` → `dd` each partition off via netcat over
    Ethernet *or* the SMB share; `mtd2` = the JFFS2 rootfs. Receiver (`nc`) confirmed available.

### Added (2026-06-03, hap_sync — a HAP-dedicated FreeFileSync replacement)

- **`tools/hap_sync.py`** — actually transfers music to the HAP and keeps it in sync incrementally
  (copies only new/changed files), over the device's **SMB1** share via **`pysmb`** — so you do
  **not** have to enable the insecure SMB1 client in Windows. Handles the **two-share** layout in one
  run: separate PC folders → `HAP_Internal` and `HAP_External`, configured in a small `hap_sync.json`
  (`tools/hap_sync.json.example` provided; the real one is git-ignored). Auto-skips junk
  (`.ffs_tmp`, `Thumbs.db`, `._*`…) and unsupported formats, preserves `<Artist>/<Album>/`, and offers
  `plan` (dry-run), `sync`, `list`, `wake` (WoL), `check`.
  - **On-disk remote-index cache** so we never re-list tens of thousands of files every run: the
    first run scans the share, then `plan`/`sync` read the cache instantly, and a `sync` folds the
    files it just uploaded into the cache (steady-state = no re-scan). `--refresh` / the `refresh`
    command force a full re-listing. Cache lives in `.hap_sync_cache/` (git-ignored).
  - **Live-tested end-to-end** against the device: anonymous SMB1 connect, full recursive listing
    (67k files), and a verified upload round-trip.
  - Robustness fix discovered in testing: a long SMB1 recursive listing can desync pysmb's session
    (breaking the next write) — `hap_sync` reconnects on any listing error and uploads on a fresh
    connection, which also made the remote listing complete/consistent.

### Added (2026-06-03, HAP companion tool)

- **`tools/hap_companion.py`** — makes any file-copy tool (FreeFileSync, rsync, drag-and-drop)
  HAP-aware, without replacing it. Stdlib only, read-only.
  - `validate <folder>` — pre-flight a music folder: flags **unsupported** codecs/containers, **junk**
    that pollutes the library (`.ffs_tmp`, `.part`, `Thumbs.db`, `._*`…), PCM **over 192 kHz** (the
    Forza PCM-path cap — reads FLAC/WAV headers to check real rates), and album folders **missing
    cover art**.
  - `diff <hdd_browse.db> <folder>` — semantic new-vs-already-on-HAP comparison of a local
    `<Artist>/<Album>/` tree against the device's own SQLite catalog (so you transfer only what's
    actually missing, by content). Validated against a real library (24,404 artist/album pairs).
  - `wake <mac>` (Wake-on-LAN) and `check <ip>` (reachability).
- **Fix:** both `hap_companion.py` and `library_browser.py` now tolerate the non-UTF-8 (latin-1) text
  that exists in some on-device DB rows (e.g. "Zé Roberto"), which previously crashed the SQLite read.

### Added (2026-06-03, library browser tool)

- **`tools/library_browser.py`** — a stdlib-only web browser for a HAP library, reading the
  on-device SQLite catalog (`hdd_browse.db`) directly: artists → albums → tracks, with cover art
  (served from the `PROP78D9` thumbnail BLOB), codec, sample-rate/bit-depth, durations, and search.
  Read-only (DB opened immutable), data never leaves the machine. It's the reference decoder for the
  `FTxx02`/`PROPxxxx` schema documented in `09-disk-layout.md`, and the foundation for a control-app
  library view (the live API can't list HDD content; `downloadByDiff` is blocked — but the SQLite is
  all we need). Validated against a real 77k-track library; it immediately surfaced ~68 orphan
  "tracks" that were actually FreeFileSync `.ffs_tmp` temp files the indexer had picked up.

### Added (2026-06-03, audio path decoded from the Forza driver)

- New [`docs/11-audio-path.md`](docs/11-audio-path.md): the full signal chain, read from the GPL
  `forza_snd_driver` source. The FPGA is an **Altera PCIe device** (`0x1172:0xE001`); the SoC DMA's
  audio into its FIFO. Decoded the two DSPs' actual jobs and mapped them to the app's sound settings:
  **ADSP-21488 SHARC = "HEQ"/DSEE-HX restoration + digital filter** (the "DSEE" toggle),
  **Cirrus CS48L10 = oversampling/SRC** (firmware `4up/2up/nonSRC` ↔ the "Oversampling" setting),
  plus the **DSD-remastering** mode machine (Direct.PCM / Direct.DSD / DSD_ReMaster.PCM). Documented
  the **`/dev/forza` ioctl ABI** — the lever a Phase-4 daemon uses to drive the chain while preserving
  Sony's analog path — and that DSP firmware lives on the rootfs at `/sony/lib/modules/dspfw/`.

### Changed (2026-06-03, repo-wide accuracy + clarity pass)

A full audit of every doc against the 2026-06-02/03 ground truth, to make the repo a reliable
reference for newcomers and specialists alike. Purged the claims that had become false and wired up
the new docs everywhere:

- **README**: named the DSPs (ADSP-21488 SHARC + CS48L10), corrected the status/roadmap (firmware is
  OTA-only — no "format-analyze the blob"; the OS path is UART → NAND dump), reflected that the full
  library DB is now in hand, and **added docs 09/10 to the reading order** (they were missing).
- **Killed the "firmware is downloadable" falsehood** in `07-firmware.md`, `00-overview.md`,
  `CONTRIBUTING.md`, `08-prior-art.md`, and `archive/README.md` — it is OTA-only with no public copy.
- **Removed the last "Tokyo Cabinet = library DB" relics** (`06-hdd-swap.md`, `08-prior-art.md`) and
  the "SHARC part not published" / "NAND not pinned down" hedges (`01-hardware.md`, `02-software-stack.md`):
  rootfs is `/dev/mtdblock2` JFFS2 on NAND (GPMI), SPI-NOR is an M25P32.
- **`04-smb.md`** gained a "Security boundary" section (anonymous read/write confirmed; symlink + HTTP
  traversal blocked; no safe Samba RCE) and the real on-disk share paths.
- **`03-network-api.md`** documents the vestigial `/sony/contentdb/v100` + MusicConnect endpoints.
- **`api-method-catalog.md`** reframes `downloadByDiff` as no-longer-a-blocker (DB obtained off-disk).
- Added dated **correction banners** to the superseded 2026-05 research notes (iOS postmortem,
  mitmproxy, database-service, downloadByDiff deep-dive) pointing forward to the 2026-06 findings.
- **`tools/hap_client.py` doc/bug pass, verified live against the device (2026-06-03):** the paused
  state wire value is **`PAUSED_PLAYBACK`** (not `PAUSED`) — fixed the now-playing CLI so a paused
  device renders correctly; corrected the repeat/shuffle `target` docstrings (canonical `'track'`;
  Spotify is `''`, not `'spotify'`); documented that `getSoundSettings` returns the value in
  `currentValue` (catalog + confirmed the client already reads it).

### Added (2026-06-03, OS acquisition recon + UART console identified)

- **UART serial console pinned down at the SoC** — new doc [`docs/10-uart-console.md`](docs/10-uart-console.md).
  From the IC101 pin-function table (service manual p75–79): the i.MX6 UART1 console (`ttymxc0 @ 115200`)
  is **ball M1 = CSI0_DAT10 (TX)** and **ball M3 = CSI0_DAT11 (RX)**; CSI0_DAT12/13 is the U-COM MCU
  link, CSI0_DAT14/15 the remote-learning link. Boot-mode straps hardwired for NAND. Full shopping
  list, 3.3 V safety rules, and the U-Boot→NAND-dump procedure included.
- **Audio DSPs identified** from the GPL `forza_snd_driver` source (downloaded): **ADSP-21488** SHARC
  (`adsp_21488.c`) + **Cirrus CS48L10** (`cdsp_cs48l10.c`). Updated `01-hardware.md` (were "not published").
- Full session record: [`research/notes/2026-06-03-os-acquisition-recon.md`](research/notes/2026-06-03-os-acquisition-recon.md)
  — firmware confirmed unobtainable publicly (99-agent sweep), GPL bundle fetched, and live-device
  software recon: Samba 3.0.37 anon RW to music shares but **symlink traversal blocked**, lighttpd
  **path traversal blocked**.
- **`/sony/contentdb/v100` REST API: confirmed NOT implemented on 19404R** (GET times out, POST 404
  while the same `:60200` ScalarWebAPI answers) — vestigial like MusicConnect; don't re-chase.
- **Flash layout learned from the GPL kernel** (pre-UART): cmdline `console=ttymxc0,115200
  root=/dev/mtdblock2 … rootfstype=jffs2`; rootfs is **writable JFFS2 on NAND mtd2**; SPI-NOR
  M25P32 (4 MB) holds U-Boot+kernel. Documented in `10-uart-console.md`.

### Added (2026-06-02, direct HDD read — on-disk layout + ground-truth DB schema)

- **First direct read of a HAP-Z1ES internal disk** (pulled, attached over USB, imaged + mounted
  read-only via WSL2). New canonical doc [`docs/09-disk-layout.md`](docs/09-disk-layout.md) and full
  forensic note [`research/notes/2026-06-02-hdd-direct-read-ondisk-findings.md`](research/notes/2026-06-02-hdd-direct-read-ondisk-findings.md).
- **Ground-truth DB schema committed** under [`research/db-schema/`](research/db-schema/) — `.schema`
  dumps of every on-device database (schema only, no library data). Confirms the schema reverse-engineered
  from the APK on 2026-05-25, with real row counts (77 668 tracks on the reference unit) and decoded enums
  (codec `PROP304B`: 49=FLAC/81=MP3/97=AAC/65=ALAC/129=WMA/17=WAV/33=AIFF; `PROP6844`=year; `PROP3047`=seconds).
- **Disk architecture established**: two ext4 partitions — `/data` (3 GB, the SQLite catalog, format
  `ver 14.00`) and `/mnt/internal` (928 GB, music under `storage/<Artist>/<Album>/` + a `db_storage/cover_art`
  cache). Files are `root:root 0700`; the indexer runs as root.

### Changed (2026-06-02, corrections from the disk read)

- **Library metadata store is SQLite, not Tokyo Cabinet** — corrected in `02-software-stack.md` and
  `06-hdd-swap.md`. Tokyo Cabinet is in the GPL bundle but is not the library DB.
- **The HDD holds no rootfs** — only `/data` + `/mnt/internal`. Partially answers Open Question #1 in
  `02-software-stack.md`; the OS lives on internal flash. Audio-path diagram paths corrected
  (`storage/` not `Music/`; `/data/*.db` not `library.tch`).

### Added (2026-05-26, web UI third pass — gear-panel controls, archive, Minimal mode)

- **Gear panel is now a full control surface**, not just a theme picker. New sections:
  - **Display** — Minimal mode toggle (hides the header "HAP-Revival · firmware · active" and the bottom footer for a stripped-down look). Choice persisted in `localStorage`.
  - **Sound** — pill toggles for DSEE (auto/off), DSD remastering (on/off), Gapless (auto/off), Volume normalization (auto/off), Oversampling (precision/normal). Each setting has a plain-language caption directly under it explaining what it actually does, plus a longer hover tooltip on the label. All five round-trip validated against the live device via `audio.setSoundSettings` v1.1.
  - **Playback** — Volume slider (auto-disabled on HAP-Z1ES, enabled on HAP-S1 with the device's min/max/step), Sleep timer dropdown auto-populated from `getSleepTimer` candidate seconds (Off + 10/20/30/40/50/60/90/120 min).
  - **Current track** — Favorite buttons (♥ / — / 👎) using `editContentInfo` with `tagUri:"meta:favorite"`. Auto-disabled when the current source is not an HDD track (Spotify Connect, radio, etc.) because Sony's editContentInfo only works on `audio:track?id=N` URIs.
- **Backend new endpoints** to back the above: `/api/set-sound`, `/api/set-volume`, `/api/mute-toggle`, `/api/set-sleep-timer`, `/api/set-favorite`. `/api/state` now also returns sleep_timer, volume, and favorite_type in the now_playing block. Each sub-fetch is try-wrapped so a partial device failure doesn't blank the whole UI.
- **Live-reload of HTML template** (commit a94d5d7) means editing CSS/JS in `webui.py` no longer needs a server restart — the HTML is re-read from disk on each GET. Cache-Control: no-store + Pragma + Expires so the browser never holds a stale copy. Adding new Python endpoints still needs a server restart since the Python class is loaded once at start.
- **Permanent archive of technical PDFs** under `archive/`:
  - HAP-Z1ES Service Manual (8.3 MB, SHA-256 documented in `archive/README.md`)
  - HAP-S1 Service Manual (10.4 MB)
  - HAP-Z1ES end-user Help Guide (1.3 MB)
  - HAP-S1 end-user Help Guide (1.4 MB)
  Total ~21 MB. Three docs that previously cited the now-dead `riverparkinc.com` mirror updated to point at the local archive. Documents legal stance + manual-download procedure for contributors who want to add more (e.g. the Reference Manual, Quick Start, RM-ANU183 remote manual).

### Added (2026-05-25, web UI second pass — themes, ambient bg, adaptive contrast)

Building on the first web UI commit (b7e3eb4), a focused polish round driven by live user feedback during the session:

- **Ambient cover background** (Apple Music / Tidal style). The current cover image fills the viewport, blurred to 60 px and saturated 1.8×, behind the now-playing card. Cards switch to frosted-glass over it. The cover element itself gets a soft glow tinted by the HAP-extracted dominant color.
- **Bug fix: `body` was opaque**, hiding `body::before` (the ambient layer) completely. Split the `html, body` shorthand so `html` keeps the dark fallback and `body` becomes transparent. The ambient mode actually shows up now — earlier "ambient" screenshots were pure black because of this.
- **Theme switcher** (⚙ icon top-right). Four modes:
  - **Ambient cover** (default)
  - **Solid (from cover)** — flat color = the RGB the HAP itself extracts from the cover
  - **Dark** — the original
  - **Custom** — native HTML5 color picker, choice persisted via `localStorage`
  Active selection visually highlighted (accent-tinted row + border). Selected theme + custom color survive reload (per-browser).
- **Adaptive text contrast**: when the background is bright (perceptual luminance > 0.6 via Rec. 601 weights), the UI switches to dark text + light frosted-glass cards. Auto-flipping `--fg`, `--muted`, `--card-bg`, `--hover`, and `--text-shadow` CSS variables. Header + footer also get an adaptive `text-shadow` for the worst-case mid-luminance covers. Recomputed both on cover change and on theme change.
- **`pausePlayingContent` is a TOGGLE, not just pause** — discovered when the user reported play not working after pause. The "naming-true" `pause()` / `resume()` library methods now check state first; the web UI uses `/api/toggle-playback` (direct toggle, single round-trip).
- **`setPowerStatus({status:"play"})` does NOT reliably resume Spotify Connect playback** — only the `pausePlayingContent` toggle does. The library's `resume()` documents this and uses the toggle.
- **Web UI live-reload**: the HTML template is re-read from the source file on every request via sentinel comments. Means iterating on CSS / JS no longer requires bouncing the server — F5 in the browser is enough. Cache-Control no-store + Pragma no-cache + Expires 0 on the HTML response so the browser cannot cache between reloads.
- **Server-side initial-cover URL**: the `--cover-url` CSS variable is now pre-populated server-side from the current `getPlayingContentInfo`, so the ambient background renders on the very first paint instead of waiting for the JS refresh tick.

### Added (2026-05-25, +5 ✅ set\* methods round-trip-validated; favorites unlocked)

- **5 setter methods** live-validated via round-trip ("set to current value = no net change"):
  - `audio.setSoundSettings` v1.1 `[{settings:[{target,value}]}]`
  - `avContent.setBufferTime` v1.0 `[{bufferTimeSec:N}]`
  - `avContent.setRepeatType` v1.0 `[{target,type}]`
  - `avContent.setShuffleType` v1.0 `[{target,type}]`
  - `system.setSleepTimer` v1.0 `[{status,sleepTimerSec}]`
- **Favorites unlocked** via `editContentInfo` v1.0 with `{method:"editTrackInfo", target:[{uri,tagUri:"meta:favorite",value:"favorite"|"dislike"|"normal"}]}` — Sony's `setFavorite` does not exist as a separate call.
- **Per-source repeat/shuffle**: `target:"track"` for HDD/USB, `target:""` for Spotify (Sony's canonical values from the APK).
- **`x-hap-device-id` header now sent by default** on every `hap_client.py` request (matching Sony's Android client; optional in practice but good hygiene).
- New library methods: `set_sound_setting`, `set_repeat`, `set_shuffle`, `set_buffer_time`, `set_sleep_timer`, `set_volume`, `mute_toggle`, `set_favorite`, `toggle_playback`.

### Added (2026-05-25, /sony/database service + on-device DB schema decoded + recfile transport)

- **`/sony/database` service confirmed live**. `checkSameDatabase` v1.0 returns `{isSameVersion, isSameName, type}` with the correct `database:<short_uuid>?dbType=hdd&...` URI.
- **`downloadByDiff` v1.0**: same shape; live still returns empty `location` even with Sony's exact request (header + `originalVersion=-1` + preflight `checkSameDatabase`). Pending mitmproxy capture of Sony's Android client during a real sync.
- **Complete on-device DB schema decoded** from `assets/demo_browse.db` (79 KB SQLite shipped in the Android APK, never publicly extracted before). 11 tables — `FT0000` (root), `FT0002` (tracks, 37+ columns), `FT000A` (albums with thumbnail BLOB), `FT4502` (genres), `FT5202` (artists), `FT6F02` (composers), `FT7002` (lyricists), `FTF003` (playlists), `FTF004` (playlist contents). ~60 PROP-code hex constants decoded (PROP3601 = id, PROP304B = codec, PROP3048 = sample rate, PROP10DE = bit width, PROP6844 = release date, etc.). Full breakdown in [`research/notes/2026-05-25-database-service-and-db-schema.md`](research/notes/2026-05-25-database-service-and-db-schema.md).
- **`recfile` generic transport mechanism** discovered. Some JSON-RPC methods (`getPlaylistInfo`, `downloadByDiff`, probably others) return `{location: "http://<ip>:60200/sony/avContent/recfile/requestN.data"}` instead of the payload itself. A plain HTTP GET on that URL returns the binary/text payload as `application/x-www-form-urlencoded` data (e.g. `newVersion=9&types=2&ids=-1&positions=...`). Confirmed via `getPlaylistInfo` on a freshly-created playlist.
- **APK deep-dive #2** (research/notes/2026-05-25-apk-deep-dive-downloadbydiff.md, ~600 lines): full Java code paths for `downloadByDiff`, `getRichMetaInfo`, `editContentInfo` dispatch, the polling state machine, etc.

### Added (2026-05-25, first working client + web UI)

- **`tools/hap_client.py`** — clean Python client library wrapping every confirmed API method. Stdlib-only (no `requests`). Typed dataclasses (`SystemInfo`, `NowPlaying`, `SoundSettings`, `SleepTimer`). Doubles as a CLI: `python tools/hap_client.py <ip> now-playing | pause | resume | seek N | play-track N | system | sound | sleep-timer | next | prev`.
- **`tools/webui.py`** — minimal stdlib HTTP server (no Flask, no aiohttp) serving an HTML5 single-page control panel at `http://localhost:8080`. Features: now-playing with cover art, dynamic accent color from the device's RGB hint, seek by clicking the progress bar, pause/resume/next/previous/standby buttons, live sound-settings display, 3-second polling matching Sony's own app. The first working third-party HAP control web app ever shipped.
- Live-validated against firmware 19404R: end-to-end functional with Spotify Connect playback (cover art from Spotify CDN renders correctly).

### Research (2026-05-25, post-APK-decompile)

- **Decompiled `com.sony.HAP.HDDAudioRemote` v4.3.1** (12.88 MB APK from APKCombo). First public decompile of this client. Full findings: `research/notes/2026-05-25-apk-decompile-findings.md` plus a deep-dive at `research/notes/2026-05-25-apk-deep-dive-downloadbydiff.md` (~1100 lines combined). Toolchain: OpenJDK 21 (winget) + jadx 1.5.5.
- **Live-validated 3 new methods** with Sony shapes:
  - `system.setPowerStatus v1.1` `[{status:"play"}]` ✅ resumes playback (wake + play, 4th status value)
  - `avContent.setPlayContent v1.1` `[{positionSec:N}]` ✅ seek-within-track (NOT a separate `seekStreamingContent`)
  - `avContent.createPlayingListAndQuickPlay v1.0` `[{uri,listIndex,listCount,playbackControlMode}]` ✅ THE HDD playback start primitive (Sony's UI calls this when you tap a track)
- **Discovered new service `/sony/database`** (live-confirmed exists, responds to `checkSameDatabase`). Sony uses it to sync the entire on-device music DB to a local SQLite mirror via `checkSameDatabase` + `downloadByDiff`. Highest-leverage target for unlocking HDD content browsing.
- **APK reveals 15+ new methods** Sony's client uses that we hadn't catalogued: `getSleepTimer`/`setSleepTimer`, `getSupportedFileType`, `createPlaylist`/`updatePlaylist`/`deletePlaylist`/`getPlaylistInfo`, `getStorageInformation`, `getBufferTime`/`setBufferTime`, `setAudioInput`, `getRichMetaInfo`, `editContentInfo`, `registerDevice`, `setRepeatType`/`getRepeatType`, `setShuffleType`/`getShuffleType`.
- **APK reveals 🟡 method shapes** for all previously-unknown methods. Notable corrections to our prior guesses:
  - `deleteContent.uri` is a JSON **array** of URI strings, not a scalar.
  - Pause/next/previous need `params:[{}]` (empty object inside array), not `[]`.
  - `scanPlayingContent` is FF/REW with `{direction:"fwd"|"bwd"}` — NOT scrub-to-position.
  - `getContentList v1.3` is for **internet radio (netService) only** — HDD content is browsed via the `database` service's local SQLite cache, not via getContentList.
- **Confirmed: HAP has no WebSocket notifications.** Sony's app uses 4 polling threads at 5 s cadence. Our client design should do the same — stop investigating push mechanisms.
- **Corrections vs APK agent's report** (live tested 2026-05-25):
  - `/sony/<service>` IS required on firmware 19404R (agent claimed otherwise — wrong).
  - `x-hap-device-id` header is optional (agent claimed mandatory — wrong, our calls work without).
  - `/turnOn`, `/turnOff` plain HTTP endpoints return 404 on firmware 19404R (agent claimed they exist — wrong on this firmware; possibly HAP-S1 only or removed).
- **Side effect documented**: my own probing during the session accidentally paused user's music (the 🟡 setPlayContent calls returned `[1, "Any"]` errors but had side effects). Recovered via `setPowerStatus({status:"play"})`. Lesson: **`[1, "Any"]` does not mean "no effect"** — some methods partially succeed even when reporting an error. Test only with disposable content going forward.

### Research (2026-05-25, post-fuzz)

- **First `tools/api-fuzzer.py` run on a live HAP-Z1ES (firmware 19404R)** — 53 method+service candidates tested, up to 8 versions each. **24 methods confirmed to exist** on the device (up from 10 previously known). Output: `research/captures/fuzz-192_168_1_28-20260525T184419Z.json`.
- **New methods discovered to exist** (parameters TBD): `system.setPowerStatus` v1.1, `audio.setAudioMute` v1.1, `avContent.setPlayContent` v1.1 (was Unsupported at v1.0), `avContent.stopPlayingContent` v1.0, `avContent.scanPlayingContent` v1.0, `avContent.getContentInfo` v1.1, `avContent.getContentList` v1.3 (was Unsupported at 1.0/1.2), `avContent.deleteContent` v1.1 (flagged dangerous), `guide.getServiceProtocols` v1.0.
- **New methods confirmed working with empty params**: `audio.setSoundSettings` v1.1 and `avContent.setPlaybackModeSettings` v1.0 — both reply with empty result (noop with no params).
- **New error codes documented**: code `1 "Any"` (generic / invalid value) and code `3 "illegal Argument"` (missing/wrong parameter), in addition to the previously known `5/12/14`. Gives finer-grained method-existence detection.
- **Settled negatives**: HAP cannot self-update via API (no `getSWUpdateInfo`/`actSWUpdate`), seek within track not exposed (no `seekStreamingContent`), favorites and Bluetooth not exposed.

### Research (2026-05-25, initial reconnaissance)

- **Network surface mapped** on a live HAP-Z1ES (firmware 19404R, 2026-05-25):
  - Confirmed SSDP banner `Linux/3.0 UPnP/1.0 Sony-HAP/1.0`
  - Confirmed open TCP ports: 139, 445, **60100** (lighttpd / UPnP description), **60200** (ScalarWebAPI JSON-RPC)
  - Confirmed alternate Sony API ports (10000, 54480, 52323) are **closed** on HAP — settled the python-songpal#29 ambiguity
  - Captured full `/hap.xml` device descriptor with `MusicConnect:1` + `ScalarWebAPI:1` service entries
  - Verified working methods: `system.getSystemInformation` v1.2, `system.getPowerStatus` v1.1, `audio.getVolumeInformation` v1.1, `audio.getSoundSettings` v1.1, `avContent.getPlayingContentInfo` v1.2, `avContent.pausePlayingContent` v1.0
- **Hardware confirmed**: SoC is NXP **i.MX6 Dual** (`MCIMX6D5EYM10AC`, Cortex-A9 dual @ 1 GHz) per Sony service manual `IC101` part number. Earlier i.MX53 inference (Cortex-A8 single) corrected.
- **Software stack confirmed** from Sony's [oss.sony.net GPL release](https://oss.sony.net/Products/Linux/Audio/HAP-S1.html):
  - OpenWrt trunk r35385 base
  - Linux 3.0.35, U-Boot 2012.04.01
  - Samba 3.0.37, Dropbear 2012.55, lighttpd 1.4.35
  - GStreamer 0.10.36 + Freescale plugins
  - **Custom `forza_snd_driver` kernel module** (Sony codename "forza") — source available in GPL bundle
  - **Control daemon is Python 2.7 + web.py 0.37 + lighttpd**, not C
  - Front-panel UI is DirectFB 1.4.17 (no X11)
- **Service DIAG menu entry corrected**: requires HOME + BACK held, then PLAY then POWER (4-key combo, not 2).
- **HDD swap recipe documented**: sector-clone via KURO-DACHI/CLONE/U3 preserves DB; Crucial MX500 / KIOXIA recommended; avoid Samsung 860/870 EVO.
- **Exhaustive prior-art inventory completed** — entire public corpus consists of one Swift app (HAPxFer), one 10-line gist (frazei), one Python file organizer (music-organizer), one stuck issue (python-songpal#29), Sony's GPL drop, a Crestron module, and the JP hardware-mod blogs. See [`docs/08-prior-art.md`](docs/08-prior-art.md).

### Added

- Initial repository structure, README, license split (MIT code / CC-BY-SA 4.0 docs), CONTRIBUTING, CHANGELOG.
- Documentation set (`docs/00–08`) covering overview, hardware, software stack, network API, SMB, DIAG modes, HDD swap, firmware, and prior art.
- Tools: `tools/discover.py` (SSDP + API probe), `tools/api-fuzzer.py` (method×version brute force), `tools/apk-decompile.md` (recipe).
- Issue templates for API method discoveries, hardware findings, and bug reports.
- Living API method catalog at [`research/api-method-catalog.md`](research/api-method-catalog.md).
