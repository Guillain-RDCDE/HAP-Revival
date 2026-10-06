"""The two tools that read the on-disk catalogue: the audit and the browser.

Both are driven against a small hdd_browse.db built here with the real
table and column names, so a schema typo would show up as a failing test rather
than on somebody's copy of their player's disk.
"""

import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import library_audit
import library_browser


def build_db(path):
    db = sqlite3.connect(str(path))
    db.executescript(
        """
        CREATE TABLE FT5202 (PROP3601 INTEGER, PROP7020 TEXT, PROP7065 TEXT, PROP7221 TEXT);
        CREATE TABLE FT000A (PROP3601 INTEGER, PROP7020 TEXT, PROP7055 TEXT, PROP6844 INTEGER,
                             PROP78D9 BLOB, PROP7065 TEXT);
        CREATE TABLE FT4502 (PROP3601 INTEGER, PROP7020 TEXT);
        CREATE TABLE FT0002 (PROP3601 INTEGER, PROP7020 TEXT, PROP304B INTEGER, PROP3047 INTEGER,
                             PROP3048 INTEGER, PROP10DE INTEGER, PROP304C INTEGER,
                             PROP2053 INTEGER, PROP10A3 INTEGER, PROP7052 INTEGER,
                             PROP7045 INTEGER, PROPB2BB INTEGER, PROP7007 TEXT,
                             PROP58D3 INTEGER, PROP10DD INTEGER, PROP7065 TEXT);
        INSERT INTO FT5202 VALUES (1, 'Miles Davis', 'davis miles', 'D');
        INSERT INTO FT5202 VALUES (2, 'Portishead', 'portishead', 'P');
        INSERT INTO FT4502 VALUES (1, 'Jazz');
        INSERT INTO FT000A VALUES (10, 'Kind of Blue', 'Miles Davis', 1959, X'FFD8FF', 'kind of blue');
        INSERT INTO FT000A VALUES (11, 'Dummy', 'Portishead', 1994, NULL, 'dummy');
        -- a CD-quality FLAC, a hi-res FLAC, a DSD track, an MP3, a >192k WAV, a dupe, a corrupt entry
        INSERT INTO FT0002 VALUES (100, 'So What', 49, 562, 44100, 16, 1000, 1, 1, 1, 1, 10, 'a.flac', 0, 2, 'so what');
        INSERT INTO FT0002 VALUES (101, 'Blue in Green', 49, 300, 96000, 24, 4000, 2, 1, 1, 1, 10, 'b.flac', 0, 2, 'blue');
        INSERT INTO FT0002 VALUES (102, 'Flamenco', 49, 500, 2822400, 1, 5000, 3, 1, 1, 1, 10, 'c.dsf', 0, 2, 'flamenco');
        INSERT INTO FT0002 VALUES (103, 'Mysterons', 81, 300, 44100, 16, 320, 1, 1, 2, 1, 11, 'd.mp3', 1, 6, 'mysterons');
        INSERT INTO FT0002 VALUES (104, 'Sour Times', 17, 250, 352800, 24, 9000, 2, 1, 2, 1, 11, 'e.wav', 0, 2, 'sour');
        INSERT INTO FT0002 VALUES (105, 'Sour Times', 17, 250, 44100, 16, 1000, 3, 2, 2, 1, 11, 'f.wav', 0, 2, 'sour');
        INSERT INTO FT0002 VALUES (106, 'Ghost', 49, 0, 1048575, 0, 2147483647, 4, 2, 2, 1, 11, 'g.flac', 0, 2, 'ghost');
        """
    )
    db.commit()
    db.close()
    return path


@pytest.fixture
def db_path(tmp_path):
    return build_db(tmp_path / "hdd_browse.db")


# ---------- audit ----------


