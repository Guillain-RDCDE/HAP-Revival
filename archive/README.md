# Archive — preserved technical documents

This directory hosts technical documents we have found referenced across the project — service manuals, user manuals, datasheets — that exist on the web in **a single, fragile location each** (often a third-party mirror).

We've already seen one of these mirrors go offline mid-project: the HAP-S1 service manual that lived at `https://riverparkinc.com/wp-content/uploads/2015/01/HAPS1_SERVICE_MANUAL.pdf` returned **404** when we tested it on 2026-05-26, after being our canonical reference URL for weeks. That mirror disappeared. So has, presumably, knowledge of many similar documents elsewhere over the past decade.

This archive exists to make HAP-Revival itself a durable reference, so the next person trying to revive a HAP a few years from now doesn't hit only dead links.

## What's here

| File | What it is | Source URL (verified 2026-05-26) | Size | SHA-256 |
|---|---|---|---|---|
| `sony-service-manual-hap-z1es.pdf` | **Sony HAP-Z1ES Service Manual** — full schematics, IC list (incl. `IC101 = MCIMX6D5EYM10AC` confirming i.MX6 Dual), PCB layout, JTAG/UART pinout, DIAG mode sequence, audio path block diagram. | `https://elektrotanya.com/sony_hap-z1es.pdf/download.html` | 8.29 MB | `E15F4E6FEA05C0DE70ABB9E6426E3901A8BE8FE4AE5ED85750F8C3A9726F035C` |
| `sony-service-manual-hap-s1.pdf` | **Sony HAP-S1 Service Manual** — same scope as the HAP-Z1ES manual, plus the integrated amplifier section (LM3876 + NJW1194 schematics). Shares most board-level content with the HAP-Z1ES manual. | `https://elektrotanya.com/sony_hap-s1_ver.1.0_hdd_audio_player.pdf/download.html` | 10.44 MB | `F93E7A46D58AC8868EDB7747087B4DDE529B7476BCBE4AE04C0B66D5CFB7DE76` |
| `sony-helpguide-hap-z1es.pdf` | Sony official HAP-Z1ES Help Guide (end-user manual, full English) | `https://helpguide.sony.net/ha/hapz1es/v1/en/print.pdf` | 1.28 MB | `25A9F69C861E7B7EA930C84E3BFD5A185B9D1A74B80CEA5B60D83570EBE90E81` |
| `sony-helpguide-hap-s1.pdf` | Sony official HAP-S1 Help Guide (end-user manual, full English) | `https://helpguide.sony.net/ha/haps1/v1/en/print.pdf` | 1.37 MB | `A66BDEECAA39C1C82F0014130F5028DB6D6DFFD6A51DBFA68D234EC38F0B62F3` |

**Total archive size: ~21 MB.** Well within GitHub's per-file limit (100 MB) and the repo recommended cap (1 GB).

To verify any file matches what we archived:

```powershell
Get-FileHash -Algorithm SHA256 .\archive\sony-service-manual-hap-z1es.pdf
```

## What's not here yet (low-priority)

| Document | Where | Notes |
|---|---|---|
| HAP-S1 Reference Manual | [ManualsLib](https://www.manualslib.com/manual/1076205/Sony-Hap-S1.html) | Mid-level user doc, mostly overlaps with the Help Guide already archived. |
| HAP-S1 Quick Start | [ManualsLib](https://www.manualslib.com/manual/947209/Sony-Hap-S1.html) | Trivial doc. Probably not worth preserving. |
| Sony RM-ANU183 remote manual | (Sony official, multiple regional URLs) | Worth adding if the remote ever becomes part of the reverse-engineering target (it speaks an IR protocol that the U-COM MCU decodes). |

If you want to add any of these or other technical docs we've cited but not yet archived: drop the PDF in this folder, run `Get-FileHash -Algorithm SHA256` on it, and add a row to the table above. PR welcome.

### How to add the service manuals manually

1. Open the source URL in your browser.
2. Download the PDF (Elektrotanya: click the green download button + wait the 10-second timer + click again; ManualsLib: use the "Download" link if available, otherwise screen-scrape via the on-screen reader).
3. Save it into this `archive/` folder with the canonical filename: `sony-service-manual-hap-s1.pdf` or `sony-service-manual-hap-z1es.pdf`.
4. Compute the SHA-256 (PowerShell: `Get-FileHash -Algorithm SHA256 .\file.pdf` ; macOS/Linux: `shasum -a 256 file.pdf`).
5. Add a row to the table at the top of this README.
6. Commit + PR.

## Legal stance

These documents are the intellectual property of their respective copyright holders (Sony Corporation primarily). HAP-Revival hosts them here because:

- The HAP-Z1ES and HAP-S1 are out-of-production hardware (last firmware shipped January 2021, ~5 years ago at time of writing).
- Service manuals for legacy consumer electronics routinely circulate in repair communities and are commonly preserved by archives, museums, and right-to-repair advocacy groups.
- The primary third-party mirrors have proven unreliable — we have first-hand evidence (riverparkinc.com, 2026-05-26) that they disappear without notice, depriving owners of repair / understanding documentation.
- Distribution here is for **interoperability, repair, and historical preservation** purposes only.

**If you are the copyright holder** (Sony Corporation, or its representatives) and would prefer a specific document not be hosted here, please open a private GitHub security advisory or contact the maintainer ([@Guillain-RDCDE](https://github.com/Guillain-RDCDE)) and we will remove it. We won't make you go through DMCA paperwork.

**If you are an end user** wanting to keep these durable: clone or fork this repository. That is exactly the kind of redundant preservation we are trying to enable.

## What is NOT in this archive (and never will be)

- **Sony firmware blobs** (`*.SonyAP`). These are kept off the repo because (a) Sony's regional download pages are still live, so the originals can always be obtained, and (b) the firmware contains proprietary application code that we explicitly don't want to mass-redistribute.
- **Decompiled APK source code**. The recipe to decompile is in [`tools/apk-decompile.md`](../tools/apk-decompile.md). The output is Sony copyrighted Java and stays out of the repo per the project's `.gitignore`.
- **User music libraries** or any personally identifiable data.
