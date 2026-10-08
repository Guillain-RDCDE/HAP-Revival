# Contributing to HAP-Revival

Thanks for being here. The HAP-Z1ES / HAP-S1 community is small — every careful contribution materially advances the project.

> **Just own a HAP and want to help in five minutes?** Go to
> [`docs/HELP-IN-5-MINUTES.md`](../docs/HELP-IN-5-MINUTES.md) instead — read-only commands to
> copy and paste, and two menus to photograph. No Python, no account, no case-opening.

## What we need most, in priority order

1. **API method discoveries.** Anyone with a HAP on their LAN can fuzz the JSON-RPC surface on port 60200 and report a new working method (or a new working version of a known method). See [`research/api-method-catalog.md`](../research/api-method-catalog.md) for what's already mapped. Use the [API method issue template](ISSUE_TEMPLATE/api-method-discovered.yml).
2. **Hardware photos and findings.** Inside-the-case photos of the main board, FPGA, DSP, and the location of UART/JTAG headers are the single highest-leverage hardware contribution. We currently rely on Sony's service manual; verified high-res photos are better.
3. **Wireshark captures of the official iOS / Android apps in normal use.** Use a real device, run "HDD Audio Remote" or "Music Center," and capture the LAN traffic (mitmproxy + a self-signed cert if the app uses HTTPS, or plain tcpdump if HTTP). Anonymize and submit to `research/captures/`.
4. **UART console + NAND dump.** No public copy of the firmware exists, though Sony's update host turns out to be a plain file server and the image may yet be downloadable ([`docs/07-firmware.md`](../docs/07-firmware.md)) — the *running* system and the proprietary userland still have to be read off the device. Trace the `CSI0_DAT10/11` console pins to their board test points, attach a **3.3 V** USB-serial adapter (115200 8N1), capture the U-Boot/Linux boot log, and `dd` the rootfs (`/dev/mtdblock2`, JFFS2). Full guide: [`docs/10-uart-console.md`](../docs/10-uart-console.md). This is currently the single highest-leverage hardware contribution.
5. **Working code** — in flight. The Python client (`tools/hap_client.py`) and the browser-based control surface (`tools/webui.py`) shipped in the first session. A native iOS / iPad app is the next pipeline target, blocked only by getting a Mac into the build path.

> **Changing client code?** Read [`docs/16-gotchas.md`](../docs/16-gotchas.md) first. Several
> things that are correct everywhere else are broken on this player, and a green test suite has
> already hidden one such bug in this repository.

## Which machine can answer which question

Findings here are only as good as the hardware behind them, and no single player can produce them
all. Each player below can answer things the others cannot. Worth reading before asking someone a
question their device physically cannot settle.

