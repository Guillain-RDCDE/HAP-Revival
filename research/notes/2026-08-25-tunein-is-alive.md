# TuneIn is not dead — the HAP is just not asking it correctly

**Date**: 2026-08-25
**Status**: ⚠️ **Partly retracted the same day.** The measurements below are accurate — TuneIn's API
does behave this way. The *conclusion* was wrong: none of it was what stood between our player and a
station. Internet radio worked on the HAP the whole time, and we were breaking our own calls. See
[`../api-method-catalog.md`](../api-method-catalog.md) and
[`../../docs/16-gotchas.md`](../../docs/16-gotchas.md) §6.

Kept rather than deleted, for two reasons. The `Tune.ashx` findings stand on their own and matter for
the open bitrate question — a proxy that hands the player a FLAC stream would use exactly this. And
the note is a fair record of how a well-evidenced, internally consistent theory can still be built on
the wrong premise: every measurement here was real, and the reasoning around them was sound, and the
answer was still no.

We had concluded that internet radio was gone because Sony withdrew it. That is half the story at
most. TuneIn's device API is alive and serving in 2026 — the problem is what it now demands of a
client, and there is a well-established way to fix exactly this class of problem on exactly this
class of hardware.

## What is actually true, tested 2026-08-25

TuneIn's legacy device API still answers on `opml.radiotime.com`. Station ids are the same
`s#####` values the HAP uses, and the same ones in a tunein.com URL.

| Request | Result |
|---|---|
| `GET /Browse.ashx` | **200** — the full browse tree, OPML |
| `GET /Describe.ashx?id=s13606` | **200** — full metadata for Radio Paradise |
| `GET /Tune.ashx?id=s13606` | **`#STATUS: 400`** |
| `GET /Tune.ashx?id=s13606&formats=mp3,aac` | **200 — real stream URLs** |
| `GET /Tune.ashx?id=s13606&render=json` (no `formats`) | 200, and the "stream" is `cdn-cms.tunein.com/service/Audio/notcompatible.enUS.mp3` |

Two things fall out of that table.

**`formats=` is now mandatory for stream resolution.** Browsing and metadata work for anyone;
resolving a station to a playable URL does not, unless the client declares what it can decode. Add
`formats=mp3,aac` and you get:

```text
https://stream.radioparadise.com/ti-main-320
https://stream.radioparadise.com/ti-main-64
https://stream.radioparadise.com/ti-main-128
```

**TuneIn deliberately handles legacy clients, and tells them so out loud.** A request without
`formats` returns a perfectly well-formed response whose audio element is a spoken announcement file
named `notcompatible.enUS.mp3`. That is not a bug — someone built that on purpose for devices in
exactly our position.

Also worth noting: the URLs come back as **HTTPS**. A 2014 box on Linux 3.0.35 with a 2014 TLS stack
may well not be able to follow them, independently of everything else. Radio Paradise happens to
serve the same stream over plain HTTP, but that will not be true everywhere.

## What this changes

Our documented explanation was "Sony withdrew the service". The evidence now says the far end is up,
answering, and even has a courtesy message for clients like ours. Whatever is broken sits between
the HAP and a working `Tune.ashx` call — a missing `formats` parameter, a partner credential that
lapsed, an HTTPS stream the device cannot open, or a Sony intermediary that no longer exists.

That reframes radio from *lost* to *interposable*.

It also fits the one thing we could not explain: why stations play on some players and not others. A
player that used TuneIn while it worked may hold resolved stream URLs in its local
`tunein_browse.db` ([`../../docs/09-disk-layout.md`](../../docs/09-disk-layout.md)) and never need to
call `Tune.ashx` at all. A player that never did — like our reference Z1ES — has nothing cached and
fails at resolution every time, silently, exactly as observed.

**The prediction that tests this**: a working player should still fail on a station it has *never*
played. That is one call for anyone whose radio works, and it decides between "cached" and something
else.

## The missing piece, and how to get it

**We do not know which hostname the HAP contacts.** It is not in the Android APK — the app never
does this, the device does. It is in the firmware, which we do not have.

DNS offers no shortcut: `opml.radiotime.com` and `opml.tunein.com` resolve, but no Sony-specific
TuneIn host exists (`sony.radiotime.com`, `sony.tunein.com`, `hap.tunein.com`, `nas.sony.net` — all
NXDOMAIN). So `opml.radiotime.com` is the most likely answer, and a capture would confirm it in
seconds.

**One packet capture answers this and the firmware question at once.** Attempt a station while
capturing, and the DNS query names the host. That is the same capture already queued for the
firmware URL — see [`../../docs/07-firmware.md`](../../docs/07-firmware.md).

