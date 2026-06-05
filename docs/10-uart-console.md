# UART serial console — getting a root shell / dumping the OS

The HAP's operating system (kernel + rootfs: the Python control daemon, the library indexer, the
proprietary GStreamer elements) lives on **internal NAND**, not the HDD (proved 2026-06-02) and is
**not downloadable** anywhere (firmware is OTA-only — see
[`research/notes/2026-06-03-os-acquisition-recon.md`](../research/notes/2026-06-03-os-acquisition-recon.md)).
The live-device software vectors (Samba symlink traversal, HTTP path traversal) are blocked. That
leaves the **UART serial console** — long flagged here as the highest-leverage hardware
opportunity — as the realistic path to a root shell and a NAND/rootfs dump.

This page is the working guide. Status: **prep stage** (no probe performed on hardware yet).

## What you need

| Item | Notes |
|---|---|
| **USB↔TTL serial adapter, 3.3 V** | CP2102, FTDI FT232RL (with 3.3 V jumper), or PL2303 set to 3.3 V. ~5 €. |
| Female-female jumper wires | to reach the board test points |
| Multimeter | to identify GND by continuity (optional but helpful) |
| Torx drivers | for the chassis (see service-manual disassembly section) |

### ⚠️ Three rules that prevent frying the SoC

1. **3.3 V only.** The i.MX6 UART is 3.3 V logic. A 5 V adapter will damage the SoC.
2. **Never connect the adapter's VCC/3V3 wire.** Use only **three wires: GND, RX, TX.** The board
   is self-powered.
3. **Cross RX↔TX:** board TX → adapter RX, board RX → adapter TX, GND ↔ GND.

## Serial settings

- **115200 baud, 8N1, no flow control** (i.MX6 console = `ttymxc0`; 115200 is the near-certain default).
- Windows: PuTTY or TeraTerm. WSL alternative: attach the adapter via `usbipd-win`, then
  `picocom -b 115200 /dev/ttyUSB0`.

## Where the test points are (service manual references)

From `docs/manuals/sony-service-manual-hap-z1es.pdf` (the MAIN board is codename **SPIRITOSO**;
the SoC is **IC101 = MCIMX6D5EYM10AC**, i.MX6 Dual):

| Manual page | Content | Use |
|---|---|---|
| p35 | Block Diagram — HDD/USB/LAN/FPGA/DSP (shows IC101) | overview of SoC connections |
| **p40** | **Printed Wiring Board — MAIN Section** | physical board layout → locate the UART test points |
| **p41–49** | **Schematic — MAIN Section (sheets 1–9)** | IC101 nets, incl. the UART console net |
| **p75** | **IC Function Description — IC101** (pin-by-pin table) | the readable pin→function map |

### Console UART identified at the SoC (from the p75–79 IC101 pin-function table)

The i.MX6's **UART1** (= the boot ROM / U-Boot / Linux `ttymxc0` console) is broken out:

| i.MX6 ball | Pad / signal | I/O | Manual description | Role |
|---|---|---|---|---|
| **M1** | **CSI0_DAT10** | O | "Transmit data output terminal" | **console TX** |
| **M3** | **CSI0_DAT11** | I | "Receive data input terminal" | **console RX** |

These descriptions are **unqualified**, unlike the neighbouring UARTs which the table explicitly
ties to other blocks — confirming M1/M3 are the general debug console, not an internal link:

- `CSI0_DAT12` (M2) / `CSI0_DAT13` (T1) → UART to the **system controller** (the Cortex-M3 housekeeping MCU)
- `CSI0_DAT14` / `CSI0_DAT15` → UART to the **remote-commander code-learning** processor

Also documented in the same table (useful context): the i.MX6 **boot-mode straps** are hardwired
(`EIM_A18/A20/A21/A23`, `EIM_RW`, `EIM_EB1`, `EIM_DA3/DA5/DA6/DA7` fixed H/L → boot from NAND), and
**JTAG** (TDO/TMS/TDI/TCK) is present but marked "Not used".

