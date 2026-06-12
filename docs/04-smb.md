# SMB file transfer

How music gets onto the HAP.

## The shares

The HAP-Z1ES / HAP-S1 Samba 3.0.37 server exposes three shares, all accessible **anonymously** —
and anonymous access is **read *and* write**, not read-only (confirmed by enumeration, 2026-06-03):

| Share | On-disk path | Purpose |
|---|---|---|
| `HAP_Internal` | `/mnt/internal/internal` → music under `/mnt/internal/storage/<Artist>/<Album>/` | Music storage — drop files here, the library auto-indexes |
| `HAP_External` | `/mnt/external_fuse` (a USB-attached drive, via FUSE) | Optional external library |
| `IPC$` | `/tmp` | Inter-process — not directly useful |

The internal HDD is **not** a monolithic music disk: it has two ext4 partitions, `/mnt/internal`
(music, exposed here) and a separate `/data` (the SQLite catalog). The OS is on internal NAND, not
the HDD. Full picture: [`09-disk-layout.md`](09-disk-layout.md).

```bash
# From any SMB1-capable client on the same LAN (force NT1 — the device only speaks SMB1):
smbclient -L //<hap-ip> -N --option='client min protocol=NT1' --option='client max protocol=NT1'
```

## Security boundary (what the SMB surface does and doesn't expose)

This is the device's biggest stock-firmware exposure, so it's worth stating precisely (and it
records attack vectors already tried, so nobody re-burns the hours):

- **Anonymous read + write** to the music shares is open to anyone on the LAN. (Useful for a future
  direct-to-share bulk loader; also a real exposure on an untrusted network — see [`SECURITY.md`](../.github/SECURITY.md).)
- **Escaping the share to the rootfs is blocked.** The classic Samba symlink / `wide links`
  traversal (create a symlink to `/`, read the filesystem) returns `NT_STATUS_ACCESS_DENIED` on
  every attempt (absolute and relative targets, both shares) — Sony hardened this.
- **HTTP path traversal is also blocked** on lighttpd (`:60100`/`:60200`), including raw `../` and
  `%2e%2f` encodings — all `404`.
- **No remote-code-execution shortcut on Samba 3.0.37/ARM**: it predates SambaCry (CVE-2017-7494,
  needs ≥3.5.0) and the `usermap_script` bug (≤3.0.25); no reliable public ARM exploit.

Net: SMB gets you files in/out of the music area, but **not** a path to the OS. That is why the
OS-acquisition route is the UART console / NAND dump, not the network — see [`10-uart-console.md`](10-uart-console.md).

## The SMB version trap

By default the HAP server only speaks **SMB1 / NT1** — the original 1980s SMB dialect, removed from modern OS defaults for security reasons.

| Client OS | Default behavior |
|---|---|
| Windows 10/11 | SMB1 is **not installed by default** since 1709. Add via "Turn Windows features on or off" → "SMB 1.0/CIFS File Sharing Support" |
| macOS High Sierra (10.13)+ | SMB1 **removed entirely**. The official Sony "HAP Music Transfer" Mac app no longer works |
| Linux (smbclient, libsmbclient) | `--option=client min protocol=NT1 --option=client max protocol=NT1` |

**Workaround on the device side**: firmware 18777R (released ~2018) introduced a hidden **Special Mode** menu (see [`05-diag-modes.md`](05-diag-modes.md)) where the SMB version can be raised to anything from 1.0 to 3.1.1. **If you do nothing else, do this** — flip it to 3.0 or higher and you regain modern OS compatibility instantly.

## Windows updates keep re-breaking access — the client-side fixes

The device-side Special Mode flip above is the durable fix. But many users leave the HAP on its SMB1
default, and then **every few Windows updates the connection breaks again** — because Microsoft keeps
hardening the SMB *client*. Typical symptoms: the share suddenly demands a username/password that
*doesn't exist* (there is no account — access is anonymous), or you get
*"You can't access this shared folder because your organization's security policies block
unauthenticated guest access."* **Nothing changed on the HAP** — a Windows update just tightened a default.

> **Don't want to do this by hand?** HAP Sync automates the whole section. Click **Check** to
> diagnose, then **Fix Windows access** to repair every problem below in one UAC prompt
> (`tools/smb_doctor.py` — also available as `python tools/hap_sync.py check --fix`). The rest of
> this section is the manual equivalent, and the reference for what those buttons actually do.

There are four independent knobs, and any single update can flip one of them. Open an **elevated**
PowerShell (right-click Start → *Terminal (Admin)*) and apply what's needed:

