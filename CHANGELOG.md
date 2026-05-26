# Changelog

All notable changes to HAP-Revival will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once we ship a versioned release.

## [Unreleased]

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
