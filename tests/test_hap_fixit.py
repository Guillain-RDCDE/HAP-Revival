"""Locating a library entry on the SMB shares, and refusing to guess.

The join is the whole value of this tool, and the measured behaviour it has to
reproduce is specific: matching album *names* to folder names resolved 0 of 12
real cases, matching *file names* resolved 267 of 274. Ties are real duplicate
albums and must stay ties.
"""

import json

import pytest

import hap_fixit


@pytest.fixture(autouse=True)
def english(monkeypatch):
    """Pin the language: finding details are translated, assertions are not.

    Without this the suite passes or fails according to the OS locale of
    whoever runs it.
    """
    monkeypatch.setenv("HAP_LANG", "en")


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


def test_finding_details_follow_the_active_language(monkeypatch):
    # These strings show up in all three surfaces. They were hard-coded English
    # at first, which put "2 tracks · no artwork" inside a French window.
    h = harvest_with("Ghost record", ["nowhere-1.flac", "nowhere-2.flac"])
    monkeypatch.setenv("HAP_LANG", "fr")
    fr = hap_fixit.build_findings(h, index(HAP_Internal=DUMMY))[0].detail
    monkeypatch.setenv("HAP_LANG", "de")
    de = hap_fixit.build_findings(h, index(HAP_Internal=DUMMY))[0].detail

    assert "pistes" in fr and "introuvable" in fr
    assert "Titel" in de
    assert fr != de


# ---------- the synced local copy ----------


def test_to_local_swaps_the_share_for_its_source_folder(tmp_path):
    maps = {"HAP_Internal": str(tmp_path / "Internal")}
    got = hap_fixit.to_local("HAP_Internal/Superpoze/(2010) Lost cosmonaut", maps)
    assert got == str(tmp_path / "Internal" / "Superpoze" / "(2010) Lost cosmonaut")
    assert hap_fixit.to_local("HAP_External/A/B", maps) == "", "unmapped share -> nothing"


def test_local_path_is_only_offered_when_the_folder_really_exists(tmp_path):
    maps = {"HAP_Internal": str(tmp_path)}
    (tmp_path / "X" / "Album").mkdir(parents=True)

    here = hap_fixit.Finding("cover", "A", "d", ["HAP_Internal/X/Album"], "1.2.3.4", maps)
    gone = hap_fixit.Finding("cover", "B", "d", ["HAP_Internal/X/Absent"], "1.2.3.4", maps)

    assert here.is_local and here.local_path == str(tmp_path / "X" / "Album")
    # A stale mapping must not send an editor at a folder that is not there.
    assert not gone.is_local and gone.local_paths == []


def test_best_path_prefers_local_and_falls_back_to_the_player(tmp_path):
    maps = {"HAP_Internal": str(tmp_path)}
    (tmp_path / "X" / "Album").mkdir(parents=True)

    local = hap_fixit.Finding("cover", "A", "d", ["HAP_Internal/X/Album"], "1.2.3.4", maps)
    remote = hap_fixit.Finding("cover", "B", "d", ["HAP_Internal/X/Absent"], "1.2.3.4", maps)

    assert local.best_path == str(tmp_path / "X" / "Album")
    assert remote.best_path == r"\\1.2.3.4\HAP_Internal\X\Absent"
    assert hap_fixit.Finding("cover", "C", "d", [], "1.2.3.4", maps).best_path == ""


def test_findings_carry_no_local_route_when_nothing_is_mapped():
    h = harvest_with("Dummy", ["01 - Mysterons.flac", "02 - Sour times.flac"])
    found = hap_fixit.build_findings(h, index(HAP_Internal=DUMMY), maps={})
    assert not any(f.is_local for f in found)
    assert found[0].best_path.startswith(r"\\")


def test_load_sync_maps_reads_the_shared_config(tmp_path):
    cfg = tmp_path / "hap_sync.json"
    cfg.write_bytes(json.dumps({
        "host": "1.2.3.4",
        "maps": [{"local": "D:\\FLAC\\Internal", "share": "HAP_Internal"},
                 {"local": "", "share": "HAP_External"}],
    }).encode("utf-8"))

    maps = hap_fixit.load_sync_maps(cfg)

    assert maps == {"HAP_Internal": "D:\\FLAC\\Internal"}, "an empty local is not a mapping"
    assert hap_fixit.load_sync_maps(tmp_path / "absent.json") == {}


