# Contributing to HAP-Revival

Thanks for being here. The HAP-Z1ES / HAP-S1 community is small — every careful contribution materially advances the project.

> **Just own a HAP and want to help in five minutes?** Go to
> [`docs/HELP-IN-5-MINUTES.md`](../docs/HELP-IN-5-MINUTES.md) instead — read-only commands to
> copy and paste, and two menus to photograph. No Python, no account, no case-opening.

## What we need most, in priority order

1. **API method discoveries.** Anyone with a HAP on their LAN can fuzz the JSON-RPC surface on port 60200 and report a new working method (or a new working version of a known method). See [`research/api-method-catalog.md`](../research/api-method-catalog.md) for what's already mapped. Use the [API method issue template](ISSUE_TEMPLATE/api-method-discovered.yml).
2. **Hardware photos and findings.** Inside-the-case photos of the main board, FPGA, DSP, and the location of UART/JTAG headers are the single highest-leverage hardware contribution. We currently rely on Sony's service manual; verified high-res photos are better.
3. **Wireshark captures of the official iOS / Android apps in normal use.** Use a real device, run "HDD Audio Remote" or "Music Center," and capture the LAN traffic (mitmproxy + a self-signed cert if the app uses HTTPS, or plain tcpdump if HTTP). Anonymize and submit to `research/captures/`.
4. **UART console + NAND dump.** No public copy of the firmware exists, though Sony's update host turns out to be a plain file server and the image may yet be downloadable ([`docs/07-firmware.md`](../docs/07-firmware.md)) — the *running* system and the proprietary userland still have to be read off the device. Trace the `CSI0_DAT10/11` console pins to their board test points, attach a **3.3 V** USB-serial adapter (115200 8N1), capture the U-Boot/Linux boot log, and `dd` the rootfs (`/dev/mtdblock2`, JFFS2). Full guide: [`docs/10-uart-console.md`](../docs/10-uart-console.md). This is currently the single highest-leverage hardware contribution.
5. **Working code** — in flight. The Python client (`tools/hap_client.py`) and the browser-based control surface (`tools/webui.py`) shipped in the first session. A native iOS / iPad app is the next pipeline target, blocked only by getting a Mac into the build path.

> **Changing client code?** Read [`docs/16-gotchas.md`](../docs/16-gotchas.md) first. Several
> things that are correct everywhere else are broken on this player, and a green test suite has
> already hidden one such bug in this repository.

## Which machine can answer which question

Findings here are only as good as the hardware behind them, and no single player can produce them
all. As of 2026-08-24 the project reaches four, each able to answer things the others cannot. Worth
reading before asking someone a question their device physically cannot settle.

| Player | State | Can settle | Cannot |
|---|---|---|---|
| **Reference Z1ES** (maintainer's) | `19404R`, HDD library, **internet radio works**, `contentdb` REST hangs | Everything on the JSON-RPC and `contentplayer` REST surfaces, push notifications, internet radio, the gotchas | Volume, tone control, anything S1, anything on an older firmware. And its `contentdb` is broken where others' works |
| **S1 at Amos's workplace** | `19404R`, backup slot holds **`0018120R`** | Volume (`0`–`74`), tone control reads, an S1 tone-control write | Not ours to risk. The one machine that *could* reach an older firmware, and the one we will not ask to |
| **S1 at Amos's home** | `19404R`, backup slot **spent** (both slots identical) | Second S1 data point | Cannot downgrade — the slot was burned by a re-flash |
| **Saschko's player** | German locale; he wrote the browser remote that drives its radio | A second locale's TuneIn tree — paths are locale-specific, so his are not ours | Model and firmware unknown to us |

That table used to say radio worked on his player and not ours, and invited theories about why.
There was nothing to explain: radio works on ours too, and always did — we were calling the API
wrongly. See [`docs/16-gotchas.md`](../docs/16-gotchas.md) §6 for the header that hid it.

**What nobody can currently answer**, and what a new contributor would unlock:

- **A player running any firmware older than `19404R`.** It would settle whether Sony withdrew the
  `/sony/contentdb/v100` library API or never finished it — currently our most consequential
  inference. `0018120R` and `0017310R` are both known to exist and neither is running anywhere we
  can reach.
- **A registered player whose owner will run three calls**, to pin down `path` semantics and make
  internet radio reliable rather than folklore.
- **An opened case.** No UART, no NAND dump, no board photographs of our own.
- **One packet capture, from anyone at all.** Which host the player calls when you press play on a
  station, and what it sends. TuneIn's device API is alive and answering; we simply do not know what
  the HAP asks it. The same capture also reveals the firmware download URL. It is the single
  highest-value thing anyone with a HAP and ten minutes could do.

## What we explicitly do not want

- Sony-copyrighted binaries (firmware blobs, decompiled APK source) committed to the repo. **The recipe to obtain them is fine; the artefacts themselves are not.**
- Pirated music in test data.
- Anything that bypasses streaming-service DRM (we integrate with Tidal/Qobuz/Spotify via their *legitimate* protocols, never around them).

## Workflow

Until we hit a v0.1 milestone, the workflow is intentionally light:

1. Open an issue describing what you want to do or what you found. Link prior issues / PRs.
2. For docs/research changes: small PRs are welcome anytime, no design discussion needed.
3. For code changes: open a draft PR early so we can discuss architecture before too much effort is spent.
4. For destructive operations (anything that could brick a HAP), nothing is merged without (a) a tested recovery path, (b) clear opt-in UX, (c) at least two contributors having tested on their own devices.

## Coding conventions

- **Python**: PEP 8 + type hints + `ruff` for lint. Target Python 3.10+ for tooling, but anything that has to run *on the device* must work with the on-device Python 2.7 (until we replace the daemon).
- **Markdown**: prefer compact prose, tables for catalogs, ASCII diagrams where they help. Don't add a section unless it earns its place.
- **Commits**: imperative mood ("add discovery script", not "added discovery script" or "adding"). One logical change per commit.
- **PR titles**: short summary + scope tag if relevant: `[docs]`, `[tools]`, `[api]`, `[hw]`.

## Reverse engineering ethics

This project operates on **legally owned personal hardware** (your own HAP-Z1ES). We:

- Use Sony's mandatory GPL release (oss.sony.net) for kernel and userland source.
- Read Sony's published service manuals, freely available on ManualsLib, Elektrotanya, etc.
- Decompile APKs that have been distributed by Sony for end-user installation.
- Probe network and physical interfaces of devices we own.

We do **not**:

- Distribute Sony's proprietary closed-source binaries.
- Reverse engineer for the purpose of replicating Sony's hardware commercially.
- Bypass DRM on copyrighted content.

If a contribution moves into legally grey territory, raise it in the PR — we'll discuss before merging.

## Code of Conduct

Be kind, be precise, assume good faith. We have neither the time nor the appetite for drama. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security

If you find a security issue with anything we ship (the future control daemon, the iOS app, etc.) please follow [SECURITY.md](SECURITY.md) — not the public issue tracker.

## Recognition

All contributors are credited in [CHANGELOG.md](../CHANGELOG.md) per release and in `README.md` once we add a contributors section. Code contributions are credited via git history; doc-only or research-only contributions are credited explicitly in the changelog.

Thank you. Let's keep good hardware alive.
