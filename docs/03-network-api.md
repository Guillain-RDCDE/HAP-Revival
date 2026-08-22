# Network API

How the HAP-Z1ES talks to the world over the LAN.

## Open ports (factory firmware 19404R)

| Port | Proto | Service | Notes |
|---|---|---|---|
| 139 | TCP | NetBIOS Session | Samba 3.0.37 |
| 445 | TCP | SMB | Samba 3.0.37 — see [`04-smb.md`](04-smb.md) |
| 1900 | UDP | SSDP | UPnP discovery, server banner `Linux/3.0 UPnP/1.0 Sony-HAP/1.0` |
| 60100 | TCP | HTTP (lighttpd) | UPnP device description + embedded web UI |
| 60200 | TCP | HTTP (lighttpd) | **JSON-RPC ScalarWebAPI** — the control plane |

**Not open** (verified empirically): 22 (SSH), 23 (telnet), 80 (HTTP), 443 (HTTPS), 5000, 8000, 8080, 8443, 10000 (Sony Home Audio API on cousin devices), 54480 (Sony Personal Audio API), 52323 (BRAVIA), 33335 (Sony receiver "External Control", per the Crestron STR-DN1050 module — refused, 2026-08-21).

**Implication**: the alternate Sony ports referenced in `python-songpal#29` are **not** used by the HAP — the HAP family is its own generation with its own port assignment. Don't waste time probing those.

Three Sony generations, three unrelated control planes: receivers of 2014 on **raw TCP 33335**, the HAP of 2014 on **HTTP 60200**, the STR-DN1080 of 2017 on **ScalarWebAPI 10000**. "Sony device, similar year" predicts nothing about the protocol. Only the HAP-S1 shares the Z1ES's. See [`08-prior-art.md`](08-prior-art.md) §6b.

## SSDP discovery

A standard `M-SEARCH * HTTP/1.1` to `239.255.255.250:1900` returns five replies, one for each advertised service:

```http
HTTP/1.1 200 OK
CACHE-CONTROL: max-age=1800
LOCATION: http://192.168.1.28:60100/hap.xml
SERVER: Linux/3.0 UPnP/1.0 Sony-HAP/1.0
ST: upnp:rootdevice
USN: uuid:00000000-0000-1010-8000-<wifi-mac-no-colons>::upnp:rootdevice
```

Also advertised:

- `urn:schemas-upnp-org:device:Basic:1`
- `urn:schemas-sony-com:service:ScalarWebAPI:1`
- `urn:schemas-sony-com:service:MusicConnect:1`

The UUID format is `00000000-0000-1010-8000-<12 hex chars>`. The last 12 hex chars are the **Wi-Fi MAC** (without colons), not the Ethernet MAC.

## UPnP device description (port 60100)

`GET http://<ip>:60100/hap.xml` returns the standard UPnP root device document, including the X_ScalarWebAPI extension:

```xml
<av:X_ScalarWebAPI_DeviceInfo xmlns:av="urn:schemas-sony-com:av">
  <av:X_ScalarWebAPI_Version>1.0</av:X_ScalarWebAPI_Version>
  <av:X_ScalarWebAPI_BaseURL>http://<ip>:60200/sony</av:X_ScalarWebAPI_BaseURL>
  <av:X_ScalarWebAPI_ServiceList>
    <av:X_ScalarWebAPI_ServiceType>guide</av:X_ScalarWebAPI_ServiceType>
    <av:X_ScalarWebAPI_ServiceType>system</av:X_ScalarWebAPI_ServiceType>
    <av:X_ScalarWebAPI_ServiceType>audio</av:X_ScalarWebAPI_ServiceType>
    <av:X_ScalarWebAPI_ServiceType>avContent</av:X_ScalarWebAPI_ServiceType>
  </av:X_ScalarWebAPI_ServiceList>
</av:X_ScalarWebAPI_DeviceInfo>
<av:X_HAP_DeviceInfo xmlns:av="urn:schemas-sony-com:av">
  <av:X_HAP_Version>0019404R</av:X_HAP_Version>
  <av:X_HAP_MACAddr>80:56:f2:85:0e:27</av:X_HAP_MACAddr>
</av:X_HAP_DeviceInfo>
```

Other endpoints on port 60100:

- `/HAP.html` → 301 to `/HAP_app.html` — a 272 KB HTML/JS embedded admin UI (CSS comments in Japanese — internal Sony tooling, not designed for end users).
- `/ScalarWebAPI_SCPD.xml` — UPnP SCPD descriptor (essentially empty — the real API is the JSON-RPC below).
- `/MusicConnect_SCPD.xml` — declares `TransportState` (STOPPED/PLAYING/PAUSED_PLAYBACK/NO_MEDIA_PRESENT) and `LastChange` evented variables.
- `/HAP-Z1ES_120.png`, `/HAP-Z1ES_48.png`, etc. — device icons.