def test_audit_totals_and_buckets(db_path):
    report = library_audit.build_report(library_audit.Audit(str(db_path)), top=5)
    assert report["totals"] == {"tracks": 7, "albums": 2, "artists": 2, "playtime": 2162}
    # The saturated "Ghost" entry lands in hires by its numbers; the report then
    # lists it separately under `corrupt` rather than hiding it.
    assert report["buckets"] == {"hires": 3, "cd": 2, "lossy": 1, "dsd": 1, "unknown": 0}
    assert report["codec_count"] == {"FLAC": 4, "WAV": 2, "MP3": 1}
    assert report["source"] == "hdd_browse.db" and report["has_drm_and_channels"] is True
    assert report["drm"] == 1 and report["multich"] == 1


def test_audit_lists_the_problems(db_path):
    report = library_audit.build_report(library_audit.Audit(str(db_path)), top=5)
    assert [a["name"] for a in report["missing_cover"]] == ["Dummy"]
    assert [d["title"] for d in report["duplicates"]] == ["Sour Times"]
    assert [t["title"] for t in report["over_ceiling"]] == ["Sour Times"]
    assert [t["title"] for t in report["corrupt"]] == ["Ghost"]


def test_text_report_mentions_every_section(db_path):
    report = library_audit.build_report(library_audit.Audit(str(db_path)), top=5)
    text = library_audit.render_text(report)
    for needle in ("HAP LIBRARY AUDIT", "quality mix", "formats", "sample rates", "bit depths",
                   "multichannel tracks: 1", "DRM-flagged: 1", "Sour Times", "Ghost",
                   "Dummy", "DSD64", "352.8 kHz"):
        assert needle in text, needle


def test_text_report_shows_rest_limits_and_truncation():
    audit = library_audit.RestAudit({
        "host": "h", "artists": [], "albums": [
            {"albumid": i, "name": f"A{i}", "number_of_tracks": 1} for i in range(4)],
        "tracks": [],
    })
    text = library_audit.render_text(library_audit.build_report(audit, top=2))
    assert "not visible over the network API" in text
    assert "… and 2 more" in text
    assert "none — every PCM track is within" in text


def test_html_report_renders_and_escapes(db_path):
    report = library_audit.build_report(library_audit.Audit(str(db_path)), top=5)
    page = library_audit.render_html(report)
    assert "<title>HAP Library Audit</title>" in page
    assert "Sour Times" in page and "Dummy" in page


def test_khz_and_duration_formatting():
    assert library_audit.khz(44100) == "44.1 kHz"
    assert library_audit.khz(2822400) == "DSD64 (2.8224 MHz)"
    assert library_audit.khz(5644800) == "DSD128 (5.6448 MHz)"
    assert library_audit.khz(0) == "(unknown)"
    assert library_audit.fmt_dur_long(90061) == "1d 1h 1m"
    assert library_audit.fmt_dur_long(3660) == "1h 1m"
    assert library_audit.fmt_dur_long(59) == "0m"
    assert library_audit.bar(0.5, width=4) == "██··"


