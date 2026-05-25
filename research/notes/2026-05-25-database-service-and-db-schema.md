# 2026-05-25 — `/sony/database` service + on-device DB schema

Two major discoveries:

1. The `/sony/database` service is live-confirmed (responds to `checkSameDatabase`).
2. The Android APK ships a Sony-curated SQLite (`assets/demo_browse.db`, 79 KB) that exposes the **complete on-device library DB schema**.

Combined, these unlock the path to a full library browser in any future HAP-Revival client.

## 1. `/sony/database/checkSameDatabase` live results

```json
{
  "method": "checkSameDatabase",
  "params": [{"uri": "database:00000000-0000-1010-8000-104FA86F4B84?dbType=hdd&dbSerial=0&originalVersion=0"}],
  "id": 1,
  "version": "1.0"
}
```

Returns:
```json
{
  "result": [{
    "isSameVersion": false,
    "type": "",
    "isSameName": false
  }],
  "id": 1
}
```

The URI is `database:<short_uuid>?dbType=hdd&dbSerial=<n>&originalVersion=<n>` where `<short_uuid>` is the device UDN minus the `uuid:` prefix. We sent `dbSerial=0` and `originalVersion=0` as the "fresh client, no local copy" case — the device correctly reports `isSameVersion: false` and `isSameName: false`.

## 2. `/sony/database/downloadByDiff` — partial

```json
{
  "method": "downloadByDiff",
  "params": [{"uri": "database:<short_uuid>?dbType=hdd&dbSerial=0&originalVersion=0"}],
  "id": 1,
  "version": "1.0"
}
```

Returns:
```json
{
  "result": [{
    "dbType": "",
    "type": "all",
    "location": ""
  }],
  "id": 1
}
```

The shape is right (server accepted), but `location` is empty across all variants tested (`dbSerial=0/1`, `originalVersion=0/1`, no params). Three hypotheses:

- The `dbType=hdd` value in the URI is not the one the server expects (maybe `audio`, `metadata`, `playinglist`, etc.).
- A handshake / initialization call is required first (e.g. `getRichMetaInfo` before `downloadByDiff`).
- The location is empty when nothing has changed since the last `dbSerial`/`originalVersion` known to the server, but the server has no idea what those values "mean" for an anonymous client.

Path forward: capture Sony's Android app on the wire with mitmproxy (or run a separate Android emulator on the LAN) to see the exact preflight calls that come before `downloadByDiff` returns a real location.

## 3. The `recfile` mechanism (NEW)

Discovered by accident: `getPlaylistInfo` returned a location URL pointing to `/sony/avContent/recfile/request4.data`. Fetching that URL with a plain GET returns 40 bytes of **form-urlencoded** data:

```
newVersion=9&types=2&ids=-1&positions=...
```

This is a **generic transport mechanism**: long / structured results from the JSON-RPC API are not returned in the response itself — instead, the API returns a `location` URL pointing to `/sony/avContent/recfile/requestN.data`, and the client fetches the binary/text payload separately. The format is form-urlencoded (matching the `data: "..."` parameter pattern the APK uses for `createPlaylist`/`updatePlaylist`).

Implication: when `downloadByDiff` eventually returns a non-empty location, expect a similar pattern — a `recfile` URL pointing to a much larger payload containing the actual DB diff (probably in tab-separated or form-urlencoded form for incremental update applicability).

## 4. The on-device DB schema (from `assets/demo_browse.db`)

The Sony Android app ships a 79 KB SQLite as a demo / fallback. Its schema **is the actual on-device DB schema** the HAP uses internally — every table, column, and index.

Table summary:

| Table | Purpose | Key columns |
|---|---|---|
| `FT0000` | Root catalog entry (per top-level object) | PROP3601 (id), PROP1086 (import type), PROP7020 (name), PROP7221 (initial), PROP7023, PROPAA90 |
| `FT0002` | **Tracks** (37+ columns) | PROP3601 (id), PROP304B (codec), PROP3046 (play count), PROP3047 (duration), PROP3048 (sample rate), PROP304C (audio bitrate), PROP7045 (genre id), PROP7052 (artist id), PROP706F (composer id), PROP7070 (lyricist id), PROP7020 (track name), PROP2053 (track no), PROP6844 (release date), PROP087E (rating type), PROPB2BB (album id), PROP10DE (audio bit width), PROP207B (update flag), PROP7065 (sort name), PROP7221 (initial) |
| `FT000A` | **Albums** | PROP3601, PROP6844 (release date), PROP78D9 (thumbnail BLOB!), PROPAA10 (has-thumb flag), PROP7020 (album name), PROP7055 (album artist), PROP7065 (sort name) |
| `FT4502` | **Genres** | PROP3601, PROP7020 (genre name) + variants |
| `FT5202` | **Artists** | PROP3601, PROP7020 (artist) + variants |
| `FT6F02` | **Composers** | PROP3601, PROP7020 (composer) + variants |
| `FT7002` | **Lyricists** | PROP3601, PROP7020 (lyricist) + variants |
| `FTF002` | Group memberships (artist↔group, genre↔group) | composite key PROP3601+PROP3006+PROP705E |
| `FTF003` | **Playlists** | PROP3601 (list id), PROP7020 (name), PROP106E (track count), PROPAA70 (modify number) |
| `FTF004` | **Playlist contents** | composite key PROP3601 (track id) + PROP3006 (list id) + PROP2053 (position) |
| `FTF0FF` | Generic key/value | PROP3601 (id), PROPFFF0 (int value), PROPFFF1 (text value) |

Plus standard `android_metadata` (locale).

### Decoded PROP-column dictionary

These hex codes are stable across tables. They follow what looks like a Sony-internal MTP / WMDM property registry:

