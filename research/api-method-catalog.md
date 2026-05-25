# API Method Catalog (living document)

The current state of mapping for the Sony HAP-Z1ES / HAP-S1 ScalarWebAPI on port 60200. Updated as new methods are discovered.

**Last update**: 2026-05-25 (post-APK-decompile + live validation)
**Firmware tested against**: 19404R
**Device tested**: HAP-Z1ES (the canonical reference unit)
**Methods confirmed by live test**: see ✅ rows below
**Methods extracted from APK (Sony Android HDDAudioRemote 4.3.1)**: see [APK findings note](notes/2026-05-25-apk-decompile-findings.md)
**Endpoint base URL**: `http://<ip>:60200/sony/<service>` — **the `/sony/` prefix IS required on firmware 19404R**. The APK decompile report initially suggested otherwise; that interpretation was wrong (confirmed by live test on 2026-05-25). `POST /avContent` (no prefix) returns 404.
**Headers**: `Content-Type: application/json` is required. `x-hap-device-id: <uuid>` is sent by Sony's Android client on every call but appears to be **optional** — successful calls observed without it.

## Critical correction to the APK agent's report

The APK decompile agent claimed:
- `/avContent` is the endpoint, not `/sony/avContent` → **WRONG** (live: `/avContent` → 404)
- `x-hap-device-id` is mandatory → **WRONG** (live: optional)
- Plain HTTP `/turnOn`, `/turnOff`, `/turnOn?type=replay` exist → **WRONG** on firmware 19404R (404)

Likely explanation: the agent read `httpHost = "http://<ip>:60200/"` and assumed the per-service suffix constants were `"avContent"` etc.; it did not verify the actual `API_SERVICES_<x>` constant values, which presumably hold `"sony/avContent"` or similar. The lesson: **never trust APK-derived URLs without a 200-response test**.

## New service: `database` (live-confirmed 2026-05-25)

`POST /sony/database` is reachable. Responds to `checkSameDatabase` with `[3, "illegal Argument"]` when called with empty params — confirms the method+service exist. Full shape per APK:

```json
{"method":"checkSameDatabase","params":[{"uri":"database:<short_uuid>?dbType=hdd&dbSerial=<n>&originalVersion=<n>"}],"id":1,"version":"1.0"}
```

The `<short_uuid>` is the device UDN minus the `uuid:` prefix. **This service is the path to a full library DB export** via the `downloadByDiff` method. High-value target for future investigation.

## How to read this catalog

Each method row shows:

- **Service**: `system` / `audio` / `avContent` / `guide`
- **Method**: the `method` field in the JSON-RPC request
- **Working version**: the value of `"version"` that the device accepts. Other versions return `error: [14, "Unsupported Version"]`.
- **Status**: ✅ confirmed working / ⚠️ exists but parameters unclear / ❌ confirmed not implemented / ❓ untested
- **Params shape**: the `params` array structure
- **Notes**: anything important

## Service: `system`

| Method | Working version | Status | Params | Notes |
|---|---|---|---|---|
| `getSystemInformation` | **1.2** | ✅ | `[]` | Returns model, MAC, firmware version, generation, cid, language, name |
| `getPowerStatus` | **1.1** | ✅ | `[]` | Returns `{status: "active" \| "standby", standbyDetail: ""}` |
| `setPowerStatus` | **1.1** | ✅ | `[{status: "active"\|"off"\|"play"\|"standby"}]` | **LIVE-CONFIRMED 2026-05-25** with `{status:"play"}` (wakes + resumes playback). Sony's 4 values: `"active"` (on, no playback), `"off"` (power off, with `standbyDetail:""`), `"play"` (on + start/resume playback), `"standby"` (with `standbyDetail:"databaseReady"` for DB-readable standby). |
| `getInterfaceInformation` | 1.0 | ✅ | `[]` | Returns `{productName: "HAP", modelName: "HAP-Z1ES", productCategory: "audioServer", interfaceVersion: "1.0.0"}` |
| `getNetworkSettings` | n/a | ❌ | — | `No Such Method` at all versions |
| `getCurrentTime` | n/a | ❌ | — | `No Such Method` at all versions |
| `getStorageList` | 1.0 | ✅ | `[]` | Returns empty `[]` — needs USB device inserted to populate? Untested with USB attached |
| `getVersions` | 1.0 | ✅ | `[]` | Returns empty array — introspection neutered |
| `getMethodTypes` | 1.0 | ✅ | `["<ver>"]` | Returns empty `results` — introspection neutered |