def test_audit_cli_from_db_and_html(db_path, tmp_path, capsys):
    out_html = tmp_path / "r.html"
    assert library_audit.main([str(db_path), "--html", str(out_html), "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert "HAP LIBRARY AUDIT" in out and "HTML report written" in out
    assert out_html.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_audit_cli_argument_errors(db_path, tmp_path, capsys):
    with pytest.raises(SystemExit):
        library_audit.main([str(db_path), "--from-player", "1.2.3.4"])
    with pytest.raises(SystemExit):
        library_audit.main([])
    bogus = tmp_path / "not.db"
    bogus.write_bytes(b"nope")
    assert library_audit.main([str(bogus)]) == 2
    assert "could not read DB" in capsys.readouterr().err


def test_audit_cli_from_player_needs_a_harvest(monkeypatch, capsys):
    monkeypatch.setattr(library_audit.hap_library, "load_harvest", lambda host: None)
    assert library_audit.main(["--from-player", "1.2.3.4"]) == 2
    assert "no catalog cached" in capsys.readouterr().err
    monkeypatch.setattr(library_audit.hap_library, "load_harvest", lambda host: {"tracks": []})
    assert library_audit.main(["--from-player", "1.2.3.4"]) == 2
    assert "no tracks" in capsys.readouterr().err


def test_audit_cli_from_player_runs_on_a_harvest(monkeypatch, capsys):
    harvest = {"host": "h", "artists": [], "albums": [], "tracks": [
        {"name": "t", "duration": 100,
         "codec": {"codec_type": "flac", "sample_rate": 44100, "bit_width": 16}}]}
    monkeypatch.setattr(library_audit.hap_library, "load_harvest", lambda host: harvest)
    assert library_audit.main(["--from-player", "1.2.3.4"]) == 0
    assert "the player, over REST" in capsys.readouterr().out


# ---------- browser ----------


@pytest.fixture
def browser(db_path):
    library_browser.Handler.lib = library_browser.Library(str(db_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), library_browser.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        library_browser.Handler.lib = None


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def test_browser_home_lists_stats_and_newest_albums(browser):
    status, ctype, body = _get(browser, "/")
    assert status == 200 and ctype.startswith("text/html")
    text = body.decode("utf-8")
    assert "2 artists" in text and "2 albums" in text and "7 tracks" in text
    assert text.index("Dummy") < text.index("Kind of Blue"), "newest first"


def test_browser_artist_and_album_pages(browser):
    _, _, body = _get(browser, "/artists")
    text = body.decode("utf-8")
    assert 'href="/artist/1"' in text and "Miles Davis" in text
    _, _, body = _get(browser, "/artist/1")
    assert "Kind of Blue" in body.decode("utf-8")
    _, _, body = _get(browser, "/album/11")
    text = body.decode("utf-8")
    assert "Dummy" in text and "Mysterons" in text and "MP3" in text
    assert "multi-ch" in text and "DRM" in text, "the per-track flags are shown"
    assert ">2.3<" in text, "a multi-disc album numbers tracks disc.track"
    assert "352.8 kHz / 24-bit" in text


def test_browser_albums_search_and_cover(browser):
    _, _, body = _get(browser, "/albums")
    assert "2 shown" in body.decode("utf-8")
    _, _, body = _get(browser, "/search?q=sour")
    text = body.decode("utf-8")
    assert "Tracks (2)" in text and "Sour Times" in text
    _, _, body = _get(browser, "/search?q=")
    assert "Type something" in body.decode("utf-8")
    _, _, body = _get(browser, "/search?q=zzzzzz")
    assert "No matches" in body.decode("utf-8")
    status, ctype, body = _get(browser, "/cover/10")
    assert status == 200 and ctype == "image/jpeg" and body == b"\xff\xd8\xff"
    assert _get(browser, "/cover/11")[0] == 404


def test_browser_404s_and_errors(browser):
    assert _get(browser, "/nothing/here")[0] == 404
    assert _get(browser, "/artist/999")[2].decode("utf-8").count("not found") == 1
    assert _get(browser, "/album/999")[2].decode("utf-8").count("not found") == 1
    assert _get(browser, "/artist/notanumber")[0] == 500


def test_browser_formatting_helpers():
    assert library_browser.fmt_dur(3661) == "1:01:01"
    assert library_browser.fmt_dur(61) == "1:01"
    assert library_browser.fmt_quality(96000, 24) == "96 kHz / 24-bit"
    assert library_browser.fmt_quality(44100, 0) == "44.1 kHz"
    assert library_browser.fmt_quality(0, 16) == ""
    assert library_browser.cover_style(3, 10) == "background-image:url(/cover/3)"
    assert library_browser.cover_style(3, 0) == ""


def test_browser_cli_parser():
    args = library_browser.build_parser().parse_args(["x.db"])
    assert args.port == library_browser.DEFAULT_PORT
    assert library_browser.build_parser().parse_args(["x.db", "9000"]).port == 9000
