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
| Hardware identification | SoC, DAC, DSP, ethernet PHY confirmed. FPGA documented from service manual (Altera EP4CGX30) but not photo-verified | [`01-hardware.md`](01-hardware.md) |
| OS and userland | OpenWrt + Linux 3.0.35 + Python 2.7 daemon, all confirmed via GPL release | [`02-software-stack.md`](02-software-stack.md) |
| Network API | Port 60100 (UPnP) + 60200 (JSON-RPC); ~30 methods live-validated, full catalog at [`research/api-method-catalog.md`](../research/api-method-catalog.md) | [`03-network-api.md`](03-network-api.md) |
| File transfer | SMB1 / NT1, share `HAP_Internal`, auto library rescan | [`04-smb.md`](04-smb.md) |
| Diagnostic modes | DIAG (4-key combo) + Special Mode (SMB version selector) | [`05-diag-modes.md`](05-diag-modes.md) |
| HDD/SSD swap | Validated SSD list, sector-clone recipe, 2TB internal cap | [`06-hdd-swap.md`](06-hdd-swap.md) |
| Firmware blob | 19404R, 74 MB, format never publicly analyzed | [`07-firmware.md`](07-firmware.md) |
| Prior art | Exhaustive bibliography, three GitHub repos total | [`08-prior-art.md`](08-prior-art.md) |

## What we don't know yet

- The full ScalarWebAPI method dictionary on port 60200 (Sony disabled `getMethodTypes` introspection).
- The on-device UART pinout and U-Boot console behavior (no community probe published).
- The firmware container format (no public binwalk output).
- The FPGA bitstream programming model (we have the `forza_snd_driver` source, but the FPGA logic itself is closed).
- The exact protocol used by the official **iOS** app for real-time updates. The **Android** equivalent has been confirmed (APK decompile, 2026-05-25) to use plain HTTP polling at 5 s cadence — no WebSocket, no push, four background threads polling four endpoints. The iOS app likely behaves identically, pending Wireshark capture.

Filling these gaps is the work of Phase 1 — see [`README.md`](../README.md#roadmap).

## Audience

This documentation is written for:

- **HAP-Z1ES / HAP-S1 owners** who want to understand what's inside their machine.
- **Contributors** to this project who need to come up to speed quickly.
- **Future maintainers** in 2028, 2030, 2035 — the project may outlive any individual involvement, and that's the point.

It is **not** written for:

- Non-technical end-users looking for a one-click installer (we're not there yet).
- People deciding whether to *buy* a HAP-Z1ES in 2026 (read the AudioCircle and Audiogon threads for that).