### The second API: REST on the same port

Port 60200 serves **two** APIs. Besides the JSON-RPC ScalarWebAPI below, there is a REST surface —
the one the embedded `HAP_app.html` admin UI calls, and the one the Crestron control module speaks
exclusively. It splits in two, and the two halves have opposite fates on 19404R:

- **`/sony/contentplayer/v100/...` — alive.** Power, transport, now-playing, sound settings,
  external input, and a single `POST …/operation` endpoint for every write. Verified live
  2026-08-20. Fully mapped in
  [`research/notes/2026-08-20-crestron-module-teardown.md`](../research/notes/2026-08-20-crestron-module-teardown.md).
- **`/sony/contentdb/v100/...` — mostly dead, but not entirely.** The library half
  (`audio/{albums,artists,genres,tracks,playlists}`, `services/{sensme,favorite,directory}`) **hangs
  and times out (0 bytes)** on every listing and metadata path.

  **Cover art is the exception and it works** (verified 2026-08-22):
  `GET /sony/contentdb/v100/audio/albums/images/cover_art/<ID>` returns **200, `image/jpeg`, in
  ~0.2 s**, while `GET /sony/contentdb/v100/audio/albums/<albumid>` on the *same album* hangs. So
  the daemon still serves part of this tree; only the database-backed endpoints are unresponsive,
  which is what you would expect if the backing service was removed rather than the routes.

  The player itself still emits `contentdb` URLs. A `playinginfo` response for HDD content embeds
  `album.url`, `album.image.url`, `album.tracks_url` and `track.url`, all pointing into this API —
  of those, only the image one answers. Firmware that hands out links to its own dead endpoints is
  further evidence of withdrawal rather than of something never implemented.

The hang is not the generic unknown-path behaviour: an unknown path under `/sony` 404s in
milliseconds, and so does `/sony/contentdb/v100` itself. Only its leaves hang. The route is
registered and its handler never answers — a feature that shipped in firmware `0017310R` (which the
2016 Crestron module targets) and was later disabled. `HAP_app.html` is therefore not a UI pointed
at a backend this device never had; it is a UI for a backend this device **lost**.

Until that changes, reach the library via the JSON-RPC `avContent.*` methods, or read it off disk
([`09-disk-layout.md`](09-disk-layout.md)).

**Trap — the daemon serialises requests.** While a `contentdb` request is pending, *every* endpoint
times out, including ones that answered seconds earlier; it recovers on its own once the pending
request is abandoned. Probe sequentially, with a known-good request as a health check between each,
or you will record false negatives across the whole surface.

### Genuinely vestigial

- **`MusicConnect`** — declared in the UPnP description, but `POST /MusicConnect/control` returns **404**.

## JSON-RPC ScalarWebAPI (port 60200)

This is the real control plane. Every endpoint is `POST http://<ip>:60200/sony/<service>` with a JSON-RPC body:

```json
{
  "method": "<methodName>",
  "id": 1,
  "params": [...],
  "version": "<version>"
}
```

Services exposed:

- `/sony/system` — power, system info, network settings
- `/sony/audio` — volume, sound settings (DSEE, DSD remastering, gapless, oversampling)
- `/sony/avContent` — playback control, library browse, now-playing info
- `/sony/guide` — API introspection (mostly disabled on HAP — `getMethodTypes` returns `{"results": []}`)

### Quirks observed

- **Per-method versioning is non-uniform.** Each method advertises its own version, and the server returns `error: [14, "Unsupported Version"]` if you call the wrong one. There is no `1.0` for everything. See [`research/api-method-catalog.md`](../research/api-method-catalog.md) for the working version of each known method.
- **HTTP `Expect: 100-continue` triggers `417 Expectation Failed`.** Most Python and PowerShell clients send this header by default; you must disable it. It only bites on requests *with a body*, so reads work fine and writes fail — which reads as a syntax problem and isn't one. (Cost a contributor an evening on 2026-08-21.)
  - Python `requests`: `session = requests.Session(); session.headers.update({'Expect': ''})`
  - Python stdlib (`http.client`, `urllib`): unaffected, sends no `Expect`.
  - PowerShell `Invoke-RestMethod` / `Invoke-WebRequest`: `[System.Net.ServicePointManager]::Expect100Continue = $false`. **Set it before the first request to that host** — `ServicePoint` copies the value when it is created and ignores later changes, so putting the line after a GET silently does nothing. Reproduced and fixed on PowerShell 5.1 against a Z1ES, 2026-08-21: `$true` → `417`, `$false` → `200`.
  - `curl` / `curl.exe`: unaffected below 1 KB of body; force it off with `-H "Expect:"` if needed.
  - Note that in Windows PowerShell 5.1 `curl` is an **alias for `Invoke-WebRequest`**, not curl. Call `curl.exe` explicitly, or the `-X`/`-H`/`-d` flags will be misparsed.