| PROP code | Meaning | Type | Notes |
|---|---|---|---|
| `PROP087E` | rating type | INT | matches MTP `Rating` |
| `PROP08E8/E9/EA` | SensMe channel 1/2/3 | INT | Sony's mood/energy/cadence axes |
| `PROP106E` | track count | INT | playlist row count |
| `PROP1086` | import type | INT | how the item got into the lib (USB / CD rip / SMB push / etc.) |
| `PROP10A3` | (untyped, likely DSD flag) | INT? | new column added later |
| `PROP10DD` | (likely DSD-related) | INT | added later |
| `PROP10DE` | audio bit width | INT | 16 / 24 / 32 |
| `PROP10E7` | SensMe channel count | INT | usually 3 |
| `PROP2053` | track number / position | INT | per-track or position in playlist |
| `PROP207B` | update flag | INT | indexer marker |
| `PROP3006` | (group id / list id) | INT | varies by context |
| `PROP304B` | codec | INT enum | FLAC / DSF / DFF / WAV / AIFF / ALAC / MP3 / AAC / WMA / ATRAC |
| `PROP304C` | audio bitrate | INT | bps |
| `PROP3046` | play count | INT | |
| `PROP3047` | duration | INT | seconds (probably) |
| `PROP3048` | sample rate | INT | Hz |
| `PROP3601` | **object id** | INT | primary key everywhere |
| `PROP58D3` | (typing unknown) | INT | added later |
| `PROP58DF` | possible play flag | INT | playable y/n |
| `PROP6844` | release date | INT | likely epoch or YYYYMMDD |
| `PROP7007` | (text) | TEXT | added later — possibly URL or metadata location |
| `PROP7020` | **display name** | TEXT | the canonical "name" column everywhere |
| `PROP7023` | (text) | TEXT | secondary name? |
| `PROP7045` | genre id reference | INT | FK to FT4502.PROP3601 |
| `PROP7052` | artist id reference | INT | FK to FT5202.PROP3601 |
| `PROP7055` | album artist name | TEXT | denormalized on FT000A |
| `PROP705E` | group type | INT | composite key in FTF002 |
| `PROP7065` | sort name | TEXT | for collation |
| `PROP706F` | composer id reference | INT | FK to FT6F02.PROP3601 |
| `PROP7070` | lyricist id reference | INT | FK to FT7002.PROP3601 |
| `PROP7221` | initial letter | TEXT | for A-Z jump |
| `PROP78D9` | thumbnail | BLOB | album cover binary |
| `PROPAA90` | (text) | TEXT | added later |
| `PROPAA00` | track name (yomi/phonetic) | TEXT | Japanese reading |
| `PROPAA01..AA08` | (untyped extras) | various | extension columns added per firmware revision |
| `PROPAA10` | has-thumbnail flag | INT | on FT000A |
| `PROPAA11` | album name (yomi) | TEXT | |
| `PROPAA20` | genre name (yomi) | TEXT | |
| `PROPAA30` | artist name (yomi) | TEXT | |
| `PROPAA40` | composer name (yomi) | TEXT | |
| `PROPAA50` | lyricist name (yomi) | TEXT | |
| `PROPAA70` | playlist modify number | INT | revision counter — matches the `newVersion=9` we observed in the recfile |
| `PROPAA71` | playlist name (yomi) | TEXT | |
| `PROPB2BB` | album id reference | INT | FK to FT000A.PROP3601 |
| `PROPFFF0` | generic value (int) | INT | |
| `PROPFFF1` | generic value (text) | TEXT | |

Indexes exist on the obvious browse axes: sort key, initial letter, genre, artist, composer, lyricist, release date, rating, play count, import type.

### Implications for our client

**We can build a full library browser without ever asking the device to browse.** The flow:

1. Get the device UDN (`getSystemInformation` + UPnP descriptor).
2. Call `downloadByDiff` (with the correct URI; this will give us a `location`).
3. GET the `location` to fetch the diff.
4. Apply the diff to a local SQLite using the exact schema above.
5. Browse locally — artists, albums, tracks, genres, playlists, sort/filter however we want.
6. To play a track: call `createPlayingListAndQuickPlay` with `audio:track?id=<PROP3601>`.

This is **exactly what Sony's own Android app does**. The HAP exposes its DB schema to be sync'd to clients; we mirror it.

Library size scaling: the user has ~~thousands of tracks. A full sync via downloadByDiff is probably a few MB of data (form-urlencoded). After the initial sync, the polling thread `thGetDBStatus` calls `checkSameDatabase` every 5 s; when `isSameVersion` flips to true, we know we're in sync. When it flips to false, call `downloadByDiff` again with our current `dbSerial`/`originalVersion` and apply the diff.

## 5. What's blocked

- **`downloadByDiff` returning empty `location`** is the immediate unblock. Three avenues:
  1. mitmproxy capture of Sony's Android app on the wire.
  2. Try alternative `dbType` values: `audio`, `metadata`, `playinglist`, `playingList`, `library`.
  3. Read more of the APK source — there's likely a `setupHttpBuffer` or similar preflight that establishes a session.

- **PROP code dictionary** above is ~60% reverse-engineered. Some columns are tagged but their semantics inferred. Future work: cross-reference with Sony MTP/WMDM property registry, or sniff the device with a real library populated.

## 6. Asset itself

`C:\Users\loutr\Tools\jadx-output\HDDAudioRemote-4.3.1\_apk-assets\assets\demo_browse.db` (79872 bytes). **Not committed to the repo** — Sony copyrighted asset. The schema (above) is fact extracted from it; fair use for interoperability.

The demo DB itself contains 3 sample rows in `FT0000` and is otherwise empty — Sony shipped it for the app's "no device connected" demo mode.
