# SMB file transfer

How music gets onto the HAP.

## The shares

The HAP-Z1ES / HAP-S1 Samba 3.0.37 server exposes three shares, all accessible **without authentication**:

| Share | Backing | Purpose |
|---|---|---|
| `HAP_Internal` | the 1 TB internal HDD | Music storage — drop files here, the library auto-indexes |
| `HAP_External` | a USB-attached drive, if any | Optional external library |
| `IPC$` | (standard SMB) | Inter-process — not directly useful |

```bash
# From any SMB1-capable client on the same LAN:
smbclient -L //<hap-ip> -U "" -N
```

## The SMB version trap

By default the HAP server only speaks **SMB1 / NT1** — the original 1980s SMB dialect, removed from modern OS defaults for security reasons.

| Client OS | Default behavior |
|---|---|
| Windows 10/11 | SMB1 is **not installed by default** since 1709. Add via "Turn Windows features on or off" → "SMB 1.0/CIFS File Sharing Support" |
| macOS High Sierra (10.13)+ | SMB1 **removed entirely**. The official Sony "HAP Music Transfer" Mac app no longer works |
| Linux (smbclient, libsmbclient) | `--option=client min protocol=NT1 --option=client max protocol=NT1` |

**Workaround on the device side**: firmware 18777R (released ~2018) introduced a hidden **Special Mode** menu (see [`05-diag-modes.md`](05-diag-modes.md)) where the SMB version can be raised to anything from 1.0 to 3.1.1. **If you do nothing else, do this** — flip it to 3.0 or higher and you regain modern OS compatibility instantly.

## Library auto-indexing

**Files dropped on the SMB share are auto-indexed within seconds** — no API call is required to trigger a rescan.

Verified by the [HAPxFer](https://github.com/danielrweber/HAPxFer) project and consistent with the behavior of the Sony Music Transfer app. The indexer is presumably watching the share via inotify on the corresponding Linux mount.

Implication for Phase 2: a third-party transfer tool only needs to write to the share. No follow-up "refresh library" call. Big workflow simplification.

## Accepted file formats

From the [HAPxFer source](https://github.com/danielrweber/HAPxFer):

- **DSD**: DSF and DFF (2.8 MHz / 5.6 MHz)
- **Lossless PCM**: FLAC, WAV, AIFF, ALAC (Apple Lossless)
- **Lossy**: MP3, AAC/M4A, WMA, ATRAC

ATRAC is a Sony-only lossless/lossy codec — supported here for legacy MiniDisc/Walkman library compatibility. Don't expect anyone outside Sony to ship music in ATRAC.

## File layout conventions

The HAP indexer expects (or at least handles best) the standard `<Artist>/<Album>/<Track>.flac` layout. The [outmyth/music-organizer](https://github.com/outmyth/music-organizer) Python tool encodes these conventions if you want to bulk-prepare a library before transfer.

## Cover art

The indexer picks up `cover.jpg` / `folder.jpg` / `front.jpg` in album directories. Embedded cover art in FLAC/MP3/etc. is also extracted.

The cover art served by the JSON-RPC API (see [`03-network-api.md`](03-network-api.md)) goes through an opaque ID — there's no public mapping from album ID to cover art ID yet.

## Wake-on-LAN

The HAP supports WoL on Ethernet. Sending a magic packet to the Ethernet MAC will wake it from network standby. HAPxFer does this automatically before a transfer.

## What does NOT work

- **SFTP**: no SSH daemon is started by default (despite Dropbear being built into the firmware).
- **WebDAV**: not exposed.
- **NFS**: `unfs3` is in the GPL bundle, suggesting it's installed, but no NFS port is open in factory firmware.
- **FTP**: closed.

SMB is your only way to push files in factory configuration.

## Future direction

Once we have root shell:

1. **Enable Dropbear SSH** in `/etc/init.d/` → SCP/SFTP file transfer over SSH.
2. **Upgrade Samba** from 3.0.37 to a current release — fixes a decade of known CVEs and gives proper SMB3 + encryption by default.
3. **Add a modern WebDAV endpoint** as an alternative for clients that hate SMB.
4. **Expose a JSON-RPC `pushFile` method** for the future iOS app so users never see SMB at all.
