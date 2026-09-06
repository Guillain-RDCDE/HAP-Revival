# Overview

**HAP-Revival** is a community reverse-engineering and modernization project for the Sony HAP-Z1ES and HAP-S1 HDD audiophile players, abandoned by Sony in January 2021.

## In one paragraph

Sony shipped two excellent audiophile-grade source players in 2014 (HAP-Z1ES) and 2014–2015 (HAP-S1), built around a custom FPGA, an Analog Devices SHARC DSP, and dual PCM1795 DACs. The hardware still measures and sounds outstanding a decade later. The software, frozen at firmware 19404R, does not: SMBv1 file transfer, no Tidal, no Qobuz, no Roon, standard-resolution Spotify on a hi-res chassis, a remote app that hasn't seen meaningful updates since 2022. **HAP-Revival** documents the device from the metal up, rebuilds the missing software in the open, and produces a modern control app worthy of the analog chain Sony built.

## Project structure

| Path | What it contains |
|---|---|
| `README.md` | Project introduction and roadmap |
| `docs/` | Reference documentation — start here |
| `research/` | Active reconnaissance work, captures, lab notes |
| `tools/` | Working scripts (discovery, fuzzer, recipes) |
| `api-spec/` | Living machine-readable API specification |
| `.github/` | Issue templates and CI |

## What we know so far

| Domain | Status | See |
|---|---|---|
| Hardware identification | SoC, DAC, ethernet PHY confirmed. **DSPs now identified** (ADSP-21488 SHARC + Cirrus CS48L10, from the Forza driver source). FPGA documented from service manual (Altera EP4CGX30) but not photo-verified | [`01-hardware.md`](01-hardware.md) |
| OS and userland | OpenWrt + Linux 3.0.35 + Python 2.7 daemon, all confirmed via GPL release. OS lives on internal flash, **not** the HDD | [`02-software-stack.md`](02-software-stack.md) |
| Network API | Port 60100 (UPnP) + 60200 (JSON-RPC); ~30 methods live-validated, full catalog at [`research/api-method-catalog.md`](../research/api-method-catalog.md) | [`03-network-api.md`](03-network-api.md) |
| File transfer | SMB1 / NT1, share `HAP_Internal`, auto library rescan | [`04-smb.md`](04-smb.md) |
| Diagnostic modes | DIAG (4-key combo) + Special Mode — **five entries**, photographed 2026-08-22, including a firmware downgrade | [`05-diag-modes.md`](05-diag-modes.md) |
| HDD/SSD swap | Validated SSD list, sector-clone recipe, 2TB internal cap | [`06-hdd-swap.md`](06-hdd-swap.md) |
| Firmware blob | 19404R — no public copy, but Sony's update host is alive and is a **plain Akamai file server over HTTP**, so the image may be downloadable once we learn the path. `0018120R` newly identified from a real unit's downgrade dialog | [`07-firmware.md`](07-firmware.md) |
| Prior art | Exhaustive bibliography, three GitHub repos total | [`08-prior-art.md`](08-prior-art.md) |
| On-disk layout | Disk read directly 2026-06-02: two ext4 partitions (`/data` SQLite catalog + `/mnt/internal` music); ground-truth DB schema; no rootfs on disk | [`09-disk-layout.md`](09-disk-layout.md) |
| OS acquisition | Live-device software vectors (Samba symlink, HTTP traversal) blocked. Capturing one Network Update check to learn the CDN path is now the cheapest lead; **UART serial console** remains the way to the *running* system and the proprietary userland | [`10-uart-console.md`](10-uart-console.md), [`research/notes/2026-06-03-os-acquisition-recon.md`](../research/notes/2026-06-03-os-acquisition-recon.md) |
| Audio path | Decoded from the GPL Forza driver: Altera FPGA over PCIe → CS48L10 (oversampling) + ADSP-21488 SHARC (DSEE-HX "HEQ") + DSD remastering → 2× PCM1795; controlled via `/dev/forza` ioctls | [`11-audio-path.md`](11-audio-path.md) |
| Music sync | `hap_sync.py` — HAP-dedicated FreeFileSync replacement: two-folder→two-share, junk/format filtering, SMB1 via pysmb (no Windows SMB1), remote-index cache | [`12-music-sync.md`](12-music-sync.md) |
| Control app | `webui.py` is an installable **PWA** — add to the iPhone/iPad home screen, standalone full-screen, no App Store. The bridge to the future native app | [`13-control-app.md`](13-control-app.md) |
| Rootfs extraction | **Tested** off-device pipeline: NAND dump → `jefferson` (userspace, no MTD kernel modules — WSL2 lacks them) → browsable rootfs, via `tools/extract_rootfs.sh` | [`14-nand-extract.md`](14-nand-extract.md) |
| Forza control interface | The decoded `/dev/forza` ioctl contract (magic 0xDF; API/DSP/DAC command sets; field semantics traced arm-by-arm) — the Phase-4 lever for the DSP/DAC chain. DSP is model-selected: SHARC on the Z1ES (Spiritoso), CS48L10 on Allegro | [`15-forza-ioctl.md`](15-forza-ioctl.md) |

## What we don't know yet

- The full ScalarWebAPI method dictionary on port 60200 (Sony disabled `getMethodTypes` introspection).
- Whether the device rescans `/mnt/internal/storage/` on a cold disk mount (not just on SMB drop) — the open question gating a direct-to-disk bulk transfer tool. See [`09-disk-layout.md`](09-disk-layout.md).
- The physical UART test-point location on the board and the live U-Boot boot-log behaviour. (The SoC-side console pinout is now **known** — i.MX6 UART1, balls M1/M3, `ttymxc0 @ 115200`; see [`01-hardware.md`](01-hardware.md) / [`10-uart-console.md`](10-uart-console.md).)
- The FPGA bitstream programming model (we have the `forza_snd_driver` source, but the FPGA logic itself is closed).
- The exact protocol used by the official **iOS** app for real-time updates. The **Android** equivalent has been confirmed (APK decompile, 2026-05-25) to use plain HTTP polling at 5 s cadence — four background threads polling four endpoints, no WebSocket. Note this is a choice Sony's app makes, not a limit of the device: the HAP does have a UDP push mechanism, found in the Crestron module and verified live on 2026-08-20 ([`03-network-api.md`](03-network-api.md#real-time-updates--push-notifications-over-udp)). Our own clients use it. The iOS app likely polls like the Android one, pending Wireshark capture.

Filling these gaps is the work of Phase 1 — see [`README.md`](REFERENCE.md#what-has-been-established).

## Audience

This documentation is written for:

- **HAP-Z1ES / HAP-S1 owners** who want to understand what's inside their machine.
- **Contributors** to this project who need to come up to speed quickly.
- **Future maintainers** in 2028, 2030, 2035 — the project may outlive any individual involvement, and that's the point.

It is **not** written for:

- Non-technical end-users looking for a one-click installer (we're not there yet).
- People deciding whether to *buy* a HAP-Z1ES in 2026 (read the AudioCircle and Audiogon threads for that).