- **Introspection is neutered.** `getMethodTypes` returns `{"results": []}` at every version on every service, and `getSupportedApiInfo` returns `[12, "No Such Method"]`. The full method dictionary has been recovered via APK decompile (see [`research/notes/2026-05-25-apk-decompile-findings.md`](../research/notes/2026-05-25-apk-decompile-findings.md) and [`research/notes/2026-05-25-apk-deep-dive-downloadbydiff.md`](../research/notes/2026-05-25-apk-deep-dive-downloadbydiff.md)) plus live fuzzing.
- **Response bytes are UTF-8 JSON.** Some libraries return them as `byte[]` — decode with UTF-8 before parsing.
- **CORS: permissive on origin, silent on headers — which blocks browser clients that set `Content-Type`.** Characterised 2026-08-22. The player answers `OPTIONS` with `200`, echoes your `Origin` straight back in `Access-Control-Allow-Origin`, and advertises `Access-Control-Allow-Methods: GET, POST, OPTIONS`. But it **never sends `Access-Control-Allow-Headers`**. So:
  - A `fetch`/XHR that sets **no** `Content-Type` is a *simple* request, skips the preflight, and works — and because the origin is echoed, the page can even read the reply.
  - Adding `Content-Type: application/json` makes it *non-simple*, forces a preflight, and the preflight fails for want of `Access-Control-Allow-Headers`. The browser reports a generic network error, which reads like the device being unreachable. It isn't.
  - **The device does not need the header** — it parses a JSON body without it (verified). For a pure browser client, simply don't set it.
  - This does not affect clients that go through a local server (our [`webui.py`](../tools/webui.py) proxies, so it is immune), nor `curl`, nor any non-browser client.

### Sample working call

```bash
curl -X POST http://192.168.1.28:60200/sony/avContent \
  -H 'Content-Type: application/json' \
  --data '{"method":"getPlayingContentInfo","id":1,"params":[],"version":"1.2"}'
```

Returns (formatted):

```json
{
  "id": 1,
  "result": [{
    "title": "Dan té dinyé la",
    "artist": "Nahawa Doumbia",
    "albumName": "La grande cantatrice Malienne vol. 3",
    "fileName": "02 - Nahawa Doumbia - Dan té dinyé la.flac",
    "uri": "audio:track?id=163756",
    "albumID": "audio:album?id=11781",
    "playlistUri": "audio:playinglist?id=69",
    "storageUri": "storage:usb1",
    "audioInfo": [{"codec":"flac","frequency":"44100","bandwidth":"16","bitrate":"1001000"}],
    "audioCodec": ["flac"],
    "audioFrequency": ["44100"],
    "bandwidth": "16",
    "bitrate": "1001000",
    "durationMsec": 274000,
    "positionMsec": 110000,
    "state": "PLAYING",
    "shuffleType": "off",
    "repeatType": "off",
    "playbackControlMode": "folder",
    "playlistModifiedVersion": 7,
    "favoriteType": "normal",
    "listCount": 4,
    "listIndex": 1,
    "coverArtUrl": "http://192.168.1.28:60200/sony/avContent/storage/cover_art/A0002E05",
    "backgroundColorR": 93,
    "backgroundColorG": 160,
    "backgroundColorB": 80,
    "backgroundColorA": 255,
    "composer": "Nahawa Doumbia"
  }]
}
```

Notice the typo `playinglist` (instead of `playlist`) — preserved here verbatim because that's the actual URI scheme. Future code that parses this must match the typo.

### URI schemes observed

| Scheme | Example | Meaning |
|---|---|---|
| `audio:track?id=NNN` | `audio:track?id=163756` | A single track in the library DB |
| `audio:album?id=NNN` | `audio:album?id=11781` | An album in the library DB |
| `audio:artist?id=NNN` | (inferred) | An artist |
| `audio:playinglist?id=NNN` | `audio:playinglist?id=69` | A playlist (note typo) |
| `storage:usb1` | `storage:usb1` | The USB-attached external drive |
| `storage:internal` | (inferred) | The internal HDD |

### Cover art

`http://<ip>:60200/sony/avContent/storage/cover_art/<8-hex-id>` returns the album art as JPEG (probably). The 8-hex ID is opaque — it does not match the album ID in `audio:album?id=NNN` directly.

## Real-time updates — push notifications over UDP

> **Corrected 2026-08-20.** This section previously stated that the HAP exposes no push mechanism.
> That was wrong. The 2026-05-25 APK decompile searched for `switchNotifications` and for WebSocket
> and correctly found neither — but the mechanism is neither of those, and Sony's own Android app
> simply does not use it. Found in the Crestron module and **verified live on 19404R**.

