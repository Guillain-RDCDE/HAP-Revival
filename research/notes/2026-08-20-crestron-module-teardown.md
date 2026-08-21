# Crestron module teardown — a second REST API and working push notifications

**Date**: 2026-08-20
**Provenance**: the Crestron certified module for the HAP-Z1ES, contributed by **Amos**, who bought
it for $0.00 from the Crestron Application Market and sent the full package.
**Status**: findings below are **validated live against a HAP-Z1ES on firmware 19404R**, not merely
read out of the binaries.

This is the artefact [`docs/08-prior-art.md`](../../docs/08-prior-art.md) listed as the single most
valuable missing piece — "the only quasi-official protocol document known to exist… could leapfrog
several phases of API reverse-engineering". It delivered more than expected: not just the Help PDF,
but a complete, non-obfuscated client implementation.

Two of our published conclusions were wrong and are corrected by this note.

## What was in the package

| File | What it is |
|---|---|
| `Help/Sony High Resolution Audio Player Help.pdf` | The Crestron help sheet. **Names the vendor firmware it was written against: `0017310R`.** |
| `Program/Crestron.Sony.HddAudioPlayer.Ui.clz` | SIMPL# library — a plain ZIP holding two .NET assemblies |
| `Program/…Engine v1.00.10.usp` | SIMPL+ source, in clear |
| `Program/…v1.00.10.umc`, `.smw`, `.lpz`, `.sig` | SIMPL Windows program and archives |
| `Ui/Sony_HAP_XPanel.*` | XPanel touch-panel project (7 MB `.vtp`) |

Module version 1.00.10, compiled 2016-06-08. Inside the `.clz`:

- `Crestron.Sony.HddAudioPlayer.Ui.dll` — menu/UI state machine
- `Crestron.Sony.ContentServiceWebApi.dll` — **the protocol client**

Both decompile cleanly (`ilspycmd`), with class, method and JSON property names intact.

## Method

```bash
cp Crestron.Sony.HddAudioPlayer.Ui.clz clz.zip && unzip clz.zip -d clz/
dotnet tool install -g ilspycmd --version 8.2.0.7535
DOTNET_ROLL_FORWARD=LatestMajor ilspycmd clz/Crestron.Sony.ContentServiceWebApi.dll -o dec -p
```

The module builds its URLs by reflection: `PathFactory` walks the .NET namespace backwards until it
hits the segment `Root`, lowercasing each element into a path. So
`…Root.Sony.ContentDb.v100.Audio.Albums` becomes `/sony/contentdb/v100/audio/albums`. Every endpoint
in the module is recoverable this way, without a single hardcoded URL string in the binary.

## Finding 1 — there is a second, REST API, and it is alive

The module never touches the JSON-RPC ScalarWebAPI we documented. It speaks a **REST API on the same
port 60200**, the one the embedded `HAP_app.html` admin UI calls.

We had recorded this whole surface as vestigial. That was half wrong: **`contentplayer` works on
19404R**; only `contentdb` is dead.

Verified live (2026-08-20, firmware 19404R):

| Request | Result |
|---|---|
| `GET /sony/contentplayer/v100/playinginfo` | **200** `{"repeat_mode":"off","playback_state":"playing","source_type":"spotify_connect",…}` |
| `GET /sony/contentplayer/v100/powerstate` | **200** `{"power_state":"on"}` |
| `GET /sony/contentplayer/v100/externalinput` | **200** `{"source":"none"}` |
| `GET /sony/contentplayer/v100/playqueue` | **200** `{}` |
| `GET /sony/contentplayer/v100/settings/sound/dsee` | **200** `{"setting":{"name":"dsee","value":"auto"}}` |
| `GET /sony/contentplayer/v100/volumelevel` | **500** `{"error_code":500,"description":"Internal Server Error"}` — expected: the Z1ES has no volume stage. Should work on the S1. |
| `GET /sony/contentdb/v100/audio/albums?offset=0&limit=3` | **hangs**, 0 bytes |

