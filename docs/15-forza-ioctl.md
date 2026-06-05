# `/dev/forza` — the ioctl programming reference

This is the **userspace lever for the whole analog chain.** Everything Sony's
playback daemon does to the FPGA, the DSP and the DACs — mute, HEQ/DSEE,
PCM↔DSD, sample-rate/format changes, DAC filter selection — it does through
`ioctl()` calls on the character device **`/dev/forza`**. A Phase-4 custom
userland that keeps Sony's audio path ([docs/11-audio-path.md](11-audio-path.md))
**must speak this interface**; this page is its decoded contract.

Decoded from the GPL `forza_snd_driver` source for firmware 19404R
(`export/forza_if.h` = the public ABI; `forza_core.c` = the dispatcher;
`dsp_ops.c` / `forza_audio_controller.c` = the per-command behaviour). Nothing
here is guessed — every field semantic below is traced to a `switch` arm in the
driver.

## The device and the call pattern

```c
#include "forza_if.h"          /* from the GPL bundle: forza/export/forza_if.h */
#include <fcntl.h>
#include <sys/ioctl.h>

int fd = open("/dev/forza", O_RDWR);
struct ioctl_struct st = {0};
st.cmd = FORZA_API_MUTE;       /* which sub-command (see tables below)        */
st.val = FORZA_ENA;            /* its argument                                */
ioctl(fd, FORZA_IOCTL_API_SET, &st);
close(fd);
```

`/dev/forza` is created by the driver at probe (major auto-assigned,
`class=forza`). `open`/`release` are no-ops; there is no `read`/`write` — the
device is **ioctl-only**.

## The four request codes

The driver registers exactly four ioctl request numbers, magic **`0xDF`**:

| Macro | `_IOC` nr | `st.cmd` enum it selects | Purpose |
|---|---|---|---|
| `FORZA_IOCTL_DSET`    | 0 | (none — reads a bare `int`) | debug: prints the int, no effect |
| `FORZA_IOCTL_API_SET` | 1 | `API_ACCESS_CMD`            | **the main control surface** (mute, HEQ, fade, format, input routing…) |
| `FORZA_IOCTL_DSP_SET` | 2 | `DSP_CTRL_ACCESS_CMD`       | DSP lifecycle (init/reset/firmware-download/filter/version) |
| `FORZA_IOCTL_DAC_SET` | 3 | `DAC_CTRL_ACCESS_CMD`       | DAC (PCM1795) init/reset/default/FIR selection |

```c
#define FORZA_IOCTL_MAGIC   0xDF
#define FORZA_IOCTL_API_SET _IOC(_IOC_WRITE, 0xDF, 1, sizeof(int))
/* …DSP_SET nr=2, DAC_SET nr=3, DSET nr=0 — all _IOC_WRITE */
```

> **Implementer gotcha — the encoded size is nominal.** The `_IOC(...)` macros
> encode `sizeof(int)` (4) as the size, but for API/DSP/DAC the driver does
> `copy_from_user(&st, arg, sizeof(struct ioctl_struct))` — it copies the **full
> 7-int struct (28 bytes)** regardless. So `arg` must always point at a complete
> `struct ioctl_struct`, never a bare `int`. (Only `FORZA_IOCTL_DSET` reads a
> bare int, via `get_user`.)
>
> **It's write-only.** Every handler is `copy_from_user` only — the driver never
> `copy_to_user`s anything back. Commands that "read" (DSP version, status) emit
> their result to the **kernel log** (`dmesg`), not into your struct. Plan to
> scrape `dmesg` for those, or extend the driver.

## `struct ioctl_struct` — the argument block

```c
struct ioctl_struct {
  int cmd;    /* sub-command: an API_/DSP_/DAC_ enum value (see tables)        */
  int key;    /* secondary selector: register offset, fader channel, att ch.  */
  int val;    /* primary argument: on/off, mode, reset phase, FIR number…     */
  int mode;   /* (reserved in this rev — not read by any handler)             */
  int rate;   /* sample-rate hint for format ops                             */
  int fs;     /* sample rate (Fs) for format / reload                        */
  int bit;    /* bit depth (e.g. 24) for format ops                          */
};
```

Which fields a command actually reads is listed per-command below. Unused fields
are ignored; zero-init the struct and set only what the command needs.

