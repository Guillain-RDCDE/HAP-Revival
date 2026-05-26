<!-- markdownlint-disable MD033 MD041 -->
<p align="center">
  <img alt="HAP-Revival — Modernizing Sony's audiophile HDD players" src=".github/banner.png" width="100%">
</p>

# HAP-Revival

> **Keeping the Sony HAP-Z1ES and HAP-S1 alive — for the music, not the plumbing.**
> Sony shipped its last firmware in January 2021. We're picking it up from there.

<p align="left">
  <img alt="status" src="https://img.shields.io/badge/status-pre--alpha-orange">
  <img alt="devices" src="https://img.shields.io/badge/devices-HAP--Z1ES%20%7C%20HAP--S1-blue">
  <img alt="license code" src="https://img.shields.io/badge/license%20(code)-MIT-green">
  <img alt="license docs" src="https://img.shields.io/badge/license%20(docs)-CC--BY--SA%204.0-lightgrey">
</p>
<!-- markdownlint-enable MD033 MD041 -->

---

## Why we're doing this

Put a 24/96 FLAC on a HAP-Z1ES, sit down, and the room changes. There's a stillness around the instruments. A cymbal decays longer than it has any right to. Cellos have weight; voices have a body; you can hear the space the recording was made in. This is what audiophile-grade source hardware is *supposed* to do — and what €500 streamers, however clever, still don't.

The HAP-Z1ES (2014, ~€2000 at launch) does it with a chain Sony's "ES" engineers clearly built to last: dual Burr-Brown **PCM1795** DACs in mono mode, an Analog Devices **SHARC** DSP, a custom Sony **FPGA** running the clock domain, a properly isolated linear PSU, a 14 kg chassis built like a piece of furniture. A decade on it still measures and sounds outstanding.

What didn't last is the software.

Sony shipped firmware **19404R** in January 2021 and quietly walked away. Five years later, the machine that does Mahler so well:

- still uses **SMBv1** for file transfers (broken on modern macOS, off by default on Windows),
- streams Spotify **only in standard resolution** — on a deck designed for hi-res,
- has **no Tidal, no Qobuz, no Roon, no AirPlay 2**, nothing added after 2016,
- runs an iOS remote ("HDD Audio Remote") that hasn't been touched since 2022 and may vanish from the App Store any day,
- boots a **Linux 3.0.35 kernel** with userland from the OpenWrt era.

The hardware deserves better. **HAP-Revival** is the open project to give it better — software worthy of the analog chain Sony built, written by people who actually listen on these things.

> *A personal note — I bought a HAP-Z1ES years ago because it sounded right, and it still does. Watching Sony abandon software this good felt like watching a beautiful instrument get locked in a cupboard. This repo is the lockpick. — Guillain*

## Status

**Pre-alpha. Research and reverse-engineering phase — and unapologetically a music project pretending to be a software project.**

Where we are:

- ✅ Mapped the network API surface (ports 60100/60200, ScalarWebAPI methods, MusicConnect UPnP).
- ✅ Documented the internal stack from Sony's GPL sources, service manuals, and community teardowns.
- ✅ Catalogued every public prior-art artefact so contributors don't redo work.
- ✅ Decompiled the `com.sony.HAP.HDDAudioRemote` Android APK (first public decompile of this client) and live-validated ~30 API methods from it.
- ✅ Shipped a small Python client library + a browser-based web UI you can use *today*.
- ⏳ Closing in on the `downloadByDiff` flow for full library DB sync.
- ⏳ Probing the UART debug port on the main board for a root shell.
- ⏳ Format-analyzing the 19404R firmware blob.

**Nothing in this repository will brick your device** at the current stage. Everything is network-passive and read-only — and even the playback control is bounded (the standby button asks before it presses anything).

## Supported devices

| Device | Status | Notes |
|---|---|---|
| Sony **HAP-Z1ES** | Primary target | Pure source player, no internal amp, clean analog out |
| Sony **HAP-S1** | Secondary target | Same SoC and stack, adds integrated amp (2× LM3876 + NJW1194 volume) |

Same i.MX6 SoC, same firmware images, same network protocols, same GPL bundle. Work on one transfers to the other.

## What works today

