# Diagnostic and Special Modes

The HAP-Z1ES / HAP-S1 has two undocumented (for end users) modes accessible via front-panel key combinations. Both are entered with the device in standby.

## DIAG Mode (the factory service menu)

**Entry sequence** (per Sony service manual, page 25, and confirmed on [electro-medical.blogspot.com](https://electro-medical.blogspot.com)):

1. Put the device in **standby**.
2. Hold **HOME** + **BACK** simultaneously.
3. Still holding both, press **PLAY**.
4. Then press **POWER**.

That's a **4-key combo**, not the 2-key one widely (mis)reported.

The LCD switches to a numeric menu. Navigate with the rotary encoder.

### DIAG menu contents

| # | Item | Use |
|---|---|---|
| 1 | Version Info | Firmware version + build metadata |
| 2 | LED / KEY Check | Test every button and indicator LED |
| 3 | LCD Test | Color bar + backlight brightness |
| 4 | RTC | Real-time clock |
| 5 | Fan Speed Control | Override the fan curve manually |
| 6 | HDD SMART Short (2 min) | Quick disk health check |
| 7 | HDD SMART Long (2–4 h) | Full disk surface scan |
| 8 | Audio Playback Test | Internal audio path verification |
| 9 | Network | Wi-Fi + Ethernet diagnostics |
| 10 | QUIT | Exit |

**Exit**: select QUIT, or press POWER (except during a SMART test, which will complete first).

### Safety

DIAG mode is **read-only / diagnostic only**. There is no documented option in it to erase user data, flash firmware, or otherwise modify the device. Safe to explore.

### What we want to learn from it but haven't yet

- The "Network" diagnostic may dump useful info (IP, MAC, gateway, link speed) on the LCD — worth photographing.
- The "Audio Playback Test" may reveal which test files are stored in the firmware and how they're routed — possibly useful for understanding the audio pipeline.
- The "Version Info" output may include the bootloader version and a build date precise enough to cross-reference with the GPL release.

If you have a HAP, photograph each DIAG submenu and submit the photos via the [hardware-finding issue template](../.github/ISSUE_TEMPLATE/hardware-finding.yml).

## Special Mode (the SMB version selector)

Introduced in firmware **18777R** (mid-2018) to let users on modern OSes (which no longer support SMB1) keep using the HAP.

**Entry sequence**:

1. Device in **standby**.
2. Hold **HOME**, then press **POWER**.

A simpler menu appears with two documented options:

- **SMB Version**: 1.0, 2.0, 2.1, 3.0, 3.0.2, **3.1.1** (default in latest firmware)
- **Restart**

Behavior: setting SMB Version then choosing Restart applies the change. **If you do nothing else with this menu, flip the SMB version up** — Windows 11 and modern macOS will start working with the HAP without disabling client-side security.

### Possible other entries

The existence of a hidden menu structure strongly suggests Sony added other gated options across firmware revisions. We do not know what's there beyond the two documented entries. **Photograph anything else you see** in Special Mode and report it.

#### Reported: a firmware downgrade entry (Amos, 2026-08-21 — unverified)

> *"You can downgrade your firmware to the previous version if you hold down home and push power to
> turn it on while still holding down home. I forget what the menu option is but it's pretty
> self-explanatory."*

That entry sequence is exactly the Special Mode combo above, on firmware `0019404R`. If it is real,
it is the "other gated option" this section has been asking about since the page was written, and it
matters a lot: **firmware `0017310R` served the `/sony/contentdb/v100` library API that 19404R has
withdrawn** (see [`08-prior-art.md`](08-prior-art.md) §6 and the
[teardown note](../research/notes/2026-08-20-crestron-module-teardown.md)). A downgrade would turn
that inference into a live, testable API.

**Treat as unconfirmed.** The reporter says himself he does not remember the menu wording, and our
own documentation of this menu lists only *SMB Version* and *Restart*. Either the entry is there and
we simply never enumerated it, or it belongs to the 4-key DIAG menu, or the recollection is off.
**Photograph the menu before acting on it.**

##### Before anyone downgrades

Unlike everything else on this page, a downgrade is a **firmware write**, and it leaves the
risk-free part of the roadmap:

- The HAP has no documented recovery mechanism. Per [`07-firmware.md`](07-firmware.md), *"the only
  way back from a bricked SPI flash is a JTAG re-flash."*
- Sony has shipped nothing since January 2021 and the units are long out of production.
- We do not know whether "downgrade" rolls back to an image already held in NAND or re-fetches one
  over the network — and that distinction decides whether there is anything to capture at all.

There is also a cheaper way to want the same thing. If the OTA URL turns out to carry the version
string, older images may be downloadable straight from Sony's CDN with no downgrade and no risk —
see [`07-firmware.md`](07-firmware.md). **Capture an update check first; gamble a machine last.**

## Why this matters for HAP-Revival

These menus are the **only official sanctioned way to change device behavior without flashing firmware**. If we can find an undocumented entry that, say, enables Dropbear SSH or exposes a developer mode, the entire Phase 3 (root shell) becomes a 30-second exercise instead of a UART probing project.

We don't know if such an entry exists. But we haven't checked exhaustively either.

## Power-off shortcuts (bonus, not strictly DIAG)

- **Force restart** if the unit hangs: hold POWER for ~10 seconds.
- **Network standby toggle**: in the Settings menu, not these special modes. Enable it for Wake-on-LAN to work.

## References

- HAP-S1 Service Manual, page 25 — preserved as [`manuals/sony-service-manual-hap-s1.pdf`](manuals/sony-service-manual-hap-s1.pdf). Live mirrors: [Elektrotanya](https://elektrotanya.com/sony_hap-s1_ver.1.0_hdd_audio_player.pdf/download.html), [ManualsLib](https://www.manualslib.com/manual/893329/Sony-Hap-S1.html). (The previously-cited `riverparkinc.com` mirror went 404 on 2026-05-26 — exactly the kind of link-rot the archive exists to insulate us from.)
- [electro-medical.blogspot.com](https://electro-medical.blogspot.com) — JP-language hobbyist walkthrough
- [Sony Asia support page documenting Special Mode for SMB](https://www.sony-asia.com/electronics/support/audio-components-hdd-audio-network-audio-players/hap-z1es/software/00279155)
