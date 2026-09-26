# Amplifier control — why it is infrared, and where the network fits

The HAP-Z1ES is a **source**, not an amplifier. It feeds a separate amp over analog RCA or XLR, and
that amp does the loudness. So the player needs a way to power the amp on and set its volume without
you reaching for a second remote. Sony's answer, the one that actually ships, is **infrared**. That
surprises people — infrared on a hi-fi component of this class sounds wrong — so this page documents
the mechanism, why it is not the mistake it looks like, and how it relates to the network service
(`MusicConnect`) that a widely-copied online description gets wrong.

This is a HAP-Z1ES page. The HAP-S1 is different: it has a built-in amplifier (2× LM3876 + NJW1194
electronic volume, see [`01-hardware.md`](01-hardware.md)), so it controls its own volume and does
not need any of this.

## The problem to solve: the player has no analog volume

The HAP-Z1ES has **no analog volume stage**. It does have a front-panel volume and a fade feature,
but those are applied in the **digital domain, before the DAC**, through the Forza `ATT`
(attenuation) and `FADE` ioctls ([`11-audio-path.md`](11-audio-path.md)). Digital attenuation throws
away resolution as you turn it down — the lower the level, the fewer bits reach the converter. On a
hi-res chassis built around dual PCM1795 DACs, that is exactly what you do not want to lean on.

The audiophile configuration is therefore to run the HAP-Z1ES at **fixed, full output** and let the
**amplifier** attenuate in the analog domain, where volume is a resistor network or a good electronic
volume chip and costs no resolution. That is the better-sounding path — and it is the reason amp
control exists at all: once the player deliberately does *not* do volume itself, something has to
command the amp, and it should be the player's own remote or app, not a separate one.

## What Sony ships: Amp Control Settings, over infrared

The feature is called **Amp Control Settings** in the menu. Configured, it lets the HAP-Z1ES remote
and the HDD Audio Remote app **power the amplifier on and off, change its volume, and mute it**,
alongside the player. The transport is infrared, by one of two physical links (Sony Help Guide,
[Prep 1. Connecting an amplifier](https://helpguide.sony.net/ha/hapz1es/v1/en/contents/TP0000221951.html)
and [Operating a Sony amplifier](https://helpguide.sony.net/ha/hapz1es/v1/en/contents/TP0000221998.html)):

- **Wired, to a Sony amp with an IR input jack.** A mono mini-plug cable from the player's
  `IR REMOTE OUT` jack to the amplifier's IR-input jack. This is a *wired* control link — infrared
  signalling carried down a cable, with no line-of-sight and nothing to aim.
- **The bundled IR blaster, for everything else.** A little emitter on a lead from `IR REMOTE OUT`,
  taped in front of the amplifier's remote sensor. This is the fallback for Sony amps without an
  IR-input jack and for **other manufacturers' amps** — which is the whole point of choosing IR.

Audio itself never touches any of this: it leaves on the analog `LINE OUT` (RCA unbalanced or XLR
balanced) cables. The IR link carries **control only**.

## "Isn't infrared absurd on a hi-fi component?"

It is the natural first reaction, and it is worth answering squarely rather than hiding, because the
confusion is instructive.

- **Control is not signal.** Infrared here does exactly what your finger on the amp's remote does:
  send "power on", "volume up", "mute". It is a command channel that runs *beside* the audio, never
  through it. The music rides the analog cables and is untouched. So there is no fidelity cost — the
  worry comes from picturing IR somewhere in the signal path, where it never is.
- **It is often a wire, not a beam.** For Sony amps the recommended link is the mono-minijack cable
  into the amp's IR-input jack — reliable, no aiming, no ambient-light problems. The blaster you tape
  to the amp is only the compatibility fallback.
- **In 2014, infrared was the only universal language.** Network control would have worked with a
  handful of specific Sony models; infrared works with essentially **every amplifier ever made,
  any brand**. Sony bundled an emitter precisely so the feature works with a non-Sony amp. For a
  source meant to sit in any existing system, that is the pragmatic, compatible choice.

Where the instinct is right: by today's standards this is dated. A device designed now would command
the amp over the network, or over HDMI-CEC, or through an ecosystem like Roon or HEOS. The HAP is
from just before that became universal. It got network control for driving **itself**
([`03-network-api.md`](03-network-api.md)); commanding a *third-party amp*, in that era, stayed on
infrared.

## The network angle: MusicConnect, and a common misconception

A description that circulates online says the player's `MusicConnect` service is a **network** link
that auto-powers a Sony ES receiver (STR-ZA and the like), selects its input, and controls its
volume over the LAN. It is worth stating precisely what is true here, because the claim is half right
and half wrong:

- **Right about the purpose.** The player really does auto-power an amp and control its volume when
  you start playback. That much is a real, shipped feature.
- **Wrong about the mechanism.** Sony documents that control as **infrared**, above. There is **no
  network amp control** anywhere in the HAP's documentation, and no Sony source names `MusicConnect`
  or ties it to specific networked receivers. The networked-ES-receiver story is unsourced and
  contradicts Sony's own IR-based amp-control pages. It reads like a plausible-sounding synthesis
  that was never checked.

What `MusicConnect` verifiably *is*, on our own unit, is documented in
[`03-network-api.md`](03-network-api.md#musicconnect--no-control-but-a-working-event-channel): a UPnP
service whose control endpoint is dead (`404`) but whose **event channel works** and pushes the
player's transport state (`PLAYING` / `PAUSED_PLAYBACK` / `STOPPED` / `NO_MEDIA_PRESENT`) over the
network. Its name and payload fit a **system-integration** role — broadcast "I am playing" so a
companion device can react — which is the same *intent* as the amp-linking above, just over the
network instead of infrared. But its actual consumer is **unconfirmed**: Sony's shipped amp control
is IR, the official app never subscribes to `MusicConnect` (it polls the JSON-RPC API every 5 s), and
the service type appears nowhere on the public web outside this repository. So it may well be an
early or partial network-integration hook that Sony left running but never wired into the product it
actually released.

## What this means for the project

- **We drive the player over the network, not by IR.** The modern control app talks to the
  ScalarWebAPI ([`03-network-api.md`](03-network-api.md)); it never needs the infrared path, which is
  strictly the player-to-amp leg.
- **`MusicConnect` is a usable signal regardless of Sony's intent.** Subscribing to its events gives
  an instant play/pause/stop indication for a responsive UI, and a clean trigger for automation —
  complementary to the UDP push mechanism we already use
  ([`03-network-api.md`](03-network-api.md#real-time-updates--push-notifications-over-udp)).
- **A future integration could bridge network to amp** — subscribe to the player's transport state
  and command a modern amp over IP or CEC — but that is new work on our side, not a latent Sony
  feature waiting to be switched on.

## Sources

- Sony Help Guide (HAP-Z1ES):
  [Prep 1. Connecting an amplifier](https://helpguide.sony.net/ha/hapz1es/v1/en/contents/TP0000221951.html),
  [Operating an external amplifier](https://helpguide.sony.net/ha/hapz1es/v1/en/contents/TP0000221983.html),
  [Operating a Sony amplifier](https://helpguide.sony.net/ha/hapz1es/v1/en/contents/TP0000221998.html).
- Digital-domain volume / no analog volume stage: [`11-audio-path.md`](11-audio-path.md).
- `MusicConnect` and the UDP push mechanism: [`03-network-api.md`](03-network-api.md).