| Cause (which update default bit you) | Check | Fix (elevated PowerShell) |
|---|---|---|
| **SMB signing now required** — Win11 24H2/25H2 made this the default. Samba 3.0.37 can't sign, so the connection is refused, usually surfacing as a credential prompt. | `Get-SmbClientConfiguration \| Select RequireSecuritySignature` | `Set-SmbClientConfiguration -RequireSecuritySignature $false -Force` |
| **Insecure guest logons disabled** — gives the *"...security policies block unauthenticated guest access"* error. | `Get-SmbClientConfiguration \| Select EnableInsecureGuestLogons` | `Set-SmbClientConfiguration -EnableInsecureGuestLogons $true -Force` |
| Same, but the Group Policy toggle didn't write the registry value (a known quirk). | `AllowInsecureGuestAuth` under `...\LanmanWorkstation\Parameters` | `Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters' AllowInsecureGuestAuth 1` |
| **SMB1 client feature removed** by the update. | `Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol-Client \| Select State` | `Enable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol-Client` *(reboot)* |

None of these need a reboot **except** re-adding the SMB1 feature.

### The stale-mapping gotcha

Even once the knobs above are correct, a **persistent mapped drive** (e.g. `Y:` → `\\<hap-ip>\HAP_Internal`)
created under the old config can stay stuck *"Disconnected / Unavailable"* and keep forcing a credential
prompt — Windows retries the broken cached session before attempting a fresh guest logon. Drop it and
reconnect clean:

```powershell
net use * /delete /y                            # drop all stale mappings
net use \\<hap-ip>\HAP_Internal /user:guest ""  # fresh guest session, blank password
# optional — re-map a drive letter that survives reboots:
net use Y: \\<hap-ip>\HAP_Internal /user:guest "" /persistent:yes
```

### Want to stop fighting Windows entirely?

Two escape hatches that sidestep the whole treadmill:

1. **Flip the device to SMB3** via Special Mode ([`05-diag-modes.md`](05-diag-modes.md)) — Windows then
   talks to it like any modern NAS and none of the above applies.
2. **Use [`tools/hap_sync.py`](../tools/hap_sync.py)**, which speaks SMB1 directly via `pysmb` in user
   space. It bypasses the Windows SMB stack completely: no feature toggles, no signing/guest knobs, no
   admin rights — see [`12-music-sync.md`](12-music-sync.md).

## Library auto-indexing

**Files dropped on the SMB share are auto-indexed within seconds** — no API call is required to trigger a rescan.

Verified by the [HAPxFer](https://github.com/danielrweber/HAPxFer) project and consistent with the behavior of the Sony Music Transfer app. The indexer is presumably watching the share via inotify on the corresponding Linux mount.

Implication for Phase 2: a third-party transfer tool only needs to write to the share. No follow-up "refresh library" call. Big workflow simplification. **Implemented:** [`tools/hap_sync.py`](../tools/hap_sync.py) — an incremental, HAP-aware sync to both shares over SMB1 (via `pysmb`, so you don't enable Windows SMB1); it filters junk/unsupported files and preserves the `<Artist>/<Album>/` layout. **Full step-by-step guide: [`12-music-sync.md`](12-music-sync.md).**

## Accepted file formats

From the [HAPxFer source](https://github.com/danielrweber/HAPxFer):

- **DSD**: DSF and DFF (2.8 MHz / 5.6 MHz)
- **Lossless PCM**: FLAC, WAV, AIFF, ALAC (Apple Lossless)
- **Lossy**: MP3, AAC/M4A, WMA, ATRAC

ATRAC is a Sony-only lossless/lossy codec — supported here for legacy MiniDisc/Walkman library compatibility. Don't expect anyone outside Sony to ship music in ATRAC.

## File layout conventions

The HAP indexer expects (or at least handles best) the standard `<Artist>/<Album>/<Track>.flac` layout — which on disk lands at `/mnt/internal/storage/<Artist>/<Album (year)>/NN - Artist - Title.flac` (+ a `Cover.jpg`), exactly mirrored in the SQLite folder table. The [outmyth/music-organizer](https://github.com/outmyth/music-organizer) Python tool encodes these conventions if you want to bulk-prepare a library before transfer. See [`09-disk-layout.md`](09-disk-layout.md) for the on-disk structure.

## Cover art

The indexer picks up `cover.jpg` / `folder.jpg` / `front.jpg` in album directories. Embedded cover art in FLAC/MP3/etc. is also extracted.

The cover art served by the JSON-RPC API (see [`03-network-api.md`](03-network-api.md)) goes through an opaque ID. The disk read explained it: full-resolution art is cached on disk at `/mnt/internal/db_storage/cover_art/A00xxxxx/` (one directory per object id, in hex), while the SQLite row carries only a small thumbnail BLOB. See [`09-disk-layout.md`](09-disk-layout.md).

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
