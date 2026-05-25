# Contributing to HAP-Revival

Thanks for being here. The HAP-Z1ES / HAP-S1 community is small — every careful contribution materially advances the project.

## What we need most, in priority order

1. **API method discoveries.** Anyone with a HAP on their LAN can fuzz the JSON-RPC surface on port 60200 and report a new working method (or a new working version of a known method). See [`research/api-method-catalog.md`](research/api-method-catalog.md) for what's already mapped. Use the [API method issue template](.github/ISSUE_TEMPLATE/api-method-discovered.yml).
2. **Hardware photos and findings.** Inside-the-case photos of the main board, FPGA, DSP, and the location of UART/JTAG headers are the single highest-leverage hardware contribution. We currently rely on Sony's service manual; verified high-res photos are better.
3. **Wireshark captures of the official iOS / Android apps in normal use.** Use a real device, run "HDD Audio Remote" or "Music Center," and capture the LAN traffic (mitmproxy + a self-signed cert if the app uses HTTPS, or plain tcpdump if HTTP). Anonymize and submit to `research/captures/`.
4. **Firmware blob analysis.** Download a Sony firmware (URLs in [`docs/07-firmware.md`](docs/07-firmware.md)), run `binwalk`, document the container format. Nobody has published this.
5. **Working code.** Once the API is mapped, a clean Python client → web UI → iOS app pipeline.

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

All contributors are credited in [CHANGELOG.md](CHANGELOG.md) per release and in `README.md` once we add a contributors section. Code contributions are credited via git history; doc-only or research-only contributions are credited explicitly in the changelog.

Thank you. Let's keep good hardware alive.
