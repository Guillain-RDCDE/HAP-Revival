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


def test_decode_payload_accepts_plain_utf8():
    assert hap_library.decode_payload('{"name": "Dvořák"}'.encode()) == '{"name": "Dvořák"}'


def test_decode_payload_rescues_a_latin1_byte_in_a_utf8_body():
    # Measured on the real player: one artist name out of 17 317 carried a bare
    # 0xE9 in an otherwise valid UTF-8 page. json.loads on the bytes throws, and
    # the whole 343 KB page would be lost over one character.
    raw = b'{"name": "Z\xe9 Roberto", "other": "caf\xc3\xa9"}'
    text = hap_library.decode_payload(raw)
    assert "Zé Roberto" in text
    assert "café" in text, "correctly-encoded names must survive untouched"
    assert "�" not in text, "the byte is recovered, not replaced"


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


def test_harvest_walks_every_collection(lib):
    data = lib.harvest()
    assert data["counts"]["tracks"] == len(list(lib.tracks()))
    assert data["counts"]["artists"] == len(list(lib.artists()))
    assert data["host"] == lib.host


def test_search_matches_case_and_accent_insensitively(lib):
    data = lib.harvest()
    assert [a["name"] for a in lib.search(data, "MILES")["artists"]] == ["Miles Davis"]
    assert lib.search(data, "teardrop")["tracks"][0]["name"] == "Teardrop"
    assert lib.search(data, "")["artists"] == []
    assert lib.search(data, "zzzznothing")["tracks"] == []


def test_search_respects_its_limit(lib):
    data = lib.harvest()
    # "a" appears in every demo artist; the cap must still hold.
    assert len(lib.search(data, "a", limit=1)["artists"]) == 1


def test_harvest_round_trips_through_disk(lib, tmp_path):
    data = lib.harvest()
    target = tmp_path / "cat.json"
    hap_library.save_harvest(data, target)
    back = hap_library.load_harvest(lib.host, target)
    assert back["counts"] == data["counts"]
    assert "saved_at" in back
    assert hap_library.load_harvest(lib.host, tmp_path / "absent.json") is None


def test_a_harvest_page_retries_with_a_doubling_deadline(lib, monkeypatch):
    """The protection for libraries larger than the one this was measured on.

    A request costs what it costs to count the whole catalogue, so the per-page
    time grows with the library. A fixed ceiling is a guess about somebody
    else's collection; doubling turns "failed" into "took longer".
    """
    seen: list[float] = []
    calls = {"n": 0}
    real = lib.fetch

    def flaky(path, **params):
        seen.append(lib.timeout)
        calls["n"] += 1
        if calls["n"] < 3:
            raise hap_library.LibraryError("timed out")
        return real(path, **params)

    monkeypatch.setattr(hap_library, "HARVEST_RETRY_PAUSE_SEC", 0)
    lib.timeout_for_harvest = 10
    lib.timeout = 10
    lib.fetch = flaky

    page = lib._fetch_page_with_retry("tracks", 0, None)

    assert seen == [10, 20, 40], "each attempt must wait twice as long"
    assert page.items, "the third attempt's result is the one returned"
    assert lib.timeout == 10, "the deadline is restored afterwards"


def test_a_page_that_never_answers_still_raises(lib, monkeypatch):
    monkeypatch.setattr(hap_library, "HARVEST_RETRY_PAUSE_SEC", 0)

    def always_fails(path, **params):
        raise hap_library.LibraryError("timed out")

    monkeypatch.setattr(lib, "fetch", always_fails)
    with pytest.raises(hap_library.LibraryError, match="timed out"):
        lib._fetch_page_with_retry("tracks", 0, None)


def test_harvest_uses_its_own_deadline_not_the_interactive_one(lib):
    # An interactive call should fail while somebody is still watching; a batch
    # harvest can afford to wait a great deal longer.
    lib.timeout = 5
    lib.timeout_for_harvest = 900
    during: list[float] = []
    real = lib.fetch

    def note(path, **params):
        during.append(lib.timeout)
        return real(path, **params)

    lib.fetch = note
    lib.harvest()

    assert during and set(during) == {900}
    assert lib.timeout == 5, "the interactive deadline is put back"


def test_favorites_reflect_the_devices_own_flag(lib):
    assert list(lib.favorites()) == []
    mock_hap.DEMO_TRACKS[2].favorite_type = "favorite"
    try:
        favs = list(lib.favorites())
        assert [t["name"] for t in favs] == ["Teardrop"]
    finally:
        mock_hap.DEMO_TRACKS[2].favorite_type = "normal"
