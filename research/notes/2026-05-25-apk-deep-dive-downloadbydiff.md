# APK deep-dive: downloadByDiff, getRichMetaInfo, and misc

Date: 2026-05-25
Source: `C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\sources\`
Primary target: `jp/co/sony/lfx/anap/control/CommonControl.java`
Polling thread: `jp/co/sony/lfx/anap/entity/CommonSoundInfo.java`

All code below is quoted verbatim from the decompiled jadx output. Line numbers refer to those files.

---

## Section 1: downloadByDiff flow

### 1.1 The single canonical URL shape

`getHttpHost(con)` returns whatever was stored as `KeyHttpHost`, which in turn is the UPnP-advertised `X_ScalarWebAPI_BaseURL` with a literal `"/"` appended at discovery time (`SettingConnectionFragment.java:209`):

```java
lst.setScalarWebAPI_BaseURL(String.valueOf(item.getScalarWebAPI_BaseURL()) + "/");
```

The constants for the four service "leaves" appended after that slash (`CommonControl.java:69-72`):

```java
public static final String API_SERVICES_AUDIO     = "audio";
public static final String API_SERVICES_AV_CONTENT = "avContent";
public static final String API_SERVICES_DATABASE  = "database";
public static final String API_SERVICES_SYSTEM    = "system";
```

So every database-method request is `POST <baseURL>/database`. The leading `/sony/` is whatever the device advertises; the app never hard-codes it. Empirically the HAP-Z1ES advertises `http://<ip>:<port>/sony` so the final URL is `http://<ip>:<port>/sony/database`. (No path "leaks" anywhere in the APK.)

Every request also carries an `x-hap-device-id` header (`CommonHTTP.java:234`):

```java
con.setRequestProperty("x-hap-device-id", CommonPreference.getInstance().getXHapDeviceId(context));
```

Where the value is built in `MainActivity.java:432`:

```java
String hapId = "Android:" + Build.VERSION.RELEASE + ":" + packageInfo.versionName + ":" + fixId;
```

with `fixId = "yyyyMMddHHmmss_<mac_no_colons>"` from `MainActivity.createId()` line 470. So the literal value looks like `Android:10:4.3.1:20240611120030_aabbccddeeff`. Some devices may demand a non-empty header — worth sending an arbitrary plausible value if HAP-Revival sees inconsistent results.

Also note: there is NO leading slash in the JSON-RPC `id` field convention either. Every database/avContent message carries `id:1` (integer). The `getPlayingContentInfo` requests use `id:3` (line 2214) — but this is irrelevant to the database flow.

### 1.2 `checkSameDatabase` request shape (line 1599)

```java
public static String createMsgForCheckSameDatabase(String uuId, String dbName, String dbSerial, int modifyNo) {
    JSONObject jSONObject = new JSONObject();
    JSONArray params = new JSONArray();
    JSONObject paramsObjs = new JSONObject();
    try {
        paramsObjs.put(PARAMS_GET_PLAYING_CONTENT_INFO_URI, "database:" + uuId.substring(5) + "?dbType=" + dbName + "&dbSerial=" + dbSerial + "&originalVersion=" + modifyNo);
        params.put(paramsObjs);
        jSONObject.put(API_METHOD, METHOD_CHECK_SAME_DATABASE);
        jSONObject.put(API_PARAMS, params);
        jSONObject.put("id", 1);
        jSONObject.put("version", API_VERSION_1_0);
```

Resulting JSON:

```json
{
  "method": "checkSameDatabase",
  "params": [{"uri": "database:<uuid_no_prefix>?dbType=hdd&dbSerial=<serial>&originalVersion=<n>"}],
  "id": 1,
  "version": "1.0"
}
```

`uuId.substring(5)` strips the literal `uuid:` prefix off the UDN (the value originates from `upnpDevice.UDN` via `lst.setUuId(item.getRootUuid())` in `SettingConnectionFragment.java:204`).

### 1.3 `downloadByDiff` request shape (line 1617)

Structurally identical, with a different method name:

```java
private static String createMsgForDownloadByDiff(String uuId, String dbName, String dbSerial, int modifyNo) {
    JSONObject jSONObject = new JSONObject();
    JSONArray params = new JSONArray();
    JSONObject paramsObjs = new JSONObject();
    try {
        paramsObjs.put(PARAMS_GET_PLAYING_CONTENT_INFO_URI, "database:" + uuId.substring(5) + "?dbType=" + dbName + "&dbSerial=" + dbSerial + "&originalVersion=" + modifyNo);
        params.put(paramsObjs);
        jSONObject.put(API_METHOD, METHOD_DOWNLOAD_BY_DIFF);
        jSONObject.put(API_PARAMS, params);
        jSONObject.put("id", 1);
        jSONObject.put("version", API_VERSION_1_0);
```

