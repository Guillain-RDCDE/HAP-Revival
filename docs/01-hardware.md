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
- **DSP**: Analog Devices SHARC family. Specific part not yet published.
- **DACs**: 2× Burr-Brown / TI **PCM1795** in mono mode — one per channel. The PCM1795 is a stereo DAC; running it in mono is a luxury that improves channel separation and pushes the noise floor down.

## Ethernet

- PHY: **Atheros AR8035** (10/100/1000 Mbps).
- Two MAC addresses on the device: one for Ethernet, one for Wi-Fi. The UPnP UUID is derived from the Wi-Fi MAC.

## Storage

- **Internal**: 1 TB 2.5" SATA HDD (factory). Holds the rootfs + the music library + the Tokyo Cabinet metadata DB.
- **Maximum supported internal**: 2 TB (MBR limit on Sony's firmware).
- **External**: USB drives up to 4 TB — our reference HAP-Z1ES on firmware 19404R plays from `storage:usb1` daily, confirmed working.
- **U-Boot and kernel** live on an **SoC-side SPI flash** chip, **not on the HDD**. This is why HDD swaps don't brick the bootloader, and why factory-reset always works regardless of disk state. See [`06-hdd-swap.md`](06-hdd-swap.md).

## Front panel

- Color LCD driven by **DirectFB 1.4.17** (no X11, no Wayland, direct framebuffer).
- Rotary encoder + 6 hardware buttons (POWER, HOME, BACK, OPTIONS, MENU/PLAY, and the encoder click) handled by the U-COM Cortex-M3.
- IR receiver for the supplied RM-ANU183 remote.

## Power

- Linear power supply with separate transformers for the analog and digital sections (HAP-Z1ES — true dual mono).
- HAP-S1 adds an integrated amplifier: **2× LM3876** chipamps + **NJW1194** electronic volume.
- HAP-S1 headphone amp is reportedly **a 400 Ω resistor on the speaker output** — confirmed by Amir Majidimehr (Audio Science Review, [HAP-S1 measurements thread](https://www.audiosciencereview.com/forum/index.php?threads/sony-hap-s1-review-network-amp.6921/), Feb 2019). One of the few cost-cutting decisions visible in the product.

## Debug interfaces

Per the HAP-S1 service manual (same architecture as HAP-Z1ES) — see [`archive/`](../archive/) for the canonical preserved copy if one has been added there, or [Elektrotanya](https://elektrotanya.com/sony_hap-s1_ver.1.0_hdd_audio_player.pdf/download.html) / [ManualsLib](https://www.manualslib.com/manual/893329/Sony-Hap-S1.html) as live mirrors:

- **JTAG**: TDO, TMS, TDI test points on the main board.
- **UART**: documented as "boot mode settings terminals on the main board" — pinout in the manual; baud rate not specified but i.MX6 default is `ttymxc0 @ 115200 8N1`.
- **SYS/MPU PROG**: programming header for the U-COM Cortex-M3 (housekeeping MCU, not the application SoC).
- **SYS/JIG**: factory test jig connector.

**Nobody has published an actual UART probe** on either device. The header is documented but the boot log, U-Boot password (if any), and on-screen behavior on serial are all unknown. This is the single highest-leverage hardware research opportunity remaining.

## Service manual references

- **Preserved in [`archive/`](../archive/)** when a contributor has added them — see [`archive/README.md`](../archive/README.md) for the manual-download procedure (Elektrotanya / ManualsLib block scripted download).
- **HAP-Z1ES** live: [ManualsLib](https://www.manualslib.com/manual/1606461/Sony-Hap-Z1es.html), [Elektrotanya](https://elektrotanya.com/sony_hap-z1es.pdf/download.html).
- **HAP-S1** live: [ManualsLib](https://www.manualslib.com/manual/893329/Sony-Hap-S1.html), [Elektrotanya](https://elektrotanya.com/sony_hap-s1_ver.1.0_hdd_audio_player.pdf/download.html). The HAP-Z1ES and HAP-S1 manuals share most content — having either is a fair substitute for the other.
- **End-user Help Guides** (HAP-Z1ES + HAP-S1) are archived in [`archive/sony-helpguide-hap-z1es.pdf`](../archive/sony-helpguide-hap-z1es.pdf) and [`archive/sony-helpguide-hap-s1.pdf`](../archive/sony-helpguide-hap-s1.pdf). Live source: <https://helpguide.sony.net/ha/hapz1es/v1/en/print.pdf>, <https://helpguide.sony.net/ha/haps1/v1/en/print.pdf>.

Relevant pages:

- Block diagram: early pages of each manual.
- Board IDs and IC list: schematic section.
- Disassembly: dedicated section.
- DIAG mode entry: page 25 of the HAP-S1 manual (see [`05-diag-modes.md`](05-diag-modes.md) for the verified sequence).
