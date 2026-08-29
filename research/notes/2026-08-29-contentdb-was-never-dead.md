# The library API was never dead — our timeouts were too short

**2026-08-29.** Every `/sony/contentdb/v100/...` endpoint this project has documented as
"hangs forever" answers `200` with real data on `HAP-Z1ES` firmware `0019404R`. It is slow,
not dead. Six months of documentation built on the opposite claim is wrong, and this note
records the measurements that overturn it.

## What we said

From [`docs/03-network-api.md`](../../docs/03-network-api.md):

> `/sony/contentdb/v100/...` — mostly dead, but not entirely. The library half
> (`audio/{albums,artists,genres,tracks,playlists}`, `services/{sensme,favorite,directory}`)
> **hangs and times out (0 bytes)** on every listing and metadata path.

And, more forcefully, in [`docs/16-gotchas.md`](../../docs/16-gotchas.md) and
[`docs/HELP-IN-5-MINUTES.md`](../../docs/HELP-IN-5-MINUTES.md): *"That is a known dead API,
not you. Don't."*

## What the device actually does

Sequential `curl`, one request at a time, generous timeout, against `192.168.1.28`:

| Endpoint | Status | Bytes | Time |
|---|---|---|---|
| `audio/genres` | 200 | 2 990 | 10.8 s |
| `audio/albums` | 200 | 8 428 | 15.5 s |
| `audio/artists` | 200 | 3 098 | 13.0 s |
| `audio/tracks?count=5` | 200 | 19 579 | 17.4 s |
| `audio/albums/4964` | 200 | 399 | 7.2 s |
| `audio/artists/1` | 200 | 2 | 5.0 s |
| `audio/playlists` | 200 | 1 238 | 5.8 s |
| `services/favorite` | 200 | 4 325 | 0.2 s |
| `services/sensme` | 200 | 3 117 | 9.1 s |
| `services/directory` | 200 | 578 | 4.1 s |

`audio/albums/4964` is the **exact example** `03-network-api.md` gave as hanging while its
cover art answered. It answers in 7.2 s.

The payloads are genuine. `audio/genres` reports **59 414 tracks under genre 0** — the untitled genre, i.e. the tracks with no genre tag, not the library total, which is **78 369** (see the harvest below);
`audio/tracks` returns full metadata — album name, `albumid`, release date, track count,
duration, artist — the whole tree the project planned to reach by `downloadByDiff` or by
pulling the disk.

### It warms up, and the cold penalty is severe

Three calls to `audio/genres` back to back:

| Attempt | Time |
|---|---|
| 1 | 6.2 s |
| 2 | 2.0 s |
| 3 | 1.7 s |

After the player dropped off the network and rejoined it (see below), the same endpoints
came back **much** colder — `audio/genres` 30.1 s, `audio/albums` 20.1 s,
`audio/albums/4964` 21.7 s, `audio/playlists` **57.2 s** — all still `200`, all still
correct. So the working range is roughly **1.7 s warm to 57 s cold**, and the cold end
depends on what else the player is doing (it was streaming Spotify throughout).

## Why we got it wrong

Every tool that probed this API capped out at six seconds:

| Tool | Timeout |
|---|---|
| [`tools/api-fuzzer.py`](../../tools/api-fuzzer.py) | 6 s |
| [`tools/hap_client.py`](../../tools/hap_client.py) | 6 s |
| [`tools/discover.py`](../../tools/discover.py) | 6 s |
| [`tools/call.py`](../../tools/call.py) | 8 s |

A cold `contentdb` leaf takes 5–57 s. Those requests could not succeed. They failed the
same way every time — no status, no body — which reads exactly like a route whose handler
never answers.

The detail that made the wrong theory *convincing* is the cover art. It answered in 0.2 s,
and it was the one endpoint under the ceiling. From that we built a tidy story: the routes
survive, the database behind them was removed, only the static half still serves. The real
pattern was simpler and had nothing to do with databases — **fast requests passed, slow
requests failed**, and we had drawn the line at exactly six seconds without noticing we had
drawn it ourselves.

The serialisation trap already documented in `03-network-api.md` compounded this: while one
slow `contentdb` request is pending, everything else times out too, so a sweep produced
false negatives across the whole surface and made the failure look even broader.

## What this changes

- **The library is readable over REST, today, on 19404R.** No `downloadByDiff`, no NAND
  dump, no removing the disk.
- **There is no per-machine `contentdb` fault.** The 2026-08-28 conclusion — that Amos's
  player was healthy and ours was broken — is void: both are healthy, and ours was only
  ever being asked with a stopwatch that ran out.
- **The 18120R question is moot.** `docs/07-firmware.md` wanted that firmware partly to
  learn when the library API died. It did not die.
- **`0017310R` is not special.** The Crestron module built on this API in 2016 because it
  worked — and it still does.

## Corollary found the same day: `keyevent` cannot drive the network menus

Chasing a separate goal (pointing the player's DNS at a logging resolver, to learn the
Network Update path), we drove the front panel remotely with
[`tools/hap_screen.py`](../../tools/hap_screen.py) as far as
*Settings → Network Settings → Internet Settings → Wireless setup*, and selected it.