Note `source_type: "spotify_connect"` — a source the 2016 Crestron enum does not know about
(it lists `none/hdd/radiko/tunein/vtuner/optical/coaxial/linein1/linein2`) and which we had not
recorded either. Firmware gained it after the module was written.

### The `contentdb` hang is a dead handler, not an unknown route

Controls run against a healthy daemon, one request at a time:

| Request | Result |
|---|---|
| `GET /sony/completely/bogus/path` | 404 `not found` (bare text) — lighttpd's own 404 |
| `GET /sony/contentplayer/v100/bogus` | 404 `{"error_code":404,…}` — the *application's* 404 |
| `GET /sony/contentplayer/v100` | 404 (parent nodes are not addressable; normal) |
| `GET /sony/contentdb/v100` | 404 |
| `GET /sony/contentdb/v100/audio/albums` | **hangs** |

An unknown path returns 404 in a few milliseconds. `contentdb`'s leaves hang forever. So the route
is registered in the daemon and its handler never answers — consistent with a feature that shipped
in `0017310R` (the firmware the Crestron module targets) and was later disabled or had its backend
removed. That reframes `HAP_app.html`: it is not a generic UI pointed at a backend this device never
had; it is a UI for a backend this device **lost**. Firmware archaeology and a downgrade path are
now worth more than we assumed.

### Trap: the daemon serialises requests, and a hung request wedges it

While a `contentdb` request is pending, **every other endpoint times out too**, including ones that
answered 30 seconds earlier. It recovers on its own within seconds of the pending request being
abandoned. Any probe run that fires requests concurrently, or that touches `contentdb` before
testing something else, will produce false negatives across the board — our first pass at the
notification endpoint below reported a timeout for exactly this reason. **Probe sequentially, with a
known-good request as a health check between each.**

## Finding 2 — the HAP has push notifications, over UDP

[`docs/03-network-api.md`](../../docs/03-network-api.md) and
[`api-method-catalog.md`](../api-method-catalog.md) both stated flatly that the HAP exposes no push
mechanism, on the strength of the 2026-05-25 APK decompile. That decompile searched for
`switchNotifications` and for WebSocket, and correctly found neither. The mechanism is neither: it
is **pseudo-HTTP `NOTIFY` over UDP**, and Sony's Android app simply does not use it.

### Subscribing

```http
POST http://<ip>:60200/sony/notification/status
Content-Type: application/json; charset=UTF-8

{"status": "enable", "port": 9999}
```

Response, verified live:

```json
{ "timeout": 300, "port": 9999 }
```

`timeout` is the subscription lifetime in **seconds** — re-arm every ~250 s. (The Crestron module
re-arms every 10 s, then 20 s, and ignores the returned value entirely; there is no need to copy
that.) It only subscribes while `power_state` is `on`.

**The Crestron module's own path is wrong for this endpoint.** Its `Notification.Status` namespace
sits outside the `Sony` sub-namespace, so `PathFactory` yields `/notification/status` — which
returns a hard 404 here. The working path is `/sony/notification/status`. Also 404: 
`/sony/contentplayer/v100/notification/status`, `/sony/contentplayer/v100/notification`.

### Receiving

The device then sends UDP datagrams to `<your-ip>:<port>` from `<hap-ip>:60200`. Verified capture:

```http
NOTIFY * HTTP/1.1
Content-Length: 112
Content-Type: application/json
SEQ: 1
X-ContentServiceHostUUID: uuid:00000000-0000-1010-8000-104FA86F4B84

{ "event": "playingtrackChanged", "url": "http://192.168.1.28:60200/sony/contentplayer/v100/playinginfo" }
```

- It is a pseudo-HTTP request line + headers + JSON body in a single 263-byte datagram, not raw JSON.
- The body carries `event` and a **`url` to fetch** — the notification says *what changed and where
  to read it*, it does not carry the new state.
