<!-- markdownlint-disable MD001 MD026 MD033 MD041 -->
<div align="center">

<img alt="HAP Revival — keeping the Sony HAP-Z1ES & HAP-S1 alive" src=".github/social-banner.png" width="100%">

# HAP-Revival

### The open software the Sony HAP-Z1ES and HAP-S1 never got — working tools you can use tonight, and the reverse engineering of everything Sony left behind.

Sony shipped a 2014 audiophile masterpiece, then walked away from its software in January 2021: still SMBv1, no Tidal, no Qobuz, no Roon, no AirPlay. The DACs still sing. This repo rebuilds the rest — **starting with the parts that already work**.

[![docs](https://github.com/Guillain-RDCDE/HAP-Revival/actions/workflows/docs-lint.yml/badge.svg)](https://github.com/Guillain-RDCDE/HAP-Revival/actions/workflows/docs-lint.yml)
[![python](https://github.com/Guillain-RDCDE/HAP-Revival/actions/workflows/python-lint.yml/badge.svg)](https://github.com/Guillain-RDCDE/HAP-Revival/actions/workflows/python-lint.yml)
[![release](https://img.shields.io/github/v/release/Guillain-RDCDE/HAP-Revival?color=2ea043&label=HAP%20Sync)](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest)
[![tests](https://img.shields.io/badge/tests-116%20passing-2ea043)](tests)
[![devices](https://img.shields.io/badge/devices-HAP--Z1ES%20·%20HAP--S1-1f6feb)](#-supported-devices)
[![languages](https://img.shields.io/badge/UI-6%20languages-30363d)](tools/i18n.py)
[![license code](https://img.shields.io/badge/code-MIT-green)](LICENSE)
[![license docs](https://img.shields.io/badge/docs-CC--BY--SA%204.0-lightgrey)](LICENSE-docs)

<br>

[![Download HAP Sync](https://img.shields.io/badge/⬇_Download_HAP_Sync-2ea043?style=for-the-badge)](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest) &nbsp;
[![Start here](https://img.shields.io/badge/Start_here_—_no_jargon-1f6feb?style=for-the-badge)](docs/START-HERE.md) &nbsp;
[![The research](https://img.shields.io/badge/The_research-30363d?style=for-the-badge)](docs/00-overview.md)

<img src=".github/hap-sync.png" width="820" alt="HAP Sync: the HAP auto-detected, two PC folders mapped to the internal and external shares, scanning a library before transfer">

<sub>HAP Sync — the HAP found by itself, two folders mapped, a library scanned and ready to transfer.</sub>

</div>

---

## What you can use today

Ten finished tools. **No HAP on hand? Every one of them runs against the built-in mock device.**

| | What it does |
|---|---|
| **🎵 [HAP Sync](tools/hap_gui.py)** — *the one most people want* | Copies your music to the HAP in one click: finds the device by itself, remembers your folders, skips what the HAP can't play. One `.exe`, no install, **and you never enable Windows' insecure SMB1 client**. |
| **⌨️ [HAP Sync CLI](tools/hap_sync.py)** | The same transfer engine, scriptable — for cron jobs, NAS boxes and people who like pipes. |
| **🌐 [Web UI](tools/webui.py)** | A remote in your browser: now-playing, play / pause / seek, sound settings, cover art. One stdlib-only file. |
| **📱 [Control app](docs/13-control-app.md)** | The web UI installed to your phone's home screen — own icon, full-screen, no App Store, no account. |
| **📟 [Python client](tools/hap_client.py)** | Scriptable access to every API method we mapped, from the shell or your own code. |
| **📡 [Discovery](tools/discover.py)** | Finds the HAP on your network over SSDP and dumps its description — no IP to hunt down. |
| **📚 [Library browser](tools/library_browser.py)** | Browses the HAP's on-disk catalogue offline, straight from its SQLite database. |
| **🩺 [Library audit](tools/library_audit.py)** | Health-checks your collection: formats, hi-res mix, duplicates, missing artwork, ghost tracks. |
| **🔧 [SMB Doctor](tools/smb_doctor.py)** | Repairs the exact Windows settings that updates keep breaking, in one click. |
| **🎭 [Mock device](tools/mock_hap.py)** | A fake HAP that answers the real protocol — try everything with no hardware, break nothing. |

Every interface ships in **6 languages** (EN · FR · JA · DE · ES · IT) and switches live.
**Nothing here can damage your device:** reads are pure, playback is bounded, standby confirms first.

---

## Run it in 5 minutes

Grab **HAP Sync** as a single Windows `.exe` from the [**latest release**](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest) — nothing to install.
First launch: SmartScreen → *More info → Run anyway* (not code-signed yet).

Everything else is Python 3.10+ and stdlib-only:

```bash
git clone https://github.com/Guillain-RDCDE/HAP-Revival.git && cd HAP-Revival

python tools/discover.py                        # find your HAP on the LAN (SSDP)
python tools/webui.py <hap-ip>                  # web remote → http://localhost:8080
python tools/hap_client.py <hap-ip> now-playing # …or drive it from the CLI

python tools/webui.py --demo                    # no HAP? run the whole UI off the mock device
```

```powershell
# HAP Sync from source, or build the .exe yourself
pip install pysmb ; python tools/hap_gui.py
powershell -ExecutionPolicy Bypass -File tools/build_gui.ps1
```

New here, or not a programmer? → **[Start Here — the 5-minute friendly guide](docs/START-HERE.md)**.

---

## Why HAP Sync exists

Sony's only supported way to get music onto the machine is an **SMBv1** share that modern Windows and macOS actively fight you over — and when it half-works, it drops files silently.

- **Auto-detects the HAP** on your network, wakes it over Wake-on-LAN if it's asleep.
- **Speaks SMB1 itself** (via `pysmb`), so your OS keeps its defences up.
- **Two folders → both shares** — internal disk and USB, remembered between runs.
- **Skips the junk** (`Thumbs.db`, `.DS_Store`, `.ffs_tmp`, AppleDouble) that becomes ghost tracks, and formats the HAP can't play.
- **Incremental & fast** — only what changed, remote index cached, auto-reindex when done.
- **Survives Sony's ancient Samba** — the 3.0.37 daemon desyncs on modern Direct-TCP SMB1; HAP Sync negotiates over NetBIOS and reconnects per file. *(Files that had been stuck for years now go through.)*

Background on the whole SMB mess: [docs/04-smb.md](docs/04-smb.md) · sync guide: [docs/12-music-sync.md](docs/12-music-sync.md).

---

## Why we're doing this

Put a 24/96 FLAC on a HAP-Z1ES, sit down, and the room changes. There's a stillness around the instruments; cellos have weight, voices have a body, you can hear the space the recording was made in. This is what audiophile source hardware is *supposed* to do — and what most modern streamers, however clever, still don't.

The HAP-Z1ES does it with a chain Sony's "ES" engineers built to last: dual Burr-Brown **PCM1795** DACs, an Analog Devices **ADSP-21488 SHARC** DSP, a custom **FPGA** on the clock domain, an isolated linear PSU, a 14 kg chassis. A decade on, it still measures and sounds outstanding. **What didn't last is the software** — SMBv1 transfers, standard-resolution Spotify on a hi-res deck, nothing added since 2016, a remote app untouched since 2022, a Linux 3.0.35 kernel with OpenWrt-era userland.

The hardware deserves better. This is the open project to give it better.

> *I bought a HAP-Z1ES years ago because it sounded right, and it still does. Watching Sony abandon software this good felt like watching a beautiful instrument get locked in a cupboard. This repo is the lockpick. — Guillain*

---

## The research half

The tools above exist because the machine was taken apart, on paper, first. That research is the other half of this repo — and the most complete public record of these players anywhere.

- ✅ **Network API mapped** — ScalarWebAPI on port 60200, ~30 methods live-validated, [machine-readable spec](api-spec/) included.
- ✅ **Sony's `HDDAudioRemote` Android app decompiled** — the first public decompile of this client.
- ✅ **Internal disk read** — it holds **no OS**, just a SQLite catalogue plus your music. Full schema in hand.
- ✅ **Hardware identified from the metal up** — SoC, DACs, both DSPs, FPGA, PSU, and the Forza kernel driver's ioctl surface.
- ⏳ **Next: the UART console** — i.MX6 UART1, `ttymxc0 @ 115200`, for a root shell and a NAND dump. Firmware 19404R is OTA-only, so the OS has to be pulled off the device, not downloaded.

Everything published so far is **network-passive and read-only — nothing in this repo will brick your device.**

### Roadmap

| Phase | Goal | Device risk |
|---|---|---|
| **1 — Reverse engineering** *(current)* | Decompile, read the disk, read Sony's GPL kernel sources, locate UART | None |
| **2 — Control app** | Modern web / iOS app over the *existing* API, no firmware change | None |
| **3 — Root shell** | UART console → shell → `dd` the NAND as a recovery snapshot | Low (case open) |
| **4 — Custom userland** | Keep Sony's kernel + audio driver, swap the playback daemon for MPD + streaming bridges | Gated behind a tested recovery path |
| **5 — Modern OS** | Mainline where feasible, new control plane, our own API | Opt-in only |

Phases 4–5 are where hi-res streaming (Tidal · Qobuz · Roon · AirPlay 2) and a native iOS app live.
The analog chain (FPGA → SHARC → PCM1795) is the whole point of this hardware. **We preserve it, period** — every phase keeps it untouched.

---

## 🎛 Supported devices

| Device | Role | Notes |
|---|---|---|
| Sony **HAP-Z1ES** | Primary | Pure source player, clean analog out, no internal amp |
| Sony **HAP-S1** | Secondary | Same SoC and stack, adds an integrated amp |

Same i.MX6 SoC, same firmware images, same protocols — work on one transfers to the other.

## 📖 Documentation

Start with **[Start Here](docs/START-HERE.md)** if you're new, or the **[Overview](docs/00-overview.md)** for the project in one page.

<details>
<summary>Full doc index (hardware, API, disk, firmware, UART, audio path…)</summary>

| | | | |
|---|---|---|---|
| [Hardware](docs/01-hardware.md) | [Software stack](docs/02-software-stack.md) | [Network API](docs/03-network-api.md) | [SMB share](docs/04-smb.md) |
| [Diag modes](docs/05-diag-modes.md) | [HDD swap](docs/06-hdd-swap.md) | [Firmware](docs/07-firmware.md) | [Prior art](docs/08-prior-art.md) |
| [Disk layout](docs/09-disk-layout.md) | [UART console](docs/10-uart-console.md) | [Audio path](docs/11-audio-path.md) | [Music sync](docs/12-music-sync.md) |
| [Control app](docs/13-control-app.md) | [NAND extraction](docs/14-nand-extract.md) | [Forza ioctl ref](docs/15-forza-ioctl.md) | |

Active reconnaissance: [`research/`](research/) · Tools: [`tools/`](tools/) · API spec: [`api-spec/`](api-spec/).
</details>

## 🤝 Contributing

Found a Japanese teardown blog from 2015? Captured iOS traffic in Wireshark? Scanned a service manual? You have something to contribute. Run `python tools/discover.py` (read-only — it just probes your LAN and dumps the device description for triage), then read [CONTRIBUTING](.github/CONTRIBUTING.md) and open an issue. We read all of them.

## ⚖️ License & disclaimer

**Code** ([`tools/`](tools/), future daemon): [MIT](LICENSE). · **Docs** (everything else): [CC-BY-SA 4.0](LICENSE-docs). The split keeps code reusable while keeping the painstakingly-collected research open and credited.

The HAP-Z1ES is out of warranty in 2026 regardless. Opening the case, probing UART, or flashing custom firmware *can* damage your device. Everything here is as-is, no warranty — **you are responsible for your own hardware.**

## 🙏 Acknowledgements

[danielrweber/HAPxFer](https://github.com/danielrweber/HAPxFer) (SMB reference) · [frazei's gist](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a) (first public API docs) · [rytilahti/python-songpal](https://github.com/rytilahti/python-songpal) (protocol cousin) · the **Japanese audiophile community** (emuzu, briareos, saionjihouse, the kakaku.com regulars) for a decade of HDD-swap documentation nobody else matched — 本当にありがとうございます · **Sony Engineering** for outstanding 2014 hardware *and* publishing the GPL bundle that makes this possible. · And **you**, if you contribute — especially if you actually *listen* on one of these.
<!-- markdownlint-enable MD001 MD026 MD033 MD041 -->
