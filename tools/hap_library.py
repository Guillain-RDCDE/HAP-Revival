#!/usr/bin/env python3
"""
Read the HAP's music library over its REST API — artists, albums, tracks, and
the metadata the front panel shows, straight off the device.

This is the network counterpart to `library_browser.py` / `library_audit.py`,
which read the same catalog from `hdd_browse.db` and therefore need the disk out
of the machine. Everything here works over the LAN, on a running player.

Two facts about `/sony/contentdb/v100` shape every design decision below, both
measured 2026-08-29 (see research/notes/2026-08-29-contentdb-was-never-dead.md):

  **Unfiltered collections are slow — around 40-90 s — and the cost is fixed.**
  `?limit=2` costs about as much as `?limit=5000`. It looks like the price of
  `paging.total`, which has to count the whole table. So: ask for big pages, and
  cache the result. `MAX_LIMIT` is 5000; 10000 is refused with a 400.

  **Anything scoped by id is fast — well under a second.** `albums/{id}/tracks`,
  `artists/{id}/albums`, `tracks/{id}` all answer immediately. Drill-down
  browsing needs no cache at all; only the four root listings do.

The daemon also handles one request at a time, so nothing here is concurrent,
and a caller must not run these alongside other requests to the same player.

Requires: Python 3.10+, stdlib only.

Usage:
    python tools/hap_library.py <ip> artists
    python tools/hap_library.py <ip> albums --limit 20
    python tools/hap_library.py <ip> artist-albums 1089
    python tools/hap_library.py <ip> album-tracks 10633
    python tools/hap_library.py <ip> track 148136
    python tools/hap_library.py <ip> playlists
    python tools/hap_library.py <ip> favorites
    python tools/hap_library.py <ip> count
    python tools/hap_library.py <ip> harvest          # ~90 min, cached on disk
    python tools/hap_library.py <ip> search dvorak    # searches the cache

The harvest is written to ~/.hap-revival/library-<host>.json and stays on this
machine — it is your own library metadata, and it is deliberately kept outside
the repository so it cannot be committed by accident.
"""

from __future__ import annotations

import argparse
import codecs
import json
import sys
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

API_PORT = 60200
BASE_PATH = "/sony/contentdb/v100"

# Generous on purpose. A cold root listing can take 90 s; the 6 s this repo used
# to default to is why the whole API was recorded as dead for months.
DEFAULT_TIMEOUT_SEC = 120.0

# The device answers 400 for anything above this. 5000 works, 10000 does not;
# the exact ceiling in between was not worth the minutes it would cost to find.
MAX_LIMIT = 5000

# Root listings are expensive and almost never change. Scoped lookups are cheap,
# so they are not cached at all.
ROOT_CACHE_TTL_SEC = 900.0

# A harvest asks for 5000 rows at a time — about 5 MB — and how long that takes
# depends on what else the player is doing. Measured between 52 s and over 120 s
# for the same request on the same day, so the interactive ceiling above is too
# tight here, and a single slow page must not throw away a run that has already
# spent four minutes on artists and albums.
HARVEST_TIMEOUT_SEC = 420.0
HARVEST_RETRIES = 3
HARVEST_RETRY_PAUSE_SEC = 10.0

# Response envelopes: the collection key the device uses for each resource.
COLLECTION_KEYS = ("tracks", "albums", "artists", "genres", "playlists")


# Where a harvested catalog is kept. Outside the repo on purpose: it is the
# user's own music metadata, and it must never end up in a commit.
CACHE_DIR = Path.home() / ".hap-revival"


class LibraryError(Exception):
    """Any failure reaching or parsing the library API."""


def _latin1_fallback(exc: UnicodeError):
    """Decode one stray non-UTF-8 byte as Latin-1 instead of losing it."""
    if isinstance(exc, UnicodeDecodeError):
        return exc.object[exc.start : exc.end].decode("latin-1"), exc.end
    raise exc


codecs.register_error("hap_mixed", _latin1_fallback)


