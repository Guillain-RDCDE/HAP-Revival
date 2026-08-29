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
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
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

# Response envelopes: the collection key the device uses for each resource.
COLLECTION_KEYS = ("tracks", "albums", "artists", "genres", "playlists")


class LibraryError(Exception):
    """Any failure reaching or parsing the library API."""


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
            data = json.loads(raw)
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

        At `limit=5000` the full 59 414-track library is 12 requests, roughly
        11 minutes. Follows `paging.next` rather than incrementing an offset, so
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
    args = parser.parse_args(argv)

    lib = Library(args.host)
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
