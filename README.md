<!-- markdownlint-disable MD033 MD041 -->
<p align="center">
  <img alt="HAP Revival — keeping the Sony HAP-Z1ES & HAP-S1 alive" src=".github/social-banner.png" width="100%">
</p>

# 🎵 HAP-Revival

[![status](https://img.shields.io/badge/status-pre--alpha-orange)](#-where-we-are)
[![devices](https://img.shields.io/badge/devices-HAP--Z1ES%20%7C%20HAP--S1-blue)](#-supported-devices)
[![license code](https://img.shields.io/badge/code-MIT-green)](LICENSE)
[![license docs](https://img.shields.io/badge/docs-CC--BY--SA%204.0-lightgrey)](LICENSE-docs)

**Keeping the Sony HAP-Z1ES and HAP-S1 alive — for the music, not the plumbing.**

Sony shipped its last firmware in January 2021 and walked away. The hardware still sounds
superb; the software rotted. HAP-Revival is rebuilding the parts Sony abandoned — one piece
you can actually use today — and reverse-engineering the rest toward a modern, open OS.

> 🟢 **New here, or not a programmer?** → **[Start Here — the 5-minute friendly guide](docs/START-HERE.md)**
> What this machine is, what you can do *today*, and how deep you want to go. No jargon. The rest of this page is the technical side.

---

## ⬇️ What you can use today

| Tool | What it does | Platform |
|---|---|---|
| **🎵 HAP Sync** | Copy music to the HAP in one click — auto-finds the device, remembers your folders, skips what the HAP can't play | Windows — [**download `.exe`**](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest/download/HapSync.exe) |
| **🌐 Web UI** | Browser remote: now-playing, play / pause / seek, sound settings, cover art | Any browser |
| **📱 Control app** | The web UI installed to your phone's home screen — own icon, full-screen, no App Store | iOS · iPadOS · Android — [guide](docs/13-control-app.md) |
| **📚 Library browser & audit** | Browse and health-check the on-disk catalog offline (formats, hi-res mix, duplicates, missing art) | Any OS |
| **📟 Python client / CLI** | Scriptable control of every mapped API method, stdlib-only | Any OS |

Every interface ships in **6 languages** (EN · FR · JA · DE · ES · IT) and switches live.
*Planned:* custom firmware with hi-res streaming (Tidal · Qobuz · Roon · AirPlay) and a native iOS app — see the [roadmap](#-roadmap).

### 🎵 HAP Sync — getting music onto the HAP, finally painless

![HAP Sync: the HAP auto-detected, two PC folders mapped to the internal and external shares, scanning a library before transfer](.github/hap-sync.png)

Sony's only supported transfer path is an **SMBv1** share that modern Windows and macOS fight
you over. HAP Sync does it properly — one self-contained `.exe`, no install:

- **Auto-detects the HAP** on your network — no IP to hunt down.
- **Speaks SMB1 directly** (via `pysmb`) — you never enable Windows' insecure SMB1 client.
- **Two folders → both shares** (internal disk + USB), folders remembered between runs.
- **Skips the junk** (`Thumbs.db`, `.DS_Store`, `.ffs_tmp`, AppleDouble) that becomes ghost tracks, and formats the HAP can't play.
- **Incremental & fast** — only changed files, remote index cached, WoL to wake a sleeping HAP, auto-reindex after.
- **Fix Windows access** button repairs the exact settings Windows updates keep breaking, in one click.

```powershell
# Run from source (Python 3.10+)         |  # …or build the standalone .exe (no Python to run it)
pip install pysmb                        |  powershell -ExecutionPolicy Bypass -File tools/build_gui.ps1
python tools/hap_gui.py                  |
```

Prefer scripting it? The same engine ships as a CLI — see [`tools/hap_sync.py`](tools/hap_sync.py) and the [music-sync guide](docs/12-music-sync.md). · First `.exe` launch: SmartScreen → *More info → Run anyway* (not code-signed yet). Background on the SMB mess: [docs/04-smb.md](docs/04-smb.md).

---

## ▶️ Try it in 5 minutes — zero risk

You need a HAP-Z1ES or HAP-S1 on your LAN and Python 3.10+. **No HAP? Use the built-in mock device.**

```bash
git clone https://github.com/Guillain-RDCDE/HAP-Revival.git && cd HAP-Revival

python tools/discover.py                 # find your HAP automatically (SSDP)
python tools/webui.py <hap-ip>           # web UI → http://localhost:8080
python tools/hap_client.py <hap-ip> now-playing   # or the CLI

python tools/webui.py --demo             # no hardware: drive the web UI off a fake HAP
```

**Nothing in this UI can damage the device.** Reads are pure, playback is bounded, standby
confirms before sending. The whole client is one stdlib-only file — readable in an afternoon.

---

## 🎼 Why we're doing this

Put a 24/96 FLAC on a HAP-Z1ES, sit down, and the room changes. There's a stillness around the
instruments; cellos have weight, voices have a body, you can hear the space the recording was
made in. This is what audiophile source hardware is *supposed* to do — and what €500 streamers
still don't.

The HAP-Z1ES (2014, ~€2000) does it with a chain Sony's "ES" engineers built to last: dual
Burr-Brown **PCM1795** DACs, an Analog Devices **ADSP-21488 SHARC** DSP, a custom Sony **FPGA**
on the clock domain, an isolated linear PSU, a 14 kg chassis. A decade on, it still measures and
sounds outstanding. **What didn't last is the software:**

- still **SMBv1** for transfers (broken on modern macOS, off by default on Windows),
- Spotify **only in standard resolution** — on a deck designed for hi-res,
- **no Tidal, Qobuz, Roon, or AirPlay 2** — nothing added since 2016,
- an iOS remote untouched since 2022 that may vanish from the App Store any day,
- a **Linux 3.0.35** kernel with OpenWrt-era userland.

The hardware deserves better. This is the open project to give it better.

> *I bought a HAP-Z1ES years ago because it sounded right, and it still does. Watching Sony
> abandon software this good felt like watching a beautiful instrument get locked in a cupboard.
> This repo is the lockpick. — Guillain*

---

## 📍 Where we are

**Pre-alpha — research & reverse-engineering, and unapologetically a music project pretending to be a software project.** Everything in this repo is network-passive and read-only; **nothing here will brick your device.**

- ✅ Mapped the network API (ScalarWebAPI on port 60200) and live-validated ~30 methods.
- ✅ Decompiled Sony's `HDDAudioRemote` Android app — the first public decompile of this client.
- ✅ Read the internal disk: it holds **no OS** — just a SQLite catalog + your music. Full schema in hand.
- ✅ Shipped the usable tools above (Web UI, CLI, HAP Sync, library browser/audit, demo mode).
- ⏳ Heading for the **UART console** (i.MX6 UART1, `ttymxc0 @ 115200`) for a root shell + NAND dump — firmware 19404R is OTA-only, so the OS must be dumped from the device, not downloaded.

### 🗺️ Roadmap

| Phase | Goal | Device risk |
|---|---|---|
| **1 — Reverse engineering** *(current)* | Decompile, read the disk, read Sony's GPL kernel sources, locate UART | None |
| **2 — Control app** | Modern web / iOS app over the *existing* API, no firmware change | None |
| **3 — Root shell** | UART console → shell → `dd` the NAND as a recovery snapshot | Low (case open) |
| **4 — Custom userland** | Keep Sony's kernel + audio driver, swap the playback daemon for MPD + streaming bridges | Gated behind a tested recovery path |
| **5 — Modern OS** | Mainline where feasible, new control plane, our own API | Opt-in only |

The analog chain (FPGA → SHARC → PCM1795) is the whole point of this hardware. **We preserve it, period** — every phase keeps it untouched.

---

## 🎛️ Supported devices

| Device | Role | Notes |
|---|---|---|
| Sony **HAP-Z1ES** | Primary | Pure source player, clean analog out, no internal amp |
| Sony **HAP-S1** | Secondary | Same SoC and stack, adds an integrated amp |

Same i.MX6 SoC, same firmware images, same protocols — work on one transfers to the other.

---

## 📖 Documentation

The full research lives in [`docs/`](docs/). Start with **[Overview](docs/00-overview.md)** for the project in one page, or [**Start Here**](docs/START-HERE.md) if you're new.

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

---

## 🤝 Contributing

Found a Japanese teardown blog from 2015? Captured iOS traffic in Wireshark? Scanned a service
manual? You have something to contribute. Run `python tools/discover.py` (read-only — it just
probes your LAN and dumps the device description for triage), then read
[CONTRIBUTING](.github/CONTRIBUTING.md) and open an issue. We read all of them.

## ⚖️ License & disclaimer

**Code** ([`tools/`](tools/), future daemon): [MIT](LICENSE). · **Docs** (everything else): [CC-BY-SA 4.0](LICENSE-docs). The split keeps code reusable while keeping the painstakingly-collected research open and credited.

The HAP-Z1ES is out of warranty in 2026 regardless. Opening the case, probing UART, or flashing custom firmware *can* damage your device. Everything here is as-is, no warranty — **you are responsible for your own hardware.**

## 🙏 Acknowledgements

[danielrweber/HAPxFer](https://github.com/danielrweber/HAPxFer) (SMB reference) · [frazei's gist](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a) (first public API docs) · [rytilahti/python-songpal](https://github.com/rytilahti/python-songpal) (protocol cousin) · the **Japanese audiophile community** (emuzu, briareos, saionjihouse, the kakaku.com regulars) for a decade of HDD-swap documentation nobody else matched — 本当にありがとうございます · **Sony Engineering** for outstanding 2014 hardware *and* publishing the GPL bundle that makes this possible. · And **you**, if you contribute — especially if you actually *listen* on one of these.
<!-- markdownlint-enable MD033 MD041 -->
