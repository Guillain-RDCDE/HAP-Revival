# NAND dump → rootfs — the off-device extraction pipeline (tested)

[`docs/10-uart-console.md`](10-uart-console.md) gets you a root shell and the raw
flash partitions copied off the HAP. **This page is the second half**: turning
that raw `mtd2.img` (the JFFS2 rootfs) into a browsable directory tree on your
PC — the Python control daemon, the init scripts, the library indexer, the DSP
firmware blobs.

The pipeline below was **validated end-to-end on 2026-06-05** against a synthetic
NAND-like JFFS2 image (128 KiB eraseblock, little-endian) — it round-trips files,
symlinks and the full tree. So the day the dump lands, this is a known-good path,
not an improvisation.

## TL;DR

```bash
# on a Linux box or WSL2, after you've pulled mtd2.img off the HAP:
tools/extract_rootfs.sh mtd2.img
# -> mtd2.img.extracted/  with a summary of the HAP artifacts found
```

## Key gotcha: WSL2 has no MTD subsystem → use jefferson, not mtdram/nandsim

The "textbook" way to read a JFFS2 image is to load it into a simulated MTD
device and mount it:

```bash
sudo modprobe mtdram total_size=… erase_size=128
sudo modprobe mtdblock
sudo dd if=mtd2.img of=/dev/mtdblock0
sudo mount -t jffs2 /dev/mtdblock0 /mnt/rootfs
```

**This does not work on WSL2.** The Microsoft WSL2 kernel ships **no MTD drivers**
(`/lib/modules/$(uname -r)/kernel/drivers/mtd/` doesn't exist — confirmed on
kernel 6.6.87), so `mtdram`/`nandsim`/`mtdblock` can't be loaded. A native Linux
box with a stock distro kernel *can* do the mount route, but it needs root.

So we standardise on **[`jefferson`](https://github.com/onekey-sec/jefferson)** — a
pure-userspace JFFS2 parser. No kernel modules, **no root**, works identically on
WSL2 and native Linux. It handles zlib/RTIME/LZO node compression (the LZO
support comes from the `lzallright` wheel it pulls in).

## Step 1 — get the image off the HAP (recap from docs/10)

At the HAP's root shell (over UART), confirm the map then copy the rootfs out.
**Ready-to-paste** — pick the transport the device supports:

```sh
# On the HAP: confirm which mtd is the JFFS2 rootfs (expect mtd2, root=/dev/mtdblock2)
cat /proc/mtd
cat /proc/cmdline

# (A) over Ethernet with netcat — fastest. PC first:
#     nc -l -p 9000 > mtd2.img
dd if=/dev/mtd2 | nc <PC-IP> 9000

# (B) via the SMB share we can already read/write (no HAP-side net tools):
dd if=/dev/mtd2 of=/mnt/internal/internal/mtd2.img
#   then pull mtd2.img with any SMB client and delete it from the share
```

Grab **mtd2** (the rootfs) at minimum; ideally `dd` **every** partition for a full
backup before you ever write to the NAND. Reading is non-destructive.

> Use `dd if=/dev/mtd2` (the MTD char device), **not** `nanddump`. The char device
> returns ECC-corrected data with the OOB/spare bytes stripped — a clean JFFS2
> image jefferson reads directly. `nanddump --oob` interleaves spare bytes and
> needs an extra de-OOB pass.

## Step 2 — extract on the PC

```bash
# one-time: the script auto-offers to pip-install jefferson (user-level, no root)
tools/extract_rootfs.sh mtd2.img out/
```

What the script does ([`tools/extract_rootfs.sh`](../tools/extract_rootfs.sh)):

1. ensures `jefferson` is on `PATH` (installs via `pip3 install --user` if absent;
   adds `--break-system-packages` automatically on Ubuntu 24.04+/PEP-668),
2. runs `jefferson mtd2.img -d out/`,
3. prints a summary that flags the **Phase-4 levers** in the extracted tree:
   the Python control daemon (`*forza*.py`), the DSP firmware (`*/dspfw/*`), the
   `etc/init.d` scripts, the **dropbear** binary, the lighttpd config, and the
   web.py ScalarWebAPI app.

### Manual equivalent (if you'd rather not use the script)

```bash
pip3 install --user jefferson        # add --break-system-packages on 24.04+
~/.local/bin/jefferson mtd2.img -d out/
ls -R out/
```

### Native-Linux-only alternative (mount, needs root + a stock kernel)

```bash
sudo modprobe mtdram total_size=$(( $(stat -c%s mtd2.img) / 1024 )) erase_size=128
sudo modprobe mtdblock
sudo dd if=mtd2.img of=/dev/mtdblock0
sudo mkdir -p /mnt/rootfs && sudo mount -t jffs2 /dev/mtdblock0 /mnt/rootfs
```

## What we're after in the extracted tree

| Path (expected) | Why it matters |
|---|---|
| the Python control daemon (web.py app under lighttpd) | the JSON-RPC API on :60200 — our reference for the Phase-4 daemon |
| `etc/init.d/*` | boot order; where we add `dropbear` and our daemon |
| dropbear binary + keys | already shipped (see [02-software-stack](02-software-stack.md)); enabling it at boot = persistent SSH root |
| `*/dspfw/*` (`adsp_21488.bin`, the CS48L10 fw) | the DSP firmware loaded over `/dev/forza` — see [15-forza-ioctl.md](15-forza-ioctl.md) |
| the library indexer | how the SQLite catalog ([09-disk-layout](09-disk-layout.md)) is built |
| proprietary GStreamer elements | the playback path we either keep or replace |

The rootfs is **writable JFFS2**, so once we have a shell, changes persist —
enable dropbear at boot, drop in our daemon. **Back up the full NAND first**, and
do not `nand erase`/`nand write` during the dump phase.

## Toolchain provenance (for reproducibility)

- **jefferson 0.4.7** (`pip3 install --user jefferson`; pulls in `dissect.cstruct`
  and `lzallright` for LZO).
- **mtd-utils 2.3.0** (`mkfs.jffs2`) was used only to *build the test fixture*; it
  is not needed to extract. On WSL2 it can be unpacked without root via
  `apt-get download mtd-utils && dpkg-deb -x …` if you want to make your own test
  images.

Related: [UART console](10-uart-console.md) · [audio path](11-audio-path.md) ·
[Forza ioctl reference](15-forza-ioctl.md) · [software stack](02-software-stack.md)
