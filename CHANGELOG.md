# Changelog

All notable changes to HAP-Revival will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once we ship a versioned release.

## [Unreleased]

### Added (2026-08-29, the local route, for libraries that are not tidy)

The previous entry assumed local folders that mirror the shares: swap the path prefix and you have
the album. That is the tidy case, and it is not everybody's.

So there are now two routes to the local copy, cheapest first, and you need neither:

1. **Prefix swap** — folders synced to the shares, using the mapping HAP Sync already stores. Exact,
   nothing to scan. On a mirrored setup it resolved **628 of 628** located findings.
2. **File names**, via `hap_fixit.py <ip> scan-local` or the **Index my folders** button — for a
   library filed differently from the player, or under different folder names. It is the same trick
   that locates albums on the player itself: index the folders once and vote. Local disks are fast:
   **90 204 files in 70 s**, against minutes over SMB1.

With neither, everything still works — the buttons open the player's own copy over the network,
which is exactly what happened before any of this existed.

The prefix swap wins whenever it resolves, so a scan never overrides an exact mapping. Also fills
`gui.validate_help` and `gui.diff_help`, missing from four catalogs since they were written.

### Added (2026-08-29, fix your own copy, then sync)

Correcting tags directly on the player works, but it is a write over SMB1 to a 2014 box that
handles one request at a time — fine for one album, painful for 274. Anyone who keeps local
folders synced to the shares already has a second copy of every one of those albums, on a local
disk, and **HAP Sync already knows the mapping**: `hap_sync.json` records `D:\FLAC\Internal →
HAP_Internal`. A share path therefore translates to a local one by swapping the prefix.

So it does. `HAP_Internal/Superpoze/(2010) Lost cosmonaut` becomes
`D:\FLAC\Internal\Superpoze\(2010) Lost cosmonaut`, and that is the folder Open and Tag editor
now reach for — in the GUI, the web panel and the CLI alike. The player's own path stays visible
and copyable underneath. Measured on a real setup: **628 of 628** located findings also existed
locally, so in practice every fix is a local edit followed by a normal sync.

A local path is only offered when the folder is actually there: a stale mapping must not send an
editor at something that has moved. Rows with a local copy are marked ▪, and after opening one the
log says what to do next rather than only printing a path.

### Added (2026-08-29, from "what is wrong" to "here it is, open it")

The audit could say 274 albums have no artwork. It could not say **where they are**, which is the
only thing that lets you fix them. New `tools/hap_fixit.py` closes that gap, and the same engine is
offered three ways: a **Fix tab** in the HAP Sync window, a **To fix** panel in the web UI, and a
standalone **HTML report** with copyable paths.

Locating a library entry on disk is harder than it sounds. The REST catalog returns an empty
`filepath` on every track, album folders are not named after the album tag (`Dummy (1994)` on disk,
`Dummy` in the tag), and many albums carry no album artist at all. **Matching on album names
resolved 0 of 12** real cases. **Matching on file names resolves 267 of 274** — every track carries
its exact file name, so indexing both SMB shares once (~4 min) and voting per album finds the
folder. It even survives folders spelled without the tag's accents.

A tie is reported as ambiguous and never resolved by guessing: those seven are albums that really do
exist twice on disk, which is worth knowing on its own.

**The most useful thing it reports**: several "coverless" albums already have a `cover.jpg` in the
folder. The player reads artwork **embedded in the tags**, so a loose image does not count — but it
does mean the artwork is already to hand, and the fix is thirty seconds in a tag editor. The report
says which case each album is.

Buttons open the folder in Explorer or hand it to Mp3tag (`/fp:`), configurable via `HAP_TAG_EDITOR`.
In the web UI they appear only when the browser is on the machine running the server, and the server
refuses any path that is not one of its own findings.

### Fixed (2026-08-29, driving the Fix tab for real)

Building the tab was not the same as it working. Three defects only surfaced once the App was
instantiated and its handlers called — none of them was visible to a linter, an import check, or a
human reading the diff:

- **Two handlers named things that do not exist**: `self.ip_var` (the IP lives in `host_var`) and
  `self._start_job` (it is `_run_async`). Both would have raised `AttributeError` on the first
  click. `tests/test_hap_gui_fix.py` now builds the real window, hides it, and calls every handler.
- **The findings spoke English inside a French window.** The detail strings were built in the engine
  with hard-coded English, so a French UI listed "2 tracks · no artwork in the folder either". All
  of it — details, category names, report headings, the HTML page — now goes through `i18n`, in all
  six languages, and a test pins the behaviour by comparing two languages.

One further trap worth recording: a per-test `tk.Tk()` fixture made the **second** test of the file
"skip" with a `TclError`, because building a second root after destroying the first fails on
Windows. The skipped test was the one that catches the `ip_var` class of bug. One module-scoped
root, reset between tests, and it runs.

### Fixed (2026-08-29, the share crawl)

- **A share crawl silently lost 90% of the second share.** Reusing one SMB connection across two
  long listings desyncs pysmb's SMB1 session; every subsequent `listPath` fails, and per-folder
  error tolerance swallows it. `HAP_External` came back as 5 931 files instead of 66 733, with no
  error. Now one connection per share, and unlistable folders are counted and reported. Gotcha 9.

### Added (2026-08-29, search, and the audit without a screwdriver)

**Search.** The web UI can now search the library by artist, album or track, case- and
accent-insensitively (`dvorak` finds `Dvořák`). The player has no search endpoint and one request
costs 30–60 s, so searching it directly is not possible; instead the catalog is harvested once and
matched in memory. The harvest takes about ninety minutes and monopolises the player, so it never
starts on its own — the UI says what it will cost and waits to be asked. It is cached at
`~/.hap-revival/library-<host>.json`, deliberately outside the repo: it is the user's own library
metadata and must not end up in a commit.

**The audiophile audit now runs over the network.** `library_audit.py --from-player <ip>` produces
the same Hi-Res / DSD / duplicate / missing-cover report that previously required pulling the drive
out of the machine. `RestAudit` presents the same interface as the SQLite `Audit`, so `build_report`
is untouched and both sources render identically.

Two figures the disk catalog has and REST does not: the **DRM flag** and the **channel count**. They
are reported as *not visible over the network API* rather than as zero — "no multichannel tracks" and
"we cannot see multichannel tracks" are different claims.

First run against a real library, over the network: 17 317 artists, 5 740 albums, **78 369 tracks**,
239 days of playtime, 93.2 % lossless, 4.6 % hi-res, no DSD, 274 albums without artwork and 391
duplicated titles. The harvest took 5 512 s.

### Fixed (2026-08-29)

- **A saturated entry was reported as a hi-res track.** One FLAC came back with `sample_rate`
  1 048 575 (2^20−1), `bit_rate` 2 147 483 647 (INT_MAX), `bit_width` 0 and `duration` 0 — every
  field a sentinel, on a file the indexer could not read. The audit announced it as a "1048.58 kHz"
  track exceeding the player's ceiling. Corrupt entries now get their own section, and the
  over-ceiling list holds only genuine files.
- **Two figures were wrong wherever they were written.** The library holds **78 369** tracks, not
  59 414 — that smaller number is genre 0's `number_of_tracks`, i.e. the tracks with *no genre tag*,
  misread as the library total. And a full harvest takes about **90 minutes**, not 11: the 11 was
  extrapolated from a single 52 s page, while under sustained load the player needs ~300 s per page.
  Both corrected in the docs, the tools and all six translations.
- **Clicking a track in the library did nothing.** The UI posted to `/api/play_track`; the route is
  `/api/play-track`. Found by driving the page's own JavaScript against the mock.
- **A harvest died on one character.** The player returns whatever bytes its catalog holds, so tags
  imported as Latin-1 arrive raw inside otherwise-valid UTF-8 — one artist in 17 317 here. That
  raised `UnicodeDecodeError` and lost a whole 343 KB page. Now decoded strictly with a Latin-1
  fallback for only the failing bytes, so the name is recovered rather than replaced. Gotcha 8.

### Added (2026-08-29, the library, over the network)

The web UI can now **browse the player's music library and play from it** — artists, albums,
playlists and favorites, drilling down to tracks, one tap to play. That closes the gap between this
remote and the app Sony withdrew: the transport controls were already here, the library was the
missing half.

It rests on `/sony/contentdb/v100`, which this project spent months believing was dead (see the
correction below). Two measured properties shape the design:

- **Root listings are slow and the cost is fixed** — 28–90 s whether you ask for 2 rows or 5000,
  which looks like the price of `paging.total` counting the whole table. They are cached; a second
  read of 17 317 artists comes back in 0.015 s.
- **Anything scoped by id is sub-second.** Drill-down needs no cache and gets none, so favorites and
  play counts are never stale.

Also confirmed live: the `trackid` the REST API hands out **is** the id `createPlayingListAndQuickPlay`
expects — `audio:track?id=<trackid>` — so browsing and playback share one namespace and the UI needs
no translation between them.

New `tools/hap_library.py` (client + CLI: `artists`, `albums`, `album-tracks`, `favorites`, `count`,
…), `/api/library/…` routes in `webui.py`, the same endpoints faithfully mocked in `mock_hap.py` so
`--demo` exercises the browser with no hardware, and 17 tests. Library strings translated into all
six languages.

### Corrected (2026-08-27, the console was never waiting for a click)