def decode_payload(raw: bytes) -> str:
    """Decode a response body, tolerating the player's mixed encodings.

    The player does not re-encode tags: it hands back whatever bytes the catalog
    holds. Most of a response is valid UTF-8, but a track or artist imported
    with Latin-1 tags carries raw high bytes in the middle of it — measured
    2026-08-29 on a 343 KB artist page where exactly one name, `Zé Roberto`
    (artistid 16712), had a bare 0xE9. `json.loads` on the bytes raises
    `UnicodeDecodeError` and the whole page is lost over one character.

    Strict UTF-8 first, so nothing is guessed when nothing needs to be; the
    fallback applies only to the bytes that actually fail, and Latin-1 is the
    right guess for them because it is what those tags were written in.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "hap_mixed")


def _fold(text: str) -> str:
    """Lowercase and strip accents, so `dvorak` finds `Dvořák`."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def cache_path(host: str) -> Path:
    """Where this host's harvested catalog lives."""
    safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in host)
    return CACHE_DIR / f"library-{safe}.json"


def save_harvest(harvest: dict, path: Path | None = None) -> Path:
    """Write a harvest to disk. Stays on this machine; nothing is uploaded."""
    target = path or cache_path(harvest.get("host", "unknown"))
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(harvest)
    payload["saved_at"] = time.time()
    # write_bytes, not write_text: on Windows the default encoding is not UTF-8
    # and a library full of accents would be mangled on the way out.
    target.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return target


def load_harvest(host: str, path: Path | None = None) -> dict | None:
    """Read a previously saved harvest, or None if there isn't one."""
    target = path or cache_path(host)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


@dataclass
class Page:
    """One page of a collection, plus what the device says about the rest."""

    items: list[dict]
    total: int = 0
    offset: int = 0
    limit: int = 0
    next_url: str = ""

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)