### Confirmed NOT implemented on `system`

`setNetworkSettings`, `getCurrentTime`, `setCurrentTime`, `getDeviceMode`, `setDeviceMode`, `getSWUpdateInfo`, `actSWUpdate`, `getRemoteControllerInfo`, `getWuTangInfo`, `getLEDIndicatorStatus`, `setLEDIndicatorStatus`, `getColorKeysLayout` — all `[12, "No Such Method"]`.

**Notable absence**: `getSWUpdateInfo` / `actSWUpdate` are missing → HAP cannot self-update via API. Firmware updates go through the device UI only, fetching from Sony's servers.

## Service: `audio`

| Method | Working version | Status | Params | Notes |
|---|---|---|---|---|
| `getVolumeInformation` | **1.1** | ✅ | `[]` | On HAP-Z1ES returns `minVolume: -1, target: "", mute: "toggle", volume: -1, step: 1, maxVolume: -1` — HAP-Z1ES has no internal amp so volume values are -1 (not applicable). HAP-S1 should return real values. |
| `setAudioVolume` | **1.0** | 🟡 | `[{volume: "<n>"}]` per APK | Confirmed shape from APK. On HAP-Z1ES volume is meaningless (no amp); test on HAP-S1. |
| `setAudioMute` | **1.1** | 🟡 | `[{mute: "on"\|"off"\|"toggle"}]` per APK | APK shows Sony **forces `"toggle"` on HAP-Z1ES** (modelType==2) regardless of requested state — implementation quirk. |
| `getSoundSettings` | **1.1** | ✅ | `[{target: ""}]` | Returns the proprietary audio toggles: `dsee` (auto/off), `dsdRemastering` (on/off), `gaplessPlayback` (auto/off), `volumeNormalization` (auto/off), `oversampling` (precision/normal) |
| `setSoundSettings` | **1.1** | ✅ | `[{settings: [{target: "<target>", value: "<value>"}]}]` | **Confirmed working** by fuzzer (returned `{result: []}` with empty params — server accepted noop). Targets: `dsee`, `dsdRemastering`, `gaplessPlayback`, `volumeNormalization`, `oversampling`. Use the candidate values returned by `getSoundSettings`. |
| `getVersions` | 1.0 | ✅ | `[]` | Empty (neutered) |
| `getMethodTypes` | 1.0 | ✅ | `["<ver>"]` | Empty (neutered) |

### Confirmed NOT implemented on `audio`

`getSpeakerSettings`, `setSpeakerSettings`, `getCustomEqualizerSettings`, `setCustomEqualizerSettings`, `getAudioOutputs` — all `[12, "No Such Method"]`.

## Service: `avContent`

