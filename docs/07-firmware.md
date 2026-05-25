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

## Download URLs

Sony hosts each firmware on regional support pages. The pages are JavaScript-gated; there is no clean CDN URL for direct scripted download.

- **UK**: <https://www.sony.co.uk/electronics/support/audio-components-hdd-audio-network-audio-players/hap-z1es/downloads/00017123>
- **Asia**: <https://www.sony-asia.com/electronics/support/downloads/00017124>
- **Canada**: <https://www.sony.ca/en/electronics/support/audio-components-hdd-audio-network-audio-players/hap-z1es/downloads/00017125>

To download: visit one of the pages in a real browser, accept the terms, and grab the blob. **Do not commit the blob to this repository** — it is Sony copyrighted material. The download URL is fine to share.

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

To recover those, we have to extract them from the firmware blob — see below.

## Firmware blob analysis (the green-field opportunity)

**Nobody has publicly documented**:

- The file format / container of the `.SonyAP` blob.
- Whether it's encrypted or signed.
- Whether older firmware versions (18444R) used a simpler / less hardened format than 19404R.
- The diff between two firmware versions (would reveal exactly what Sony changed in each release).

Recipe for the first contributor to attempt:

1. Download 19404R (and one or two older versions) via a real browser from the Sony URLs above.
2. Run `binwalk` (or `binwalk -e` to extract):

   ```bash
   binwalk -B HAPZ1ES_19404R.SonyAP
   binwalk -e HAPZ1ES_19404R.SonyAP -C extracted/
   ```

3. Look for: tar magic, squashfs magic, ext2/3/4 magic, gzip / xz / bzip2 / lzo / lz4 streams, ELF headers, certificate / signature blocks, U-Boot legacy image headers (`uImage` magic `0x27051956`).
4. Diff the older + newer firmware byte-for-byte at offsets that look like metadata to identify version markers and any update mechanism.
5. **Do not commit the raw blob or its extracted contents.** Document findings in a markdown note under `research/notes/firmware-format-analysis.md`. Reference the file size and SHA-256 of what you analyzed for reproducibility.

If the format turns out to be encrypted, that's still useful information — it tells us the next step is to dump the decryption key from the running rootfs (which requires UART shell).

## Partition layout (best current understanding)

Unverified — pending UART shell or firmware extraction:

- **SPI flash** (small, soldered to main board): U-Boot, kernel, possibly an early initramfs.
- **HDD**: rootfs (likely a Linux ext3 or ext4 partition), music library partition, swap?
- **Music library** is what `HAP_Internal` SMB share exposes.

The exact partition table can be obtained the moment we have shell:

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

The module ships with a Help PDF documenting the TCP/IP command set Crestron uses. Access requires a Crestron account; we have not yet obtained or analyzed this PDF. If you have access, the PDF is the closest thing to an official Sony protocol document that exists in 2026.

## License note

Sony firmware is Sony's intellectual property. The GPL source bundle (oss.sony.net) is the only part Sony is legally required to release, and it's explicitly licensed under their respective open-source licenses.

**This project does not redistribute Sony firmware blobs or extracted proprietary contents.** Recipes, analysis notes, and the GPL source bundle (which Sony itself publishes) are all fair game. Decompiled proprietary binaries are not.