**The HAP pushes events as pseudo-HTTP `NOTIFY` datagrams over UDP.** Subscribe:

```http
POST http://<ip>:60200/sony/notification/status
Content-Type: application/json; charset=UTF-8

{"status": "enable", "port": 9999}
```

```json
{ "timeout": 300, "port": 9999 }
```

`timeout` is the subscription lifetime in seconds — re-arm every ~250 s. Subscribe only while
`power_state` is `on`. The device then sends to `<your-ip>:<port>` from `<hap-ip>:60200`:

```http
NOTIFY * HTTP/1.1
Content-Length: 112
Content-Type: application/json
SEQ: 1
X-ContentServiceHostUUID: uuid:00000000-0000-1010-8000-104FA86F4B84

{ "event": "playingtrackChanged", "url": "http://192.168.1.28:60200/sony/contentplayer/v100/playinginfo" }
```

The event says *what changed and where to read it*; it does not carry the new state — GET the `url`.
**Every event is transmitted three times with the same `SEQ`**, so deduplicate on `SEQ`.
`X-ContentServiceHostUUID` follows the SSDP UUID format, so one listener can serve several HAPs.

| Event | Read back from | Status on 19404R | Fires when |
|---|---|---|---|
| `playqueueChanged` | `…/v100/playqueue` | ✅ **observed** | The play queue is replaced — immediately, <0.5 s |
| `playingtrackChanged` | `…/v100/playinginfo` | ✅ **observed** | The new track actually loads — ~7 s after the queue change |
| `playinginfoChanged` | `…/v100/playinginfo` | ✅ **observed** | Pause, and resume |
| `volumeChanged` | `…/v100/volumelevel` | ⬜ not observed | Expected never on a Z1ES, which has no volume stage. Should fire on an S1. |
| `powerstateChanged` | `…/v100/powerstate` | ⬜ not observed | Would need a standby cycle; not run on a machine whose owner is away |

Measured 2026-08-22 by subscribing and then driving the player through queue changes, pause and
resume. Note the two-stage pattern: a queue change emits `playqueueChanged` at once and
`playingtrackChanged` several seconds later when the track is really playing. A client that only
watches one of them will either act on a track that has not started, or lag the change.

**Sound settings emit nothing.** Writing a sound setting (`setsoundsetting`) produced no event at
all. There is no `soundSettingChanged`. Anything that changes DSEE, DSD remastering, gapless,
oversampling or tone control must be discovered by re-reading — push will not tell you.

On Windows, send one datagram outbound from the listening socket to the HAP before subscribing —
otherwise Windows Firewall drops the unsolicited inbound UDP.

[`tools/hap_notify.py`](../tools/hap_notify.py) implements all of this:

```bash
python tools/hap_notify.py <hap-ip> --follow
```

Note that `switchNotifications` (the WebSocket mechanism used on cousin devices) really is absent —
that part of the earlier finding stands. The two are unrelated mechanisms.

### Polling, as a fallback

Sony's own app polls rather than subscribing. Any client should now prefer the push mechanism above
and keep this as a fallback:

| Thread | Endpoint | Method | Cadence |
|---|---|---|---|
| Volume + mute | `POST /sony/audio` | `getVolumeInformation` v1.1 | 5 s |
| Now-playing | `POST /sony/avContent` | `getPlayingContentInfo` v1.2 | 5 s |
| Power | `POST /sony/system` | `getPowerStatus` v1.1 | 5 s |
| Library sync state | `POST /sony/database` | `checkSameDatabase` v1.0 | 5 s |

Sony's "official example code" repo (`sonydevworld/audio_control_api_examples`) **does** demonstrate `switchNotifications` over WebSocket, but for *cousin* devices (BRAVIA TVs, STR-DN receivers, SRS speakers). The HAP family is a different generation and never picked up that capability.

## Methods we've confirmed working

See [`research/api-method-catalog.md`](../research/api-method-catalog.md) for the living catalog with exact versions and parameter shapes.

## Reference: cousin-device documentation we can transpose

- [Sony BRAVIA Pro REST API spec](https://pro-bravia.sony.net/develop/integrate/rest-api/spec/) — the most exhaustive Sony-published method/version dictionary.
- [`rytilahti/python-songpal`](https://github.com/rytilahti/python-songpal) — Python implementation for STR-DN1080 and soundbars. Likely 80% portable to the HAP with port change + version remap.
- [`openHAB Sony binding PR #6884`](https://github.com/openhab/openhab-addons/pull/6884) — built from Wireshark, covers TV/Bluray/AVR/soundbar. Java but readable as a method reference.
