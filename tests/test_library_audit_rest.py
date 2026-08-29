"""The audit computed from a REST harvest rather than the on-disk catalog.

`RestAudit` deliberately presents the same interface as `Audit`, so
`build_report` cannot tell them apart. These tests pin that down, and pin down
the two figures REST genuinely cannot supply.
"""

import library_audit


def track(name, codec, srate, bits, dur=200, albumid=1, album="A", artist="X"):
    return {
        "name": name,
        "trackid": abs(hash((name, albumid, dur))) % 100000,
        "duration": dur,
        "codec": {"codec_type": codec, "sample_rate": srate, "bit_width": bits},
        "album": {"albumid": albumid, "name": album},
        "artist": {"name": artist},
    }


HARVEST = {
    "host": "127.0.0.1",
    "artists": [{"artistid": 1, "name": "X"}],
    "albums": [
        {"albumid": 1, "name": "A", "number_of_tracks": 4,
         "album_artist": {"name": "X"},
         "image": {"url": "http://p/cover/1"}},
        {"albumid": 2, "name": "No cover", "number_of_tracks": 9,
         "album_artist": {"name": "Y"}},                       # no `image` key
        {"albumid": 3, "name": "Empty cover", "number_of_tracks": 2,
         "album_artist": {"name": "Z"}, "image": {}},
    ],
    "tracks": [
        track("CD track", "flac", 44100, 16),
        track("Hi-res", "flac", 96000, 24),
        track("Lossy", "mp3", 44100, 16),
        track("DSD", "dsd", 2822400, 1),
        track("Too fast", "wav", 352800, 24),
        track("Dupe", "flac", 44100, 16, dur=123),
        track("Dupe", "flac", 44100, 16, dur=123),
    ],
}


def audit():
    return library_audit.RestAudit(HARVEST)


def test_totals_come_from_the_harvest():
    t = audit().totals()
    assert t["tracks"] == 7
    assert t["albums"] == 3
    assert t["artists"] == 1
    assert t["playtime"] == sum(x["duration"] for x in HARVEST["tracks"])


def test_codec_names_are_uppercased_to_match_the_disk_catalog():
    # The device says "flac"; hdd_browse.db says "FLAC". One report, one spelling.
    names = {r["codec"] for r in audit().tracks()}
    assert names == {"FLAC", "MP3", "DSD", "WAV"}


def test_quality_buckets_match_what_the_classifier_says():
    counts = {}
    for r in audit().tracks():
        counts[library_audit.classify(r["codec"], r["srate"], r["bits"])] = (
            counts.get(library_audit.classify(r["codec"], r["srate"], r["bits"]), 0) + 1
        )
    assert counts["dsd"] == 1
    assert counts["lossy"] == 1
    assert counts["hires"] == 2          # 96/24 and the 352.8 kHz one
    assert counts["cd"] == 3


def test_albums_missing_cover_covers_both_shapes():
    missing = audit().albums_missing_cover()
    names = [a["name"] for a in missing]
    # No `image` key at all is how the real device says "no artwork"; an empty
    # `image` object is defensive, and must not be reported as having one.
    assert names == ["No cover", "Empty cover"]
    assert missing[0]["trks"] == 9, "sorted by track count, worst first"


def test_duplicates_need_the_same_title_album_and_duration():
    dups = audit().duplicates()
    assert len(dups) == 1
    assert dups[0]["title"] == "Dupe" and dups[0]["n"] == 2


def test_over_ceiling_finds_pcm_above_192k_and_ignores_dsd():
    over = audit().over_ceiling()
    assert [t["title"] for t in over] == ["Too fast"]


def test_a_saturated_entry_is_reported_as_corrupt_not_as_hi_res():
    # Seen in a real library: sample_rate 2^20-1, bit_rate INT_MAX, bit_width 0,
    # duration 0 — a FLAC the indexer could not read. Calling that a
    # "1048.58 kHz hi-res track" would be nonsense.
    harvest = dict(HARVEST)
    broken = track("Ghosts", "flac", 1048575, 0, dur=0, albumid=9, album="Tin Drum")
    harvest["tracks"] = HARVEST["tracks"] + [broken]
    r = library_audit.build_report(library_audit.RestAudit(harvest), 5)

    assert [t["title"] for t in r["corrupt"]] == ["Ghosts"]
    assert [t["title"] for t in r["over_ceiling"]] == ["Too fast"], (
        "a genuine over-ceiling track must stay in its own list"
    )


def test_looks_corrupt_needs_more_than_a_high_rate():
    # 352.8 kHz with a real bit depth and duration is a real file, not a sentinel.
    assert not library_audit.looks_corrupt(352800, 24, 300)
    assert library_audit.looks_corrupt(1048575, 0, 0)
    assert not library_audit.looks_corrupt(44100, 0, 0), "only high rates qualify"


def test_drm_and_channels_are_declared_unavailable_not_zero():
    # The REST payload has neither field. Reporting "0 multichannel tracks"
    # would be a claim the data cannot support.
    assert audit().has_drm_and_channels is False
    report = library_audit.build_report(audit(), 5)
    assert report["has_drm_and_channels"] is False
    assert report["source"] == "the player, over REST"


def test_build_report_runs_unchanged_on_this_source():
    r = library_audit.build_report(audit(), 5)
    assert r["totals"]["tracks"] == 7
    assert 0 < r["lossless_pct"] < 100
    assert r["buckets"]["dsd"] == 1
    # And it renders without raising.
    library_audit.render_html(r)