def test_a_differently_filed_local_library_is_still_found(tmp_path):
    """The case the prefix swap cannot serve: same music, different folders.

    A user whose local library is not organised like the player's gets nothing
    from swapping a path prefix. File names still match, which is the same
    reason the album could be located on the player at all.
    """
    # On the player: /Portishead/Dummy (1994). Locally: nothing like it.
    local = tmp_path / "Mes disques" / "trip-hop" / "portishead 94"
    local.mkdir(parents=True)
    for name in ("01 - Mysterons.flac", "02 - Sour times.flac"):
        (local / name).write_bytes(b"")

    scanned = hap_fixit.scan_local([str(tmp_path)])
    loc = hap_fixit.local_locator(scanned)

    found = hap_fixit.resolve_local(
        ["HAP_Internal/Portishead/Dummy (1994)"],
        ["01 - Mysterons.flac", "02 - Sour times.flac"],
        {},          # no mapping at all
        loc,
    )
    assert found == [str(local)]


def test_the_prefix_swap_wins_when_it_works(tmp_path):
    # Cheaper and exact: no scan should be consulted when the mapping resolves.
    mirrored = tmp_path / "Sync" / "X" / "Album"
    mirrored.mkdir(parents=True)
    (mirrored / "01 - a.flac").write_bytes(b"")
    decoy = tmp_path / "Elsewhere" / "somewhere else"
    decoy.mkdir(parents=True)
    (decoy / "01 - a.flac").write_bytes(b"")

    loc = hap_fixit.local_locator(hap_fixit.scan_local([str(tmp_path)]))
    found = hap_fixit.resolve_local(
        ["HAP_Internal/X/Album"], ["01 - a.flac"],
        {"HAP_Internal": str(tmp_path / "Sync")}, loc,
    )
    assert found == [str(mirrored)]


def test_scan_local_ignores_folders_that_are_not_there(tmp_path):
    scanned = hap_fixit.scan_local([str(tmp_path / "absent"), str(tmp_path)])
    assert list(scanned["roots"]) == [str(tmp_path)]
    assert hap_fixit.local_locator({"roots": {}}) is None
    assert hap_fixit.local_locator(None) is None


def test_scan_local_keeps_only_music_and_artwork(tmp_path):
    (tmp_path / "A").mkdir()
    for name in ("track.flac", "cover.jpg", "notes.txt", "desktop.ini"):
        (tmp_path / "A" / name).write_bytes(b"")

    rows = hap_fixit.scan_local([str(tmp_path)])["roots"][str(tmp_path)]

    assert sorted(r[1] for r in rows) == ["cover.jpg", "track.flac"]


def test_local_index_round_trips(tmp_path):
    (tmp_path / "A").mkdir()
    (tmp_path / "A" / "x.flac").write_bytes(b"")
    scanned = hap_fixit.scan_local([str(tmp_path)])

    target = tmp_path / "local.json"
    hap_fixit.save_local_index(scanned, "1.2.3.4", target)
    back = hap_fixit.load_local_index("1.2.3.4", target)

    assert back["roots"] == scanned["roots"]
    assert hap_fixit.load_local_index("1.2.3.4", tmp_path / "none.json") is None


def test_the_html_report_shows_the_local_copy_first(tmp_path):
    maps = {"HAP_Internal": str(tmp_path)}
    (tmp_path / "X" / "Album").mkdir(parents=True)
    f = hap_fixit.Finding("cover", "A", "d", ["HAP_Internal/X/Album"], "1.2.3.4", maps)

    page = hap_fixit.render_html([f], "1.2.3.4")

    local_at = page.index(str(tmp_path / "X" / "Album"))
    unc_at = page.index(r"\\1.2.3.4\HAP_Internal\X\Album")
    assert local_at < unc_at, "the copy to edit belongs at the top"


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
