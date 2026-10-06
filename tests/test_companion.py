"""Tests for the pre-flight validator and the library decoder.

Covers the bits the README promises but that are easy to silently break:
  - the >192 kHz ceiling flag (the Forza PCM cap, docs/11-audio-path.md)
  - junk / unsupported / missing-cover accounting
  - the semantic diff against the HAP's SQLite catalog (the PROP-code schema)
  - the command line around both
"""

import sqlite3

from test_hap_media import write_flac, write_wav

import hap_companion as comp

# ---------- scan_folder ----------


def test_scan_folder_full_accounting(tmp_path):
    a = tmp_path / "Artist" / "Album"
    a.mkdir(parents=True)
    write_flac(a / "01.flac", 96000)            # ok, within ceiling
    write_flac(a / "02.flac", 352800)           # > 192 kHz -> hi-res flag
    write_wav(a / "03.wav", 384000)             # > 192 kHz -> hi-res flag
    (a / "cover.jpg").write_bytes(b"img")        # has cover
    (a / "Thumbs.db").write_bytes(b"j")          # junk
    (a / "movie.mkv").write_bytes(b"v")          # unsupported
    (a / "booklet.pdf").write_bytes(b"p")        # sidecar: neither counted nor flagged

    b = tmp_path / "Artist2" / "Album2"          # audio but NO cover
    b.mkdir(parents=True)
    (b / "song.mp3").write_bytes(b"m")

    r = comp.scan_folder(str(tmp_path))
    assert r["n_ok"] == 4                          # 2 flac + 1 wav + 1 mp3
    assert r["n_junk"] == 1
    assert r["n_unsup"] == 1
    assert r["n_hi"] == 2                          # the 352.8k flac + the 384k wav
    assert any("movie.mkv" in u for u in r["unsup"])
    assert any("Thumbs.db" in j for j in r["junk"])
    assert any("352.8 kHz" in h for h in r["hires"])
    # only Artist2/Album2 lacks a cover; Artist/Album has cover.jpg
    assert len(r["no_cover"]) == 1
    assert r["no_cover"][0].endswith("Album2")


def test_scan_folder_clean(tmp_path):
    a = tmp_path / "A" / "B"
    a.mkdir(parents=True)
    write_flac(a / "01.flac", 44100)
    (a / "cover.jpg").write_bytes(b"img")
    r = comp.scan_folder(str(tmp_path))
    assert r["n_junk"] == r["n_unsup"] == r["n_hi"] == 0
    assert r["no_cover"] == []


def test_cmd_validate_prints_the_verdict_and_exit_code(tmp_path, capsys):
    a = tmp_path / "A" / "B"
    a.mkdir(parents=True)
    write_flac(a / "01.flac", 44100)
    (a / "cover.jpg").write_bytes(b"img")
    assert comp.cmd_validate(str(tmp_path)) == 0
    assert "Verdict: clean" in capsys.readouterr().out

    (a / "Thumbs.db").write_bytes(b"j")
    assert comp.cmd_validate(str(tmp_path)) == 1
    out = capsys.readouterr().out
    assert "[JUNK]" in out and "Thumbs.db" in out and "issues found" in out


def test_print_section_truncates_long_lists(capsys):
    comp.print_section("T", [f"item{i}" for i in range(30)], limit=25)
    out = capsys.readouterr().out
    assert "T (30):" in out and "item24" in out and "item25" not in out
    assert "and 5 more" in out
    comp.print_section("Empty", [])
    assert capsys.readouterr().out == ""
    comp.print_section("Empty", [], show_empty=True)
    assert "Empty (0):" in capsys.readouterr().out


# ---------- diff against the SQLite catalog ----------


