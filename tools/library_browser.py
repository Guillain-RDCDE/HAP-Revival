#!/usr/bin/env python3
"""
HAP-Revival library browser.

Browse a Sony HAP-Z1ES / HAP-S1 music library straight from its on-device SQLite
catalog (`hdd_browse.db`), in your web browser — artists, albums, tracks, cover art,
codec / sample-rate / bit-depth — with zero dependency on the device being online.

Why this exists: the HAP cannot serve an HDD library listing over its network API
(`getContentList` is netService/radio only; `downloadByDiff` returns an empty
location on firmware 19404R). But the catalog is plain SQLite — so once you have the
DB file, the whole library is browsable. This tool is the reference decoder for that
schema (see docs/09-disk-layout.md) and a foundation for a future control app.

Getting the DB file: it lives on the HDD's small `/data` partition as
`hdd_browse.db` (the fully-commented, human-readable catalog; `master.db` holds the
same data in raw property-bag form). Read the disk on a Linux box / WSL (see
docs/06-hdd-swap.md, docs/09-disk-layout.md) and copy `hdd_browse.db` out.

Usage:
    python tools/library_browser.py /path/to/hdd_browse.db
    # then open http://localhost:8090

Stdlib only (sqlite3 + http.server). Read-only: the DB is opened immutable; nothing
is ever written. Your library data never leaves your machine.
"""
from __future__ import annotations

import html
import sqlite3
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- schema decode (from hdd_browse.db; see docs/09-disk-layout.md) ----
# Tables: FT5202 artists, FT000A albums, FT0002 tracks, FT4502 genres, FT0000 folders.
# Columns are Sony PROP-codes; the ones we use:
#   artist/album/genre: PROP3601 id, PROP7020 name, PROP7065 sort, PROP7221 initial
#   album extra:        PROP7055 album-artist, PROP6844 year, PROP78D9 cover thumb (BLOB)
#   track:              PROP7020 title, PROP304B codec, PROP3047 duration(s),
#                       PROP3048 sample-rate, PROP10DE bit-depth, PROP304C bitrate,
#                       PROP2053 track-no, PROP10A3 disc-no, PROP7052 artist-id,
#                       PROP7045 genre-id, PROPB2BB album-id, PROP7007 file-name,
#                       PROP58D3 drm-flag, PROP10DD multichannel-flag

CODECS = {
    49: "FLAC", 81: "MP3", 97: "AAC", 65: "ALAC",
    129: "WMA", 17: "WAV", 33: "AIFF", 0: "?",
}


def codec_name(v: int) -> str:
    return CODECS.get(int(v or 0), f"#{v}")


