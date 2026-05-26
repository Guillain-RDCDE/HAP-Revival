# 2026-05-26 — Failing forward: why we couldn't capture the iOS HDD Audio Remote app

> *Three escalating attempts to intercept the wire traffic between Sony's iOS app and the HAP. All three failed for different (and ultimately revealing) reasons. We pivoted to reading the HAP's rootfs directly off the internal HDD instead. This note documents what didn't work so the next contributor doesn't re-burn the same hours.*

## TL;DR

| Attempt | What we did | What killed it |
|---|---|---|
| 1 | Configure iOS Wi-Fi to use the PC as HTTP/HTTPS proxy. | Sony app bypasses the iOS system proxy — uses lower-level networking. Safari traffic captured fine; Sony app sees nothing. |
| 2 | Run mitmproxy in WireGuard mode, iPhone tunnels everything via VPN. | iOS **local-subnet bypass**: the iPhone's Wi-Fi route for `192.168.1.0/24` (where the HAP lives) wins against the VPN's `0.0.0.0/0` default route. Local traffic exits via Wi-Fi without going through the tunnel. |
| 3 | Activate Windows Mobile Hotspot, move iPhone to a different subnet (`192.168.137.x`). Re-run WireGuard with the new endpoint. | Tunnel + NAT now work end-to-end (Safari to the HAP IP is captured ✓). But the **Sony app discovers the HAP via SSDP multicast** (UDP 239.255.255.250:1900), which doesn't traverse VPN tunnels or subnets without an explicit relay. The app reports "lecteur invisible". |

The mitmproxy + WireGuard + hotspot path is a perfectly working tool — for traffic that uses **unicast** to a **known IP**. It happens to not be a fit for an app that gates on multicast discovery.

We stopped here. The HDD-reading path (dock SATA-USB, manual HDD extraction → mount on PC → read the rootfs) is on its way and will give us strictly more information than mitmproxy ever would, with much less complexity.

## The goal

Why we wanted this capture in the first place: see what Sony's iOS app sends to `/sony/database/downloadByDiff` that we can't reproduce ourselves. We've spent two sessions reverse-engineering the database service:

- `database.checkSameDatabase` works for us ✓ (live-validated 2026-05-25)
- `database.downloadByDiff` accepts the request, returns a well-formed JSON envelope with `type: "all"`, but the `location` field is **empty** — every single time, with every parameter combination we tried.

The APK deep-dive ([2026-05-25-apk-deep-dive-downloadbydiff.md](2026-05-25-apk-deep-dive-downloadbydiff.md)) confirmed our request shape is byte-identical to what Sony's Android client sends. Yet Sony gets a non-empty `location` URL back, and we don't. There has to be a piece of state (header, preflight call, session token, app version handshake?) we're not replicating.

mitmproxy on the iOS client was the most direct way to see what Sony's app actually sends and find the missing piece.

## Attempt 1 — Standard Wi-Fi proxy

The classic setup:

- `pip install mitmproxy` on the PC ✓
- Launch `mitmweb --listen-port 8080`
- iPhone → Settings → Wi-Fi → (i) → Configure Proxy → Manual → PC IP + port 8080
- Skip the CA cert install (HAP traffic is plain HTTP, no decryption needed)

**Verification**: Safari on the iPhone went through the proxy — every page load showed up in mitmweb. The setup works.

**Failure**: launching HDD Audio Remote on the iPhone showed zero traffic in mitmweb. The app connected to the HAP successfully (from its own UI), but mitmproxy saw nothing.

**Why**: iOS exposes proxy settings via a public API, but apps can opt out. URLs constructed through low-level sockets, CFNetwork without the `kCFProxiesHTTPEnable` flag, or any other proxy-unaware networking layer simply ignore the system setting. Sony's app is in that club. Many older audio control apps are.

That's actually defensible from a privacy perspective — system proxies are an obvious MITM attack vector — but it ends our first attempt.

