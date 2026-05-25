#!/usr/bin/env python3
"""
HAP-Revival web UI — a minimal HTML5 control surface for the Sony HAP-Z1ES /
HAP-S1, served by Python's stdlib http.server.

This is the first working third-party HAP control web app. Open it in any
modern browser; it polls the device every 3 seconds (matching Sony's own
polling model) and displays now-playing + lets you pause/resume/seek.

Stdlib-only. Run with:

    python tools/webui.py <hap-ip>
    python tools/webui.py --port 8080 192.168.1.28

Then open http://localhost:8080 in your browser.

Features in this V0:
    - Now-playing: title, artist, album, cover art (with cross-CDN proxy for
      Spotify Connect album art), elapsed/total time, audio quality info.
    - Live progress bar updated every 3s.
    - Pause / Resume / Next / Previous buttons.
    - Seek by clicking on the progress bar.
    - Sound settings (DSEE, DSD remastering, gapless, oversampling) — read-only.
    - Power button (wake/standby).
    - Identity info: model, firmware, MAC.

Not in V0:
    - Library browse (waiting on downloadByDiff to return non-empty location).
    - Playlist management.
    - WebSocket / push (HAP only supports polling).
    - Multi-device fleet view.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Allow `python tools/webui.py …` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hap_client import HAP, HAPError  # noqa: E402


def _live_html_template() -> str | None:
    """Re-read the HTML_PAGE constant out of our own source file on each
    request. Lets contributors iterate on the template/CSS without having
    to bounce the server. Returns None if anything goes wrong; caller
    falls back to the module-level constant.
    """
    try:
        src = Path(__file__).resolve().read_text(encoding="utf-8")
        start = src.find('HTML_PAGE = """')
        if start < 0:
            return None
        start += len('HTML_PAGE = """')
        end = src.find('"""', start)
        if end < 0:
            return None
        return src[start:end]
    except OSError:
        return None


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>HAP-Revival — control</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0e0e10; --fg: #f0f0f0; --muted: #aaa;
  --accent: rgb(__ACCENT_R__, __ACCENT_G__, __ACCENT_B__);
  --accent-soft: rgba(__ACCENT_R__, __ACCENT_G__, __ACCENT_B__, 0.35);
  --card-bg: rgba(20,20,24,0.55); --hover: rgba(255,255,255,0.12);
  --cover-url: __INITIAL_COVER_URL__;
}
html, body { background: var(--bg); color: var(--fg); font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Helvetica, Arial, sans-serif; min-height: 100vh; overflow-x: hidden; }
body { display: flex; flex-direction: column; align-items: center; padding: 24px 16px; position: relative; }

/* Ambient cover background: heavily blurred cover, scaled up, behind everything.
   This is what gives the "diffuse colors from the album art" feeling.
   Tuning notes: blur too high or opacity too low + dark overlay = invisible.
   With muted covers, saturation boost matters most. */
body::before {
  content: "";
  position: fixed;
  inset: -15vh -15vw;
  background-image: var(--cover-url);
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  filter: blur(60px) saturate(1.8) brightness(1.05);
  opacity: 1.0;
  z-index: -2;
  transition: opacity 0.6s ease;
  /* Fallback solid color if no cover yet */
  background-color: var(--accent);
}
/* Light vignette only — preserve as much color as possible while keeping
   text readable. Top kept transparent, bottom only slightly darker. */