Same-day correction to the note below, from a contributor's HAP-S1 where the console panel appeared
without any click. Reading `initialize()` rather than the markup: v1.0 ships the panel
`display:none`, but **unhides it unconditionally on any browser whose clock reads 2025-09-24 or
later** — a date hard-coded four years past the last firmware. Between 2021-09-24 and that date it
stays hidden and the word "Player" merely gains a fade-in hover hint; the click has been unnecessary
since. It reads the browser's clock, not the player's.

Also corrected: v1.2.1's blank tree has nothing to do with our dead `contentdb`.

**`HAP_ver.1.2.1.html` has never worked, on any unit** (settled 2026-08-28). A direct
`GET /sony/contentdb/v100/audio/genres` on a contributor's HAP-S1 returns the full genre list, and
the page is blank there anyway. `browselib.js` reads a variable named `xhr` thirty times and never
assigns it; `haplib.js` calls its globals `Xhr` and `XhrC`. Every browse function raises
`ReferenceError` inside an `onreadystatechange` callback, where nothing surfaces — no console
banner, no failed request, because the second request is never issued. Just an empty `<div>` that
looks precisely like a dead backend.

Two things follow. The catalogue's claim that `contentdb` REST is healthy elsewhere and hung on the
reference unit is now evidenced rather than inferred — on a healthy player the library tree is
readable straight over REST, no `downloadByDiff` and no disk removal. And the doubled slash those
URLs carry (`//sony/…`) is **not** a factor either: the player serves it identically.

### Added (2026-08-27, the front panel over HTTP)

A contributor spotted two filenames on frazei's page — `/HAP_v1.0.html` and `/HAP_ver.1.2.1.html` —
and asked whether we had noticed them. We had not; port 60100 has no directory listing, so they are
only findable by name. They are served on `19404R`, and the script they load describes an API surface
that exists in no other source we hold.

- **A third API on port 60200: `/sony/hap?target=…&cmd=…`.** Confirmed live, reads and writes.
  - `target=screen&cmd=display_png` returns the **live 480×272 framebuffer of the player's own
    display** as a PNG — menus, highlight bar and all. `download_png` serves the same as a download;
    `capture_png` makes the player write it to `HAP_Internal/anap/capture/`.
  - `target=keyevent&cmd=<key>` injects a front-panel key: `home up down left right enter back
    option play`. Verified by driving the OPTION menu and returning to the starting screen without
    interrupting playback.
  - **Together they make the on-device UI scriptable** — everything Sony removed from the mobile app
    but left in the front-panel menus becomes reachable over the network, with no firmware, no UART
    and no NAND work.
- **The stream selector is observable.** Driving OPTION → *Flux* renders "Sélectionnez un flux" with
  what TuneIn offers for the station — three entries, all 320 kbps MP3. That is the surface an
  interposed host would be talking to, which sharpens the open bitrate question rather than settling
  it.
- **New tool**: [`tools/hap_screen.py`](tools/hap_screen.py) — `show`, `key`, `capture`. Stdlib only.
- **Three screens preserved** in `research/captures/`, and the full write-up with the evidence in
  [`research/notes/2026-08-27-hap-tool-endpoint.md`](research/notes/2026-08-27-hap-tool-endpoint.md).
- **Two corrections to what the pages appear to offer.** v1.0's "On Timer" is not a device feature —
  it is a `setTimeout` in the browser that sends a power-on; close the tab and it is gone. And
  v1.2.1's breakage on the reference unit is explained by `browselib.js` building its tree purely
  from the dead `contentdb` half, but that explanation does not carry to a player where `contentdb`
  answers and v1.2.1 is broken anyway.

### Fixed (2026-08-25, internet radio works — and always did)

Five days, three published theories, all wrong. Sony withdrew TuneIn from the mobile app and the
device's own menu — **not from the machine**. It has been reachable over the network the whole time.
A contributor pointed at the player's built-in web interface, `http://<ip>:60100/HAP_app.html`,
which still browses and plays TuneIn perfectly.

- **Radio browses and plays on the reference Z1ES**, verified end to end: the tree comes back
  localised, stations play, `getPlayingContentInfo` confirms a live MP3 stream.
- **Three self-inflicted causes, each producing `[1, "Any"]`:**
  - **`x-hap-device-id` breaks `getContentList` on a `netService:` URI.** With it, `[1, "Any"]`.
    Without it, the full directory. The catalogue used to call this header "optional". Now
    [gotcha 6](docs/16-gotchas.md).
  - **`scope: "directory"` is invalid for TuneIn** — omit it, or use `favorite`.
  - **`path` is a position in *this player's* tree and must match the station id.** Locale-specific:
    a French tree and a German one differ. Pairing an arbitrary path with an arbitrary id does
    nothing, silently.
- **`[1, "Any"]` is not a diagnosis** — the device's generic refusal, seen for at least three
  unrelated causes. Recorded as a corollary in the gotchas page, because every wrong theory this week
  rested on reading meaning into it.
- **New client support**: `radio_browse()` and `play_station_uri()`, plus `radio-browse` on the CLI.
  Browsing hands you a matched path and id, so it cannot be got wrong the way `play_station` can.
- **A shell trap, guarded**: Git Bash rewrites a bare `/` argument into the Git install root, so
  `radio-browse /` arrived at the player as `C:/Program Files/Git/`. An hour was spent blaming the
  device. The CLI now detects and repairs it, and accepts `root` as a synonym.
- **Retracted**: the note claiming TuneIn's servers were the problem. `Tune.ashx` behaviour was real
  and correctly measured, but it was never what stood between this player and a station.
- **18 new tests** (198 → **216**), including regression guards on the header and on the mangled path.

### Changed (2026-08-25, aligning the rest of the docs with the TuneIn finding)

- **The fleet table no longer describes Saschko's player by its account state.** Registration turned
  out to be irrelevant, so the row now says what actually matters: radio still plays on it, and it
  is the only machine that can test whether a *never-played* station resolves.
- **Added the packet capture to the list of things nobody can answer.** It is now the single
  highest-value contribution available to anyone with a HAP and ten minutes — it names the host the
  player calls for radio *and* reveals the firmware download URL.
- **The five-minute page leads with the useful question.** "Is your player registered" was the wrong
  thing to foreground; "does radio still work, and did you use TuneIn while Sony supported it" is
  the one that separates the players that work from the ones that don't. Added the decisive test for
  owners whose radio works: play a station you have never played before.

### Added (2026-08-25, TuneIn is alive — we were asking the wrong question)

- **TuneIn's device API still answers in 2026.** `opml.radiotime.com` returns `200` for `Browse.ashx`
  and `Describe.ashx`. Its stream-resolution call `Tune.ashx` returns **`400` without a `formats=`
  parameter** and **real stream URLs with one**. Tested live; the table is in
  [`research/notes/2026-08-25-tunein-is-alive.md`](research/notes/2026-08-25-tunein-is-alive.md).
- **TuneIn even has a message for devices like ours.** A resolution request that omits `formats`
  comes back well-formed, with the audio element pointing at a file called
  `notcompatible.enUS.mp3` — a spoken announcement. Somebody built that deliberately for legacy
  clients.
- **This reframes radio from lost to interposable.** Our documentation said Sony withdrew the
  service. The far end is up; what is broken sits between the HAP and a working `Tune.ashx` call.
- **It also gives the cache hypothesis a mechanism**: a player holding stream URLs from when the
  service worked never needs to call the endpoint that now fails, which is exactly why radio works
  on some machines and not others.