## Attempt 2 — mitmproxy WireGuard mode, single subnet

mitmproxy 12+ ships a WireGuard server mode. The pitch: run a WireGuard VPN endpoint on the PC, install the WireGuard app on the iPhone, scan a QR code → all iPhone traffic gets tunneled to the PC and intercepted, **regardless** of whether individual apps honor the system proxy.

Steps that worked:

- `mitmweb --mode wireguard --listen-host 0.0.0.0`
- Generated a QR for the printed client config (with `Endpoint = <PC LAN IP>:51820` — the auto-printed `0.0.0.0:51820` is unrouteable from the iPhone)
- Installed WireGuard from the App Store on the iPhone, scanned the QR, activated the tunnel
- Opened Windows Firewall for UDP 51820 inbound (essential — the default rule was TCP-only)

After Wi-Fi proxy was off and WireGuard was on:

- Safari → google.com worked (slowly): captured in mitmweb ✓
- The iPhone's background traffic to Apple push servers showed up: captured ✓
- The Sony app: still nothing in mitmweb when it talked to the HAP at `192.168.1.28`.

**Diagnostic test**: Safari → `http://192.168.1.28:60100/hap.xml`. The page **loaded** (correct XML returned), but **didn't appear in mitmweb**.

That's the smoking gun: the iPhone reaches the HAP successfully via its **Wi-Fi interface directly**, completely bypassing the WireGuard tunnel.

**Why**: iOS uses **longest-prefix-match routing** plus a hard-coded preference for the direct-connect (link-local) route over VPN routes for any destination on the same physical subnet. The iPhone has:

- Wi-Fi link-local route: `192.168.1.0/24 dev en0` (added by DHCP, /24 specific)
- WireGuard route: `0.0.0.0/0 dev wg0` (`AllowedIPs = 0.0.0.0/0`, /0 specific)

`/24` wins against `/0`. Any traffic to `192.168.1.x` exits via Wi-Fi, never seeing the tunnel.

This is documented behavior, and it cannot be overridden from `AllowedIPs` alone. You can ask `AllowedIPs = 192.168.1.0/24` to be more specific than the link route — iOS still prefers the link route. The WireGuard app doesn't expose a "force include all networks" toggle the way some commercial VPNs do.

The standard workaround: put the iPhone on a *different* subnet, so the HAP becomes "remote" from the iPhone's perspective.

## Attempt 3 — Windows Mobile Hotspot to break the local-subnet trap

Activate the Windows Mobile Hotspot on the PC (Settings → Network & Internet → Mobile hotspot → toggle on). Windows creates a soft AP on the same Wi-Fi adapter, exposed as a separate SSID, with its own subnet (typically `192.168.137.0/24`).