- **Each event is transmitted three times with the same `SEQ`.** Deduplicate on `SEQ`; the Crestron
  module does exactly this, tracking the last value and dropping repeats.
- `X-ContentServiceHostUUID` matches the SSDP UUID format (`…-<wifi-mac>`), so one listener can
  demultiplex several HAPs.
- 240 s of listening on an idle-but-playing unit yielded 15 datagrams = 5 distinct events, roughly
  one per 45 s (Spotify Connect track changes).

### Event names

Observed live: `playingtrackChanged`. The Crestron module handles five, matched case-insensitively:

| Event | Module's reaction |
|---|---|
| `playingtrackChanged` | GET `/sony/contentplayer/v100/playinginfo` |
| `playinginfoChanged` | GET `/sony/contentplayer/v100/playinginfo` |
| `playqueueChanged` | GET `/sony/contentplayer/v100/playqueue` |
| `powerstateChanged` | GET `/sony/contentplayer/v100/powerstate` |
| `volumeChanged` | GET `/sony/contentplayer/v100/volumelevel` |

Only `playingtrackChanged` is confirmed on 19404R so far; the other four are read from the module
and not yet observed. `volumeChanged` is unlikely to fire on a Z1ES given `volumelevel` returns 500.

### Windows note

Windows Firewall drops the unsolicited inbound UDP. Sending one datagram outbound from the listening
socket to the HAP before subscribing opens the stateful mapping and the notifications arrive without
any firewall rule.

## The endpoint map, as recovered from the module

Base `http://<ip>:60200`. Query parameters are lowercased field names:
`offset`, `limit`, `genreid`, `artistid`, `albumid`, `trackid`, `playlistid`,
`orderbyid` (`track_name` | `album_name`).

### `contentplayer` — live on 19404R

| Method | Path |
|---|---|
| GET | `/sony/contentplayer/v100/playinginfo` |
| GET | `/sony/contentplayer/v100/playqueue` |
| GET | `/sony/contentplayer/v100/playqueue/tracks?offset=&limit=` |
| GET | `/sony/contentplayer/v100/powerstate` |
| GET | `/sony/contentplayer/v100/volumelevel` |
| GET | `/sony/contentplayer/v100/externalinput` |
| GET | `/sony/contentplayer/v100/settings/sound/<setting>` |
| POST | `/sony/contentplayer/v100/operation` |

`<setting>` ∈ `dsee`, `gaplessplayback`, `volumenormalization`, `dsdremastering`, `oversampling`,
`tonecontrolbypass`, `tonecontrolbass`, `tonecontroltreble`.

**All writes go to the single `/operation` endpoint**, discriminated by a `method` field.

Verified live 2026-08-20 with an idempotent write — reading `dsee`, posting the identical value
back, reading again:

```http
POST /sony/contentplayer/v100/operation
Content-Type: application/json; charset=UTF-8

{"method":"setsoundsetting","setting":{"name":"dsee","value":"auto"}}
```

```
200 {}
```

**A successful write returns `200` with an empty object `{}`, not a confirmation.** Read the setting
back to see the effect — an empty reply is success, not silence. Failure shapes, same session:

| What was sent | Reply |
|---|---|
| Body wrapped in single quotes (the Windows `cmd` quoting trap) | `400 {"error_code":400,"description":"Bad Request"}` |
| Body with no `method` field | `400 Bad Request` |
| `method` fine, unknown `setting.name` | `500 Internal Server Error` |
| `GET` on `/operation` instead of `POST` | `404 Not Found` |

So a 400 means the daemon could not parse what arrived — nearly always a shell quoting problem
rather than a wrong schema. A 500 means it parsed fine and did not like the contents.

The full method table below is read from the module; only `setsoundsetting` is verified live.