So the on-the-wire body is:

```json
{
  "method": "downloadByDiff",
  "params": [{"uri": "database:<uuid_no_prefix>?dbType=hdd&dbSerial=<serial>&originalVersion=<n>"}],
  "id": 1,
  "version": "1.0"
}
```

### 1.4 `dbType` values that exist in the binary

Constants block (line 435-441):

```java
private static final String SAME_DATABASE_TYPE_ALL = "all";
private static final String SAME_DATABASE_TYPE_DATABASE = "database";
private static final String SAME_DATABASE_TYPE_DB_SERIAL = "dbSerial";
private static final String SAME_DATABASE_TYPE_DB_TYPE = "dbType";
private static final String SAME_DATABASE_TYPE_DIFF = "diff";
private static final String SAME_DATABASE_TYPE_DIFF_AUTO = "diffAuto";
public static final String SAME_DATABASE_TYPE_HDD = "hdd";
private static final String SAME_DATABASE_TYPE_ORIGINAL_VERSION = "originalVersion";
```

And a near-duplicate block at line 89-97:

```java
private static final String BY_DIFF_ALL = "all";
private static final String BY_DIFF_DATABASE = "database";
private static final String BY_DIFF_DB_SERIAL = "dbSerial";
private static final String BY_DIFF_DB_TYPE = "dbType";
private static final String BY_DIFF_DIFF = "diff";
private static final String BY_DIFF_DIFF_AUTO = "diffAuto";
private static final String BY_DIFF_HDD = "hdd";
private static final String BY_DIFF_ORIGINAL_VERSION = "originalVersion";
private static final String BY_DIFF_RADIO = "radio";
```

Note `BY_DIFF_RADIO = "radio"` exists but is never used anywhere in `CommonControl.createMsg…`. Searching, the only callers ever pass `SAME_DATABASE_TYPE_HDD`:

```text
CommonControl.java:590:   JSONObject get = downLoadByDiff(con, SAME_DATABASE_TYPE_HDD, localDbSerial, localDbNo);
CommonControl.java:603:   JSONObject obj = downLoadByDiff(con, SAME_DATABASE_TYPE_HDD, "0", 0);
CommonControl.java:2879:  JSONObject get = downLoadByDiff(context, SAME_DATABASE_TYPE_HDD, localDbSerial, localDbNo);
CommonSoundInfo.java:536: String postStr = CommonControl.createMsgForCheckSameDatabase(..., CommonControl.SAME_DATABASE_TYPE_HDD, ...);
```

So `dbType=hdd` is confirmed. The values `all`, `diff`, `diffAuto`, `database` are **response-side** type discriminators, not request-side `dbType` values. The radio DB (`BY_DIFF_RADIO`) appears never to be downloaded by 4.3.1 — the radio DB has its own separate path through `updateLocalRadioDatabase` at line 628 (which does NOT use `downloadByDiff` at all; it goes through a different endpoint that I did not trace further). There is no other dbType emitted by this app.

### 1.5 Response parsing — the actual state machine

Top-level entry point: `updateLocalDatabase(Context, boolean)` at line 531, called from `updateLocalDatabase(Context, Handler, boolean)` at line 512, which is in turn called from ~12 places (every fragment that does something that mutates server-side DB: edit playlists, add tracks, delete content, etc., plus `LauncherActivity` at startup line 473).

The driver loop (line 576-625) — verbatim minus the demo-mode branch:

```java
int loop = 0;
while (true) {
    if (loop >= 2) {
        break;
    }
    try {
        int localDbNo = TableInfoDao.getModifyNo();
        String localDbSerial = TableInfoDao.getDBSerial();
        if (localDbSerial.isEmpty()) {
            localDbSerial = "0";
        }
        if (!CommonPreference.getInstance().isExistConnectInfo(con)) {
            break;
        }
        JSONObject get = downLoadByDiff(con, SAME_DATABASE_TYPE_HDD, localDbSerial, localDbNo);
        if (get != null) {
            try {
                String type = Common.getString(get, "type");
                if (!"all".equals(type)) {
                    if (!"diff".equals(type) && !"diffAuto".equals(type)) {
                        result = 2;
                        break;
                    }
                    result = diffDbSync(con, get, localDbNo);
                    if (result != 1) {
                        break;
                    }
                    JSONObject obj = downLoadByDiff(con, SAME_DATABASE_TYPE_HDD, "0", 0);
                    result = updateLocalDatabaseAll(obj, isChangeSet);
                    break;
                }
                result = updateLocalDatabaseAll(get, isChangeSet);
                if (result != 1) {
                    break;
                }
                loop++;
            } catch (JSONException e5) {
                loop++;
            }
        } else {
            loop++;
        }
    } catch (Exception e6) {
        DevLog.e(LOG_ENABLED, "err: " + e6.getMessage());
    }
}
```