| Method | Working version | Status | Params | Notes |
|---|---|---|---|---|
| `getPlayingContentInfo` | **1.2** | ✅ | `[]` | The gold method. Returns title, artist, album, codec, bitrate, frequency, position, duration, URIs, coverArtUrl, RGB background color. See [`docs/03-network-api.md`](../docs/03-network-api.md) for full response shape. |
| `pausePlayingContent` | **1.0** | 🟡 | `[{}]` per APK | APK shows empty object `[{}]` (NOT empty array `[]`). The `[1, "Any"]` we saw earlier was because we sent `[]`. Untested with `[{}]` yet — should ✅ on next pass. |
| `stopPlayingContent` | **1.0** | 🟡 | `[{}]` | Sony's app never calls this; method exists on device. Try `[{}]` first. |
| `setPlayNextContent` | **1.0** | 🟡 | `[{}]` per APK | APK confirms empty object. Should ✅ on retest. |
| `setPlayPreviousContent` | **1.0** | 🟡 | `[{}]` per APK | Same as above. |
| `setPlayContent` | **1.1** | ✅ | 3 shapes — see notes | **LIVE-CONFIRMED 2026-05-25**: `[{positionSec: N}]` (seek within current track, the `+0.01` jitter from Sony's code is to force re-trigger). Two other shapes from APK (UNTESTED live): `[{listIndex: N}]` (start track at queue position N) and `[{uri: "netService:audio?serviceName=X&id=Y", playlistName: "..."}]` (radio/TuneIn). No `{uri}` for HDD content — use `createPlayingListAndQuickPlay` instead. |
| `createPlayingListAndQuickPlay` | **1.0** | ✅ | `[{uri: "audio:track?id=N", listIndex: 0, listCount: 1, playbackControlMode: "folder"}]` | **LIVE-CONFIRMED 2026-05-25**. THE primary HDD playback primitive. Builds a play queue and starts playback. Returns `{playbackControlMode, uri: "audio:playinglist?id=<new-id>"}` — note the new playinglist id (in our test: 70, previous was 69). |
| `scanPlayingContent` | **1.0** | 🟡 | `[{direction: "fwd"\|"bwd"}]` per APK | **Press-and-hold fast-forward / rewind** (NOT scrub-to-position — that's `setPlayContent + positionSec`). The device accelerates playback rate while called. Untested live with this shape. |
| `getContentInfo` | **1.1** | ✅ | `[{uri: "audio:track?id=N"}]` | **CONFIRMED 2026-05-25**: returns `{title, coverArtUrl, backgroundColorR/G/B/A}` (a *subset* of `getPlayingContentInfo` — no artist/album/codec/duration). Album URIs `audio:album?id=N` return `[1, "Any"]` — only track URIs work for this method. The reduced metadata set suggests there's a separate "full info" call we haven't found yet. |
| `getContentList` | **1.3** | 🟡 | `[{uri: "netService:audio?serviceName=X[&path=Y]", scope: "directory"\|"favorite"\|"search"\|"connected"\|"unconfirmed"\|"unconnected", stIdx: 0, cnt: 100, finish: false, search?: {word: "..."}}]` | **APK reveals**: this method is for **internet radio / netService browsing only** (TuneIn/vTuner). For HDD content (`audio:track`, `audio:album`), Sony's app **does not use this method** — it browses via the local SQLite cache it sync'd via the `database` service's `downloadByDiff`. That's why all our `audio:album` shapes failed: wrong category of URI entirely. Untested live with the netService shape. |
| `deleteContent` | **1.1** | 🟡 | `[{uri: ["audio:track?id=N", "audio:track?id=M", ...]}]` per APK | **CORRECTED**: `uri` is a JSON ARRAY of URI strings (bulk delete), not a scalar. Use `audio:track?id=N` or `audio:folder?id=N` (folder for bulk dir delete). **DANGEROUS** — destroys library content. Test with disposable test track + backup. |
| `getSourceList` | 1.0 | ✅ but empty | `[{scheme: "<scheme>"}]` | Returns empty result with empty params. Needs the right scheme. Try `"storage"`, `"audio"`, `"radio"`, `"hap"`. |
| `getSchemeList` | 1.0 | ✅ but empty | `[]` | Returns empty result. |
| `getCurrentExternalTerminalsStatus` | 1.0 | ✅ | `[]` | Returns empty array. |
| `getPlaybackModeSettings` | 1.0 | ✅ | `[{target: ""}]` | Returned empty result. |
| `setPlaybackModeSettings` | **1.0** | ✅ | `[{settings: [{target: "<x>", value: "<y>"}]}]` | **NEW: confirmed working at v1.0** (empty params returned `{result: []}`). Likely controls shuffle/repeat. |
| `getVersions` | 1.0 | ✅ | `[]` | Empty (neutered) |
| `getMethodTypes` | 1.0 | ✅ | `["<ver>"]` | Empty (neutered) |

### Confirmed NOT implemented on `avContent`

`seekStreamingContent`, `getContentCount`, `setActiveTerminal`, `getSupportedPlaybackFunction`, `getAvailablePlaybackFunction`, `getBluetoothSettings`, `setBluetoothSettings`, `getFavoriteList`, `setFavoriteContent`, `getApplicationStatusList` — all `[12, "No Such Method"]`.

**Notable absences**:
- `seekStreamingContent` → solved by APK: seek is actually done by re-calling `setPlayContent` with **only** `positionSec` (plus a tiny `+0.01` jitter Sony adds to force re-trigger). No separate seek method.
- `getFavoriteList` / `setFavoriteContent` → favorites management is via `editContentInfo` per APK (with `method: "editFavorite"` or similar dispatch). `getPlayingContentInfo` returns `favoriteType: "normal"` showing favorites exist conceptually.
- `getBluetoothSettings` → BlueZ is in firmware (per GPL bundle), but BT receiver/transmitter is front-panel only — no API surface.
- `stopPlayingContent` → the official Sony app never uses it. Probably exists only as a historical leftover. Pause + standby is the documented Sony way to stop.

## Service: `guide`

| Method | Working version | Status | Params | Notes |
|---|---|---|---|---|
| `getVersions` | 1.0 | ✅ but empty | `[]` | Returns `{result: []}` — introspection is intentionally neutered |
| `getMethodTypes` | 1.0 | ✅ but empty | `["<version>"]` | Returns `{results: []}` — same |
| `getServiceProtocols` | **1.0** | 🟡 | unknown | Exists; `[5, "illegal Request"]` with empty params. Should return supported transports (xhrpost, websocket). |
| `getSupportedApiInfo` | n/a | ❌ | — | `No Such Method` — confirms [python-songpal#29](https://github.com/rytilahti/python-songpal/issues/29) finding. HAP family deliberately does not expose this. |
| `switchNotifications` | n/a | ❌ | — | `No Such Method` on this service. Real-time notifications may be exposed on a per-service endpoint instead (e.g. `/sony/avContent` with method `switchNotifications`). To investigate. |

**Note**: `switchNotifications` not being on `/sony/guide` is a clue that the HAP notification flow differs from cousin Sony devices. Try POSTing `switchNotifications` to `/sony/avContent` and `/sony/audio` directly — that's the python-songpal pattern.

## Notification methods (WebSocket — not yet verified)

Sony's [official examples](https://github.com/sonydevworld/audio_control_api_examples) document these notification subscriptions for real-time updates. We have NOT yet verified which work on the HAP. Pending:

- `notifyPowerStatus`
- `notifyVolumeInformation`
- `notifyPlayingContentInfo`
- `notifySettingsUpdate`
- `notifySWUpdateInfo`
- `notifyExternalTerminalStatus`
- `notifyAvailablePlaybackFunction`

Subscription mechanism (on cousin devices): `POST /sony/<service>` with `method: "switchNotifications"`, then upgrade the connection to WebSocket via `ws://<ip>:<port>/sony/<service>`.

WebSocket upgrade probe on port 60200 returned **405 Method Not Allowed** on `/sony/avContent` — likely needs a specific upgrade flow or different endpoint. To investigate.

## Method names to try (from cousin devices)

These have not been tested against the HAP but are documented for similar Sony devices. Add them to the fuzzer queue:

From [python-songpal/songpal/device.py](https://github.com/rytilahti/python-songpal/blob/master/songpal/device.py):
- `getSWUpdateInfo`, `actSWUpdate`
- `getCustomEqualizerSettings`, `setCustomEqualizerSettings`
- `getSupportedPlaybackFunction`, `getAvailablePlaybackFunction`
- `setPlaybackModeSettings`
- `seekStreamingContent` (or similar — seek within track)
- `getDeviceMode`, `setDeviceMode`
- `getWuTangInfo` (Wi-Fi config — tried, `No Such Method` on HAP)

From [Sony BRAVIA spec](https://pro-bravia.sony.net/develop/integrate/rest-api/spec/):
- `setActiveApp`
- `terminateApps`
- `getApplicationList`

## Discovery workflow

To add a method to this catalog:

1. Run `python tools/api-fuzzer.py --method <name>` with default versions sweep.
2. If a version returns anything other than `Unsupported Version` or `No Such Method`, record the response.
3. Test the method against multiple devices if possible (HAP-Z1ES + HAP-S1).
4. Submit a PR updating this file. Include the raw JSON request and response in your commit message.

## Reference: error codes seen

| Code | Message | Meaning |
|---|---|---|
| 1 | `Any` | Generic / catch-all error. Often means params include an invalid value (e.g. wrong `output:` target, wrong URI scheme). |
| 3 | `illegal Argument` | A specific parameter is missing or has the wrong type. |
| 5 | `illegal Request` | The request envelope is wrong (missing required wrapper object, wrong structure). |
| 12 | `No Such Method` | Method not implemented on this service. |
| 14 | `Unsupported Version` | Method exists but `version` value is wrong — try other versions. |
| (none) | (no `error` key) | Success — `result` field has the payload. |

**Status legend used in tables above:**
- ✅ Working, return shape known
- 🟡 Method confirmed to exist, but correct params not yet known (returns `Any` / `illegal Argument` / `illegal Request`)
- ❓ Untested, hypothesized
- ❌ Confirmed not implemented on this device

## Legend explanation: 🟡 methods (the ones we should attack next)

These methods *exist on the device* — the server didn't reject them as "No Such Method." We just don't know the right parameter shape. The right way to discover the params is:

1. **Decompile the Android APK** ([`tools/apk-decompile.md`](../tools/apk-decompile.md)) — yields the exact param shape Sony's own client sends.
2. **Wireshark the iOS app** while you tap each button — captures the live JSON-RPC requests.
3. **Try shapes from cousin Sony devices** (BRAVIA spec, python-songpal device.py) — many work as-is.

Once we know the param shape, status moves from 🟡 to ✅.

---

# Live validation log — 2026-05-25 (post-APK-decompile)

Master record of methods validated live against the HAP-Z1ES on firmware 19404R, using Sony shapes from the APK decompile. This section supersedes the older 🟡 hypotheses in the per-service tables above when in conflict.

## ✅ Newly validated working methods

| Service | Method | Version | Confirmed params | Sample response |
|---|---|---|---|---|
| `system` | `getSleepTimer` | 1.0 | `[{}]` | `{status:"off", remainTimerSec:-1, sleepTimerSec:-1, candidateStatus:["on","off"], candidateSec:[600,1200,1800,2400,3000,3600,5400,7200]}` |
| `system` | `setPowerStatus` | 1.1 | `[{status:"play"}]` | `{result:[]}` — wakes + resumes |
| `avContent` | `getBufferTime` | 1.0 | `[{}]` | `{bufferTimeSec:60, candidate:[15,30,60,180]}` |
| `avContent` | `getRepeatType` | 1.0 | `[{target:"audio"}]` (or `"spotify"`) | `{type:"off", target:"track"}` — **settings are PER SOURCE** |
| `avContent` | `getShuffleType` | 1.0 | `[{target:"audio"}]` | same per-source pattern |
| `avContent` | `getPlaylistInfo` | 1.0 | `[{uri:"audio:list?id=N&originalVersion=M"}]` | `{type:"all", location:"http://<ip>:60200/sony/avContent/recfile/requestN.data"}` |
| `avContent` | `getContentInfo` | 1.1 | `[{uri:"audio:track?id=N"}]` | `{title, coverArtUrl, backgroundColorR/G/B/A}` (subset of getPlayingContentInfo — track URIs only) |
| `avContent` | `setPlayContent` | 1.1 | `[{positionSec:N}]` | `{result:[]}` — seeks to N seconds in current track |
| `avContent` | `createPlayingListAndQuickPlay` | 1.0 | `[{uri:"audio:track?id=N", listIndex:0, listCount:1, playbackControlMode:"folder"}]` | `{playbackControlMode, uri:"audio:playinglist?id=<new>"}` — primary HDD play primitive |
| `database` | `checkSameDatabase` | 1.0 | `[{uri:"database:<short_uuid>?dbType=hdd&dbSerial=N&originalVersion=M"}]` | `{isSameVersion:bool, isSameName:bool, type:""}` |

## ❌ Confirmed NOT implemented on firmware 19404R (despite APK references)

- `system.getSupportedFileType` — Sony app references it; HAP-Z1ES returns `No Such Method`. Probably HAP-S1 only or removed.
- `avContent.getStorageInformation` — same. Use the older `getStorageList` instead.
- `GET /turnOn`, `GET /turnOff` — APK references these plain-HTTP endpoints; HAP-Z1ES returns 404 with or without `/sony/` prefix.

## 🟡 Confirmed exists but params still unknown after live test

- `database.downloadByDiff` — endpoint accepted, but returned `{dbType:"", type:"all", location:""}` with empty `location` across all tested variants (`dbSerial=0/1, originalVersion=0/1, no version params`). Likely needs a preflight handshake or a different `dbType` value. **Highest-leverage unblock pending.**
- `avContent.getRichMetaInfo` — Sony shape from APK is complex; our simple `[{uri}]` returned `[1, "Any"]`. Needs APK re-read for the full param object.
- `system.setSleepTimer`, `avContent.setBufferTime`, `setRepeatType`, `setShuffleType`, `setAudioVolume`, `setAudioMute`, `setSoundSettings`, `setAudioInput` — shapes known from APK but UNTESTED (deliberately, to avoid side effects on user listening).

## 🎯 The `recfile` generic transport mechanism (NEW)

Many JSON-RPC methods don't return the actual payload in the response. Instead they return `{location: "http://<ip>:60200/sony/avContent/recfile/requestN.data"}`. A plain HTTP GET on this URL returns the binary/text payload as **`application/x-www-form-urlencoded`** data.

Example from `getPlaylistInfo` on playlist id=70 (which we created earlier via `createPlayingListAndQuickPlay`):

```
GET http://<ip>:60200/sony/avContent/recfile/request4.data
→ 40 bytes: newVersion=9&types=2&ids=-1&positions=...
```

The `requestN` counter is monotonic per device session.

**Implication for client code**: any method returning `{type: "all"\|"diff", location: "<URL>"}` is using this pattern. Parse JSON, GET location, parse form-urlencoded payload.

## 📐 On-device DB schema (extracted from APK's `demo_browse.db`)

The Android APK ships a 79 KB SQLite (`assets/demo_browse.db`) with the **complete on-device library DB schema**. Tables:

| Table | Purpose | Notable columns (Sony PROP-codes) |
|---|---|---|
| `FT0000` | Root catalog | PROP3601 (id), PROP1086 (import type), PROP7020 (name) |
| `FT0002` | **Tracks** (37+ columns) | PROP304B (codec), PROP3047 (duration), PROP3048 (sample rate), PROP304C (bitrate), PROP10DE (bit width), PROP7045 (genre id), PROP7052 (artist id), PROP706F (composer id), PROP7070 (lyricist id), PROPB2BB (album id), PROP6844 (release date), PROP087E (rating) |
| `FT000A` | **Albums** | PROP78D9 (thumbnail BLOB!), PROP7055 (album artist), PROP6844 (release date) |
| `FT4502` | Genres | PROP7020 (name) + variants (yomi/sort/initial) |
| `FT5202` | Artists | same pattern |
| `FT6F02` | Composers | same |
| `FT7002` | Lyricists | same |
| `FTF003` | Playlists | PROP106E (track count), PROPAA70 (modify number — matches `newVersion=N` in recfile!) |
| `FTF004` | Playlist contents (track ↔ list) | composite key (PROP3601, PROP3006, PROP2053) |

Full PROP-code dictionary (~60 codes decoded) in [`research/notes/2026-05-25-database-service-and-db-schema.md`](notes/2026-05-25-database-service-and-db-schema.md).

**Implication**: once `downloadByDiff` returns a real `location`, we can sync the entire HAP library DB into a local SQLite using this exact schema, and build a complete library browser without ever asking the device.
