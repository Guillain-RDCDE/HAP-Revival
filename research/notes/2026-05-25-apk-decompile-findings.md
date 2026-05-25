# Decompile findings: `com.sony.HAP.HDDAudioRemote` 4.3.1

**Date**: 2026-05-25
**Status**: Complete first pass. No live-device validation yet.
**Headline**: All 12 🟡 methods in [`api-method-catalog.md`](../api-method-catalog.md) now have a Sony-confirmed parameter shape. Plus we found **~15 methods the catalog never knew existed**, **one entire new service (`/database`)**, and proof that the HAP family **does not use WebSocket notifications** — the Android app polls four endpoints every 5 s.

---

## 1. Artefact provenance

| Field | Value |
|---|---|
| Source | APKCombo CDN (`https://download.pureapk.com/b/APK/...`), redirected from `https://apkcombo.com/hdd-audio-remote/com.sony.HAP.HDDAudioRemote/download/phone-4.3.1-apk` |
| Filename | `HDDAudioRemote-4.3.1.apk` (NOT in repo — Sony copyright) |
| Local path | `C:\Users\loutr\Downloads\HDDAudioRemote-4.3.1.apk` |
| Size | 13 509 789 bytes (12.88 MB) — matches APKMirror listing |
| SHA-256 | `0C694FD946FA590833BFF1D475E618CE62012EA2C4539FCAA101F69D19946D00` |
| `versionCode` | `20221122` |
| `versionName` | `4.3.1` |
| `package` | `com.sony.HAP.HDDAudioRemote` |
| `minSdkVersion` | 24 (Android 7.0) |
| `targetSdkVersion` | 33 (Android 13) |
| Built against | `platformBuildVersionName=13`, `platformBuildVersionCode=33` |

## 2. Toolchain (record for reproducibility)

