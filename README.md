<p align="center">
  <img alt="HAP-Revival — Modernizing Sony's audiophile HDD players" src=".github/banner.png" width="100%">
</p>

# HAP-Revival

> **Modernizing the Sony HAP-Z1ES and HAP-S1 audiophile HDD players.**
> Sony stopped shipping software in January 2021. We're picking it up.

<p align="left">
  <img alt="status" src="https://img.shields.io/badge/status-pre--alpha-orange">
  <img alt="devices" src="https://img.shields.io/badge/devices-HAP--Z1ES%20%7C%20HAP--S1-blue">
  <img alt="license code" src="https://img.shields.io/badge/license%20(code)-MIT-green">
  <img alt="license docs" src="https://img.shields.io/badge/license%20(docs)-CC--BY--SA%204.0-lightgrey">
</p>

---

## Why this project exists

The Sony HAP-Z1ES (released 2014, list price ~€2000) is an audiophile-grade HDD music player built around a serious analog chain: dual Burr-Brown **PCM1795** DACs in mono mode, an **Analog Devices SHARC** DSP, a custom **FPGA**, and a clean linear power supply. Sony's "ES" line still represents some of the best mass-produced source hardware of the decade.

Sony shipped the last firmware (**19404R**) in January 2021 and walked away. Five years later, the device:

- Still uses **SMBv1** by default for file transfers (broken on modern macOS, requires disabling Windows security defaults).
- Streams Spotify **only in standard resolution** — on a machine designed for hi-res audio.
- Has **no Tidal, no Qobuz, no Roon, no AirPlay 2**, no service added after 2016.
- Runs an iOS app ("HDD Audio Remote") that hasn't been updated since 2022, looks like 2014, and may be removed from the App Store at any moment.
- Boots a **Linux 3.0.35 kernel** with userland from the OpenWrt era.

The hardware deserves better. **HAP-Revival** is the open project to give it better.

## Status

**Pre-alpha. Research and reverse-engineering phase.**

We are currently:

- ✅ Mapping the network API surface (ports 60100/60200, ScalarWebAPI methods, MusicConnect UPnP service).
- ✅ Documenting the internal hardware stack from Sony's published GPL sources, service manuals, and community teardowns.
- ✅ Cataloging every public prior-art artefact so contributors don't re-do work.
- ⏳ Decompiling the `com.sony.HAP.HDDAudioRemote` Android APK to recover the full API method dictionary.
- ⏳ Probing the UART debug port on the main board for a root shell.
- ⏳ Format-analyzing the 19404R firmware blob.

**Nothing in this repository will brick your device** at the current stage. All reconnaissance is network-passive and read-only.

## Supported devices

| Device | Status | Notes |
|---|---|---|
| Sony **HAP-Z1ES** | Primary target | Source player only, no internal amplifier; clean analog output |
| Sony **HAP-S1** | Secondary target | Same SoC and software stack, adds integrated amplifier (2× LM3876 + NJW1194 volume) |

The two devices share the same i.MX6 SoC, same firmware images, same network protocols, and the same `oss.sony.net` GPL source release. Work on one transfers to the other.

## What works today

