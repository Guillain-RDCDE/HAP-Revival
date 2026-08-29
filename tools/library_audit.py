#!/usr/bin/env python3
"""
HAP-Revival library audit — an audiophile health-check of your HAP music library.

Reports what's actually *in* your library and what might need attention.
Read-only, nothing written, and nothing leaves your machine.

**Two sources, one report.** Either read the player over the network — no
screwdriver, no disk removal — or read the on-device SQLite catalog
(`hdd_browse.db`) if you happen to have it:

    python tools/hap_library.py 192.168.1.28 harvest   # once, ~90 min
    python tools/library_audit.py --from-player 192.168.1.28

The network source cannot see two fields the disk catalog has: the **DRM flag**
and the **channel count**. They are reported as unavailable rather than as zero.

It answers the questions an owner of a hi-res deck actually asks:

  * How much of my library is genuinely **Hi-Res** vs CD-quality vs lossy?
  * How many **DSD** tracks, and at what rates?
  * Are any PCM tracks **above the HAP's 192 kHz ceiling** (won't play natively)?
  * Which albums are **missing cover art** (a blank tile on the front panel)?
  * Are there **likely duplicate** tracks bloating the index?
  * The format / sample-rate / bit-depth breakdown, with a quality score.

Companion to the other catalog tools:
  * `library_browser.py` — *browse* the library (artists/albums/tracks/covers).
  * `hap_companion.py`    — *validate* files before transfer + diff vs the DB.
  * `library_audit.py`    — *report* on what the library already contains.  (this)

Usage:
    python tools/library_audit.py --from-player 192.168.1.28      # over the LAN
    python tools/library_audit.py /path/to/hdd_browse.db          # text report
    python tools/library_audit.py /path/to/hdd_browse.db --html report.html
    python tools/library_audit.py /path/to/hdd_browse.db --top 30 # longer lists

Getting the DB: it lives on the HDD's `/data` partition as `hdd_browse.db`.
See docs/09-disk-layout.md. Stdlib only (sqlite3).
"""
from __future__ import annotations

import argparse
import html
import sqlite3
import sys
import urllib.parse

# ---- schema decode (same PROP-codes as library_browser.py; docs/09-disk-layout.md) ----
# Tracks  FT0002: PROP7020 title, PROP304B codec, PROP3047 dur(s), PROP3048 srate(Hz),
#                 PROP10DE bits, PROP304C bitrate, PROPB2BB album-id, PROP7052 artist-id,
#                 PROP7007 file-name, PROP58D3 drm, PROP10DD multichannel
# Albums  FT000A: PROP3601 id, PROP7020 name, PROP7055 album-artist, PROP78D9 cover(BLOB)
# Artists FT5202: PROP3601 id, PROP7020 name

CODECS = {
    49: "FLAC", 81: "MP3", 97: "AAC", 65: "ALAC",
    129: "WMA", 17: "WAV", 33: "AIFF", 0: "?",
}
LOSSLESS = {"FLAC", "ALAC", "WAV", "AIFF", "DSD"}
LOSSY = {"MP3", "AAC", "WMA"}

HAP_PCM_CEILING_HZ = 192_000   # the HAP plays PCM up to 192 kHz; DSD up to 5.6 MHz
DSD_THRESHOLD_HZ = 2_000_000   # DSD64 ≈ 2.8224 MHz — anything this high is DSD, not PCM


def looks_corrupt(srate, bits, dur) -> bool:
    """True when a track's numbers are sentinels rather than measurements.

    A real library turned one of these up: `sample_rate` 1 048 575 (2^20-1),
    `bit_rate` 2 147 483 647 (INT_MAX), `bit_width` 0 and `duration` 0 — every
    field saturated, on a FLAC the indexer evidently could not read. Reported as
    a 1048.58 kHz hi-res track it is nonsense; what it actually means is that the
    file is broken and almost certainly will not play.
    """
    srate = int(srate or 0)
    return srate > HAP_PCM_CEILING_HZ and (int(bits or 0) == 0 or int(dur or 0) == 0)


def codec_name(v) -> str:
    return CODECS.get(int(v or 0), f"#{v}")


