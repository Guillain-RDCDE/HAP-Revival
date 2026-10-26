**Download `HapSync.exe` below.** No install, no Python, no admin rights — double-click it.
Already on 0.4.0? It offers this release in its footer: one click and it is done.

HAP Sync copies your music to a Sony HAP-Z1ES or HAP-S1 in one click. This release lets the same
click keep your backup disks up to date too, so the player and its copies never need a second
sync tool.

### What's new in HAP Sync since `hap-sync-v0.4.0`

- **Backup disks in the same run.** A line's target box now offers **Local folder** next to the
  two HAP shares: pick a destination (a second disk, a third, as many lines as you like) and the
  sync copies there too. The HAP lines always run first; the copies follow. A copy carries every
  format (only junk is left out), notices a re-tag even when the byte size did not change, keeps
  the files' dates, and never leaves a half-written file behind if it is interrupted.
- **You choose what happens to files you removed from the source**, line by line:
  *Never delete* (the default), *List extras* (shown in the analysis, nothing deleted) or
  *Exact mirror* (deleted, along with the folders left empty). A mirror holds its deletions back
  when the source is empty or when they would remove more than half of the copy — far more often
  a wrong or unplugged source than a real clean-up — and says so in the analysis.
- **One clear message when the USB disk is not mounted.** A USB disk plugged into the HAP after it
  started is only shared once you confirm a prompt on the player's **front screen**. Until then
  every upload to `HAP_External` used to fail on its own, with an SMB dump each time. HAP Sync now
  checks each share before uploading and tells you, once, what to do.
- Two lines feeding the same share no longer lose each other's uploads from the cache.

### And in the rest of the repository

- `hap_sync.py` takes the same local copies from `hap_sync.json` (`"dest"` in place of `"share"`,
  plus `"delete": "keep" | "list" | "mirror"`), and `sync --allow-mass-delete` lets a held-back
  mirror through once you have checked. See the
  [music guide](https://github.com/Guillain-RDCDE/HAP-Revival/blob/main/docs/12-music-sync.md).
- `hap_notify` no longer stops listening on Windows right after subscribing.

Full list in the
[CHANGELOG](https://github.com/Guillain-RDCDE/HAP-Revival/blob/main/CHANGELOG.md).

SHA-256 of `HapSync.exe`: `{{SHA256}}`

### Getting started

1. Download `HapSync.exe`, put it anywhere, double-click it.
   First launch: SmartScreen → *More info → Run anyway* (not code-signed yet).
2. Hit **Find** — it discovers the HAP on your LAN (and wakes it if it's asleep).
3. Point one or two folders at the internal disk and the USB share, add a backup line if you
   like, **Analyse**, then **Sync**.

Coming from 0.3.0 or earlier? Those versions cannot check for updates, so replace the file by hand
this once; later releases offer themselves.

Never touched this before? Read [Start Here](https://github.com/Guillain-RDCDE/HAP-Revival/blob/main/docs/START-HERE.md) — five minutes, no jargon.