| Body | Effect |
|---|---|
| `{"method":"controlplayback","operation":"play\|pause\|next\|previous"}` | Transport |
| `{"method":"playcontent","content_url":…,"content_type":"track\|container\|streaming","play_type":"now\|next\|last","firstplay_trackid":N,"firstplay_index":N,"shuffle_mode":…,"repeat_mode":…}` | Load and play |
| `{"method":"setpowerstate","power_state":"on\|off"}` | Power |
| `{"method":"setvolumelevel","volume_level":"N"}` or `{"method":"setvolumelevel","mute":"on\|off"}` | Volume. `N` is an **absolute integer sent as a string**, not a percentage. The module rescales it against `volume_level_min`/`_max`, which a real S1 does not send — see the `volumelevel` section below before copying that logic. Z1ES has no volume stage at all. |
| `{"method":"setsoundsetting","setting":{"name":…,"value":…}}` | Sound settings |
| `{"method":"setexternalinput","source":"none\|optical\|coaxial\|linein1\|linein2"}` | Input |
| `{"method":"setrepeatmode","repeat_mode":"off\|one\|all"}` | Repeat |
| `{"method":"setshufflemode","shuffle_mode":"off\|track\|album"}` | Shuffle |

Sound setting values are not uniform: `dsee`/`gaplessplayback`/`volumenormalization` take
`off`/`auto`; `dsdremastering`/`tonecontrolbypass` take `off`/`on`; `oversampling` takes
`normal`/`precision`; `tonecontrolbass`/`tonecontroltreble` take a signed integer formatted
`+#;-#;0` over a −10…+10 range.

**Tone control is new to us** — it is an S1 feature (the Z1ES has no tone stage) and appears nowhere
else in our documentation.

**Reported working on a real HAP-S1** (Amos, 2026-08-21): all three tone-control reads return data,
and a write —
`{"method":"setsoundsetting","setting":{"name":"tonecontrolbass","value":"+3"}}` — returned `200 {}`,
the same success shape verified on the Z1ES. This is a contributor report; the capture files have
not reached us yet, so it is not marked verified here. If it holds, it is the first confirmation of
tone control on an S1 and the first S1 write of any kind.

### `volumelevel`: the Z1ES/S1 divergence, confirmed — and a defect in the module

`GET /sony/contentplayer/v100/volumelevel` returns `500 Internal Server Error` on the Z1ES, which
has no volume stage. On a **HAP-S1 it answers** (Amos, 2026-08-21):

```json
{"mute": "off", "request": "http://…/sony/contentplayer/v100/volumelevel", "volume_level": 7}
```

The divergence is now observed rather than inferred from the hardware. But look at what is
**missing**: no `volume_level_min`, no `volume_level_max`. The module's parser requires both:

```csharp
audioObject.Max   = (ushort)response["volume_level_max"];   // absent on a real S1
audioObject.Min   = (ushort)response["volume_level_min"];   // absent on a real S1
audioObject.Value = (ushort)response["volume_level"];
…
if (audioObject2.Max > audioObject2.Min) { /* rescale to 0–100 */ }
return null;                                                 // otherwise: no feedback
```

Either the cast of an absent field throws, or it yields zeros and the `Max > Min` guard falls
through to `return null`. Both end in the same place: **the module produces no volume feedback on
this response.** `SetVolume` is gated on the same object (`_audioObject != null && Max > Min`), so
writes never fire either.

Cross-checking the rest of the package makes the picture unambiguous. The SIMPL+ module exposes
**no volume signal at all** — the only match for "volume" in the source is `VolumeNormalization`,
which is a sound setting, not a level — and the Help PDF documents none. So Crestron implemented
volume in the DLL against a response shape that no shipping HAP produces, found it could not work,
and shipped with volume disconnected from the installer-facing module. It is dead code.