def fmt_dur(seconds: int) -> str:
    s = int(seconds or 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def fmt_quality(srate: int, bits: int) -> str:
    if not srate:
        return ""
    khz = srate / 1000
    khz_s = f"{khz:g}"
    return f"{khz_s} kHz / {bits}-bit" if bits else f"{khz_s} kHz"


class Library:
    def __init__(self, path: str):
        # immutable = read-only, no -wal/-journal, safe on a copy
        uri = f"file:{urllib.parse.quote(path)}?immutable=1&mode=ro"
        self.db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        # the on-device DB mixes UTF-8 with some latin-1 text (e.g. "Zé Roberto") — be tolerant
        self.db.text_factory = lambda b: b.decode("utf-8", "replace")
        self.db.row_factory = sqlite3.Row

    def q(self, sql: str, args=()):
        return self.db.execute(sql, args).fetchall()

    def stats(self) -> dict:
        def n(t):
            return self.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        return {
            "artists": n("FT5202"), "albums": n("FT000A"),
            "tracks": n("FT0002"), "genres": n("FT4502"),
        }

    def artists(self, search: str = "") -> list:
        if search:
            return self.q(
                "SELECT a.PROP3601 id, a.PROP7020 name, a.PROP7221 ini, "
                "count(DISTINCT t.PROPB2BB) albums, count(*) tracks "
                "FROM FT5202 a JOIN FT0002 t ON t.PROP7052=a.PROP3601 "
                "WHERE a.PROP7020 LIKE ? GROUP BY a.PROP3601 "
                "ORDER BY a.PROP7065 LIMIT 500",
                (f"%{search}%",),
            )
        return self.q(
            "SELECT a.PROP3601 id, a.PROP7020 name, a.PROP7221 ini, "
            "count(DISTINCT t.PROPB2BB) albums, count(*) tracks "
            "FROM FT5202 a JOIN FT0002 t ON t.PROP7052=a.PROP3601 "
            "WHERE a.PROP7020<>'' GROUP BY a.PROP3601 ORDER BY a.PROP7065"
        )

    def artist(self, aid: int):
        a = self.q("SELECT PROP3601 id, PROP7020 name FROM FT5202 WHERE PROP3601=?", (aid,))
        albums = self.q(
            "SELECT al.PROP3601 id, al.PROP7020 name, al.PROP6844 year, "
            "al.PROP7055 album_artist, length(al.PROP78D9) thumb, count(*) tracks "
            "FROM FT0002 t JOIN FT000A al ON al.PROP3601=t.PROPB2BB "
            "WHERE t.PROP7052=? GROUP BY al.PROP3601 ORDER BY al.PROP6844, al.PROP7065",
            (aid,),
        )
        return (a[0] if a else None), albums

    def albums(self, search: str = "", limit: int = 600) -> list:
        where = "WHERE PROP7020 LIKE ?" if search else "WHERE PROP7020<>''"
        args = (f"%{search}%",) if search else ()
        return self.q(
            f"SELECT PROP3601 id, PROP7020 name, PROP7055 album_artist, "
            f"PROP6844 year, length(PROP78D9) thumb FROM FT000A {where} "
            f"ORDER BY PROP7065 LIMIT {int(limit)}", args,
        )

    def album(self, alid: int):
        a = self.q(
            "SELECT PROP3601 id, PROP7020 name, PROP7055 album_artist, "
            "PROP6844 year, length(PROP78D9) thumb FROM FT000A WHERE PROP3601=?", (alid,),
        )
        tracks = self.q(
            "SELECT t.PROP3601 id, t.PROP7020 title, t.PROP2053 trk, t.PROP10A3 disc, "
            "t.PROP304B codec, t.PROP3047 dur, t.PROP3048 srate, t.PROP10DE bits, "
            "t.PROP10DD multich, t.PROP58D3 drm, ar.PROP7020 artist "
            "FROM FT0002 t LEFT JOIN FT5202 ar ON ar.PROP3601=t.PROP7052 "
            "WHERE t.PROPB2BB=? ORDER BY t.PROP10A3, t.PROP2053", (alid,),
        )
        return (a[0] if a else None), tracks

    def cover(self, alid: int) -> bytes | None:
        r = self.q("SELECT PROP78D9 FROM FT000A WHERE PROP3601=?", (alid,))
        return bytes(r[0][0]) if r and r[0][0] else None

    def search_tracks(self, term: str) -> list:
        return self.q(
            "SELECT t.PROP3601 id, t.PROP7020 title, t.PROPB2BB album_id, "
            "al.PROP7020 album, ar.PROP7020 artist, t.PROP304B codec "
            "FROM FT0002 t LEFT JOIN FT000A al ON al.PROP3601=t.PROPB2BB "
            "LEFT JOIN FT5202 ar ON ar.PROP3601=t.PROP7052 "
            "WHERE t.PROP7020 LIKE ? ORDER BY t.PROP7065 LIMIT 200", (f"%{term}%",),
        )


# ---------- HTML ----------

CSS = """
:root{--bg:#14161a;--card:#1e2128;--fg:#e8eaed;--muted:#9aa0a6;--accent:#7cc4ff;--line:#2a2e36}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{position:sticky;top:0;background:#0f1115ee;backdrop-filter:blur(8px);
border-bottom:1px solid var(--line);padding:12px 20px;display:flex;gap:18px;align-items:center;z-index:5}
header .brand{font-weight:700}header nav a{margin-right:14px;color:var(--muted)}
header form{margin-left:auto}input[type=search]{background:var(--card);border:1px solid var(--line);
color:var(--fg);padding:7px 12px;border-radius:8px;width:260px}
main{max-width:1100px;margin:22px auto;padding:0 20px}
h1{font-size:22px;margin:0 0 16px}h2{font-size:16px;color:var(--muted);font-weight:600;margin:24px 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.card a{color:var(--fg)}.cover{aspect-ratio:1;background:#0c0d10 center/cover no-repeat;display:block}
.card .meta{padding:9px 11px}.card .t{font-weight:600;font-size:14px;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.card .s{color:var(--muted);font-size:12px}
table{width:100%;border-collapse:collapse}td,th{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
td.n{color:var(--muted);width:48px;text-align:right}td.q{color:var(--muted);font-size:13px;white-space:nowrap}
.albumhead{display:flex;gap:22px;margin-bottom:18px}.albumhead .cover{width:200px;height:200px;border-radius:12px;flex:0 0 auto}
.pill{display:inline-block;background:#272b33;color:var(--muted);border-radius:6px;padding:1px 7px;font-size:12px;margin-left:6px}
.alpha a{display:inline-block;margin:0 6px 6px 0;color:var(--muted)}
ul.rows{list-style:none;padding:0;margin:0}ul.rows li{padding:8px 0;border-bottom:1px solid var(--line)}
.muted{color:var(--muted)}
"""


def page(title: str, body: str) -> bytes:
    nav = (
        '<a href="/">Home</a><a href="/artists">Artists</a>'
        '<a href="/albums">Albums</a>'
    )
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · HAP Library</title><style>{CSS}</style></head><body>
<header><span class="brand">🎵 HAP Library</span><nav>{nav}</nav>
<form action="/search"><input type="search" name="q" placeholder="Search artists, albums, tracks…"></form>
</header><main>{body}</main></body></html>"""
    return doc.encode("utf-8")


def cover_style(alid, thumb) -> str:
    if thumb:
        return f"background-image:url(/cover/{alid})"
    return ""


def album_card(al) -> str:
    aa = al["album_artist"] or ""
    yr = f' · {al["year"]}' if al["year"] else ""
    return (
        f'<div class="card"><a href="/album/{al["id"]}">'
        f'<span class="cover" style="{cover_style(al["id"], al["thumb"])}"></span>'
        f'<span class="meta"><div class="t">{html.escape(al["name"] or "—")}</div>'
        f'<div class="s">{html.escape(aa)}{yr}</div></span></a></div>'
    )


class Handler(BaseHTTPRequestHandler):
    lib: Library = None  # set on the server

    def log_message(self, *a):  # quiet
        pass

    def _send(self, body: bytes, ctype="text/html; charset=utf-8", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        qs = urllib.parse.parse_qs(u.query)
        try:
            if not parts:
                return self._send(self.home())
            if parts[0] == "artists":
                return self._send(self.artists_page())
            if parts[0] == "albums":
                return self._send(self.albums_page())
            if parts[0] == "artist" and len(parts) > 1:
                return self._send(self.artist_page(int(parts[1])))
            if parts[0] == "album" and len(parts) > 1:
                return self._send(self.album_page(int(parts[1])))
            if parts[0] == "cover" and len(parts) > 1:
                return self.cover_response(int(parts[1]))
            if parts[0] == "search":
                return self._send(self.search_page(qs.get("q", [""])[0]))
        except Exception as e:  # noqa: BLE001
            return self._send(page("Error", f"<h1>Error</h1><pre>{html.escape(str(e))}</pre>"), code=500)
        return self._send(page("Not found", "<h1>404</h1>"), code=404)

    # ---- pages ----
    def home(self) -> bytes:
        s = self.lib.stats()
        recent = self.lib.q(
            "SELECT PROP3601 id, PROP7020 name, PROP7055 album_artist, PROP6844 year, "
            "length(PROP78D9) thumb FROM FT000A WHERE PROP7020<>'' "
            "ORDER BY PROP6844 DESC LIMIT 18"
        )
        cards = "".join(album_card(a) for a in recent)
        body = (
            f'<h1>Your HAP library</h1>'
            f'<p class="muted">{s["artists"]:,} artists · {s["albums"]:,} albums · '
            f'{s["tracks"]:,} tracks · {s["genres"]:,} genres</p>'
            f'<h2>Newest albums</h2><div class="grid">{cards}</div>'
        )
        return page("Home", body)

    def artists_page(self) -> bytes:
        rows = self.lib.artists()
        by_ini: dict[str, list] = {}
        for r in rows:
            ini = (r["ini"] or "#").upper()[:1]
            by_ini.setdefault(ini, []).append(r)
        alpha = '<div class="alpha">' + "".join(
            f'<a href="#{k}">{html.escape(k)}</a>' for k in sorted(by_ini)) + "</div>"
        out = [f"<h1>Artists <span class='pill'>{len(rows):,}</span></h1>", alpha]
        for k in sorted(by_ini):
            out.append(f'<h2 id="{html.escape(k)}">{html.escape(k)}</h2><ul class="rows">')
            for r in by_ini[k]:
                out.append(
                    f'<li><a href="/artist/{r["id"]}">{html.escape(r["name"])}</a> '
                    f'<span class="muted">· {r["albums"]} albums · {r["tracks"]} tracks</span></li>'
                )
            out.append("</ul>")
        return page("Artists", "".join(out))

    def artist_page(self, aid: int) -> bytes:
        artist, albums = self.lib.artist(aid)
        if not artist:
            return page("Not found", "<h1>Artist not found</h1>")
        cards = "".join(album_card(a) for a in albums)
        body = (
            f'<h1>{html.escape(artist["name"])} <span class="pill">{len(albums)} albums</span></h1>'
            f'<div class="grid">{cards}</div>'
        )
        return page(artist["name"], body)

    def albums_page(self) -> bytes:
        albums = self.lib.albums()
        cards = "".join(album_card(a) for a in albums)
        body = f'<h1>Albums <span class="pill">{len(albums)} shown</span></h1><div class="grid">{cards}</div>'
        return page("Albums", body)

    def album_page(self, alid: int) -> bytes:
        album, tracks = self.lib.album(alid)
        if not album:
            return page("Not found", "<h1>Album not found</h1>")
        total = sum(t["dur"] or 0 for t in tracks)
        rows = []
        multi_disc = len({t["disc"] for t in tracks}) > 1
        for t in tracks:
            num = f'{t["disc"]}.{t["trk"]}' if multi_disc else str(t["trk"] or "")
            tags = ""
            if t["multich"]:
                tags += '<span class="pill">multi-ch</span>'
            if t["drm"]:
                tags += '<span class="pill">DRM</span>'
            rows.append(
                f'<tr><td class="n">{num}</td><td>{html.escape(t["title"] or "—")}{tags}</td>'
                f'<td class="q">{codec_name(t["codec"])}</td>'
                f'<td class="q">{html.escape(fmt_quality(t["srate"], t["bits"]))}</td>'
                f'<td class="n">{fmt_dur(t["dur"])}</td></tr>'
            )
        yr = f' · {album["year"]}' if album["year"] else ""
        body = (
            f'<div class="albumhead">'
            f'<span class="cover" style="{cover_style(alid, album["thumb"])}"></span>'
            f'<div><h1 style="margin-bottom:6px">{html.escape(album["name"] or "—")}</h1>'
            f'<p class="muted">{html.escape(album["album_artist"] or "")}{yr} · '
            f'{len(tracks)} tracks · {fmt_dur(total)}</p></div></div>'
            f'<table><thead><tr><th class="n">#</th><th>Title</th><th>Codec</th>'
            f'<th>Quality</th><th class="n">Time</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
        )
        return page(album["name"] or "Album", body)

    def search_page(self, term: str) -> bytes:
        term = term.strip()
        if not term:
            return page("Search", "<h1>Search</h1><p class='muted'>Type something in the box above.</p>")
        artists = self.lib.artists(term)[:50]
        albums = self.lib.albums(term, limit=60)
        tracks = self.lib.search_tracks(term)
        out = [f"<h1>Search: “{html.escape(term)}”</h1>"]
        if artists:
            out.append(f'<h2>Artists ({len(artists)})</h2><ul class="rows">')
            out += [f'<li><a href="/artist/{a["id"]}">{html.escape(a["name"])}</a> '
                    f'<span class="muted">· {a["albums"]} albums</span></li>' for a in artists]
            out.append("</ul>")
        if albums:
            out.append(f'<h2>Albums ({len(albums)})</h2><div class="grid">')
            out += [album_card(a) for a in albums]
            out.append("</div>")
        if tracks:
            out.append(f'<h2>Tracks ({len(tracks)})</h2><ul class="rows">')
            out += [f'<li><a href="/album/{t["album_id"]}">{html.escape(t["title"] or "—")}</a> '
                    f'<span class="muted">· {html.escape(t["artist"] or "")} · '
                    f'{html.escape(t["album"] or "")} · {codec_name(t["codec"])}</span></li>' for t in tracks]
            out.append("</ul>")
        if not (artists or albums or tracks):
            out.append("<p class='muted'>No matches.</p>")
        return page(f"Search {term}", "".join(out))

    def cover_response(self, alid: int):
        data = self.lib.cover(alid)
        if not data:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        print("error: pass the path to hdd_browse.db", file=sys.stderr)
        return 2
    port = int(argv[2]) if len(argv) > 2 else 8090
    Handler.lib = Library(argv[1])
    s = Handler.lib.stats()
    print(f"Loaded {s['tracks']:,} tracks / {s['albums']:,} albums / {s['artists']:,} artists")
    print(f"Browse at http://localhost:{port}  (Ctrl-C to stop)")
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
