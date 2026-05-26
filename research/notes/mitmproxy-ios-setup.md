# mitmproxy setup for capturing the iOS HDD Audio Remote app

> **⚠️ STATUS (2026-05-26): we tried this end-to-end and it does not work for the Sony HDD Audio Remote app specifically.** The setup itself is correct — Safari + system services are captured fine. But Sony's app uses (a) low-level networking that bypasses the iOS system proxy and (b) SSDP multicast discovery that doesn't traverse VPN tunnels. After three escalating attempts (proxy mode → WireGuard single-subnet → WireGuard + Windows Mobile Hotspot dual-subnet), the app still can't see the HAP through the capture pipeline. Full failure analysis: [`2026-05-26-ios-capture-postmortem.md`](2026-05-26-ios-capture-postmortem.md).
>
> **Keep this guide for**: any other iOS app that talks unicast HTTP/HTTPS to a known IP (most modern apps). The mitmproxy + WireGuard setup is solid for that use case.
>
> **Don't use this guide for**: capturing Sony HDD Audio Remote. We pivoted to reading the HAP's internal HDD directly off the SATA dock instead — which gives strictly more information with strictly less complexity.

How to capture the wire traffic between an iOS client app and a target on the LAN, on a Windows PC.

The original target for HAP-Revival was Sony HDD Audio Remote, to see the exact request sequence around `database.downloadByDiff` so we could replicate it. **That specific target didn't work** — see the warning above. The setup itself is sound for any iOS app that doesn't gate on multicast discovery.

## What you'll need

- A Windows PC on the same Wi-Fi as the HAP and your iPhone.
- Python 3.10+ and `pip` (already on the reference machine).
- Your iPhone with the Sony **HDD Audio Remote** app installed.
- ~15 minutes the first time, ~2 minutes for subsequent capture sessions.

## One-time install on the PC

```powershell
python -m pip install --user mitmproxy
```

After install the wrappers live at `C:\Users\<you>\AppData\Roaming\Python\Python314\Scripts\` — `mitmweb.exe`, `mitmdump.exe`, `mitmproxy.exe`. Either add that path to your `PATH` or invoke `mitmweb.exe` by full path.

## Find your PC's LAN IP

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '192.168.*' -or $_.IPAddress -like '10.*' }
```

Pick the IP on your **Wi-Fi** interface — that's the address the iPhone will reach you on. Note it down (e.g. `192.168.1.21`).

## Launch mitmweb

```powershell
& "C:\Users\$env:USERNAME\AppData\Roaming\Python\Python314\Scripts\mitmweb.exe" --listen-port 8080
```

The first launch shows:

- Web UI at `http://127.0.0.1:8081` — open it in your browser.
- Proxy listening on `0.0.0.0:8080`.

