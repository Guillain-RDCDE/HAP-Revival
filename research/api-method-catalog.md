# API Method Catalog (living document)

The current state of mapping for the Sony HAP-Z1ES / HAP-S1 ScalarWebAPI on port 60200. Updated as new methods are discovered.

**Last update**: 2026-05-25
**Firmware tested against**: 19404R
**Device tested**: HAP-Z1ES (the canonical reference unit)

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
| `setPowerStatus` | 1.0 | ⚠️ | `[{status: "active" \| "off"}]` | Per [frazei gist](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a). Untested live; should be safe but flips device state. |
| `getInterfaceInformation` | 1.0 | ✅ | `[]` | Returns `{productName: "HAP", modelName: "HAP-Z1ES", productCategory: "audioServer", interfaceVersion: "1.0.0"}` |
| `getNetworkSettings` | various | ❌ | `[{netif:""}]` | Returns `error: [12, "No Such Method"]` at v1.0 — unknown if a different version exists |
| `getCurrentTime` | various | ❌ | `[]` | `No Such Method` at v1.0 |
| `getStorageList` | 1.0 | ✅ | `[]` | Returns empty `[]` — needs USB device inserted to populate? Untested with USB attached |

## Service: `audio`

| Method | Working version | Status | Params | Notes |
|---|---|---|---|---|
| `getVolumeInformation` | **1.1** | ✅ | `[]` | On HAP-Z1ES returns `minVolume: -1, target: "", mute: "toggle", volume: -1, step: 1, maxVolume: -1` — HAP-Z1ES has no internal amp so volume values are -1 (not applicable). HAP-S1 should return real values. |
| `setAudioVolume` | 1.0 | ⚠️ | `[{volume: "<n>", target: ""}]` | Per [frazei gist](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a). Untested. |
| `getSoundSettings` | **1.1** | ✅ | `[{target: ""}]` | Returns the proprietary audio toggles: `dsee` (auto/off), `dsdRemastering` (on/off), `gaplessPlayback` (auto/off), `volumeNormalization` (auto/off), `oversampling` (precision/normal) |
| `setSoundSettings` | 1.1 (inferred) | ❓ | `[{settings: [{target: "dsee", value: "off"}]}]` | Untested. BRAVIA spec shape; needs verification. |
| `getSpeakerSettings` | various | ❌ | `[{target: ""}]` | `No Such Method` at v1.0 |

## Service: `avContent`

| Method | Working version | Status | Params | Notes |
|---|---|---|---|---|
| `getPlayingContentInfo` | **1.2** | ✅ | `[]` | The gold method. Returns title, artist, album, codec, bitrate, frequency, position, duration, URIs, coverArtUrl, RGB background color. See [`docs/03-network-api.md`](../docs/03-network-api.md) for full response shape. |
| `pausePlayingContent` | 1.0 | ✅ | `[]` | Verified by call — returns empty result, no error. Pauses current playback. |
| `setPlayNextContent` | 1.0 | ⚠️ | `[]` | Per [frazei gist](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a). Untested. |
| `setPlayPreviousContent` | 1.0 | ⚠️ | `[]` | Per frazei. Untested. |
| `setPlayContent` | unknown | ❓ | `[{uri: "audio:track?id=NNN"}]` | Needed for playback initiation. Returns `Unsupported Version` at 1.0 — try 1.1, 1.2. |
| `getSourceList` | 1.0 | ✅ but empty | `[{scheme: "<scheme>"}]` | Returns empty result. Needs the right scheme. Try `"storage"`, `"audio"`, `"radio"`, `"hap"`. |
| `getSchemeList` | 1.0 | ✅ but empty | `[]` | Returns empty result. Likely needs a different version. |
| `getContentList` | unknown | ❓ | `[{uri: "<uri>", stIdx: 0, cnt: 10}]` | `Unsupported Version` at 1.0, 1.2. Try 1.3, 1.4, 1.5, 1.6. |
| `getContentCount` | various | ❌ | `[{uri:"", type:"", target:"", view:""}]` | `No Such Method` at v1.0 |
| `getCurrentExternalTerminalsStatus` | 1.0 | ✅ but empty | `[]` | Returns empty array. |
| `getPlaybackModeSettings` | 1.0 | ✅ but empty | `[{target:""}]` | Returns empty array. |
| `getBluetoothSettings` | various | ❌ | `[{target:""}]` | `No Such Method` at v1.0 |
| `getApplicationStatusList` | various | ❌ | `[]` | `No Such Method` at v1.0 |

## Service: `guide`

| Method | Working version | Status | Params | Notes |
|---|---|---|---|---|
| `getVersions` | 1.0 | ✅ but empty | `[]` | Returns `{result: []}` — introspection is intentionally neutered |
| `getMethodTypes` | any | ✅ but empty | `["<version>"]` | Returns `{results: []}` — same |
| `getSupportedApiInfo` | various | ❌ | `[{services:[]}]` | `No Such Method` at v1.0 |
| `getServiceProtocols` | 1.0 | ❌ | `[]` | Returns `error: [5, "illegal Request"]` |

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
| 5 | `illegal Request` | Method exists but request shape is wrong |
| 12 | `No Such Method` | Method not implemented on this service |
| 14 | `Unsupported Version` | Method exists but try a different `version` value |
| (none) | (no `error` key) | Success — `result` field has the payload |