## Command set 1 — `FORZA_IOCTL_API_SET` (`st.cmd` = `API_ACCESS_CMD`)

The day-to-day control surface. Source: the `FORZA_IOCTL_API_SET` switch in
`forza_core.c`.

| `st.cmd` | value | reads | Effect (from the driver) |
|---|---|---|---|
| `FORZA_API_INIT`        | 0  | — | no-op in this rev |
| `FORZA_API_RESET`       | 1  | — | no-op in this rev |
| `FORZA_API_MUTE`        | 2  | `val` | `val=FORZA_ENA`(1) → DAC output **off** (mute assert); `val=FORZA_DIS`(2) → DAC output **on** |
| `FORZA_API_INPUT`       | 3  | `val` | DAC input routing: `FORZA_DAC_PCM`(4)→DAC default 'p'; `FORZA_DAC_DSD`(5)→DAC default 'd'; `FORZA_DAC_DIR`(6)→'p' + output enable |
| `FORZA_API_SMUTE`       | 4  | `val` | soft-mute via `audio_ops->lmute`: `ENA`(1)→on, `DIS`(2)→off |
| `FORZA_API_S_PCM`       | 5  | `val` | PCM passthrough: `ENA`(1)→PCM→PCM **direct** (bypass DSD); `DIS`(2)→PCM→DSD (default) |
| `FORZA_API_HEQ`         | 10 | `val` | **DSEE-HX / HEQ run mode** → `dsp_ops->heq`. `val`=`FORZA_HEQ_RUN_*` (see enum) |
| `FORZA_API_HEQ_PARAM`   | 11 | `val`(+params) | push HEQ coefficient params → `dsp_ops->heq_params` |
| `FORZA_API_FADE`        | 12 | `val` | fader on/off → `audio_ops->set_fader(val)` |
| `FORZA_API_FADE_PARAM`  | 13 | `key`,`val` | fader params → `audio_ops->set_fader_val(key, val)` |
| `FORZA_API_FORMAT`      | 14 | `fs`,`bit`,`rate` | set stream format on the DSP → `dsp_ops->formats` (Fs + bit depth) |
| `FORZA_API_ATT`         | 15 | `key`,`val` | attenuation per channel → `audio_ops->att(key, val)` |
| `FORZA_API_FORMATTER`   | 80 | `val` | FPGA formatter enable (inverted): `ENA`(1)→formatter **off**; `DIS`(2)→**on** |
| `FORZA_API_HEQ_CONTROL` | 97 | `val` | master HEQ gate: stores `heq_control`. `0`=force HEQ off globally, `1`=allow |
| `FORZA_API_DEBUG_TEST`  | 98 | (struct) | debug test pattern → `audio_ops->debug_test` |
| `FORZA_API_DEBUG_LED`   | 99 | `val` | front VU/LED debug mode → `audio_ops->debug_led` (`DEBUG_LED_MODE` enum) |

Note the **inversions**: `FORZA_API_MUTE` uses `ENA=mute`, and `FORZA_API_FORMATTER`
maps `ENA→disable`. These are quirks of the source — the table above is
authoritative, not the constant names.

## Command set 2 — `FORZA_IOCTL_DSP_SET` (`st.cmd` = `DSP_CTRL_ACCESS_CMD`)

DSP lifecycle. Each arm calls `forza->dsp_ops-><op>`, and **`dsp_ops` is chosen
per hardware model** (see "Two DSP back-ends" below). Most arms log `st.key` and
`st.val`.