@dataclass
class Library:
    """Read-mostly view of one player's music library."""

    host: str
    port: int = API_PORT
    timeout: float = DEFAULT_TIMEOUT_SEC
    _cache: dict[str, tuple[float, Page]] = field(default_factory=dict, repr=False)

    # ---------- transport ----------

    def _url(self, path: str, **params: object) -> str:
        query = {k: v for k, v in params.items() if v is not None}
        url = f"http://{self.host}:{self.port}{BASE_PATH}/{path.lstrip('/')}"
        return f"{url}?{urllib.parse.urlencode(query)}" if query else url

    def _get_json(self, url: str) -> dict:
        try:
            with urlopen(url, timeout=self.timeout) as resp:
                raw = resp.read()
        except HTTPError as e:
            # The device answers 400 for an out-of-range limit, and its body is
            # a bare {"error_code": 400, "description": "Bad Request"}.
            raise LibraryError(f"HTTP {e.code} on {url}") from e
        except (URLError, OSError) as e:
            raise LibraryError(f"{e} on {url}") from e
        try:
            data = json.loads(decode_payload(raw))
        except json.JSONDecodeError as e:
            raise LibraryError(f"not JSON from {url}: {raw[:120]!r}") from e
        if not isinstance(data, dict):
            raise LibraryError(f"unexpected payload from {url}: {type(data).__name__}")
        return data

    @staticmethod
    def _unpack(data: dict) -> Page:
        """Pull the collection and paging out of a response envelope.

        Collections come back under their own key (`tracks`, `albums`, …); a
        single-object lookup uses the same plural key with one element, except
        `genres/{id}`, which answers with a singular `genre` object instead.
        """
        items: list[dict] = []
        for key in COLLECTION_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                items = value
                break
        else:
            for key in ("genre", "album", "artist", "track", "playlist"):
                value = data.get(key)
                if isinstance(value, dict):
                    items = [value]
                    break

        paging = data.get("paging") or {}
        return Page(
            items=items,
            total=int(paging.get("total", len(items)) or 0),
            offset=int(paging.get("offset", 0) or 0),
            limit=int(paging.get("limit", len(items)) or 0),
            next_url=str(paging.get("next", "") or ""),
        )

    def fetch(self, path: str, **params: object) -> Page:
        """One request, no caching. `path` is relative to /sony/contentdb/v100."""
        limit = params.get("limit")
        if isinstance(limit, int) and limit > MAX_LIMIT:
            raise LibraryError(
                f"limit={limit} exceeds what the device accepts (max {MAX_LIMIT}); "
                "it answers 400 rather than clamping"
            )
        return self._unpack(self._get_json(self._url(path, **params)))

    # ---------- root listings (slow: cached) ----------

    def _root(self, path: str, offset: int, limit: int, refresh: bool) -> Page:
        key = f"{path}:{offset}:{limit}"
        hit = self._cache.get(key)
        if hit and not refresh and (time.monotonic() - hit[0]) < ROOT_CACHE_TTL_SEC:
            return hit[1]
        page = self.fetch(path, offset=offset, limit=limit)
        self._cache[key] = (time.monotonic(), page)
        return page

    def artists(self, offset: int = 0, limit: int = 200, refresh: bool = False) -> Page:
        return self._root("audio/artists", offset, limit, refresh)

    def albums(self, offset: int = 0, limit: int = 200, refresh: bool = False) -> Page:
        return self._root("audio/albums", offset, limit, refresh)

    def genres(self, offset: int = 0, limit: int = 200, refresh: bool = False) -> Page:
        return self._root("audio/genres", offset, limit, refresh)

    def tracks(self, offset: int = 0, limit: int = 200, refresh: bool = False) -> Page:
        return self._root("audio/tracks", offset, limit, refresh)

    def playlists(self, refresh: bool = False) -> Page:
        return self._root("audio/playlists", 0, 200, refresh)

    # ---------- scoped lookups (fast: never cached) ----------

    def artist(self, artist_id: int) -> dict | None:
        page = self.fetch(f"audio/artists/{int(artist_id)}")
        return page.items[0] if page.items else None

    def album(self, album_id: int) -> dict | None:
        page = self.fetch(f"audio/albums/{int(album_id)}")
        return page.items[0] if page.items else None

    def track(self, track_id: int) -> dict | None:
        page = self.fetch(f"audio/tracks/{int(track_id)}")
        return page.items[0] if page.items else None

    def genre(self, genre_id: int) -> dict | None:
        page = self.fetch(f"audio/genres/{int(genre_id)}")
        return page.items[0] if page.items else None

    def artist_albums(self, artist_id: int, offset: int = 0, limit: int = 200) -> Page:
        return self.fetch(f"audio/artists/{int(artist_id)}/albums", offset=offset, limit=limit)

    def album_tracks(self, album_id: int, offset: int = 0, limit: int = 200) -> Page:
        return self.fetch(f"audio/albums/{int(album_id)}/tracks", offset=offset, limit=limit)

    def playlist_tracks(self, playlist_id: int, offset: int = 0, limit: int = 200) -> Page:
        return self.fetch(
            f"audio/playlists/{int(playlist_id)}/tracks", offset=offset, limit=limit
        )

    def favorites(self, offset: int = 0, limit: int = 200) -> Page:
        return self.fetch("services/favorite/tracks", offset=offset, limit=limit)

    # ---------- whole-collection walk ----------

    def iter_all(self, path: str, limit: int = MAX_LIMIT, **params: object):
        """Yield every item of a collection, following the device's own paging.

        At `limit=5000` a 78 369-track library is 16 requests. Follows
        `paging.next` rather than incrementing an offset, so
        it stops exactly where the device says the collection ends.
        """
        offset = 0
        seen = 0
        while True:
            page = self.fetch(path, offset=offset, limit=limit, **params)
            if not page.items:
                return
            yield from page.items
            seen += len(page.items)
            if not page.next_url or (page.total and seen >= page.total):
                return
            offset += len(page.items)

    # ---------- whole-library harvest ----------

    def harvest(self, progress=None, with_tracks: bool = True) -> dict:
        """Pull the entire library into one dict, following the device's paging.

        Budget about **90 minutes** for a large library — measured 5512 s for
        17 317 artists + 5740 albums + 78 369 tracks. Page size is capped at
        5000, so it is the number of requests that costs, not the bytes; and a
        page takes ~300 s once the player has been working for a while, well
        above the ~50 s a first cold page suggests. An earlier estimate of
        11 minutes was extrapolated from one such cold page and was wrong by
        a factor of seven.

        `progress(kind, seen, total)` is called after each page, for a UI.
        """
        out: dict = {
            "host": self.host,
            "artists": [],
            "albums": [],
            "tracks": [],
        }
        wanted = ["artists", "albums"] + (["tracks"] if with_tracks else [])
        was = self.timeout
        self.timeout = HARVEST_TIMEOUT_SEC
        try:
            self._harvest_into(out, wanted, progress)
        finally:
            self.timeout = was
        out["counts"] = {k: len(out[k]) for k in ("artists", "albums", "tracks")}
        return out

    def _harvest_into(self, out: dict, wanted: list[str], progress) -> None:
        for kind in wanted:
            offset = 0
            while True:
                page = self._fetch_page_with_retry(kind, offset, progress)
                if not page.items:
                    break
                out[kind].extend(page.items)
                if progress:
                    progress(kind, len(out[kind]), page.total)
                offset += len(page.items)
                if not page.next_url or offset >= page.total:
                    break

    def _fetch_page_with_retry(self, kind: str, offset: int, progress) -> Page:
        """One harvest page, retried — a slow page is not a dead one.

        The first attempt at a 5 MB page of tracks has timed out on a player
        that answered the same request in 52 s an hour earlier. Giving up there
        would discard the artists and albums already collected.
        """
        last: LibraryError | None = None
        for attempt in range(1, HARVEST_RETRIES + 1):
            try:
                return self.fetch(f"audio/{kind}", offset=offset, limit=MAX_LIMIT)
            except LibraryError as e:
                last = e
                if attempt < HARVEST_RETRIES:
                    if progress:
                        progress(f"{kind} (retry {attempt})", offset, 0)
                    time.sleep(HARVEST_RETRY_PAUSE_SEC)
        raise last if last else LibraryError("harvest failed for an unknown reason")

    def search(self, harvest: dict, query: str, limit: int = 60) -> dict:
        """Substring search over a harvest. Case- and accent-insensitive.

        The device has no search endpoint, and asking it per keystroke would be
        unusable at 30 s a request — so the whole catalog is matched locally.
        """
        needle = _fold(query)
        if not needle:
            return {"artists": [], "albums": [], "tracks": []}
        found: dict[str, list] = {}
        for kind in ("artists", "albums", "tracks"):
            hits = []
            for item in harvest.get(kind) or []:
                if needle in _fold(item.get("name", "")):
                    hits.append(item)
                    if len(hits) >= limit:
                        break
            found[kind] = hits
        return found

    # ---------- the one write ----------

    def set_favorite(self, track_id: int, kind: str = "favorite") -> None:
        """Mark a track `favorite`, `dislike`, or `normal`.

        The only write this API exposes. Documented in the 2016 Crestron module;
        POST body shape is theirs.
        """
        if kind not in ("favorite", "dislike", "normal"):
            raise LibraryError(f"unknown favorite_type {kind!r}")
        body = json.dumps(
            {"track": {"trackid": int(track_id), "favorite_type": kind}}
        ).encode("utf-8")
        url = self._url(f"audio/tracks/{int(track_id)}")
        # No Content-Type on purpose: the player parses JSON without one, and
        # sending it makes a browser client fail its preflight (docs/16-gotchas.md).
        try:
            with urlopen(_post(url, body), timeout=self.timeout):
                return
        except (HTTPError, URLError, OSError) as e:
            raise LibraryError(f"{e} on {url}") from e


