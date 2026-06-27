# Manuals — preserved technical documents

Service manuals, help guides and datasheets that exist on the web in **a single, fragile mirror
each.** We mirror them here so HAP-Revival itself is a durable reference — the next person
reviving a HAP years from now shouldn't hit only dead links.

> This isn't hypothetical: the HAP-S1 service manual that lived at `riverparkinc.com` was our
> canonical reference for weeks, then returned **404** on 2026-05-26. That mirror is gone.

## What's here

| File | What it is | Source (verified 2026-05-26) | Size |
|---|---|---|---|
| `sony-service-manual-hap-z1es.pdf` | **HAP-Z1ES Service Manual** — schematics, IC list (`IC101 = MCIMX6D5EYM10AC`, i.MX6 Dual), PCB layout, JTAG/UART pinout, DIAG sequence, audio block diagram | [elektrotanya.com](https://elektrotanya.com/sony_hap-z1es.pdf/download.html) | 8.29 MB |
| `sony-service-manual-hap-s1.pdf` | **HAP-S1 Service Manual** — same scope, plus the integrated amp section (LM3876 + NJW1194) | [elektrotanya.com](https://elektrotanya.com/sony_hap-s1_ver.1.0_hdd_audio_player.pdf/download.html) | 10.44 MB |
| `sony-helpguide-hap-z1es.pdf` | Official HAP-Z1ES Help Guide (end-user, full English) | [helpguide.sony.net](https://helpguide.sony.net/ha/hapz1es/v1/en/print.pdf) | 1.28 MB |
| `sony-helpguide-hap-s1.pdf` | Official HAP-S1 Help Guide (end-user, full English) | [helpguide.sony.net](https://helpguide.sony.net/ha/haps1/v1/en/print.pdf) | 1.37 MB |

**SHA-256** (verification of record):

```text
hap-z1es service   E15F4E6FEA05C0DE70ABB9E6426E3901A8BE8FE4AE5ED85750F8C3A9726F035C
hap-s1   service   F93E7A46D58AC8868EDB7747087B4DDE529B7476BCBE4AE04C0B66D5CFB7DE76
hap-z1es helpguide 25A9F69C861E7B7EA930C84E3BFD5A185B9D1A74B80CEA5B60D83570EBE90E81
hap-s1   helpguide A66BDEECAA39C1C82F0014130F5028DB6D6DFFD6A51DBFA68D234EC38F0B62F3
```

Verify a file with:

```powershell
Get-FileHash -Algorithm SHA256 .\docs\manuals\sony-service-manual-hap-z1es.pdf
```

**Want these to survive?** Clone or fork the repo. That redundant preservation is exactly the point.

## Adding a manual

Drop the PDF in this folder with its canonical name (e.g. `sony-service-manual-hap-s1.pdf`), then:

```powershell
Get-FileHash -Algorithm SHA256 .\file.pdf      # macOS/Linux: shasum -a 256 file.pdf
```

Add a row to the table above and open a PR. *(Elektrotanya: green button → 10 s timer → click again. ManualsLib: use the Download link, else screen-scrape the on-screen reader.)*

**Still wanted (low priority):** HAP-S1 Reference Manual & Quick Start ([ManualsLib](https://www.manualslib.com/manual/1076205/Sony-Hap-S1.html) — mostly overlaps the Help Guide) · Sony RM-ANU183 remote manual (worth it only if the IR remote becomes a reverse-engineering target).

## What is NOT here (and never will be)

- **Sony firmware blobs** (`*.SonyAP`) — proprietary app code, and **OTA-only** anyway: the device fetches it from `info.update.sony.net`, the regional pages expose no blob, and no public copy exists. We couldn't redistribute it if we wanted to. ([recon notes](../../research/notes/2026-06-03-os-acquisition-recon.md) §1)
- **Decompiled APK source** — Sony copyrighted Java, stays out per `.gitignore`. The recipe lives in [`tools/apk-decompile.md`](../../tools/apk-decompile.md).
- **User music libraries** or any personal data.

## Legal stance

These documents are the IP of their copyright holders (primarily Sony Corporation). We host them
for **interoperability, repair, and historical preservation** of out-of-production hardware (last
firmware January 2021) — the way repair communities and archives routinely preserve legacy
service manuals, especially when the only third-party mirrors keep disappearing.

**If you are the copyright holder** and would prefer a document not be hosted here, open a private
GitHub security advisory or contact [@Guillain-RDCDE](https://github.com/Guillain-RDCDE) — we'll
remove it, no DMCA paperwork needed.
