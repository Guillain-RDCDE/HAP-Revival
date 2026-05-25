# Prior art — exhaustive bibliography

The complete public corpus of work on the Sony HAP-Z1ES / HAP-S1, validated by four parallel research agents in 2026-05.

## Tier 1 — Directly HAP-relevant artefacts

Total count: **7**. That's the entire world's HAP-specific output across a decade.

### 1. Sony GPL source release

- **URL (latest)**: <https://oss.sony.net/Products/Linux/Audio/HAP-S1.html> (covers HAP-S1 and HAP-Z1ES; HAP-Z1ES has no separate page)
- **URL (older firmwares)**: `HAP-S1_19226R.html`, `HAP-S1_18777R.html`, `HAP-S1_18444R.html` under <https://oss.sony.net/Products/Linux/Audio/>
- **What**: Sony's mandatory open-source release. Kernel, U-Boot, BusyBox, Samba 3.0.37, Dropbear 2012.55, lighttpd 1.4.35, GStreamer 0.10.36, Python 2.7.3, web.py, Tokyo Cabinet, SQLite, DirectFB, **`forza_snd_driver`** (the custom audio kernel module).
- **Why it matters**: tells us exactly what's running on the device. The `forza_snd_driver` source is the most valuable single file in the entire prior-art corpus.
- **What it doesn't have**: the proprietary application-layer (control daemon, custom GStreamer elements, UPnP daemon, library indexer, FPGA bitstream).

### 2. `danielrweber/HAPxFer`

- **URL**: <https://github.com/danielrweber/HAPxFer>
- **What**: macOS Swift app (99.2% Swift, 0.8% C) that replaces the discontinued Sony "HAP Music Transfer." Bundles `libsmbclient` to speak SMB1 against the `HAP_Internal` share. Implements transfer, folder sync, Wake-on-LAN, artist tag override, scheduled sync. **GPLv3.**
- **Author**: Daniel Weber.
- **Stars**: 0. **Forks**: 0. **Issues**: 0. **PRs**: 0. The repository has had zero community engagement since creation.
- **Verified concrete facts** (verbatim from README):
  - "uses Samba's libsmbclient library to speak SMB1 (NT1 protocol) directly to the HAP-Z1ES"
  - "The device exposes an `HAP_Internal` SMB share where music files are stored"
  - "SMB1 removed — macOS dropped SMB1 support starting with High Sierra (2017). The HAP-Z1ES only speaks SMB1"
  - Library rescan is triggered automatically by file-drop on the share — **no API call required**.

### 3. `frazei/09d69242a8beed0cf0a1c193a45a650a` (gist)

- **URL**: <https://gist.github.com/frazei/09d69242a8beed0cf0a1c193a45a650a>
- **Date**: July 26, 2022
- **What**: 10-line markdown documenting the JSON-RPC control surface. The **only** prior public documentation of the API before HAP-Revival.
- **Concrete content**:
  - Web UI: `http://IPADDR:60100/HAP.html` → `HAP_app.html`
  - JSON-RPC endpoint root: `http://IPADDR:60200/sony/`
  - Service paths: `/sony/system` (getPowerStatus, setPowerStatus active/off), `/sony/avContent` (pausePlayingContent, setPlayNextContent, setPlayPreviousContent), `/sony/audio` (getVolumeInformation, setAudioVolume)
  - Standard ScalarWebAPI JSON envelope with `version` + `id`
- **Why it matters**: confirms that frazei (and now us) independently observed the same API. Validates our methodology. Frazei did not extend the work — the gist has remained at 7 methods for 4 years.

### 4. `rytilahti/python-songpal#29`

- **URL**: <https://github.com/rytilahti/python-songpal/issues/29>
- **Date**: opened September 2018 by `wouzzie`, still open in 2026
- **What**: Issue titled "Missing support for devices without getSupportedApiInfo (Sony BDV-N5200, HAP-S1, BDV-N9200W)." Confirms HAP-S1 returns `{'error': [12, 'getSupportedApiInfo'], 'id': 1}` and reports the API at `:10000/sony` (likely an older firmware version, since current 19404R uses :60200 exclusively — verified empirically).
- **Status**: no workaround merged. python-songpal does not work with HAP devices as-is.
- **Why it matters**: confirms HAP needs custom handling; documents that Sony deliberately neutered introspection on this family.