- **Prior art found, under a different name.** The vTuner directory behind a decade of Denon,
  Marantz, Yamaha, Onkyo and Pioneer receivers *was* discontinued, and the community answered with
  DNS interception and emulation — [YCast](https://github.com/milaq/YCast),
  [YTuner](https://github.com/coffeegreg/YTuner), [victorantos/denon](https://github.com/victorantos/denon),
  the last of which proxies HTTPS streams down to plain HTTP for receivers that cannot do TLS. That
  is the same shape the HAP needs, and searching for "HAP TuneIn fix" finds nothing precisely
  because the problem was solved for the neighbours under another service's name.
- **Still blocked on one capture**: we do not know which host the HAP contacts. It is not in the
  APK — the device does this, not the app. The same packet capture already queued for the firmware
  URL answers it.

### Added (2026-08-25, dead anchors can no longer hide)

- **New tool: [`tools/check_links.py`](tools/check_links.py)**, wired into the docs CI. markdownlint
  and lychee both ignore `#fragments`, so a link to a heading that no longer exists passes every
  check we had — two such links were dead for two weeks after a README rewrite before anyone
  noticed. Stdlib only, external URLs deliberately not checked. Verified it fails on a dead anchor
  and on a missing file, and passes on the current tree (40 Markdown files).

### Changed (2026-08-25, registration was never the gate)

Our second wrong explanation in two days, and the second corrected by an owner rather than by more
testing.

- **`registerDevice` is about cloud sync of favourites, not access.** We had concluded that
  per-device registration gated radio playback. Amos, who used TuneIn while Sony supported it:
  *"You can use TuneIn on the HAP units without being registered or having an account. When the
  service was officially supported you could login to save your favorites to/from the cloud but when
  Sony discontinued official support that quit working."*
- **The client no longer refuses on that basis**, which was a real functional bug: `play-station`
  would have blocked people whose players might well work. It now attempts, then **reads the state
  back** and reports whether anything actually started — the discipline gotcha 5 asks for, applied to
  the one call that most needs it. `play_station(..., verify=True)` returns a `"started"` flag.
- **`path` is not the gate either.** Tested on the reference Z1ES: `1/1/1`, `1/1/2`, `2/1/1`,
  `0/0/0` and an empty value all behave identically — accepted, playlist URI returned, queue empty,
  `playinginfo` `500`, previous playback cleared. The cause is upstream of both account state and
  path, and is **not yet understood**.
- **Leading hypothesis recorded, marked untested**: station resolution goes through a Sony back-end
  that is gone, and the players where radio still works resolve from their own local
  `tunein_browse.db`, populated while the service lived. That would also make `path` an index into
  that local list. **Only a working player can test it** — a station id that player has never used,
  under a fresh path.
- **The `path` uniqueness question is reopened**, not settled. The duplicate values in the published
  page are a known oversight: the author and Amos had discussed the numbering, and Amos corrects it
  before use — *"I don't know if it actually matters or not but I fixed it."* So nobody knows,
  including the two people it works for.
- **Saschko is credited** in the acknowledgements, at his request — a nickname, not his real name.
  With his message passed on: many thanks for the effort to keep the HAP-S1 and Z1 usable.
- **11 new tests** (187 → **198**), including a regression guard that playback never consults
  registration again.

### Added (2026-08-24, which machine can answer which question)

- **The test fleet is documented** in [`CONTRIBUTING.md`](.github/CONTRIBUTING.md). Four players,
  each able to settle things the others cannot: the reference Z1ES (everything except radio, volume,
  tone control and old firmware), Amos's workplace S1 (the only route to `0018120R`, and the one we
  will not ask him to risk), his home S1 (backup slot spent), and the German author's player
  (believed registered — the only machine we know of that can settle `path` and station playback).
  Written because we have twice been close to asking someone a question their hardware cannot
  answer.
- **What nobody can currently answer** is listed alongside it, as the honest recruitment pitch: a
  player on any firmware older than `19404R`, a registered player whose owner will run three calls,
  and an opened case.
- **Two broken anchors fixed** — `README.md#roadmap` and `README.md#why-were-doing-this`, both
  pointing at headings that vanished in the 2026-08-15 README rebuild and both silently dead since.
  Found by writing an anchor checker; the repo's link check does not cover fragments.
- **Three stale rows in the overview aligned** with what we now know: the firmware is no longer
  described as needing a NAND dump, OS acquisition leads with the CDN capture, and Special Mode is
  recorded as having five entries rather than being "the SMB version selector".

### Added (2026-08-22, a gotchas page, and a live check with teeth)

Prompted by the contributed script being broken by a refactor that added a correct-in-general,
wrong-here HTTP header. Any tidy-up tends to move code toward what is correct in general, which is
exactly what this player punishes — so the same failure mode is ours as much as his.

- **New page: [`docs/16-gotchas.md`](docs/16-gotchas.md)** — the five places where doing the correct
  thing breaks this player, in one place instead of scattered across three pages: `Content-Type` on
  browser requests, `Expect: 100-continue`, concurrent requests, non-uniform API versions, and
  success-shaped replies that mean nothing. Linked from CONTRIBUTING, the README index and the
  five-minute page.
- **New tool: [`tools/smoke_live.py`](tools/smoke_live.py)** — exercises the client against a real
  player and asserts values come back **populated**, not merely that nothing raised. Read-only by
  default; `--include-writes` adds writes that are idempotent by construction. Never in CI.
  - **Verified it has teeth**: re-introducing the exact `_first_field` unwrapping bug that green
    unit tests hid last week makes two of its checks fail. A smoke test that cannot fail is
    decoration.
  - It also asserts two gotchas are *still true* — the 417 on `Expect` and the missing
    `Access-Control-Allow-Headers` — so the documentation fails loudly if a firmware ever changes
    them.
  - 12 checks against the reference Z1ES: 11 pass, 1 skips (`volumelevel`, which 500s by design on
    a Z1ES).
- **Evidence tiers are now written down** in the catalogue, weakest to strongest: read from a binary
  → reported by a contributor → live-confirmed → **independently corroborated**. Only the CORS trap
  has reached the top tier.
- **Stopped overselling radio in the README.** The client "including internet radio" was true of the
  code and misleading about the outcome, since it refuses to run on unregistered players — which is
  most of them. Also corrected "each one runs against a built-in mock device": the live smoke test
  is precisely the one that cannot.

### Changed (2026-08-22, the CORS diagnosis confirmed from the other side)

- **The author of the contributed TuneIn page reached the same fix independently.** His page worked,
  then stopped after he let an AI refactor the JavaScript; the refactor had added
  `Content-Type: application/json`. He reverted to his original code, without the header, and it
  worked again — without knowing what we had found. Two people arriving at the same one-line cause
  from opposite directions is about as good as confirmation gets for this kind of thing. Recorded in
  `03-network-api.md`.
- **The `path` hypothesis is weakened, not confirmed.** We had guessed `path` must be unique per
  station, and that his "not every station loads" complaint was self-inflicted by a duplicate. His
  corrected page ships **three** stations sharing `1/1/3`, deliberately, written by the same person
  who told us to increment it. Either uniqueness does not matter or he still has the bug, and we
  cannot tell which from here: on an unregistered player, station playback does nothing, so there is
  no signal. Marked blocked on registration rather than left as a live guess.

### Added (2026-08-22, three of five push events measured, and a page for people who own one)

- **Which UDP events actually fire, measured.** Subscribed, then drove the player through queue
  changes, pause and resume. `playqueueChanged`, `playingtrackChanged` and `playinginfoChanged` are
  now **observed live**; the table in `03-network-api.md` says what triggers each. Two details worth
  building around: a queue change emits `playqueueChanged` immediately and `playingtrackChanged`
  about **seven seconds later** when the track really starts, so a client watching only one of them
  either acts early or lags. And **sound settings emit nothing at all** — there is no
  `soundSettingChanged`, so DSEE, DSD remastering, gapless, oversampling and tone control have to be
  re-read.
- **`contentdb` is not entirely dead.** `…/audio/albums/images/cover_art/<ID>` returns **200,
  `image/jpeg`, in 0.2 s**, while the listing for the *same album* hangs. Only the database-backed
  endpoints are unresponsive. The player also still emits `contentdb` URLs in its own `playinginfo`
  payload — firmware handing out links to its own dead endpoints, which is what withdrawal looks
  like rather than something never built.
- **New page: [`docs/HELP-IN-5-MINUTES.md`](docs/HELP-IN-5-MINUTES.md)** — read-only, copy-paste,
  no Python. Five asks, each with the reason it matters, plus the three traps that cost us evenings
  (PowerShell's `curl` alias, the serialising daemon, the hanging `contentdb`). Linked from the
  README and CONTRIBUTING. It exists because the biggest gains of the past week came from small
  precise asks to someone who owns the hardware, not from more analysis.
  - Every command in it was run in the shell it is written for. The registration check is given in
    three forms because the first one we wrote **failed in PowerShell** — quotes get mangled and the
    player answers `illegal Request`. PowerShell needs the `--%` stop-parsing token; `cmd.exe` does
    not.
- **`hap_notify` shuts down cleanly.** Closing the notifier while a listener thread was inside
  `events()` raised instead of stopping — found by running a real capture, not by reading the code.
  It now returns quietly, and a failed re-arm no longer kills the loop. Two tests cover both.
- **TuneIn pairing looks retired on TuneIn's side.** The player still issues PINs and they rotate
  daily, but `tunein.com/sony` and `tunein.com/activate` both 404. Players paired years ago keep
  working; players that never were — like ours — probably cannot be. Suggestive, not proven: we only
  tried the two obvious URLs.
- **Corrected a stale claim in CONTRIBUTING** that the firmware is "unobtainable, so there is no
  blob to `binwalk`".

### Added (2026-08-22, the Special Mode menu photographed, and a CORS trap)

- **Special Mode has five entries, not two.** Photographed on 19404R by Amos, closing a question
  this page had carried since it was written: alongside *SMB Version* and *Restart* there are
  **Clear Database**, **Reset to Default Settings** and **Restore Previous Version**.
- **The downgrade dialog names both versions before you commit**, which is the safety check we had
  been guessing at. On the unit photographed: current `0019404R`, previous **`0018120R`** — a
  firmware absent from our table and from every Sony page we have found. It sits between the dead
  `contentdb` of 19404R and the live one of 17310R, so whether *it* serves that API is now a
  concrete question.
- **A downgrade is probably a local rollback, not a re-download.** The dialog speaks only of content
  and the database, never of the network. If that holds, the "downgrade to sniff an OTA" plan is
  dead; capturing a *Network Update check* is unaffected and remains the route.
- **CORS characterised, and it explains a contributor's dead end.** The player answers preflights
  `200`, echoes `Origin` back, advertises `GET, POST, OPTIONS` — and never sends
  `Access-Control-Allow-Headers`. So a browser client that sets `Content-Type: application/json`
  gets its preflight rejected and reports what looks like an unreachable device; one that sets no
  `Content-Type` is a simple request and works. The device parses JSON without the header anyway.
  That is exactly why v1 of the contributed TuneIn page works and v2, which added the header, does
  not. Our `webui.py` proxies through a local server and is unaffected.

### Added (2026-08-21, internet radio — and why it does nothing here)

A HAP owner on the Steve Hoffman forums wrote an HTML remote that plays TuneIn stations on a player
where Sony removed radio from the front panel and both mobile apps. Contributed via Amos. Its whole
protocol content is one call, and it turned out to be a mode of a primitive we already use.

- **`createPlayingListAndQuickPlay` has a `"station"` mode.** Same method and version as HDD
  playback, but `playbackControlMode: "station"`, `listCount: 0`, and a
  `netService:audio?serviceName=tunein&path=…&id=s#####` URI. Documented in the catalogue.
- **Corrected within the day, before anything was built on it.** The first write-up concluded that
  Sony had withdrawn only *browse* and left *playback* working, so radio was restorable from
  outside. Testing it on our own Z1ES said otherwise: the call is accepted, returns a plausible
  playlist URI, and does nothing — the queue stays empty and the previous session is cleared.
- **The real gate is registration.** `registerDevice` with `method: "check"` returns
  `{"isRegistered": false}` here, and TuneIn on the HAP requires per-device pairing. That one fact
  explains both the empty queue and the `[1, "Any"]` from `getContentList`. The pairing flow is
  still alive — `method: "getPin"` returns a real code.
- **`registerDevice` is now LIVE-CONFIRMED** for `check` and `getPin`, having been APK-derived and
  untested since May.
- **New client support**: `radio_is_registered()`, `radio_registration()` and `play_station()` in
  `hap_client.py`, plus `radio-status` and `play-station` CLI commands. `play-station` **refuses to
  run on an unregistered player** rather than silently wiping playback, and `radio-status` prints
  the pairing PIN when the player is unbound.
- **Two response-shape corrections found while testing**: `playbackControlMode` is not validated at
  all — the device echoes back any string, including nonsense, so a successful-looking reply proves
  nothing. And `GET …/playinginfo` returns **500 when the play queue is merely empty**, not only
  when the device is asleep; the Crestron module's "404/500 means powered off" reading would report
  a live player as offline.
- **17 new tests** (164 → **185**). Note for the next person: `HAP.call` unwraps the single-element
  `result` list, so a fake `call` returning the *wrapped* shape will validate a client that reads
  nothing on real hardware. That happened here — the tests passed and the CLI printed an empty PIN
  against the live device. The recorder now documents the real contract and the parsing tolerates
  both.

### Added (2026-08-21, the netService whitelist, and a service withdrawn under the device)

- **`getContentList`'s `netService` shape is live-tested at last**, closing a gap the APK notes left
  open in May. The firmware's internet-radio whitelist is exactly **`{tunein, radiko}`**: both return
  `[1, "Any"]` (name accepted, service fails downstream), while `vtuner`, `spotify`, `bivl` and a
  nonsense control all return `[3, "illegal Argument"]`. Scope makes no difference. `getSourceList`
  is pinned to **v1.0** — every other version returns `[14, "Unsupported Version"]`.
- **Two independent sources now agree that vTuner was never supported**: the 2016 Crestron Help PDF
  marks `Source_Type_VTuner` as *"not currently supported by the device"*, and the 2026 firmware
  rejects the name outright.
- **TuneIn was withdrawn server-side during 2026, with no firmware change** (contributor report,
  Amos, corroborated by the `[1, "Any"]` signature above — the name is valid, the far end is gone).
  The device still carries the code. Recorded in `api-method-catalog.md`, because it is the clearest
  statement of why this project exists: the hardware is *still* losing functionality by remote
  action, a decade after release and five years after its last firmware.

### Added (2026-08-21, the firmware blob may not need a NAND dump after all)

- **Sony's update host is alive and is a plain file server.** `info.update.sony.net` resolves to
  Akamai, its certificate was **renewed on 2025-12-04**, and it answers **plain HTTP with no
  redirect to HTTPS**, `Server: AkamaiNetStorage`, `Accept-Ranges: bytes`, body `Not a file`. That
  is a static file store, not an application — so the firmware blob is very likely a public file
  fetchable with `curl` once we know its path, rather than something extractable only by dumping
  NAND over UART. `07-firmware.md` said the NAND route was "the realistic path"; that now reads as
  too pessimistic, and the page says so.
- **Recommended next step, and it risks nothing**: trigger *Settings → Network Update* on a device
  already running 19404R while capturing traffic. There is nothing newer, so nothing is written —
  but the request reveals the path scheme and the transport. If the version string is part of the
  path, older images including `0017310R` may be directly downloadable, which would hand us the
  live `contentdb` API **without downgrading anything**.
- **Reported: a firmware downgrade entry in Special Mode** (Amos, on 19404R) — the "other gated
  option" `05-diag-modes.md` has been asking about since it was written. Recorded as unverified: the
  reporter does not remember the wording, and our own notes list only *SMB Version* and *Restart* in
  that menu. Documented with the safety case attached, because unlike everything else on that page a
  downgrade is a firmware write and the only way back from a brick is a JTAG re-flash.
- **S1 volume range measured: 0–74**, not a percentage and not discoverable from the API. The
  earlier guess of a 50 ceiling was wrong.
- **The S1 runs `0019404R` too**, so the `volumelevel` divergence (200 on S1, 500 on Z1ES) is a
  **model** difference, not a firmware one. Question closed.

### Added (2026-08-21, the 417 trap, and a cousin module ruled out)

- **The `Expect: 100-continue` → `417` quirk now has a fix for every client, and the fix is tested.**
  We had documented the quirk but only given a remedy for Python `requests`. It cost a contributor
  an evening, because it bites *only requests with a body* — reads work, writes fail, and it reads
  like a syntax error. Reproduced against a Z1ES on PowerShell 5.1 (`$true` → 417, `$false` → 200)
  and confirmed at the protocol level: `POST /operation` returns 200 without the header and 417 with
  it. The subtlety that makes the fix fail silently is now written down — `ServicePoint` copies
  `Expect100Continue` when it is created, so the line must come before the *first* request to that
  host. Also noted: in Windows PowerShell 5.1 `curl` is an alias for `Invoke-WebRequest`, so `-X`,
  `-H` and `-d` are misparsed; call `curl.exe`.
- **Crestron STR-DN1050 module: checked and ruled out** (`docs/08-prior-art.md` §6b). Suggested by
  Amos on the reasonable hunch that another 2014-era Sony module might share the HAP's protocol. It
  does not: raw TCP on port 33335, a byte stream with no JSON, no REST, polling only. Verified that
  port 33335 is connection-refused on the HAP. Three Sony generations, three unrelated control
  planes — receivers on 33335, the HAP on 60200, the STR-DN1080 of 2017 on ScalarWebAPI 10000. Only
  the HAP-S1 shares the Z1ES's protocol.
- **Method recorded: any Crestron module's Help PDF is public** — fetch the product page, grep for
  `content/Help/`, fetch that URL. No account. Only the module package needs one. A sweep found 18
  Sony products on the market, none of them in the HAP family; that avenue is exhausted.
- **Reported on a real HAP-S1** (Amos): all three tone-control reads return data, and a
  `tonecontrolbass` write returns `200 {}`. Marked as a contributor report pending the capture
  files, not as verified.
- **The Z1ES/S1 volume divergence is now observed, and it exposes dead code in the module.** An S1
  answers `GET …/volumelevel` with `{"mute":"off","volume_level":7}` where the Z1ES returns `500` —
  but the response carries **no `volume_level_min` / `_max`**, the two fields the Crestron parser
  requires before it will emit any volume feedback at all. Cross-checked against the rest of the
  package: the SIMPL+ module exposes no volume signal, and the Help PDF documents none. Crestron
  wrote volume support against a response shape no shipping HAP produces and left it disconnected.
  Our client must treat `volume_level` as an opaque integer and must not rescale it to a percentage.

### Changed (2026-08-20, the web UI stops polling)

Follow-up to the teardown below, closing the two gaps that commit left open.

- **[`tools/webui.py`](tools/webui.py) is push-driven.** The server subscribes to the player's UDP
  notification stream and the browser long-polls `/api/events`, which is released the moment
  something changes — a track change now appears immediately instead of up to three seconds later.
  Verified end-to-end against a live Z1ES: a real push released the long-poll in 5.6 s of a 25 s
  window and moved the generation counter.
- **The timer stays, with a job.** It advances the progress bar and it is the whole story when push
  is unavailable — player asleep, `--demo`'s mock device, or the new `--no-push`. It ticks at 3 s
  without push and 10 s with it, and retunes itself when push comes or goes. `PushWatcher` retries
  in the background, so a player switched on later starts pushing without restarting the UI.
- **The progress bar is smoother while talking less.** Position is now advanced locally once a
  second from the last anchor the player gave us, instead of jumping on each poll.
- **`--no-push` and `--notify-port`** added for people who would rather not open a UDP port, or who
  need a different one.
- **The six-language claim now holds for the whole surface.** `hap_notify.py`'s CLI strings were
  English-only; they are in the catalogue in all six languages, and the tool takes `--lang` like
  every other. The web footer's `web.footer.polls` ("polls every 3s") became `web.footer.live`,
  since it was describing behaviour the UI no longer has.
- **18 new tests** (146 → **164**), all offline: the generation/long-poll semantics, one event
  releasing every waiting browser tab, junk `since` parameters, the no-watcher fallback, and three
  guards that fail if any of the new strings ever falls back to English.

### Added (2026-08-20, Crestron module teardown — two corrections and a second API)

The Crestron certified module for the HAP-Z1ES, contributed by **Amos**, who bought it for $0.00
from the Crestron Application Market. `docs/08-prior-art.md` had it listed as the single most
valuable missing artefact. It delivered more than the Help PDF: `Crestron.Sony.ContentServiceWebApi.dll`
is a complete, non-obfuscated protocol client that decompiles cleanly. Findings re-verified live
against a Z1ES on 19404R. Full teardown in
[`research/notes/2026-08-20-crestron-module-teardown.md`](research/notes/2026-08-20-crestron-module-teardown.md).

- **The HAP has push notifications — we said it didn't.** `POST /sony/notification/status` with
  `{"status":"enable","port":N}` returns `{"timeout":300,"port":N}` and the device then pushes
  pseudo-HTTP `NOTIFY` datagrams over UDP, each carrying an `event` name and a `url` to read the new
  state from, retransmitted three times under one `SEQ`. Verified live. The earlier "polling-only"
  conclusion came from an APK search for `switchNotifications` and WebSocket — both genuinely
  absent, but the mechanism is neither, and Sony's own app never subscribes. Corrected in
  `docs/03-network-api.md` and `research/api-method-catalog.md`.
- **`/sony/contentplayer/v100` is alive — we had the whole REST surface down as vestigial.** Power,
  transport, now-playing, sound settings, external input, plus one `POST …/operation` endpoint for
  every write, discriminated by a `method` field. Only the `contentdb` half is dead.
- **The `contentdb` hang is a dead handler, not an unknown route.** Unknown paths 404 in
  milliseconds; only `contentdb`'s leaves hang. Combined with the PDF naming vendor firmware
  `0017310R`, this points at a library API that was withdrawn between that firmware and 19404R —
  the first evidence an older firmware is functionally richer. See `docs/07-firmware.md`.
- **Trap documented: the daemon serialises requests.** One pending `contentdb` request makes every
  other endpoint time out, including ones that answered seconds earlier. Concurrent probing
  manufactures false negatives across the entire surface — it produced one on the notification
  endpoint during this very session. Probe sequentially with health checks.
- **New surface**: S1 tone control (`tonecontrolbass`/`treble`/`bypass`, −10…+10), SensMe channels,
  a `spotify_connect` source type absent from the 2016 enum, and an undocumented `streaming`
  content type that Crestron themselves could not parse.

Licence: the binaries are © Crestron Electronics. Protocol facts are documented and re-verified; no
decompiled code enters this repository.

- **New tool: [`tools/hap_notify.py`](tools/hap_notify.py)** — subscribes to the push stream and
  streams events, with `--follow` to read back the new state. Handles the three traps for you:
  `SEQ` deduplication, re-arming at 80% of the server-declared timeout, and priming Windows'
  stateful UDP filter so the firewall stops dropping the inbound datagrams. Smoke-tested against a
  live Z1ES: 15 datagrams in, 5 events out.
- **30 new tests** (116 → **146**), all offline. The parser is tested against a datagram captured
  verbatim from the device, the deduplicator against the real three-times-per-event retransmission
  pattern, and the notifier end-to-end over loopback. One test pins `SUBSCRIBE_PATH` to
  `/sony/notification/status` as a regression guard, since the Crestron module's own path omits the
  `/sony` prefix and 404s.

### Changed (2026-08-15, README rebuilt around what actually ships)

- The landing page opened on the manifesto and buried the working tools in a compressed table, so a
  visitor read *"pre-alpha research project"* before learning that ten finished tools are one click
  away. Rebuilt: hero with call-to-action buttons, **"What you can use today"** directly under it
  (one line per tool, each linked to its source, HAP Sync marked as the entry point), then the
  5-minute quickstart. The manifesto, the SMB story and the reverse-engineering status now sit
  *below* the tools. Dropped the `pre-alpha` badge; added release, test-count and language badges.

## [hap-sync-v0.2.0] — 2026-08-15

First published release with a downloadable binary
([`HapSync.exe`](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest/download/HapSync.exe),
Windows x64, 14.7 MB, self-contained — SHA-256
`8ca8edf7a9cbbed89c96d83a025cadfd9a9066a5cf8c454cefef01efd3d94db3`). The `hap-sync-v0.1.0` tag was
never attached to a GitHub release, so every download link in the README pointed at nothing.

### Fixed (2026-06-29, SMB1 transfer drops)

- **Transfers no longer stall mid-library.** The HAP's Samba 3.0.37 desyncs SMB1 framing over
  Direct TCP (port 445) after a file or two — surfacing as *"Invalid protocol header for Direct TCP
  session message"*. [`tools/hap_sync.py`](tools/hap_sync.py) now connects over **NetBIOS (139)**
  first, falling back to 445, and opens a **fresh session per file** so the connection never lives
  long enough to drift mid-stream. Validated against real hardware: files stuck for years go through.
- **Frozen-app settings persist** — [`tools/hap_gui.py`](tools/hap_gui.py) reads and writes
  `hap_sync.json` next to `sys.executable` instead of PyInstaller's temporary `_MEIPASS` dir.

### Added (2026-06-12, transfer plan: full visibility + add-only mode)

- **`Only add new files` mode** (GUI checkbox, **off by default**; CLI `--new-only` on `plan`/`sync`).
  The local library is the source of truth, so a normal sync faithfully mirrors it — a "changed"
  file (path already on the HAP but byte size differs, e.g. a re-tag or re-encode) **is** pushed by
  default; no exceptions. The opt-in add-only mode is for the rare case of adding files without
  overwriting anything already there. New engine helper `hap_sync.actionable(scan)` centralizes the
  filter; `scan_map` records the intent so the plan and the transfer stay in sync.
- **Plan now shows everything, grouped and explained.** Output is split into **CHANGED** (with
  `local X vs HAP Y, Δ±Z` per file, so it's obvious whether the audio really differs or it's just
  metadata) and **NEW**, sorted, no longer truncated at 12 lines. The GUI also writes the *complete*
  plan to `hap_plan_<share>.txt` next to the config every analysis, so nothing is ever hidden behind
  a cap. Fixes the "it says 100 files changed and I don't know what they are" confusion.

### Added (2026-06-12, built-in SMB doctor — diagnose & fix Windows access)

- **`tools/smb_doctor.py`** — a shared engine that diagnoses SMB access to the HAP and can repair
  the Windows-side breakage that OS updates keep reintroducing. Two independent concerns, kept
  distinct so users aren't misled:
  - **Authoritative transfer probe** — opens the HAP's anonymous SMB1 share via `pysmb` exactly
    like the transfer does. If it connects, syncing works *regardless* of any Windows SMB setting.
  - **Native-path checks (Windows only)** — `RequireSecuritySignature` (the 24H2/25H2 default that
    blocks the HAP), `EnableInsecureGuestLogons`/`AllowInsecureGuestAuth`, the SMB1 client feature
    (read from the `mrxsmb10` driver, no admin), and **genuinely** broken mapped drives. The last
    is verified by *actively* probing each mapping with `Test-Path` rather than trusting
    `Get-SmbMapping`'s Status field — an idle persistent mapping reports "Disconnected" yet
    reconnects fine, so trusting Status would tell users to delete working drives.
  - **One-click fix** — non-admin fixes (clearing stale mappings) run in the user session; admin
    fixes are bundled into a single self-elevating PowerShell (one UAC prompt). The split matters:
    an elevated process sees a different drive-letter namespace and wouldn't find the user's maps.
- **Wired into both surfaces**: the GUI's **Check** button now shows the full diagnosis and reveals
  a **Fix Windows access** button when there's something to repair ([`tools/hap_gui.py`](tools/hap_gui.py));
  the CLI gains `hap_sync check` (rich report) and `hap_sync check --fix` ([`tools/hap_sync.py`](tools/hap_sync.py)).

### Changed (2026-06-12, Windows SMB hardening troubleshooting)

- Expanded [`docs/04-smb.md`](docs/04-smb.md) with a **"Windows updates keep re-breaking access"**
  section. Each Win10/11 update can silently flip an SMB *client* default and lock you out of the
  anonymous HAP share even though nothing changed on the device. Documents the four knobs with check +
  elevated-PowerShell fix commands — **SMB signing now required by default on Win11 24H2/25H2**
  (`RequireSecuritySignature`, the most recent regression), insecure guest logons
  (`EnableInsecureGuestLogons` / `AllowInsecureGuestAuth`), and the SMB1 client feature — plus the
  **stale persistent-mapping gotcha** (a `Disconnected/Unavailable` mapped drive keeps forcing a bogus
  credential prompt; `net use * /delete /y` then reconnect as guest). Reiterates the two clean escapes:
  flip the device to SMB3 via Special Mode, or use `tools/hap_sync.py` (pysmb, bypasses the Windows SMB
  stack entirely).

### Changed (2026-06-03, UART session prep)

- Expanded [`docs/10-uart-console.md`](docs/10-uart-console.md) into a ready-to-run session guide while
  waiting for the USB-serial adapter:
  - **Re-verified the console pins against the authoritative IC101 pin table (p79): M1 = CSI0_DAT10 (TX),
    M3 = CSI0_DAT11 (RX), UART1 / `ttymxc0` @ 115200** — confirmed correct (the LCD RGB bus uses other
    CSI0_DAT balls in the N/P/R/T/U rows; don't confuse them).
  - **Board-level candidate `CN4008`** — the unqualified TXD/RXD console nets route to connector
    `CN4008` (MAIN schematic p47), which also appears on the MAIN PWB (p40): the likely factory debug
    header. Confirm its pinout empirically.
  - **Disassembly order** to reach the MAIN board (it sits under the FPGA-DSP board).
  - **Dump runbook**: interrupt U-Boot → `cat /proc/mtd` → `dd` each partition off via netcat over
    Ethernet *or* the SMB share; `mtd2` = the JFFS2 rootfs. Receiver (`nc`) confirmed available.

### Added (2026-06-03, hap_sync — a HAP-dedicated FreeFileSync replacement)

- **`tools/hap_sync.py`** — actually transfers music to the HAP and keeps it in sync incrementally
  (copies only new/changed files), over the device's **SMB1** share via **`pysmb`** — so you do
  **not** have to enable the insecure SMB1 client in Windows. Handles the **two-share** layout in one
  run: separate PC folders → `HAP_Internal` and `HAP_External`, configured in a small `hap_sync.json`
  (`tools/hap_sync.json.example` provided; the real one is git-ignored). Auto-skips junk
  (`.ffs_tmp`, `Thumbs.db`, `._*`…) and unsupported formats, preserves `<Artist>/<Album>/`, and offers
  `plan` (dry-run), `sync`, `list`, `wake` (WoL), `check`.
  - **On-disk remote-index cache** so we never re-list tens of thousands of files every run: the
    first run scans the share, then `plan`/`sync` read the cache instantly, and a `sync` folds the
    files it just uploaded into the cache (steady-state = no re-scan). `--refresh` / the `refresh`
    command force a full re-listing. Cache lives in `.hap_sync_cache/` (git-ignored).
  - **Live-tested end-to-end** against the device: anonymous SMB1 connect, full recursive listing
    (67k files), and a verified upload round-trip.
  - Robustness fix discovered in testing: a long SMB1 recursive listing can desync pysmb's session
    (breaking the next write) — `hap_sync` reconnects on any listing error and uploads on a fresh
    connection, which also made the remote listing complete/consistent.

### Added (2026-06-03, HAP companion tool)

- **`tools/hap_companion.py`** — makes any file-copy tool (FreeFileSync, rsync, drag-and-drop)
  HAP-aware, without replacing it. Stdlib only, read-only.
  - `validate <folder>` — pre-flight a music folder: flags **unsupported** codecs/containers, **junk**
    that pollutes the library (`.ffs_tmp`, `.part`, `Thumbs.db`, `._*`…), PCM **over 192 kHz** (the
    Forza PCM-path cap — reads FLAC/WAV headers to check real rates), and album folders **missing
    cover art**.
  - `diff <hdd_browse.db> <folder>` — semantic new-vs-already-on-HAP comparison of a local
    `<Artist>/<Album>/` tree against the device's own SQLite catalog (so you transfer only what's
    actually missing, by content). Validated against a real library (24,404 artist/album pairs).
  - `wake <mac>` (Wake-on-LAN) and `check <ip>` (reachability).
- **Fix:** both `hap_companion.py` and `library_browser.py` now tolerate the non-UTF-8 (latin-1) text
  that exists in some on-device DB rows (e.g. "Zé Roberto"), which previously crashed the SQLite read.

### Added (2026-06-03, library browser tool)

- **`tools/library_browser.py`** — a stdlib-only web browser for a HAP library, reading the
  on-device SQLite catalog (`hdd_browse.db`) directly: artists → albums → tracks, with cover art
  (served from the `PROP78D9` thumbnail BLOB), codec, sample-rate/bit-depth, durations, and search.
  Read-only (DB opened immutable), data never leaves the machine. It's the reference decoder for the
  `FTxx02`/`PROPxxxx` schema documented in `09-disk-layout.md`, and the foundation for a control-app
  library view (the live API can't list HDD content; `downloadByDiff` is blocked — but the SQLite is
  all we need). Validated against a real 77k-track library; it immediately surfaced ~68 orphan
  "tracks" that were actually FreeFileSync `.ffs_tmp` temp files the indexer had picked up.

### Added (2026-06-03, audio path decoded from the Forza driver)

- New [`docs/11-audio-path.md`](docs/11-audio-path.md): the full signal chain, read from the GPL
  `forza_snd_driver` source. The FPGA is an **Altera PCIe device** (`0x1172:0xE001`); the SoC DMA's
  audio into its FIFO. Decoded the two DSPs' actual jobs and mapped them to the app's sound settings:
  **ADSP-21488 SHARC = "HEQ"/DSEE-HX restoration + digital filter** (the "DSEE" toggle),
  **Cirrus CS48L10 = oversampling/SRC** (firmware `4up/2up/nonSRC` ↔ the "Oversampling" setting),
  plus the **DSD-remastering** mode machine (Direct.PCM / Direct.DSD / DSD_ReMaster.PCM). Documented
  the **`/dev/forza` ioctl ABI** — the lever a Phase-4 daemon uses to drive the chain while preserving
  Sony's analog path — and that DSP firmware lives on the rootfs at `/sony/lib/modules/dspfw/`.

### Changed (2026-06-03, repo-wide accuracy + clarity pass)

A full audit of every doc against the 2026-06-02/03 ground truth, to make the repo a reliable
reference for newcomers and specialists alike. Purged the claims that had become false and wired up
the new docs everywhere:

- **README**: named the DSPs (ADSP-21488 SHARC + CS48L10), corrected the status/roadmap (firmware is
  OTA-only — no "format-analyze the blob"; the OS path is UART → NAND dump), reflected that the full
  library DB is now in hand, and **added docs 09/10 to the reading order** (they were missing).
- **Killed the "firmware is downloadable" falsehood** in `07-firmware.md`, `00-overview.md`,
  `CONTRIBUTING.md`, `08-prior-art.md`, and `archive/README.md` — it is OTA-only with no public copy.
- **Removed the last "Tokyo Cabinet = library DB" relics** (`06-hdd-swap.md`, `08-prior-art.md`) and
  the "SHARC part not published" / "NAND not pinned down" hedges (`01-hardware.md`, `02-software-stack.md`):
  rootfs is `/dev/mtdblock2` JFFS2 on NAND (GPMI), SPI-NOR is an M25P32.
- **`04-smb.md`** gained a "Security boundary" section (anonymous read/write confirmed; symlink + HTTP
  traversal blocked; no safe Samba RCE) and the real on-disk share paths.
- **`03-network-api.md`** documents the vestigial `/sony/contentdb/v100` + MusicConnect endpoints.
- **`api-method-catalog.md`** reframes `downloadByDiff` as no-longer-a-blocker (DB obtained off-disk).
- Added dated **correction banners** to the superseded 2026-05 research notes (iOS postmortem,
  mitmproxy, database-service, downloadByDiff deep-dive) pointing forward to the 2026-06 findings.
- **`tools/hap_client.py` doc/bug pass, verified live against the device (2026-06-03):** the paused
  state wire value is **`PAUSED_PLAYBACK`** (not `PAUSED`) — fixed the now-playing CLI so a paused
  device renders correctly; corrected the repeat/shuffle `target` docstrings (canonical `'track'`;
  Spotify is `''`, not `'spotify'`); documented that `getSoundSettings` returns the value in
  `currentValue` (catalog + confirmed the client already reads it).

### Added (2026-06-03, OS acquisition recon + UART console identified)

- **UART serial console pinned down at the SoC** — new doc [`docs/10-uart-console.md`](docs/10-uart-console.md).
  From the IC101 pin-function table (service manual p75–79): the i.MX6 UART1 console (`ttymxc0 @ 115200`)
  is **ball M1 = CSI0_DAT10 (TX)** and **ball M3 = CSI0_DAT11 (RX)**; CSI0_DAT12/13 is the U-COM MCU
  link, CSI0_DAT14/15 the remote-learning link. Boot-mode straps hardwired for NAND. Full shopping
  list, 3.3 V safety rules, and the U-Boot→NAND-dump procedure included.
- **Audio DSPs identified** from the GPL `forza_snd_driver` source (downloaded): **ADSP-21488** SHARC
  (`adsp_21488.c`) + **Cirrus CS48L10** (`cdsp_cs48l10.c`). Updated `01-hardware.md` (were "not published").
- Full session record: [`research/notes/2026-06-03-os-acquisition-recon.md`](research/notes/2026-06-03-os-acquisition-recon.md)
  — firmware confirmed unobtainable publicly (99-agent sweep), GPL bundle fetched, and live-device
  software recon: Samba 3.0.37 anon RW to music shares but **symlink traversal blocked**, lighttpd
  **path traversal blocked**.
- **`/sony/contentdb/v100` REST API: confirmed NOT implemented on 19404R** (GET times out, POST 404
  while the same `:60200` ScalarWebAPI answers) — vestigial like MusicConnect; don't re-chase.
- **Flash layout learned from the GPL kernel** (pre-UART): cmdline `console=ttymxc0,115200
  root=/dev/mtdblock2 … rootfstype=jffs2`; rootfs is **writable JFFS2 on NAND mtd2**; SPI-NOR
  M25P32 (4 MB) holds U-Boot+kernel. Documented in `10-uart-console.md`.

### Added (2026-06-02, direct HDD read — on-disk layout + ground-truth DB schema)

- **First direct read of a HAP-Z1ES internal disk** (pulled, attached over USB, imaged + mounted
  read-only via WSL2). New canonical doc [`docs/09-disk-layout.md`](docs/09-disk-layout.md) and full
  forensic note [`research/notes/2026-06-02-hdd-direct-read-ondisk-findings.md`](research/notes/2026-06-02-hdd-direct-read-ondisk-findings.md).
- **Ground-truth DB schema committed** under [`research/db-schema/`](research/db-schema/) — `.schema`
  dumps of every on-device database (schema only, no library data). Confirms the schema reverse-engineered
  from the APK on 2026-05-25, with real row counts (77 668 tracks on the reference unit) and decoded enums
  (codec `PROP304B`: 49=FLAC/81=MP3/97=AAC/65=ALAC/129=WMA/17=WAV/33=AIFF; `PROP6844`=year; `PROP3047`=seconds).
- **Disk architecture established**: two ext4 partitions — `/data` (3 GB, the SQLite catalog, format
  `ver 14.00`) and `/mnt/internal` (928 GB, music under `storage/<Artist>/<Album>/` + a `db_storage/cover_art`
  cache). Files are `root:root 0700`; the indexer runs as root.

### Changed (2026-06-02, corrections from the disk read)

- **Library metadata store is SQLite, not Tokyo Cabinet** — corrected in `02-software-stack.md` and
  `06-hdd-swap.md`. Tokyo Cabinet is in the GPL bundle but is not the library DB.
- **The HDD holds no rootfs** — only `/data` + `/mnt/internal`. Partially answers Open Question #1 in
  `02-software-stack.md`; the OS lives on internal flash. Audio-path diagram paths corrected
  (`storage/` not `Music/`; `/data/*.db` not `library.tch`).

### Added (2026-05-26, web UI third pass — gear-panel controls, archive, Minimal mode)

- **Gear panel is now a full control surface**, not just a theme picker. New sections:
  - **Display** — Minimal mode toggle (hides the header "HAP-Revival · firmware · active" and the bottom footer for a stripped-down look). Choice persisted in `localStorage`.
  - **Sound** — pill toggles for DSEE (auto/off), DSD remastering (on/off), Gapless (auto/off), Volume normalization (auto/off), Oversampling (precision/normal). Each setting has a plain-language caption directly under it explaining what it actually does, plus a longer hover tooltip on the label. All five round-trip validated against the live device via `audio.setSoundSettings` v1.1.
  - **Playback** — Volume slider (auto-disabled on HAP-Z1ES, enabled on HAP-S1 with the device's min/max/step), Sleep timer dropdown auto-populated from `getSleepTimer` candidate seconds (Off + 10/20/30/40/50/60/90/120 min).
  - **Current track** — Favorite buttons (♥ / — / 👎) using `editContentInfo` with `tagUri:"meta:favorite"`. Auto-disabled when the current source is not an HDD track (Spotify Connect, radio, etc.) because Sony's editContentInfo only works on `audio:track?id=N` URIs.
- **Backend new endpoints** to back the above: `/api/set-sound`, `/api/set-volume`, `/api/mute-toggle`, `/api/set-sleep-timer`, `/api/set-favorite`. `/api/state` now also returns sleep_timer, volume, and favorite_type in the now_playing block. Each sub-fetch is try-wrapped so a partial device failure doesn't blank the whole UI.
- **Live-reload of HTML template** (commit a94d5d7) means editing CSS/JS in `webui.py` no longer needs a server restart — the HTML is re-read from disk on each GET. Cache-Control: no-store + Pragma + Expires so the browser never holds a stale copy. Adding new Python endpoints still needs a server restart since the Python class is loaded once at start.
- **Permanent archive of technical PDFs** under `archive/`:
  - HAP-Z1ES Service Manual (8.3 MB, SHA-256 documented in `archive/README.md`)
  - HAP-S1 Service Manual (10.4 MB)
  - HAP-Z1ES end-user Help Guide (1.3 MB)
  - HAP-S1 end-user Help Guide (1.4 MB)
  Total ~21 MB. Three docs that previously cited the now-dead `riverparkinc.com` mirror updated to point at the local archive. Documents legal stance + manual-download procedure for contributors who want to add more (e.g. the Reference Manual, Quick Start, RM-ANU183 remote manual).

### Added (2026-05-25, web UI second pass — themes, ambient bg, adaptive contrast)

Building on the first web UI commit (b7e3eb4), a focused polish round driven by live user feedback during the session:

- **Ambient cover background** (Apple Music / Tidal style). The current cover image fills the viewport, blurred to 60 px and saturated 1.8×, behind the now-playing card. Cards switch to frosted-glass over it. The cover element itself gets a soft glow tinted by the HAP-extracted dominant color.
- **Bug fix: `body` was opaque**, hiding `body::before` (the ambient layer) completely. Split the `html, body` shorthand so `html` keeps the dark fallback and `body` becomes transparent. The ambient mode actually shows up now — earlier "ambient" screenshots were pure black because of this.
- **Theme switcher** (⚙ icon top-right). Four modes:
  - **Ambient cover** (default)
  - **Solid (from cover)** — flat color = the RGB the HAP itself extracts from the cover
  - **Dark** — the original
  - **Custom** — native HTML5 color picker, choice persisted via `localStorage`
  Active selection visually highlighted (accent-tinted row + border). Selected theme + custom color survive reload (per-browser).
- **Adaptive text contrast**: when the background is bright (perceptual luminance > 0.6 via Rec. 601 weights), the UI switches to dark text + light frosted-glass cards. Auto-flipping `--fg`, `--muted`, `--card-bg`, `--hover`, and `--text-shadow` CSS variables. Header + footer also get an adaptive `text-shadow` for the worst-case mid-luminance covers. Recomputed both on cover change and on theme change.
- **`pausePlayingContent` is a TOGGLE, not just pause** — discovered when the user reported play not working after pause. The "naming-true" `pause()` / `resume()` library methods now check state first; the web UI uses `/api/toggle-playback` (direct toggle, single round-trip).
- **`setPowerStatus({status:"play"})` does NOT reliably resume Spotify Connect playback** — only the `pausePlayingContent` toggle does. The library's `resume()` documents this and uses the toggle.
- **Web UI live-reload**: the HTML template is re-read from the source file on every request via sentinel comments. Means iterating on CSS / JS no longer requires bouncing the server — F5 in the browser is enough. Cache-Control no-store + Pragma no-cache + Expires 0 on the HTML response so the browser cannot cache between reloads.
- **Server-side initial-cover URL**: the `--cover-url` CSS variable is now pre-populated server-side from the current `getPlayingContentInfo`, so the ambient background renders on the very first paint instead of waiting for the JS refresh tick.

### Added (2026-05-25, +5 ✅ set\* methods round-trip-validated; favorites unlocked)

- **5 setter methods** live-validated via round-trip ("set to current value = no net change"):
  - `audio.setSoundSettings` v1.1 `[{settings:[{target,value}]}]`
  - `avContent.setBufferTime` v1.0 `[{bufferTimeSec:N}]`
  - `avContent.setRepeatType` v1.0 `[{target,type}]`
  - `avContent.setShuffleType` v1.0 `[{target,type}]`
  - `system.setSleepTimer` v1.0 `[{status,sleepTimerSec}]`
- **Favorites unlocked** via `editContentInfo` v1.0 with `{method:"editTrackInfo", target:[{uri,tagUri:"meta:favorite",value:"favorite"|"dislike"|"normal"}]}` — Sony's `setFavorite` does not exist as a separate call.
- **Per-source repeat/shuffle**: `target:"track"` for HDD/USB, `target:""` for Spotify (Sony's canonical values from the APK).
- **`x-hap-device-id` header now sent by default** on every `hap_client.py` request (matching Sony's Android client; optional in practice but good hygiene).
- New library methods: `set_sound_setting`, `set_repeat`, `set_shuffle`, `set_buffer_time`, `set_sleep_timer`, `set_volume`, `mute_toggle`, `set_favorite`, `toggle_playback`.

### Added (2026-05-25, /sony/database service + on-device DB schema decoded + recfile transport)

- **`/sony/database` service confirmed live**. `checkSameDatabase` v1.0 returns `{isSameVersion, isSameName, type}` with the correct `database:<short_uuid>?dbType=hdd&...` URI.
- **`downloadByDiff` v1.0**: same shape; live still returns empty `location` even with Sony's exact request (header + `originalVersion=-1` + preflight `checkSameDatabase`). Pending mitmproxy capture of Sony's Android client during a real sync.
- **Complete on-device DB schema decoded** from `assets/demo_browse.db` (79 KB SQLite shipped in the Android APK, never publicly extracted before). 11 tables — `FT0000` (root), `FT0002` (tracks, 37+ columns), `FT000A` (albums with thumbnail BLOB), `FT4502` (genres), `FT5202` (artists), `FT6F02` (composers), `FT7002` (lyricists), `FTF003` (playlists), `FTF004` (playlist contents). ~60 PROP-code hex constants decoded (PROP3601 = id, PROP304B = codec, PROP3048 = sample rate, PROP10DE = bit width, PROP6844 = release date, etc.). Full breakdown in [`research/notes/2026-05-25-database-service-and-db-schema.md`](research/notes/2026-05-25-database-service-and-db-schema.md).
- **`recfile` generic transport mechanism** discovered. Some JSON-RPC methods (`getPlaylistInfo`, `downloadByDiff`, probably others) return `{location: "http://<ip>:60200/sony/avContent/recfile/requestN.data"}` instead of the payload itself. A plain HTTP GET on that URL returns the binary/text payload as `application/x-www-form-urlencoded` data (e.g. `newVersion=9&types=2&ids=-1&positions=...`). Confirmed via `getPlaylistInfo` on a freshly-created playlist.
- **APK deep-dive #2** (research/notes/2026-05-25-apk-deep-dive-downloadbydiff.md, ~600 lines): full Java code paths for `downloadByDiff`, `getRichMetaInfo`, `editContentInfo` dispatch, the polling state machine, etc.

### Added (2026-05-25, first working client + web UI)

- **`tools/hap_client.py`** — clean Python client library wrapping every confirmed API method. Stdlib-only (no `requests`). Typed dataclasses (`SystemInfo`, `NowPlaying`, `SoundSettings`, `SleepTimer`). Doubles as a CLI: `python tools/hap_client.py <ip> now-playing | pause | resume | seek N | play-track N | system | sound | sleep-timer | next | prev`.
- **`tools/webui.py`** — minimal stdlib HTTP server (no Flask, no aiohttp) serving an HTML5 single-page control panel at `http://localhost:8080`. Features: now-playing with cover art, dynamic accent color from the device's RGB hint, seek by clicking the progress bar, pause/resume/next/previous/standby buttons, live sound-settings display, 3-second polling matching Sony's own app. The first working third-party HAP control web app ever shipped.
- Live-validated against firmware 19404R: end-to-end functional with Spotify Connect playback (cover art from Spotify CDN renders correctly).

### Research (2026-05-25, post-APK-decompile)

- **Decompiled `com.sony.HAP.HDDAudioRemote` v4.3.1** (12.88 MB APK from APKCombo). First public decompile of this client. Full findings: `research/notes/2026-05-25-apk-decompile-findings.md` plus a deep-dive at `research/notes/2026-05-25-apk-deep-dive-downloadbydiff.md` (~1100 lines combined). Toolchain: OpenJDK 21 (winget) + jadx 1.5.5.
- **Live-validated 3 new methods** with Sony shapes:
  - `system.setPowerStatus v1.1` `[{status:"play"}]` ✅ resumes playback (wake + play, 4th status value)
  - `avContent.setPlayContent v1.1` `[{positionSec:N}]` ✅ seek-within-track (NOT a separate `seekStreamingContent`)
  - `avContent.createPlayingListAndQuickPlay v1.0` `[{uri,listIndex,listCount,playbackControlMode}]` ✅ THE HDD playback start primitive (Sony's UI calls this when you tap a track)
- **Discovered new service `/sony/database`** (live-confirmed exists, responds to `checkSameDatabase`). Sony uses it to sync the entire on-device music DB to a local SQLite mirror via `checkSameDatabase` + `downloadByDiff`. Highest-leverage target for unlocking HDD content browsing.
- **APK reveals 15+ new methods** Sony's client uses that we hadn't catalogued: `getSleepTimer`/`setSleepTimer`, `getSupportedFileType`, `createPlaylist`/`updatePlaylist`/`deletePlaylist`/`getPlaylistInfo`, `getStorageInformation`, `getBufferTime`/`setBufferTime`, `setAudioInput`, `getRichMetaInfo`, `editContentInfo`, `registerDevice`, `setRepeatType`/`getRepeatType`, `setShuffleType`/`getShuffleType`.
- **APK reveals 🟡 method shapes** for all previously-unknown methods. Notable corrections to our prior guesses:
  - `deleteContent.uri` is a JSON **array** of URI strings, not a scalar.
  - Pause/next/previous need `params:[{}]` (empty object inside array), not `[]`.
  - `scanPlayingContent` is FF/REW with `{direction:"fwd"|"bwd"}` — NOT scrub-to-position.
  - `getContentList v1.3` is for **internet radio (netService) only** — HDD content is browsed via the `database` service's local SQLite cache, not via getContentList.
- **Confirmed: HAP has no WebSocket notifications.** Sony's app uses 4 polling threads at 5 s cadence. Our client design should do the same — stop investigating push mechanisms.
- **Corrections vs APK agent's report** (live tested 2026-05-25):
  - `/sony/<service>` IS required on firmware 19404R (agent claimed otherwise — wrong).
  - `x-hap-device-id` header is optional (agent claimed mandatory — wrong, our calls work without).
  - `/turnOn`, `/turnOff` plain HTTP endpoints return 404 on firmware 19404R (agent claimed they exist — wrong on this firmware; possibly HAP-S1 only or removed).
- **Side effect documented**: my own probing during the session accidentally paused user's music (the 🟡 setPlayContent calls returned `[1, "Any"]` errors but had side effects). Recovered via `setPowerStatus({status:"play"})`. Lesson: **`[1, "Any"]` does not mean "no effect"** — some methods partially succeed even when reporting an error. Test only with disposable content going forward.

### Research (2026-05-25, post-fuzz)

- **First `tools/api-fuzzer.py` run on a live HAP-Z1ES (firmware 19404R)** — 53 method+service candidates tested, up to 8 versions each. **24 methods confirmed to exist** on the device (up from 10 previously known). Output: `research/captures/fuzz-192_168_1_28-20260525T184419Z.json`.
- **New methods discovered to exist** (parameters TBD): `system.setPowerStatus` v1.1, `audio.setAudioMute` v1.1, `avContent.setPlayContent` v1.1 (was Unsupported at v1.0), `avContent.stopPlayingContent` v1.0, `avContent.scanPlayingContent` v1.0, `avContent.getContentInfo` v1.1, `avContent.getContentList` v1.3 (was Unsupported at 1.0/1.2), `avContent.deleteContent` v1.1 (flagged dangerous), `guide.getServiceProtocols` v1.0.
- **New methods confirmed working with empty params**: `audio.setSoundSettings` v1.1 and `avContent.setPlaybackModeSettings` v1.0 — both reply with empty result (noop with no params).
- **New error codes documented**: code `1 "Any"` (generic / invalid value) and code `3 "illegal Argument"` (missing/wrong parameter), in addition to the previously known `5/12/14`. Gives finer-grained method-existence detection.
- **Settled negatives**: HAP cannot self-update via API (no `getSWUpdateInfo`/`actSWUpdate`), seek within track not exposed (no `seekStreamingContent`), favorites and Bluetooth not exposed.

### Research (2026-05-25, initial reconnaissance)

- **Network surface mapped** on a live HAP-Z1ES (firmware 19404R, 2026-05-25):
  - Confirmed SSDP banner `Linux/3.0 UPnP/1.0 Sony-HAP/1.0`
  - Confirmed open TCP ports: 139, 445, **60100** (lighttpd / UPnP description), **60200** (ScalarWebAPI JSON-RPC)
  - Confirmed alternate Sony API ports (10000, 54480, 52323) are **closed** on HAP — settled the python-songpal#29 ambiguity
  - Captured full `/hap.xml` device descriptor with `MusicConnect:1` + `ScalarWebAPI:1` service entries
  - Verified working methods: `system.getSystemInformation` v1.2, `system.getPowerStatus` v1.1, `audio.getVolumeInformation` v1.1, `audio.getSoundSettings` v1.1, `avContent.getPlayingContentInfo` v1.2, `avContent.pausePlayingContent` v1.0
- **Hardware confirmed**: SoC is NXP **i.MX6 Dual** (`MCIMX6D5EYM10AC`, Cortex-A9 dual @ 1 GHz) per Sony service manual `IC101` part number. Earlier i.MX53 inference (Cortex-A8 single) corrected.
- **Software stack confirmed** from Sony's [oss.sony.net GPL release](https://oss.sony.net/Products/Linux/Audio/HAP-S1.html):
  - OpenWrt trunk r35385 base
  - Linux 3.0.35, U-Boot 2012.04.01
  - Samba 3.0.37, Dropbear 2012.55, lighttpd 1.4.35
  - GStreamer 0.10.36 + Freescale plugins
  - **Custom `forza_snd_driver` kernel module** (Sony codename "forza") — source available in GPL bundle
  - **Control daemon is Python 2.7 + web.py 0.37 + lighttpd**, not C
  - Front-panel UI is DirectFB 1.4.17 (no X11)
- **Service DIAG menu entry corrected**: requires HOME + BACK held, then PLAY then POWER (4-key combo, not 2).
- **HDD swap recipe documented**: sector-clone via KURO-DACHI/CLONE/U3 preserves DB; Crucial MX500 / KIOXIA recommended; avoid Samsung 860/870 EVO.
- **Exhaustive prior-art inventory completed** — entire public corpus consists of one Swift app (HAPxFer), one 10-line gist (frazei), one Python file organizer (music-organizer), one stuck issue (python-songpal#29), Sony's GPL drop, a Crestron module, and the JP hardware-mod blogs. See [`docs/08-prior-art.md`](docs/08-prior-art.md).

### Added

- Initial repository structure, README, license split (MIT code / CC-BY-SA 4.0 docs), CONTRIBUTING, CHANGELOG.
- Documentation set (`docs/00–08`) covering overview, hardware, software stack, network API, SMB, DIAG modes, HDD swap, firmware, and prior art.
- Tools: `tools/discover.py` (SSDP + API probe), `tools/api-fuzzer.py` (method×version brute force), `tools/apk-decompile.md` (recipe).
- Issue templates for API method discoveries, hardware findings, and bug reports.
- Living API method catalog at [`research/api-method-catalog.md`](research/api-method-catalog.md).
