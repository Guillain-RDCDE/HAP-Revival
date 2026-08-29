"""Locating a library entry on the SMB shares, and refusing to guess.

The join is the whole value of this tool, and the measured behaviour it has to
reproduce is specific: matching album *names* to folder names resolved 0 of 12
real cases, matching *file names* resolved 267 of 274. Ties are real duplicate
albums and must stay ties.
"""

import json

import hap_fixit


def index(**shares):
    """Build an index the way crawl_shares would return it."""
    return {
        "host": "192.168.1.28",
        "shares": {name: files for name, files in shares.items()},
        "indexed_at": 0,
    }


DUMMY = [
    ["/Portishead/Dummy (1994)", "01 - Mysterons.flac", 100],
    ["/Portishead/Dummy (1994)", "02 - Sour times.flac", 100],
    ["/Portishead/Dummy (1994)", "cover.jpg", 20],
    ["/Portishead/(1994) Dummy", "01 - Mysterons.flac", 100],
    ["/Portishead/(1994) Dummy", "02 - Sour times.flac", 100],
    ["/Einaudi/Alexandria (2002)", "01 - Ancora.flac", 100],
    ["/Einaudi/Alexandria (2002)", "02 - Dietro casa.flac", 100],
]


def test_locate_finds_the_folder_from_file_names_alone():
    # Note what is *not* used: the album is tagged "Alexandria" and the folder is
    # "Alexandria (2002)". Name matching fails here; file names do not.
    loc = hap_fixit.Locator(index(HAP_Internal=DUMMY))
    folders, hits = loc.locate(["01 - Ancora.flac", "02 - Dietro casa.flac"])
    assert folders == ["HAP_Internal/Einaudi/Alexandria (2002)"]
    assert hits == 2


def test_a_tie_stays_a_tie():
    # Dummy exists twice on this disk. Picking one would tell the user their
    # album is somewhere it also is not.
    loc = hap_fixit.Locator(index(HAP_Internal=DUMMY))
    folders, _ = loc.locate(["01 - Mysterons.flac", "02 - Sour times.flac"])
    assert folders == ["HAP_Internal/Portishead/(1994) Dummy",
                       "HAP_Internal/Portishead/Dummy (1994)"]


def test_a_weak_match_resolves_to_nothing():
    # One file out of twenty in a folder is coincidence, not a location.
    loc = hap_fixit.Locator(index(HAP_Internal=DUMMY))
    folders, hits = loc.locate(["01 - Mysterons.flac"] + [f"x{i}.flac" for i in range(19)])
    assert folders == []
    # One known file, present in two folders: one vote each, best score 1.
    assert hits == 1


def test_unknown_files_locate_nothing():
    loc = hap_fixit.Locator(index(HAP_Internal=DUMMY))
    assert loc.locate(["nowhere.flac"]) == ([], 0)
    assert loc.locate([]) == ([], 0)


def test_both_shares_are_searched():
    loc = hap_fixit.Locator(
        index(HAP_Internal=DUMMY, HAP_External=[["/V/A/Comp", "z.flac", 1]] * 2)
    )
    folders, _ = loc.locate(["z.flac"])
    assert folders == ["HAP_External/V/A/Comp"]


def test_loose_images_are_reported_because_the_player_ignores_them():
    # The HAP reads artwork embedded in tags. A cover.jpg in the folder means the
    # image is already to hand — not that the album has artwork.
    loc = hap_fixit.Locator(index(HAP_Internal=DUMMY))
    assert loc.loose_images("HAP_Internal/Portishead/Dummy (1994)") == ["cover.jpg"]
    assert loc.loose_images("HAP_Internal/Portishead/(1994) Dummy") == []


def test_unc_paths_are_windows_shaped():
    assert hap_fixit.unc("192.168.1.28", "HAP_Internal/A/B") == r"\\192.168.1.28\HAP_Internal\A\B"


# ---------- findings ----------


def harvest_with(album_name, filenames, has_image=False):
    album = {"albumid": 1, "name": album_name, "number_of_tracks": len(filenames),
             "album_artist": {"name": "Portishead"}}
    if has_image:
        album["image"] = {"url": "http://p/1"}
    return {
        "host": "192.168.1.28",
        "artists": [],
        "albums": [album],
        "tracks": [
            {"trackid": i, "name": f"t{i}", "filename": fn, "duration": 100 + i,
             "album": {"albumid": 1, "name": album_name},
             "artist": {"name": "Portishead"},
             "codec": {"codec_type": "flac", "sample_rate": 44100, "bit_width": 16}}
            for i, fn in enumerate(filenames)
        ],
    }


def test_a_coverless_album_is_located_and_its_loose_image_mentioned():
    h = harvest_with("Dummy", ["01 - Mysterons.flac", "02 - Sour times.flac"])
    found = hap_fixit.build_findings(h, index(HAP_Internal=DUMMY))
    cover = [f for f in found if f.kind == "cover"]
    assert len(cover) == 1
    assert cover[0].ambiguous, "this album is on the disk twice"
    assert "2 copies on disk" in cover[0].detail
    assert cover[0].path.startswith(r"\\192.168.1.28\HAP_Internal")


def test_an_album_with_artwork_produces_no_cover_finding():
    h = harvest_with("Dummy", ["01 - Mysterons.flac"], has_image=True)
    found = hap_fixit.build_findings(h, index(HAP_Internal=DUMMY))
    assert [f for f in found if f.kind == "cover"] == []


def test_an_unlocatable_album_is_kept_and_flagged():
    # Losing the finding would be worse: the album still has no artwork.
    h = harvest_with("Ghost record", ["nowhere-1.flac", "nowhere-2.flac"])
    found = hap_fixit.build_findings(h, index(HAP_Internal=DUMMY))
    cover = [f for f in found if f.kind == "cover"][0]
    assert cover.folders == [] and cover.paths == []
    assert "not found" in cover.detail


def test_the_html_report_escapes_and_lists_every_finding():
    h = harvest_with("A & B <script>", ["01 - Mysterons.flac", "02 - Sour times.flac"])
    found = hap_fixit.build_findings(h, index(HAP_Internal=DUMMY))
    page = hap_fixit.render_html(found, "192.168.1.28")
    assert "<script>" not in page.split("<script>\nfunction cp")[0].replace(
        "&lt;script&gt;", ""), "titles must be escaped"
    assert "A &amp; B" in page
    assert page.count("<tr") == len(found)


def test_index_round_trips_through_disk(tmp_path):
    idx = index(HAP_Internal=DUMMY)
    target = tmp_path / "shares.json"
    hap_fixit.save_index(idx, target)
    back = hap_fixit.load_index("192.168.1.28", target)
    assert back["shares"]["HAP_Internal"] == json.loads(json.dumps(DUMMY))
    assert hap_fixit.load_index("x", tmp_path / "nope.json") is None