| `st.cmd` | value | reads | Effect |
|---|---|---|---|
| `FORZA_DSP_INIT`      | 0  | `val` | host-interface enable. `val=1`→HOST↔DSP; `val=2`→host detach (DSP↔flash) |
| `FORZA_DSP_RESET`     | 1  | `val` | `val=2`→assert reset; `val=1`→release; else→full reset cycle |
| `FORZA_DSP_FWDL`      | 2  | `val` | **download DSP firmware** (`adsp_21488.bin` / CS48L10 blob) over SPI |
| `FORZA_DSP_MUTE`      | 3  | `val` | DSP-side mute: `val=1`→mute, `val=2`→unmute |
| `FORZA_DSP_STATUS`    | 4  | — | read DSP/FIFO status → `dmesg`; also clears the FPGA FIFO |
| `FORZA_DSP_FORMATS`   | 5  | `fs`,`bit` | program DSP for the current PCM/DSD format |
| `FORZA_DSP_REG_WRITE` | 6  | `key`,`val` | write DSP reg at base+`key` (`key`≤0x20) = `val` |
| `FORZA_DSP_VERSION`   | 7  | — | read DSP firmware version → `dmesg` |
| `FORZA_DSP_REMOVE`    | 8  | — | teardown / log status |
| `FORZA_DSP_FWDL_FLAG` | 9  | `val` | set "full firmware download" flag (0/1) for the next format change |
| `FORZA_DSP_FILTER`    | 10 | `val` | digital-filter mode (SHARC only): `HEQ_FILTER_NORMAL`/`HEQ_FILTER_HI_PRE` |
| `FORZA_DSP_RECOVER`   | 11 | — | force DSP recovery (re-init→reset→fwdl sequence) |
| `FORZA_DSP_RELOAD`    | 12 | — | reload firmware at the current Fs (`cur_st.crate`) |

## Command set 3 — `FORZA_IOCTL_DAC_SET` (`st.cmd` = `DAC_CTRL_ACCESS_CMD`)

Direct PCM1795 control. (Routing between PCM/DSD/DIR is normally done via
`FORZA_API_INPUT` above; the only DAC arms the dispatcher actually implements
are:)

| `st.cmd` | value | reads | Effect |
|---|---|---|---|
| `FORZA_DAC_INIT`    | 0 | — | `dac_ops->init` — initialise both PCM1795s |
| `FORZA_DAC_RESET`   | 1 | `val` | `val=ENA`(1)→assert DAC reset; else→release |
| `FORZA_DAC_DEFAULT` | 2 | — | reload the DAC default register set for `chip->fmode` |
| `FORZA_DAC_FIR`     | 7 | `val` | **DSD FIR filter select**: `1..4` → `PCM1795_DSD_FIR_1..4` (out-of-range logged) |

`FORZA_DAC_MUTE`/`FORZA_DAC_PCM`/`FORZA_DAC_DSD`/`FORZA_DAC_DIR` (3–6) exist in the
enum but are **not** handled in the `FORZA_IOCTL_DAC_SET` switch — those paths are
driven through `FORZA_API_INPUT`/`FORZA_API_MUTE` instead.

## Enums you'll need

```c
/* HEQ / DSEE-HX run mode — st.val for FORZA_API_HEQ */
FORZA_HEQ_RUN_NORMAL   = 1   /* DSEE-HX on, normal      */
FORZA_HEQ_RUN_DISABLE  = 2   /* off (bit-perfect)       */
FORZA_HEQ_RUN_IMPROVED = 3   /* DSEE-HX on, "improved"  */

/* Digital filter shape — st.val for FORZA_DSP_FILTER (SHARC/Spiritoso only) */
HEQ_FILTER_NORMAL = 0
HEQ_FILTER_HI_PRE = 1        /* "high-precision" / sharper rolloff */

/* DAC input route — st.val for FORZA_API_INPUT */
FORZA_DAC_PCM = 4   FORZA_DAC_DSD = 5   FORZA_DAC_DIR = 6

/* generic enable/disable — st.val for MUTE/SMUTE/S_PCM/FORMATTER */
FORZA_ENA = 1   FORZA_DIS = 2

/* front-panel LED debug — st.val for FORZA_API_DEBUG_LED */
FORZA_DEBUG_LED_FIFO=0  FORZA_DEBUG_LED_VU=1  FORZA_DEBUG_LED_DEMO=2  FORZA_DEBUG_LED_CPU=3
```

The user-facing settings in our web UI map onto these: **DSEE auto/off** →
`FORZA_API_HEQ` (`RUN_NORMAL`/`RUN_IMPROVED` vs `RUN_DISABLE`); **oversampling
precision/normal** → `FORZA_DSP_FILTER` (`HI_PRE`/`NORMAL`); **DSD remastering** →
`FORZA_API_S_PCM` / `FORZA_API_INPUT` PCM↔DSD.

## Two DSP back-ends — model-selected (`chip->fmode`)

