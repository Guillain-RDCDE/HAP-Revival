# i.MX6 serial download — a root path that does not need the UART

The first serial-console bench session was negative: the UART is silent and unpowered even at the
factory header, most likely because of unfitted 0 Ω links on the MAIN board under the DSP daughter
board (see
[`10-uart-console.md`](10-uart-console.md#bench-session-2026-11-23--the-console-is-silent)). That
closes the console as the way in — but it is not the only door to a root shell.

This page proposes a second path that goes **through the SoC's boot ROM over USB, not through the
UART**, and it is derived entirely from two sources we already hold: Sony's own published GPL
U-Boot, and the service manual. It is a **proposed route pending bench confirmation**, written up
here first so the reasoning and the open questions are on the record before any hardware is touched.

## TL;DR

- Sony's GPL U-Boot for this player is built **unsigned** — no `CONFIG_SECURE_BOOT`, and the boot
  header carries **no CSF** (code-signing command sequence). That is the build you make for a part
  whose secure-boot fuses are **open**.
- An i.MX6 with open fuses will accept and run **our own unsigned U-Boot in RAM over USB**, through
  the boot ROM's Serial Download Protocol (SDP) — the same mechanism `imx_usb_loader` and NXP's
  `uuu` drive. No signature, no UART.
- From that U-Boot we read the **eMMC** directly (`mmc` commands) and dump the rootfs, which yields
  the firmware-update tool and the **AES key** that unseals the 19404R blob we already captured.
- The one catch: the board is strapped to normal boot, so the SoC does not offer SDP on its own.
  Getting it into SDP needs either a boot-failure fallback or a one-resistor rework — detailed
  below. Everything here must be confirmed on the bench; the fuse state is inferred from source,
  not yet read from silicon.

## What the GPL U-Boot proves (ground truth)

Sony is required to publish the U-Boot source because it is GPL. The drop is at
`oss.sony.net/Products/Linux/Audio/HAP-S1.html` (it covers both players). The Sony changes live in
the U-Boot patch, archived off-git alongside the other research sources.

Two facts come straight out of that source:

- The board is **`mx6_anap`** (`CONFIG_ANAP`), an i.MX6 Dual. All the player-specific U-Boot code
  sits under `board/freescale/mx6_anap/` and `include/configs/mx6_anap.h`.
- `include/configs/mx6_anap.h` **does not define `CONFIG_SECURE_BOOT`**. The HAB (High Assurance
  Boot) code is present in the tree, but the config symbol is enabled only on the Freescale
  reference boards (`mx6q_sabresd`, `mx6q_arm2`, the sl boards), never on the Sony board.
- The consequence is written into the boot header. In
  `board/freescale/mx6_anap/flash_header.S` the image vector table sets the CSF pointer
  conditionally:

  ```text
  #ifdef CONFIG_SECURE_BOOT
  app_code_csf:     .word __hab_data     /* a real signature block */
  #else
  app_code_csf:     .word 0x0            /* no signature — this is the branch that compiles */
  #endif
  ```

  With `CONFIG_SECURE_BOOT` undefined for ANAP, **`app_code_csf = 0`** — the image ships with no
  signature. That is exactly the image you build for an **open** (non-secure) part.

A boot ROM running in secure mode rejects an unsigned image; Sony ships an unsigned image as its
production bootloader. The most consistent reading is that the HAB fuses on this SoC are **open**,
and an unsigned image loaded over SDP will therefore run. This is inference from the shipped build,
not yet a reading of the fuse bank — see the open questions below.

## The boot mode is strapped to normal internal boot

From the i.MX6 ball list in the service manual:

- `BOOT_MODE0` — ball **C12** — *Boot mode setting terminal, fixed at "L"*.
- `BOOT_MODE1` — ball **F12** — *Boot mode setting terminal, fixed at "H"*.

So `BOOT_MODE[1:0] = 0b10` = **internal boot**. The dozens of `EIM_*` lines also marked *"boot mode
setting terminal, fixed at L/H"* are the `BOOT_CFG` straps that point the ROM at the eMMC. The part
boots normally and **does not enter serial-download mode by itself** — the ROM only falls through to
SDP when internal boot cannot produce a valid image, or when `BOOT_MODE` is `0b01`.

Two ways to reach SDP follow from that, lightest first:

1. **Boot-failure fallback (no rework).** Hold the eMMC unreadable at power-on — a brief short on a
   uSDHC data or clock line, if a series resistor or test pad is reachable — so the ROM finds no
   valid header and drops to the serial downloader. Whether any uSDHC line is reachable without
   rework is a bench question (check the MAIN-board schematic sheets for series resistors on the
   eMMC bus).
2. **One-resistor rework (permanent, trivial for a tech).** Move the two `BOOT_MODE` straps to
   `0b01` (serial downloader): `BOOT_MODE0` L→H, `BOOT_MODE1` H→L. These are top-side strap
   resistors near the SoC, not the links buried under the DSP board that defeated the UART. This is
   a far smaller job than the UART soldering, and it makes SDP available on every power-on.

## Where USB-OTG goes

The boot ROM's SDP speaks over the SoC's **USB_OTG** (USB0) port. From the i.MX6 pin descriptions in
the service manual:

- `USB_OTG_DP` / `USB_OTG_DN` — *"two-way USB data with the USB connector"*.
- VBUS is **driven by the SoC** under GPIO control (`EIM_D22` = *"VBUS power on/off control for the
  USB connector"*, `EIM_D21` = over-current sense).
- `USB_OTG_ID` is marked **"not used"**.

In normal operation this is the **external USB-A port** (the one that takes a USB drive), wired as a
host. That is good news: the data pair is on an accessible connector, not an internal pad. In SDP
the boot ROM reconfigures USB_OTG as a **USB device**, so the roles invert — and because both the
player and the PC would then try to source VBUS, the link must be a **USB A-to-A cable with VBUS
(the red wire) left disconnected**, data and ground only.

One thing to confirm on the bench before trusting this: schematic sheet 49 shows the OTG net passing
through a **VBUS switch** and sitting near the internal WLAN/BT combo connectors (`CN9001`/`CN9002`)
as well as `CN4005` on the IO board. Meter out which physical connector actually carries
`USB_OTG_DP`/`USB_OTG_DN` before wiring anything.

## The route, end to end

1. Put the SoC into SDP (fallback short, or the strap rework) and connect the OTG port to the PC
   with a VBUS-cut A-to-A cable.
2. On the PC, confirm the player enumerates as an NXP/Freescale serial-download device
   (USB VID `0x15a2`). This single step is the real proof that the fuses are open.
3. Load an i.MX6 Dual SPL + U-Boot into RAM with `imx_usb_loader` (or `uuu`). Build it from the ANAP
   source we hold, or from a generic `mx6dq` target — we only need RAM bring-up and `mmc`.
4. At that U-Boot, read the eMMC: the ANAP environment boots from eMMC
   (`mmc dev 3`, `root=/dev/mmcblk0p1`), so `mmc dev 3; mmc read …` (or `ext4load`) pulls the root
   partition off the device with no live OS involved.

   > This corrects the working assumption in [`14-nand-extract.md`](14-nand-extract.md), which was
   > derived from the kernel config and expected a raw-NAND JFFS2 rootfs at `/dev/mtdblock2`. The
   > ANAP U-Boot boots from **eMMC**; the extraction target is an **ext4 partition on eMMC**, not a
   > JFFS2 MTD. The `jefferson` step in that doc does not apply to an ext4 image — mount it, or use
   > `debugfs`/`7z`, instead.
5. Mount the dumped rootfs off-device, find the firmware-update tool, and recover the AES key it
   uses. With the key, the 19404R CN blob already in hand
   ([`07-firmware.md`](07-firmware.md)) decrypts, and the whole shipped image opens up — without
   ever needing the running system.

## What is proven, and what the bench must confirm

Proven from sources we hold:

- The player's production U-Boot is unsigned (no `CONFIG_SECURE_BOOT`, CSF pointer `0`).
- `BOOT_MODE[1:0]` is strapped to internal boot (`0b10`).
- USB_OTG is routed to the external USB connector, host-wired, ID unused.
- The player boots its rootfs from eMMC.

Still to confirm on the bench, in order:

1. **Fuse state** — does the player enumerate as VID `0x15a2` in SDP? Open fuses are inferred, not
   yet read. This is the make-or-break test and it is free.
2. **Which connector** carries `USB_OTG_DP`/`USB_OTG_DN`, and whether a VBUS-cut A-to-A cable on it
   reaches the SoC (the VBUS switch on sheet 49 may gate it).
3. **How to trigger SDP** without rework — is any uSDHC line reachable for the boot-fail short, or do
   we accept the one-resistor `BOOT_MODE` rework by a tech?

## Provenance

- Sony GPL U-Boot (`u-boot-2012.04.01` + the Sony patch) and kernel, from
  `oss.sony.net/Products/Linux/Audio/HAP-S1.html`; archived off-git with the other research sources.
- Service manual ball list and schematic sheets (IC101 i.MX6DQ `MCIMX6D5EYM10AC`), preserved under
  [`manuals/`](manuals/).
- Reasoning recorded 2026-11-23, the same day the UART came back silent. Nothing here has been tried
  on hardware yet; it is the next bench session's plan, not a result.