## Prior art: this exact problem, solved repeatedly, on this exact class of hardware

vTuner — the directory service behind internet radio on a decade of Denon, Marantz, Yamaha, Onkyo
and Pioneer receivers — was discontinued, and the community answered by emulating it and
intercepting DNS. Several mature implementations exist:

| Project | Notes |
|---|---|
| [milaq/YCast](https://github.com/milaq/YCast) | Self-hosted vTuner emulation; the original of the genre |
| [coffeegreg/YTuner](https://github.com/coffeegreg/YTuner) | Broader device support, includes an optional DNS proxy to intercept `vtuner.com` lookups |
| [victorantos/denon](https://github.com/victorantos/denon) | Single Go binary, DNS + HTTP in one process. **Explicitly proxies HTTPS streams down to plain HTTP** for receivers that cannot do TLS — the same limitation the HAP is likely to have |

The technique is identical to what the HAP needs: point the device's DNS at a machine you control,
answer in the shape the device expects, and hand back a stream it can actually open.

The difference in our favour is that **we do not have to emulate a dead directory** — TuneIn's is
alive. A HAP proxy would mostly forward, adding `formats=` on the way out and rewriting HTTPS stream
URLs to HTTP on the way back.

There is no TuneIn-specific equivalent of YCast, because TuneIn never died. Nobody needed one. That
is why searching for "HAP TuneIn fix" finds nothing: the problem has been solved for the neighbours,
under a different service name.

## What this would take

1. **Capture** one station attempt. Learn the hostname and the exact request. *(Blocked on physical
   access — the only genuinely blocking step.)*
2. **Confirm the shape.** Replay the request by hand; see whether adding `formats=` alone fixes it.
3. **Proxy.** DNS-redirect that host to a local service that forwards to `opml.radiotime.com`, adds
   `formats=mp3,aac`, and rewrites stream URLs to plain HTTP.
4. **Give it back.** If it works, the same proxy fixes every HAP still in service — including the
   ones whose owners were told the feature was simply gone.

Steps 2 to 4 are ordinary work. Step 1 needs someone standing next to the machine.

## Update 2026-08-30 — step 1 answered without a capture, and the FLAC question closed

The capture in step 1 was never actually needed for the TuneIn host. Two facts, both from the
player and the public API, no packet capture involved:

**The player uses `opml.radiotime.com` — cross-checked against live playback.** Playing a real
station over the API (`s6553`, ALOUETTE) and reading `getPlayingContentInfo` back gives
`audioInfo.codec = "mp3,aac"`, `bitrate = "128000"`, and a cover art URL the **player itself
proxies**: `http://<ip>:60200/sony/avContent/storage/radio_icon/tunein/s6553`. Querying
`opml.radiotime.com/Tune.ashx?id=s6553&formats=mp3,aac` from the PC returns exactly the streams that
station plays (`alouette.ice.infomaniak.ch/alouette-high.{aac,mp3}`). Same station id, same service,
same result — the player is speaking to this host. So the only reason left to capture the player's
traffic is the **firmware OTA path**, which has no public-API shortcut (blind path-guessing on
`info.update.sony.net` returned 404 for every HAP pattern tried, 2026-08-30).

**FLAC is not available, and the ceiling is the station's, not the device's.** Asking
`Tune.ashx?id=s6553&formats=mp3,aac,flac,ogg,wma` returns the *same* four MP3/AAC URLs. TuneIn
stations simply do not offer FLAC. This settles the open bitrate question: "serve the player a FLAC
stream" cannot mean *getting* a real FLAC stream from TuneIn — there isn't one. It could only mean
**substituting our own** stream (a local Icecast serving FLAC) via the proxy in steps 3–4. Worth
knowing before anyone builds that proxy expecting hi-res radio to fall out of it.

Steps 3–4 still need the player to resolve `opml.radiotime.com` to a local service, i.e. DNS
redirection — which this network's Livebox does not allow (it distributes no custom DNS, confirmed
2026-08-30). So the proxy remains possible but blocked on the same DNS-redirection step as the
firmware capture, not on learning the host.

## Sources

- [milaq/YCast](https://github.com/milaq/YCast) · [coffeegreg/YTuner](https://github.com/coffeegreg/YTuner) · [victorantos/denon](https://github.com/victorantos/denon)
- [core-hacked/tunein-api](https://github.com/core-hacked/tunein-api) — unofficial documentation of the TuneIn/Radiotime endpoints
- Live probes of `opml.radiotime.com`, 2026-08-25, recorded in the table above
