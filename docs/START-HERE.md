<!-- markdownlint-disable MD033 -->

# 🟢 Start Here — the friendly version

**New here? Not a programmer? This page is for you.**

The rest of this project is written for tinkerers and reverse-engineers, and it
*looks* intimidating — pages about kernels, serial consoles, and disk partitions.
You don't need any of that to get value out of this.

This page answers four questions, in plain language, in about five minutes.
Every section ends with a link to the deep stuff — follow it **only if you want to**.

---

## 1. What is this machine?

The Sony **HAP-Z1ES** (and its smaller sibling, the **HAP-S1**) is a music player
with a hard drive inside and a very, very good sound chip. You put your music files
on it, and it plays them beautifully into your hi-fi.

```text
   Your music             The Sony HAP                Your amp / headphones
  (FLAC, DSD…)      ┌──────────────────────────┐
  ───────────►      │  hard drive  +  hi-fi     │      ───────────►   🔊
   over Wi-Fi       │  sound chip ("the DAC")   │                  (the good sound)
                    └──────────────────────────┘
```

That's it. Music goes in, gorgeous sound comes out. The hardware is from 2014 and
still sounds better than most things you can buy new today.

---

## 2. What's the problem this project fixes?

Sony stopped updating the software in January 2021 and walked away. The machine
still sounds wonderful — but the software around it got stuck in time:

- copying music onto it is needlessly painful,
- no Tidal, no Qobuz, no Roon, no AirPlay,
- the phone remote app hasn't been touched in years and may disappear.

**HAP-Revival fixes the software — without ever touching the sound.** The part that
makes it sound amazing stays exactly as Sony built it. We only rebuild the bits
Sony abandoned.

---

## 3. What can I do *today*?

Two things, both safe, no soldering, no risk to your device:

```text
  🎵  Copy my music onto it          📱  Control it like a phone app
  ┌────────────────────────┐        ┌────────────────────────┐
  │  HAP Sync — one .exe    │        │  play / pause / info    │
  │  one click, Windows     │        │  cover art, settings    │
  │  finds the HAP for you  │        │  add to home screen 📲  │
  └────────────────────────┘        └────────────────────────┘
```

- **🎵 HAP Sync** — a one-click Windows app that copies your music onto the HAP and
  skips the files it can't use. [Download it here.](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest/download/HapSync.exe)
- **📱 Control app** — control the HAP from any browser, and on an **iPhone or iPad
  you can add it to the home screen** so it opens full-screen like a real app (no App
  Store needed). [How to install it.](13-control-app.md)

> ✅ **Nothing here can break your device.** These tools only *read* information and
> control playback — the same things the buttons on the front panel already do.

→ Step-by-step music copying guide: [docs/12-music-sync.md](12-music-sync.md)
→ Put the remote on your phone: [docs/13-control-app.md](13-control-app.md)

---

## 4. How deep do I want to go?

There are three levels. **You can happily stay at Level 1 forever** — most people will.

```text
  Level 1 — I just listen     →  copy my music, use the browser remote
  Level 2 — I tinker          →  swap the hard drive, explore the settings
  Level 3 — I hack            →  open the case, build a new operating system
                                  (experts only — this is the rest of the repo)
```

The mountain of technical pages you see in this project is **all Level 3**. It exists
so that, one day, the HAP can do modern streaming and run forever. You don't have to
read any of it to enjoy the two tools above.

---

## Mini-glossary — scary words, defused

The technical docs throw these around. Here's all you need to know:

| Word | In plain English |
|---|---|
| **DAC** | The hi-fi sound chip inside — the reason the HAP sounds so good. |
| **API** | The "remote-control language" the HAP speaks over the network. Our tools speak it for you. |
| **SMB** | The (old, fussy) way Windows copies files to the HAP. HAP Sync handles it so you don't have to. |
| **Firmware** | The HAP's built-in software — the part Sony froze in 2021. |
| **UART** | A tiny socket inside the case that experts use to get under the hood. Level 3 only. |
| **NAND** | The chip where the HAP keeps its own software. Level 3 only. |

---

## Where to go next

- Just want to **use** it? → grab [HAP Sync](https://github.com/Guillain-RDCDE/HAP-Revival/releases/latest/download/HapSync.exe) and read the [music guide](12-music-sync.md). You're done.
- Curious **why** the project exists? → the [README](../README.md#why-the-project-exists).
- Ready for **Level 3**? → the full [documentation index](../README.md#documentation). Take your time; it'll still be here.

*Welcome aboard. It's a music project pretending to be a software project — and you're here for the music.* 🎶
