# Hardware

What's actually inside the Sony HAP-Z1ES / HAP-S1 chassis.

## Main application SoC

**NXP / Freescale i.MX6 Dual @ 1 GHz** — dual ARM Cortex-A9 with NEON.

- Part number on the board: `IC101 = MCIMX6D5EYM10AC` (per Sony service manual, schematic legend).
- This is the chip that runs the Linux 3.0.35 kernel, the lighttpd HTTP server, the Python control daemon, and the Samba file server.
- The Freescale i.MX6 family was the standard high-end embedded ARM platform circa 2013–2015 — common in industrial control, in-vehicle infotainment, and high-end set-top boxes.

There is a **secondary housekeeping microcontroller** on the U-COM board:

- `IC7002 = MB9AF156NPMC-G-JNE2` (Cypress / Spansion / Fujitsu, ARM Cortex-M3).
- Drives the front panel buttons, the IR receiver, the rotary encoder, the standby power management.
- Does **not** run Linux. Communicates with the i.MX6 over an internal serial link.

## Audio pipeline

This is the part Sony invested in. The Linux SoC does not touch the audio sample stream after it leaves I²S — everything from there is dedicated silicon.

```text
                                        I²S
   ┌───────────────┐    audio data     ┌───────────────────┐
   │  i.MX6 (Linux │ ──────────────────▶│  Sony FPGA        │
   │  + GStreamer  │                   │  (closed bitstream│
   │  + forza_snd) │                   │   — IC001)        │
   └───────────────┘                   └────────┬──────────┘
                                                │
                                                ▼
                                     ┌────────────────────┐
                                     │  Analog Devices    │
                                     │  SHARC DSP (IC601) │
                                     └────────┬───────────┘
                                              │
                                              ▼
                            ┌─────────────────┴─────────────────┐
                            │                                   │
                            ▼                                   ▼
                ┌────────────────────┐              ┌────────────────────┐
                │  PCM1795 (L mono)  │              │  PCM1795 (R mono)  │
                │  (Burr-Brown / TI) │              │  (Burr-Brown / TI) │
                └─────────┬──────────┘              └─────────┬──────────┘
                          │                                   │
                          ▼                                   ▼
                  ┌──────────────┐                    ┌──────────────┐
                  │ Analog L out │                    │ Analog R out │
                  └──────────────┘                    └──────────────┘
```

- **FPGA**: vendor referenced in service manual as Altera EP4CGX30 (Cyclone IV GX with embedded transceivers — used for the high-speed I²S/serial bus to the SHARC + DAC). Not yet confirmed from a chip photo by the community.
- **DSP**: **two** DSPs, confirmed 2026-06-02 from the GPL `forza_snd_driver` source file names:
  - **Analog Devices ADSP-21488** SHARC (`adsp_21488.c`) — the main audio DSP (DSEE-HX / DSD remastering likely run here).
  - **Cirrus Logic CS48L10** (`cdsp_cs48l10.c`) — a second/"cdsp" audio DSP.
- **DACs**: 2× Burr-Brown / TI **PCM1795** in mono mode — one per channel. The PCM1795 is a stereo DAC; running it in mono is a luxury that improves channel separation and pushes the noise floor down.

## Ethernet

- PHY: **Atheros AR8035** (10/100/1000 Mbps).
- Two MAC addresses on the device: one for Ethernet, one for Wi-Fi. The UPnP UUID is derived from the Wi-Fi MAC.

## Storage

