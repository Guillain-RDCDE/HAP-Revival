# On-device SQLite schemas — ground truth

`.schema` dumps of the **actual databases on a HAP-Z1ES internal disk** (`/data` partition),
extracted 2026-06-02 by reading the disk directly over USB. The authoritative reference for the
HAP's data model.

**Schema only** — table/column/index definitions + row counts as comments. No track data, no
personal library content.

| File | What it is |
|---|---|
| `hdd_browse.schema.sql` | **Start here.** Fully commented; decodes the `PROPxxxx` columns. |
| `master.schema.sql` | The master library — same data, raw property-bag form (no comments). |
| `*_for_disp` | Display-optimized copies. |
| `tunein` · `netradio` · `radiko` · `spotify` · `bivl` | Per-service browse/state DBs. |

This is the same data the network `downloadByDiff` method would serve (still blocked) — reading
the disk got us there directly. DB format `ver 14.00` (from `master.db` `Internals`), all SQLite 3.x.

**Context:** [disk direct-read findings](../notes/2026-06-02-hdd-direct-read-ondisk-findings.md) · [database service & schema](../notes/2026-05-25-database-service-and-db-schema.md).