def _build_catalog(db_path):
    """Build a tiny DB matching the real HAP schema the decoder reads:
    tracks (FT0002) join artists (FT5202) and albums (FT000A) on PROP ids."""
    db = sqlite3.connect(str(db_path))
    db.execute("CREATE TABLE FT5202 (PROP3601 INTEGER, PROP7020 TEXT)")   # artists
    db.execute("CREATE TABLE FT000A (PROP3601 INTEGER, PROP7020 TEXT)")   # albums
    db.execute("CREATE TABLE FT0002 (PROP7052 INTEGER, PROPB2BB INTEGER)")  # tracks
    db.execute("INSERT INTO FT5202 VALUES (1, 'Miles Davis')")
    db.execute("INSERT INTO FT000A VALUES (10, 'Kind of Blue')")
    db.execute("INSERT INTO FT0002 VALUES (1, 10)")
    db.commit()
    db.close()


def test_diff_library(tmp_path):
    db = tmp_path / "hdd_browse.db"
    _build_catalog(db)

    music = tmp_path / "music"
    (music / "Miles Davis" / "Kind of Blue").mkdir(parents=True)   # already on HAP
    (music / "Bonobo" / "Black Sands").mkdir(parents=True)         # new
    (music / "loose_file.txt").write_text("ignored")               # not a dir -> skipped

    r = comp.diff_library(str(db), str(music))
    assert r["have_count"] == 1
    assert "Bonobo / Black Sands" in r["new"]
    assert "Miles Davis / Kind of Blue" in r["existing"]


def test_diff_library_matches_album_name_only(tmp_path):
    # The HAP album-artist may differ from the folder artist; the decoder also
    # matches on album name alone. A different artist + same album = existing.
    db = tmp_path / "hdd_browse.db"
    _build_catalog(db)
    music = tmp_path / "music"
    (music / "Various Artists" / "Kind of Blue").mkdir(parents=True)
    r = comp.diff_library(str(db), str(music))
    assert "Various Artists / Kind of Blue" in r["existing"]


def test_cmd_diff_prints_both_lists(tmp_path, capsys):
    db = tmp_path / "hdd_browse.db"
    _build_catalog(db)
    music = tmp_path / "music"
    (music / "Bonobo" / "Black Sands").mkdir(parents=True)
    assert comp.cmd_diff(str(db), str(music)) == 0
    out = capsys.readouterr().out
    assert "NEW — not on the HAP (1):" in out and "+ Bonobo / Black Sands" in out
    assert "ALREADY on the HAP — skip these (0):" in out


# ---------- wake / check / CLI ----------


def test_cmd_wake_validates_the_mac(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(comp, "send_wol", lambda mac: sent.append(mac))
    assert comp.cmd_wake("80:56:F2:85:0E:27") == 0
    assert sent == ["80:56:F2:85:0E:27"]
    monkeypatch.undo()  # back to the real sender, which validates before touching the network
    assert comp.cmd_wake("nope") == 2
    assert "12 hex digits" in capsys.readouterr().err


def test_cmd_check_reports_each_port(monkeypatch, capsys):
    monkeypatch.setattr(comp, "tcp_port_open", lambda ip, port, timeout=3.0: port == 60200)
    assert comp.cmd_check("1.2.3.4") == 1
    out = capsys.readouterr().out
    assert "445" in out and "CLOSED" in out and "60200" in out and "[FAIL]" in out
    monkeypatch.setattr(comp, "tcp_port_open", lambda ip, port, timeout=3.0: True)
    assert comp.cmd_check("1.2.3.4") == 0
    assert "[OK]" in capsys.readouterr().out


def test_main_dispatches_subcommands(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(comp, "send_wol", lambda mac: None)
    assert comp.main(["wake", "80:56:F2:85:0E:27"]) == 0
    a = tmp_path / "A" / "B"
    a.mkdir(parents=True)
    write_flac(a / "01.flac", 44100)
    assert comp.main(["validate", str(tmp_path)]) == 0
    # A missing database is an error message, not a traceback.
    assert comp.main(["diff", str(tmp_path / "nope.db"), str(tmp_path)]) == 2
    assert "error" in capsys.readouterr().err
