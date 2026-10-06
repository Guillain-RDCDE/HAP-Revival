"""The on-disk catalogue decoder shared by the audit, the browser and the diff."""

import sqlite3

import pytest

import hap_catalog


@pytest.mark.parametrize("code,name", [
    (49, "FLAC"), (81, "MP3"), (97, "AAC"), (65, "ALAC"), (129, "WMA"),
    (17, "WAV"), (33, "AIFF"), (0, "?"), (None, "?"), (7, "#7"),
])
def test_codec_name(code, name):
    assert hap_catalog.codec_name(code) == name


def test_open_catalog_is_read_only_and_tolerant(tmp_path):
    db_path = tmp_path / "hdd_browse.db"
    db = sqlite3.connect(str(db_path))
    db.execute("CREATE TABLE FT5202 (PROP3601 INTEGER, PROP7020 TEXT)")
    db.execute("INSERT INTO FT5202 VALUES (1, 'Dvořák')")
    # One Latin-1 name among UTF-8 ones, exactly as the player's catalogue has it.
    db.execute("INSERT INTO FT5202 VALUES (2, CAST(X'5AE920526F626572746F' AS TEXT))")
    db.commit()
    db.close()

    ro = hap_catalog.open_catalog(str(db_path))
    rows = ro.execute("SELECT PROP3601 id, PROP7020 name FROM FT5202 ORDER BY id").fetchall()
    assert rows[0]["name"] == "Dvořák", "rows are addressable by alias"
    assert rows[1]["name"].startswith("Z") and rows[1]["name"].endswith(" Roberto")
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO FT5202 VALUES (3, 'x')")
    ro.close()
    assert not (tmp_path / "hdd_browse.db-journal").exists()


def test_open_catalog_refuses_a_missing_file(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        hap_catalog.open_catalog(str(tmp_path / "absent.db"))