So the state machine, in order:

1. Read `localDbNo` and `localDbSerial` from the local-side `define` table (see § 1.6 below).
2. POST `downloadByDiff` with those values.
3. Branch on response `type`:
   - **`"all"`** → call `updateLocalDatabaseAll(get, isChangeSet)`. This grabs `result[0].location`, opens it as an HTTP URL, streams the bytes straight into the local DB file (line 3138-3186). The downloaded blob is the *whole SQLite database*. If this succeeds → result=0, break. If it fails it loops up to 2 times.
   - **`"diff"`** or **`"diffAuto"`** → call `diffDbSync(get, localDbNo)` (line 3198). This also streams from `location`, but treats the contents as a serialized history of SQL statements (see § 1.6). After diff-apply success, the loop **immediately re-issues** `downloadByDiff` with `dbSerial="0", originalVersion=0` (i.e. asking for a full reset) and pipes that into `updateLocalDatabaseAll`. So even diff-success ends with a full-DB download. (This second call is essentially a sanity refresh.)
   - **anything else** → `result = 2`, break (error path).
4. If `get == null` (HTTP failure) → `loop++` (retry once).

A second use site at line 2872 (`getDatabaseStatus`) handles the `"diffAuto"` short-poll without retry logic — it's the periodic background "do I need to re-sync?" check.

### 1.6 Why `location` is empty in our request — three hypotheses

The app never expects an empty `location` for `type:"all"`. It would NPE in `updateLocalDatabaseAll` at line 3141:

```java
URL url = new URL(location);
```

(`new URL("")` throws `MalformedURLException`, caught silently and result stays at 1.) So if Sony's server is *legitimately* returning `location:""` to us, that is itself the bug we're hitting. Possible causes ranked by likelihood, all consistent with what's in the binary:

1. **Missing `x-hap-device-id` header** — every request the app sends carries this. If HAP-Revival is omitting it, the device may be entering a "blocked" mode that returns valid-shaped-but-empty payloads. The header value is just `"Android:<os>:<app_ver>:<yyyymmddhhmmss>_<mac>"` — there's no signing, no token, no validation other than "non-empty". (`MainActivity.java:432`)
2. **Bad `uri` shape** — the URI is built by concatenation; if the UUID we strip off has a different prefix (e.g. `urn:` rather than `uuid:`) then `substring(5)` removes wrong characters and `dbType` may parse as malformed. The HAP-Z1ES typically advertises `UDN: uuid:00000000-…`; verify what `getResultObject` of `getSystemInformation` returns and what was learned during discovery.
3. **`originalVersion=-1` from `TableInfoDao.getModifyNo()`'s default**, never normalized in either the diff or all path (line 13-35 of `TableInfoDao.java`):

   ```java
   public static int getModifyNo() {
       int no = -1;
       ...
       return no;
   }
   ```

   Note the app's `updateLocalDatabase` driver (line 582-586) normalizes empty `dbSerial` to `"0"` but **never** normalizes `localDbNo` from `-1` to `0`. So the very first request the app sends, with no local DB present, is literally `dbSerial=0&originalVersion=-1`. If we're sending `originalVersion=0` we are NOT replicating what the app does. The other call site (line 603) explicitly sends `"0", 0`. **Try `originalVersion=-1` — that's what the 4.3.1 app sends on first contact.**

### 1.7 The `define` table — what the local DB has at fields 0 and 1

From `TableInfoDao.java`:

```java
public static int getModifyNo() {
    int no = -1;
    String sql = "SELECT " + CommonDao.DEFINEINTVALUE_FLD_S + " FROM " + CommonDao.DEFINE_TBL_S + " WHERE " + CommonDao.OBJECTID_FLD_S + " = 0";
    ...
}

public static String getDBSerial() {
    String serial = "";
    String sql = "SELECT " + CommonDao.DEFINESTRVALUE_FLD_S + " FROM " + CommonDao.DEFINE_TBL_S + " WHERE " + CommonDao.OBJECTID_FLD_S + " = 1";
    ...
}
```

So `define` has at minimum two rows keyed by `objectId`: row 0 = modify-number (integer), row 1 = DB-serial (string). When HAP-Revival downloads its first full DB, it should pull these fields out to know what to send back on the next checkSameDatabase / downloadByDiff round-trip.

