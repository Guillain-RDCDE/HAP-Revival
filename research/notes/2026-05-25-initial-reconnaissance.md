# 2026-05-25 — Initial reconnaissance

First systematic probe of a HAP-Z1ES on a home LAN. This note records the **method** so future investigations can be replicated.

## Setup

- Device: HAP-Z1ES, firmware **0019404R**, on `192.168.1.28`, Ethernet, awake and playing.
- Probe machine: Windows 11, PowerShell 5.1.
- No `nmap` / `masscan` available — used PowerShell `TcpClient` with async connect + 3s timeout for port scans.

## Steps run

1. **Connectivity check** — `Test-Connection 192.168.1.28` → reachable (~70 ms).
2. **MAC vendor check** — `arp -a` → `80:56:F2:85:0E:27`, Sony Corp OUI confirmed.
3. **Initial TCP port scan** — common audio/admin ports. Result: only **139, 445** open.
4. **SMB share enumeration** — `net view \\192.168.1.28 /all` → `HAP_Internal`, `HAP_External`, `IPC$` visible without authentication.
5. **SMB share mount** — `New-SmbMapping -RemotePath \\192.168.1.28\HAP_Internal` → succeeded, drive Y:.
6. **Root listing of HAP_Internal** — confirmed the share contains user music files only, no system folders. Rootfs is not exposed via SMB.
7. **SSDP M-SEARCH** (multicast 239.255.255.250:1900) — initial attempt yielded zero replies because the device was in network standby during the first probe rounds.
8. **User confirmed device was actively playing music** → re-ran SSDP M-SEARCH (this time with also unicast to 192.168.1.28:1900 as a fallback). Got **5 SSDP replies**:
   - `SERVER: Linux/3.0 UPnP/1.0 Sony-HAP/1.0`
   - `LOCATION: http://192.168.1.28:60100/hap.xml`
   - Services advertised: `upnp:rootdevice`, `urn:schemas-upnp-org:device:Basic:1`, `urn:schemas-sony-com:service:ScalarWebAPI:1`, `urn:schemas-sony-com:service:MusicConnect:1`
   - UUID derived from Wi-Fi MAC (different from Ethernet MAC)
9. **HTTP GET `/hap.xml`** on port 60100 — got the full UPnP device description, including `X_ScalarWebAPI_BaseURL = http://192.168.1.28:60200/sony` and `X_HAP_Version = 0019404R`.
10. **TCP probe of port 60200** — confirmed open. The ScalarWebAPI endpoint.
11. **Initial JSON-RPC probes** — all returned HTTP 417 "Expectation Failed." Diagnosed as PowerShell's default `Expect: 100-continue` header. Fix: `[System.Net.ServicePointManager]::Expect100Continue = $false`.
12. **First successful API call** — `system.getInterfaceInformation` at v1.0 returned `{productName: "HAP", modelName: "HAP-Z1ES", productCategory: "audioServer"}`.
13. **Version sweep** — tried each known method at versions 1.0–1.5. Several methods returned "Unsupported Version" until the right version was found:
    - `system.getSystemInformation` → v1.2 ✅
    - `system.getPowerStatus` → v1.1 ✅
    - `audio.getVolumeInformation` → v1.1 ✅
    - `audio.getSoundSettings` → v1.1 ✅ (revealed DSEE, DSD remastering, gapless, volume normalization, oversampling toggles)
    - `avContent.getPlayingContentInfo` → v1.2 ✅ (returned the user's current track in full: Nahawa Doumbia FLAC 16/44 from USB1)
14. **`getMethodTypes` introspection** — returned `{"results": []}` at every version on every service. **Sony deliberately disabled introspection** on HAP. Method names must be discovered another way.
15. **WebSocket upgrade attempt** on port 60200 — returned 405. The Sony notification mechanism likely needs a different endpoint or upgrade flow.
16. **Alternate port probe** (10000, 54480, 52323, 52324, 55400) — all closed. The HAP family is its own generation; cousin Sony devices use different ports.
17. **Embedded web UI probe** — `GET /HAP.html` on port 60100 → 1KB redirect HTML → `/HAP_app.html` → 272 KB embedded JS UI. CSS comments are in Japanese (internal Sony tooling).

## Findings → docs/

The above translated into:

- [`docs/03-network-api.md`](../../docs/03-network-api.md) — the canonical writeup of the API surface.
- [`docs/05-diag-modes.md`](../../docs/05-diag-modes.md) — the verified DIAG entry sequence.
- [`research/api-method-catalog.md`](../api-method-catalog.md) — the living method catalog.

## What to do next

1. Run `tools/api-fuzzer.py --target <ip>` to expand the catalog mechanically.
2. Apply `tools/apk-decompile.md` recipe to the official Android APK.
3. Wireshark the official iOS app during normal use to capture the *real* parameter shapes Sony's client sends.

## Lessons learned

- PowerShell 5.1's `ForEach-Object -Parallel` doesn't exist (PS7 only). Use `TcpClient` + async connect for fast port scans on Windows.
- `Expect: 100-continue` is sent by default by both PowerShell and Python's `requests`. The HAP server returns 417. Disable explicitly.
- SSDP M-SEARCH must hit the device when it's awake. Network standby kills the UPnP responder. Either wake the device manually or send a WoL packet first.
- Sony's JSON-RPC version field is per-method, not per-service. There's no "API version 1.2" — every method picks its own.
