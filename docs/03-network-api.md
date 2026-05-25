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

**Not open** (verified empirically): 22 (SSH), 23 (telnet), 80 (HTTP), 443 (HTTPS), 5000, 8000, 8080, 8443, 10000 (Sony Home Audio API on cousin devices), 54480 (Sony Personal Audio API), 52323 (BRAVIA).

**Implication**: the alternate Sony ports referenced in `python-songpal#29` are **not** used by the HAP — the HAP family is its own generation with its own port assignment. Don't waste time probing those.

## SSDP discovery

A standard `M-SEARCH * HTTP/1.1` to `239.255.255.250:1900` returns five replies, one for each advertised service:

```
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
- **HTTP `Expect: 100-continue` triggers `417 Expectation Failed`.** Most Python and PowerShell clients send this header by default; you must disable it. In Python with `requests`: `session = requests.Session(); session.headers.update({'Expect': ''})`.
- **Introspection is neutered.** `getMethodTypes` returns `{"results": []}` at every version on every service, and `getSupportedApiInfo` returns `[12, "No Such Method"]`. The full method dictionary must be discovered by APK decompile or fuzzing against the BRAVIA/python-songpal method names.
- **Response bytes are UTF-8 JSON.** Some libraries return them as `byte[]` — decode with UTF-8 before parsing.

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

## WebSocket notifications

Sony's [official example code](https://github.com/sonydevworld/audio_control_api_examples) demonstrates `switchNotifications` for real-time updates: subscribe to `notifyPlayingContentInfo`, `notifyVolumeInformation`, `notifyPowerStatus`, `notifySettingsUpdate`, `notifySWUpdateInfo`. We **have not yet verified** which of these are reachable on the HAP (the WebSocket upgrade probe returned 405 on `/sony/avContent` — likely needs a different endpoint or upgrade flow).

## Methods we've confirmed working

See [`research/api-method-catalog.md`](../research/api-method-catalog.md) for the living catalog with exact versions and parameter shapes.

## Reference: cousin-device documentation we can transpose

- [Sony BRAVIA Pro REST API spec](https://pro-bravia.sony.net/develop/integrate/rest-api/spec/) — the most exhaustive Sony-published method/version dictionary.
- [`rytilahti/python-songpal`](https://github.com/rytilahti/python-songpal) — Python implementation for STR-DN1080 and soundbars. Likely 80% portable to the HAP with port change + version remap.
- [`openHAB Sony binding PR #6884`](https://github.com/openhab/openhab-addons/pull/6884) — built from Wireshark, covers TV/Bluray/AVR/soundbar. Java but readable as a method reference.