def _post(url: str, body: bytes):
    """A POST request object, kept out of the class so tests can see it."""
    from urllib.request import Request

    return Request(url, data=body, method="POST")


# ---------- CLI ----------


def _fmt_track(t: dict) -> str:
    codec = t.get("codec") or {}
    spec = ""
    if codec:
        rate = codec.get("sample_rate", 0)
        spec = f"  [{codec.get('codec_type', '?')} {rate / 1000:g}kHz/{codec.get('bit_width', '?')}bit]"
    artist = (t.get("artist") or {}).get("name", "")
    return f"  {t.get('trackid'):>7}  {t.get('name', '')[:44]:<44} {artist[:24]:<24}{spec}"


def _fmt_row(item: dict) -> str:
    for key in ("albumid", "artistid", "genreid", "playlistid"):
        if key in item:
            count = item.get("number_of_tracks", "")
            return f"  {item[key]:>7}  {item.get('name', '')[:52]:<52} {count:>6} pistes"
    return f"  {item}"


def main(argv: list[str] | None = None) -> int:
    # The paging flags live on a parent parser so they work on either side of
    # the subcommand: `... albums --limit 5` and `... --limit 5 albums` both do
    # the same thing. Declared only on the top level, the first form is an error,
    # which is the form everyone types.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--limit", type=int, default=30)
    common.add_argument("--offset", type=int, default=0)
    common.add_argument("--json", action="store_true", help="dump raw JSON")

    parser = argparse.ArgumentParser(
        description="Read a HAP music library over REST.", parents=[common]
    )
    parser.add_argument("host", help="player IP or hostname")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("artists", "albums", "genres", "tracks", "playlists", "favorites", "count"):
        sub.add_parser(name, parents=[common])
    for name in ("artist-albums", "album-tracks", "playlist-tracks", "track"):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("id", type=int)
    sub.add_parser("harvest", parents=[common])
    p = sub.add_parser("search", parents=[common])
    p.add_argument("query")
    args = parser.parse_args(argv)

    lib = Library(args.host)

    if args.cmd == "harvest":
        started = time.time()

        def show(kind: str, seen: int, total: int) -> None:
            print(f"  {kind:<8} {seen:>6} / {total:<6} ({time.time() - started:.0f}s)")

        print(f"Harvesting {args.host} — about 90 minutes for a large library.")
        try:
            data = lib.harvest(progress=show)
        except LibraryError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        where = save_harvest(data)
        print(f"\n{data['counts']} → {where}")
        return 0

    if args.cmd == "search":
        data = load_harvest(args.host)
        if data is None:
            print(
                f"no catalog cached for {args.host}. Run:\n"
                f"    python tools/hap_library.py {args.host} harvest",
                file=sys.stderr,
            )
            return 1
        hits = lib.search(data, args.query, limit=args.limit)
        for kind in ("artists", "albums", "tracks"):
            rows = hits[kind]
            if not rows:
                continue
            print(f"\n-- {kind} ({len(rows)})")
            for item in rows:
                print(_fmt_track(item) if "trackid" in item else _fmt_row(item))
        if not any(hits.values()):
            print("aucun résultat")
        return 0

    try:
        if args.cmd == "count":
            for what, fn in (
                ("pistes", lib.tracks),
                ("albums", lib.albums),
                ("artistes", lib.artists),
                ("genres", lib.genres),
            ):
                start = time.time()
                page = fn(0, 1)
                print(f"{what:>9}: {page.total:>7}   ({time.time() - start:.1f}s)")
            return 0

        if args.cmd == "track":
            item = lib.track(args.id)
            print(json.dumps(item, indent=2, ensure_ascii=False) if item else "introuvable")
            return 0

        lookup = {
            "artists": lambda: lib.artists(args.offset, args.limit),
            "albums": lambda: lib.albums(args.offset, args.limit),
            "genres": lambda: lib.genres(args.offset, args.limit),
            "tracks": lambda: lib.tracks(args.offset, args.limit),
            "playlists": lib.playlists,
            "favorites": lambda: lib.favorites(args.offset, args.limit),
            "artist-albums": lambda: lib.artist_albums(args.id, args.offset, args.limit),
            "album-tracks": lambda: lib.album_tracks(args.id, args.offset, args.limit),
            "playlist-tracks": lambda: lib.playlist_tracks(args.id, args.offset, args.limit),
        }
        page = lookup[args.cmd]()
    except LibraryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(page.items, indent=2, ensure_ascii=False))
        return 0

    print(f"{len(page)} sur {page.total} (offset {page.offset})")
    for item in page:
        print(_fmt_track(item) if "trackid" in item else _fmt_row(item))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
