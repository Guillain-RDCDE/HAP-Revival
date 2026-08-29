# Gotchas — where doing the correct thing breaks

Every entry here is a case where the **generally right** move is the **locally wrong** one. This
player is a 2014 embedded Linux box with a 2014 HTTP stack, and it punishes several habits that are
correct everywhere else.

This page exists because of a specific incident. A contributor's browser remote worked for months,
then stopped after he let an AI refactor the JavaScript. The refactor had added
`Content-Type: application/json` to a JSON POST — an unambiguously correct thing to add, and the one
thing this device cannot tolerate from a browser. He reverted and it worked again.

The lesson generalises beyond his case: any tidy-up — by hand, by a linter, by a tool — will tend
to move code toward what is correct in general, and this player punishes several of those moves.
It is not hypothetical either. The same class of mistake has already cost this repository once
(see [the green-tests problem](#the-green-tests-problem) below).

**If you are tidying, refactoring or "fixing" client code, read this first.**

---

## 1. Never set `Content-Type` on a browser request

**Correct in general.** Declaring the media type of a JSON body is basic hygiene.

**Wrong here.** It turns a *simple* CORS request into one requiring a preflight. The player answers
the preflight `200`, echoes your `Origin`, advertises `GET, POST, OPTIONS` — and never sends
`Access-Control-Allow-Headers`. The browser therefore rejects the preflight and never sends the real
request. What you see is a generic network error that looks exactly like the device being off.

**Do instead.** Send no `Content-Type` from a browser. The player parses the JSON body regardless —
verified. Non-browser clients (`curl`, Python, our own tools) are unaffected, and code that goes
through a local proxy such as [`webui.py`](../tools/webui.py) is immune.

Confirmed twice, independently: by probing the CORS headers directly, and by the script's author
arriving at the same one-line fix without seeing our diagnosis.

---

## 2. Never send `Expect: 100-continue`

**Correct in general.** It saves uploading a large body the server will reject.

**Wrong here.** The player returns `417 Expectation Failed`. It only bites requests **with a body**,
so reads work and writes fail — which reads like a syntax error in your JSON and sends you looking
in the wrong place entirely. It cost a contributor an evening.

**Do instead.** Disable it. Python's stdlib never sends it. `requests`:
`session.headers.update({'Expect': ''})`. PowerShell:
`[System.Net.ServicePointManager]::Expect100Continue = $false` — and it must run **before the first
request to that host**, because `ServicePoint` copies the value at creation and ignores later
changes. Setting it after a GET silently does nothing; that produced a false pass in our own testing.

---

## 3. Never issue requests concurrently

**Correct in general.** Parallel requests are faster, and a probe sweep is the obvious place for
them.

**Wrong here.** The daemon handles one request at a time. A slow request makes **every other
endpoint** time out until it completes — including endpoints that answered a second earlier. Anything
under `/sony/contentdb/v100/…` takes 5–57 s cold, so a sweep that touches it poisons everything after
it.

**Do instead.** Probe sequentially, with a known-good request (`…/v100/powerstate`) as a health check
between steps. This nearly cost us the entire push-notification discovery: the first attempt at the
subscription endpoint reported a timeout that was pure collateral damage.

---

## 4. Never assume a uniform API version

**Correct in general.** One version per API.

**Wrong here.** Each JSON-RPC method advertises its own, and the wrong one returns
`[14, "Unsupported Version"]`. `getSourceList` is `1.0` only; `getPlayingContentInfo` is `1.2`;
`setPlayContent` is `1.1`. There is no rule — see
[`research/api-method-catalog.md`](../research/api-method-catalog.md) for the working version of each.

---

## 5. Never trust a successful-looking reply

**Correct in general.** A 200 means it worked.

**Wrong here.** This API acknowledges things it does not do:

- `playbackControlMode` is **not validated** — send `"bogusmode"` and the device echoes it back in a
  perfectly well-formed response.
- A successful write returns `200 {}`. No confirmation, and indistinguishable from a write that was
  ignored.
- `createPlayingListAndQuickPlay` returns a plausible playlist URI while creating an **empty queue**
  that plays nothing.
- `…/playinginfo` returns `500` when the queue is merely empty, and `…/volumelevel` returns `500`
  permanently on a Z1ES. Reading either as "device is asleep" — which the Crestron module does —
  reports a live player as offline.

**Do instead.** Read the state back after every write. `play_station(..., verify=True)` does exactly
that, and it exists because the device will happily report success for a station it never started.

---

## 6. Never send `x-hap-device-id` on a `netService` browse

**Correct in general.** Sony's own Android client sends this header on every call, and some
`database` methods require it. Copying that looks like the safe choice.

**Wrong here.** With the header, `getContentList` on a `netService:` URI returns `[1, "Any"]`.
Without it, the same call returns the full TuneIn directory. Nothing in the error hints at a header.

**Do instead.** Omit it for netService browsing — `hap_client.call(..., send_client_id=False)`.

This one cost days. Combined with `scope: "directory"` (also invalid for TuneIn, also `[1, "Any"]`),
it produced three separate published theories about why internet radio was "gone", all wrong. The
service had been working the whole time.

**Corollary worth internalising: `[1, "Any"]` is not a diagnosis.** It is this device's generic
refusal, observed for at least three unrelated causes. Never build a theory on it.

---

## 7. Never keep a short HTTP timeout

**Correct in general.** A few seconds is a generous ceiling for a LAN request, and a short timeout
keeps a probe sweep from hanging on a dead endpoint.

**Wrong here.** Cold `/sony/contentdb/v100/…` requests take **5 to 57 seconds** on `0019404R`. Every
tool in this repository used 6 s, so those endpoints failed every single time — no status, no body.
We read that as a dead API and documented it as one for months. It is not dead; it is slow, and it
warms up (`audio/genres`: 6.2 s → 2.0 s → 1.7 s on three consecutive calls).

**Do instead.** Allow at least **90 s** for anything under `contentdb`, and probe sequentially
(see gotcha 3). If a request fails at exactly your timeout, suspect your timeout.

**The corollary is the general one.** A failure that always arrives at the value you chose is
evidence about your client, not about the device. The theory that made this so durable was built on
cover art answering in 0.2 s while album metadata "hung" — a real, reproducible difference that we
explained with a missing database, when the actual dividing line was our own six-second ceiling.
Measurements: [`../research/notes/2026-08-29-contentdb-was-never-dead.md`](../research/notes/2026-08-29-contentdb-was-never-dead.md).

---

## 8. Never assume the response is valid UTF-8

**Correct in general.** A JSON body is UTF-8. `json.loads(response.read())` is the obvious line to
write, and it is right almost everywhere.

**Wrong here.** The player does not re-encode tags — it hands back whatever bytes its catalog holds.
Most of a response is clean UTF-8, but a track or artist imported with Latin-1 tags carries a bare
high byte in the middle of it. Measured 2026-08-29: on a 343 KB page of 5000 artists, **exactly one
name** — `Zé Roberto`, artistid 16712 — held a raw `0xE9`. `json.loads` on the bytes raises
`UnicodeDecodeError` and **the entire page is lost over one character**. During a harvest that walks
the whole library, one such name anywhere aborts the run.

**Do instead.** Decode strictly first, and fall back only for the bytes that actually fail:

```python
def _latin1_fallback(exc):
    return exc.object[exc.start:exc.end].decode("latin-1"), exc.end

codecs.register_error("hap_mixed", _latin1_fallback)

try:
    text = raw.decode("utf-8")
except UnicodeDecodeError:
    text = raw.decode("utf-8", "hap_mixed")
```

This is what [`tools/hap_library.py`](../tools/hap_library.py) does. Note what it does **not** do:
`errors="replace"` would turn `Zé Roberto` into `Z� Roberto` and quietly corrupt the name;
decoding the whole body as Latin-1 would mojibake every correctly-encoded name in it. Only the
failing bytes get the fallback, and Latin-1 is the right guess for them because that is what those
tags were written in.

---

## 9. Never reuse one SMB connection across two long listings

**Correct in general.** Opening one connection and reusing it is the efficient, tidy thing to do,
and reconnecting per unit of work looks wasteful.

**Wrong here.** A long recursive listing desyncs pysmb's SMB1 session. After it, every `listPath`
on that connection fails — and because a crawler has to tolerate the odd unreadable folder, those
failures get swallowed and you are left with a **partial index that looks complete**. Measured
2026-08-29: crawling `HAP_Internal` (27 263 files) then `HAP_External` on the same connection
returned **5 931** files for the second share. A fresh connection per share returned **66 733**.
Nothing errored; the number was simply wrong by a factor of eleven.

**Do instead.** One connection per share, as [`tools/hap_fixit.py`](../tools/hap_fixit.py) does —
and **count the folders you failed to list**, then say so. A crawl that quietly skips a tenth of the
disk is worse than one that refuses to finish.

The only reason this was caught is that an earlier one-off script had already measured the same
share at 66 716 files. Without that number to compare against, 5 931 looks perfectly plausible.

---

## The green-tests problem

The above makes ordinary unit tests weaker than they look here, and we proved it.

`hap_client.radio_registration()` was covered by tests that replaced `HAP.call` with a fake. The
fake returned `{"result": [{...}]}`. The real `HAP.call` **unwraps** the single-element `result`
list and returns the inner dict. So the client read nothing, the tests all passed, and the bug only
surfaced when the CLI printed an empty PIN against the real device.

The test double encoded the author's assumption instead of the real contract, and then confirmed it.

**Two rules follow.**

1. A test double must mirror the **actual** contract of the thing it replaces. If you are not sure
   what that contract is, go and read it — do not infer it from the code you are writing.
2. **Client changes get a live check before they ship.** Run
   [`tools/smoke_live.py`](../tools/smoke_live.py) against a real player. It asserts that values
   come back *populated*, not merely that nothing raised — which is the exact failure the unit tests
   missed.

The unit suite still matters; it is fast, offline, and runs in CI. It just cannot see this class of
bug, and no amount of adding to it will change that.
