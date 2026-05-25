# API Method Catalog (living document)

The current state of mapping for the Sony HAP-Z1ES / HAP-S1 ScalarWebAPI on port 60200. Updated as new methods are discovered.

**Last update**: 2026-05-25 (post-fuzz)
**Firmware tested against**: 19404R
**Device tested**: HAP-Z1ES (the canonical reference unit)
**Methods that exist on the device**: **24** (12 working with empty params, 12 known to exist but require parameters)
**Methods confirmed NOT implemented**: 29 (return `No Such Method`)
**Source for this version of the catalog**: `tools/api-fuzzer.py` run on 2026-05-25T18:44Z, output at `research/captures/fuzz-192_168_1_28-20260525T184419Z.json`

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
| `setPowerStatus` | **1.1** | 🟡 | `[{status: "active" \| "off"}]` | Method exists at v1.1 (fuzzer: `[3, "illegal Argument"]` with empty params). [Frazei gist](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a) reports v1.0 with `{status:"active"\|"off"}`. **Test carefully — this flips device power state.** |
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
| `setAudioVolume` | **1.0** | 🟡 | `[{volume: "<n>", target: ""}]` | Method exists (fuzzer: `[3, "illegal Argument"]` with empty params). Confirms [frazei gist](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a). Untested with real value on HAP-Z1ES (no internal amp) — try on HAP-S1. |
| `setAudioMute` | **1.1** | 🟡 | `[{mute: "on" \| "off" \| "toggle"}]` | Method exists at v1.1 (illegal Argument with empty params). |
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
| `pausePlayingContent` | **1.0** | 🟡 | likely `[{output:""}]` | Returned `[1, "Any"]` to fuzzer with empty params. Probably needs an `output` target. Re-test once we know the shape. |
| `stopPlayingContent` | **1.0** | 🟡 | likely `[{output:""}]` | Exists; `[1, "Any"]` with empty params. |
| `setPlayNextContent` | **1.0** | 🟡 | likely `[{output:""}]` | Exists; `[1, "Any"]` with empty params. |
| `setPlayPreviousContent` | **1.0** | 🟡 | likely `[{output:""}]` | Exists; `[1, "Any"]` with empty params. |
| `setPlayContent` | **1.1** | 🟡 | shape unknown | Method exists at v1.1. Tested shapes that all returned `[1, "Any"]`: `{uri}`, `{uri,output:""}`, `{uri,position:0}`, `{uri,playSpeed:""}`, `{uri,resume:"on"}`. Either the URI format is wrong, or the device refuses to "re-play" what is already playing. Needs APK decompile to know the real shape. |
| `scanPlayingContent` | **1.0** | 🟡 | unknown | Exists; `[3, "illegal Argument"]`. Likely scrub/seek within current track. |
| `getContentInfo` | **1.1** | ✅ | `[{uri: "audio:track?id=N"}]` | **CONFIRMED 2026-05-25**: returns `{title, coverArtUrl, backgroundColorR/G/B/A}` (a *subset* of `getPlayingContentInfo` — no artist/album/codec/duration). Album URIs `audio:album?id=N` return `[1, "Any"]` — only track URIs work for this method. The reduced metadata set suggests there's a separate "full info" call we haven't found yet. |
| `getContentList` | **1.3** | 🟡 | shape unknown | Method exists at v1.3. Tested 8 shape variants on 2026-05-25, all returned `[3, "illegal Argument"]`: `{uri,stIdx,cnt}`, `{source,stIdx,cnt}`, `{uri,stIdx,cnt,type,target,view}`, `{uri,stIdx,cnt,sort,view:"Default"}`, `{uri:""}`, `{path,stIdx,cnt}`, `{uri:"audio",stIdx,cnt}`, `{uri,index,count}`. The required key set is not derivable from BRAVIA/python-songpal shapes — Sony built a different schema for HAP. APK decompile is the way. |
| `deleteContent` | **1.1** | 🟡 | `[{uri: "<file uri>"}]` | Exists; `[5, "illegal Request"]` with empty params. **DANGEROUS** — deletes a file from the library. Do not test without backup. |
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
- `seekStreamingContent` → seek within track is **not** supported via this method name. The HAP front panel can scrub, so either there's a different method name we haven't tried (e.g. `seekContent`, `setPlayPosition`) or seek is done by re-calling `setPlayContent` with `positionMsec` in params.
- `getFavoriteList` / `setFavoriteContent` → favorites management is not API-exposed. `getPlayingContentInfo` returns `favoriteType: "normal"` showing favorites exist conceptually — likely managed via the on-device UI only.
- `getBluetoothSettings` → BlueZ is in firmware (per GPL bundle), but BT receiver/transmitter is front-panel only.

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