| Player | State | Can settle | Cannot |
|---|---|---|---|
| **Reference Z1ES** (maintainer's) | `19404R`, HDD library, **internet radio works**, `contentdb` REST slow but healthy | Everything on the JSON-RPC, `contentplayer` and `contentdb` REST surfaces, the front panel over HTTP, push notifications, internet radio, the gotchas | Volume, tone control, anything S1, anything on an older firmware |
| **S1 at Amos's workplace** | `19404R`, backup slot holds **`0018120R`** | Volume (`0`–`74`), tone control reads, an S1 tone-control write | Not ours to risk. The one machine that *could* reach an older firmware, and the one we will not ask to |
| **S1 at Amos's home** | `19404R`, backup slot **spent** (both slots identical) | Second S1 data point | Cannot downgrade — the slot was burned by a re-flash |
| **Saschko's player** | German locale; he wrote the browser remote that drives its radio | A second locale's TuneIn tree — paths are locale-specific, so his are not ours | Model and firmware unknown to us |
| **Øyvind's S1** ([#1](https://github.com/Guillain-RDCDE/HAP-Revival/issues/1)) | `19404R`, Norway; its owner is willing to open the case | A third S1 data point, a Norwegian TuneIn tree, and possibly the first UART session | Nothing on an older firmware |

That table used to say radio worked on his player and not ours, and invited theories about why.
There was nothing to explain: radio works on ours too, and always did — we were calling the API
wrongly. See [`docs/16-gotchas.md`](../docs/16-gotchas.md) §6 for the header that hid it.

**What nobody can currently answer**, and what a new contributor would unlock:

- **A player running any firmware older than `19404R`.** For the archive: `0018120R` and
  `0017310R` are both known to exist and neither is running anywhere we can reach. (It no longer
  matters for the library API, which is alive on `19404R` too.)
- **An opened case.** No UART, no NAND dump, no board photographs of our own yet. One owner has
  offered ([#1](https://github.com/Guillain-RDCDE/HAP-Revival/issues/1)).
- **One capture of a firmware update check.** The update host is a plain file server, but the path
  to the image is not guessable ([`docs/07-firmware.md`](../docs/07-firmware.md)). It takes a
  machine that *routes* the player's traffic — a Linux box, a Mac or a Raspberry Pi acting as its
  gateway. Redirecting traffic from an ordinary PC on the same network was tried on 2026-08-31 and
  the player refused to connect. The radio half of the old capture question needed no capture at
  all: the player asks TuneIn's public API, and asking it the same thing gives the same streams.

## What we explicitly do not want

- Sony-copyrighted binaries (firmware blobs, decompiled APK source) committed to the repo. **The recipe to obtain them is fine; the artefacts themselves are not.**
- Pirated music in test data.
- Anything that bypasses streaming-service DRM (we integrate with Tidal/Qobuz/Spotify via their *legitimate* protocols, never around them).

## Workflow

Until we hit a v0.1 milestone, the workflow is intentionally light:

1. Open an issue describing what you want to do or what you found. Link prior issues / PRs.
2. For docs/research changes: small PRs are welcome anytime, no design discussion needed.
3. For code changes: open a draft PR early so we can discuss architecture before too much effort is spent.
4. For destructive operations (anything that could brick a HAP), nothing is merged without (a) a tested recovery path, (b) clear opt-in UX, (c) at least two contributors having tested on their own devices.

## Coding conventions

- **Python**: PEP 8 + type hints + `ruff` for lint (rules in `pyproject.toml`). Target Python 3.10+ for tooling, but anything that has to run *on the device* must work with the on-device Python 2.7 (until we replace the daemon).
- **One definition of each fact about the player.** The port numbers, share names, playable formats, junk patterns, catalogue schema and the JSON-RPC envelope each live in exactly one module, and every tool imports them from there:
  - `tools/hap_common.py` — ports, shares, cache locations, Wake-on-LAN, the TCP probe, JSON files, capture files, the UTF-8 console fix.
  - `tools/hap_media.py` — what the HAP plays, what it ignores, what must never reach it; the FLAC/WAV header readers; the 192 kHz PCM ceiling.
  - `tools/hap_catalog.py` — the `hdd_browse.db` schema, codec codes, and the read-only connection.
  - `tools/hap_client.py` — the ScalarWebAPI transport (`rpc_post`) under the `HAP` class; `call.py`, `discover.py` and `api-fuzzer.py` use it rather than their own.
  - `tools/hap_png.py` — the stdlib PNG encoder behind the mock's covers and the PWA icons.
  If you find yourself copying a constant or a helper between two tools, move it into one of these instead.
- **Scripts stay runnable as scripts.** Every tool is `python tools/<name>.py …` from any directory, with `main(argv=None)` taking an explicit argument list so tests can drive it, and no `sys.path` tricks.
- **The web UI's page lives in `tools/web/`** (`index.html`, `manifest.webmanifest`, `sw.js`), not inside `webui.py`; it is re-read on every request, so edit it with the server running.
- **Every user-facing string goes through `i18n.t()`**, and the catalogues are `tools/locales/<lang>.json` — one file per language, same keys in each (a test enforces it, placeholders included). Adding a string means adding its key to all six files; adding a language means one new file plus one line in `i18n.LANGUAGES`. The GUI's log lines and dialogs are no exception.
- **tkinter is touched from the main thread only.** A worker job gets everything it needs as arguments captured before it starts and reports back through the queue (`_emit`); reading a `tk.Variable` from the worker blocks outside the main loop, and the GUI tests run without one.
- **The mock device is the test bench.** `tools/mock_hap.py` answers the JSON-RPC surface, the contentdb and contentplayer REST surfaces, the front panel, TuneIn browsing, push subscriptions (with real UDP `NOTIFY` datagrams, three per event like the player) and the two documented gotchas (417 on `Expect`, no `Allow-Headers` on preflight). When you find a new behaviour on the real player, teach it to the mock in the same change.

### Running the checks

Everything CI runs, locally, with nothing but `pip install ruff pytest`:

```bash
ruff check tools/ tests/          # lint, rules from pyproject.toml
python -m compileall -q tools/    # every script still parses
python -m pytest                  # the offline suite: pure logic + a loopback mock device
```

No test needs a HAP. The suite drives every tool against `tools/mock_hap.py` on a loopback port,
and never touches `~/.hap-revival` (a fixture redirects the caches to a temp folder). The tkinter
tests (`tests/test_hap_gui_fix.py`, `tests/test_hap_gui_app.py`) need a display; they skip
themselves on a headless runner and CI runs them in their own job under `xvfb-run`:

```bash
xvfb-run -a python -m pytest tests/test_hap_gui_fix.py tests/test_hap_gui_app.py
```

`tools/smoke_live.py` is the check to run against your own player; the suite runs it against the
mock too (`--port`), so a regression in the checks themselves shows up without hardware.

- **Markdown**: prefer compact prose, tables for catalogs, ASCII diagrams where they help. Don't add a section unless it earns its place.
- **Commits**: imperative mood ("add discovery script", not "added discovery script" or "adding"). One logical change per commit.
- **PR titles**: short summary + scope tag if relevant: `[docs]`, `[tools]`, `[api]`, `[hw]`.

## Releasing

Every tool reports `tools/hap_update.VERSION` and compares it with the latest GitHub release, so a
release is three steps and a click:

1. Bump `VERSION` in `tools/hap_update.py` and turn the CHANGELOG's *Unreleased* section into
   `## [hap-sync-vX.Y.Z] — date`.
2. Tag that commit `hap-sync-vX.Y.Z` and push the tag, or run the *Release HAP Sync* workflow from
   the Actions tab on that commit (it then creates the tag from `VERSION` itself). The workflow
   builds `HapSync.exe` on Windows, refuses a tag that does not match `VERSION`, and opens a
   **draft** release with the exe and `SHA256SUMS.txt` attached.
3. Write the release notes on the draft and publish it. From that moment every installed copy
   offers the update: HAP Sync in its footer, the web remote in its banner, the command-line tools
   at the end of a run.

The update check reads the exe's SHA-256 from GitHub's asset digest (or the sums file, or the
notes) and refuses to install an exe it cannot verify, so never attach an unverified binary by hand.

## Reverse engineering ethics

This project operates on **legally owned personal hardware** (your own HAP-Z1ES). We:

- Use Sony's mandatory GPL release (oss.sony.net) for kernel and userland source.
- Read Sony's published service manuals, freely available on ManualsLib, Elektrotanya, etc.
- Decompile APKs that have been distributed by Sony for end-user installation.
- Probe network and physical interfaces of devices we own.

We do **not**:

- Distribute Sony's proprietary closed-source binaries.
- Reverse engineer for the purpose of replicating Sony's hardware commercially.
- Bypass DRM on copyrighted content.

If a contribution moves into legally grey territory, raise it in the PR — we'll discuss before merging.

## Code of Conduct

Be kind, be precise, assume good faith. We have neither the time nor the appetite for drama. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security

If you find a security issue with anything we ship (the future control daemon, the iOS app, etc.) please follow [SECURITY.md](SECURITY.md) — not the public issue tracker.

## Recognition

All contributors are credited in [CHANGELOG.md](../CHANGELOG.md) per release and in `README.md` once we add a contributors section. Code contributions are credited via git history; doc-only or research-only contributions are credited explicitly in the changelog.

Thank you. Let's keep good hardware alive.
