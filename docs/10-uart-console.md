# UART serial console — getting a root shell / dumping the OS

The HAP's operating system (kernel + rootfs: the Python control daemon, the library indexer, the
proprietary GStreamer elements) lives on **internal NAND**, not the HDD (proved 2026-06-02) and is
**not downloadable** anywhere (firmware is OTA-only — see
[`research/notes/2026-06-03-os-acquisition-recon.md`](../research/notes/2026-06-03-os-acquisition-recon.md)).
The live-device software vectors (Samba symlink traversal, HTTP path traversal) are blocked. That
leaves the **UART serial console** — long flagged here as the highest-leverage hardware
opportunity — as the realistic path to a root shell and a NAND/rootfs dump.

This page is the working guide. Status (2026-11-23): **the console is located but silent.** The
wiring is traced, the bench works end to end, and the player was listened to at boot, after boot
and in DIAG mode — **zero bytes, and no voltage on the console lines even at the factory header
inside the player.** The most likely cause is that the 0 Ω links feeding the console on the MAIN
board were left unfitted at the factory. That is unconfirmed: it needs the MAIN board uncovered.
Read [Bench session 2026-11-23](#bench-session-2026-11-23--the-console-is-silent) before buying
anything. On a HAP-S1 the same header **is** live (@jimsmt, 2026-11-24) — see the
[cross-model notes](#cross-model-the-s1-console-is-live-and-the-s1-to-z1es-connector-map-2026-11-24).

## The short version

- The rear panel has an unlabelled slot between the `EXT` USB socket and the Sony rating label. It
  is **`CN4007`**, a 7-way flat-flex (FFC) socket, **1.0 mm pitch**, and it carries the i.MX6
  console UART (UART1, `ttymxc0`) at **3.3 V** — plus a reset line and a 3.3 V rail you must not
  touch.
- You need a **7-way 1.0 mm FFC cable**, an **FFC-to-2.54 mm breakout board** (1.0 mm side), three
  jumper wires and a **3.3 V USB–TTL adapter**. Nothing to open, nothing to solder — in theory.
  On our unit the console carried nothing (see the bench session below), and the rear socket came
  off the board on the first insertion.
- **115200 8N1**, no flow control. Open the terminal, then power the player on.

![Rear panel: the service slot next to the EXT USB socket](../research/captures/2026-09-26-rear-service-slot.jpg)

## What you need

| Item | Notes |
|---|---|
| **USB↔TTL serial adapter, 3.3 V** | CH340, CP2102, FTDI FT232RL or PL2303 — with the level jumper on **3V3**. ~3 €. |
| **FFC cable, 7-way, 1.0 mm pitch** | Any length from 10 cm; 0.3 mm thick standard. Type A or B does not matter with a breakout board. |
| **FFC-to-2.54 mm breakout board** | A ZIF (flip-latch) board takes a narrower cable than its own width, so a 9/10/12-way board is fine as long as its **1.0 mm** side is used. Get one with the pin header already soldered. |
| Female-female jumper wires | breakout → adapter |
| Multimeter | to find GND by continuity to the chassis (identifies the cable orientation) |

Verified on Amazon.fr, 2026-09-26: cable `B08493L4KZ` (20 × 150 mm, 8.72 €). **Correction
(2026-10-12):** the breakout first listed here, `B0D84641C2`, is too small — its only real socket is
0.5 mm; the "1.0 mm back" is bare pads that need soldering. What worked: an "FPC-8P 1.0 mm" board
with the 1.0 mm socket fitted and a 2 × 4 right-angle header already soldered (eBay, ~10 €).

### ⚠️ Three rules that prevent frying the SoC

1. **3.3 V only.** The i.MX6 UART is 3.3 V logic. A 5 V adapter will damage the SoC.
2. **Never connect the adapter's VCC/3V3 wire.** Use only **three wires: GND, RX, TX.** The board
   is self-powered, and the service port even exposes its own 3.3 V rail — leave it alone.
3. **Cross RX↔TX:** player TX → adapter RX, player RX → adapter TX, GND ↔ GND. Swapping the two
   data lines by mistake is harmless (nothing appears; swap back).

## Serial settings

- **115200 baud, 8N1, no flow control** (i.MX6 console = `ttymxc0`; confirmed by the GPL kernel
  cmdline `console=ttymxc0,115200`).
- Windows: PuTTY or TeraTerm. macOS: the CH340 is native (`/dev/cu.usbserial-*`), `screen` or
  Python `termios` work. WSL alternative: attach the adapter via `usbipd-win`, then
  `picocom -b 115200 /dev/ttyUSB0`.

## Where the console is — traced through the service manual

Source: [`manuals/sony-service-manual-hap-z1es.pdf`](manuals/sony-service-manual-hap-z1es.pdf).
The MAIN board is codename **SPIRITOSO**; the SoC is **IC101 = MCIMX6D5EYM10AC** (i.MX6 Dual).
The board Sony calls the **IO board** (`1-888-906-11`, silk-screened `HAP-Z1ES-DIGITAL`) is the
one carrying the USB, LAN and IR sockets on the rear.

### The chain, segment by segment

| Segment | Where | Pins | Manual |
|---|---|---|---|
| SoC | IC101, MAIN board | ball **M1 = `CSI0_DAT10`** = UART1 **TX** (console out); ball **M3 = `CSI0_DAT11`** = UART1 **RX** (console in) | p47, p75 |
| Series resistors | MAIN | TX → R702 → R749 → M1; RX → R701 → M3 (all 0 Ω) | p47 |
| Main-board header | **`CN701`**, 6-way | 1 = 3.3 V, 2 = GND, 3 = **RXD** (console in), 4 = **TXD** (console out), 5 = DON, 6 = N.C. Test pads on side B: CL708 GND, CL706 TXD, CL707 RXD | p47, p40 |
| Cable | 4 white wires MAIN `CN701` → IO `CN4008` | — | — |
| IO-board header | **`CN4008`**, 5-way, 1.5 mm pitch (Sony `1-573-768-21`) | 1 = 3.3 V, 2 = GND, 3 = **RXD**, 4 = **TXD**, 5 = DON. Silk-screened `3.3V / GND / TXD / GND` next to it (the `RXD` label is under the wires). Pin 1 is unwired. | p51, p50, p110 |
| Rear service port | **`CN4007`**, 7-way FFC socket, **1.0 mm pitch**, LIF non-ZIF (Sony `1-784-859-51`) | see the table below | p51, p110 |

The names on `CN4008`/`CN701` are the **processor's**: `TXD` is what the i.MX6 transmits. The
names on the rear port `CN4007` are the **service tool's**: its `TX` pin is wired to `CN4008 RXD`
(what the player receives) and its `RX` pin to `CN4008 TXD` (what the player sends). Read from the
IO-board schematic (p51): `CL4020 TX → CN4008-3 RXD`, `CL4022 RX → CN4008-4 TXD`,
`CL4024 DON → CN4008-5 DON`. So the rear port is labelled exactly like a USB–TTL adapter, and it
wires **straight, name to name**.

### Rear service port `CN4007` — pinout and what to connect

| Pin | Name (tool side) | Test pad | Meaning for the player | Connect to |
|---|---|---|---|---|
| 1 | DON | CL4024 | goes to the SoC `DIAG_EN` input via R762 | nothing |
| 2 | RST | CL4023 | reset | **nothing** |
| 3 | RX | CL4022 | **console OUT** of the player (SoC M1) | adapter **RXD** |
| 4 | SCK | CL4021 | not connected on the IO board | nothing |
| 5 | TX | CL4020 | **console IN** of the player (SoC M3) | adapter **TXD** |
| 6 | GND | CL4019 | ground | adapter **GND** |
| 7 | 3.3 V | CL4018 | the player's 3.3 V rail | **nothing** |

Pin 1 is at the end marked by the triangle on the IO-board silk screen (the end nearest the
resistor group R4026/R4031/R4032, away from the USB socket). On the rear panel, resolve the
orientation empirically rather than by drawing: **the GND conductor is the one with continuity to
the chassis, and the 3.3 V conductor is its outer neighbour at the end of the row.** Everything
else follows from those two.

![IO board: CN4007 (FFC socket at the board edge) and CN4008 (5-way header)](../research/captures/2026-09-26-io-board-cn4007-cn4008.jpg)

### Why 1.0 mm

The service manual gives the part but not the pitch. It was measured on the IO-board PWB drawing
(p50), which is to scale: the seven `CN4007` pads are 50 px apart where the five `CN4008` pads —
1.5 mm pitch per the parts list — are 71 px apart, i.e. **1.06 mm**, and the board's 3 mm via
grid agrees. A 7-way 1.0 mm FFC is 8.0 mm wide, which is the width of the slot on the rear panel.

![PWB drawing p50: CN4007 pads (top) against CN4008 pads (bottom, 1.5 mm)](../research/captures/2026-09-26-io-board-pwb-cn4007-pitch.png)

### If you have the lid off anyway: `CN4008` directly

The same three signals are on `CN4008` (IO board, next to the USB socket, on the component side —
so it is reachable without unscrewing anything once the top cover is off). Its pins are 0.6 mm
tails at 1.5 mm pitch: too small for crocodile clips, fine for micro test hooks, or for sewing pins
pushed through the insulation of the white wires (top wire = pin 2). Pin 1 (3.3 V) has no wire.

![CN4008: where each adapter wire goes](../research/captures/2026-09-26-cn4008-wiring.jpg)

| `CN4008` pin | Silk | Connect to |
|---|---|---|
| 1 | 3.3V | nothing |
| 2 | GND | adapter GND |
| 3 | (RXD) | adapter TXD |
| 4 | TXD | adapter RXD |
| 5 | GND (DON on the schematic) | nothing |

The solder-side test pads of the IO board (`CL4019` GND, `CL4022` console out, `CL4020` console
in) are the third option, mapped in
[`research/captures/2026-09-26-io-board-uart-pads.png`](../research/captures/2026-09-26-io-board-uart-pads.png)
— but the solder side faces the chassis floor, so the rear slot is the practical route.

### What is inside (board inventory, from the open unit)

Photographed 2026-09-26 on the reference HAP-Z1ES
([overview](../research/captures/2026-09-26-chassis-open-overview.jpg),
[IO board](../research/captures/2026-09-26-io-board-overview.jpg)):

| Board | Sony ref | What it is |
|---|---|---|
| MAIN (Spiritoso) | — | i.MX6 Dual IC101, 2 × H5TQ1G63EFR DDR3, KLM4G1FE3B 4 GB eMMC-class NAND (IC501), AR8035 Ethernet PHY, SATA to the HDD. Sits **under** the DSP board. |
| FPGA-DSP | `1-888-626-11` | daughter board on top of MAIN; yellow "DSP" sticker, `FORZA` marking, unpopulated CN101/CN102 pads (not a UART) |
| IO ("DIGITAL") | `1-888-906-11` | USB, LAN, IR-out; **`CN4007` service port, `CN4008` console header** |
| U-COM | — | MB9AF156 Cortex-M3 system controller (front panel, standby); talks to the i.MX6 on UART `CSI0_DAT12/13` — not the console |
| DCDC | `1-888-902-11` | digital supplies, fan control |
| ANALOG POWER | `1-888-904-11` | ±15 V / 5 V for the audio boards |
| STBY | `1-888-903-11` | **mains**: the red standby transformer and relay live here, uninsulated |
| AUDIO | `1-888-900-11` | DAC / analogue output stage |
| AUDOUT | `1-888-901-11` | RCA sockets |
| FAN-CONNECT | `1-889-634-11` | fan and HDD-bay interconnect |

Two transformers (`1-697-298-11`, `1-697-301-11`) feed the digital and analogue halves. The HDD
is an HGST 1 TB 2.5" 5400 rpm on a plain SATA cable.

On a **HAP-S1**, the DIAG *Version Info* page reports the eMMC as `SAMSUNG M4G1FB`
(@djordjevich-droid, 2026-11-19 — see [`05-diag-modes.md`](05-diag-modes.md)). That is the
name the chip gives itself, not the package marking, so it is consistent with the Samsung 4 GB
`KLM4G1F…` part above without proving the two models carry the same chip. The same page on a
Z1ES would settle it.

The front-panel **test mode** (p25) is unrelated to the console: with the unit in standby, hold
`HOME` + `BACK`, then press `▶II` (PLAY) then `POWER` — a "Main Menu" with Version Info, ID Info,
LED/KEY, LCD/Others, HDD, Audio, WiFi, Ether, IR Learning, Quit appears on the display. Full
menu in [`05-diag-modes.md`](05-diag-modes.md).

## Bench session 2026-11-23 — the console is silent

The first real attempt, on the reference HAP-Z1ES (firmware `0019404R`). Everything on the PC side
was proven before the player was touched; the result is a clean negative, kept here in full so
nobody has to repeat it blind.

> **The console being silent does not close the root path.** Sony's own GPL U-Boot is built
> unsigned, so the i.MX6 boot ROM should accept our own U-Boot over USB and let us dump the eMMC
> without the UART at all. That alternative is worked out in
> [`19-imx6-serial-download.md`](19-imx6-serial-download.md).

### The bench

A Windows 11 laptop next to the player, a CH340 adapter (USB `1a86:7523`, jumper on 3V3), driven
remotely over SSH. A small Python logger (`pyserial`, 115200 8N1) runs permanently, finds the
adapter by its USB ID whatever COM number Windows gives it, and writes every byte to a raw `.bin`
plus a timestamped `.log`. **Loopback test passed** (TX tied to RX: 120 bytes of text and 256 random
bytes came back identical), so a silent log means a silent player, not a broken bench.

![CH340 adapter: GND, RXD, TXD used; 3V3 and 5V left free](../research/captures/2026-11-23-ch340-adapter-wiring.jpg)

### The rear socket `CN4007` is fragile

- The seven contacts sit on the **top** side of the slot. The FFC goes in **contacts facing up**.
- With the FFC fully home (about 1 cm deep), only the GND conductor showed continuity; the other
  six read open. Shortly after, **the socket came off the IO board** while the cable was being
  re-seated. It is a surface-mount LIF part held by its pads; treat it gently.
- The board survived: the seven pads and the two hold-down tabs are clean. With the socket gone, a
  bare FFC end pressed **contacts down** on the pads (tape and a weight) makes contact — which
  reverses the conductor order, so re-find GND by continuity every time you change anything.
- With contacts up in an intact socket, GND is the **2nd conductor from the left, seen from the
  back of the player**. On our 8-way breakout that came out as the mapping below (GND verified by
  continuity; the rest follows the service-manual order).

![FPC-8P breakout: which pin goes to which adapter wire (socket intact, FFC contacts up)](../research/captures/2026-11-23-cn4007-breakout-wiring.jpg)

### What was measured

| Test | Result |
|---|---|
| Listen during cold boot (5 min), after boot, and in DIAG mode | **0 bytes** |
| Voltages on the breakout, player on, DC 20 V range, black probe on chassis | **0 V on every pin** |
| Same check **directly on the factory header `CN4008`**, player on: pin 1 (3.3 V) and pin 4 (TXD, console out) | **0 V on both** |
| Sanity check of the meter on the EXT USB socket, player on | 5.29 V |
| Resistance to chassis, player off (pads, contacts down) | GND = 0 Ω, one neighbour 52.7 kΩ, the rest open |

An idle UART output sits at the logic-high level (3.3 V here). **0 V on the console-out line at the
factory header, with the player running, means that line is not driven at all** — so the rear port
and our cable are not the problem. The 3.3 V pin of the same header is dead too.

Caveat: the `CN4008` check was done by touching the 0.6 mm tails of the header with a standard
probe — hard to do cleanly. It deserves to be repeated with a fine probe before it is taken as final.

### Why this is not a software lock

- The Sony GPL kernel (`board-mx6q_sabresd.c` in the `linux-3.0.35` patch) registers **UART1** and
  sets up an **early console** on it, on exactly the two balls traced here (`CSI0_DAT10/11`, M1/M3,
  "UART1 for debug"). The software expects a console on these pins.
- **DIAG mode** (front panel: `HOME` + `BACK`, then `▶II`, then `POWER`) does not wake it: still 0
  bytes. The `DON` line on the service port goes straight (R762, 0 Ω) to the SoC's `DIAG_EN` input
  (`EIM_D28`, ball G23, "Diag mode enable signal input"), which the kernel never reads — so pulling
  `DON` is unlikely to give more than the front-panel combo already does.

### The most likely cause: unfitted 0 Ω links on MAIN

On the MAIN-board schematic (p47) every console line reaches `CN701` through a 0 Ω link:

| `CN701` pin | Signal | Link |
|---|---|---|
| 1 | 3.3 V | **R705** (0 Ω) from the 3.3 V rail |
| 3 | RXD (console in) | **R701** (0 Ω) |
| 4 | TXD (console out) | **R702** (0 Ω), then R749 to ball M1 |
| 5 | DON | **R762** (0 Ω) to `DIAG_EN` |

Leaving such links off production boards is a common way to disconnect a debug port. **Both dead
lines we measured (3.3 V and TXD) pass through one of them**, which fits. It is a hypothesis: none of
these parts has been seen yet.

**Where they are:** the MAIN board sits in the metal cage on the left of the chassis, next to the
HDD, **under the FPGA-DSP daughter board** (the one marked `FORZA`). The grey 4-wire cable from
`CN4008` runs to it. It cannot be seen without lifting the DSP board.

**If you can get there** (a repair shop can): photograph the area around `CN701` and check whether
R701, R702 and R705 are fitted. If the pads are empty, bridging them (or wiring straight to the
SoC side of each link) should bring the console back — and that would be the first root shell on a
HAP. Sony notes that IC101 is not replaceable on its own: a damaged MAIN board means a whole new
board, so this is a job for steady hands.

### A side finding: the factory Wi-Fi test network

In DIAG mode, **Wifi → Network/Module Info** shows the network the factory test uses:
**SSID `SONY_HAP_TEST`, key `SONY_HAP_TEST`**. A phone hotspot with that name and password (2.4 GHz)
is joined at once: the page then shows an IP, mask and gateway, and *Ping/RSSI* succeeds. The player
answers ping (TTL 64) but **a full TCP scan, ports 1–65535, found nothing open** — not even the
ports it serves in normal use (60100–60400). DIAG mode opens no maintenance door on the network.

## Session plan (what we do once connected)

1. Open PuTTY at 115200 8N1, then **power on the HAP**. The **U-Boot + kernel boot log** streams —
   already a goldmine (firmware version, NAND layout, `bootargs`). If the terminal stays silent,
   swap the two data wires; if it shows garbage, try 57600 then 38400.
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

Also documented in the IC101 pin table (p75–79): the i.MX6 **boot-mode straps** are hardwired
(`EIM_A18/A20/A21/A23`, `EIM_RW`, `EIM_EB1`, `EIM_DA3/DA5/DA6/DA7` fixed H/L → boot from NAND), and
**JTAG** (TDO/TMS/TDI/TCK) is present but marked "Not used". The neighbouring UARTs are explicitly
tied to other blocks — `CSI0_DAT12/13` (M2/T1) to the system controller, `CSI0_DAT14/15` to the
remote-commander code-learning processor — which is what makes M1/M3 the general console.

## Cross-model: the S1 console is live, and the S1 to Z1ES connector map (2026-11-24)

@jimsmt reopened a HAP-S1 ([issue #6](https://github.com/Guillain-RDCDE/HAP-Revival/issues/6))
and got the serial console working — the direct counter-case to our silent Z1ES bench above. Two
things came out of it: a confirmed live pinout, and the fact that **Sony renumbered the connectors
between the two models**, a trap worth spelling out.

### Connectors are renumbered between S1 and Z1ES

Both service manuals list the same parts under different `CN` numbers. Matched by Sony **part
number** — the only reliable key — the console header is the same component on both machines. It is
simply called `CN4008` on the Z1ES and `CN4013` on the S1.

| Function | Sony part no. | HAP-Z1ES | HAP-S1 |
|---|---|---|---|
| LAN jack (10/100/1000) | 1-842-235-11 | CN4001 | CN4001 |
| USB-A (5 V 1 A, `EXT`) | 1-822-423-11 | CN4002 | CN4002 |
| Pin header, 11P 1.5 mm | 1-779-268-21 | CN4003 | CN4003 |
| Pin header, 6P 1.5 mm | 1-573-806-21 | CN4005 | CN4005 |
| **UART console, 5P 1.5 mm** | **1-573-768-21** | **CN4008** | **CN4013** |
| FFC/FPC LIF, 7P | 1-784-859-51 | CN4007 | CN4011 |

**Do not trust the `CN` label across models.** From the same parts lists:

- **`CN4006` is a different connector on each model** — a 3-pin 1.5 mm header on the Z1ES
  (1-691-550-11), a 24-pin FFC/FPC on the S1 (1-815-763-32).
- The **7-pin flat-flex** that is our rear service port (`CN4007` on the Z1ES) is **`CN4011`** on
  the S1.
- The S1 carries connectors the Z1ES does not: on the S1, `CN4007` (22P FFC), `CN4008` (13P),
  `CN4009` (4P) and `CN4010` (2P) are all distinct parts. The Z1ES 40xx range stops at `CN4008`.

The console header pinout is identical on both (Z1ES `CN4008` = S1 `CN4013`):

| Pin | Signal |
|---|---|
| 1 | 3.3 V |
| 2 | GND |
| 3 | RXD |
| 4 | TXD |
| 5 | DON |
| 6 | N.C. |

### What the S1 shows that the Z1ES did not

On @jimsmt's S1 the header is **live**: 3.3 V present, RX/TX good, and a boot log appears at
power-on. That is the direct counter-case to
[our silent Z1ES header](#bench-session-2026-11-23--the-console-is-silent), and it strengthens the
unfitted-0-Ω-links / board-revision theory — the same connector, powered on one unit and dead on
ours.

But even on the live port, two limits appear, and they shape the whole approach:

- **U-Boot is silent and does not break in.** Several key combinations held while applying AC power
  did nothing.
- **The running Linux system ignores UART input entirely.** Boot messages come out up to an
  `-init-` line, then nothing accepts a keystroke.

Read together, this looks less like "input is broken" and more like **no interactive shell is
offered on `ttymxc0`**: the kernel console is output-only (no `getty`/login) and U-Boot has little
or no interrupt window. If that holds, typing into the running system will never drop you to a
shell — the shell has to come from **U-Boot** (booting `init=/bin/sh` or single-user), not from the
live console.

That is exactly the appeal of the [i.MX6 USB serial-download path](19-imx6-serial-download.md): it
bypasses both the silent U-Boot prompt and the console-input problem. @jimsmt's boot log stays
valuable as the reference to confirm a USB-loaded U-Boot is driving the real board.

> **Open question.** @jimsmt reports the S1 UART reaching a **rear-panel** port wired to `CN4013`
> by long leads, but the service manual places `CN4013` on the digital/IO board. Whether that rear
> port is original or owner-added is still to confirm.

## Safety nets

- **Read before write.** Just dumping (boot log + `dd` of NAND) changes nothing on the device.
- Do **not** `nand erase`/`nand write` anything during the dump phase.
- Keep the verified `/data` backup image (`D:\HAPZ1ES\images\p1_rootfs.img`) and don't factory-reset
  until we have a full NAND dump archived.
- The STBY board (top right when the lid is off) carries **230 V** on bare pins. Keep fingers and
  probes away from it; the console work never needs to go near it.
