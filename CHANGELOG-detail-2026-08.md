# Detailed change log — August 2026

[`CHANGELOG.md`](CHANGELOG.md) says *what* changed. This file says **why**, at
length, for the cycle that began on 2026-08-15.

It is kept because a good part of it is the project correcting itself: six
published conclusions overturned, each written up next to the claim it replaced
rather than quietly edited away. That record is worth more than a tidy history,
and it does not belong on the page someone reads to find out what is new.

Newest first.

## Entries

### Fixed (2026-08-30, timeouts calibrated on one library are still guesses)

Every duration in the library tooling was measured against a single 78 369-track collection and
then written down as a constant. That repeats the six-second mistake more slowly: the cost of an
unfiltered request **is** the cost of counting the catalogue, so those seconds describe somebody's
music collection, not the device. A library several times larger pays twice — more pages, each of
them slower — and would have run straight into the ceiling.

- **The per-page deadline now doubles on each retry** (420 s → 840 s → 1680 s) instead of staying
  put, so a larger catalogue takes longer rather than failing, and the progress line says which
  attempt and which deadline it is on.
- **`--timeout` and `--harvest-timeout`** expose both floors, for collections beyond even that.
- **The harvest estimates from the pages this player has actually returned** rather than printing
  a number measured elsewhere: `artists 5000 / 17317 (40s, ~2 min left)`.
- The docs stop quoting these figures as properties of the device. Gotcha 7 now says outright that
  hard-coding the 90 s is the same error as hard-coding the 6 s.

### Changed (2026-08-29, the README, rewritten in two halves)

The front page listed thirteen tools and a test count that had been wrong for weeks, and asked a
new arrival to pick from a menu rather than showing them a path. It is now split the way the
audience is:

**Own a HAP? Start here** — five numbered things the player can do again, each one command or one
click, in the order someone actually wants them: get music on it, control it from a phone, play the
internet radio Sony removed, browse and search the library, then audit and repair the collection.

**Under the hood** — for anyone weighing whether to trust the project: what the machine is, the
three APIs on one port as a table, what has actually been established, the traps that make this
device unlike anything modern, and how the work is done. That last section says plainly that six
published conclusions have been overturned, five of them by a contributor, because a project that
corrects itself in public is easier to rely on than one that never appears to be wrong.

Also fixes the stale numbers (216 → 300 tests, thirteen → nineteen tools), adds a screenshot of the
Fix tab with the player's MAC masked, and re-points two documentation anchors at the headings that
replaced the ones they referenced.

### Added (2026-08-29, the front panel, mocked)

`mock_hap.py` now serves `/sony/hap` — a 480×272 framebuffer tinted by whatever is playing, and the
nine front-panel keys. `hap_screen.py` therefore runs with no hardware, like everything else. The
README had claimed as much since the endpoint was found on 2026-08-27; it was not true until now.

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
