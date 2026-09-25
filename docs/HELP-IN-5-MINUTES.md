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

**Anything under `/sony/contentdb/v100/…` is very slow, not broken.** A cold request can take up to
a minute. Give it `-m 90` and wait — it does answer. (We spent months believing that API was dead
because our tools gave up after 6 seconds.)

The full list, with the reasons, is in [`16-gotchas.md`](16-gotchas.md).

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

## 5. Internet radio: send us your station tree

There is no longer a radio question to ask you about pairing. Radio works on every player tested so
far, whether or not it is linked to a TuneIn account, and including stations that had never been
played on it. We used to think otherwise because our own client sent one header too many (see
[`16-gotchas.md`](16-gotchas.md) and
[`../research/notes/2026-08-25-tunein-is-alive.md`](../research/notes/2026-08-25-tunein-is-alive.md)).

What still differs from one player to the next is the **station tree**. Positions in it depend on
the player's region, so ours are no use to an owner in another one. If you have Python:

```text
python tools/hap_client.py 192.168.1.28 radio-browse root
```

Send the list it prints. No Python? Skip this one — §1 to §4 matter more.

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
before being written down. The two **menu** sections we cannot test ourselves; they are transcribed from
contributors' photographs. If anything here misbehaves, that is a bug in this page — please tell us.
