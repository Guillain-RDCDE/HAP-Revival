# 2026-06-03 — OS acquisition: firmware is unobtainable publicly, live-device software recon, decision to go UART

Goal of the session: get the device's **OS / rootfs** (Python control daemon, indexer, GStreamer
elements) now that the 2026-06-02 disk read proved the HDD holds **no rootfs** (only `/data` +
`/mnt/internal`; the OS lives on internal NAND). Summary: the firmware blob is not obtainable
anywhere public, the easy software vectors against the live device are blocked, and the reliable
remaining path is a **UART serial console** (see [`docs/10-uart-console.md`](../../docs/10-uart-console.md)).

## 1. Firmware blob: confirmed unobtainable publicly (deep research, 99 agents)

A 99-agent adversarially-verified web sweep (EN/JP/CN, archive.org, GitHub) reached a firm
conclusion: **no public copy of any HAP-Z1ES/HAP-S1 firmware version exists** — not 19404R, not
any older one. The firmware is genuinely OTA-only; the device fetches it itself during a
"Network Update" and Sony never exposes a direct file link or the update-server URL
(`info.update.sony.net`) on any regional page (UK 00017123, Asia 00017124, Canada 00017125,
Japan, China `service.sony.com.cn/download/firm/00002752`).

**Why nobody ever dumped it:** the HDD-swap modding scene never needed to. The OS is on internal
NAND, so a blank replacement drive re-initializes **on-device** via factory-reset (~5 min), which
restores firmware + factory-bundled DSD music from NAND. Confirmed by multiple JP blogs
(nonroom.com, emuzu cocolog: *"初期化してもファームは最新。HDDとは別の場所に格納されている"* —
"firmware stays current after init; stored separately from the HDD").

Consequence: to get the firmware/rootfs we must extract it **from the device itself** (NAND dump
via a root shell), or capture+unpack the OTA blob. There is no shortcut download.

## 2. What IS freely downloadable — the GPL source bundle (fetched)

Verified live (HTTP 200, anonymous) and **downloaded** to `D:\HAPZ1ES\gpl\`:

- `https://prodgpl.blob.core.windows.net/download/Audio/HAP-S1,%20HAP-Z1ES/forza_snd_driver.tgz`
  (39 005 B, md5 `902fc90d2083e0a6f84db13f95708e01`) — the Sony-custom audio driver source.
- `.../linux-3.0.35.tar.xz` (63.8 MB) and `.../linux-3.0.35.patch.gz` (6.1 MB) — kernel + Sony patch.
- (Path has a literal space+comma → `%20` required.)

**New hardware ground truth from `forza_snd_driver.tgz`** — the audio DSPs, previously "not
published" in [`docs/01-hardware.md`](../../docs/01-hardware.md), are now known from the driver source files:

- **`adsp_21488.c`** → the SHARC DSP is an **Analog Devices ADSP-21488**.
- **`cdsp_cs48l10.c`** → there is a **second DSP, a Cirrus Logic CS48L10** ("cdsp").
- Plus `forza_core.c`, `forza_pcm.c`, `forza_audio_controller.c`, `forza_lib.c`, `forza_hwlow.c`,
  `export/forza_if.h` — the full FPGA/DSP/DAC control path in GPLv2 C (Copyright 2013,2014 Sony).

**`.SonyAP` unpacker for later:** [`ma1co/fwtool.py`](https://github.com/ma1co/fwtool.py) — the
Sony-camera firmware tool; same FDAT/container family, likely unpacks the HAP blob *if* obtained.

## 3. Live-device software recon (user's own unit, authorized)

Device reachable at `192.168.1.28`: **445/139 open** (Samba), **60100/60200 open** (lighttpd +
ScalarWebAPI), **22 closed** (dropbear present in firmware but not started).

### 3a. Samba — anonymous read/write, but no rootfs escape

`nmap` + `smbclient` (forced SMB1, the device speaks **only NT LM 0.12 / SMBv1**):

- **Samba 3.0.37**, message signing disabled, guest/anonymous access.
- Shares with **anonymous READ/WRITE**:
  - `HAP_Internal` → `/mnt/internal/internal`
  - `HAP_External` → `/mnt/external_fuse` (the USB drive, via FUSE)
  - `IPC$` → `/tmp`
- **Symlink/wide-links traversal to the rootfs: BLOCKED.** Every `symlink` create (absolute `/`
  and relative `../../../`, on both ext4 and FUSE shares) returns `NT_STATUS_ACCESS_DENIED`. Sony
  hardened Samba against the classic `samba_symlink_traversal`. So Samba gives filesystem write to
  the music areas but **no path to the rootfs**.
- No reliable RCE: Samba 3.0.37 is **below** the SambaCry (CVE-2017-7494, needs ≥3.5.0) and
  `usermap_script` (CVE-2007-2447, ≤3.0.25) ranges; remaining CVEs (e.g. CVE-2012-1182) have no
  public **ARM** exploit and risk crashing the device. Not pursued.

> Useful byproduct: anonymous SMB write to `HAP_Internal`/`HAP_External` is confirmed — relevant
> to a future direct-to-share bulk music loader.

### 3b. HTTP (lighttpd :60100) — traversal blocked, but a new API surface found

- Path traversal to `/etc/passwd` on `:60100` and on the `:60200` `recfile` endpoint: **all 404**,
  including raw `--path-as-is` and `%2e%2f` encodings. lighttpd 1.4.35 normalizes; no file read.
- Served endpoints: `/hap.xml` (UPnP desc, UDN `uuid:00000000-0000-1010-8000-104FA86F4B84`),
  `/HAP_app.html` (272 KB embedded admin UI), `/MusicConnect_SCPD.xml`, icons.
- **NEW: a REST-style content API referenced by the admin UI** (distinct from the JSON-RPC
  ScalarWebAPI). Endpoints seen in `HAP_app.html`:
  - `/sony/contentdb/v100/audio/{albums,artists,genres,tracks,playlists}` (with
    `?albumid=/artistid=/genreid=/offset=` query params)
  - `/sony/contentdb/v100/services/{directory,favorite,sensme}`
  - `/sony/contentplayer/v100/{operation,playinginfo,playqueue/tracks,powerstate}`
  - `/sony/hap?target=screen`, `/HAP_Internal/anap/capture`
  - Naive anonymous GETs returned empty bodies — needs proper probing (method/headers/auth, or it
    may be an internal SPA route). **Potentially the cleanest path to the library for a control
    app** (the original `downloadByDiff` goal). Tracked for follow-up; add to the API catalog.

## 4. Decision

Getting the rootfs **without opening the box** is not achievable via the safe/easy software
vectors (Samba symlink blocked, HTTP traversal blocked, no safe Samba RCE). The reliable route is
a **UART serial console** → interrupt U-Boot → root shell → `dd` the NAND / read the live rootfs.
This is also the repo's long-standing flagged "highest-leverage hardware opportunity." User opted
to open the box. Full plan + manual references in
[`docs/10-uart-console.md`](../../docs/10-uart-console.md).

## Open follow-ups

- Properly characterize the `/sony/contentdb/v100` API (verb, headers, auth) — may unblock the
  library browser for the control app independently of any rootfs work.
- Confirm `dropbear` can be started post-shell to make NAND dumps repeatable over the network.
- The `.SonyAP` container format remains undocumented (fwtool.py is the candidate tool).