### 5. `outmyth/music-organizer`

- **URL**: <https://github.com/outmyth/music-organizer>
- **What**: Python tool to organize music files and generate M3U playlists for "audiophile DAPs — Sony HAP-Z1ES/Walkman, Chord Poly, Lotoo PAW Gold 2017."
- **HAP relevance**: just knows about DSD support and the standard `<Artist>/<Album>/<Track>.flac` path convention. No protocol code, no API.
- **Stars**: 0. **Forks**: 0.

### 6. Crestron HAP-Z1ES control module

- **URL**: <https://applicationmarket.crestron.com/sony-hap-z1es/>
- **Date**: last updated 2016-07-26
- **What**: SIMPL Windows TCP/IP control module for the HAP-Z1ES. Closed source. The accompanying Help PDF documents the wire protocol Crestron uses.
- **Access**: requires a Crestron developer account. Not freely scraped.
- **Why it matters**: this is the **only quasi-official protocol document** known to exist. If a contributor with Crestron access pulls this PDF, it could leapfrog several phases of API reverse-engineering.

### 7. `com.sony.HAP.HDDAudioRemote` Android APK

- **URL**: <https://www.apkmirror.com/apk/sony-corporation/hdd-audio-remote/hdd-audio-remote-4-3-1-release/>
- **Version**: 4.3.1
- **Size**: 12.88 MB
- **Last updated**: 2022-12-12
- **Minimum Android**: 7.0
- **What**: Sony's official Android remote app for the HAP-Z1ES/HAP-S1. Still in the Play Store. The APK contains every API method name, version, and JSON shape the device understands.
- **Status (until 2026-05-25)**: never publicly decompiled. **Now decompiled by HAP-Revival** — first public decompile, with two extensive analysis notes: [`research/notes/2026-05-25-apk-decompile-findings.md`](../research/notes/2026-05-25-apk-decompile-findings.md) (first pass — endpoints, headers, polling model, method index) and [`research/notes/2026-05-25-apk-deep-dive-downloadbydiff.md`](../research/notes/2026-05-25-apk-deep-dive-downloadbydiff.md) (deep dive — `downloadByDiff` flow, `getRichMetaInfo`, `editContentInfo` dispatch).
- **Why it mattered**: this was the **single highest-leverage unexplored artefact** in the entire corpus. Decompilation yielded the complete method dictionary, Sony-authoritative parameter shapes for every 🟡 entry in our catalog, and the negative finding that there is no WebSocket push (Sony polls at 5 s). It directly unblocked everything between commits 899b999 and 8ebca38.

## Tier 2 — Adjacent Sony reverse-engineering (transposable to HAP)

The HAP API is a variant of Sony's ScalarWebAPI used across cameras, TVs, AV receivers, soundbars. While HAP isn't directly supported by any of these projects, the JSON shapes and method patterns are highly transferable.

