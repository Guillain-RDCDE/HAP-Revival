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

## Why this matters for HAP-Revival

These menus are the **only official sanctioned way to change device behavior without flashing firmware**. If we can find an undocumented entry that, say, enables Dropbear SSH or exposes a developer mode, the entire Phase 3 (root shell) becomes a 30-second exercise instead of a UART probing project.

We don't know if such an entry exists. But we haven't checked exhaustively either.

## Power-off shortcuts (bonus, not strictly DIAG)

- **Force restart** if the unit hangs: hold POWER for ~10 seconds.
- **Network standby toggle**: in the Settings menu, not these special modes. Enable it for Wake-on-LAN to work.

## References

- HAP-S1 Service Manual, page 25. Sources: [`archive/`](../archive/) for the preserved copy if it has been contributed there; [Elektrotanya](https://elektrotanya.com/sony_hap-s1_ver.1.0_hdd_audio_player.pdf/download.html) or [ManualsLib](https://www.manualslib.com/manual/893329/Sony-Hap-S1.html) as live mirrors. (The previously-cited `riverparkinc.com` mirror went 404 on 2026-05-26 — exactly the kind of link-rot the archive exists to insulate us from.)
- [electro-medical.blogspot.com](https://electro-medical.blogspot.com) — JP-language hobbyist walkthrough
- [Sony Asia support page documenting Special Mode for SMB](https://www.sony-asia.com/electronics/support/audio-components-hdd-audio-network-audio-players/hap-z1es/software/00279155)