`dsp_hw_create()` binds `chip->dsp_ops` to **one** of two op-sets based on the
board model passed at probe:

| `fmode` | Board codename | `dsp_ops` → | HEQ/DSEE DSP it drives |
|---|---|---|---|
| `'s'` | **Spiritoso** (= the **HAP-Z1ES** MAIN board, per [docs/10](10-uart-console.md)) | `adsp_ops` | **Analog Devices ADSP-21488 SHARC** |
| `'a'` | **Allegro** | `cdsp_ops` | **Cirrus Logic CS48L10** |

So on the **Z1ES**, the `FORZA_IOCTL_DSP_SET` and `FORZA_API_HEQ`/`FORMAT`/`FILTER`
commands talk to the **SHARC** (`adsp_21488.*`); the Allegro variant routes the
same commands to the CS48L10 (`cdsp_cs48l10.*`). Two consequences for Phase 4:

- `FORZA_DSP_FILTER` (`HI_PRE`) is a **real** SHARC operation on the Z1ES, but on
  Allegro `cdsp_hw_filter` is a logged no-op ("NORMAL only").
- The firmware blob downloaded by `FORZA_DSP_FWDL` differs per model
  (`adsp_21488.bin` vs the CS48L10 image) — both live under
  `/sony/lib/modules/dspfw/` on the rootfs (recover them via
  [docs/14-nand-extract.md](14-nand-extract.md)).

## A minimal "keep the analog chain" sequence (Phase 4 sketch)

The driver itself shows the canonical bring-up order (`snd_forza_create`,
`cdsp_hw_recovery`). For a custom daemon, starting playback of a 24-bit/96 kHz
PCM stream reduces to roughly:

```c
ioctl(fd, FORZA_IOCTL_DSP_SET, &(struct ioctl_struct){.cmd=FORZA_DSP_RESET, .val=2}); /* assert  */
ioctl(fd, FORZA_IOCTL_DSP_SET, &(struct ioctl_struct){.cmd=FORZA_DSP_RESET, .val=1}); /* release */
ioctl(fd, FORZA_IOCTL_DSP_SET, &(struct ioctl_struct){.cmd=FORZA_DSP_INIT,  .val=1}); /* host on */
ioctl(fd, FORZA_IOCTL_DSP_SET, &(struct ioctl_struct){.cmd=FORZA_DSP_FWDL,  .val=1}); /* load fw */
ioctl(fd, FORZA_IOCTL_API_SET, &(struct ioctl_struct){.cmd=FORZA_API_INPUT, .val=FORZA_DAC_PCM});
ioctl(fd, FORZA_IOCTL_API_SET, &(struct ioctl_struct){.cmd=FORZA_API_FORMAT, .fs=96000, .bit=24});
ioctl(fd, FORZA_IOCTL_API_SET, &(struct ioctl_struct){.cmd=FORZA_API_HEQ,   .val=FORZA_HEQ_RUN_DISABLE}); /* bit-perfect */
ioctl(fd, FORZA_IOCTL_API_SET, &(struct ioctl_struct){.cmd=FORZA_API_MUTE,  .val=FORZA_DIS});            /* unmute */
/* …then stream PCM frames into the ALSA PCM device the driver exposes */
```

The actual audio frames still flow through the ALSA/GStreamer PCM path (the FPGA
DMA over PCIe described in [docs/11](11-audio-path.md)); these ioctls only
**configure** the FPGA/DSP/DAC around that stream. Exact ordering/timing
(`udelay`s between steps) should follow `forza_audio_controller.c`.

## Caveats

- Derived from the **19404R GPL drop**; field meanings could differ in other
  firmware revisions. Verify against the on-device `forza.ko` once we have the
  NAND dump.
- The `mode` struct field is unread in this revision — reserved.
- `_IOC_WRITE` direction + no `copy_to_user` means **read-back is via `dmesg`
  only** (`FORZA_DSP_VERSION`, `FORZA_DSP_STATUS`). A Phase-4 fork could add
  `copy_to_user` to surface these to userspace cleanly.

Related: [audio path](11-audio-path.md) · [NAND extraction](14-nand-extract.md) ·
[software stack](02-software-stack.md) · [hardware](01-hardware.md)