### 1.8 `diffDbSync` — how to apply the diff format (line 3198)

For when we eventually get a non-`"all"` response. Quoted in part:

```java
URL url = new URL(location);
HttpURLConnection conn = getConnection(url);
if (conn != null) {
    BufferedInputStream input2 = new BufferedInputStream(conn.getInputStream());
    ...
    File srcFile = historyDao.initializeLocalDatabase();
    if (srcFile != null) {
        ...
        setOutputStream(null, srcFile, input2);
        historyDao.deleteDBHelper();
        historyDao.createDBHelper();
        ...
        ArrayList<ListHistory> historyArray = new ArrayList<>();
        historyDao.selectHistory(context, historyArray, dbVersion);
        int size = historyArray.size();
        for (int i = 0; i < size; i++) {
            ListHistory history = historyArray.get(i);
            ArrayList<ListHistory> paramArray = new ArrayList<>();
            historyDao.selectParameter(context, paramArray, history.getHistoryId());
            int paramSize = paramArray.size();
            Object[] params = new Object[paramSize];
            for (int j = 0; j < paramSize; j++) {
                ListHistory param = paramArray.get(j);
                byte[] blob = param.getBlolbParam();
                if (blob != null && blob.length > 0) {
                    params[j] = blob;
                } else {
                    String text = param.getTextParam();
                    if (text != null) {
                        params[j] = text;
                    }
                }
            }
            synchronized (CommonDao.mSyncObj) {
                if (paramSize <= 0) {
                    CommonDao.getInstance().getDb().execSQL(history.getSqlState());
                } else {
                    CommonDao.getInstance().getDb().execSQL(history.getSqlState(), params);
                }
            }
        }
        if (size > 0) {
            int maxHistoryId = historyArray.get(size - 1).getHistoryId();
            historyDao.updateDbVersion(maxHistoryId);
        }
        result = 0;
```

So the diff *is itself a SQLite file* — it's downloaded into a transient location (`initializeLocalDatabase`), opened, and a `history`-table inside it is iterated. Each row has a SQL statement (`sqlState`) and parameter blobs/texts; these are then `execSQL`'d against the *real* local DB. After iteration the max `historyId` becomes the new `modifyNo` for the next round.

This means a `diff` response's `location` points at a small SQLite blob with at least these tables: `history(historyId, sqlState, ...)` and a parameter-list table. We don't need to implement diff sync to get the database initially — only `type:"all"` is needed for first-fetch. Diff is an incremental update mechanism.

---

## Section 2: getRichMetaInfo

### 2.1 Endpoint & response shape

`execGetRichMetaInfo` at line 3286:

```java
private static int execGetRichMetaInfo(Context con, String postStr, int candidateIndex, MusicInfo info) {
    Common.setThreadState(false);
    int result = 0;
    String URL = String.valueOf(CommonPreference.getInstance().getHttpHost(con)) + API_SERVICES_AV_CONTENT;
    JSONObject retVal = CommonHTTP.getInstance().execHttpRequest(con, URL, postStr, "", "", CommonHTTP.TIMEOUT_90S);
    JSONObject get = getResultObject(retVal);
```

So `getRichMetaInfo` is `POST <baseURL>/avContent` (not `/database`), 90-second timeout. `getResultObject` (line 2944) returns `result[0]` as a JSONObject — meaning the response shape is:

```json
{"result": [{ "albumTitle": "...", "trackInfo": [...], ... }], "id": 1}
```

…or on error:

```json
{"error": [<code>, "<msg>"], "id": 1}
```

(`error` is an array, the first element is the integer code.)

### 2.2 The 3 distinct `createMsgForGetRichMetaInfo` overloads — full bodies

**Overload A** — folder mode, multiple albums (line 3357):

```java
private static String createMsgForGetRichMetaInfo(String scope, ArrayList<GetMusicInfoDao.MusicInfoFolderItem> folderIdArray, int candidateIndex) {
    ...
    JSONArray targets = new JSONArray();
    JSONArray trackIds = new JSONArray();
    JSONObject targetObjs = new JSONObject();
    int i = 0;
    while (true) {
        ...
        if (i < folderIdArray.size()) {
            int albumId = folderIdArray.get(i).getAlbumId();
            trackIds.put(String.valueOf(folderIdArray.get(i).getTrackId()));
            if (i + 1 == folderIdArray.size() || albumId != folderIdArray.get(i + 1).getAlbumId()) {
                targetObjs = new JSONObject();
                ...
                targetObjs.put(PARAMS_GET_PLAYING_CONTENT_INFO_ALBUM_ID, String.valueOf(albumId));
                targetObjs.put(PARAMS_GET_RICH_META_INFO_TRACKID, trackIds);
                targets.put(targetObjs);
                trackIds = new JSONArray();
                ...
            }
            i++;
        } else {
            jSONObject2.put(ActionLogBuilder.KEY_TARGET, targets);
            jSONObject2.put("scope", scope);
            jSONObject2.put("candidateIndex", candidateIndex);
            jSONArray.put(jSONObject2);
            jSONObject.put(API_METHOD, METHOD_GET_RICH_META_INFO);
            jSONObject.put(API_PARAMS, jSONArray);
            jSONObject.put("id", 1);
            jSONObject.put("version", API_VERSION_1_0);
            ...
        }
    }
}
```

