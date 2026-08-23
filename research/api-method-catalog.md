# API Method Catalog (living document)

The current state of mapping for the Sony HAP-Z1ES / HAP-S1 ScalarWebAPI on port 60200. Updated as new methods are discovered.

**Last update**: 2026-05-25 (post-APK-decompile + live validation)
**Firmware tested against**: 19404R
**Device tested**: HAP-Z1ES (the canonical reference unit)
**Methods confirmed by live test**: see ✅ rows below
**Evidence tiers used in this document**, weakest to strongest: *read from a binary / APK* → *reported by a contributor* → *live-confirmed* (we ran it against the reference unit) → **independently corroborated** (two parties reached it without seeing each other's work — so far only the CORS `Content-Type` trap, see [`../docs/16-gotchas.md`](../docs/16-gotchas.md)). Anything unlabelled is a live-confirmed observation on 19404R.
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

The `<short_uuid>` is the device UDN minus the `uuid:` prefix. The `downloadByDiff` method is the *network* path to a full library DB export. **Superseded for client-building (2026-06-02):** the identical library SQLite was read directly off the HDD's `/data` partition and its schema confirmed — so a client can be built/validated against the real DB today. `downloadByDiff` remains an unsolved network-sync curiosity (empty `location`) but is **no longer a blocker**. See [`../docs/09-disk-layout.md`](../docs/09-disk-layout.md) + [`db-schema/`](db-schema/).

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

`setNetworkSettings`, `getNetworkSettings`, `getCurrentTime`, `setCurrentTime`, `getDeviceMode`, `setDeviceMode`, `getSWUpdateInfo`, `actSWUpdate`, `getRemoteControllerInfo`, `getWuTangInfo`, `getLEDIndicatorStatus`, `setLEDIndicatorStatus`, `getColorKeysLayout`, `getSystemSupportedFunction`, `getWolMode`, `getPowerSavingMode` — all `[12, "No Such Method"]`. (Last three re-confirmed live 2026-06-03.)

**Notable absence**: `getSWUpdateInfo` / `actSWUpdate` are missing → HAP cannot self-update via API. Firmware updates go through the device UI only, fetching from Sony's servers.

## Service: `audio`

| Method | Working version | Status | Params | Notes |
|---|---|---|---|---|
| `getVolumeInformation` | **1.1** | ✅ | `[]` | On HAP-Z1ES returns `minVolume: -1, target: "", mute: "toggle", volume: -1, step: 1, maxVolume: -1` — HAP-Z1ES has no internal amp so volume values are -1 (not applicable). HAP-S1 should return real values. |
| `setAudioVolume` | **1.0** | 🟡 | `[{volume: "<n>"}]` per APK | Confirmed shape from APK. On HAP-Z1ES volume is meaningless (no amp); test on HAP-S1. |
| `setAudioMute` | **1.1** | 🟡 | `[{mute: "on"\|"off"\|"toggle"}]` per APK | APK shows Sony **forces `"toggle"` on HAP-Z1ES** (modelType==2) regardless of requested state — implementation quirk. |
| `getSoundSettings` | **1.1** | ✅ | `[{target: ""}]` | Returns an array of `{target, currentValue, candidate:[{value, isAvailable, min, max, step}]}` — the proprietary audio toggles: `dsee` (auto/off), `dsdRemastering` (on/off), `gaplessPlayback` (auto/off), `volumeNormalization` (auto/off), `oversampling` (precision/normal). The current value is in **`currentValue`** (verified live 2026-06-03). |
| `setSoundSettings` | **1.1** | ✅ | `[{settings: [{target: "<target>", value: "<value>"}]}]` | **Confirmed working** by fuzzer (returned `{result: []}` with empty params — server accepted noop). Targets: `dsee`, `dsdRemastering`, `gaplessPlayback`, `volumeNormalization`, `oversampling`. Use the candidate values returned by `getSoundSettings`. |
| `getVersions` | 1.0 | ✅ | `[]` | Empty (neutered) |
| `getMethodTypes` | 1.0 | ✅ | `["<ver>"]` | Empty (neutered) |

### Confirmed NOT implemented on `audio`

`getSpeakerSettings`, `setSpeakerSettings`, `getCustomEqualizerSettings`, `setCustomEqualizerSettings`, `getAudioOutputs` — all `[12, "No Such Method"]`.

## Service: `avContent`

| Method | Working version | Status | Params | Notes |
|---|---|---|---|---|
| `getPlayingContentInfo` | **1.2** | ✅ | `[]` | The gold method. Returns title, artist, album, codec, bitrate, frequency, position, duration, URIs, coverArtUrl, RGB background color. See [`docs/03-network-api.md`](../docs/03-network-api.md) for full response shape. |
| `pausePlayingContent` | **1.0** | ✅ | `[{}]` | **LIVE-CONFIRMED 2026-05-25 + this is a TOGGLE**, not just pause. Called from PLAYING → goes PAUSED. Called from PAUSED → goes PLAYING. Misleadingly named. Use this single call for play/pause buttons in any UI. The naming-true `pause()` / `resume()` helpers in `tools/hap_client.py` check state first to enforce direction semantics. `setPowerStatus({status:"play"})` does NOT reliably resume Spotify Connect playback — only this toggle does. |
| `stopPlayingContent` | **1.0** | 🟡 | `[{}]` | Sony's app never calls this; method exists on device. Try `[{}]` first. |
| `setPlayNextContent` | **1.0** | 🟡 | `[{}]` per APK | APK confirms empty object. Should ✅ on retest. |
| `setPlayPreviousContent` | **1.0** | 🟡 | `[{}]` per APK | Same as above. |
| `setPlayContent` | **1.1** | ✅ | 3 shapes — see notes | **LIVE-CONFIRMED 2026-05-25**: `[{positionSec: N}]` (seek within current track, the `+0.01` jitter from Sony's code is to force re-trigger). Two other shapes from APK (UNTESTED live): `[{listIndex: N}]` (start track at queue position N) and `[{uri: "netService:audio?serviceName=X&id=Y", playlistName: "..."}]` (radio/TuneIn). No `{uri}` for HDD content — use `createPlayingListAndQuickPlay` instead. |
| `createPlayingListAndQuickPlay` | **1.0** | ✅ | `[{uri: "audio:track?id=N", listIndex: 0, listCount: 1, playbackControlMode: "folder"}]` | **LIVE-CONFIRMED 2026-05-25**. THE primary HDD playback primitive. Builds a play queue and starts playback. Returns `{playbackControlMode, uri: "audio:playinglist?id=<new-id>"}` — note the new playinglist id (in our test: 70, previous was 69). |
| `scanPlayingContent` | **1.0** | 🟡 | `[{direction: "fwd"\|"bwd"}]` per APK | **Press-and-hold fast-forward / rewind** (NOT scrub-to-position — that's `setPlayContent + positionSec`). The device accelerates playback rate while called. Untested live with this shape. |
| `getContentInfo` | **1.1** | ✅ | `[{uri: "audio:track?id=N"}]` | **CONFIRMED 2026-05-25**: returns `{title, coverArtUrl, backgroundColorR/G/B/A}` (a *subset* of `getPlayingContentInfo` — no artist/album/codec/duration). Album URIs `audio:album?id=N` return `[1, "Any"]` — only track URIs work for this method. The reduced metadata set suggests there's a separate "full info" call we haven't found yet. |
| `getContentList` | **1.3** | 🟡 | `[{uri: "netService:audio?serviceName=X[&path=Y]", scope: "directory"\|"favorite"\|"search"\|"connected"\|"unconfirmed"\|"unconnected", stIdx: 0, cnt: 100, finish: false, search?: {word: "..."}}]` | **APK reveals**: this method is for **internet radio / netService browsing only** (TuneIn/vTuner). For HDD content (`audio:track`, `audio:album`), Sony's app **does not use this method** — it browses via the local SQLite cache it sync'd via the `database` service's `downloadByDiff`. That's why all our `audio:album` shapes failed: wrong category of URI entirely. **The netService shape is now LIVE-TESTED (2026-08-21, 19404R)** — see the service-name whitelist below. |
| `deleteContent` | **1.1** | 🟡 | `[{uri: ["audio:track?id=N", "audio:track?id=M", ...]}]` per APK | **CORRECTED**: `uri` is a JSON ARRAY of URI strings (bulk delete), not a scalar. Use `audio:track?id=N` or `audio:folder?id=N` (folder for bulk dir delete). **DANGEROUS** — destroys library content. Test with disposable test track + backup. |
| `getSourceList` | **1.0** | ✅ but empty | `[{scheme: "<scheme>"}]` | **Version pinned 2026-08-21**: only `1.0` is accepted — `1.1`/`1.2`/`1.3` all return `[14, "Unsupported Version"]`. At `1.0` it returns `{"result": []}` even with `scheme: "netService"`. Still needs the right scheme, or is neutered like the rest of introspection. |

### The `netService` whitelist — live-tested 2026-08-21 on 19404R

The APK notes suggested enumerating `serviceName` values to learn which internet-radio services the
firmware understands. Done, via `getContentList` v1.3. The firmware distinguishes sharply between a
**name it knows** and a **name it doesn't**, which makes it a clean oracle:

| `serviceName` | Reply | Reading |
|---|---|---|
| `tunein` | `[1, "Any"]` | **Known.** Passed argument validation, then failed downstream |
| `radiko` | `[1, "Any"]` | **Known.** Same |
| `vtuner` | `[3, "illegal Argument"]` | **Rejected outright** |
| `spotify` | `[3, "illegal Argument"]` | Rejected — Spotify Connect is not a `netService` |
| `bivl` | `[3, "illegal Argument"]` | Rejected |
| `nosuchservice` | `[3, "illegal Argument"]` | Rejected (the control) |

**So the whitelist is exactly `{tunein, radiko}`.** Every `scope` value (`directory`, `favorite`,
`connected`, `unconfirmed`, `unconnected`) gives the same `[1, "Any"]` for `tunein` — the failure is
not scope-dependent.

Two cross-confirmations fall out of this. The 2016 Crestron Help PDF marks `Source_Type_VTuner` as
*"not currently supported by the device"* — and ten years later the firmware still rejects the name
as an illegal argument. And `[1, "Any"]` rather than `[3, ...]` for `tunein` means the name is valid
but the service does not answer, which matches a contributor's account (Amos, 2026-08-21) that
**Sony withdrew TuneIn during 2026 server-side, without shipping any firmware change**. The device
still has the code; the far end is gone.

That is worth naming plainly: this project is documenting a machine that is *still losing*
functionality, by remote action, a decade after release and five years after its last firmware.

### Browse is dead, but playback still works — internet radio can be restored

Contributed 2026-08-21 via Amos: an independent HTML remote by a German HAP owner (met on the Steve
Hoffman forums) that still plays TuneIn stations on a device where Sony removed radio from the
front panel and from both mobile apps. Its entire protocol content is one call:

```json
POST /sony/avContent
{
  "id": 1,
  "method": "createPlayingListAndQuickPlay",
  "params": [{
    "playbackControlMode": "station",
    "listCount": 0,
    "uri": "netService:audio?serviceName=tunein&path=1/1/1&id=s20291",
    "listIndex": 0
  }],
  "version": "1.0"
}
```

**This is the same primitive we already use for HDD playback, in a mode we did not know about.** Our
entry above documents `createPlayingListAndQuickPlay` v1.0 with `playbackControlMode: "folder"`,
`listCount: 1` and an `audio:track?id=N` URI. Here it takes **`playbackControlMode: "station"`**,
`listCount: 0`, and a `netService:` URI. New enum value, new URI category, same method and version.

It also **contradicts our APK-derived assumption**: the catalogue says radio is played with
`setPlayContent` + `{uri: "netService:…", playlistName}`. This author uses a different primitive
altogether. Either both work, or the APK shape is stale.

> **⚠️ Corrected 2026-08-21, same day.** This section first concluded that "Sony withdrew the browse
> service and left the streaming path intact, so radio is restorable from the outside". **That was
> wrong**, and it was wrong because it was inferred from someone else's working device rather than
> tested on ours. Testing it produced a much more ordinary explanation — see below. Do not build on
> the original claim.

**What actually happens on an unregistered unit** (live, 19404R, 2026-08-21): the call is *accepted*
and returns `{"playbackControlMode": "station", "uri": "audio:playinglist?id=1"}`, which looks like
success. But the play queue stays **empty**, nothing plays, and the previous playback session is
cleared. `setPlayContent` with the APK's netService shape returns `[1, "Any"]`.

The reason is not a withdrawn service. It is this:

```json
POST /sony/avContent
{"method":"registerDevice","version":"1.0","id":1,
 "params":[{"uri":"netService:audio?serviceName=tunein","method":"check"}]}

→ {"result": [{"isRegistered": false}], "id": 1}
```

**The unit is not registered with TuneIn**, and TuneIn on the HAP requires per-device registration.
The German author's device evidently is registered; ours never was. That single fact explains the
empty queue *and* the `[1, "Any"]` from `getContentList` — no account, no content.

And the registration flow is still alive: `method: "getPin"` returns a real code
(`{"pinCode": "SW94LN"}`), which is the pairing code you enter on TuneIn's side.

So the honest statement is: **radio may well be restorable, but registration is the gate, and we
have not been through it.** Whether Sony's pairing back-end still honours a new PIN in 2026 is
untested and is the next thing to find out. What is certain is that a client cannot simply fire
station IDs at an unregistered player.

This is also the likeliest explanation for the `streaming` content type that the Crestron module
encounters and renders literally as `"UNDOCUMENTED STREAM"` — netService items in a directory
listing.

#### `registerDevice` — LIVE-CONFIRMED 2026-08-21

Previously listed as APK-derived and untested. Both read-ish methods work on 19404R:

| `method` | Response |
|---|---|
| `check` | `{"isRegistered": false}` on our unit |
| `getPin` | `{"pinCode": "SW94LN"}` — a fresh 6-character pairing code |
| `unregister` | Not tested (destructive on a registered unit) |

`getPin` is safe to call and is the fastest way to tell whether the pairing machinery is alive.

#### Two response-shape corrections found along the way

- **`playbackControlMode` is not validated.** The device echoes back whatever string you send —
  `"station"`, `"folder"`, even `"bogusmode"` — and still returns a playinglist URI. It is **not**
  an oracle for probing valid values, and a call "succeeding" here says nothing about whether it
  did anything.
- **`GET /sony/contentplayer/v100/playinginfo` returns `500` when the play queue is empty**, not
  only when the device is asleep. The Crestron module treats `404`/`500` as "server is likely
  powered off" — that reading is incomplete and will mislead a client into reporting a live player
  as offline. Cross-check `powerstate` (which stays `200`) before concluding anything.

#### Open: what is `path`?

`path=1/1/1`, `1/1/2`, `1/1/3` … The author's instruction is *"do not forget to increase the data
number"*, so it must be distinct per station, and he notes *"not every station is properly loaded"*.

**Hypothesis, weakened 2026-08-22.** We guessed that `path` must be unique and that his loading
complaint was self-inflicted, because his first list reused `1/1/5` for two entries. His corrected
page reuses **`1/1/3` for three entries** — deliberately shipped that way, by the person who wrote
the instruction to increment it. So either uniqueness does not matter and the guess was wrong, or he
is still carrying the bug he described. We cannot separate the two from here: on an unregistered
player station playback does nothing at all, so there is no signal to read.

**Blocked on registration**, not on effort. Anyone with a *paired* player can settle it in three
calls: the same station under two different paths, and two different stations under one shared path.

**Attribution / licence**: the script was shared privately. The protocol facts above are documented
because facts are not copyrightable, but the file itself is not vendored here and must not be
without its author's permission. His name is not yet known to us — ask before crediting, and credit
before shipping anything built on this.
| `getSchemeList` | 1.0 | ✅ but empty | `[]` | Returns empty result. |
| `getCurrentExternalTerminalsStatus` | 1.0 | ✅ | `[]` | Returns empty array. |
| `getPlaybackModeSettings` | 1.0 | ✅ | `[{target: ""}]` | Returned empty result. |
| `setPlaybackModeSettings` | **1.0** | ✅ | `[{settings: [{target: "<x>", value: "<y>"}]}]` | **NEW: confirmed working at v1.0** (empty params returned `{result: []}`). Likely controls shuffle/repeat. |
| `getVersions` | 1.0 | ✅ | `[]` | Empty (neutered) |
| `getMethodTypes` | 1.0 | ✅ | `["<ver>"]` | Empty (neutered) |

### Implemented at v1.0 but return empty `[]` (stubs — like the neutered introspection)

Live 2026-06-03: these accept v1.0 and return `{result: []}` (no error), but `[14, "Unsupported
Version"]` at v1.1+. So they exist but are effectively neutered/empty on 19404R — don't expect data:
`getSchemeList`, `getSourceList` (tried `scheme: storage / netService / audio`),
`getCurrentExternalTerminalsStatus`, `getPlaybackModeSettings`. (To enumerate sources/inputs, use the
`storage:` / `extInput:` URI schemes directly; to browse the library, read the DB — see
[`../docs/09-disk-layout.md`](../docs/09-disk-layout.md).)

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
| `switchNotifications` | n/a | ❌ | — | **`No Such Method`** — absent, confirmed by APK decompile (2026-05-25). No `ws://` URL anywhere in the binary. This stands. It does **not** mean the HAP has no push mechanism — see below. |

## Real-time updates — UDP push, with polling as fallback

> **Corrected 2026-08-20.** This section previously concluded "the HAP is a polling-only device".
> Wrong: it pushes events as pseudo-HTTP `NOTIFY` datagrams over UDP, via
> `POST /sony/notification/status`. Found in the Crestron module, verified live on 19404R. Full
> protocol in [`docs/03-network-api.md`](../docs/03-network-api.md#real-time-updates--push-notifications-over-udp)
> and [`notes/2026-08-20-crestron-module-teardown.md`](notes/2026-08-20-crestron-module-teardown.md).
>
> The earlier reasoning was sound but the search was too narrow — it looked for `switchNotifications`
> and WebSocket, which genuinely are absent, and concluded from their absence that nothing existed.
> Sony's own Android client polls and never subscribes, so the APK could not have revealed it.

Sony's app polls at 5 s. Prefer the push mechanism; keep these as a fallback:

| Thread | Endpoint | Method | Cadence |
|---|---|---|---|
| Volume + mute | `POST /sony/audio` | `getVolumeInformation` v1.1 | 5 s |
| Now-playing | `POST /sony/avContent` | `getPlayingContentInfo` v1.2 | 5 s |
| Power | `POST /sony/system` | `getPowerStatus` v1.1 | 5 s |
| Library sync state | `POST /sony/database` | `checkSameDatabase` v1.0 | 5 s |

Sony's "official example code" repo (`sonydevworld/audio_control_api_examples`) **does** demonstrate `switchNotifications` over WebSocket — but for *cousin* devices (BRAVIA TVs, STR-DN receivers, SRS speakers). The HAP family is a different generation and never picked up that capability. The `notify*` method names listed in those examples (`notifyPowerStatus`, `notifyVolumeInformation`, etc.) do not exist on the HAP.

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

## Live validation log — 2026-05-25 (post-APK-decompile)

Master record of methods validated live against the HAP-Z1ES on firmware 19404R, using Sony shapes from the APK decompile. This section supersedes the older 🟡 hypotheses in the per-service tables above when in conflict.

## ✅ Newly validated working methods

| Service | Method | Version | Confirmed params | Sample response |
|---|---|---|---|---|
| `system` | `getSleepTimer` | 1.0 | `[{}]` | `{status:"off", remainTimerSec:-1, sleepTimerSec:-1, candidateStatus:["on","off"], candidateSec:[600,1200,1800,2400,3000,3600,5400,7200]}` |
| `system` | `setSleepTimer` | 1.0 | `[{status:"on"\|"off", sleepTimerSec:<int>}]` | `{result:[]}` — accepted no-change call live |
| `system` | `setPowerStatus` | 1.1 | `[{status:"play"}]` | `{result:[]}` — wakes + resumes |
| `audio` | `setSoundSettings` | 1.1 | `[{settings:[{target, value}]}]` | `{result:[]}` — accepted dsee=auto (no-change) live |
| `avContent` | `getBufferTime` | 1.0 | `[{}]` | `{bufferTimeSec:60, candidate:[15,30,60,180]}` |
| `avContent` | `setBufferTime` | 1.0 | `[{bufferTimeSec:<int>}]` | `{result:[]}` — accepted 60s (no-change) live |
| `avContent` | `getRepeatType` | 1.0 | `[{target:"track"}]` for HDD/USB or `[{target:""}]` for Spotify | `{type:"off", target:"track"}` — **settings are PER SOURCE**. Sony's APK sends `"track"` not `"audio"`; both work but `"track"` is canonical. |
| `avContent` | `setRepeatType` | 1.0 | `[{target:"track"\|"", type:"off"\|"one"\|"all"\|"track"}]` | `{result:[]}` — accepted no-change live |
| `avContent` | `getShuffleType` | 1.0 | `[{target:"track"}]` for HDD or `[{target:""}]` for Spotify | Same per-source pattern. Canonical Sony value: `"track"`. |
| `avContent` | `setShuffleType` | 1.0 | `[{target:"track"\|"", type:"off"\|"track"\|"album"\|"folder"}]` | `{result:[]}` — accepted no-change live |
| `avContent` | `editContentInfo` | 1.0 | `[{method:"editTrackInfo", target:[{uri,tagUri:"meta:favorite",value:"favorite"\|"dislike"\|"normal"}]}]` | `{result:[]}` — **THIS is how favorites are toggled** (no separate setFavorite method exists). Live-tested with `value:"normal"` (clear). |
| `avContent` | `getPlaylistInfo` | 1.0 | `[{uri:"audio:list?id=N&originalVersion=M"}]` | `{type:"all", location:"http://<ip>:60200/sony/avContent/recfile/requestN.data"}` |
| `avContent` | `getContentInfo` | 1.1 | `[{uri:"audio:track?id=N"}]` | `{title, coverArtUrl, backgroundColorR/G/B/A}` (subset of getPlayingContentInfo — track URIs only) |
| `avContent` | `setPlayContent` | 1.1 | `[{positionSec:N}]` | `{result:[]}` — seeks to N seconds in current track |
| `avContent` | `createPlayingListAndQuickPlay` | 1.0 | `[{uri:"audio:track?id=N", listIndex:0, listCount:1, playbackControlMode:"folder"}]` | `{playbackControlMode, uri:"audio:playinglist?id=<new>"}` — primary HDD play primitive |
| `database` | `checkSameDatabase` | 1.0 | `[{uri:"database:<short_uuid>?dbType=hdd&dbSerial=N&originalVersion=M"}]` | `{isSameVersion:bool, isSameName:bool, type:""}` |

**Note on `getRichMetaInfo`**: tested 4 shape variants (`{uri}`, `{uri,types:[]}`, `{uri,types:["all"]}`, `{uri:"",types}`) — 3 returned `[1,"Any"]`. A fourth shape with `{uri,target:""}` triggered an HTTP **500 Internal Server Error** ("internal server error") — the device crashed internally on that param combination. Notable robustness concern. Method remains 🟡 pending APK re-read or mitmproxy capture.

## ❌ Confirmed NOT implemented on firmware 19404R (despite APK references)

- `system.getSupportedFileType` — Sony app references it; HAP-Z1ES returns `No Such Method`. Probably HAP-S1 only or removed.
- `avContent.getStorageInformation` — same. Use the older `getStorageList` instead.
- `GET /turnOn`, `GET /turnOff` — APK references these plain-HTTP endpoints; HAP-Z1ES returns 404 with or without `/sony/` prefix.

## 🟡 Confirmed exists but params still unknown after live test

- `database.downloadByDiff` — endpoint accepted, but returned `{dbType:"", type:"all", location:""}` with empty `location` across all tested variants (`dbSerial=0/1, originalVersion=0/1, no version params`). Likely needs a preflight handshake or a different `dbType` value. **No longer a blocker** — the same library DB is now available directly off the disk (see [`../docs/09-disk-layout.md`](../docs/09-disk-layout.md)); this remains an open network-sync curiosity only.
- `avContent.getRichMetaInfo` — Sony shape from APK is complex; our simple `[{uri}]` returned `[1, "Any"]`. Needs APK re-read for the full param object.
- `system.setSleepTimer`, `avContent.setBufferTime`, `setRepeatType`, `setShuffleType`, `setAudioVolume`, `setAudioMute`, `setSoundSettings`, `setAudioInput` — shapes known from APK but UNTESTED (deliberately, to avoid side effects on user listening).

## 🎯 The `recfile` generic transport mechanism

Many JSON-RPC methods don't return the actual payload in the response. Instead they return `{location: "http://<ip>:60200/sony/avContent/recfile/requestN.data"}`. A plain HTTP GET on this URL returns the binary/text payload as **`application/x-www-form-urlencoded`** data.

Example from `getPlaylistInfo` on playlist id=70 (which we created earlier via `createPlayingListAndQuickPlay`):

```text
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

**Implication**: a client can mirror the entire HAP library into a local SQLite using this exact schema and browse it offline. We no longer need `downloadByDiff` to do it — the real DB was read directly off the disk (2026-06-02, [`../docs/09-disk-layout.md`](../docs/09-disk-layout.md)), which both unblocks the library browser and confirms this schema is correct. A live network sync via `downloadByDiff` would still be nice-to-have, but it is no longer on the critical path.