def classify(name: str, srate: int, bits: int) -> str:
    """One of: dsd, hires, cd, lossy, unknown — the quality bucket of a track.

    Takes the codec *name*, not the catalog's integer code: the REST source only
    ever knows names, so each source normalises at its own edge and there stays
    exactly one classifier.
    """
    srate = int(srate or 0)
    bits = int(bits or 0)
    if srate >= DSD_THRESHOLD_HZ:
        return "dsd"
    if name in LOSSY:
        return "lossy"
    if name in LOSSLESS or name.startswith("#") or name == "?":
        # lossless PCM (or unknown container we treat as PCM): hi-res if it
        # beats CD on either axis.
        if srate > 48_000 or bits > 16:
            return "hires"
        return "cd"
    return "unknown"


def fmt_int(n) -> str:
    return f"{int(n or 0):,}"


def fmt_dur_long(seconds) -> str:
    s = int(seconds or 0)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def bar(frac: float, width: int = 28) -> str:
    filled = int(round(frac * width))
    return "█" * filled + "·" * (width - filled)


class Audit:
    def __init__(self, path: str):
        uri = f"file:{urllib.parse.quote(path)}?immutable=1&mode=ro"
        self.db = sqlite3.connect(uri, uri=True)
        self.db.text_factory = lambda b: b.decode("utf-8", "replace")
        self.db.row_factory = sqlite3.Row

    def q(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        return self.db.execute(sql, args).fetchone()

    # ---- aggregate sections ----

    def totals(self) -> dict:
        return {
            "tracks": self.one("SELECT count(*) FROM FT0002")[0],
            "albums": self.one("SELECT count(*) FROM FT000A")[0],
            "artists": self.one("SELECT count(*) FROM FT5202")[0],
            "playtime": self.one("SELECT total(PROP3047) FROM FT0002")[0],
        }

    def tracks(self):
        rows = self.q(
            "SELECT PROP304B codec, PROP3048 srate, PROP10DE bits, PROP3047 dur, "
            "PROP58D3 drm, PROP10DD multich FROM FT0002"
        )
        # Normalise the codec to a name here, so build_report never has to know
        # which source it is reading from.
        return [
            {
                "codec": codec_name(r["codec"]),
                "srate": r["srate"],
                "bits": r["bits"],
                "dur": r["dur"],
                "drm": r["drm"],
                "multich": r["multich"],
            }
            for r in rows
        ]

    def albums_missing_cover(self):
        return self.q(
            "SELECT al.PROP3601 id, al.PROP7020 name, al.PROP7055 aa, count(*) trks "
            "FROM FT000A al JOIN FT0002 t ON t.PROPB2BB=al.PROP3601 "
            "WHERE al.PROP78D9 IS NULL OR length(al.PROP78D9)=0 "
            "GROUP BY al.PROP3601 ORDER BY trks DESC"
        )

    def duplicates(self):
        # Same title AND same duration within one album, more than once = almost
        # certainly a duplicated import. Matching duration too avoids flagging the
        # many legitimately same-titled tracks on field-recording compilations
        # ("Untitled", "Unknown", "Instrumental").
        return self.q(
            "SELECT t.PROP7020 title, al.PROP7020 album, ar.PROP7020 artist, count(*) n "
            "FROM FT0002 t LEFT JOIN FT000A al ON al.PROP3601=t.PROPB2BB "
            "LEFT JOIN FT5202 ar ON ar.PROP3601=t.PROP7052 "
            "WHERE t.PROP7020<>'' AND t.PROP3047>0 "
            "GROUP BY t.PROP7020, t.PROPB2BB, t.PROP3047 HAVING n>1 ORDER BY n DESC"
        )

    def over_ceiling(self):
        rows = self.q(
            "SELECT t.PROP7020 title, ar.PROP7020 artist, t.PROP3048 srate, "
            "t.PROP10DE bits, t.PROP3047 dur, t.PROP304B codec "
            "FROM FT0002 t LEFT JOIN FT5202 ar ON ar.PROP3601=t.PROP7052 "
            "WHERE t.PROP3048 > ? AND t.PROP3048 < ? ORDER BY t.PROP3048 DESC",
            (HAP_PCM_CEILING_HZ, DSD_THRESHOLD_HZ),
        )
        return [
            {
                "title": r["title"],
                "artist": r["artist"],
                "srate": r["srate"],
                "bits": r["bits"],
                "dur": r["dur"],
                "codec": codec_name(r["codec"]),
            }
            for r in rows
        ]


class RestAudit:
    """The same audit, computed from a REST harvest instead of the disk catalog.

    Same interface as `Audit`, so `build_report` cannot tell them apart. The
    point is that this needs no disk removal at all — see
    research/notes/2026-08-29-contentdb-was-never-dead.md.

    **Two figures the disk catalog has and this one does not**: the DRM flag
    (`PROP58D3`) and the channel count (`PROP10DD`) are simply absent from the
    REST payload. They are reported as unavailable rather than as zero, because
    "no multichannel tracks" and "we cannot see multichannel tracks" are very
    different statements to put in front of someone.
    """

    has_drm_and_channels = False
    source_label = "the player, over REST"

    def __init__(self, harvest: dict):
        self.h = harvest
        self._albums = harvest.get("albums") or []
        self._tracks = harvest.get("tracks") or []
        self._artists = harvest.get("artists") or []

    def totals(self) -> dict:
        return {
            "tracks": len(self._tracks),
            "albums": len(self._albums),
            "artists": len(self._artists),
            "playtime": sum(int(t.get("duration") or 0) for t in self._tracks),
        }

    def tracks(self):
        out = []
        for t in self._tracks:
            c = t.get("codec") or {}
            out.append(
                {
                    # The device spells codecs in lower case ("flac"); the disk
                    # catalog's names are upper. Match the latter so both sources
                    # produce the same report.
                    "codec": (c.get("codec_type") or "?").upper(),
                    "srate": c.get("sample_rate") or 0,
                    "bits": c.get("bit_width") or 0,
                    "dur": t.get("duration") or 0,
                    "drm": 0,
                    "multich": 0,
                }
            )
        return out

    def albums_missing_cover(self):
        """Albums with no artwork.

        An album without a cover **omits the `image` key entirely** — it is
        never present-but-empty (verified on 800 albums, 56 of them bare).
        """
        rows = [
            {
                "id": a.get("albumid"),
                "name": a.get("name"),
                "aa": (a.get("album_artist") or {}).get("name", ""),
                "trks": a.get("number_of_tracks") or 0,
            }
            for a in self._albums
            if not (a.get("image") or {}).get("url")
        ]
        return sorted(rows, key=lambda r: -r["trks"])

    def duplicates(self):
        """Same title and same duration inside one album — as the SQL does."""
        seen: dict[tuple, dict] = {}
        for t in self._tracks:
            title = t.get("name") or ""
            dur = int(t.get("duration") or 0)
            if not title or dur <= 0:
                continue
            album = t.get("album") or {}
            key = (title, album.get("albumid"), dur)
            row = seen.get(key)
            if row is None:
                seen[key] = {
                    "title": title,
                    "album": album.get("name", ""),
                    "artist": (t.get("artist") or {}).get("name", ""),
                    "n": 1,
                }
            else:
                row["n"] += 1
        dups = [r for r in seen.values() if r["n"] > 1]
        return sorted(dups, key=lambda r: -r["n"])

    def over_ceiling(self):
        rows = []
        for t in self._tracks:
            c = t.get("codec") or {}
            srate = int(c.get("sample_rate") or 0)
            if HAP_PCM_CEILING_HZ < srate < DSD_THRESHOLD_HZ:
                rows.append(
                    {
                        "title": t.get("name", ""),
                        "artist": (t.get("artist") or {}).get("name", ""),
                        "srate": srate,
                        "bits": c.get("bit_width") or 0,
                        "dur": t.get("duration") or 0,
                        "codec": (c.get("codec_type") or "?").upper(),
                    }
                )
        return sorted(rows, key=lambda r: -r["srate"])


def build_report(a, top: int) -> dict:
    """Compute everything once; returned dict feeds both text and HTML."""
    tot = a.totals()
    buckets = {"hires": 0, "cd": 0, "lossy": 0, "dsd": 0, "unknown": 0}
    codec_count: dict[str, int] = {}
    srate_count: dict[int, int] = {}
    bits_count: dict[int, int] = {}
    drm = multich = 0
    for t in a.tracks():
        cls = classify(t["codec"], t["srate"], t["bits"])
        buckets[cls] += 1
        codec_count[t["codec"]] = codec_count.get(t["codec"], 0) + 1
        sr = int(t["srate"] or 0)
        srate_count[sr] = srate_count.get(sr, 0) + 1
        b = int(t["bits"] or 0)
        bits_count[b] = bits_count.get(b, 0) + 1
        if t["drm"]:
            drm += 1
        # PROP10DD is a channel count (2 = stereo); multichannel = more than 2.
        if int(t["multich"] or 0) > 2:
            multich += 1
    n = max(1, tot["tracks"])
    lossless_n = buckets["hires"] + buckets["cd"] + buckets["dsd"]
    over = a.over_ceiling()
    return {
        "totals": tot,
        "buckets": buckets,
        "codec_count": dict(sorted(codec_count.items(), key=lambda kv: -kv[1])),
        "srate_count": dict(sorted(srate_count.items())),
        "bits_count": dict(sorted(bits_count.items())),
        "drm": drm,
        "multich": multich,
        # The REST source cannot see either. Kept distinct from "zero found".
        "has_drm_and_channels": getattr(a, "has_drm_and_channels", True),
        "source": getattr(a, "source_label", "hdd_browse.db"),
        "lossless_pct": 100.0 * lossless_n / n,
        "hires_pct": 100.0 * (buckets["hires"] + buckets["dsd"]) / n,
        "missing_cover": a.albums_missing_cover(),
        "duplicates": a.duplicates(),
        # Split them: a genuine 352.8 kHz file and an entry whose every number is
        # a saturated sentinel are different problems with different answers.
        "over_ceiling": [
            t for t in over if not looks_corrupt(t["srate"], t.get("bits"), t.get("dur"))
        ],
        "corrupt": [
            t for t in over if looks_corrupt(t["srate"], t.get("bits"), t.get("dur"))
        ],
        "top": top,
    }


# ---------------- text output ----------------

def khz(hz) -> str:
    hz = int(hz or 0)
    if hz == 0:
        return "(unknown)"
    if hz >= DSD_THRESHOLD_HZ:
        # express DSD as a DSDxx multiple of 44.1k*64
        mult = round(hz / 2_822_400)
        return f"DSD{64 * mult} ({hz / 1_000_000:g} MHz)"
    return f"{hz / 1000:g} kHz"


def print_report(r: dict) -> None:
    t = r["totals"]
    n = max(1, t["tracks"])
    P = print
    P("=" * 60)
    P("  HAP LIBRARY AUDIT")
    P("=" * 60)
    P(f"  source: {r['source']}")
    P(f"  {fmt_int(t['tracks'])} tracks · {fmt_int(t['albums'])} albums · "
      f"{fmt_int(t['artists'])} artists")
    P(f"  total playtime: {fmt_dur_long(t['playtime'])}")
    P(f"  lossless: {r['lossless_pct']:.1f}%   ·   hi-res or DSD: {r['hires_pct']:.1f}%")
    P("")
    P("-- quality mix " + "-" * 45)
    labels = {"hires": "Hi-Res PCM", "dsd": "DSD", "cd": "CD-quality",
              "lossy": "Lossy", "unknown": "Unknown"}
    for k in ("hires", "dsd", "cd", "lossy", "unknown"):
        c = r["buckets"][k]
        if c or k != "unknown":
            P(f"  {labels[k]:<12} {bar(c / n)} {c / n * 100:5.1f}%  {fmt_int(c)}")
    P("")
    P("-- formats " + "-" * 49)
    for name, c in r["codec_count"].items():
        P(f"  {name:<8} {bar(c / n)} {c / n * 100:5.1f}%  {fmt_int(c)}")
    P("")
    P("-- sample rates " + "-" * 44)
    for hz, c in r["srate_count"].items():
        P(f"  {khz(hz):<18} {bar(c / n)} {fmt_int(c)}")
    P("")
    P("-- bit depths " + "-" * 46)
    for b, c in r["bits_count"].items():
        label = f"{b}-bit" if b else "(n/a)"
        P(f"  {label:<8} {bar(c / n)} {fmt_int(c)}")
    P("")
    if not r["has_drm_and_channels"]:
        P("  multichannel / DRM: not visible over the network API "
          "(only the on-disk catalog carries those two fields)")
    elif r["multich"] or r["drm"]:
        P(f"  multichannel tracks: {fmt_int(r['multich'])}   ·   DRM-flagged: {fmt_int(r['drm'])}")

    top = r["top"]
    oc = r["over_ceiling"]
    P("")
    P("-- PCM above the HAP's 192 kHz ceiling " + "-" * 20)
    if not oc:
        P("  none — every PCM track is within the HAP's native range. ✓")
    else:
        P(f"  {len(oc)} track(s) exceed 192 kHz PCM (HAP will downsample/refuse):")
        for row in oc[:top]:
            P(f"    {khz(row['srate'])} {row['codec']}  "
              f"· {row['artist'] or '?'} — {row['title'] or '?'}")
        if len(oc) > top:
            P(f"    … and {len(oc) - top} more")

    cor = r.get("corrupt") or []
    if cor:
        P("")
        P("-- unreadable metadata " + "-" * 36)
        P(f"  {len(cor)} track(s) report impossible values — the indexer could not read")
        P("  them, and they are unlikely to play:")
        for row in cor[:top]:
            P(f"    {khz(row['srate'])} {row['codec']}  "
              f"· {row['artist'] or '?'} — {row['title'] or '?'}")

    mc = r["missing_cover"]
    P("")
    P("-- albums missing cover art " + "-" * 31)
    if not mc:
        P("  none — every album has artwork. ✓")
    else:
        P(f"  {len(mc)} album(s) with no embedded cover (blank tile on the HAP):")
        for row in mc[:top]:
            P(f"    {(row['aa'] or '?')[:28]:<28}  {row['name'] or '?'}  ({row['trks']} trk)")
        if len(mc) > top:
            P(f"    … and {len(mc) - top} more")

    dup = r["duplicates"]
    P("")
    P("-- likely duplicate tracks " + "-" * 32)
    if not dup:
        P("  none found (same title within one album). ✓")
    else:
        P(f"  {len(dup)} title(s) appear more than once inside the same album:")
        for row in dup[:top]:
            P(f"    ×{row['n']}  {row['artist'] or '?'} — {row['title']}  [{row['album'] or '?'}]")
        if len(dup) > top:
            P(f"    … and {len(dup) - top} more")
    P("=" * 60)


# ---------------- HTML output ----------------

def render_html(r: dict) -> str:
    t = r["totals"]
    n = max(1, t["tracks"])
    e = html.escape

    def bardiv(frac, label, count):
        pct = frac * 100
        return (
            f'<div class="row"><span class="lbl">{e(label)}</span>'
            f'<span class="track"><span class="fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="val">{pct:.1f}% · {fmt_int(count)}</span></div>'
        )

    qmix = "".join(
        bardiv(r["buckets"][k] / n, lbl, r["buckets"][k])
        for k, lbl in (("hires", "Hi-Res PCM"), ("dsd", "DSD"), ("cd", "CD-quality"),
                       ("lossy", "Lossy"), ("unknown", "Unknown")) if r["buckets"][k]
    )
    fmts = "".join(bardiv(c / n, name, c) for name, c in r["codec_count"].items())
    srates = "".join(bardiv(c / n, khz(hz), c) for hz, c in r["srate_count"].items())

    def listing(title, rows, fmt, empty):
        if not rows:
            return f"<h2>{e(title)}</h2><p class='ok'>{e(empty)} ✓</p>"
        items = "".join(f"<li>{fmt(row)}</li>" for row in rows[: r['top']])
        more = f"<li class='muted'>… and {len(rows) - r['top']} more</li>" if len(rows) > r["top"] else ""
        return f"<h2>{e(title)} <span class='pill'>{len(rows)}</span></h2><ul>{items}{more}</ul>"

    oc = listing(
        "PCM above the 192 kHz ceiling", r["over_ceiling"],
        lambda x: f"<b>{e(khz(x['srate']))}</b> {e(x['codec'])} · "
                  f"{e(x['artist'] or '?')} — {e(x['title'] or '?')}",
        "Every PCM track is within the HAP's native range.",
    )
    mc = listing(
        "Albums missing cover art", r["missing_cover"],
        lambda x: f"{e(x['aa'] or '?')} — <b>{e(x['name'] or '?')}</b> "
                  f"<span class='muted'>({x['trks']} trk)</span>",
        "Every album has artwork.",
    )
    dup = listing(
        "Likely duplicate tracks", r["duplicates"],
        lambda x: f"<span class='pill'>×{x['n']}</span> {e(x['artist'] or '?')} — "
                  f"<b>{e(x['title'])}</b> <span class='muted'>[{e(x['album'] or '?')}]</span>",
        "No duplicate titles within an album.",
    )

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HAP Library Audit</title><style>
:root{{--bg:#14161a;--card:#1e2128;--fg:#e8eaed;--muted:#9aa0a6;--accent:#7cc4ff;--ok:#7bd88f;--line:#2a2e36}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:0 0 60px}}
header{{padding:28px 20px;border-bottom:1px solid var(--line);text-align:center}}
header h1{{margin:0 0 6px;font-size:24px}}header .big{{font-size:13px;color:var(--muted)}}
main{{max-width:840px;margin:0 auto;padding:0 20px}}
h2{{font-size:15px;color:var(--muted);font-weight:600;text-transform:uppercase;
letter-spacing:.05em;margin:30px 0 12px}}
.cards{{display:flex;gap:14px;flex-wrap:wrap;justify-content:center;margin:22px 0}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 20px;text-align:center;min-width:120px}}
.stat .num{{font-size:22px;font-weight:700}}.stat .cap{{font-size:12px;color:var(--muted)}}
.row{{display:flex;align-items:center;gap:12px;margin:5px 0}}
.row .lbl{{width:120px;font-size:13px}}.row .val{{width:130px;font-size:12px;color:var(--muted);text-align:right}}
.track{{flex:1;height:12px;background:#0c0d10;border-radius:6px;overflow:hidden}}
.fill{{display:block;height:100%;background:linear-gradient(90deg,#3a7bd5,var(--accent))}}
ul{{list-style:none;padding:0;margin:0}}li{{padding:7px 0;border-bottom:1px solid var(--line);font-size:14px}}
.pill{{background:#272b33;color:var(--muted);border-radius:6px;padding:1px 8px;font-size:12px}}
.muted{{color:var(--muted)}}.ok{{color:var(--ok)}}
b{{color:#fff;font-weight:600}}
</style></head><body>
<header><h1>🎵 HAP Library Audit</h1>
<div class="big">{r['lossless_pct']:.1f}% lossless · {r['hires_pct']:.1f}% hi-res or DSD ·
total playtime {e(fmt_dur_long(t['playtime']))}</div></header>
<main>
<div class="cards">
  <div class="stat"><div class="num">{fmt_int(t['tracks'])}</div><div class="cap">tracks</div></div>
  <div class="stat"><div class="num">{fmt_int(t['albums'])}</div><div class="cap">albums</div></div>
  <div class="stat"><div class="num">{fmt_int(t['artists'])}</div><div class="cap">artists</div></div>
  <div class="stat"><div class="num">{r['buckets']['dsd']}</div><div class="cap">DSD tracks</div></div>
</div>
<h2>Quality mix</h2>{qmix}
<h2>Formats</h2>{fmts}
<h2>Sample rates</h2>{srates}
{oc}
{mc}
{dup}
<p class="muted" style="margin-top:36px;font-size:12px">Generated by tools/library_audit.py ·
read-only from hdd_browse.db · HAP-Revival</p>
</main></body></html>"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Audit a HAP music library — from the player over the network, "
        "or from its on-disk SQLite catalog."
    )
    ap.add_argument("db", nargs="?", help="path to hdd_browse.db")
    ap.add_argument(
        "--from-player",
        metavar="IP",
        help="audit over REST instead, using the harvest cached by "
        "`hap_library.py <ip> harvest` (run that first)",
    )
    ap.add_argument("--html", metavar="FILE", help="also write an HTML report to FILE")
    ap.add_argument("--top", type=int, default=20, help="max items per issue list (default 20)")
    args = ap.parse_args(argv[1:])

    if bool(args.db) == bool(args.from_player):
        ap.error("give either a path to hdd_browse.db or --from-player <ip>, not both")

    # The report uses box-drawing chars; make sure stdout can emit UTF-8 even on
    # a legacy Windows code page (cp1252) console.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.from_player:
        import hap_library

        harvest = hap_library.load_harvest(args.from_player)
        if harvest is None:
            print(
                f"error: no catalog cached for {args.from_player}.\n"
                f"Harvest it first (about 90 minutes, once):\n"
                f"    python tools/hap_library.py {args.from_player} harvest",
                file=sys.stderr,
            )
            return 2
        if not harvest.get("tracks"):
            print("error: the cached catalog has no tracks in it.", file=sys.stderr)
            return 2
        report = build_report(RestAudit(harvest), args.top)
    else:
        try:
            audit = Audit(args.db)
            report = build_report(audit, args.top)
        except sqlite3.Error as e:
            print(f"error: could not read DB ({e}). Is this an hdd_browse.db?", file=sys.stderr)
            return 2

    print_report(report)
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(render_html(report))
        print(f"\nHTML report written to {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
