# The audio path — how the HAP actually makes sound

This is the part Sony built the device for, and the part **we never touch**. It's also the most
interesting subsystem to understand, because it's where the "ES-grade" sound comes from. Everything
here is read from the GPL `forza_snd_driver` source (the one Sony-custom kernel module Sony was
obliged to publish) — so unlike the proprietary daemon, the audio engine is **open and legible**.

## For newcomers: the one-paragraph version

When you press play, the Linux SoC does **not** push audio out of a normal sound chip. Instead it
DMA's the samples over a **PCIe link into a custom Sony FPGA**. From there the signal is handled
entirely by dedicated silicon: two audio **DSPs** (an Analog Devices SHARC and a Cirrus chip) do the
optional "make it sound better" processing (upscaling, oversampling, DSD remastering), the FPGA owns
the master **clock**, and the cleaned-up stream is clocked out to **two Burr-Brown PCM1795 DACs**
(one per channel) and then to the analog outputs. The Linux side never touches the sample timing —
that isolation is the whole point, and it's why swapping the disk or the OS can't hurt the sound.

## The chain (data flow)

```text
  GStreamer (i.MX6, Linux)
        │  ALSA: card "Forza_FPGA", format S32_LE, 8k–192 kHz   (+ a separate DSD PCM device)
        ▼
  Forza ALSA driver  ──► PCIe DMA (512 KB buffer) ──►  Altera FPGA  (PCI 0x1172:0xE001)
        │                                                  │  on-chip FIFO (8K/16K/32K by rate)
        │                                                  │  owns the master clock domain
        │                            ┌─────────────────────┼─────────────────────┐
        │                            ▼                     ▼                     ▼
        │                   CS48L10 ("cdsp")      ADSP-21488 (SHARC)     DSD Remastering
        │                   oversampling / SRC    "HEQ" restoration      Direct.PCM / Direct.DSD
        │                   (4up/2up/non firmware) + digital filter      / DSD_ReMaster.PCM
        │                            └─────────────────────┼─────────────────────┘
        │                                                  ▼
        │                                          I²S, master-clocked
        ▼                                                  ▼
  (control via /dev/forza ioctls)               2× PCM1795 (mono mode, FIR_1/FIR_2)
                                                           ▼
                                                   Analog L / R out
```

## The FPGA is a PCIe device

The "Forza" FPGA is an **Altera** part (PCI vendor `0x1172`, device `0xE001`) on the i.MX6's **PCI
Express** bus — confirmed by `snd_forza_ids[]` in `forza.c`. The driver (`MODULE_DESCRIPTION("SONY
ANAP PCI")`) is a standard ALSA + PCI driver: it maps the FPGA's BARs, sets up scatter/gather PCIe
DMA into the FPGA's FIFO, and registers two ALSA PCM devices — one **PCM**, one **native DSD**.

- ALSA hardware caps (`forza_pcm.c`): **`S32_LE`** sample format, **`8000–192000 Hz` continuous**
  (a `…_384000` line is present but commented out — this build tops out at 192 kHz on the PCM path).
- A board-select module param **`fmode`**: `a` = "Allegro", `s` = "**Spiritoso**" (the HAP-Z1ES main-board
  codename from the service manual). Same driver, two board variants (HAP-S1 vs HAP-Z1ES).

## The two DSPs, decoded

This is the headline finding from the source — what each DSP actually *does*, and how it maps to the
sound settings you see in the app. Both load firmware from the rootfs at **`/sony/lib/modules/dspfw/`**.

### ADSP-21488 (SHARC) — "HEQ" restoration + digital filter

Firmware: `/sony/lib/modules/dspfw/adsp_21488.bin`. Its command set (`adsp_21488.h`) is built around
**HEQ** — Sony's harmonic restoration, i.e. the **DSEE-HX** family that rebuilds the high end lost to
lossy compression. It is **per-codec**, which is exactly how DSEE-HX works:

- `HEQ_EFFECT_MODE`: OFF / **LPCM / MP3 / AAC / WMA / ATRAC3 / ATRACX** — a restoration profile per source codec.
- `HEQ run mode`: NORMAL / DISABLE / **IMPROVED**.
- **Digital filter** select: `FILTER_MODE_NORMAL` vs `FILTER_MODE_HI_PRE` (a slow/sharp-roll-off choice).
- Operates on PCM at 44.1–384 kHz, 16/20/24/32-bit (`ADSP_SAMPLE_RATE_*`, `ADSP_BIT_*`).

→ **The app's "DSEE (auto/off)" toggle drives this SHARC HEQ block.**

### CS48L10 ("cdsp") — oversampling / sample-rate conversion

Firmware: a multi-stage boot — `cdsp_48L10_1_os.bin` (OS), `cdsp_48L10_2_cfg.bin` (config), then one
of three **pre-processing SRC** images chosen by input rate (`cdsp_cs48l10.c`):

- `cdsp_48L10_3_pre_4upSRC.bin` — 4× upsampling (default, `CONFIG_FILENAME = CONFIG_4UPSRC`)
- `cdsp_48L10_3_pre_2upSRC.bin` — 2× upsampling
- `cdsp_48L10_3_pre_nonSRC.bin` — no SRC

