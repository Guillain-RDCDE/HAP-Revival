**Download `HapSync.exe` below.** No install, no Python, no admin rights — double-click it.

HAP Sync copies your music to a Sony HAP-Z1ES or HAP-S1 in one click. This release is the last one
you download by hand: **from now on it tells you when a newer version exists, and installs it in one
click.**

### What's new in HAP Sync since `hap-sync-v0.3.0`

- **It updates itself.** The version is in the footer. When a newer release exists, an **Update to
  X.Y.Z** button appears next to it: one click downloads the new `HapSync.exe`, checks its SHA-256
  against the one GitHub publishes, swaps the files and starts the new version. A **Help** menu
  checks on demand and shows *About*. Set `HAP_NO_UPDATE_CHECK=1` to never ask.
- **Every word in your language.** The log lines, status line and dialogs that stayed English
  whatever language was chosen now follow it, in all six.
- **Built by CI from this tag**, so the file you download is exactly the published sources.

### And in the rest of the repository

These run from Python (stdlib only) and work on any computer on the same network as the player:

- **The web remote shows a banner when a newer release exists**, with the same one-click update
  from the computer that runs it (it restarts by itself), a *What's new* link from a phone, and
  *About / Check for updates* under the gear.
- **Every command-line tool answers `--version`** and, on a terminal, ends a run with one line when a
  newer release is known. `python tools/hap_update.py apply` updates a clone or a downloaded folder.
- **One definition of every fact about the player.** Ports, shares, playable formats, the catalogue
  schema and the JSON-RPC envelope each live in one shared module; the tools no longer carry copies
  that drift apart (two had).
- **The mock player is a full test bench**: push notifications with real UDP datagrams, the
  contentplayer REST surface, TuneIn, the front panel, and the two documented gotchas. The suite
  drives every tool and the sync window against it: 645 tests, no hardware needed.

Full list in the
[CHANGELOG](https://github.com/Guillain-RDCDE/HAP-Revival/blob/main/CHANGELOG.md).

### Getting started

1. Download `HapSync.exe`, put it anywhere, double-click it.
   First launch: SmartScreen → *More info → Run anyway* (not code-signed yet).
2. Hit **Find** — it discovers the HAP on your LAN (and wakes it if it's asleep).
3. Point one or two folders at the internal disk and the USB share, **Analyse**, then **Sync**.

Coming from 0.3.0 or earlier? Those versions cannot check for updates, so replace the file by hand
this once; the next release will offer itself.

Never touched this before? Read [Start Here](https://github.com/Guillain-RDCDE/HAP-Revival/blob/main/docs/START-HERE.md) — five minutes, no jargon.

Own a HAP and want to help? [Help in five minutes](https://github.com/Guillain-RDCDE/HAP-Revival/blob/main/docs/HELP-IN-5-MINUTES.md) —
copy-paste, read-only, nothing to install.

---

**Verify your download** — SHA-256 of `HapSync.exe` (also in `SHA256SUMS.txt` below):

```text
{{SHA256}}
```

Windows x64 · built by CI from the sources at this tag · nothing here can damage your device.