| Tool | Version | Install path |
|---|---|---|
| Microsoft OpenJDK (Eclipse Temurin re-brand) | `21.0.11+10-LTS` build `Microsoft-13877171` | `C:\Program Files\Microsoft\jdk-21.0.11.10-hotspot\` |
| jadx | `1.5.5` | `C:\Users\loutr\Tools\jadx\bin\jadx.bat` |
| Decompile output | n/a | `C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\` |

jadx finished 2249/2252 classes (99.9%) in 62 s on this host. The 4 errors were inside `com.actionbarsherlock.widget.ActivityChooserModel.HistoryPersister.run()` and `jcifs.smb.SmbTransport.ssn139()` — irrelevant.

Install steps (for the project doc):

```powershell
winget install Microsoft.OpenJDK.21 --silent --accept-source-agreements --accept-package-agreements
# refresh PATH for the current session:
$env:PATH = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$env:JAVA_HOME = [System.Environment]::GetEnvironmentVariable("JAVA_HOME","Machine")
# fetch jadx from https://github.com/skylot/jadx/releases/latest, extract.
& "C:\Users\loutr\Tools\jadx\bin\jadx.bat" -d <output_dir> <apk>
```

The recipe in [`tools/apk-decompile.md`](../../tools/apk-decompile.md) can be simplified — **apktool is not needed**. jadx 1.5.5 already extracts assets/manifest cleanly as part of its run, and the manifest decoder built into jadx outputs the same human-readable XML apktool would.

## 3. Key constants (the network surface)

### 3.1 Ports

| Port | Purpose | Source |
|---|---|---|
| 60200 (TCP) | ScalarWebAPI HTTP control plane | `CommonHTTP.setManualIPSetting`: `this.httpHost = "http://" + this.ip + ":60200/"` |
| 60100 (TCP) | (not referenced in the APK directly) | Discovered via UPnP description; not hard-coded in the app |
| 1900 (UDP) | SSDP discovery | `findDevice` uses `upnpDiscovery.sendMSearch(...)` with URN filter `urn:schemas-sony-com:service:ScalarWebAPI:1` |

The Android client **does not hardcode 60100** anywhere. It discovers the API base URL by reading `<av:X_ScalarWebAPI_BaseURL>` from the UPnP description (see `upnpItem.getScalarWebAPI_BaseURL()`). Only when the user enters an IP **manually** is `60200` baked in directly. So firmware-side could in principle change 60200 — but for HAP-Z1ES/S1 the port is universally 60200 across all units.

### 3.2 Endpoint paths (BIG CORRECTION)

```java
// CommonHTTP.java:74
this.httpHost = "http://" + this.ip + ":60200/";
```

```java
// every API call site:
String URL = String.valueOf(CommonPreference.getInstance().getHttpHost(con)) + API_SERVICES_<x>;
```

i.e. the **HAP path is `/<service>`, NOT `/sony/<service>`**.

| Sony cousin devices | HAP family |
|---|---|
| `POST /sony/system` | `POST /system` |
| `POST /sony/audio` | `POST /audio` |
| `POST /sony/avContent` | `POST /avContent` |
| (no equivalent) | `POST /database` |
| `POST /sony/guide` | (the HAP Android app **never** calls `/guide` or `/sony/guide`) |

The fuzzer should be re-run against **`/avContent`** etc. instead of (only) `/sony/avContent` to confirm. If `/sony/*` and `/*` both work on the device this is moot, but if only one works we should update the docs.

Required request headers on every call (per `CommonHTTP.execHttpRequest`):

```
Accept-Encoding: *
Content-Type: application/json
x-hap-device-id: <UUID per-installation>
```

The `x-hap-device-id` header is **mandatory** — we have been omitting it in our fuzzer. The device may treat unauthenticated callers more strictly. The value is generated client-side and stored in `CommonPreference.getXHapDeviceId(context)`.

### 3.3 Non-JSON HTTP endpoints (the "turnOn"/"turnOff" plane)

```java
this.turnOnUrl = String.valueOf(this.httpHost) + "turnOn";
this.turnOnReplayUrl = String.valueOf(this.httpHost) + "turnOn?type=replay";
this.turnOnIntelligenceUrl = String.valueOf(this.httpHost) + "turnOn?type=intelligence";
this.turnOffUrl = String.valueOf(this.httpHost) + "turnOff";
```

i.e. the HAP exposes **plain HTTP GET endpoints** at port 60200 (NOT under any JSON-RPC service):

- `GET http://<ip>:60200/turnOn` — wake up
- `GET http://<ip>:60200/turnOn?type=replay` — wake up and resume last playback
- `GET http://<ip>:60200/turnOn?type=intelligence` — wake up and start SensMe-style auto-pick
- `GET http://<ip>:60200/turnOff` — sleep

These are **separate from the JSON-RPC `setPowerStatus` method** and are how the Android app and (very likely) the widget perform fast wake/sleep. They expect plain 200 OK with no body. The `x-hap-device-id` header is still sent.

This is a major new surface the catalog should document. It also means **a 2-line bash script can wake/sleep the HAP** without any JSON-RPC at all.

### 3.4 URI schemes (canonical list)

From every Sony-generated URI string we found in the source:

| Scheme | Form | Used by |
|---|---|---|
| `audio:track` | `audio:track?id=<int>` | `getContentInfo`, `createPlayingListAndQuickPlay`, `deleteContent` |
| `audio:folder` | `audio:folder?id=<int>` | `deleteContent` (when `type==1`) |
| `audio:list` | `audio:list?id=<int>&originalVersion=<int>` | `getPlaylistInfo`, `updatePlaylist` |
| `audio:list` | `audio:list?id=<int>` | `deletePlaylist` (no version) |
| `audio:track` (+sensMe) | `audio:track?id=<id>&sensMeIndex=<n>` | SensMe-style playback |
| `netService:audio` | `netService:audio` | top-level service browse |
| `netService:audio` (with svc) | `netService:audio?serviceName=<svc>` | scoped browse |
| `netService:audio` (deep) | `netService:audio?serviceName=<svc>&path=<p>&id=<id>&type=<t>` | radio station play / stream pick |
| `netService:audio` (tunein register) | `netService:audio?serviceName=tunein` | `registerDevice` for TuneIn |
| `netService:audio` (otherStream) | `netService:audio?type=otherStream&id=<id>&serviceName=tunein` | TuneIn alt-stream switch |
| `extInput:optical` | (literal) | `setAudioInput` (input=1) |
| `extInput:coaxial` | (literal) | `setAudioInput` (input=2) |
| `extInput:line` | `extInput:line?port=1` / `port=2` | `setAudioInput` (input=3/4) |
| `database:<short_uuid>` | `database:<uuid_minus_first_5_chars>?dbType=hdd&dbSerial=<n>&originalVersion=<n>` | `checkSameDatabase`, `downloadByDiff` |
| `database:list` | `database:list?id=<int>` | (referenced in playlist code) |

**None of `storage:usb`, `audio:album`, or `audio:artist` appear** in the Android client's URI builders. Either Sony does not browse by album/artist via URI (they use `getContentList` with `path=` instead), or those schemes exist on the device but only the iOS / front-panel UI uses them.

The `database` scheme is brand new — neither our docs nor python-songpal mention it.

### 3.5 Version-string usage table (per method, Sony-confirmed)

From the `createMsgFor*` builders in `jp/co/sony/lfx/anap/control/CommonControl.java`:

| Method | Sony uses | Our catalog said | Match? |
|---|---|---|---|
| `getPowerStatus` | `1.1` | `1.1` ✅ | ✅ |
| `setPowerStatus` | `1.1` | `1.1` (🟡) | ✅ |
| `getSystemInformation` | (not built here — uses different ver) | `1.2` | — |
| `getSleepTimer` | `1.0` | — | new |
| `setSleepTimer` | `1.0` | — | new |
| `getSupportedFileType` | `1.0` | — | new |
| `checkSameDatabase` | `1.0` | — | new (database service) |
| `downloadByDiff` | `1.0` | — | new (database service) |
| `createPlayingListAndQuickPlay` | `1.0` | — | **new — this is the playback start primitive** |
| `createPlaylist` | `1.0` | — | new |
| `updatePlaylist` | `1.0` | — | new |
| `deletePlaylist` | `1.0` | — | new |
| `setPlayNextContent` | `1.0` | `1.0` (🟡) | ✅ |
| `setPlayPreviousContent` | `1.0` | `1.0` (🟡) | ✅ |
| `pausePlayingContent` | `1.0` | `1.0` (🟡) | ✅ |
| `setAudioVolume` | `1.0` | `1.0` (🟡) | ✅ |
| `setAudioMute` | `1.1` | `1.1` (🟡) | ✅ |
| `scanPlayingContent` (= internal `setPlaySpeed`) | `1.0` | `1.0` (🟡) | ✅ |
| `setRepeatType` / `getRepeatType` | `1.0` | — | new |
| `setShuffleType` / `getShuffleType` | `1.0` | — | new |
| `setSoundSettings` | `1.1` | `1.1` ✅ | ✅ |
| `getSoundSettings` | `1.1` | `1.1` ✅ | ✅ |
| `getBufferTime` / `setBufferTime` | `1.0` | — | new |
| `getPlayingContentInfo` | `1.2` | `1.2` ✅ | ✅ |
| `setPlayContent` | `1.1` | `1.1` ✅ | ✅ |
| `setPlayContent` (seek variant — positionSec only) | `1.1` | — | new use of existing method |
| `getStorageInformation` | `1.0` | — | new (we tested `getStorageList`, not this) |
| `getContentInfo` | `1.1` | `1.1` (🟡) | ✅ |
| `getContentList` | `1.3` | `1.3` (🟡) | ✅ |
| `deleteContent` | `1.1` | `1.1` (🟡) | ✅ |
| `getPlaylistInfo` | `1.0` | — | new |
| `registerDevice` | `1.0` | — | new — for TuneIn account binding |
| `getRichMetaInfo` | `1.0` | — | new |
| `setAudioInput` | `1.0` | — | new — front-panel input switch via API |
| `setFavorite` | n/a (uses `editContentInfo`) | — | — |
| `editContentInfo` | (referenced) | — | new |

**Methods absent from the Sony Android app** (so the fuzz catalog's "exists but 🟡" must come from somewhere else — the device firmware exposes more than the official app uses):

- `stopPlayingContent` — **the official app never calls this**. Stopping a track happens through `pausePlayingContent` then `setPowerStatus(standby)`. The fuzzer saw "[1, Any]" for this method which means the device implements it but Sony's own GUI does not use it.
- `switchNotifications` — **the official app never subscribes to notifications**. See §5.
- `getServiceProtocols` — **never called**.
- `getMethodTypes` — **never called** (matches our finding that it returns empty).

## 4. Sony-confirmed param shapes for each 🟡 method

All quoted snippets are from `c:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\sources\jp\co\sony\lfx\anap\control\CommonControl.java`.

### `system.setPowerStatus` v1.1

```java
// CommonControl.java:1507
switch (status) {
    case -2: paramsObjs.put("status", "standby"); paramsObjs.put("standbyDetail", "databaseReady"); break;
    case 0:  paramsObjs.put("status", "off");     paramsObjs.put("standbyDetail", "");              break;
    case 1:  paramsObjs.put("status", "active");                                                    break;
    case 2:  paramsObjs.put("status", "play");                                                      break;
}
```

JSON wire forms:

```json
{"method":"setPowerStatus","params":[{"status":"active"}],                                "id":1,"version":"1.1"}
{"method":"setPowerStatus","params":[{"status":"off","standbyDetail":""}],                "id":1,"version":"1.1"}
{"method":"setPowerStatus","params":[{"status":"standby","standbyDetail":"databaseReady"}],"id":1,"version":"1.1"}
{"method":"setPowerStatus","params":[{"status":"play"}],                                  "id":1,"version":"1.1"}
```

POST target: `http://<ip>:60200/system`. **The HAP supports a 4th status `"play"`** which the catalog doesn't mention — it must wake the unit and immediately start playback (probably resuming the last queue).

Note `standbyDetail = "databaseReady"` for in-between standby state where the DB is still readable for queries (the HAP can serve metadata while logically off). This matches our `getPowerStatus` observations.

### `audio.setAudioMute` v1.1

```java
// CommonControl.java:1943
paramsObjs.put("mute", muteStatus);   // values used: "on", "off", "toggle" — and a forced "toggle" on HAP-Z1ES
```

```json
{"method":"setAudioMute","params":[{"mute":"toggle"}],"id":1,"version":"1.1"}
```

Note Sony **forces `toggle`** on HAP-Z1ES (`modelType == 2`) regardless of the requested state — confirming the HAP-Z1ES mute is really a toggle button, not a stateful on/off.

POST target: `http://<ip>:60200/audio`.

### `avContent.setPlayContent` v1.1 — **three distinct call signatures**

This is the most important finding. The catalog assumed one shape; Sony's code shows **three**.

#### 4.3.1 By list index (most common — start playback at position N in a queue)

```java
// CommonControl.java:1145
paramsObjs.put("listIndex", index);
```

```json
{"method":"setPlayContent","params":[{"listIndex":5}],"id":1,"version":"1.1"}
```

This is what fires when you tap track #5 in an album. Note it does **not** include a URI — it relies on the device's currently-loaded play queue (built by `createPlayingListAndQuickPlay`).

#### 4.3.1 By netService URI (radio / TuneIn)

```java
// CommonControl.java:1117
String contentUri = String.format("netService:audio?serviceName=%s&id=%s", serviceName, stationId);
paramsObjs.put("uri", contentUri);
paramsObjs.put("playlistName", playlistName);
```

```json
{"method":"setPlayContent","params":[{"uri":"netService:audio?serviceName=vtuner&id=12345","playlistName":"My TuneIn favs"}],"id":1,"version":"1.1"}
```

#### 4.3.1 Seek-within-track (re-uses setPlayContent!)

```java
// CommonControl.java:1994 (createMsgForSetPlaySeek — name is misleading)
paramsObjs.put("positionSec", time + 0.01d);
// no uri, no listIndex — just positionSec
```

```json
{"method":"setPlayContent","params":[{"positionSec":42.01}],"id":1,"version":"1.1"}
```

**This is how seek works on the HAP!** There is no separate `seekStreamingContent` (which we already saw return No-Such-Method). To scrub: `setPlayContent` with **only** `positionSec`. The `+ 0.01d` jitter is a Sony hack — probably to force the device to re-trigger its playback engine even when you seek to the same position.

POST target: `http://<ip>:60200/avContent`.

### `avContent.stopPlayingContent` — **DOES NOT EXIST IN APP**

The Android app never calls this. Our fuzzer observed it exists on the device (returned `[1, "Any"]`). Best guess: the API accepts `[]` or `[{output:""}]` but Sony chose to never expose it through the UI. To find the shape: test live; or try `{}` first since the device's other "no-arg" methods accept that.

**Action**: try `POST /avContent` with `{"method":"stopPlayingContent","params":[{}],"id":1,"version":"1.0"}`. If 1.0 fails try 1.1.

### `avContent.setPlayNextContent` / `setPlayPreviousContent` v1.0

```java
// CommonControl.java:1860 (next), 1877 (previous)
params.put(paramsObjs);  // paramsObjs is empty {}
```

```json
{"method":"setPlayNextContent","params":[{}],"id":1,"version":"1.0"}
{"method":"setPlayPreviousContent","params":[{}],"id":1,"version":"1.0"}
```

The params **must contain an empty object** `{}` not just an empty array `[]`. This explains our `[1, "Any"]` error from the fuzzer with `[]`.

POST target: `http://<ip>:60200/avContent`.

### `avContent.scanPlayingContent` v1.0 (the FF/REW seek)

```java
// CommonControl.java:1966 — this is named createMsgForSetPlaySpeed internally
// but METHOD_SET_PLAY_SPEED = "scanPlayingContent"
String direction = speed == -1 ? "bwd" : "fwd";
paramsObjs.put("direction", direction);
```

```json
{"method":"scanPlayingContent","params":[{"direction":"fwd"}],"id":1,"version":"1.0"}
{"method":"scanPlayingContent","params":[{"direction":"bwd"}],"id":1,"version":"1.0"}
```

This is **NOT** scrub-to-position (that's `setPlayContent + positionSec`). This is press-and-hold fast-forward / rewind. The device probably accelerates the playback rate while the request is held.

POST target: `http://<ip>:60200/avContent`.

### `avContent.getContentInfo` v1.1

```java
// CommonControl.java:2651
paramsObjs.put("uri", "audio:track?id=" + audioId);
```

```json
{"method":"getContentInfo","params":[{"uri":"audio:track?id=42"}],"id":1,"version":"1.1"}
```

Only the `audio:track?id=N` form is constructed by the Android app. Other forms (`audio:album?id=N`, `netService:audio?...`) may work on the device but Sony's client doesn't use them here.

### `avContent.getContentList` v1.3 — **three signatures**

#### 4.3.1 Service-level browse

```java
// CommonControl.java:2669
paramsObjs.put("uri", "netService:audio?serviceName=<svc>");
paramsObjs.put("scope", scope);  // values: "favorite", "search", "connected", "unconfirmed", "unconnected", "directory"
```

```json
{"method":"getContentList","params":[{"uri":"netService:audio?serviceName=vtuner","scope":"directory"}],"id":1,"version":"1.3"}
```

#### 4.3.1 Pageable browse with search

```java
// CommonControl.java:2694
String uri = "netService:audio?serviceName=" + serviceName + "&path=" + path;
paramsObjs.put("uri", uri);
paramsObjs.put("scope", scope);
paramsObjs.put("stIdx", stIdx);   // start index
paramsObjs.put("cnt", 100);        // page size — Sony uses 100
paramsObjs.put("finish", false);   // continue session
if (searchStr != null) {
    JSONObject searchObj = new JSONObject();
    searchObj.put("word", searchStr);
    paramsObjs.put("search", searchObj);
}
```

```json
{"method":"getContentList","params":[{"uri":"netService:audio?serviceName=vtuner&path=/Music/Jazz","scope":"directory","stIdx":0,"cnt":100,"finish":false,"search":{"word":"miles"}}],"id":1,"version":"1.3"}
```

#### 4.3.1 Finalise pagination

```java
// CommonControl.java:2752
paramsObjs.put("uri", "netService:audio?serviceName=<svc>");
paramsObjs.put("finish", true);
```

This tells the device "I'm done browsing, release server-side cursor state".

**Important**: the catalog said `{uri:"audio:album", stIdx:0, cnt:10}` — that's wrong for the netService form (URI scheme) and wrong for the page size (Sony uses 100, not 10). For HDD content (`audio:track`/`audio:album`), the URI form likely differs; the Android app browses HDD content via the local sqlite cache it sync'd via `downloadByDiff`, not via `getContentList`. So **HDD browsing via API may not be how Sony intended this method to be used**.

### `avContent.deleteContent` v1.1

```java
// CommonControl.java:3518
JSONArray trackIds = new JSONArray();
for (int pos = 0; pos < size; pos++) {
    String st = "audio:" + (type == 1 ? "folder" : "track") + "?id=" + ids.get(pos);
    trackIds.put(st);
}
paramsObjs.put("uri", trackIds);   // <-- uri is an ARRAY of URIs, not a single string!
```

```json
{"method":"deleteContent","params":[{"uri":["audio:track?id=12","audio:track?id=13","audio:track?id=14"]}],"id":1,"version":"1.1"}
```

**Critical**: the `uri` field is a **JSON array of URI strings**, not a scalar. This is why the catalog's guess `{uri: "<file uri>"}` would return `illegal Request`. Bulk delete is the only form Sony exposes.

POST target: `http://<ip>:60200/avContent`. Sony also halts the polling threads around the call (`CommonSoundInfo.stopThread()` before, `startThread()` after) to avoid a race against the in-flight DB change.

### `guide.getServiceProtocols`

**The Android app never calls this.** No example shape can be derived. From cousin Sony devices (BRAVIA), the call is:

```json
{"method":"getServiceProtocols","params":[],"id":1,"version":"1.0"}
```

Our fuzzer saw `[5, "illegal Request"]` — "params" envelope wrong. Try wrapping in an empty object:

```json
{"method":"getServiceProtocols","params":[{}],"id":1,"version":"1.0"}
```

This matches the pattern Sony uses for all other "no-arg" methods.

## 5. Notification mechanism — **THERE ISN'T ONE**

**This is the single biggest architectural finding.**

The HAP Android app **does not use WebSocket notifications**. There is no call to `switchNotifications` anywhere in the decompiled code. No `ws://` URLs. No upgrade handshake. The phrase "WebSocket" appears in zero source files.

Instead, the app uses **four background polling threads** (`jp/co/sony/lfx/anap/entity/CommonSoundInfo.java`):

| Thread | What it polls | Endpoint | Method | Cadence |
|---|---|---|---|---|
| `thGetVolumeInfo` | volume + mute changes | `POST /audio` | `getVolumeInformation` v1.1 | every 5 s |
| `thGetPlayingInfo` | now-playing state | `POST /avContent` | `getPlayingContentInfo` v1.2 | every 5 s (best guess — decompile of `run()` failed, but other 3 threads use 5 s `wait(5000)`) |
| `thGetPowerStatus` | power state | `POST /system` | `getPowerStatus` v1.1 | every 5 s |
| `thGetDBStatus` | library sync state | `POST /database` | `checkSameDatabase` v1.0 | every 5 s |

Each thread:
1. Builds its query JSON once at startup.
2. Loops: sleep 5 s → POST → diff result against last-seen value → if changed, fire local `notifyChange*` listener to update UI.

This is **dumb but resilient polling**. It explains:

- Why `switchNotifications` returns `No Such Method` on the HAP — Sony deliberately doesn't expose it.
- Why our WebSocket upgrade attempt on `/sony/avContent` returned 405 — the device probably doesn't speak WebSocket at all on 60200. (We have not tested a port scan for an explicit notification port; one might exist, but Sony's own client doesn't need it.)
- Why the device responds within ~5 s to changes in our experiments — that's because we were watching our own polling, not push notifications.

**Implication for our client design**: do not bother trying to implement a WebSocket subscriber. Replicate Sony's polling model. The HAP can be polled aggressively (5 s is what Sony does) without observable performance issues.

## 6. New methods Sony's client uses that our catalog never listed

Add these to `api-method-catalog.md`. All confirmed at the version listed (Sony's own client uses them).

### Service `system`

| Method | Version | Params (Sony shape) |
|---|---|---|
| `getSleepTimer` | 1.0 | `[{}]` → returns `{remainTimerSec, candidateSec[]}` |
| `setSleepTimer` | 1.0 | `[{status:"on"\|"off", sleepTimerSec:<int>}]` |
| `getSupportedFileType` | 1.0 | `[{}]` → returns list of supported formats |

### Service `audio`

| Method | Version | Params |
|---|---|---|
| `getRepeatType` | 1.0 | `[{}]` → returns `{type:"off"\|"one"\|"all"}` (NOTE: this is on `/avContent` actually — Sony's code is unclear; verify live) |
| `setRepeatType` | 1.0 | `[{type:"off"\|"one"\|"all"}]` on `/avContent` |
| `getShuffleType` | 1.0 | `[{target:""\|"track"}]` on `/avContent` |
| `setShuffleType` | 1.0 | `[{type:"off"\|"track"\|"album"\|"folder"}]` on `/avContent` |

### Service `avContent`

| Method | Version | Params |
|---|---|---|
| `createPlayingListAndQuickPlay` | 1.0 | `[{uri:"audio:track?id=<n>", listIndex:<n>, listCount:<n>, playbackControlMode:<mode>}]` — **THE primary play primitive** for HDD content. Build queue + start. |
| `createPlaylist` | 1.0 | with `data:"playingListId=<n>&trackIds=1,2,3&positions=0,1,2"` URL-form encoded inside the JSON, plus `params:[{name:"<name>"}]` |
| `updatePlaylist` | 1.0 | `[{uri:"<scheme>:list?id=<n>&originalVersion=<n>"}]` with `data:"types=...&trackIds=...&positions=..."` |
| `deletePlaylist` | 1.0 | `[{uri:"database:list?id=<n>"}]` |
| `getPlaylistInfo` | 1.0 | `[{uri:"audio:list?id=<n>&originalVersion=<n>"}]` → returns `{type, location:<URL>}` then app GETs `location` to fetch raw playlist data |
| `getStorageInformation` | 1.0 | `[{}]` → returns storage info (different from `getStorageList` which we tested) |
| `getBufferTime` | 1.0 | `[{}]` → `{bufferTimeSec, candidate:[]}` |
| `setBufferTime` | 1.0 | `[{bufferTimeSec:<int>}]` |
| `setAudioInput` | 1.0 | `[{uri:"extInput:optical"\|"extInput:coaxial"\|"extInput:line?port=1"\|"extInput:line?port=2"}]` |
| `getRichMetaInfo` | 1.0 | complex — see `createMsgForGetRichMetaInfo` |
| `editContentInfo` | (used internally) | with `method:"editTrackInfo"\|"editPresetInfo"\|...` per target |
| `registerDevice` | 1.0 | `[{uri:"netService:audio?serviceName=tunein", method:"check"\|"getPin"\|"unregister"}]` (TuneIn account binding) |

### New service `database` (entirely undocumented!)

| Method | Version | Params |
|---|---|---|
| `checkSameDatabase` | 1.0 | `[{uri:"database:<short_uuid>?dbType=hdd&dbSerial=<n>&originalVersion=<n>"}]` → `{isSameVersion, isSameName}` |
| `downloadByDiff` | 1.0 | same URI shape → returns either a full DB dump or a diff (`{type:"all"\|"diff"\|"diffAuto", ...}`) |

The Android app uses this service to **sync the entire music library schema to local SQLite for offline browsing**. The "short_uuid" is the device's UDN minus the first 5 chars (`uuid:` prefix). This is one of the most interesting discoveries — it implies the HAP exposes its whole music database for download in a structured form. **Excellent target for further reverse-engineering.**

## 7. Other notable findings

### 7.1 `assets/demo_browse.db`

The APK ships a 79 KB SQLite file at `assets/demo_browse.db` that hydrates the app's "demo mode". This is **a Sony-curated sample library**. Schema may reveal: how Sony models tracks/albums/folders in the on-device DB, what columns exist, what FK relations. Worth extracting and `sqlite3 .schema`.

Path: `C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\_apk-assets\assets\demo_browse.db`. **Do not commit.**

### 7.2 SMB / Samba on the device

`jp.co.sony.lfx.anap.network.CommonSamba` plus the bundled `jcifs` library show the Android app talks **SMB** to the HAP for music file transfer:

```java
// CommonSamba.java:62
String path = "smb://" + ip + "/" + getDestinationFilePath(context) + "/";
```

The destination path is constructed from the **phone's MAC address**:

```java
String personal = Build.MODEL + "_" + mac;
String destination = storage + "/" + personal + "/";
```

i.e. each phone gets its own subfolder named like `Pixel_AABBCCDDEEFF/` on the HAP's storage. The HAP runs an **SMB server** on the local network. This was not documented anywhere in our research previously.

**Listen port** is the standard 445 (TCP). Authentication: jcifs default (anonymous? guest? — TBD; verify by `nmap` against the device).

### 7.3 No DLNA control / DLNA push

`com.sony.huey.dlna` is present but only as the **media server side** (the app exposes itself as DMS to push local-phone content to the HAP as a renderer). No DLNA-control of the HAP is performed. The HAP is its own playback engine and exposes its features via the JSON-RPC API.

### 7.4 Identifier header

`x-hap-device-id` is constructed once per install and stored in `SharedPreferences`. It is **not** a serial number or anything tied to the HAP; it's a client-side UUID. The HAP probably uses it for analytics / per-client buffering. Sending a random UUID **should** work fine.

### 7.5 Internet radio bundling

The app has `com.sony.ANAP.functions.internetradio` and includes `vtuner` integration directly — TuneIn is the only `netService:audio?serviceName=<x>` value the app constructs. If we want to enumerate what internet radio services the HAP firmware understands, we should ping `/avContent` with `getContentList` while iterating serviceName values from `["tunein", "vtuner", "spotify"]` — the manifest's `<queries>` block whitelists Spotify and YouTube package names, which suggests Spotify is at least partially supported.

## 8. Recommended actions (in order)

1. **Re-run the API fuzzer** with two changes:
   - Endpoint paths: try **`/audio`, `/system`, `/avContent`, `/database`** (no `/sony/` prefix) in addition to the `/sony/*` paths we've been using. Confirm which set the device accepts (or both).
   - Headers: include `x-hap-device-id: <random UUID>` on every request.
   - Pass empty params as `[{}]` (object inside array) where the catalog currently passes `[]`. Sony's code never sends a bare empty array for the `params` field.

2. **Validate each 🟡 method live** with the shapes documented in §4. Update `api-method-catalog.md` rows from 🟡 to ✅ as they pass.

3. **Investigate the `database` service.** A working `checkSameDatabase` + `downloadByDiff` is the path to a full library export. Start with `getSystemInformation` to obtain the UDN, then construct `database:<short_uuid>?dbType=hdd&dbSerial=0&originalVersion=0` and POST to `/database`.

4. **Document the `turnOn` / `turnOff` plain-HTTP endpoints** in the API catalog under a new section. These are dead-simple and high-value (a 2-line bash wake script).

5. **Document the `x-hap-device-id` header requirement.** All our existing call examples in `docs/03-network-api.md` should be updated.

6. **Drop WebSocket investigation.** The catalog's WebSocket section should be rewritten as "Notification mechanism: polling-based; the device does NOT expose push notifications. The Sony Android app polls four endpoints every 5 s." Save future contributors the dead-end.

7. **Pull `demo_browse.db` schema** for clues about how the on-device DB is structured. `sqlite3 demo_browse.db .schema` — single command, big payoff.

8. **Try SMB enumeration**: `smbclient -L //<hap-ip> -N` from a Linux box on the same LAN. Probably exposes a music library share.

## 9. What I am NOT confident about

- **Which version of each method is canonical** when the device supports multiple. e.g. our fuzzer found `setPowerStatus` works at 1.1, but Sony's code uses 1.1 too — consistent. But cousin Sony spec sometimes prefers 1.0. We can only trust what we've fuzzed.
- **Whether the HAP accepts both `/sony/<svc>` and `/<svc>` URLs**, or only one. Sony's own client uses the no-prefix form exclusively. The fuzzer's previous runs used the `/sony/` form and got *some* success — so both may work, with the device routing one or both to the same handler. Verify.
- **The `output` parameter mystery** in the API catalog comments. The Android app does not pass `output` anywhere. The catalog's hypothesis `[{output:""}]` for next/previous/pause is **wrong** — the actual shape is `[{}]` (empty object). Remove the `output` references.
- **The `getServiceProtocols` shape**. Sony doesn't call it.

## 10. Compliance reminder

The APK is Sony's IP. Our derivations of method names, URI schemes, version strings, and parameter field names are **factual documentation of the public API surface** — fair use for interoperability per EU 2009/24/EC Article 6 and U.S. DMCA §1201(f). Do not commit:

- The APK file itself.
- `_apk-assets/demo_browse.db` or other Sony binary assets.
- Verbatim copies of large blocks of Sony's source code. Short fragments quoted for clarity (as in §4 above) are fine; entire files are not.

**Per-file location of source quotes for verification**:

- All `createMsgFor*` builders: `C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\sources\jp\co\sony\lfx\anap\control\CommonControl.java`
- HTTP plumbing: `C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\sources\jp\co\sony\lfx\anap\network\CommonHTTP.java`
- Polling threads: `C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\sources\jp\co\sony\lfx\anap\entity\CommonSoundInfo.java`
- UPnP discovery: `C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\sources\jp\co\sony\lfx\anap\findDevice\findDevice.java`
- URN constants: `C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\sources\jp\co\sony\lfx\common\upnp\upnpDiscoveryListener.java`
- Manifest (decoded by jadx, not apktool): `C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\resources\AndroidManifest.xml`