**Overload B** — single album + multiple tracks (line 3404):

```java
private static String createMsgForGetRichMetaInfo(String scope, int albumId, ArrayList<String> trackIdArray, int candidateIndex) {
    ...
    JSONArray trackIds = new JSONArray();
    for (int i = 0; i < size; i++) {
        trackIds.put(trackIdArray.get(i));
    }
    JSONArray targets = new JSONArray();
    JSONObject targetObjs = new JSONObject();
    try {
        targetObjs.put(PARAMS_GET_PLAYING_CONTENT_INFO_ALBUM_ID, String.valueOf(albumId));
        targetObjs.put(PARAMS_GET_RICH_META_INFO_TRACKID, trackIds);
        targets.put(targetObjs);
        jSONObject2.put(ActionLogBuilder.KEY_TARGET, targets);
        jSONObject2.put("scope", scope);
        jSONObject2.put(PARAMS_GET_PLAYING_CONTENT_INFO_ALBUM_ID, String.valueOf(albumId));
        jSONObject2.put(PARAMS_GET_RICH_META_INFO_TRACKID, trackIds);
        jSONObject2.put("candidateIndex", candidateIndex);
        jSONArray.put(jSONObject2);
        jSONObject.put(API_METHOD, METHOD_GET_RICH_META_INFO);
        jSONObject.put(API_PARAMS, jSONArray);
        jSONObject.put("id", 1);
        jSONObject.put("version", API_VERSION_1_0);
```

**Important quirk**: overload B writes `albumID` and `trackID` at BOTH the inner `target[0].*` AND the outer `params[0].*` levels. Probably a refactor artifact — but it's what the app sends on the wire. If you only emit one of the two, the device may reject. Replicate this exactly.

**Overload C** — album-combine (line 3439): same as A but with `scope = "combineAlbumInFolder"` (`Common.SCOPE_COMBINE`) and `candidateIndex = 0` hard-coded.

### 2.3 Exact resulting JSON for overload B (the "normal" case)

For `scope="track"`, `albumId=42`, `trackIdArray=["100","101"]`, `candidateIndex=0`:

```json
{
  "method": "getRichMetaInfo",
  "params": [
    {
      "target": [
        {
          "albumID": "42",
          "trackID": ["100", "101"]
        }
      ],
      "scope": "track",
      "albumID": "42",
      "trackID": ["100", "101"],
      "candidateIndex": 0
    }
  ],
  "id": 1,
  "version": "1.0"
}
```

Note **both `albumID` and `trackID` are STRINGS** (not numbers) — `String.valueOf(albumId)` and `trackIdArray` is `ArrayList<String>`. The trackIds JSONArray contains strings as well.

### 2.4 Allowed `scope` values

From `Common.java`:

```java
public static final String SCOPE_ALBUM = "album";
public static final String SCOPE_COMBINE = "combineAlbumInFolder";
public static final String SCOPE_FOLDER = "folder";
public static final String SCOPE_TRACK = "track";
```

`GetMusicInfoFragment.java:94/130/154` initialises `mScope = "track"` by default and only switches based on what the user clicked from. The driver (line 213) picks overload A vs B based on whether `mScope == "folder"`:

```java
int result = GetMusicInfoFragment.this.mScope.equals("folder") 
    ? CommonControl.getRichMetaInfo(..., GetMusicInfoFragment.this.mScope, folderTrackIds, GetMusicInfoFragment.this.mIndex, musicInfo) 
    : CommonControl.getRichMetaInfo(..., GetMusicInfoFragment.this.mScope, GetMusicInfoFragment.this.mAlbumId, GetMusicInfoFragment.this.mTrackIdArray, GetMusicInfoFragment.this.mIndex, musicInfo);
```

### 2.5 `candidateIndex` — what the previous response of `[1, "Any"]` means

`GetMusicInfoFragment` calls `getRichMetaInfo` in a `while(mIsRoop)` loop, incrementing `mIndex` on each `acquired` response (line 223). The Sony Gracenote-style metadata service returns multiple "candidate" matches for a CD, and `candidateIndex` selects which one. The user starts at 0 (line 207).