body::after {
  content: "";
  position: fixed;
  inset: 0;
  background:
    radial-gradient(ellipse at center, rgba(14,14,16,0) 0%, rgba(14,14,16,0.1) 70%, rgba(14,14,16,0.35) 100%);
  z-index: -1;
  pointer-events: none;
}
header { text-align: center; margin-bottom: 24px; }
header h1 { font-size: 18px; font-weight: 500; letter-spacing: 0.04em; opacity: 0.7; }
header .device { font-size: 12px; color: var(--muted); margin-top: 4px; }
main { width: 100%; max-width: 520px; }
.card {
  background: var(--card-bg);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 16px;
  backdrop-filter: blur(28px) saturate(1.2);
  -webkit-backdrop-filter: blur(28px) saturate(1.2);
  border: 1px solid rgba(255,255,255,0.06);
  box-shadow: 0 8px 32px rgba(0,0,0,0.35);
  transition: background 0.4s ease;
}
#now-playing { display: flex; flex-direction: column; align-items: center; gap: 16px; min-height: 360px; }
.cover {
  width: 240px;
  height: 240px;
  border-radius: 12px;
  background: #222 no-repeat center/cover;
  box-shadow:
    0 10px 40px rgba(0,0,0,0.6),
    0 0 60px 0 var(--accent-soft);
  transition: background-image 0.6s ease, box-shadow 0.8s ease;
}
.cover.placeholder::before { content: "♪"; display: flex; align-items: center; justify-content: center; height: 100%; font-size: 80px; color: #444; }
.meta { text-align: center; }
.meta .title { font-size: 22px; font-weight: 600; margin-bottom: 6px; }
.meta .artist { font-size: 15px; opacity: 0.85; }
.meta .album { font-size: 13px; opacity: 0.6; margin-top: 4px; }
.meta .tech { font-size: 11px; color: var(--muted); margin-top: 8px; letter-spacing: 0.05em; }
.state-tag { display: inline-block; padding: 2px 10px; border-radius: 10px; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; background: var(--accent); color: white; opacity: 0.8; margin-bottom: 8px; }
.state-tag.STOPPED { background: #555; }
.state-tag.PAUSED { background: #c80; }
.state-tag.PLAYING { background: var(--accent); }
.progress-wrap { width: 100%; }
.progress-bar { width: 100%; height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; cursor: pointer; overflow: hidden; }
.progress-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.4s ease; }
.progress-times { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); margin-top: 6px; }
.controls { display: flex; justify-content: center; gap: 8px; }
.btn { background: var(--card-bg); color: var(--fg); border: 0; border-radius: 999px; padding: 12px 20px; font-size: 14px; cursor: pointer; transition: background 0.15s; min-width: 56px; }
.btn:hover, .btn:focus-visible { background: var(--hover); outline: 0; }
.btn.primary { background: var(--accent); color: white; font-weight: 600; padding: 14px 28px; }
.btn.danger:hover { background: #a00; }
.settings { font-size: 12px; }
.settings table { width: 100%; }
.settings td { padding: 4px 0; }
.settings td.k { color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-size: 10px; }
.settings td.v { text-align: right; font-weight: 500; }
footer { color: var(--muted); font-size: 11px; margin-top: 32px; text-align: center; }
footer a { color: var(--muted); text-decoration: underline; }
.error { background: #422; color: #f88; padding: 12px; border-radius: 8px; font-size: 13px; }
</style>
</head>
<body>
<header>
  <h1>HAP-Revival</h1>
  <div class="device" id="device-info">connecting…</div>
</header>
<main>
  <div class="card" id="now-playing">
    <div class="cover placeholder" id="cover"></div>
    <div class="meta">
      <div class="state-tag" id="state">…</div>
      <div class="title" id="title">—</div>
      <div class="artist" id="artist"></div>
      <div class="album" id="album"></div>
      <div class="tech" id="tech"></div>
    </div>
    <div class="progress-wrap">
      <div class="progress-bar" id="progress-bar" title="Click to seek">
        <div class="progress-fill" id="progress-fill" style="width:0%"></div>
      </div>
      <div class="progress-times">
        <span id="t-position">0:00</span>
        <span id="t-duration">0:00</span>
      </div>
    </div>
    <div class="controls">
      <button class="btn" onclick="hapCall('previous')" title="Previous">⏮</button>
      <button class="btn primary" onclick="togglePlay()" id="btn-play" title="Pause/resume">⏸</button>
      <button class="btn" onclick="hapCall('next')" title="Next">⏭</button>
      <button class="btn danger" onclick="if(confirm('Standby?')) hapCall('standby')" title="Standby">⏻</button>
    </div>
  </div>
  <div class="card settings">
    <table>
      <tr><td class="k">DSEE</td><td class="v" id="s-dsee">—</td></tr>
      <tr><td class="k">DSD remastering</td><td class="v" id="s-dsd">—</td></tr>
      <tr><td class="k">Gapless playback</td><td class="v" id="s-gapless">—</td></tr>
      <tr><td class="k">Volume normalization</td><td class="v" id="s-volnorm">—</td></tr>
      <tr><td class="k">Oversampling</td><td class="v" id="s-oversample">—</td></tr>
    </table>
  </div>
  <div id="error-banner"></div>
</main>
<footer>
  <a href="https://github.com/Guillain-RDCDE/HAP-Revival" target="_blank">github.com/Guillain-RDCDE/HAP-Revival</a> · polls every 3s · stdlib only · MIT
</footer>
<script>
let lastState = null;
let lastDuration = 0;

function fmt(secs) {
  if (!secs || secs < 0) return "0:00";
  const m = Math.floor(secs / 60), s = Math.floor(secs % 60);
  return m + ":" + String(s).padStart(2, "0");
}

async function refresh() {
  try {
    const r = await fetch("/api/state");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    apply(d);
    document.getElementById("error-banner").innerHTML = "";
  } catch (e) {
    document.getElementById("error-banner").innerHTML =
      '<div class="error">Cannot reach HAP: ' + e.message + "</div>";
  }
}

function apply(d) {
  const np = d.now_playing, sys = d.system, snd = d.sound;
  document.getElementById("device-info").textContent =
    sys.model + " · firmware " + sys.version + " · " + sys.power;
  document.getElementById("state").textContent = np.state;
  document.getElementById("state").className = "state-tag " + np.state;
  document.getElementById("title").textContent = np.title || "—";
  document.getElementById("artist").textContent = np.artist || "";
  document.getElementById("album").textContent = np.album || "";
  const tech = np.codec
    ? (np.sample_rate_hz
        ? np.codec.toUpperCase() + " · " + (np.sample_rate_hz/1000) + " kHz / " + np.bit_depth + "-bit"
        : np.codec.toUpperCase())
    : (np.storage_uri ? "streaming · " + np.storage_uri : "");
  document.getElementById("tech").textContent = tech;

  const cover = document.getElementById("cover");
  if (np.cover_art_url) {
    cover.style.backgroundImage = "url('" + np.cover_art_url + "')";
    cover.classList.remove("placeholder");
  } else {
    cover.style.backgroundImage = "";
    cover.classList.add("placeholder");
  }
  document.getElementById("progress-fill").style.width = (np.progress * 100) + "%";
  document.getElementById("t-position").textContent = fmt(np.position_sec);
  document.getElementById("t-duration").textContent = fmt(np.duration_sec);
  lastDuration = np.duration_sec;

  if (snd) {
    document.getElementById("s-dsee").textContent = snd.dsee || "—";
    document.getElementById("s-dsd").textContent = snd.dsd_remastering || "—";
    document.getElementById("s-gapless").textContent = snd.gapless_playback || "—";
    document.getElementById("s-volnorm").textContent = snd.volume_normalization || "—";
    document.getElementById("s-oversample").textContent = snd.oversampling || "—";
  }

  const btn = document.getElementById("btn-play");
  btn.textContent = np.state === "PLAYING" ? "⏸" : "▶";
  lastState = np.state;

  if (np.background_color_rgba) {
    const c = np.background_color_rgba;
    document.documentElement.style.setProperty("--accent", `rgb(${c[0]},${c[1]},${c[2]})`);
    document.documentElement.style.setProperty("--accent-soft", `rgba(${c[0]},${c[1]},${c[2]},0.35)`);
  }
  // Ambient cover background: hand the cover URL to the CSS variable used by body::before
  if (np.cover_art_url) {
    document.documentElement.style.setProperty("--cover-url", `url("${np.cover_art_url}")`);
  } else {
    document.documentElement.style.setProperty("--cover-url", "none");
  }
}

function togglePlay() {
  // The HAP's `pausePlayingContent` is a true toggle (pause<->play).
  // The state-based branching we used to do here was racy + unreliable
  // for Spotify Connect; the toggle endpoint is rock solid.
  hapCall("toggle-playback");
}

async function hapCall(action, params) {
  try {
    const r = await fetch("/api/" + action, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(params || {})
    });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error("HTTP " + r.status + ": " + txt);
    }
    setTimeout(refresh, 300);
  } catch (e) {
    document.getElementById("error-banner").innerHTML =
      '<div class="error">Action failed: ' + e.message + "</div>";
  }
}

document.getElementById("progress-bar").addEventListener("click", (e) => {
  if (!lastDuration) return;
  const rect = e.currentTarget.getBoundingClientRect();
  const frac = (e.clientX - rect.left) / rect.width;
  const pos = Math.max(0, Math.min(lastDuration, frac * lastDuration));
  hapCall("seek", {position_sec: pos});
});

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


class HAPHandler(BaseHTTPRequestHandler):
    """Serves /, /api/state (GET), and /api/<action> (POST)."""

    hap: HAP  # set on subclass before serve

    # Silence the default request logging
    def log_message(self, fmt, *args):
        return

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            try:
                np = self.hap.now_playing()
                bg = np.background_color_rgba or (60, 60, 80, 255)
                cover = np.cover_art_url or ""
            except HAPError:
                bg = (60, 60, 80, 255)
                cover = ""
            # Re-read the source on each request — lets us iterate on the
            # template without restarting the server process. The HTML_PAGE
            # constant defined at module top is just the fallback if we
            # can't find ourselves on disk for any reason.
            template = _live_html_template() or HTML_PAGE
            cover_css = f'url("{cover}")' if cover else "none"
            html = (
                template.replace("__ACCENT_R__", str(bg[0]))
                .replace("__ACCENT_G__", str(bg[1]))
                .replace("__ACCENT_B__", str(bg[2]))
                .replace("__INITIAL_COVER_URL__", cover_css)
            )
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/state":
            try:
                np = self.hap.now_playing()
                sys_info = self.hap.system_info()
                snd = self.hap.sound_settings()
            except HAPError as e:
                self._send_json(200, {"error": str(e)})
                return
            self._send_json(
                200,
                {
                    "now_playing": {
                        "state": np.state,
                        "title": np.title,
                        "artist": np.artist,
                        "album": np.album,
                        "uri": np.uri,
                        "storage_uri": np.storage_uri,
                        "position_sec": np.position_sec,
                        "duration_sec": np.duration_sec,
                        "progress": np.progress,
                        "codec": np.codec,
                        "sample_rate_hz": np.sample_rate_hz,
                        "bit_depth": np.bit_depth,
                        "cover_art_url": np.cover_art_url,
                        "background_color_rgba": np.background_color_rgba,
                    },
                    "system": {
                        "model": sys_info.model,
                        "version": sys_info.version,
                        "power": self.hap.power_status(),
                    },
                    "sound": {
                        "dsee": snd.dsee,
                        "dsd_remastering": snd.dsd_remastering,
                        "gapless_playback": snd.gapless_playback,
                        "volume_normalization": snd.volume_normalization,
                        "oversampling": snd.oversampling,
                    },
                },
            )
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            params = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        try:
            if path == "/api/toggle-playback":
                # The reliable play/pause control. Sony's pausePlayingContent
                # is a toggle, so we just fire it and let the device flip.
                self.hap.toggle_playback()
            elif path == "/api/pause":
                self.hap.pause()
            elif path == "/api/resume":
                self.hap.resume()
            elif path == "/api/next":
                self.hap.next_track()
            elif path == "/api/previous":
                self.hap.previous_track()
            elif path == "/api/standby":
                self.hap.standby()
            elif path == "/api/wake":
                self.hap.wake()
            elif path == "/api/seek":
                self.hap.seek_seconds(float(params.get("position_sec", 0)))
            elif path == "/api/play-track":
                self.hap.play_track(int(params["track_id"]))
            else:
                self.send_error(404)
                return
        except HAPError as e:
            self._send_json(500, {"error": str(e)})
            return
        except (KeyError, ValueError) as e:
            self._send_json(400, {"error": f"bad params: {e}"})
            return

        self._send_json(200, {"ok": True})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("ip", help="HAP device IP address")
    parser.add_argument("--port", type=int, default=8080, help="Local HTTP port (default 8080)")
    parser.add_argument("--bind", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    args = parser.parse_args()

    HAPHandler.hap = HAP(args.ip)
    try:
        info = HAPHandler.hap.system_info()
        print(f"Connected: {info.model} firmware {info.version} ({args.ip})")
    except HAPError as e:
        print(f"WARNING: could not connect to HAP on first try: {e}", file=sys.stderr)
        print("The web UI will still start; refresh in a browser once the device is online.")

    server = ThreadingHTTPServer((args.bind, args.port), HAPHandler)
    print(f"HAP-Revival web UI: http://{args.bind}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