- iPhone connects to that AP → gets IP `192.168.137.252`
- HAP at `192.168.1.28` is now "remote" from the iPhone's perspective (different subnet)
- Re-generated the WireGuard QR with `Endpoint = 192.168.137.1:51820` (the PC's IP on the hotspot side)
- Extended the firewall rule to cover the **Public** profile too (Windows often categorizes hotspot interfaces as Public)
- Iphone scanned new QR → activated tunnel → "Latest handshake" populated ✓

**Verification**: Safari → `http://192.168.1.28:60100/hap.xml` now both **loads on the iPhone** AND **appears in mitmweb**. End-to-end:

```
iPhone (192.168.137.252) → WireGuard tunnel → PC mitmproxy → PC NAT → HAP (192.168.1.28) → ...response back the same way
```

**Failure**: launching HDD Audio Remote, the app times out searching for the HAP and offers "Launch offline". From mitmweb we could see **no requests at all** from the app — not a discovery attempt, not a connection failure mid-handshake, nothing.

**Why**: the Sony app's first action on launch is **SSDP discovery** — a UDP multicast on `239.255.255.250:1900`. Multicast packets:

- Are sent to a multicast group, not a unicast IP
- Are not routed across subnets by default
- Do not traverse VPN tunnels in any practical way without an explicit relay
- Are not in the WireGuard `AllowedIPs = 0.0.0.0/0` set in any meaningful way (WireGuard is unicast point-to-point)

The Sony app sends its SSDP `M-SEARCH`, waits for any device to reply `LOCATION: http://...`, times out, and concludes there's no HAP on the network. There is no manual-IP fallback in the app — the APK code path is discovery-only.

We tried one workaround before giving up: connect the iPhone briefly to the home Wi-Fi (where SSDP works), let the app discover the HAP, then switch back to the hotspot. The hope was the app would cache the discovered HAP's IP and reuse it. It doesn't — the app re-discovers on every launch.

## Why we stopped here

We could keep going. Plausible next steps:

- **Build an SSDP/mDNS relay** on the PC that bridges the hotspot subnet and the home subnet for `239.255.255.250:1900` traffic. Doable in ~100 lines of Python, probably a weekend project given how flaky multicast is in practice.
- **ARP poison the home Wi-Fi** so the iPhone sends HAP traffic to the PC's MAC. Aggressive, fragile, only worth it for a single capture session.
- **Run an Android emulator on the PC** with the Android APK — eliminates iOS-specific networking complexity entirely. The Android client has the same protocol surface we're trying to capture.
- **Patch the iOS WireGuard app** to disable iOS's local-subnet bypass. Requires a jailbroken iPhone or sideloading via dev cert.
- **Wireshark on the home router** running custom firmware (OpenWRT). Most "proper" approach but requires hardware support.

None of these are infeasible. All of them are several hours of additional rabbit-hole when the actual goal — understanding what's missing from our `downloadByDiff` requests — is achievable through a completely different angle that doesn't require *any* of this networking gymnastics:

**Reading the HAP's internal HDD directly.**

A SATA-to-USB dock arrived in the mail this week. With the HDD pulled and mounted read-only on the PC, we get:

- The complete Python source of the Sony control daemon
- Every method's exact implementation
- Every parameter shape, every code path, every response format
- The Tokyo Cabinet DB schema in actual practice (not just the demo SQLite from the APK)
- Init scripts (to find out if Dropbear SSH can be re-enabled at boot)
- `/etc/shadow` (the root password hash, for later when we want a live shell)

Strictly more information than mitmproxy could ever yield, with strictly less network complexity. The mitmproxy work isn't wasted — the setup documentation lives at [`mitmproxy-ios-setup.md`](mitmproxy-ios-setup.md), and the path is proven up to and including the HAP's plain HTTP traffic from the iPhone. Anyone with a multicast relay handy can finish this. We just won't.

## What we did learn

Time spent on this attempt: ~3 hours across two interactive sessions. Worth documenting because the failure modes are non-obvious:

- **iOS local-subnet bypass is non-overridable from `AllowedIPs`**. If you need to capture LAN traffic from an iPhone, you must either (a) put the iPhone on a different subnet *and* hope the target app uses unicast discovery, or (b) intercept upstream of the iPhone (router / managed switch).
- **Sony's HDD Audio Remote app is discovery-only**, no manual-IP fallback. Confirmed by APK deep-dive: there's no "Enter HAP IP manually" code path. Discovery via SSDP is the only entry.
- **Windows Mobile Hotspot is a working tool for this kind of subnet-isolation trick**. It survives DST changes, doesn't need any special drivers, and IP-forwards correctly out of the box once the firewall is opened.
- **mitmproxy 12's WireGuard mode is solid** for any non-discovery-gated app. It's our recommended setup now for capturing any audio/IoT app that simply talks unicast HTTP/HTTPS to a known IP.
- **`PersistentKeepalive = 25` in the WireGuard client config** keeps the NAT mapping alive on the PC side. Skip it and you get a tunnel that dies silently after 30-60s of idle.
- **The Windows Mobile Hotspot interface is named `Connexion au réseau local* 2`** on a French Windows 11. The asterisk is real and breaks `Where-Object { $_.InterfaceAlias -like 'Mobile Hotspot' }` if you're not careful. Use the IP `192.168.137.1` as the unambiguous identifier instead.
- **Sony's `editContentInfo` favorites endpoint, `setSoundSettings`, `setSleepTimer`, `setRepeatType`, `setShuffleType` and friends are all live-validated** even without mitmproxy iOS. We didn't need this attempt for those — the APK decompile + fuzzing gave us everything.

## How to undo this setup

If you tried this and want to clean up, in order:

### On the PC

```powershell
# 1. Stop mitmweb (Ctrl+C in its terminal).

# 2. Disable Mobile Hotspot
#    Settings → Network & Internet → Mobile hotspot → toggle off
#    (no clean CLI for the modern Mobile Hotspot; the Settings UI is the only option)

# 3. Remove the WireGuard firewall rule (needs admin)
Start-Process powershell -Verb RunAs -ArgumentList '-Command',`
  "Remove-NetFirewallRule -DisplayName 'mitmproxy WireGuard (UDP 51820 inbound)'"

# 4. Optional: delete the .conf and QR files we put on the Desktop
Remove-Item "$env:USERPROFILE\Desktop\hap-mitmproxy*.conf" -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\Desktop\hap-wireguard*-qr.png" -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\Desktop\hap-mitmproxy-hotspot.conf" -ErrorAction SilentlyContinue
```

mitmproxy itself can stay installed — it's useful for plenty of other things (any non-discovery-gated app on iOS / Android / desktop). We don't recommend uninstalling.

### On the iPhone

1. **WireGuard app** → Edit → delete every tunnel we created (the `−` button + Delete) → Done.
2. **Settings → Wi-Fi** → tap the (i) next to the home Wi-Fi → **Configure Proxy** → make sure it's set to **Off**. (We already set this earlier but worth confirming.)
3. **Settings → Wi-Fi** → find the hotspot SSID (e.g. `PC-GUILLAIN 2547`) → tap the (i) → **Forget This Network** → confirm. This stops the iPhone from auto-joining when the PC's hotspot comes back up.
4. (Optional) Uninstall the WireGuard app if you don't use it for anything else. It's small (~20 MB), harmless to leave installed, and the next time someone wants to try this it's already there.

That's it. The iPhone is back to its baseline.

## When to revisit this

If a future contributor still needs the iOS protocol specifically (not just "the Sony protocol", which we'll have entirely from the HDD), the bar to clear is **make SSDP traverse the hotspot/home boundary**. The simplest path:

- A small Python script that listens for SSDP `M-SEARCH` on the hotspot interface, forwards them to the home subnet, and relays the replies back.
- ~50-100 lines of Python with `socket` + `struct`.
- The harder part is keeping the M-SEARCH source IP coherent so the HAP's `LOCATION` header points to a reachable address from the hotspot subnet (probably needs to rewrite the reply to advertise the PC's IP, with mitmproxy then doing a reverse proxy).

If anyone wants to take this on, fork the repo and put it under `tools/ssdp-relay.py`. The mitmproxy setup documented in [`mitmproxy-ios-setup.md`](mitmproxy-ios-setup.md) is otherwise ready to be picked up exactly where we left off.

## One more thing — honest takeaway

The proxy bypass + multicast discovery combo isn't intentional defense on Sony's part. It's just what happens when you build an iOS app the way you built an iOS app in 2014. URLSession was newish, low-level CFNetwork was still common, multicast discovery was standard for "find a device on the LAN" — and none of those layers compose well with modern privacy-defaulting iOS networking.

The result, accidentally, is an app that's quite hard to MITM from a curious owner with a perfectly legitimate reason to do so. We respect that as a happy accident, and we go around it by reading the device's own filesystem instead. Different game.

If you tried this and got further than we did: please document and PR. Knowledge of dead-end approaches is genuinely useful too.