The SoC-side console pins are confirmed (M1/M3 = UART1) and cross-checked against the kernel cmdline
(`console=ttymxc0,115200`). (Aside: the `CSI0_DAT*` pins that drive the front-panel LCD's RGB bus are
*other* balls in the N/P/R/T/U rows — don't confuse them with M1/M3.)

**Board-level candidate — `CN4008`.** Tracing the schematic (MAIN sheet on p47), the unqualified
`TXD`/`RXD` console nets route to a connector **`CN4008`**, which also appears on the MAIN PWB (p40) —
so `CN4008` is very likely the **factory debug serial header**. Inspect it first when the board is
open. (Confirm its pinout empirically before connecting — see below — since the scanned schematic
isn't crisp enough to guarantee the pad order.)

**Empirical confirmation (always do this):** with the board open, find `CN4008` (or a small 3–4 pin
header / test pads near IC101, often silk-screened `TXD/RXD/GND`). Identify **GND** by continuity to
chassis ground with your multimeter. Connect only GND first, then probe candidate pins: the one that
**streams the boot log at power-on** is the board's **TX** → wire it to the adapter's RX. RX is the
neighbouring data pin. Never connect VCC.

**Empirical method (the way it's actually done):** with the board open, find a small 3–4 pin
header or test pads near IC101 (often silk-screened `TXD/RXD/GND` or a `CN###`/`TP###`). Identify
**GND** by continuity to chassis ground. Connect the adapter; the pin that **streams the boot log
at power-on** is the board's **TX**. Then find RX by trial (it's the neighbouring data pin).

## Reaching the MAIN board (disassembly order)

From the service manual's disassembly flow (p6), the MAIN board (which carries IC101 + `CN4008`) is
reached in this order — it sits *under* the FPGA-DSP board:

`Case top → Case L/R blocks → Plate bottom outer → Plate bottom → Front panel block → HDD block →
Power transformers (T1/T2) → FPGA-DSP board → MAIN board block → MAIN board`

Per-step screw detail is in the manual (`docs/manuals/sony-service-manual-hap-z1es.pdf`): MAIN board on
p19, FPGA-DSP board p18. **You probably don't need to fully extract the MAIN board** — just remove
enough (case top + the FPGA-DSP board above it) to expose the board surface and reach `CN4008` /
IC101 with the probe. Take photos as you go (the community HDD-swap notes in [`06-hdd-swap.md`](06-hdd-swap.md)
cover opening the case too).

## Flash layout — what the GPL kernel already tells us (pre-UART)

Read from the Sony `linux-3.0.35` kernel patch (oss.sony.net), so we walk in knowing what to expect:

- **Kernel boot cmdline** (`CONFIG_CMDLINE`): `noinitrd console=ttymxc0,115200 root=/dev/mtdblock2 rw rootfstype=jffs2 ip=off`, with `CONFIG_CMDLINE_FROM_BOOTLOADER=y`.
  - **Confirms** the console is `ttymxc0 @ 115200` (matches the M1/M3 pinout above).
  - **The rootfs is `/dev/mtdblock2`, a writable JFFS2** on NAND — not a read-only squashfs.
- **NAND**: Freescale **GPMI** controller (`gpmi-nand`).
- **SPI-NOR**: an **M25P32 (4 MB)** on SPI0/CS1, partitioned `bootloader` (offset 0, 256 KB) + `kernel` (rest).

Coherent predicted MTD map (exact map comes from U-Boot — confirm at the prompt with `cat /proc/mtd`):

| mtd | Medium | Contents |
|---|---|---|
| mtd0 | SPI-NOR | U-Boot (256 KB) |
| mtd1 | SPI-NOR | kernel (uImage) |
| **mtd2** | **NAND** | **rootfs (JFFS2)** ← the OS we want |
| mtd3+ | NAND | data / other |

**Consequences:**

- To dump the OS: `dd if=/dev/mtdblock2 of=rootfs.jffs2` (then `unmount`/extract with `jffs2dump`
  or mount via `mtdram`/`nandsim` off-device). Plus the full NAND for safety.
- The rootfs being **writable JFFS2** means once we have a shell we can **persist changes** —
  enable dropbear at boot, drop in our own daemon — which is exactly what Phase 4 (custom userland)
  needs. (Back up the NAND first.)

## Session plan (what we do once connected)

1. Open PuTTY at 115200 8N1, then **power on the HAP**. The **U-Boot + kernel boot log** streams —
   already a goldmine (firmware version, NAND layout, `bootargs`).
2. **Interrupt U-Boot**: mash a key during the "Hit any key to stop autoboot" countdown.
3. At the U-Boot prompt, read the flash layout: `mtdparts`, `nand info`, and `printenv` (the
   latter shows `bootargs`/`bootcmd` — how the rootfs is mounted).
4. **Get a root shell.** Let it boot (or type `boot`). The serial console usually lands on a root
   prompt. If it demands a login we don't have, reboot → interrupt U-Boot → append `init=/bin/sh`
   (or `single`) to `bootargs` → `boot` → a root shell with no password.
5. **Read the real flash map:** `cat /proc/mtd`, then `cat /proc/mounts`, `mount`, `df -h`.
6. **Dump each MTD partition to the PC.** Two ways — pick whichever the device supports:
   - **(A) Over Ethernet with netcat (fast).** On the PC (WSL — `nc` is already installed):
     `nc -l -p 9000 > nand_mtd2.img`. On the HAP: `dd if=/dev/mtd2 | nc <PC-IP> 9000`. Repeat per
     partition. (busybox `nc` is usually present in the rootfs.)
   - **(B) Via the SMB share we already read (no HAP-side network tools needed).** On the HAP:
     `dd if=/dev/mtd2 of=/mnt/internal/internal/mtd2.img`, then pull `mtd2.img` from the PC with any
     SMB client (e.g. `python tools/hap_sync.py list HAP_Internal`) and delete it afterwards.
   Grab at least **mtd2 (the rootfs, JFFS2)**, and ideally **every partition** for a full-NAND backup.
7. **Extract off-device:** unpack the JFFS2 with **[`tools/extract_rootfs.sh`](../tools/extract_rootfs.sh)**
   (`tools/extract_rootfs.sh mtd2.img`) → the **Python control daemon source**, init scripts, the
   library indexer, the proprietary GStreamer elements, and the DSP firmware blobs
   (`/sony/lib/modules/dspfw/`). That's the OS, in clear, with no dependence on the OTA blob.
   The full, **tested** extraction pipeline (and an important gotcha — WSL2's kernel has no MTD
   modules, so use the userspace `jefferson` path, not `mtdram`/`nandsim`) is in
   [`docs/14-nand-extract.md`](14-nand-extract.md).

The rootfs is **writable JFFS2** (confirmed from the kernel cmdline above), not squashfs — so once we
have a shell we can make changes persist (enable dropbear at boot, drop in our own daemon). `dd` of
the NAND partitions is read-only and non-destructive.

## Safety nets

- **Read before write.** Just dumping (boot log + `dd` of NAND) changes nothing on the device.
- Do **not** `nand erase`/`nand write` anything during the dump phase.
- Keep the verified `/data` backup image (`D:\HAPZ1ES\images\p1_rootfs.img`) and don't factory-reset
  until we have a full NAND dump archived.
