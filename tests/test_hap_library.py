"""Tests for the REST library client, driven against the mock device.

Two layers, like test_mock_hap.py:
  - unit: envelope unpacking, which is where the device's inconsistencies live
  - integration: the real Library class over HTTP against mock_hap

No hardware, no network beyond loopback.
"""

import threading

import pytest

import hap_library
import mock_hap


# ---------- unit: envelope unpacking ----------


def test_unpack_reads_a_collection_and_its_paging():
    page = hap_library.Library._unpack(
        {
            "tracks": [{"trackid": 1}, {"trackid": 2}],
            "paging": {"offset": 10, "limit": 2, "total": 99, "next": "http://x/next"},
        }
    )
    assert [t["trackid"] for t in page.items] == [1, 2]
    assert (page.total, page.offset, page.limit) == (99, 10, 2)
    assert page.next_url == "http://x/next"
    assert len(page) == 2


def test_unpack_handles_the_singular_genre_object():
    # `genres/{id}` answers with `genre`, not a one-element `genres` list.
    # Every other resource uses the plural key. This is the device's quirk.
    page = hap_library.Library._unpack({"genre": {"genreid": 0, "name": ""}})
    assert page.items == [{"genreid": 0, "name": ""}]
    assert page.total == 1


def test_unpack_survives_an_empty_paging_block():
    page = hap_library.Library._unpack({"albums": [{"albumid": 3}]})
    assert page.total == 1 and page.next_url == ""


def test_unpack_of_an_empty_collection_is_empty_not_an_error():
    page = hap_library.Library._unpack({"playlists": [], "paging": {"total": 0}})
    assert page.items == [] and page.total == 0


def test_fetch_refuses_a_limit_the_device_would_reject():
    # The player answers 400 above 5000 rather than clamping, so failing here
    # with a readable message beats a bare HTTP 400 from the wire.
    lib = hap_library.Library("127.0.0.1")
    with pytest.raises(hap_library.LibraryError, match="exceeds"):
        lib.fetch("audio/tracks", limit=10000)


def test_set_favorite_rejects_an_unknown_type():
    lib = hap_library.Library("127.0.0.1")
    with pytest.raises(hap_library.LibraryError, match="favorite_type"):
        lib.set_favorite(1, "loved")


# ---------- integration: the client over HTTP ----------


@pytest.fixture
def live_mock():
    server = mock_hap.make_server("127.0.0.1", 0, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def lib(live_mock):
    host, port = live_mock
    return hap_library.Library(host, port=port, timeout=10)


def test_tracks_listing_excludes_streaming_content(lib):
    page = lib.tracks()
    names = [t["name"] for t in page]
    assert "Teardrop" in names
    # The Spotify Connect demo track is not in the player's library DB.
    assert "Black Sands" not in names
    assert page.total == len(names)


def test_a_track_carries_the_codec_detail_an_audit_needs(lib):
    page = lib.tracks()
    mahler = next(t for t in page if t["name"].startswith("Symphony"))
    assert mahler["codec"] == {
        "codec_type": "flac",
        "sample_rate": 96000,
        "bit_width": 24,
        "bit_rate": 4608000,
    }


def test_artists_and_their_albums_link_up(lib):
    artists = lib.artists()
    miles = next(a for a in artists if a["name"] == "Miles Davis")
    albums = lib.artist_albums(miles["artistid"])
    assert [a["name"] for a in albums] == ["Kind of Blue (DSD)"]


def test_album_tracks_are_reachable_by_id(lib):
    albums = lib.albums()
    mezzanine = next(a for a in albums if a["name"] == "Mezzanine")
    tracks = lib.album_tracks(mezzanine["albumid"])
    assert [t["name"] for t in tracks] == ["Teardrop"]


def test_single_lookups_return_one_object_each(lib):
    page = lib.tracks()
    first = page.items[0]
    assert lib.track(first["trackid"])["name"] == first["name"]
    assert lib.genre(1)["name"] == "Demo"      # the singular-envelope path


def test_an_unknown_id_is_an_empty_answer_not_an_error(lib):
    # The device answers `200 {}` for an id it does not have — no 404, no error
    # body (verified against 19404R, 2026-08-29). So "missing" has to be read
    # from the body, and it must not look like a transport failure.
    assert lib.track(999999) is None
    assert lib.album(999999) is None


def test_paging_walks_the_whole_collection(lib):
    all_ids = [t["trackid"] for t in lib.iter_all("audio/tracks", limit=1)]
    assert all_ids == [t["trackid"] for t in lib.tracks()]
    assert len(all_ids) == len(set(all_ids)), "no item served twice"


def test_paging_reports_a_next_url_until_the_end(lib):
    first = lib.tracks(offset=0, limit=1)
    assert first.next_url and first.total > 1
    last = lib.tracks(offset=first.total - 1, limit=1)
    assert last.next_url == ""


def test_root_listings_are_cached_and_refresh_forces_a_reread(lib, monkeypatch):
    calls: list[str] = []
    original = lib._get_json
    monkeypatch.setattr(lib, "_get_json", lambda url: (calls.append(url), original(url))[1])

    lib.artists()
    lib.artists()
    assert len(calls) == 1, "the second call should come from cache"

    lib.artists(refresh=True)
    assert len(calls) == 2


def test_scoped_lookups_are_never_cached(lib, monkeypatch):
    # They are sub-second on the real device; caching them would only serve
    # stale favourites and play counts.
    calls: list[str] = []
    original = lib._get_json
    monkeypatch.setattr(lib, "_get_json", lambda url: (calls.append(url), original(url))[1])

    lib.track(163756)
    lib.track(163756)
    assert len(calls) == 2


def test_favorites_reflect_the_devices_own_flag(lib):
    assert list(lib.favorites()) == []
    mock_hap.DEMO_TRACKS[2].favorite_type = "favorite"
    try:
        favs = list(lib.favorites())
        assert [t["name"] for t in favs] == ["Teardrop"]
    finally:
        mock_hap.DEMO_TRACKS[2].favorite_type = "normal"