- **Internal**: 1 TB 2.5" SATA HDD (factory). Holds **only data** — the music library (`/mnt/internal`) and the SQLite metadata catalog (`/data`). **Not the rootfs** (confirmed by direct disk read 2026-06-02; see [`09-disk-layout.md`](09-disk-layout.md)).
- **Maximum supported internal**: 2 TB (MBR limit on Sony's firmware).
- **External**: USB drives up to 4 TB — our reference HAP-Z1ES on firmware 19404R plays from `storage:usb1` daily, confirmed working.
- **The OS lives on on-board flash, not the HDD.** U-Boot (+ kernel) on an **SoC-side SPI-NOR** chip; the **kernel + rootfs** on an on-board **NAND or eMMC** (the 77.8 MB firmware cannot fit a small SPI-NOR — so a larger flash part must exist; not yet pinned down in the IC list). This is why HDD swaps don't brick the bootloader, and why factory-reset works regardless of disk state. See [`06-hdd-swap.md`](06-hdd-swap.md).

## Front panel

- Color LCD driven by **DirectFB 1.4.17** (no X11, no Wayland, direct framebuffer).
- Rotary encoder + 6 hardware buttons (POWER, HOME, BACK, OPTIONS, MENU/PLAY, and the encoder click) handled by the U-COM Cortex-M3.
- IR receiver for the supplied RM-ANU183 remote.

## Power

- Linear power supply with separate transformers for the analog and digital sections (HAP-Z1ES — true dual mono).
- HAP-S1 adds an integrated amplifier: **2× LM3876** chipamps + **NJW1194** electronic volume.
- HAP-S1 headphone amp is reportedly **a 400 Ω resistor on the speaker output** — confirmed by Amir Majidimehr (Audio Science Review, [HAP-S1 measurements thread](https://www.audiosciencereview.com/forum/index.php?threads/sony-hap-s1-review-network-amp.6921/), Feb 2019). One of the few cost-cutting decisions visible in the product.

## Debug interfaces

Per the HAP-S1 service manual ([`archive/sony-service-manual-hap-s1.pdf`](../archive/sony-service-manual-hap-s1.pdf), same architecture as HAP-Z1ES):

- **JTAG**: TDO, TMS, TDI, TCK pins on IC101 — present in the IC101 pin table but marked "Not used".
- **UART console**: **identified 2026-06-03 from the IC101 pin-function table** (service manual p75–79). The Linux/U-Boot console is the i.MX6 **UART1** (`ttymxc0 @ 115200 8N1`):
  - **ball M1 = `CSI0_DAT10` = console TX** ("Transmit data output terminal")
  - **ball M3 = `CSI0_DAT11` = console RX** ("Receive data input terminal")
  - (Separately, `CSI0_DAT12/13` is the UART to the U-COM Cortex-M3, and `CSI0_DAT14/15` to the remote-commander learning block — *not* the console.)
  - Boot-mode straps are hardwired for NAND boot (`EIM_A18/20/21/23`, `EIM_RW`, `EIM_EB1`, `EIM_DA3/5/6/7`). Full procedure: [`10-uart-console.md`](10-uart-console.md).
- **SYS/MPU PROG**: programming header for the U-COM Cortex-M3 (housekeeping MCU, not the application SoC).
- **SYS/JIG**: factory test jig connector.

**Still unprobed on real hardware:** the physical test-point location on the MAIN PWB (p40) and the actual boot-log/U-Boot behaviour. The SoC-side console pins are now known (above); the remaining work is tracing `CSI0_DAT10/11` to their board test points and doing the live probe — the highest-leverage hardware step remaining.

## Service manual references

All four primary technical documents are **preserved in [`archive/`](../archive/)** for durability:

- [`archive/sony-service-manual-hap-z1es.pdf`](../archive/sony-service-manual-hap-z1es.pdf) — 8.3 MB, full schematics, IC list (incl. the `IC101 = MCIMX6D5EYM10AC` part number we keep citing), PCB layout, audio path block diagram, DIAG sequence. Originally sourced from Elektrotanya 2026-05-26.
- [`archive/sony-service-manual-hap-s1.pdf`](../archive/sony-service-manual-hap-s1.pdf) — 10.4 MB, same scope plus the integrated amplifier section (LM3876, NJW1194). Most board-level content overlaps with the HAP-Z1ES manual.
- [`archive/sony-helpguide-hap-z1es.pdf`](../archive/sony-helpguide-hap-z1es.pdf) — 1.3 MB, end-user Help Guide. Live source: <https://helpguide.sony.net/ha/hapz1es/v1/en/print.pdf>.
- [`archive/sony-helpguide-hap-s1.pdf`](../archive/sony-helpguide-hap-s1.pdf) — 1.4 MB, end-user Help Guide. Live source: <https://helpguide.sony.net/ha/haps1/v1/en/print.pdf>.

Live mirrors for the service manuals (in case you want to grab a fresh copy from upstream): [ManualsLib HAP-Z1ES](https://www.manualslib.com/manual/1606461/Sony-Hap-Z1es.html), [ManualsLib HAP-S1](https://www.manualslib.com/manual/893329/Sony-Hap-S1.html), [Elektrotanya HAP-Z1ES](https://elektrotanya.com/sony_hap-z1es.pdf/download.html), [Elektrotanya HAP-S1](https://elektrotanya.com/sony_hap-s1_ver.1.0_hdd_audio_player.pdf/download.html). Both anti-bot, manual browser download only.

Relevant pages:

- Block diagram: early pages of each manual.
- Board IDs and IC list: schematic section.
- Disassembly: dedicated section.
- DIAG mode entry: page 25 of the HAP-S1 manual (see [`05-diag-modes.md`](05-diag-modes.md) for the verified sequence).
