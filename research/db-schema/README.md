# On-device SQLite schemas (ground truth)

`.schema` dumps of the actual databases on a HAP-Z1ES internal disk (`/data` partition),
extracted 2026-06-02 by reading the disk directly over USB. See
[`research/notes/2026-06-02-hdd-direct-read-ondisk-findings.md`](../notes/2026-06-02-hdd-direct-read-ondisk-findings.md).

These are **schema only** (table/column/index definitions + row counts as comments) — no track
data, no personal library content. They are the authoritative reference for the HAP's data model:

- `hdd_browse.schema.sql` — **start here.** Fully commented; decodes the `PROPxxxx` columns.
- `master.schema.sql` — the master library; same data, raw property-bag form (no comments).
- `*_for_disp` — display-optimized copies.
- `tunein / netradio / radiko / spotify / bivl` — per-service browse/state DBs.

This is the same data the network `downloadByDiff` method would serve (still blocked — see [`../notes/2026-05-25-database-service-and-db-schema.md`](../notes/2026-05-25-database-service-and-db-schema.md)); reading the disk got us there directly.

DB format version is `ver 14.00` (from `master.db` `Internals`). All SQLite 3.x.