| Project | Lang | Stars | Coverage | Transposability to HAP |
|---|---|---|---|---|
| [`rytilahti/python-songpal`](https://github.com/rytilahti/python-songpal) | Python | ~77 | STR-DN1080, soundbars, ZR5 | **High** — same protocol family, port 10000 instead of 60200, version remap needed |
| [openHAB Sony binding PR #6884 (tmrobert8)](https://github.com/openhab/openhab-addons/pull/6884) | Java | n/a | "the most complete Sony implementation to date" — TV, Bluray, BDV, AVR, soundbar, wireless speaker. Built from Wireshark | **High** — dynamic introspection handles unknown devices |
| [openHAB SonyAudio binding (freke)](https://www.openhab.org/addons/bindings/sonyaudio/) | Java | n/a | STR-DN1080, HT-CT800, SRS-ZR5, HT-ST5000, etc. | **Medium** — production binding, more conservative |
| [`sonydevworld/audio_control_api_examples`](https://github.com/sonydevworld/audio_control_api_examples) | JS | (Sony official) | WebSocket notifications + DLNA AVTransport SOAP examples | **High** — directly usable as reference |
| [Sony BRAVIA Pro REST API spec](https://pro-bravia.sony.net/develop/integrate/rest-api/spec/) | (spec) | n/a | exhaustive method+version+JSON-shape doc | **High** — the most complete Sony-published spec; reverse-lookup for HAP method shapes |
| [`waynehaffenden/bravia`](https://github.com/waynehaffenden/bravia) | Node.js | low | Bravia wrapper | Medium — clean template |
| [`gerard33/sony-bravia`](https://github.com/gerard33/sony-bravia) | Python | low | TV-only | Low |
| [`breunigs/bravia-auth-and-remote`](https://github.com/breunigs/bravia-auth-and-remote/blob/master/commands) | (curl dump) | n/a | Concrete `getMethodTypes` walk for KDL-50W829B with `actRegister` auth | **Medium** — method dictionary to fuzz against HAP |
| [kalleth sony_bravia.md gist](https://gist.github.com/kalleth/e10e8f3b8b7cb1bac21463b0073a65fb) | (gist) | n/a | Full `getMethodTypes` walk for another Bravia | **Medium** — same |
| [`Bloodevil/sony_camera_api`](https://github.com/Bloodevil/sony_camera_api) | Python | n/a | Sony camera JSON-RPC | Low (different methods) |
| [`egaebel/sony-headphones-hack`](https://github.com/egaebel/sony-headphones-hack) | (notes) | n/a | Methodology: apktool against Sony Headphones Connect | **Medium** — recipe to apply to HDDAudioRemote APK |

## Tier 3 — Hardware-side community knowledge (mostly Japanese)

The English-speaking audiophile world has barely touched the HAP. The Japanese community has documented hardware mods rigorously.

### HDD / SSD swap

| Source | Date | Drive | Outcome |
|---|---|---|---|
| [briareos hatena](https://briareos.hatenablog.jp/entry/20160201/p1) | 2016-02 | Samsung 850 EVO 1 TB | ✅ works after factory reset |
| [emuzu cocolog](https://emuzu-2.cocolog-nifty.com/blog/2019/10/post-57c506.html) | 2019-10 | Samsung 860 EVO 1 TB via KURO-DACHI sector clone | ✅ "behaved identically to original including DB and settings" |
| [saionjihouse](https://saionjihouse.com/2021/06/27/) | 2021-06 | Samsung 860 EVO 1 TB, fan removed, factory reset | ✅ works |
| [compact.exblog](https://compact.exblog.jp/30320947/) | 2020-11 | Clone failed; factory reset worked. Library rescan wiped all HAP-Audio-Remote-edited metadata | ⚠️ caveats |
| [aku_ari rakuten](https://plaza.rakuten.co.jp/akuari/diary/202109230002/) | 2021-09 | 2 TB SSD + alu heatsink; Gracenote lookup broke after firmware update | ✅ works |
| [kakaku SortID=24642226](https://bbs.kakaku.com/bbs/K0000579959/SortID=24642226/) | 2022-03 | **Samsung 860/870 EVO → scan loops; Crucial MX500 + KIOXIA work** | Important compatibility data |
| [Head-Fi #801939](https://www.head-fi.org/threads/sony-hap-s1.801939/) | 2016-03 | HAP-S1 with Seagate ST2000LM003 2 TB 9.5 mm | ✅ "the firmware is located on a chip in the machine itself - independent from the drive" |

### Op-amp and clock mods

- [Sound Den (JP shop)](http://www.soundden.com/column/hd-player-onshitsukaizen.html), 2016-01 — paid mod service replacing both master clocks with their "DT series" clocks.
- [philm-community](https://philm-community.com/phile311031/user/diary/2023/12/15/22801/), Dec 2023 — 3-part op-amp swap series.

### Measurements (HAP-S1 only)

- [Audio Science Review thread #6921 (Amir)](https://www.audiosciencereview.com/forum/index.php?threads/sony-hap-s1-review-network-amp.6921/), Feb 2019. Headline finding: HAP-S1 headphone amp is just a 400 Ω resistor on the speaker output. No dedicated HP amp circuit.

### Internals discussion

- [diyAudio thread](https://www.diyaudio.com/community/threads/sony-hap-z1es-hi-res-source-new-2014.252985/), 2014→. Confirms FPGA + SHARC + dual PCM1795 mono.
- [AudioCircle thread #124280](https://www.audiocircle.com/index.php?topic=124280.0), 2014→. Photos of teardown (general, no IC closeups).
- [kakaku SortID=22520896](https://bbs.kakaku.com/bbs/K0000579959/SortID=22520896/) — general spec thread, includes `blackbird1212` (the most technical regular).

## Tier 4 — Service / official documents

- [HAP-Z1ES service manual on ManualsLib](https://www.manualslib.com/manual/1606461/Sony-Hap-Z1es.html) — best for HAP-Z1ES specifically.
- [HAP-S1 service manual PDF (riverparkinc mirror)](https://riverparkinc.com/wp-content/uploads/2015/01/HAPS1_SERVICE_MANUAL.pdf) — cleanest free PDF, applies equally to HAP-Z1ES architecture.
- [HAP-Z1ES service manual on Elektrotanya](https://elektrotanya.com/sony_hap-z1es.pdf/download.html) — direct download mirror.
- [Sony Help Guide HAP-Z1ES](https://helpguide.sony.net/ha/hapz1es/v1/en/) — end-user manual.
- [Sony Asia firmware page (19404R)](https://www.sony-asia.com/electronics/support/downloads/00017124).
- [Sony UK firmware page (19404R)](https://www.sony.co.uk/electronics/support/audio-components-hdd-audio-network-audio-players/hap-z1es/downloads/00017123).
- [Sony Asia support docs on Special Mode SMB selector](https://www.sony-asia.com/electronics/support/audio-components-hdd-audio-network-audio-players/hap-z1es/software/00279155).

## Forums where we looked and found nothing meaningful

These were systematically checked and yielded zero technical content for the HAP-Z1ES / HAP-S1:

- audiocircle.com (apart from the teardown thread above)
- forum.cdrlabs.com
- hifi-haven.net
- pinkfishmedia.net
- whathifi.com forums
- Hackaday.com — never published an article on the HAP
- Reddit (r/audiophile, r/diyaudio, r/ReverseEngineering)
- Audio Asylum
- audiosciencereview.com (HAP-S1 only, no HAP-Z1ES)

## Forums that may have content but were unreachable to our agents (paywall / login)

- audiogon.com
- forums.stevehoffman.tv
- avsforum.com (modern URL)
- yahoo!知恵袋 (Japanese Q&A)

If you have an account, please pull anything technical and submit via PR.

## The complete corpus summary

The world's open-source HAP-Z1ES/HAP-S1 corpus, in totality, in 2026:

1. One macOS Swift app for SMB1 file transfer (HAPxFer).
2. One Python music-organizer that knows HAP path conventions.
3. One 10-line markdown gist documenting 7 API methods (frazei).
4. One stuck GitHub issue noting `getSupportedApiInfo` is missing (python-songpal#29).
5. Sony's mandatory GPL source bundle (kernel + userland).
6. One closed-source Crestron module from 2016.
7. Sony Android APK — first publicly decompiled by HAP-Revival on 2026-05-25.
8. ~12 Japanese audiophile blog posts on HDD swap and op-amp mods.
9. ~6 forum threads with technical content.
10. The service manuals (excellent quality, freely available).

That's it. **HAP-Revival is positioned to become the canonical reference** by virtue of being the only structured project that has bothered to consolidate all of the above and to extend the API mapping work that frazei started.

## Recommended reading order for new contributors

1. The **HAP-S1 service manual PDF** (cleanest) — get the hardware architecture in your head.
2. The **Sony GPL source bundle** — pull the `forza_snd_driver` tarball and skim the source.
3. The **HAPxFer source** — see how someone else did the SMB part.
4. The **frazei gist** — see what API methods are already public.
5. The **`python-songpal/songpal/device.py`** — see the cousin-device method dictionary.
6. The **Sony BRAVIA REST API spec** — bookmark for JSON shape lookup.
7. This repository's [`research/api-method-catalog.md`](../research/api-method-catalog.md) — the live state of our own mapping.
