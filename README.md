<!-- markdownlint-disable MD033 MD041 -->
<div align="center">

<img src=".github/social-banner.png" width="100%" alt="HAP Revival">

<br><br>

**Open software for the Sony HAP-Z1ES and HAP-S1.**

Sony shipped a 2014 audiophile masterpiece, then stopped writing software for it in January 2021.
The hardware still sings. This is the rest of the story.

<br>

[![Release](https://img.shields.io/github/v/release/Guillain-RDCDE/HAP-Revival?color=2ea043&label=HAP%20Sync&style=flat-square)](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest)
&nbsp;
[![Tests](https://img.shields.io/badge/tests-198%20passing-2ea043?style=flat-square)](tests)
&nbsp;
[![License](https://img.shields.io/badge/code-MIT-blue?style=flat-square)](LICENSE)

[**Download HAP Sync**](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest) &nbsp;·&nbsp;
[Start here](docs/START-HERE.md) &nbsp;·&nbsp;
[Documentation](docs/00-overview.md)

</div>

<br>

---

<br>

## What you can use today

Thirteen finished tools. Stdlib-only Python, no accounts, no telemetry.
All but one run against a built-in mock device, so you can try them with no HAP at all — the
live smoke test is the exception, since checking a real player is the entire point of it.

<br>

### Move music onto the player

- [**HAP Sync**](tools/hap_gui.py) — copies your music to the HAP in one click. Start here.
- [**HAP Sync CLI**](tools/hap_sync.py) — the same transfer engine, scriptable.
- [**SMB Doctor**](tools/smb_doctor.py) — repairs the Windows settings that updates keep breaking.

<br>

### Control the player

- [**Web UI**](tools/webui.py) — now playing, transport, sound settings and cover art, in a browser.
  Updates the instant the music changes, because the player says so.
- [**Control app**](docs/13-control-app.md) — the same UI on your phone's home screen. No App Store.
- [**Python client**](tools/hap_client.py) — every mapped API method, from the shell or your code.
  Internet radio too, on the players where it still works — it reads the state back and tells you
  whether anything actually started, which the player itself will not.
- [**Push notifications**](tools/hap_notify.py) — the player tells you the moment anything changes,
  instead of being asked every five seconds.
- [**Discovery**](tools/discover.py) — finds the HAP on your network. No IP to hunt down.

<br>

### Understand your library

- [**Library browser**](tools/library_browser.py) — reads the player's catalogue offline.
- [**Library audit**](tools/library_audit.py) — formats, hi-res share, duplicates, missing artwork.
- [**Mock device**](tools/mock_hap.py) — a fake HAP that answers the real protocol.
- [**Live smoke test**](tools/smoke_live.py) — checks the client against your own player and
  asserts it reads real values, which the offline suite cannot.
- [**Link checker**](tools/check_links.py) — every relative link and heading anchor in the docs,
  fragments included. Runs in CI.

<br>

Every interface speaks six languages — English, French, Japanese, German, Spanish, Italian — and
switches between them live.

Nothing here can damage your device. Reads are pure, playback is bounded, standby asks first.

<br>

<div align="center">
<img src=".github/hap-sync.png" width="760" alt="HAP Sync, mid-transfer">
</div>

<br>

---

<br>

## Install

**Windows, no Python.** Download [`HapSync.exe`](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest),
put it anywhere, double-click it. On first launch, SmartScreen asks — *More info*, then *Run anyway*.
It isn't code-signed yet.

**Everything else.** Python 3.10 or newer:

```bash
git clone https://github.com/Guillain-RDCDE/HAP-Revival.git
cd HAP-Revival

python tools/discover.py                          # find the HAP on your network
python tools/webui.py <hap-ip>                    # browser remote, on port 8080
python tools/hap_client.py <hap-ip> now-playing   # or the command line

python tools/webui.py --demo                      # no HAP? drive the mock device instead
```

Only HAP Sync needs a dependency — `pip install pysmb`. To build the `.exe` yourself,
run `tools/build_gui.ps1` in a clean virtual environment.

<br>

---

<br>

## Why HAP Sync exists

Sony's only supported way to load music is an SMBv1 share. Modern Windows and macOS fight you over
it, and when it half-works it drops files without saying so.

HAP Sync speaks the protocol itself, so your operating system keeps its defences up. It finds the
player, wakes it if it's asleep, maps two folders to the internal disk and the USB share, remembers
them, and transfers only what changed. It skips the junk that becomes ghost tracks — `Thumbs.db`,
`.DS_Store`, AppleDouble — along with formats the HAP can't play.

It also works around the player's own Samba 3.0.37, which desynchronises SMB1 framing over modern
Direct TCP after a file or two. HAP Sync negotiates over NetBIOS and opens a fresh session per file.
Libraries that had been stuck for years now transfer cleanly.

<br>

---

<br>

## Why the project exists

Put a 24/96 FLAC on a HAP-Z1ES, sit down, and the room changes. There is a stillness around the
instruments. Cellos have weight, voices have a body, and you can hear the space the recording was
made in.

Sony's ES engineers built that with dual Burr-Brown PCM1795 DACs, an Analog Devices SHARC DSP, a
custom FPGA on the clock domain, an isolated linear supply and a fourteen-kilo chassis. A decade
later it still measures and sounds superb.

The software is what rotted. SMBv1 transfers. Standard-resolution Spotify on a hi-res deck. No
Tidal, no Qobuz, no Roon, no AirPlay 2. Nothing added since 2016, a remote app untouched since 2022,
and a Linux 3.0.35 kernel underneath it all.

The hardware deserves better. This is the open project to give it better.

<br>

---

<br>

## Where the research stands

The tools exist because the machine was taken apart on paper first. Nothing published so far has
opened a case or touched firmware; the writes we do make are the ordinary ones a remote control
makes — transport, sound settings, playback.

- The network API is mapped — ScalarWebAPI on port 60200, around thirty methods validated live,
  with a [machine-readable spec](api-spec/). A second, REST API sits on the same port, and the
  player pushes state changes over UDP rather than needing to be polled —
  [both found in the Crestron module](research/notes/2026-08-20-crestron-module-teardown.md).
- Sony's `HDDAudioRemote` Android app is decompiled — the first public decompile of this client.
- The internal disk is read. It holds no operating system: a SQLite catalogue and your music, and
  the full schema is in hand.
- The hardware is identified from the metal up, including both DSPs and the kernel driver's
  ioctl surface.
- Internet radio is understood: Sony's TuneIn integration needs a per-device registration, and the
  pairing endpoint still answers in 2026. The client can read that state and refuse to act without
  it.
- Sony's update host is still alive and turns out to be a plain file server, so the firmware image
  may be downloadable rather than needing a NAND dump — [`docs/07-firmware.md`](docs/07-firmware.md).
  Next is capturing one update check to learn the path, then the UART console — i.MX6 UART1 at
  115200 baud — for a root shell.

The roadmap runs in five phases: reverse engineering, then a modern control app over the existing
API, then a root shell, then a custom userland keeping Sony's kernel and audio driver, and finally
a modern OS. Risk to the device stays at none until phase three, and the custom userland waits
behind a tested recovery path.

The analog chain — FPGA to SHARC to PCM1795 — is the entire point of this hardware. Every phase
leaves it untouched.

<br>

---

<br>

## Devices

**HAP-Z1ES.** The primary target. A pure source player with clean analog out and no internal amp.

**HAP-S1.** The smaller sibling, with an integrated amp. Same SoC, same firmware images, same
protocols — work on one transfers to the other.

<br>

## Documentation

Start with [Start Here](docs/START-HERE.md) if you're new, or the [Overview](docs/00-overview.md)
for the project in one page. **Own a HAP?** [Help in five minutes](docs/HELP-IN-5-MINUTES.md) —
read-only, copy-paste, no Python needed.

<details>
<summary>Full index — hardware, API, disk, firmware, UART, audio path</summary>

<br>

| | | | |
|---|---|---|---|
| [Hardware](docs/01-hardware.md) | [Software stack](docs/02-software-stack.md) | [Network API](docs/03-network-api.md) | [SMB share](docs/04-smb.md) |
| [Diag modes](docs/05-diag-modes.md) | [HDD swap](docs/06-hdd-swap.md) | [Firmware](docs/07-firmware.md) | [Prior art](docs/08-prior-art.md) |
| [Disk layout](docs/09-disk-layout.md) | [UART console](docs/10-uart-console.md) | [Audio path](docs/11-audio-path.md) | [Music sync](docs/12-music-sync.md) |
| [Control app](docs/13-control-app.md) | [NAND extraction](docs/14-nand-extract.md) | [Forza ioctl](docs/15-forza-ioctl.md) | [**Gotchas**](docs/16-gotchas.md) |

Reconnaissance notes live in [`research/`](research/), the tools in [`tools/`](tools/), the API
specification in [`api-spec/`](api-spec/).

</details>

<br>

## Contributing

A Japanese teardown blog from 2015, iOS traffic captured in Wireshark, a scanned service manual —
all of it counts. Run `python tools/discover.py`, read [CONTRIBUTING](.github/CONTRIBUTING.md), and
open an issue. We read all of them.

<br>

## License

Code is [MIT](LICENSE). Documentation is [CC-BY-SA 4.0](LICENSE-docs). The split keeps the code
reusable and the research open and credited.

Opening the case, probing UART or flashing custom firmware can damage your device. Everything here
is provided as-is, without warranty. You are responsible for your own hardware.

<br>

## Acknowledgements

**Amos**, for tracking down the Crestron module and handing over the protocol —
[two of our conclusions were wrong](research/notes/2026-08-20-crestron-module-teardown.md) until he did ·
**Saschko**, for the browser remote that still plays TuneIn stations, and for finding the header
that breaks it before we could tell him ·
[danielrweber/HAPxFer](https://github.com/danielrweber/HAPxFer) for the SMB reference ·
[frazei's gist](https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a) for the first
public API notes · [rytilahti/python-songpal](https://github.com/rytilahti/python-songpal) for the
protocol cousin · the Japanese audiophile community — emuzu, briareos, saionjihouse and the
kakaku.com regulars — for a decade of documentation nobody else matched · Sony Engineering, for
hardware this good and for publishing the GPL bundle that makes the rest possible.

<br>
<!-- markdownlint-enable MD033 MD041 -->
