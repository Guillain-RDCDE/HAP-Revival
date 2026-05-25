# 2026-05-25 — Cover art format and SOAP MusicConnect probe

Two side experiments while the main API mapping continues.

## Cover art download

The `coverArtUrl` field in `getPlayingContentInfo` / `getContentInfo` is a plain HTTP GET. No authentication, no special header.

Tested URL: `http://192.168.1.28:60200/sony/avContent/storage/cover_art/A0002E05`

Result:
- HTTP 200
- 93 771 bytes
- First 8 bytes: `FF D8 FF E0 00 10 4A 46` → **JPEG (JFIF)**
- Renderable directly in any image viewer.

**Implications for the iOS / web app**: cover art display is trivial. Construct `<img src="<coverArtUrl>">` (or equivalent SwiftUI `AsyncImage`). No image decoding needed beyond what every platform ships.

**The 8-hex-char ID** (`A0002E05` in this example): opaque. It does NOT match the album ID in `audio:album?id=NNNN` directly. Either it's a hash, a database row id, or a sequential ID assigned during library indexing. Future investigation: dump several cover art IDs alongside their associated album IDs to look for a pattern.

**Cover art file is NOT committed to the repo** (user's music library content; gitignored via `*.bin`). The capture is at `research/captures/cover-art-A0002E05.bin` locally.

## SOAP / UPnP MusicConnect — endpoint missing

The hap.xml UPnP description declares:

```xml
<service>
  <serviceType>urn:schemas-sony-com:service:MusicConnect:1</serviceType>
  <serviceId>urn:schemas-sony-com:serviceId:MusicConnect</serviceId>
  <SCPDURL>/MusicConnect_SCPD.xml</SCPDURL>
  <controlURL>/MusicConnect/control</controlURL>
  <eventSubURL>/MusicConnect/event</eventSubURL>
</service>
```

Tested: standard SOAP `GetTransportState` envelope POSTed to `http://192.168.1.28:60100/MusicConnect/control` with proper `SOAPACTION` header.

Result: **HTTP 404**.

So the MusicConnect service is **declared in the UPnP descriptor but the actual SOAP endpoint is not served at the declared path**. This is consistent with Sony's pattern of advertising UPnP services for discovery while doing the real work via the ScalarWebAPI JSON-RPC on port 60200.

The SCPD itself (`/MusicConnect_SCPD.xml`) does load and declares the `TransportState` (STOPPED/PLAYING/PAUSED_PLAYBACK/NO_MEDIA_PRESENT) and `LastChange` evented variables — but without a working control endpoint, those can't be queried via SOAP.

**Implication**: forget SOAP/UPnP control for HAP. The JSON-RPC on port 60200 is the only working control plane. The UPnP descriptor exists for SSDP discovery and as a Sony-internal vestige.

To-do: try the same SOAP probe against port 60200 (some Sony devices route both protocols through the same port). Try also `/event` for UPnP eventing — if that works, it might be an alternative to WebSocket notifications.