The player **dropped its Wi-Fi association to run the setup wizard**, and with it the only
channel that could send further keys. No ping, no ARP entry, no port 60200. It had to be
recovered by hand on the front panel.

This is structural, not bad luck: the network menus tear down the transport the key
injection rides on. **Do not enter *Internet Settings* over `keyevent`.** Reading
*View Network Status* is safe; note that its list does not scroll under injected keys
(`up`/`down` move nothing, focus stays on the Close button).

To reach the same goal without touching the player, advertise the logging resolver over
**DHCP from the router** instead — the player picks it up on its own, and nothing on the
device is reconfigured. [`tools/hap_intercept.py`](../../tools/hap_intercept.py) is the
resolver: it logs every name the player looks up and forwards it upstream unchanged, so
nothing breaks, and it relays plain-HTTP hosts named with `--hijack` through a proxy that
records the full path.

## What the surface actually looks like (same day, after the correction)

With the timeout fixed, the rest of the API was worth mapping properly.

**Every response carries a `paging` object**: `{offset, limit, total, next, previous}`, where `next`
is a complete absolute URL and `previous` is `""` at the start. So a client never has to guess where
a collection ends — follow `next` until it is empty.

**The speed splits cleanly in two, and it is not about payload size:**

| Request | Time |
|---|---|
| `audio/albums/10633/tracks` | 0.1 s |
| `audio/tracks/148136` | 0.4 s |
| `services/favorite` | 0.4 s |
| `audio/artists/1089/albums` | 0.6 s |
| `audio/albums?limit=2` | 46.7 s |
| `audio/artists?limit=2` | 49.5 s |
| `audio/genres/0` | 85.1 s |

`?limit=2` costs about the same as `?limit=5000` (47 s vs 52 s). The cost is **fixed per unfiltered
collection**, which is what you would expect if `paging.total` forces a full count. Scoped lookups
have a small total and answer at once. Cover art, which has no paging at all, was always 0.2 s —
that is the whole reason it looked like a surviving exception to a dead API.

Practical consequence: **cache the four root listings, never cache drill-down.** A second read of
`audio/artists` (17 317 of them) came back in 0.015 s from cache against 28.5 s cold.

**Page size**: `limit=5000` works (5.2 MB in 52 s), `limit=10000` and `limit=20000` are refused
instantly with `400 {"error_code": 400, "description": "Bad Request"}`. The device does not clamp.
At 5000, the whole 78 369-track library is 16 requests.

**An unknown id is `200 {}`** — not a 404, not an error body. "No such track" has to be read out of
the body, and it must not be mistaken for a transport failure.

**`filepath` is empty on every track seen**; only `filename` is populated. That limits matching
library rows against files on the SMB share.

**Variable endpoints**: `services/sensme` and `services/directory` answered in 9.1 s and 4.1 s in one
sweep and timed out past 120 s in another, an hour later. Not documented as reliable either way.

### Browsing and playback share one id space

`createPlayingListAndQuickPlay` takes `audio:track?id=N`. The REST `trackid` **is** that N, confirmed
live: `play_track(148136)` started "4 ogives - les fleurs" and `getPlayingContentInfo` then reported
`uri: audio:track?id=148136`. No mapping needed between the browse tree and the play command.

One trap while checking it: eight seconds after the call, `getPlayingContentInfo` still returned
empty strings while the front panel was already showing the track at 00:15. The queue is built
before the JSON-RPC view catches up, so an immediate read-back can look like a failure that isn't.
The screen endpoint settled it — a good argument for keeping that channel around.

### The catalog is not uniformly UTF-8

Harvesting the whole library found this the hard way: the run died on the fourth page of artists with
`UnicodeDecodeError: invalid continuation byte` at offset 316 631.

One name in 17 317 — `Zé Roberto`, artistid 16712 — stores its `é` as a bare `0xE9`, Latin-1, inside
a 343 KB page that is otherwise valid UTF-8. The player does not normalise tags; it returns the bytes
its catalog holds, so the encoding varies **per record**, according to how each file was tagged
before it was ever imported.

`json.loads` on the raw bytes throws, and the whole page is lost over one character. The fix is a
decode error handler that falls back to Latin-1 for exactly the failing bytes — not
`errors="replace"` (which corrupts the name) and not a wholesale Latin-1 decode (which mojibakes
every correct name). Written up as gotcha 8 in [`docs/16-gotchas.md`](../../docs/16-gotchas.md).

Worth noting what this implies beyond our client: those names are presumably just as broken on the
player's own front panel, and in Sony's app when it still worked.

## Method note

Three separate wrong conclusions in this project — the TuneIn "outage", the v1.2.1 blank
page, and now this — came from explaining a symptom with a theory instead of measuring the
thing itself. Here the measurement was one `curl` with a longer `-m`. The lesson is narrower
and more useful than "test more": **a timeout is a value we chose, and a failure that always
arrives at the value we chose is evidence about us, not about the device.**
