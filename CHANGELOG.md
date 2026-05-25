# Changelog

All notable changes to HAP-Revival will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once we ship a versioned release.

## [Unreleased]

### Research (2026-05-25, post-APK-decompile)

- **Decompiled `com.sony.HAP.HDDAudioRemote` v4.3.1** (12.88 MB APK from APKCombo). First public decompile of this client. Full findings: `research/notes/2026-05-25-apk-decompile-findings.md` (370 lines). Toolchain: OpenJDK 21 (winget) + jadx 1.5.5.
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