The `annotation` field in the response controls the loop:

```java
private static final String STATUS_ACQUIRED = "acquired";
private static final String STATUS_ACQUIRING = "acquiring";
private static final String STATUS_ALL_ACQUIRED = "allAcquired";
```

Logic (line 214-235):
- `acquired` → keep this candidate, `mIndex++`, ask for next one.
- `acquiring` → server still working; sleep 3000 ms and re-poll same index.
- `allAcquired` → no more candidates; stop.

A response of `[1, "Any"]` from the wire layer (i.e. JSON-RPC `{"error":[1, "Any"]}` ?) suggests a malformed request — the device returned error code 1 with descriptive "Any" string. Most likely cause: **mis-named keys** or missing the outer-level duplicated `albumID`/`trackID` from overload B. Re-check the exact JSON your client emits against § 2.3.

The `[{uri:"audio:track?id=N"}]` you're seeing back may be a placeholder result fragment — it doesn't match any of the response keys the app parses (line 3308-3338, which expect `albumTitle`, `albumGenre`, `albumReleaseYear`, `albumArtist`, `albumTrackCount`, `annotation`, `acquireErrorCode`, `trackInfo[]` with `number`/`title`/`artist`/`genre`/`releaseYear`/`fileName`/`updateType`). If the device is returning a `uri` it's probably bouncing your request without parsing it.

### 2.6 Response keys the client expects (line 3308-3338)

The Java reads exactly these keys off `result[0]`:

| Key | Type | Notes |
|-----|------|-------|
| `coverArtUrl` | string | URL — used to fetch JPEG separately |
| `albumTitle` | string | |
| `albumGenre` | string | |
| `albumReleaseYear` | string | |
| `albumArtist` | string | |
| `albumTrackCount` | string | |
| `annotation` | string | one of `acquired` / `acquiring` / `allAcquired` |
| `acquireErrorCode` | int | |
| `trackInfo` | array | each has `number`, `title`, `artist`, `genre`, `releaseYear`, `fileName`, `updateType` |

---

## Section 3: Misc findings

### 3.1 setFavorite (line 1310, dispatch via editContentInfo)

`setFavorite` always goes through `editContentInfo`. The full message body (line 2223-2261):

```java
private static String createMsgForSetFavorite(Context con, String id, String playlistName, String value, boolean isAudio, String serviceName) {
    ...
    JSONObject favObj = new JSONObject();
    favObj.put(CONTENT_INFO_TAG_URI, "meta:favorite");
    favObj.put("value", value);
    editInfos.put(favObj);
    JSONObject playlistNameObjs = new JSONObject();
    playlistNameObjs.put(CONTENT_INFO_TAG_URI, "meta:playlistName");
    playlistNameObjs.put("value", playlistName);
    editInfos.put(playlistNameObjs);
    if (isAudio) {
        contentUri = String.format("audio:track?id=%s", id);
    } else {
        contentUri = String.format("netService:audio?serviceName=%s&id=%s", serviceName, id);
        if (serviceName.equals(InternetRadioConstant.SPOTIFY)) {
            method = CONTENT_INFO_EDIT_PRESET_INFO;
        }
    }
    targetObjs.put(CONTENT_INFO_CONTENT_URI, contentUri);
    targetObjs.put(CONTENT_INFO_EDIT_INFO, editInfos);
    jSONArray2.put(targetObjs);
    jSONObject2.put(ActionLogBuilder.KEY_TARGET, jSONArray2);
    jSONObject2.put(API_METHOD, method);  // editTrackInfo or editPresetInfo
    jSONArray.put(jSONObject2);
    jSONObject.put(API_METHOD, METHOD_EDIT_CONTENT_INFO);
```

So:

```json
{
  "method": "editContentInfo",
  "params": [{
    "target": [{
      "contentUri": "audio:track?id=42",
      "editInfo": [
        {"tagUri": "meta:favorite", "value": "favorite"},
        {"tagUri": "meta:playlistName", "value": "<name or empty>"}
      ]
    }],
    "method": "editTrackInfo"
  }],
  "id": 1, "version": "1.0"
}
```

URL: `POST /sony/avContent`. The `value` for `meta:favorite` can be `"favorite"`, `"dislike"`, or `"normal"` (the three enum values for `CONTENT_LIST_FAVORITE_TYPE_*` in line 140-142):

```java
public static final String CONTENT_LIST_FAVORITE_TYPE_DISLIKE = "dislike";
public static final String CONTENT_LIST_FAVORITE_TYPE_FAVORITE = "favorite";
public static final String CONTENT_LIST_FAVORITE_TYPE_NORMAL = "normal";
```

