# Community findings

Verified contributions from HAP owners, folded into the record. Each entry is dated,
credited to its author, and cross-linked to the page where its detail lives. Findings are
reproduced here only after we have checked them ourselves; where we could not verify a
point, it says so.

---

## 2026-11-03 — @jimsmt (HAP-S1): the OTA firmware URL, and four findings alongside it

Contributed in [issue #6](https://github.com/Guillain-RDCDE/HAP-Revival/issues/6), with a
blog post written five years earlier:
<https://akb.pages.dev/posts/fix-sony-hap-s1-tunnein-https-playback-issue/> (Chinese).

### 1. The firmware blob is downloadable after all

For a HAP-S1 (China region), @jimsmt captured the OTA firmware URL years ago by sniffing
his router during a Network Update:

```text
http://hav.update.sony.net/HAP/PRD/1G/CN/10000201_4bcc0000.bin
```

**Verified still live on 2026-11-03** (`HTTP/1.1 200`, `Content-Length: 77776256`,
`Last-Modified: Wed, 13 Jan 2021`). The size — **77,776,256 bytes** — matches the
**19404R** payload listed in [`07-firmware.md`](07-firmware.md) to the byte, which is strong
evidence this blob *is* 19404R for the CN region.

**This supersedes the standing claim in [`07-firmware.md`](07-firmware.md)** that no copy of
any HAP firmware exists anywhere public. One does now, and it is in hand.

**Our analysis of the blob (2026-11-03).** It is encrypted, and the encryption has a clear
fingerprint.

Its Shannon entropy is **8.00 bits/byte** across the whole file; the byte histogram is flat;
there is no header, no magic bytes, no readable strings, and no footer. It is not merely
compressed — compressed data would still carry its container's magic bytes (gzip, xz, lz4,
zstd), and none are present.

More telling, the file length is an **exact multiple of 16 bytes** (4,861,016 blocks), and
**12,065 of those 16-byte blocks are duplicates** (one block recurs 106 times). For random
data that count would be essentially zero. Repeated ciphertext blocks are the signature of a
**block cipher in ECB mode** (likely AES): identical plaintext regions — such as the
zero-filled stretches of the filesystem — encrypt to identical ciphertext blocks.

The decryption key is **not** in the file. On these players it lives on the device, in the
updater that unpacks the blob. So without the key the blob stays sealed, and no amount of
analysis gets around that — which is the point of AES. The blob is therefore kept as the
*locked box*: the day a root shell yields the key (or the routine that uses it), it can be
decrypted offline. See the UART path in [`10-uart-console.md`](10-uart-console.md) and the
NAND route in [`14-nand-extract.md`](14-nand-extract.md).

### 2. Firmware rollback via Special Mode

With the player **off**, hold **HOME + POWER**; the player boots into a Special Mode that
offers a rollback to the *previous* firmware version. (This is distinct from the HOME + BACK
service/test mode documented in [`05-diag-modes.md`](05-diag-modes.md).) A clean, reproducible
way to step a unit back one firmware revision.

### 3. Why TuneIn radio broke: expired root certificates

@jimsmt diagnosed the dead-radio symptom with `tcpdump`: stations whose stream URL is
**https** fail with a network error, while **http** streams play. The cause is the player's
**stale root-certificate store** — it can no longer complete a modern HTTPS handshake. This
is a general finding: it affects *any* HTTPS the player attempts, not just radio.

His working fix, for reference: an **nginx** reverse proxy bound to `opml.radiotime.com` with
`subs_filter 'https' 'http'`, rewriting the stream URLs TuneIn returns, with the player
pointed at the proxy via the router's **dnsmasq**. This is a complement to the route already
documented here — the player speaks to TuneIn's public API in the clear, so one can answer it
the same way (see [`03-network-api.md`](03-network-api.md)).

### 4. A UART caution from the S1

Five years ago @jimsmt opened his HAP-S1 and probed its internal UART header: **VCC and RX
read a healthy 3.3 V, but TX measured only 0.2 V** — he suspected the debug transmit line had
been deliberately disabled. This was an *internal* header on a HAP-**S1**, not the
HAP-**Z1ES** rear-panel CN4007 route we document, so it is a caution, not a verdict.

Practical consequence for our UART work ([`10-uart-console.md`](10-uart-console.md)): when the
adapter is connected, **open the terminal before powering the unit on** and watch for the boot
log. If it scrolls, the console output is alive. If nothing comes out, **measure the TX pin at
rest** before assuming a wiring fault — the line may be gated as it was on his S1.

### 5. Sony's GPL source is still online — and shared across both models

@jimsmt's post points at <https://oss.sony.net/Products/Linux/Audio/HAP-S1.html>, confirmed
live on 2026-11-03. The page is titled **"HAP-S1, HAP-Z1ES(19404R)"** — one source bundle for
both players — and includes U-Boot 2012.04, the full OpenWrt trunk (build 35385),
Linux 3.0.35, Dropbear 2012.55, OpenSSL 1.0.2u, Samba 3.0.37, lighttpd 1.4.35, and a
`HowToBuild.txt`. The SoC is an NXP **i.MX6 Dual** (Cortex-A9). This matches and re-confirms
the Tier-1 entry in [`08-prior-art.md`](08-prior-art.md); the presence of Dropbear in the
build is why a root shell can enable SSH, and the i.MX6 boot ROM's serial-download mode is a
possible hardware route independent of the debug UART.

**Note:** a port scan of his S1 showed only **445/139** (SMB) and **60100 / 60300 / 60400**
(the JSON-RPC API) open, server `lighttpd` — **no port 22**. SSH is present in the firmware
but not listening by default, which is why device access is capped at the SMB and API surface
until a console yields root.
