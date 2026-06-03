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

From `archive/sony-service-manual-hap-z1es.pdf` (the MAIN board is codename **SPIRITOSO**;
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

**Still to pin down:** the physical **test-point designator** on the MAIN PWB (p40) — trace the
`CSI0_DAT10/11` nets through the MAIN schematic (p41–49) to their `TP###`/`CN###`, or just find
them empirically (below). The SoC-level identification above is the load-bearing part: at the
board there will be a TX/RX pair carrying UART1.

**Empirical method (the way it's actually done):** with the board open, find a small 3–4 pin
header or test pads near IC101 (often silk-screened `TXD/RXD/GND` or a `CN###`/`TP###`). Identify
**GND** by continuity to chassis ground. Connect the adapter; the pin that **streams the boot log
at power-on** is the board's **TX**. Then find RX by trial (it's the neighbouring data pin).

## Session plan (what we do once connected)

1. Open PuTTY at 115200 8N1, then **power on the HAP**. The **U-Boot + kernel boot log** streams —
   already a goldmine (firmware version, NAND layout, `bootargs`).
2. **Interrupt U-Boot**: mash a key during the "Hit any key to stop autoboot" countdown.
3. At the U-Boot prompt, read the flash layout: `mtdparts`, `nand info`, and `printenv` (the
   latter shows `bootargs`/`bootcmd` — how the rootfs is mounted).
4. Get the OS, two options:
   - **Boot to a root shell**: append `init=/bin/sh` (or `single`) to `bootargs`, `boot`, then from
     the shell: `cat /proc/mtd`, `cat /proc/mounts`, and `dd if=/dev/mtdblockN of=...` each NAND
     partition; transfer off-device (tftp / nc / a mounted share / USB).
   - **Dump from U-Boot** directly: `nand read ${loadaddr} <off> <len>` into RAM, then `tftpput`
     (or `loady`/`loadb`) to the PC.
5. Result: the **rootfs as files** (Python daemon source, init scripts, the indexer, GStreamer
   elements) + a full NAND image — the OS dump, with no dependence on the OTA blob.

The rootfs is likely a read-only squashfs; `dd` of NAND partitions is non-destructive.

## Safety nets

- **Read before write.** Just dumping (boot log + `dd` of NAND) changes nothing on the device.
- Do **not** `nand erase`/`nand write` anything during the dump phase.
- Keep the verified `/data` backup image (`D:\HAPZ1ES\images\p1_rootfs.img`) and don't factory-reset
  until we have a full NAND dump archived.