For Spotify (only), the inner `method` switches to `editPresetInfo`.

### 3.2 editContentInfo dispatch table

All `editContentInfo` callers in the binary, with the inner `method` they use:

| Outer method | Inner method | URI shape | Purpose |
|--------------|--------------|-----------|---------|
| `editContentInfo` | `editTrackInfo` | `audio:track?id=N` | Edit favorite/playlist-name (line 2254) |
| `editContentInfo` | `editPresetInfo` | `netService:audio?serviceName=spotify_connect&id=N` | Edit Spotify preset (line 2247) |
| `editContentInfo` | `editTrackInfo` | `audio:track?id=N` with `albumID`+`candidateIndex` | Set music metadata after gracenote-style lookup (line 2312) |
| `editContentInfo` | `editTrackInfo` | `""` (empty), with `albumID` | Album-combine grouping (line 2366) — combines multiple discs into one album |
| `editContentInfo` | `editTrackInfo` | various | sensMe add/edit (line 2449/2455) |
| `editContentInfo` | `deleteSensMe` | `audio:track?id=N` | Delete from sensMe (line 2451) |
| `editContentInfo` | `resetSensMe` | (depends on editType) | Reset sensMe (line 2453) |
| `editContentInfo` | `editSensMe` | (sensMe-style URI) | Edit sensMe entry (line 2455) |
| `editContentInfo` | `resetPresetInfo` | `netService:audio?serviceName=spotify_connect` | Reset Spotify presets (line 2277) |

### 3.3 dsdRemastering / dsee / sound-settings enum values

Full set of targets (line 449-458):

```java
public static final String SOUND_SETTINGS_ALL = "";
public static final String SOUND_SETTINGS_DSD_REMASTERING = "dsdRemastering";
public static final String SOUND_SETTINGS_DSEE = "dsee";
public static final String SOUND_SETTINGS_DSEEHX = "dseeHX";
public static final String SOUND_SETTINGS_GAPLESS_PLAYBACK = "gaplessPlayback";
public static final String SOUND_SETTINGS_OVERSAMPLING = "oversampling";
public static final String SOUND_SETTINGS_TONE_CONTROL_BASS = "toneControlBass";
public static final String SOUND_SETTINGS_TONE_CONTROL_BYPASS = "toneControlBypass";
public static final String SOUND_SETTINGS_TONE_CONTROL_TREBLE = "toneControlTreble";
public static final String SOUND_SETTINGS_VOLUME_NORMALIZATION = "volumeNormalization";
```

All binary toggles send `value: "on"` or `value: "off"`. Example (line 2989):

```java
if (value == 0) {
    valueStr = "off";
} else {
    valueStr = "on";
}
if (CommonControl.setSoundSettings(... CommonControl.SOUND_SETTINGS_DSD_REMASTERING, valueStr)) {
```

Bass/treble take numeric strings (no example in `CommonControl.java` but the menu code at `CommonFragmentActivity.java:4035` passes `String.valueOf(value)`).

Message body for setSoundSettings (line 2131):

```java
settingsObjs.put(ActionLogBuilder.KEY_TARGET, target);
settingsObjs.put("value", value);
settings.put(settingsObjs);
jSONObject2.put(PARAMS_SET_SOUND_SETTINGS_SETTINGS, settings);
...
jSONObject.put(API_METHOD, METHOD_SET_SOUND_SETTINGS);
```

So:

```json
{"method": "setSoundSettings", "params": [{"settings":[{"target":"dsdRemastering","value":"on"}]}], "id":1, "version":"1.0"}
```

**Critical**: `setSoundSettings` posts to `<baseURL>"audio"` (line 1260), not `avContent`:

```java
public static boolean setSoundSettings(Context con, String target, String value) {
    String URL = String.valueOf(CommonPreference.getInstance().getHttpHost(con)) + "audio";
```

This is the *only* place the literal string `"audio"` (not `API_SERVICES_AUDIO`) is concatenated. So URL = `<baseURL>/audio` for sound-settings calls. Verify your HAP-Revival doesn't accidentally route this to `/avContent`.

### 3.4 getRepeatType / getShuffleType — what `target` values are sent

Repeat: no `target` parameter at all. `createMsgForGetRepeatType` at line 2042 sends an empty params object `{}`. The set-side maps to `"off"`, `"oneTrack"` (constant `REPEAT_TYPE_ONE`, value not shown but referenced), or `"all"`.

Shuffle: `createMsgForGetShuffleType` (line 2109) only includes `target` if non-empty:

```java
if (target != null) {
    try {
        if (!target.isEmpty()) {
            paramsObjs.put(ActionLogBuilder.KEY_TARGET, target);
        }
    }
}
```

Callers (line 1227-1232):

```java
public static int getShuffleType(Context con) {
    return getShuffleType(con, "");
}

public static int getTrackShuffleType(Context con) {
    return getShuffleType(con, "track");
}
```

So the 4.3.1 app **only ever sends `target:""` (omitted) or `target:"track"`**. It does **not** send `"audio"` or `"spotify"` despite `SHUFFLE_TARGET_SPOTIFY = "spotify"` being declared as a constant (line 443). The `SHUFFLE_TARGET_*` constants appear unused in this APK. The device evidently accepts other strings (your `"audio"` and `"spotify"` empirical results), but the app doesn't exercise them.

Set-side shuffle values (line 2076):

```java
case 0: type = "off"; break;
case 1: type = "track"; break;
case 2: type = Common.SCOPE_ALBUM; break;  // "album"
case 3: type = "folder"; break;
```

### 3.5 Spotify wiring

`InternetRadioConstant.java`:

```java
public static final String SPOTIFY = "spotify_connect";
public static final String RADIKO = "radiko";
public static final String TUNEIN = "tunein";
```

Spotify is treated as just-another-`netService`. URI shape: `netService:audio?serviceName=spotify_connect&id=<id>` (or with `&type=streams` per line 2738). The only branching:

- `setFavorite` uses `editPresetInfo` instead of `editTrackInfo` (line 2246-2248).
- `createMsgForResetPlaylist` resets Spotify connect specifically using `resetPresetInfo` against URI `netService:audio?serviceName=spotify_connect` (line 2274). This is the "log out / clear" function for Spotify.
- `PlaybackActivity.java:591` allows the `"download"` playbackType for Spotify specifically.
- There's no separate Spotify-search or Spotify-auth code path visible in `CommonControl` — that's all device-side.

### 3.6 Connection-setup oddity: setHttpHost in two places

`CommonHTTP.setHttpHost` (line 86) stores the host in the singleton AND `CommonPreference.setHttpHost` (line 304) stores in shared-prefs. Both are set during connect (`SettingConnectionFragment.java:356, 463`). The HTTP layer reads from `CommonPreference` though, so the singleton copy is dead code. Just noting.

### 3.7 `id` field convention

| Method | id value | Notes |
|--------|----------|-------|
| Most | 1 | Both fixed integer |
| `getPlayingContentInfo` (some calls) | 3 | line 2214 |
| Various | constant `API_ID_*` | Unused outside of declarations |

The device probably doesn't care about `id`. We've sent `id:1` already and it works.

### 3.8 No gracenote / no firmware-fetch in client

Grep for `gracenote`, `cddb`, `firmware`, `swUpdate`, `getSWUpdate` returned no hits. The metadata enrichment (`getRichMetaInfo`) is a thin RPC against the device — the device itself contacts Gracenote (or whatever). The Android app never makes outbound non-HAP HTTP calls for metadata or firmware.

---

## Section 4: Dead ends / things I couldn't find

1. **The exact wire format of the diff blob**. We know it's a SQLite file with a `history` table and (probably) a `parameter` table, accessed via `HistoryDao.selectHistory` and `HistoryDao.selectParameter`. I did not read `HistoryDao.java`. If you ever need to consume diffs, start with `jp/co/sony/lfx/anap/dao/HistoryDao.java`.
2. **`updateLocalRadioDatabase`** at line 628 — uses a different code path. I did not trace it. If radio favorites matter, dig there.
3. **The `getMusicInfoSearchInfo` / search-side RPCs** — `metaUri` variants exist but I didn't catalogue them. Outside scope of the request.
4. **No CONFIRMED reason why the device returns `location:""` for HAP-Z1ES**. The hypotheses in § 1.6 are the leading candidates but I have no decompile evidence pointing to "if X then return empty location". The server-side behaviour is opaque to the APK. Two most actionable items for the user to try:
   - **Send `originalVersion=-1`** (matching first-contact behaviour at line 582-590) instead of 0.
   - **Set the `x-hap-device-id` header** to a non-empty value.
5. **Whether the HAP-Z1ES expects `dbType=hdd` or something else**. The app only ever sends `hdd`. The `BY_DIFF_RADIO = "radio"` constant exists unused. If `dbType=hdd` empirically returns `dbType:""` in the response, *that may itself be the smoking gun* — try `dbType=radio` and see what comes back, or try omitting `dbType` entirely.
6. **`isExistConnectInfo`** — gates the entire flow at line 587. Just a presence check on stored prefs; not a real authentication step.
