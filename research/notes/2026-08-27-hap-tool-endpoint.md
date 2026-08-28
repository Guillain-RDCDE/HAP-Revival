# The third API: `/sony/hap` — front-panel screen capture and key injection

**Date**: 2026-08-27
**Status**: ✅ Confirmed live on the reference HAP-Z1ES (`19404R`). Both halves tested end to end,
reads and writes.

Two legacy pages sit on port 60100 next to the `HAP_app.html` we already knew about. A contributor
found them referenced from frazei's gist and asked whether we had noticed. We had not — there is no
directory listing on that port, so you only find them if you already know the filename.

```text
GET /HAP_v1.0.html        ->  200,   9 280 bytes
GET /HAP_ver.1.2.1.html   ->  200,  14 225 bytes
GET /HAP_app.html         ->  200, 272 230 bytes   (already documented)
```

Both load `/haplib.js` (35 882 bytes); v1.2.1 additionally loads `/browselib.js` (27 166 bytes).
Those two scripts are where the value is, and they describe an API surface that appears in **no**
other source we hold — not the Crestron module, not the decompiled `HDDAudioRemote` APK, not any
capture.

## The endpoint

```text
GET http://<ip>:60200/sony/hap?target=<target>&cmd=<cmd>
```

Same port as the ScalarWebAPI JSON-RPC and the `contentplayer` / `contentdb` REST trees, but a
separate namespace, and a plain query-string GET rather than JSON. `Server: Linux/3.0 Sony-HAP/1.0`.

| Target | Cmd | Response | Verified |
|---|---|---|---|
| `screen` | `display_png` | `200`, `image/png`, **480×272**, ~104 KB, ~1.3 s | ✅ live |
| `screen` | `download_png` | same image, served as a download | ✅ live |
| `screen` | `capture_png` | `200`, body is the 4-byte string `None`, **no** `Content-Type` — writes the PNG to the internal share instead | ✅ live |
| `keyevent` | `home` `up` `down` `left` `right` `enter` `back` `option` `play` | `200`, body `None`, ~3.4 s for the first call | ✅ live |

Cache-busting matters: the pages append a nonce to every screen request, and so should any client.

### `screen` — the front panel, over HTTP

`display_png` returns the **live framebuffer of the player's own display**, at its native 480×272,
as a PNG. Not a rendering of the playback state — the actual screen, menus and highlight bar
included.

`capture_png` performs the same grab but writes it server-side to the internal SMB share, at
`HAP_Internal/anap/capture/`, named `YYYY-MMDD_hhmmss.png`. Confirmed over SMB immediately after the
call: `2026-0828_014944.png`, 104 139 bytes. Note the filename — the call was made at 16:49:44 UTC on
the 27th, so **the device names its files in JST (UTC+9)**, independently of the timezone it displays.

`anap` also appears in the v1.2.1 icon filenames (`anap-folder-genre.png`). It looks like the
programme's internal codename.

### `keyevent` — the remote control, over HTTP

Each cmd injects one front-panel / IR key. Verified by capturing the screen before and after:

1. Baseline — TuneIn now-playing.
2. `cmd=option` → the OPTION overlay opens: *Favori*, *DSEE Auto*, *Flux*, *Veille Désactivé*.
3. `cmd=down`, `cmd=down`, `cmd=enter` → **“Sélectionnez un flux”**, listing the streams TuneIn
   offers for this station: three entries, all *320 kbps MP3*.
4. `cmd=back`, `cmd=back` → out to the Home menu, then `up` + `enter` → back to now-playing,
   byte-comparable to the baseline.

Playback was not interrupted at any point. The three screens are preserved as
[`../captures/screen-20260827-nowplaying-tunein.png`](../captures/screen-20260827-nowplaying-tunein.png),
[`../captures/screen-20260827-option-menu.png`](../captures/screen-20260827-option-menu.png) and
[`../captures/screen-20260827-stream-select.png`](../captures/screen-20260827-stream-select.png).

## Why this matters more than a screenshot

Screen capture and key injection **together** are a scriptable remote for the player's own UI. Every
feature Sony left in the on-device menus but removed from the mobile app becomes reachable again over
the network, with no firmware, no UART and no NAND work — and with the screen as the feedback channel,
a client can navigate without guessing what state the machine is in.

Two immediate consequences:

- **The stream selector is real and it is on-device.** The open question about pushing the player past
  MP3 320 on internet radio (see [`2026-08-25-tunein-is-alive.md`](2026-08-25-tunein-is-alive.md),
  `formats=`) now has an observable UI: the player asks TuneIn for a stream list and renders whatever
  comes back. That is the surface an interposed host would be talking to.
- **The Home menu confirms the withdrawal.** *Lecture en cours / Genres / Artistes / Albums / Plages /
  Dossiers* — no internet-radio entry, on a player that is at that moment playing internet radio.

## Why v1.2.1 looks broken

`browselib.js` builds its library tree exclusively from the `contentdb` REST half:

```text
contentdb/v100/audio/{genres,artists,albums,tracks}
contentplayer/v100/{operation,playqueue/tracks}
```

`contentdb` listings hang on the reference unit ([`../../docs/03-network-api.md`](../../docs/03-network-api.md)),
so the whole browser dies there while v1.0 — which never touches `contentdb` — works.

