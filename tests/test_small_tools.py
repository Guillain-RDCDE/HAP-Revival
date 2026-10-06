"""The small tools: the link checker, the front-panel CLI, the icon generator,
the mock's own entry points and the i18n smoke command."""

import io
import urllib.error

import pytest

import check_links
import hap_png
import hap_screen
import i18n
import make_pwa_icons
import mock_hap

# ---------- check_links ----------


@pytest.mark.parametrize("heading,anchor", [
    ("Own a HAP? Start here", "own-a-hap-start-here"),
    ("`code` and *emphasis*", "code-and-emphasis"),
    ("A [link](http://x) heading", "a-link-heading"),
    ("  Spaces   kept  ", "spaces---kept"),
    ("Accents: Dvořák", "accents-dvořák"),
])
def test_anchor_for_matches_github(heading, anchor):
    assert check_links.anchor_for(heading) == anchor


def test_anchors_skip_fenced_code(tmp_path):
    md = tmp_path / "a.md"
    md.write_text("# Real\n```\n# not a heading\n```\n## Also real\n", encoding="utf-8")
    assert check_links.anchors_of(md) == {"real", "also-real"}
    assert check_links.anchors_of(tmp_path / "missing.md") == set()


def test_check_finds_missing_files_and_dead_anchors(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(
        "# Top\n[ok](docs/a.md#here) [self](#top) [dead](docs/a.md#nope) "
        "[gone](docs/b.md) [ext](https://example.com) [mail](mailto:x@y) "
        "[img](docs/pic.png#frag) [bang](#!x)\n", encoding="utf-8")
    (tmp_path / "docs" / "a.md").write_text("## Here\n", encoding="utf-8")
    (tmp_path / "docs" / "pic.png").write_bytes(b"\x89PNG")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.md").write_text("[bad](nope.md)", encoding="utf-8")

    problems = check_links.check(tmp_path)
    assert len(problems) == 2
    assert any("dead anchor -> docs/a.md#nope" in p for p in problems)
    assert any("missing file -> docs/b.md" in p for p in problems)
    assert sorted(p.name for p in check_links.markdown_files(tmp_path)) == ["README.md", "a.md"]


def test_check_links_main(tmp_path, capsys):
    (tmp_path / "a.md").write_text("[x](#x)\n# X\n", encoding="utf-8")
    assert check_links.main([str(tmp_path)]) == 0
    assert "all relative links" in capsys.readouterr().out
    (tmp_path / "a.md").write_text("[x](#y)\n# X\n", encoding="utf-8")
    assert check_links.main([str(tmp_path)]) == 1
    assert "1 broken reference" in capsys.readouterr().out
    assert check_links.main([str(tmp_path / "absent")]) == 1


def test_the_repository_itself_passes():
    assert check_links.check(check_links.Path(__file__).resolve().parent.parent) == []


# ---------- hap_screen ----------


def test_tool_url_is_cache_busted():
    url = hap_screen.tool_url("1.2.3.4", "screen", "display_png")
    assert url.startswith("http://1.2.3.4:60200/sony/hap?target=screen&cmd=display_png&nocache=")


def test_show_writes_a_png_and_rejects_anything_else(tmp_path, monkeypatch, capsys):
    png = hap_png.encode_png(1, 1, b"\x00\x00\x00")
    monkeypatch.setattr(hap_screen, "tool_get", lambda host, target, cmd: (png, "image/png"))
    out = tmp_path / "s.png"
    assert hap_screen.cmd_show("h", out) == 0
    assert out.read_bytes() == png
    monkeypatch.setattr(hap_screen, "tool_get", lambda host, target, cmd: (b"None", "text/plain"))
    assert hap_screen.cmd_show("h", out) == 1
    assert "not a PNG" in capsys.readouterr().err


def test_keys_are_validated_and_sent_in_sequence(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(hap_screen, "tool_get",
                        lambda host, target, cmd: sent.append((target, cmd)) or (b"None", ""))
    monkeypatch.setattr(hap_screen.time, "sleep", lambda s: sent.append(("sleep", s)))
    assert hap_screen.cmd_key("h", ["down", "enter"]) == 0
    assert sent == [("keyevent", "down"), ("sleep", hap_screen.KEY_SETTLE_SEC),
                    ("keyevent", "enter")]
    assert hap_screen.cmd_key("h", ["down", "nuke"]) == 2
    assert "unknown key(s): nuke" in capsys.readouterr().err
    assert hap_screen.cmd_capture("h") == 0
    assert sent[-1] == ("screen", "capture_png")


def test_screen_main_reports_network_errors(monkeypatch, capsys):
    def boom(host, target, cmd):
        raise urllib.error.URLError("unreachable")

    monkeypatch.setattr(hap_screen, "tool_get", boom)
    assert hap_screen.main(["1.2.3.4", "capture"]) == 1
    assert "cannot reach" in capsys.readouterr().err

    def http(host, target, cmd):
        raise urllib.error.HTTPError("u", 500, "server error", {}, io.BytesIO())

    monkeypatch.setattr(hap_screen, "tool_get", http)
    assert hap_screen.main(["1.2.3.4", "key", "home"]) == 1
    assert "HTTP 500" in capsys.readouterr().err

    def slow(host, target, cmd):
        raise TimeoutError

    monkeypatch.setattr(hap_screen, "tool_get", slow)
    assert hap_screen.main(["1.2.3.4", "show"]) == 1
    assert "timed out" in capsys.readouterr().err


def test_screen_main_show_ok(tmp_path, monkeypatch):
    png = hap_png.encode_png(1, 1, b"\x00\x00\x00")
    monkeypatch.setattr(hap_screen, "tool_get", lambda host, target, cmd: (png, "image/png"))
    assert hap_screen.main(["h", "show", "-o", str(tmp_path / "x.png")]) == 0


# ---------- make_pwa_icons ----------


def test_icons_render_at_the_requested_sizes(tmp_path, capsys):
    written = make_pwa_icons.write_icons(tmp_path)
    assert [p.name for p in written] == [name for name, _, _ in make_pwa_icons.TARGETS]
    for path, (_, size, _) in zip(written, make_pwa_icons.TARGETS, strict=False):
        assert hap_png.png_size(path.read_bytes()) == (size, size)
    assert "Wrote 4 icons" in capsys.readouterr().out


def test_committed_icons_are_what_the_generator_draws():
    """Byte-for-byte they differ (zlib versions); pixel-for-pixel they must not."""
    import struct
    import zlib

    def pixels(png: bytes) -> bytes:
        pos, idat = 8, b""
        while pos < len(png):
            n = struct.unpack(">I", png[pos:pos + 4])[0]
            if png[pos + 4:pos + 8] == b"IDAT":
                idat += png[pos + 8:pos + 8 + n]
            pos += 12 + n
        return zlib.decompress(idat)

    for name, size, maskable in make_pwa_icons.TARGETS:
        committed = (make_pwa_icons.OUT_DIR / name).read_bytes()
        assert pixels(committed) == pixels(make_pwa_icons.render(size, maskable=maskable)), name


def test_maskable_icon_keeps_the_disc_inside_the_safe_zone():
    # A pixel at the edge of a maskable icon must be field, not vinyl.
    plain = make_pwa_icons.render(32)
    maskable = make_pwa_icons.render(32, maskable=True)
    assert plain != maskable
    assert hap_png.png_size(maskable) == (32, 32)


# ---------- mock_hap entry points ----------


def test_mock_parser_defaults():
    args = mock_hap.build_parser().parse_args([])
    assert args.port == 60200 and args.bind == "127.0.0.1" and not args.verbose


def test_mock_main_serves_until_interrupted(monkeypatch, capsys):
    class Server:
        def __init__(self, *a, **k):
            self.closed = False

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            self.closed = True

    made = []
    monkeypatch.setattr(mock_hap, "make_server",
                        lambda bind, port, quiet: made.append(Server()) or made[-1])
    assert mock_hap.main(["--port", "61000", "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "mock HAP-Z1ES listening on http://127.0.0.1:61000/sony/" in out and "Stopping" in out
    assert made[0].closed


def test_mock_serve_in_thread_answers():
    import urllib.request

    server = mock_hap.serve_in_thread("127.0.0.1", 0)
    try:
        host, port = server.server_address
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=5) as r:
            assert b"mock_hap" in r.read()
    finally:
        server.shutdown()
        server.server_close()


# ---------- i18n CLI ----------


def test_i18n_cli(capsys):
    assert i18n._main(["fr", "web.connecting"]) == 0
    assert capsys.readouterr().out.strip() == "connexion…"
    assert i18n._main([]) == 0
    out = capsys.readouterr().out
    assert "Detected language" in out and "Français" in out
