# Help in five minutes

You own a HAP. That already makes you rare, and it makes you more useful to this project than
another week of reading binaries.

Everything on this page is **read-only** and takes one paste each. You need no Python, no account,
and no idea how any of it works. Copy, run, send us the output — messy is fine, errors are fine, an
error is often the most useful thing you can send.

If you only do one thing, do [§1](#1-tell-us-what-your-player-is). If you have a **HAP-S1**, do
[§4](#4-hap-s1-owners-only) — we do not own one, and everything we know about it is second-hand.

---

## Before you start: three traps that will waste your evening

We hit all three, so you don't have to.

**In Windows PowerShell, type `curl.exe`, not `curl`.** Plain `curl` is an alias for a completely
different command, and `-X`, `-H` and `-d` will be misread. Reads happen to work; writes fail
confusingly.

**Run one command at a time.** The player handles a single request at a time, and one request that
hangs makes *every other endpoint* time out until it gives up. If everything suddenly goes quiet,
wait ten seconds — nothing is broken.

**Anything under `/sony/contentdb/v100/…` hangs forever.** That is a known dead API, not you. Don't
worry when it never returns.

Throughout, replace `192.168.1.28` with your player's address.

---

## 1. Tell us what your player is

```text
curl.exe http://192.168.1.28:60100/hap.xml
```

Send the whole thing (it is XML; feel free to strip your MAC address). It contains the model and the
firmware version.

**Why we want it:** we have only ever seen firmware `0019404R` and one mention of `0018120R`. If
yours is anything else, you are holding a piece of this machine's history that is not written down
anywhere public — including on Sony's own site.

---

## 2. Four readings that take one paste

```text
curl.exe http://192.168.1.28:60200/sony/contentplayer/v100/powerstate
curl.exe http://192.168.1.28:60200/sony/contentplayer/v100/playinginfo
curl.exe http://192.168.1.28:60200/sony/contentplayer/v100/externalinput
curl.exe http://192.168.1.28:60200/sony/contentplayer/v100/settings/sound/dsee
```

Each answers instantly with one line of JSON. Send all four, including any that error.

**Why we want it:** this REST API is barely documented anywhere and we have mapped it from a single
device. A second device is how we learn which parts are the machine and which parts are ours.

---

## 3. Photograph two menus

No commands, just your phone. Both menus are entered from **standby**:

| Menu | How | What to photograph |
|---|---|---|
| **Special Mode** | Hold **HOME**, press **POWER** | The whole list of entries |
| **DIAG** | Hold **HOME** + **BACK**, press **PLAY**, then **POWER** | Every submenu you can reach |

Then back out with **Restart** or **QUIT**. Neither menu writes anything by itself.

> **Do not select "Restore Previous Version".** It is a firmware downgrade. It is one-shot — the
> player keeps exactly one spare image and re-flashing burns it — and there is no recovery from a
> failed flash short of a JTAG rig. Photograph the screen; don't press Yes.

**Why we want it:** we documented Special Mode as having two entries for months. A contributor
photographed it in August 2026 and it has **five**. We are certainly still wrong about the DIAG
menu, and a photo is the whole fix.

---

## 4. HAP-S1 owners only

We do not own an S1. Everything in our documentation about it is inferred or reported.

```text
curl.exe http://192.168.1.28:60200/sony/contentplayer/v100/volumelevel
curl.exe http://192.168.1.28:60200/sony/contentplayer/v100/settings/sound/tonecontrolbass
curl.exe http://192.168.1.28:60200/sony/contentplayer/v100/settings/sound/tonecontroltreble
curl.exe http://192.168.1.28:60200/sony/contentplayer/v100/settings/sound/tonecontrolbypass
```

If `volumelevel` answers, also send us a reading at **minimum** and at **maximum** volume — the
range is not discoverable from the API and we only have one datapoint for it (`0`–`74`).

**Why we want it:** on a Z1ES `volumelevel` returns a 500, because it has no volume stage. Tone
control is S1-only and appears in no documentation but ours. You are the only people who can
confirm any of it.

---

## 5. Is your player still paired with TuneIn?

This one sends data, so the quoting matters and it differs per shell. Each form below has been run
and verified; pick your shell and paste exactly.

**Windows PowerShell** — note the `--%` right after `curl.exe`. It is not a typo; without it
PowerShell mangles the quotes and you get `illegal Request`:

```powershell
curl.exe --% -X POST http://192.168.1.28:60200/sony/avContent -H "Content-Type: application/json" -d "{\"method\":\"registerDevice\",\"id\":1,\"version\":\"1.0\",\"params\":[{\"uri\":\"netService:audio?serviceName=tunein\",\"method\":\"check\"}]}"
```

**Windows Command Prompt** (`cmd.exe`) — the same without `--%`:

```text
curl.exe -X POST http://192.168.1.28:60200/sony/avContent -H "Content-Type: application/json" -d "{\"method\":\"registerDevice\",\"id\":1,\"version\":\"1.0\",\"params\":[{\"uri\":\"netService:audio?serviceName=tunein\",\"method\":\"check\"}]}"
```

**macOS / Linux**:

```bash
curl -X POST http://192.168.1.28:60200/sony/avContent -H 'Content-Type: application/json' \
  -d '{"method":"registerDevice","id":1,"version":"1.0","params":[{"uri":"netService:audio?serviceName=tunein","method":"check"}]}'
```

You will get `{"result": [{"isRegistered": true}], "id": 1}` — or `false`.

**Why we want it, and this one is genuinely urgent.** Sony withdrew internet radio from the front
panel and both mobile apps during 2026. We believe players that were **paired before that** still
play radio, while players that never were — like ours — cannot be paired any more, because TuneIn's
pairing pages now 404. If you answer `true`, you own something that may no longer be obtainable, and
we would very much like to know how many of you there are.

If you have Python, `python tools/hap_client.py <ip> radio-status` does the same thing and is easier
to read.

---

## Sending it

Open an issue — the [hardware-finding template](../.github/ISSUE_TEMPLATE/hardware-finding.yml) or
the [API method template](../.github/ISSUE_TEMPLATE/api-method-discovered.yml) — and paste. Raw
output is better than a summary. If something errored, that *is* the result: send it.

Two things to strip if you'd rather not share them: your MAC address (in `hap.xml`) and any track
titles you consider private.

---

## What we will never ask you to do

- Open the case, unless you have said you want to.
- Flash, downgrade or reset anything.
- Install anything on the player.
- Run something whose effect we have not explained here.

Every **command** on this page was run against a real HAP-Z1ES, in the shell it is written for,
before being written down — §5 is here in three forms precisely because the first one we wrote
failed in PowerShell. The two **menu** sections we cannot test ourselves; they are transcribed from
contributors' photographs. If anything here misbehaves, that is a bug in this page — please tell us.