The failure is silent by construction: every handler tests `readyState == 4` and never the HTTP
status, then feeds the body straight to `JSON.parse`. An empty or error response throws inside the
callback, the exception dies there, and the `<div>` the click just opened stays empty forever. That
is exactly the reported symptom on an HAP-S1 — *“opens a small blank below but does not load
anything”* — so the two machines fail identically at the browser, whatever is happening underneath.

### The page has never worked, on any unit

Settled 2026-08-28. `GET /sony/contentdb/v100/audio/genres` on the HAP-S1 returns the **full genre
list** — `genreid`, `name`, `number_of_tracks`, per-genre `url` — so that machine's `contentdb` is
entirely healthy and the page is blank anyway. The fault is in the script, and it is not subtle:

```js
xhr2 = createXMLHttpRequest();          // assigned, used, works — gets paging.total
xhr2.onreadystatechange = function() {
    if (xhr2.readyState == 4) {
        ...
        xhr.open("GET", … + "?offset=0&limit=" + total, true);   // <-- xhr is not defined
```

**`xhr` is never declared or assigned.** Not in `browselib.js`, which reads it 30 times and assigns
it never; not in `HAP_ver.1.2.1.html`; and not in `haplib.js`, whose globals are `Xhr` and `XhrC` —
the only lowercase `xhr` there is the *parameter* of `XHRrequest(xhr, url, …)`. Every browse function
follows the same two-request shape and dies at the same line.

The `ReferenceError` is raised inside an `onreadystatechange` callback, so nothing surfaces: no
console banner, no failed request in the network tab — the second request is never issued at all —
just a `<div>` that opens and stays empty. It looks exactly like a dead backend, which is what both
of us assumed.

So the reference unit's hung `contentdb` explained nothing: v1.2.1 would be just as blank with a
perfectly live one. It reads like a global that was renamed to `Xhr` in `haplib.js` without anyone
updating the browser, and shipped.

**Consequences.** The catalogue line stands and is now evidenced: `contentdb` REST is healthy on a
contributor's `19404R` and hung on ours — a property of *our unit*. On a healthy player the library
tree is directly readable over REST, no `downloadByDiff` and no disk removal required. And v1.2.1 is
of no diagnostic use to anyone; only v1.0 is.

**Checked and cleared, so nobody else chases it**: `browselib.js` builds every URL as
`apiBaseURL + "/sony/…"` where `apiBaseURL` already ends in `/`, so every request goes out with a
doubled slash — `//sony/contentdb/…`. The player does not care: `//sony/contentplayer/v100/powerstate`
and `/sony/contentplayer/v100/powerstate` both return the same `200`. It is not the bug.

## Two things the pages do *not* do

- **The v1.0 “On Timer” is not a device feature.** `checkOnTimer()` computes a delay in the browser
  and arms a `setTimeout` that sends a power-on when it fires. Close the tab and it is gone; nothing
  is stored on the player. The real timer is JSON-RPC `system.setSleepTimer`, which the client
  already exposes — and which this discovery does not change.

  It is less odd than it looks: there is no device-side wake timer to expose. `setSleepTimer` turns
  the player **off**, and every candidate for the other direction — `getWolMode`, `getWuTangInfo`,
  `getPowerSavingMode` — answers `[12, "No Such Method"]` on this firmware. Faking it in the page
  was the only way to have the feature at all on a console whose author could assume the tab stays
  open.
- **The console is not hidden any more — it unhid itself in September 2025.** The markup ships
  `display:none`, and clicking the word **“Player”** in the title does toggle it, which is what this
  note first claimed was required. Reading `initialize()` rather than the markup says otherwise:

  ```js
  var now = new Date();
  if (now >= new Date(2025, 9-1, 24)) {
      setVisibility(true, Console_UI, mountSMB);          // console shown, unconditionally
  } else {
      if (now >= new Date(2021, 9-1, 24)) {
          e.style.animationPlayState = "running";         // "Player" starts fading on hover
      }
      setVisibility(cfgConsoleUIVisibility, Console_UI, mountSMB);   // cfg... is false
  }
  ```

  Three eras, on a hard-coded calendar: hidden before **2021-09-24**; hidden after it but with the
  word “Player” given a fade-in hover hint, for anyone who thought to try; and **shown to everyone
  from 2025-09-24 onward**. We are past that date, so the panel is simply there — reported
  independently by a contributor whose page opened fully without a click, on an HAP-S1.

  It reads on the browser's clock, not the player's, so it is a client-side unlock and nothing was
  scheduled on the device. The page still announces *“This page is out of support.”* Whatever the
  intent, someone wrote a date four years past the last firmware into a service page and shipped it.

## Reproducing

```bash
python tools/hap_screen.py <ip> show -o screen.png   # live front panel
python tools/hap_screen.py <ip> key option           # press OPTION
python tools/hap_screen.py <ip> capture              # write to HAP_Internal/anap/capture/
```

## Open

- Enumerate the rest of the namespace. `screen` and `keyevent` are the only two targets the pages
  use; whether the handler serves others is untested. A cautious fuzz of `target=` is the obvious
  next step, read-only cmds first.
- Whether `keyevent` accepts keys that have no front-panel button (numeric, direct-input).
- The pages are from 2014 and marked out of support. Nothing suggests removal in `19404R`, but a
  player on an older firmware should be checked before we build on this.

## Credit

Found because **Amos** noticed the two filenames on frazei's page and asked whether we had seen them.
Everything above followed from that one question.
