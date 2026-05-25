# HDD / SSD swap recipe

Years of Japanese audiophile blogs have rigorously validated this procedure. **The internal disk can be safely replaced** with another HDD or with an SSD, with full preservation of the device's behavior.

## Key insight: U-Boot + kernel are on SPI flash, not the HDD

This is the load-bearing fact. The Sony service manual and multiple HDD-swap experiments confirm:

- **The bootloader (U-Boot) and Linux kernel live on a small SPI flash chip soldered to the main board.**
- The HDD stores: the rootfs (or at least the writable part of it), the music library, the Tokyo Cabinet metadata DB, the user settings, and the log files.

Consequence: **swapping the HDD cannot brick the bootloader**. The device will always boot up to the point of trying to mount the HDD. If the HDD is empty or unrecognizable, the firmware drops into a factory-reset / initial-setup flow that rebuilds the rootfs from scratch. Confirmed by multiple JP community swaps.

## Compatibility list (community-validated)

| Drive | Result | Source |
|---|---|---|
| Samsung 850 EVO 1 TB | ✅ works after factory reset | [briareos hatena 2016-02](https://briareos.hatenablog.jp/entry/20160201/p1) |
| Samsung 860 EVO 1 TB | ✅ works after sector clone via KURO-DACHI | [emuzu cocolog 2019-10](https://emuzu-2.cocolog-nifty.com/blog/2019/10/post-57c506.html) |
| Samsung 860 EVO 1 TB | ✅ works after factory reset (no clone) | [saionjihouse 2021-06](https://saionjihouse.com/2021/06/27/) |
| Samsung 870 EVO | ⚠️ **triggers scan loops + copy errors** | [kakaku SortID=24642226](https://bbs.kakaku.com/bbs/K0000579959/SortID=24642226/) |
| Samsung 860 PRO | ⚠️ same as 870 EVO | [kakaku SortID=24642226](https://bbs.kakaku.com/bbs/K0000579959/SortID=24642226/) |
| **Crucial MX500** | ✅ works reliably | [kakaku SortID=24642226](https://bbs.kakaku.com/bbs/K0000579959/SortID=24642226/) |
| **KIOXIA SSD** | ✅ works reliably | [kakaku SortID=24642226](https://bbs.kakaku.com/bbs/K0000579959/SortID=24642226/) |
| 2 TB SSD (with alu heatsink) | ✅ — 2 TB is the **maximum** | [aku_ari rakuten 2021-09](https://plaza.rakuten.co.jp/akuari/diary/202109230002/) |
| Seagate ST2000LM003 2 TB HDD | ✅ works in HAP-S1 (9.5 mm) | [Head-Fi #801939](https://www.head-fi.org/threads/sony-hap-s1.801939/) |

**Recommendations**:
- **Best choice 2026**: Crucial MX500 1 TB or 2 TB. Validated, widely available, reasonable price.
- **Avoid**: Samsung 870/860 EVO and 860 PRO (unexplained vendor-specific incompatibility, likely related to firmware ID strings or TRIM behavior).
- **Maximum internal size**: 2 TB. The firmware uses MBR partitioning. Larger drives are recognized by the SATA controller but only the first 2 TB is addressable.
- **For >2 TB**: use the USB external port. The user's HAP-Z1ES is currently playing from `storage:usb1`, confirmed working with at least 4 TB external drives.

## Two valid procedures

### Procedure A: sector-by-sector clone (preserves DB, settings, ratings)

Best if your existing HDD still works and you want zero data loss.

1. Power down the HAP.
2. Remove the original HDD (see service manual for screws).
3. Use a **hardware sector cloner** (KURO-DACHI/CLONE/U3 confirmed; any "duplicator" or "clone" dock that does bit-for-bit copy works). **Do not use a file-level copy tool** — community evidence is unambiguous that file-level clones do not work, presumably due to MBR/partition-table specifics or Tokyo Cabinet DB layout.
4. Install the cloned drive in the HAP.
5. Power on. The device should behave identically to before, including all your tags, playlists, and library edits.

### Procedure B: blank drive + factory reset (loses metadata edits)

Best if your original HDD is dead, or you don't care about preserved settings.

1. Power down. Install the new blank drive.
2. Power on. The device detects no valid filesystem and enters factory-reset mode.
3. The firmware partitions and formats the new drive, recreates the system directories.
4. You then need to re-transfer your music via SMB. The library is rebuilt from scratch as files arrive.
5. **Metadata edits made via the HAP Audio Remote app are lost** — only filesystem-stored tags survive (those embedded in FLAC/MP3 files themselves).

## Why use an SSD at all?

In an audiophile context the rational answers are:

- **Silence**: no platter noise, no head seek noise. The HAP-Z1ES already has a quiet fan, the HDD is the loudest component.
- **Reliability**: HDDs in 24/7 service degrade. SSDs at light write loads (a music library is read-heavy, write-rare) last effectively forever.
- **Heat**: less heat → less fan activity → quieter device.

There is **no audible improvement** from an SSD in this device — the audio path is entirely buffered through RAM and isolated from the disk subsystem by the FPGA + DSP + DAC chain. Anyone who tells you a "high-end audiophile SSD" sounds better than a Crucial MX500 is mistaken. The audio system is so deliberately decoupled from the disk that swapping the disk vendor cannot affect the analog output.

## Physical procedure

The HAP-Z1ES service manual covers disassembly in detail. Summary:

1. Remove top cover screws.
2. Remove the HDD bracket (~4 screws).
3. Disconnect the SATA data + power cables.
4. The HDD bracket has rubber damping mounts — keep them.

Some users (saionjihouse) report **removing the fan entirely** when fitting an SSD, since the SSD doesn't need cooling and the fan was sized for HDD heat. The thermal monitoring may still expect a fan and produce warnings — verify before committing to fan removal.

## Adding a larger drive in the field

If you want >1 TB internal, the cleanest path is:

1. Buy a Crucial MX500 2 TB.
2. Sector-clone your existing 1 TB to it with a KURO-DACHI dock.
3. Install the cloned 2 TB drive.
4. Boot the HAP. It should immediately work and show 1 TB free space (the cloned partition is still 1 TB).
5. Either: live with the 1 TB partition until you want more space, OR: from the front panel, run a factory reset that re-partitions to use the full 2 TB. Step 5b loses your library so it's only attractive when you have backups.

## Safety nets

- **Always keep your original HDD as a recovery image.** Don't reuse it for anything until you've validated the new drive runs your HAP normally for at least a week.
- **Document the original partition layout** before swapping — `fdisk -l /dev/sd<X>` on the original drive read from a Linux box gives the partition table. The HAP currently uses MBR, not GPT, despite gptfdisk being in the GPL bundle.
- **Take photos** of the disassembly so reassembly goes faster.