Windows Defender Firewall will pop up asking to allow `mitmweb.exe` to receive connections on **Private networks**. **Allow**. (Without this, the iPhone can't reach the proxy.)

## Configure the iPhone to use the proxy

1. Settings → Wi-Fi → tap the (i) next to your connected network.
2. Scroll down to **Configure Proxy** → tap → **Manual**.
3. Fill in:
   - **Server**: your PC's IP, e.g. `192.168.1.21`
   - **Port**: `8080`
   - **Authentication**: off
4. Tap **Save**.

## (Optional) Install mitmproxy's root CA on the iPhone

Strictly speaking, the HAP API on port 60200 is plain HTTP, so mitmproxy can read every request without any certificate trickery. The CA install is only needed if you also want to intercept HTTPS traffic the app makes to Sony's cloud (firmware-check, account, etc.).

For our target (HAP control protocol), you can **skip this section**. If you want it anyway:

1. With the proxy active and the iPhone routing through it, open **Safari** on the iPhone.
2. Go to `http://mitm.it`.
3. Tap the **Apple** logo → download the iOS profile.
4. Settings → General → VPN & Device Management → tap the downloaded profile → Install (you'll need your phone passcode).
5. Settings → General → About → Certificate Trust Settings → enable the toggle next to **mitmproxy**.

## Start capturing

1. Open the **HDD Audio Remote** app on the iPhone.
2. Let it discover and connect to the HAP. Watch the mitmweb browser tab — every HTTP request from the app should appear in real time.
3. **Filter** by typing in the search bar at the top of mitmweb. Useful filters:
   - `~u sony` — only requests to `/sony/...` (the API)
   - `~u database` — only the database service calls (`downloadByDiff` and friends)
   - `~u avContent` — only the avContent service
   - `~hq 192.168.1.28` — only requests targeting the HAP IP

## What to look for first

The single most valuable capture: a **full bootstrap sequence**. Restart the app cold (close it from the app switcher, then re-open) while mitmweb is recording. The app will:

1. Discover the HAP via SSDP (UDP, won't appear in mitmweb but will appear in network logs).
2. Fetch the UPnP description (`GET http://192.168.1.28:60100/hap.xml`).
3. Probably call `system.getSystemInformation`, `system.getPowerStatus`, `audio.getVolumeInformation`, `avContent.getPlayingContentInfo`.
4. **Begin the database sync**: `database.checkSameDatabase` then `database.downloadByDiff`.
5. **If the response to `downloadByDiff` has a non-empty `location`**, the app immediately does a `GET` on that URL. **That's the exact request we cannot reproduce yet.** Capture every header on both the POST and the follow-up GET.

Right-click any request in mitmweb → **Save** → you get a `.har` or raw text file you can attach to a GitHub issue or commit to `research/captures/`.

## Quick recipes

### Just dump every request to a file in real time

```powershell
& "C:\Users\$env:USERNAME\AppData\Roaming\Python\Python314\Scripts\mitmdump.exe" --listen-port 8080 -w hdd-audio-remote.mitmflow
```

Then `mitmdump.exe -r hdd-audio-remote.mitmflow` plays it back, or open it in mitmweb later.

### Replay a captured request from Python

```python
# Quick replay of the exact downloadByDiff Sony sent
import json, urllib.request
body = json.dumps({"method":"downloadByDiff","id":1,"params":[...],"version":"1.0"}).encode()
req = urllib.request.Request("http://192.168.1.28:60200/sony/database",
    data=body, method="POST",
    headers={"Content-Type":"application/json","x-hap-device-id":"<copy-from-capture>"})
print(urllib.request.urlopen(req).read().decode())
```

## Troubleshooting

- **The iPhone doesn't show any traffic in mitmweb** → the iOS proxy setting was saved but the connection isn't going through. Check that mitmweb actually shows "Proxy: 0.0.0.0:8080" in the bottom status line. Re-check the iPhone is on the same Wi-Fi (not 4G/5G). Make sure Windows Defender allowed `mitmweb.exe` on **Private** networks.
- **The iPhone shows "No internet"** → the proxy isn't reachable. Verify the IP is right (it can change after a Wi-Fi reconnect; pin a static IP in your router for both the PC and the HAP if you do this often). Verify the firewall.
- **iOS bypasses the proxy for the HAP** → some iOS versions skip the proxy for "local subnet" addresses. The fix: use mitmproxy's **WireGuard mode** instead of HTTP proxy mode (`--mode wireguard`). It runs a WireGuard VPN that captures *all* iPhone traffic regardless of destination. Install the free WireGuard app on iPhone, scan the QR code mitmweb displays. Slightly more setup but bulletproof.
- **HTTPS calls show as `[unable to decrypt]`** → you need to install + trust the mitmproxy CA on the iPhone (see optional section above). Plain HTTP captures fine without this.

## Reset when done

1. **Stop mitmweb**: Ctrl+C in the PowerShell window.
2. **Turn off the iPhone proxy**: Settings → Wi-Fi → (i) → Configure Proxy → **Off**.

The iPhone goes back to direct internet access. The mitmproxy CA, if you installed it, can be removed via Settings → General → VPN & Device Management → tap the profile → Remove Profile.

## Why this matters for HAP-Revival

The two open knowledge gaps that a 30-minute capture session would close:

1. **`downloadByDiff` empty `location`** — we know the response shape but never receive a real URL. Sony's iOS app gets one. A capture shows the full request (every header, every param) so we can replicate it byte-for-byte.
2. **iOS-vs-Android protocol divergence** — we've decompiled the Android client thoroughly. The iOS app could use different method versions, different parameter names, or call methods we haven't seen. The capture is the ground truth.

Commit captures to `research/captures/` (sanitize any auth tokens / personal device IDs first). Document new findings in a dated note under `research/notes/`.