| Capability | Status | Notes |
|---|---|---|
| SSDP discovery of HAP devices on the LAN | ✅ | `tools/discover.py` |
| **Python client library** (typed dataclasses, importable) | ✅ | `tools/hap_client.py` — stdlib only |
| **Web UI control surface** (browser-based) | ✅ | `tools/webui.py` — see [Try it now](#try-it-now-5-minutes-zero-risk) |
| Now-playing read (title/artist/codec/position/cover/RGB hint) | ✅ | `avContent.getPlayingContentInfo` v1.2 |
| System info, volume, sound settings, sleep timer, buffer time | ✅ | See [api-method-catalog](research/api-method-catalog.md) |
| Play track by ID / pause / resume / seek / next / previous | ✅ | `createPlayingListAndQuickPlay`, `setPlayContent`, etc. |
| Power control: wake / wake-and-play / standby | ✅ | `setPowerStatus` with `active` / `play` / `off` |
| Spotify Connect detection + cover art via Spotify CDN | ✅ | Auto-rendered in the web UI |
| On-device library DB schema fully decoded | ✅ | 11 tables, ~60 PROP-codes — see [DB schema note](research/notes/2026-05-25-database-service-and-db-schema.md) |
| Library DB live download via `downloadByDiff` | 🟡 | Service responds; `location` field empty pending more reverse-engineering |
| Native iOS / iPad app | ❌ | Web UI works in Safari on iPad today; native app planned |
| Modern streaming services (Tidal, Qobuz, Roon) | ❌ | Requires custom userland on the device (Phase 4) |
| Custom OS replacement | ❌ | Long-term goal; UART + firmware unpack required first |

## Try it now (5 minutes, zero risk)

You need a HAP-Z1ES or HAP-S1 on your LAN, Python 3.10+, and 5 minutes.

```bash
git clone https://github.com/Guillain-RDCDE/HAP-Revival.git
cd HAP-Revival

# Find your HAP automatically via SSDP
python tools/discover.py

# Use the CLI client
python tools/hap_client.py <hap-ip> now-playing
python tools/hap_client.py <hap-ip> system
python tools/hap_client.py <hap-ip> sound

# Or launch the web UI and open http://localhost:8080
python tools/webui.py <hap-ip>
```

The web UI polls every 3 seconds (matching Sony's own polling cadence — the HAP has no push-notification mechanism). Cover art renders inline. The UI's accent color follows the cover art's dominant color (the HAP itself computes and exposes this RGB hint via the API). Click the progress bar to seek.

**Nothing in this UI can damage the device.** Reads are pure. Playback control is bounded. The "standby" button asks for confirmation before sending. The library shipping the calls is at `tools/hap_client.py` — 350 lines, well-commented, stdlib only.

## Roadmap

**Phase 1 — Reverse engineering (no risk to the device).**
Decompile the official APK, format-analyze the firmware blob, capture iOS app traffic in Wireshark, read Sony's GPL kernel patches and the `forza_snd_driver` source. *Current phase.*

**Phase 2 — Third-party control app.**
Modern web / iOS / iPad app talking to the *existing* ScalarWebAPI on port 60200. No firmware modification. Useful immediately for any HAP owner.

**Phase 3 — Root shell.**
UART probe or hidden-menu exploit to obtain a shell on the device. Snapshot the rootfs as a safety net. Re-enable the Dropbear SSH binary that already ships in firmware.

**Phase 4 — Custom userland.**
Keep Sony's kernel + `forza_snd_driver` (preserves the audio chain), replace the proprietary playback daemon with MPD + modern streaming bridges (librespot, mopidy, squeezelite). Requires a tested recovery path.

**Phase 5 — Fully modern OS, modern app, new services.**
Mainline kernel where feasible, new control plane, multi-device fleet management, the iOS app talking to our own API instead of Sony's.

## Architecture (target end state)

```
       ┌────────────────────────────────────┐
       │  iOS / iPad / Android / Web client │
       │  (modern UI, hi-res streaming UX)  │
       └─────────────────┬──────────────────┘
                         │ HTTPS + WebSocket
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
       │   — untouched, no excuses)         │
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

Active reconnaissance work lives in [`research/`](research/). Tools and scripts in [`tools/`](tools/). Living API spec in [`api-spec/`](api-spec/).

## Getting started (contributors)

You need a HAP-Z1ES or HAP-S1 on the same LAN, Python 3.10+, and ~10 minutes.

```bash
git clone https://github.com/Guillain-RDCDE/HAP-Revival.git
cd HAP-Revival
python tools/discover.py
```

This will SSDP-probe your network, identify any HAP devices, and dump their full UPnP description + a sample of API responses. **No write operations.** Output is saved to `research/captures/` for triage.

To go further: read [CONTRIBUTING](CONTRIBUTING.md).

## Non-goals

- **Not a streaming service.** No music hosting, no DRM, no accounts.
- **Not selling hardware.** We help you keep yours alive longer.
- **Not bricking your device.** Anything destructive will be gated behind explicit, documented opt-in.
- **Not replacing the analog chain.** The Sony FPGA → SHARC → PCM1795 path is the point of owning this hardware. We preserve it.

## Disclaimer

The HAP-Z1ES is out of warranty in 2026 regardless of what you do to it. That said: opening the case, probing UART, or eventually flashing custom firmware *can* damage your device. Anything in this repository is provided as-is, with no warranty. **You are responsible for your own hardware.** Read the documentation, take backups, ask questions before acting.

## License

- **Code** (anything under `tools/`, `api-spec/examples/`, future daemon code): [MIT](LICENSE).
- **Documentation** (anything under `docs/`, `research/`, README, etc.): [Creative Commons Attribution-ShareAlike 4.0](LICENSE-docs).

Choose this split so the code is maximally reusable (including by future iOS apps that might be commercial), while ensuring the painstakingly-collected documentation always remains open and credited.

## Acknowledgements

- **Sony Engineering** — for shipping outstanding hardware in 2014 and publishing the GPL source bundle that makes this work possible.
- **[danielrweber/HAPxFer](https://github.com/danielrweber/HAPxFer)** — the only third-party HAP project on GitHub before us, and a working reference for the SMB protocol.
- **[frazei](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a)** — for the first public documentation of the JSON-RPC control surface (July 2022).
- **[rytilahti/python-songpal](https://github.com/rytilahti/python-songpal)** — protocol-cousin reference implementation we'll port from.
- **The Japanese audiophile community** (emuzu, briareos, saionjihouse, kakaku.com regulars) — for years of hands-on HDD swap and modification documentation that nobody in the English-speaking world has matched.
- **You**, if you contribute — see [CONTRIBUTING](CONTRIBUTING.md).
