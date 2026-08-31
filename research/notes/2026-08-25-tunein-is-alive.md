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

## Update 2026-08-30 — step 1 answered without a capture, and the FLAC question sharpened

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

**FLAC over TuneIn: no. FLAC radio in general: yes. The gap between those two is the whole story,
and the first draft of this note got it wrong by testing one station.**

*What TuneIn carries.* Asking `Tune.ashx?id=…&formats=mp3,aac,flac,ogg,wma` returns MP3/AAC every
time, across stations — ALOUETTE (`s6553`) gives the infomaniak MP3/AAC feeds, and **Radio Paradise
(`s13606`), which broadcasts FLAC on its own infrastructure, comes back through TuneIn as
`stream.radioparadise.com/ti-main-320`** — the `ti-` prefix is literally a TuneIn-only MP3 feed the
station cuts for aggregators. So TuneIn normalises everything down to lossy. That much *is* settled.

*What actually exists.* Hi-res FLAC internet radio is real and reachable — just not through TuneIn.
Verified live 2026-08-30, direct Icecast/HTTP, no aggregator:

| Station | Direct stream | Format |
|---|---|---|
| Radio Paradise (main) | `https://stream.radioparadise.com/flac` | Ogg FLAC, 16/44 |
| Radio Paradise (Mellow) | `https://stream.radioparadise.com/mellow-flac` | Ogg FLAC |
| Intense Radio | `https://secure.live-streams.nl/flac.flac` | FLAC 24/44 |
| JB Radio-2 | `http://199.189.87.9:10999/flac` | Ogg FLAC 16/96 |

[`radio-browser.info`](https://www.radio-browser.info/) lists many more, filterable by codec.
(Mother Earth Radio, the famous 24/192 one, **closed in 2025** — do not put it in any default list.)

*Why the player still can't have them, and the two things that would have to be true.* The HAP's
radio is **TuneIn-only, with no custom-URL entry** — confirmed against the Sony manual and by the
absence of any API to add one (`getSchemeList` returns `[]`, `getSourceList` on `netService`/`audio`
returns `[]`, introspection is disabled). So the only route to FLAC radio on this device is a proxy
that answers a TuneIn station id with one of the real FLAC URLs above. That needs **both**:

1. **DNS redirection** of `opml.radiotime.com` to the proxy — blocked on this network (the Livebox
   distributes no custom DNS, confirmed 2026-08-30), and the same wall the firmware capture hits.
2. **The player's network-radio decoder actually handling FLAC-over-HTTP** — *unverified, and the
   real risk.* That codepath has only ever been fed MP3/AAC by TuneIn; the on-device FLAC decoder is
   used for files off the disk, and there is no evidence the streaming path can reach it. This could
   sink the whole idea even with the proxy working, and it cannot be tested until the DNS step is
   solved. Anyone building the proxy should test this first, with a single hard-coded FLAC URL,
   before writing anything else.

## Update 2026-08-31 — the interposition was attempted, and the player refused it

We built the full rig and pointed it at a real player. The result is instructive, and it closes the
"just build the proxy" optimism of steps 3–4 above.

**Setup.** Windows PC on the same Wi-Fi as the HAP, npcap + scapy. ARP-poison the HAP alone
(gateway → us), scapy-spoof its DNS for `opml.radiotime.com` → us, and serve a fake `Tune.ashx`
(returns a URL back to us) plus a live re-stream of Radio Paradise's real Ogg-FLAC on `:80`. Then
play a station by id and watch whether the HAP pulls FLAC and decodes it.

**What worked.** DNS interception is solid: the HAP accepted our spoofed answers every time (hundreds
of them). Our fake-TuneIn server is correct — from the LAN, `GET /Tune.ashx` returns the FLAC URL and
`GET /rp.flac` delivers genuine FLAC (verified, 1.7 MB pulled by `curl`).

**What did not.** The HAP never once opened a TCP connection to us — **zero SYN across every run.**
Under interception it degrades into a DNS-retry storm (measured ~**898 queries per minute** for
`opml.radiotime.com`) and never reaches the connect stage, so it can never receive the FLAC. Two
forwarding strategies were tried to keep it online during the MitM, and neither held:

- *Userland scapy forwarding* relayed almost nothing (the HAP was already wedged into the DNS loop).
- *Windows interface IP-forwarding flag* (`Set-NetIPInterface -Forwarding Enabled`) does **not**
  actually route on a client OS without the RRAS `RemoteAccess` service, which is stopped by
  default — so the HAP stayed black-holed.

**Conclusion.** The 2014 TuneIn client does not tolerate a man-in-the-middle: cut off from its normal
path even briefly, it loops on DNS instead of connecting. So the decode question — *can the HAP's
network-radio pipeline play FLAC-over-HTTP?* — **remains empirically unanswered**, because we could
not deliver a byte of FLAC to it. Answering it would need genuinely transparent routing so the
interception is invisible to the player: a Linux box (or the Mac) as a real router/NAT between the
HAP and the gateway, or a properly configured RRAS/NAT on Windows — not ARP poisoning from a client.

The rig and this dead-end are recorded so the next attempt starts from transparent routing, not from
scratch. Everything was restored afterwards: ARP corrected, forwarding disabled, the player back to
normal playback.

## Sources

- [milaq/YCast](https://github.com/milaq/YCast) · [coffeegreg/YTuner](https://github.com/coffeegreg/YTuner) · [victorantos/denon](https://github.com/victorantos/denon)
- [core-hacked/tunein-api](https://github.com/core-hacked/tunein-api) — unofficial documentation of the TuneIn/Radiotime endpoints
- Live probes of `opml.radiotime.com`, 2026-08-25, recorded in the table above