| Capability | Status | Notes |
|---|---|---|
| SSDP discovery of HAP devices on the LAN | ✅ | `tools/discover.py` — finds your HAP without you typing an IP |
| **Python client library** (typed dataclasses, importable) | ✅ | `tools/hap_client.py` — stdlib only, ~30 methods exposed |
| **Web UI control surface** (browser-based, single page) | ✅ | `tools/webui.py` — see [Try it now](#try-it-now-5-minutes-zero-risk) below |
| Now-playing (title / artist / codec / position / cover / RGB hint) | ✅ | `avContent.getPlayingContentInfo` v1.2 |
| Play / pause toggle, seek, next, previous, standby | ✅ | `pausePlayingContent` is a true toggle — counter-intuitive but reliable |
| Play track by ID (HDD content) | ✅ | `createPlayingListAndQuickPlay` v1.0 |
| Power: wake / wake-and-play / standby | ✅ | `setPowerStatus` with `active` / `play` / `off` / `standby` |
| System info, volume, sound settings, sleep timer, buffer time | ✅ | See [api-method-catalog](research/api-method-catalog.md) |
| DSEE / DSD-remastering / gapless / volume-normalization / oversampling | ✅ | `setSoundSettings` v1.1 round-trip validated |
| Sleep timer, buffer time, repeat, shuffle (per-source: HDD vs Spotify) | ✅ | All round-trip validated |
| Toggle favorites on tracks | ✅ | `editContentInfo` v1.0 with `tagUri:"meta:favorite"` |
| Spotify Connect detection + cover art | ✅ | Device serves HDD covers, Spotify CDN serves its own — both transparent |
| Web UI: ambient cover background, themes, adaptive contrast | ✅ | Four themes (Ambient / Solid-from-cover / Dark / Custom). Persisted. Text contrast auto-flips. |
| Web UI: Minimal mode + plain-language captions under every setting | ✅ | ⚙ panel hides chrome; each Sound/Playback option explains what it actually does in real English. |
| On-device library DB schema fully decoded | ✅ | 11 tables, ~60 PROP-codes — see [DB schema note](research/notes/2026-05-25-database-service-and-db-schema.md) |
| Library DB live download via `downloadByDiff` | 🟡 | Service responds; `location` field empty pending iOS capture during a real sync |
| Native iOS / iPad app | ❌ | The web UI works in Safari on iPad today; native app planned |
| Modern streaming services (Tidal, Qobuz, Roon) | ❌ | Requires custom userland (Phase 4) |
| Custom OS replacement | ❌ | Long-term goal; UART + firmware unpack required first |

## Try it now (5 minutes, zero risk)

You need a HAP-Z1ES or HAP-S1 on your LAN, Python 3.10+, and 5 minutes.

```bash
git clone https://github.com/Guillain-RDCDE/HAP-Revival.git
cd HAP-Revival

# Find your HAP automatically via SSDP
python tools/discover.py

# CLI client
python tools/hap_client.py <hap-ip> now-playing
python tools/hap_client.py <hap-ip> system
python tools/hap_client.py <hap-ip> sound

# Or launch the web UI and open http://localhost:8080
python tools/webui.py <hap-ip>
```

The web UI polls every 3 seconds — slightly tighter than Sony's own 5 s cadence for snappier feedback, well within what the device handles gracefully. (The HAP has no push mechanism; polling is the only option, as confirmed from the decompiled Sony app. So we just ask politely, every three seconds.) Cover art renders inline. The accent color follows the cover's dominant hue — the HAP itself computes that RGB and exposes it via the API, a small Sony detail that's genuinely delightful once you notice it. Click the progress bar to seek. The ⚙ icon top-right opens a theme switcher with adaptive text contrast.

**Nothing in this UI can damage the device.** Reads are pure. Playback is bounded. Standby confirms before sending. The whole client is one stdlib-only file (`tools/hap_client.py`), readable in an afternoon, importable as a module or used straight as a CLI.

## Roadmap

**Phase 1 — Reverse engineering (no risk to the device).**
Decompile the official APK, format-analyze the firmware blob, capture iOS app traffic, read Sony's GPL kernel patches and the `forza_snd_driver` source. *Current phase.*

**Phase 2 — Third-party control app.**
Modern web / iOS / iPad app talking to the *existing* ScalarWebAPI on port 60200. No firmware modification. Useful immediately for any HAP owner.

**Phase 3 — Root shell.**
UART probe or hidden-menu exploit to get a shell. Snapshot the rootfs as a safety net first. Re-enable the Dropbear SSH binary that already ships in firmware.

**Phase 4 — Custom userland.**
Keep Sony's kernel + `forza_snd_driver` (preserves the audio chain), replace the proprietary playback daemon with MPD + modern streaming bridges (librespot, mopidy, squeezelite). Requires a tested recovery path — we will not ship a phase 4 build before that exists.

**Phase 5 — Fully modern OS, modern app, new services.**
Mainline kernel where feasible, new control plane, multi-device fleet management, the iOS app talking to our own API instead of Sony's.

## Architecture (target end state)

```text
       ┌────────────────────────────────────┐
       │  iOS / iPad / Android / Web client │
       │  (modern UI, hi-res streaming UX)  │
       └─────────────────┬──────────────────┘
                         │ HTTPS + SSE — the HAP itself polls;
                         │              our future daemon
                         │              can finally speak push.
       ┌─────────────────▼──────────────────┐
       │  HAP-Revival control daemon        │
       │  (Python / FastAPI on the device)  │
       └─────────────────┬──────────────────┘
                         │
       ┌─────────────────▼──────────────────┐
       │  Sony's kernel 3.0.35 + forza_snd  │
       │  (preserved — drives FPGA + DSP)   │
       └─────────────────┬──────────────────┘
                         │ I²S
       ┌─────────────────▼──────────────────┐
       │  Sony FPGA → SHARC DSP → 2×PCM1795 │
       │  (the part that makes it audiophile│
       │   — untouched. This is why we're   │
       │    here in the first place.)       │
       └────────────────────────────────────┘
```

## Documentation

The full research lives in [`docs/`](docs/). Recommended reading order:

1. [Overview](docs/00-overview.md) — the project in one page
2. [Hardware](docs/01-hardware.md) — SoC, FPGA, DSP, DAC, ports
3. [Software stack](docs/02-software-stack.md) — OS, daemons, libraries
4. [Network API](docs/03-network-api.md) — ScalarWebAPI on port 60200
5. [SMB share](docs/04-smb.md) — file transfer protocol
6. [Diagnostic modes](docs/05-diag-modes.md) — DIAG + Special Mode entry sequences
7. [HDD swap recipe](docs/06-hdd-swap.md) — SSD compatibility, cloning
8. [Firmware](docs/07-firmware.md) — blob, GPL sources, partitions
9. [Prior art bibliography](docs/08-prior-art.md) — every existing artefact, ranked

Active reconnaissance lives in [`research/`](research/). Tools and scripts in [`tools/`](tools/). Living API spec in [`api-spec/`](api-spec/).

## Getting started (contributors)

You need a HAP-Z1ES or HAP-S1 on the same LAN, Python 3.10+, ~10 minutes, and ideally a record you love queued up to test against.

```bash
git clone https://github.com/Guillain-RDCDE/HAP-Revival.git
cd HAP-Revival
python tools/discover.py
```

This SSDP-probes your network, identifies any HAP devices, and dumps their full UPnP description + a sample of API responses to `research/captures/` for triage. **No write operations.**

To go further: read [CONTRIBUTING](CONTRIBUTING.md). If you've unearthed a Japanese teardown blog from 2015, captured iOS traffic in Wireshark, scanned a service manual, or just have your HAP on a different network than ours, you have something to contribute. Open an issue — we read all of them.

## Non-goals

- **Not a streaming service.** No music hosting, no DRM, no accounts.
- **Not selling hardware.** We help you keep yours alive longer. That's the whole pitch.
- **Not bricking your device.** Anything destructive will be gated behind explicit, documented opt-in.
- **Not replacing the analog chain.** The Sony FPGA → SHARC → PCM1795 path is the entire point of owning this hardware. We preserve it, period.

## Disclaimer

The HAP-Z1ES is out of warranty in 2026 regardless of what you do to it. That said: opening the case, probing UART, or eventually flashing custom firmware *can* damage your device. Everything in this repository is provided as-is, no warranty. **You are responsible for your own hardware.** Read the docs, take backups, ask before acting.

## License

- **Code** (anything under `tools/`, `api-spec/examples/`, future daemon code): [MIT](LICENSE).
- **Documentation** (anything under `docs/`, `research/`, this README, etc.): [Creative Commons Attribution-ShareAlike 4.0](LICENSE-docs).

The split keeps code maximally reusable (including by future iOS apps that might be commercial) while ensuring the painstakingly-collected documentation always remains open and credited. Knowledge about how the HAP works should never again be locked in one company's drawer.

## Acknowledgements

This project stands on a lot of shoulders.

- **Sony Engineering** — for shipping outstanding hardware in 2014 and publishing the GPL source bundle that makes this work possible. We mean it: most companies don't.
- **[danielrweber/HAPxFer](https://github.com/danielrweber/HAPxFer)** — the only third-party HAP project on GitHub before us, and a working reference for the SMB protocol.
- **[frazei](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a)** — for the first public documentation of the JSON-RPC control surface (July 2022). A single gist saved a year of work.
- **[rytilahti/python-songpal](https://github.com/rytilahti/python-songpal)** — protocol-cousin reference implementation we'll port from.
- **The Japanese audiophile community** (emuzu, briareos, saionjihouse, the kakaku.com regulars) — for a decade of hands-on HDD swap and modification documentation nobody in the English-speaking world has matched. もしこれを読んでいるなら、本当にありがとうございます。
- **You**, if you contribute — see [CONTRIBUTING](CONTRIBUTING.md). Especially you if you actually *listen* on one of these.
