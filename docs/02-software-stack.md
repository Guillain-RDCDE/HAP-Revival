# Software stack

Everything Sony loaded onto the HAP-Z1ES / HAP-S1, derived from the published [Sony GPL source release](https://oss.sony.net/Products/Linux/Audio/HAP-S1.html) (mandatory under GPL terms) and from observed banners on a live device.

## Build system / base distribution

- **OpenWrt** trunk r35385 (snapshot circa 2013).
- This makes the HAP a slightly customized OpenWrt device. Most of the conventions (`/etc/init.d/`, UCI configuration, `opkg` package management) should be familiar to anyone who has worked with router firmware.

## Bootloader and kernel

- **U-Boot 2012.04.01** with Sony patches. Lives on an SoC-side SPI flash chip (not on the HDD).
- **Linux 3.0.35** with Sony patches and Freescale BSP. Released 2012, vintage Freescale i.MX6 kernel.
- Both kernel and U-Boot sources are in the [oss.sony.net GPL bundle](https://oss.sony.net/Products/Linux/Audio/HAP-S1.html), including the patch files.

## Userland packages (extracted from GPL release)

| Category | Package | Version | Notes |
|---|---|---|---|
| Init system | OpenWrt `procd` + `netifd` + `ubus` + `uci` + `libubox` | 2012-12-20 era | Standard OpenWrt boot |
| Core utils | `busybox` | 1.19.4 | |
| Device manager | `udev` | 173 | |
| File sharing | `samba` | **3.0.37** | SMBv1 by default, switchable up to 3.1.1 via Special Mode (firmware ≥18777R) |
| SSH | `dropbear` | 2012.55 | **Built into firmware but not started by default** — key lever for getting root |
| HTTP server | `lighttpd` | 1.4.35 | Serves both port 60100 (UPnP description) and port 60200 (JSON-RPC API) |
| DNS / DHCP | `dnsmasq` | 2.62 | |
| Bluetooth | `bluez` | 3.36 | Bluetooth A2DP receiver mode |
| Package manager | `opkg` | (snapshot) | OpenWrt's package manager |
| Audio framework | `alsa-lib` + `alsa-utils` | 1.0.24.x | |
| Audio codecs | `FLAC` 1.2.1, `libvorbis` 1.2.3 | | |
| Playback engine | `gstreamer` + base/good/bad/ugly/python | **0.10.36** | Obsolete since ~2013 (GStreamer 1.x is current) |
| Freescale GStreamer | `gst-fsl-plugins` | 3.0.5 | i.MX6 hardware acceleration |
| Freescale userland | `imx-lib` | 12.08.00 | i.MX6 vendor library |
| File-share over NFS | `unfs3` | | NFS server (purpose unclear — possibly internal use only) |
| Disk partitioning | `gptfdisk` | | |
| Scripting | `python` | **2.7.3** | The control daemon runs on this |
| Web framework | `web.py` | 0.37 | Powers the JSON-RPC daemon |
| OSC | `pyOSC` | | Likely used for internal IPC between Python daemon and GStreamer |
| Database (1) | `sqlite` | 3.27 | |
| Database (2) | `tokyocabinet` | 1.4.47 | Music library metadata |
| Metadata reader | `libmediainfo` | 0.7.81 | Music file tag extraction |
| Front-panel UI | `DirectFB` | 1.4.17 | Direct framebuffer GUI (no X11) |
| IPC | `dbus` | 1.4.14 | |
| Crypto | `openssl` | 1.0.2u | |

## The Sony-custom pieces

These are not in the GPL bundle (because they're either proprietary or trade secrets). The codename across all of them is **"forza"** (Italian: *force*).

- **`forza_snd_driver`** — the custom ALSA kernel module that glues GStreamer to the FPGA + SHARC + PCM1795 chain. Sony's GPL obligation **does** cover this (it's a kernel module, GPL-derived), and the source IS in the bundle. **Reading this is the entry point for understanding the audio path programming.**
- **`hapmcr`** (inferred name) — the control daemon binary running on Python 2.7 + web.py + lighttpd, exposing the JSON-RPC API on port 60200. Not in the GPL bundle. Closed.
- **The GStreamer playback elements** that handle DSD playback, gapless transitions, the DSEE-HX upscaler, and the proprietary HAP-format decoder. Not in the GPL bundle.
- **The UPnP daemon** serving `MusicConnect:1` and the iOS-app-facing protocol. Not in the GPL bundle.
- **The library indexer** that parses incoming files dropped on the SMB share, extracts metadata via libmediainfo, builds the Tokyo Cabinet database. Not in the GPL bundle.
- **The HAP firmware-update tool** that consumes the `.SonyAP` blob. Not in the GPL bundle.
- **The FPGA bitstream**. Not in the GPL bundle (and would be irrelevant in source form — it's already compiled to FPGA logic).

## Audio path data flow (best current understanding)

```text
   Music file (FLAC/DSF/WAV/etc.)
            │
            │ SMB1 PUT to HAP_Internal share
            ▼
   /mnt/internal/Music/<artist>/<album>/file.flac
            │
            │ indexer scans, writes Tokyo Cabinet DB
            ▼
   /mnt/internal/.hap/library.tch (inferred path)
            │
            │ Playback request via JSON-RPC or front panel
            ▼
   Python control daemon (web.py on lighttpd)
            │
            │ DBus / OSC / direct call?
            ▼
   GStreamer pipeline (filesrc → flacdec → forza_snd_sink)
            │
            │ Sony Forza ALSA driver
            ▼
   I²S → FPGA → SHARC → 2× PCM1795 → analog out
```

The Python daemon does the orchestration; GStreamer does the decoding; the Forza driver hands samples to the FPGA; the FPGA handles clock recovery and routes to the SHARC + DACs. The DSEE-HX upsampling and DSD remastering likely happen inside the SHARC, not in GStreamer.

## Implications for the modernization plan

- **The control plane is editable without recompiling C**. Python + web.py on lighttpd means: get a shell, edit a .py file, restart lighttpd, ship a new feature. This is enormously favorable for Phase 4 — we don't need to rebuild a kernel module to add Tidal support.
- **GStreamer 0.10 is dead**. To integrate modern streaming (librespot, Tidal SDK, Roon endpoint), we'll likely need to either backport elements or run a parallel GStreamer 1.x stack alongside the original, or replace the playback engine entirely with MPD. Each option preserves the Forza driver, which is the part that matters for sound quality.
- **The init system is OpenWrt-standard**. Enabling Dropbear SSH at boot is a one-line edit in `/etc/init.d/` once we have shell. Same for adding our own daemon.
- **Samba 3.0.37 is ancient and vulnerable**. Anyone running their HAP on a network with untrusted devices should already worry. Upgrading Samba is a Phase 3 deliverable.
- **DirectFB UI on the front panel** means we can theoretically replace the on-device UI without driving a separate display server.

## Open questions

1. Where exactly is the rootfs stored — entirely on the SPI flash, on a dedicated HDD partition, or split? (Community evidence from HDD swap experiments suggests U-Boot + kernel on SPI flash, rootfs + apps on HDD — but unconfirmed.)
2. How is GStreamer driven by the Python daemon — via DBus, via OSC (hence the `pyOSC` package), or via direct subprocess?
3. What's in `/etc/inittab` or the OpenWrt `procd` boot sequence?
4. Are there cron jobs that periodically scan the SMB share or check for firmware updates?

All answered the moment we have UART shell.