→ **The app's "Oversampling (precision/normal)" setting selects between these SRC firmwares.** The
CS48L10 has its own boot handshake (`SLAVE_BOOT`, `KICKSTART`, soft-boot) and a checksum-verified
firmware download.

### DSD Remastering engine

`forza_audio_controller.c` switches between three signal modes:

- **Direct.PCM** — PCM straight through to the DACs.
- **Direct.DSD** — native DSD bitstream to the DACs (the dedicated DSD PCM device).
- **DSD_ReMaster.PCM** — PCM (or DSD) **remastered to DSD** before the DAC — Sony's "DSD Remastering
  Engine", which converts everything to a DSD stream the PCM1795 plays natively.

→ **The app's "DSD remastering (on/off)" toggle picks Direct vs DSD_ReMaster.**

### The DACs (PCM1795)

DAC command set (`forza_if.h` `DAC_CTRL_ACCESS_CMD`): INIT / RESET / DEFAULT / MUTE / **PCM** / **DSD**
/ **DIR** / **FIR**. Two PCM1795 run in **mono mode** (one per channel) with selectable FIR filters
(`PCM1795_DSD_FIR_1` / `FIR_2`; the "ET" sound mode uses FIR_1). `FORZA_DAC = DAC_PCM1795`.

## The control interface — `/dev/forza` (this is the lever for Phase 4)

Everything above is driven from userspace through a single char device, **`/dev/forza`**, via `ioctl`
(magic `0xDF`). This is **how a replacement daemon would drive the audio chain while preserving Sony's
analog path** — we keep this kernel module + the DSP firmware, and speak to it exactly as Sony's
proprietary daemon does.

> **Full decoded contract:** every sub-command, field semantic, enum and a
> Phase-4 bring-up sequence is in **[docs/15-forza-ioctl.md](15-forza-ioctl.md)** —
> the per-command reference traced arm-by-arm from the driver source. The table
> below is the summary.

The interface (`export/forza_if.h`):

```c
// ioctl(fd, FORZA_IOCTL_{API,DSP,DAC}_SET, &st);
struct ioctl_struct { int cmd, key, val, mode, rate, fs, bit; };
```

| ioctl | Command enum | Purpose |
|---|---|---|
| `FORZA_IOCTL_API_SET` | `API_ACCESS_CMD` | top-level: INIT, RESET, MUTE, INPUT, S_PCM, **HEQ**, HEQ_PARAM, **FADE**, FORMAT, **ATT** (attenuation), FORMATTER, LED |
| `FORZA_IOCTL_DSP_SET` | `DSP_CTRL_ACCESS_CMD` | DSP: INIT, RESET, **FWDL** (firmware download), MUTE, STATUS, FORMATS, REG_WRITE, FILTER, **RELOAD**, RECOVER |
| `FORZA_IOCTL_DAC_SET` | `DAC_CTRL_ACCESS_CMD` | DAC: INIT, RESET, DEFAULT, MUTE, **PCM**, **DSD**, DIR, **FIR** |

The fade/attenuation primitives here are why the front-panel volume and the fade-in/out feature exist
even though the HAP-Z1ES has no analog volume stage — they're applied in the digital domain before the
DAC.

> Note: `FORZA_DSP` is compiled `DEVICE_DISABLE` in the GPL build's `forza_defs.h`, yet the DSEE /
> oversampling features clearly ship. So the DSP path is enabled/orchestrated at runtime (by the
> proprietary daemon via these ioctls + firmware download), not hard-wired on at compile time — worth
> confirming once we have the rootfs.

## Why this matters for modernization

- **Phase 4 keeps this whole subsystem.** Replacing the proprietary playback daemon with MPD +
  streaming bridges only requires that the replacement feed the same ALSA device and issue the same
  `/dev/forza` ioctls for DSEE / oversampling / DSD-remaster / filter. The analog magic is untouched.
- **The DSP firmware blobs live on the rootfs** (`/sony/lib/modules/dspfw/`), so a NAND dump
  (see [`10-uart-console.md`](10-uart-console.md)) will give us the `.bin` images — needed if we ever
  rebuild or relocate the rootfs.
- It confirms the hardware story in [`01-hardware.md`](01-hardware.md): Altera FPGA over PCIe,
  ADSP-21488 SHARC, Cirrus CS48L10, dual PCM1795 mono.

## Source map (`forza_snd_driver`, GPL)

| File | Role |
|---|---|
| `forza.c` | module/PCI/ALSA registration; creates PCM + DSD devices |
| `forza_core.c` | card creation, FPGA setup, DMA init |
| `forza_pcm.c` | ALSA PCM ops (S32_LE, 8k–192k), DMA ring, interrupts |
| `forza_audio_controller.c` | the Direct / DSD-Remaster mode state machine |
| `forza_hwlow.c/.h` | low-level FPGA register access (BARs, FIFO, clock, oversampling) |
| `adsp_21488.c/.h` | SHARC: HEQ (DSEE-HX) restoration, formats, digital filter |
| `cdsp_cs48l10.c/.h` | Cirrus DSP: oversampling/SRC, multi-stage firmware boot |
| `dsp_ops.c` | shared DSP register read/write helpers |
| `forza_lib.c` | misc helpers, build-info banner |
| `export/forza_if.h` | the `/dev/forza` userspace ioctl ABI |