**Rule for our own client**: treat `volume_level` as an **opaque integer**. Do not assume `min`/`max`
are present and do not rescale to a percentage — the module's `(value - min) / (max - min) * 100`
is unusable here. `mute` (`"on"`/`"off"`) is present and behaves as documented.

**Range measured on a real S1** (Amos, 2026-08-21): **0 to 74**. Not a percentage, and not
discoverable from the API — a client either hardcodes it or learns it. The earlier guess that the
ceiling might be 50 was wrong.

**And the S1 runs `0019404R`, the same firmware as our Z1ES.** So the `volumelevel` divergence —
`200` with data on the S1, `500` on the Z1ES — is a **model** difference, not a firmware one. The
Z1ES has no volume stage and its daemon says so with a 500. That closes the question.

Still open: whether any firmware ever sent `volume_level_min` / `_max` at all, which would explain
why Crestron's parser expects them.

### `contentdb` — dead on 19404R, presumed live on 0017310R

| Method | Path |
|---|---|
| GET | `/sony/contentdb/v100/audio/{albums,artists,genres,tracks,playlists}` |
| GET | `/sony/contentdb/v100/audio/albums/{id}` · `/{id}/tracks` |
| GET | `/sony/contentdb/v100/audio/artists/{id}` · `/{id}/albums` |
| GET | `/sony/contentdb/v100/audio/genres/{id}` |
| GET | `/sony/contentdb/v100/audio/tracks/{id}` |
| GET | `/sony/contentdb/v100/audio/playlists/{id}` · `/{id}/tracks` |
| GET | `/sony/contentdb/v100/services/sensme` · `/{id}` |
| GET | `/sony/contentdb/v100/services/favorite/tracks` |
| GET | `/sony/contentdb/v100/services/directory` · `/{container}` |
| POST | `/sony/contentdb/v100/audio/tracks/{id}` — body `{"track":{"trackid":N,"favorite_type":"favorite\|dislike\|normal"}}` |

Appending `/alltracks` to a container's item URL yields a playable container URL — that is how the
module enqueues a whole album or directory.

List responses are `{"request": <echoed absolute URL>, "paging": {…}, "<collection>": [...]}`. The
module dispatches purely on the echoed `request` URL, which is a convenient design to copy.

Two curiosities: `services/sensme` returns `playlists` of a `Channellist` shape (SensMe channels),
and the directory service can return an item of type `streaming` that Crestron themselves did not
understand — their code renders it literally as `"UNDOCUMENTED STREAM"`.

## Errors

- `404`/`500` when powered off — the module treats these as "server is likely powered off".
- `204`/`400` return `{"error_code": N, "description": "…"}`.
- Bare-text `not found` (no JSON) means the request never reached the application; a JSON 404 means
  it did, and the application rejected the path.
- On a write: `400` = unparseable body (check shell quoting first), `500` = parsed but rejected,
  `200 {}` = done.

## Licensing

The binaries are © Crestron Electronics. The **facts** of the wire protocol — paths, field names,
enumerated values — are not copyrightable, and analysis for interoperability is lawful, but no
decompiled code may be copied into this MIT-licensed repository. The decompilation output is kept
out of the tree; everything above is a description of the protocol, re-verified against a real
device wherever the table says so. Anything not re-verified is marked as read from the module.

## What this unblocks

1. **Push-driven clients.** Shipped as [`tools/hap_notify.py`](../../tools/hap_notify.py) —
   subscribe, dedupe on `SEQ`, fetch the `url`, re-arm before `timeout`. `tools/webui.py` and any
   control app can now stop polling at 5 s and update the instant something changes.
2. **A REST client alongside the JSON-RPC one.** `contentplayer` gives power, transport, sound
   settings and now-playing without JSON-RPC's per-method version roulette.
3. **A concrete reason to pursue firmware archaeology** — `contentdb` is a whole library API that
   this hardware used to serve.
4. **S1 tone control**, ready to document the moment someone with an S1 tests it.
