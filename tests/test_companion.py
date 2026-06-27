"""Tests for the pre-flight validator and the library decoder.

Covers the bits the README promises but that are easy to silently break:
  - FLAC / WAV header parsing (real sample-rate, stdlib only)
  - the >192 kHz ceiling flag (the Forza PCM cap, docs/11-audio-path.md)
  - junk / unsupported / missing-cover accounting
  - the semantic diff against the HAP's SQLite catalog (the PROP-code schema)
"""

import sqlite3
import struct
import wave

import hap_companion as comp


# ---------- header parsers ----------


def _write_flac(path, sample_rate, bits=24, channels=2):
    """Write a minimal file with a valid FLAC STREAMINFO block for the parser.

    Only the 4-byte word at STREAMINFO offset 10 matters: it packs
    sample_rate(20) | channels-1(3) | bits-1(5) | top-4-bits-of-total-samples."""
    v = (sample_rate << 12) | ((channels - 1) << 9) | ((bits - 1) << 4) | 0
    info = b"\x00" * 10 + struct.pack(">I", v) + b"\x00" * 20  # 34-byte STREAMINFO
    block_header = b"\x00\x00\x00\x22"  # type 0 (STREAMINFO), length 0x22 = 34
    path.write_bytes(b"fLaC" + block_header + info)


def _write_wav(path, sample_rate, bits=16, channels=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(bits // 8)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00" * (bits // 8) * channels)  # one frame is enough


def test_flac_streaminfo_roundtrip(tmp_path):
    p = tmp_path / "a.flac"
    _write_flac(p, 96000, bits=24, channels=2)
    assert comp.flac_streaminfo(str(p)) == (96000, 24, 2)


def test_flac_streaminfo_dxd(tmp_path):
    p = tmp_path / "dxd.flac"
    _write_flac(p, 352800, bits=24, channels=2)
    assert comp.flac_streaminfo(str(p))[0] == 352800


def test_flac_streaminfo_rejects_non_flac(tmp_path):
    p = tmp_path / "x.flac"
    p.write_bytes(b"NOTFLAC" + b"\x00" * 40)
    assert comp.flac_streaminfo(str(p)) is None


def test_wav_info_roundtrip(tmp_path):
    p = tmp_path / "a.wav"
    _write_wav(p, 44100, bits=16, channels=2)
    assert comp.wav_info(str(p)) == (44100, 16, 2)


# ---------- scan_folder ----------


def test_scan_folder_full_accounting(tmp_path):
    a = tmp_path / "Artist" / "Album"
    a.mkdir(parents=True)
    _write_flac(a / "01.flac", 96000)            # ok, within ceiling
    _write_flac(a / "02.flac", 352800)           # > 192 kHz -> hi-res flag
    _write_wav(a / "03.wav", 384000)             # > 192 kHz -> hi-res flag
    (a / "cover.jpg").write_bytes(b"img")        # has cover
    (a / "Thumbs.db").write_bytes(b"j")          # junk
    (a / "movie.mkv").write_bytes(b"v")          # unsupported

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
    # only Artist2/Album2 lacks a cover; Artist/Album has cover.jpg
    assert len(r["no_cover"]) == 1
    assert r["no_cover"][0].endswith("Album2")


def test_scan_folder_clean(tmp_path):
    a = tmp_path / "A" / "B"
    a.mkdir(parents=True)
    _write_flac(a / "01.flac", 44100)
    (a / "cover.jpg").write_bytes(b"img")
    r = comp.scan_folder(str(tmp_path))
    assert r["n_junk"] == r["n_unsup"] == r["n_hi"] == 0
    assert r["no_cover"] == []


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
