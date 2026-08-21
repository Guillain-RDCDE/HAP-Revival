# Firmware

What we know — and don't know — about the on-device firmware.

## Current state

| Version | Released | Size | Notes |
|---|---|---|---|
| **19404R** | 2021-01-14 | ~77.8 MB (77,776,256 bytes) | **Latest. Sony has shipped nothing since.** |
| 19226R | ~2019 | ~similar | |
| 18777R | ~2018 | ~similar | Introduced the Special Mode SMB selector |
| 18444R | ~2017 | ~similar | |
| earlier | 2014–2016 | | Multiple incremental releases |

Each version is distributed as a single binary blob (extension reportedly `.SonyAP` or similar; format not publicly documented). The firmware updater on the device consumes this blob; **no one outside Sony has documented its container format**.

## The firmware blob is OTA-only — there is no public copy

> **⚠️ You cannot download the HAP firmware. Confirmed by an exhaustive multi-source search
> (2026-06-03): no copy of any HAP-Z1ES/HAP-S1 firmware version exists anywhere public** —
> not on archive.org, GitHub, or the Japanese/Chinese modding communities. See
> [`research/notes/2026-06-03-os-acquisition-recon.md`](../research/notes/2026-06-03-os-acquisition-recon.md).

The device fetches updates **over the air**: Settings → Network Update pulls the blob directly from
Sony's update servers (`info.update.sony.net`) and applies it. The regional "download" support pages
below are **information pages only** — they describe the on-device Network Update procedure and do
**not** expose a downloadable file (verified across UK / Asia / Canada / Japan / China; even Sony
China's `service.sony.com.cn/download/firm/…` is network-update-only). The "~77.8 MB" figure is the
OTA payload size, not a clickable link.

- **UK**: <https://www.sony.co.uk/electronics/support/audio-components-hdd-audio-network-audio-players/hap-z1es/downloads/00017123>
- **Asia**: <https://www.sony-asia.com/electronics/support/downloads/00017124>
- **Canada**: <https://www.sony.ca/en/electronics/support/audio-components-hdd-audio-network-audio-players/hap-z1es/downloads/00017125>

**Why nobody ever mirrored it:** the HDD-swap modding scene never needed the blob — the OS lives on
internal NAND, so a blank replacement drive re-initializes on-device via factory reset (~5 min),
restoring firmware + bundled music from NAND. (If anyone captures the OTA blob,
[`ma1co/fwtool.py`](https://github.com/ma1co/fwtool.py) is the likely unpacker for Sony's
`.SonyAP`/FDAT container.)

### The update host is alive, and it is a plain file server (2026-08-21)

That "the realistic path is a NAND dump" conclusion now looks too pessimistic. Probing
`info.update.sony.net` — no device involved, no credentials:

| Fact | Value |
|---|---|
| Resolves | `23.194.190.156`, `.147` via `info.update.sony.net.edgesuite.net` — **Akamai** |
| TLS certificate | Valid, `CN=info.update.sony.net`, Sony Global Manufacturing & Operations, **renewed 2025-12-04**, expires 2027-01-04 |
| Plain HTTP | **Works.** `GET http://info.update.sony.net/` → `404`, and **no redirect to HTTPS** |
| `Server:` | **`AkamaiNetStorage`** |
| Body at `/` | `Not a file` |
| `Accept-Ranges` | `bytes` |

Three things follow. Sony is **still paying to renew that certificate in December 2025**, so the
update infrastructure is maintained, not abandoned. `AkamaiNetStorage` plus `Not a file` means the
origin is a **static file store**, not an application — give it a valid path and it hands back a
file. And it serves that file over **plain HTTP with range support and no HTTPS redirect**, which is
what you would expect a 2014 device running Linux 3.0.35 to require.

**So the blob is very likely a static file on a public CDN, fetchable with `curl`, if we learn its
path.** That is a different problem from "dump the NAND over UART" — and a much smaller one.

We do **not** know the path, and we will not find it by guessing at someone else's CDN. The way to
learn it is to capture one update check from a real device (see below). If the version string turns
out to be part of the path, older firmwares may be directly addressable too — which would give us
`0017310R`, and with it the live `contentdb` API, **without downgrading anything**.

The UART/NAND route ([`10-uart-console.md`](10-uart-console.md)) remains the way to get the
*running* system and the proprietary userland. This CDN route, if it works, gets us the *shipped
image* — cheaper, and with zero risk to hardware. Try it first.

### Next step: capture one update check (zero risk)

On a device already running the latest firmware, trigger **Settings → Network Update** while
capturing its traffic. There is nothing newer than 19404R, so the check finds no update and nothing
is written to the device — but the request itself reveals the host, the path scheme, and whether the
device speaks HTTP or HTTPS. That single capture is the whole unlock, and it risks nothing.

## GPL source code (what Sony is legally required to publish)

This is the big one. Because the firmware contains GPL-licensed software (the Linux kernel, BusyBox, Samba, etc.), Sony must publish the source code for those components. They do, at:

- **Index page**: <https://oss.sony.net/Products/Linux/Audio/HAP-S1.html> (covers HAP-S1 and HAP-Z1ES — they share a page)
- **Older firmwares**: <https://oss.sony.net/Products/Linux/Audio/HAP-S1_19226R.html>, `.../HAP-S1_18777R.html`, `.../HAP-S1_18444R.html`
- **Tarball CDN**: `https://prodgpl.blob.core.windows.net/download/Audio/HAP-S1, HAP-Z1ES(<ver>)/<package>.tar.<ext>` — note the literal space and parentheses in the path; URL-encode when scripting.

### What's included in the GPL drop

- Linux 3.0.35 source + Sony patch
- U-Boot 2012.04.01 source + Sony patch (and an older 2009.08 patch)
- BusyBox, dropbear, dnsmasq, samba, lighttpd, OpenWrt scripts (procd, netifd, ubus, uci, libubox)
- ALSA, FLAC, libvorbis, GStreamer 0.10.36 + base/good/bad/ugly/python plugins + `gst-fsl-plugins`
- `imx-lib` (Freescale userland)
- Python 2.7.3, `web.py` 0.37, `pyOSC`
- SQLite, Tokyo Cabinet, MediaInfo
- DirectFB 1.4.17
- bluez, dbus
- **`forza_snd_driver.tgz`** — the Sony-custom ALSA kernel driver. **This is the most valuable single file in the bundle.** Reading it gives us the FPGA/DSP/DAC programming model.

### What's NOT in the GPL drop

These are Sony's proprietary application-layer pieces:

- The control daemon (`hapmcr` or whatever it's called internally).
- The custom GStreamer playback elements (DSD playback, gapless, DSEE-HX upscaler).
- The UPnP daemon serving `MusicConnect:1` and the iOS-app-facing protocol.
- The library indexer.
- The firmware-update tool.
- The FPGA bitstream.

To recover those, we extract them **from the running device** — `dd` the NAND rootfs over a UART
root shell (see [`10-uart-console.md`](10-uart-console.md)). We deliberately do **not** depend on the
firmware blob, because it is unobtainable (above).

## The realistic acquisition path: NAND dump, not blob unpack

Since the `.SonyAP` blob cannot be downloaded, the green-field opportunity is the **NAND dump**, which
yields the same proprietary pieces (control daemon, GStreamer elements, indexer) as *live files* with
no container to reverse:

1. Get a UART root shell (pinout + procedure: [`10-uart-console.md`](10-uart-console.md)).
2. `cat /proc/mtd` to read the live partition map, then `dd if=/dev/mtdblockN of=…` each partition.
   The rootfs is `/dev/mtdblock2` (writable JFFS2) — mount/extract it off-device.
3. Document findings in `research/notes/` with sizes + SHA-256 for reproducibility.
   **Do not commit dumped proprietary contents.**

**Only if someone ever captures the OTA blob** (e.g. by intercepting a Network Update) does the
classic unpack apply — and even then it may be encrypted/signed:

```bash
binwalk -B HAPZ1ES_19404R.SonyAP            # identify the container
binwalk -e HAPZ1ES_19404R.SonyAP -C out/    # try to extract
```

Look for tar / squashfs / ext / jffs2 / gzip-xz-lzo streams, ELF headers, signature blocks, and
U-Boot legacy image headers (`uImage` magic `0x27051956`). The format is undocumented;
[`ma1co/fwtool.py`](https://github.com/ma1co/fwtool.py) (Sony camera firmware tool, same container
family) is the candidate unpacker. If it's encrypted, the key would have to come from the running
rootfs — i.e. you need the UART shell anyway.

## Partition layout (best current understanding)

- **HDD — confirmed 2026-06-02** (direct disk read, see [`09-disk-layout.md`](09-disk-layout.md)): two ext4 partitions only — `/data` (3 GB, SQLite catalog) and `/mnt/internal` (928 GB, music). **No rootfs, no swap.** The `HAP_Internal` SMB share exposes `/mnt/internal/storage`.
- **On-board flash — derived 2026-06-03 from the GPL `linux-3.0.35` kernel config** (see [`10-uart-console.md`](10-uart-console.md); live `cat /proc/mtd` will confirm offsets):
  - **SPI-NOR = M25P32 (4 MB)** on SPI0/CS1, partitioned `bootloader` (offset 0, 256 KB) + `kernel`.
  - **NAND via Freescale GPMI** holds the **rootfs = `/dev/mtdblock2`, a writable JFFS2** (`root=/dev/mtdblock2 rootfstype=jffs2` in the kernel cmdline; console `ttymxc0,115200`).
  - Predicted MTD map: mtd0 U-Boot (SPI), mtd1 kernel (SPI), **mtd2 rootfs JFFS2 (NAND)**, mtd3+ data.

The exact partition table is confirmed the moment we have shell:

```bash
cat /proc/partitions
cat /proc/mtd  # SPI flash partitions
mount
df -h
```

## Recovery considerations

For Phase 4 (custom userland), the safety net is:

1. **Before flashing anything**, sector-clone the HDD to a spare drive (see [`06-hdd-swap.md`](06-hdd-swap.md) — Procedure A).
2. **Before modifying SPI flash contents**, dump the existing SPI flash via U-Boot serial command or via the SoC's recovery mode (if accessible).
3. **Never** push a flash modification that hasn't been tested under U-Boot bringup-only first.

The HAP has no documented recovery USB stick / recovery partition mechanism. The only way back from a bricked SPI flash is a JTAG re-flash. Plan accordingly.

## Crestron module (a quasi-official protocol artefact)

Crestron sells a control module for the HAP-Z1ES, last updated 2016-07-26:

- <https://applicationmarket.crestron.com/sony-hap-z1es/>

**Obtained and analysed 2026-08-20** (contributed by Amos) — see
[`research/notes/2026-08-20-crestron-module-teardown.md`](../research/notes/2026-08-20-crestron-module-teardown.md).

Its relevance to *firmware* specifically: the Help PDF names the vendor firmware it was written
against, **`0017310R`**. The module is built entirely on the `/sony/contentdb/v100` REST library API,
which on our `19404R` unit is a registered route whose handler never answers — while its sibling
`/sony/contentplayer/v100` still works. A whole library API therefore appears to have been
**withdrawn between `0017310R` and `19404R`**.

That is the first concrete evidence that an older firmware is functionally *richer* than the last
one, and it raises the value of two open questions: whether any `0017310R` image survives anywhere,
and whether the HAP will accept a downgrade. Both are unanswered.

## License note

Sony firmware is Sony's intellectual property. The GPL source bundle (oss.sony.net) is the only part Sony is legally required to release, and it's explicitly licensed under their respective open-source licenses.

**This project does not redistribute Sony firmware blobs or extracted proprietary contents.** Recipes, analysis notes, and the GPL source bundle (which Sony itself publishes) are all fair game. Decompiled proprietary binaries are not.
