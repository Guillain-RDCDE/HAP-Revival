"""The version check and the self-update, driven without GitHub.

Every network call goes to a loopback HTTP server that hands out whatever
bytes the test registered, or to a fake `fetch`. The exe swap runs on a fake
executable in a temp folder, the git path on a fake `subprocess.run`, the zip
path on an archive built in the test. Nothing here touches ~/.hap-revival
(conftest redirects the cache) and the opt-out set by conftest is lifted only
inside the tests that drive the checker itself."""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import hap_update
import pytest
from hap_update import Asset, Release, Status, UpdateError

# ---------- fixtures ----------


@pytest.fixture
def enabled(monkeypatch):
    """Lift conftest's opt-out so the checker runs (against fakes)."""
    monkeypatch.delenv(hap_update.OPT_OUT_ENV, raising=False)


@pytest.fixture
def http_files():
    """A loopback server: `files[path] = bytes` (or an int for an HTTP error)."""
    files: dict[str, bytes | int] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = files.get(self.path)
            if body is None:
                self.send_error(404)
                return
            if isinstance(body, int):
                self.send_error(body)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[:2]
    files["__base__"] = f"http://{host}:{port}".encode()
    try:
        yield files
    finally:
        httpd.shutdown()
        httpd.server_close()


def base(files) -> str:
    return files["__base__"].decode()


def release(version="9.9.9", **extra) -> Release:
    return Release(version=version, tag=f"hap-sync-v{version}",
                   url=f"https://github.com/x/y/releases/tag/hap-sync-v{version}", **extra)


SAMPLE_API = {
    "tag_name": "hap-sync-v0.3.0",
    "html_url": "https://github.com/Guillain-RDCDE/HAP-Revival/releases/tag/hap-sync-v0.3.0",
    "body": "**Verify your download** — SHA-256 of `HapSync.exe`:\n\n```text\n"
            + "5207e0d1" * 8 + "\n```\n",
    "published_at": "2026-09-25T09:26:28Z",
    "zipball_url": "https://api.github.com/repos/Guillain-RDCDE/HAP-Revival/zipball/hap-sync-v0.3.0",
    "assets": [{
        "name": "HapSync.exe",
        "browser_download_url": "https://github.com/x/HapSync.exe",
        "size": 14849799,
        "digest": "sha256:" + "ab" * 32,
    }],
}


# ---------- versions ----------


@pytest.mark.parametrize("text,parsed", [
    ("0.4.0", (0, 4, 0, 1, "")),
    ("v1.2.3", (1, 2, 3, 1, "")),
    ("0.4.0-rc1", (0, 4, 0, 0, "rc1")),
    ("0.4.0.dev2", (0, 4, 0, 0, "dev2")),
])
def test_parse_version(text, parsed):
    assert hap_update.parse_version(text) == parsed


@pytest.mark.parametrize("bad", ["", "1.2", "x.y.z", "1.2.3.4.5", "hap-sync-v0.3.0"])
def test_parse_version_rejects_non_versions(bad):
    with pytest.raises(ValueError):
        hap_update.parse_version(bad)


def test_compare_versions_orders_prereleases_first():
    assert hap_update.compare_versions("0.3.0", "0.4.0") == -1
    assert hap_update.compare_versions("0.4.0", "0.4.0") == 0
    assert hap_update.compare_versions("0.10.0", "0.9.9") == 1
    assert hap_update.compare_versions("0.4.0-rc1", "0.4.0") == -1


def test_tags_round_trip():
    assert hap_update.version_from_tag("hap-sync-v0.3.0") == "0.3.0"
    assert hap_update.version_from_tag("v0.3.0") == "0.3.0"
    assert hap_update.version_from_tag("0.3.0") == "0.3.0"
    assert hap_update.tag_for("0.4.0") == "hap-sync-v0.4.0"
    assert hap_update.tag_for() == f"hap-sync-v{hap_update.VERSION}"


def test_the_shipped_version_is_a_final_semver():
    *_numbers, final, pre = hap_update.parse_version(hap_update.VERSION)
    assert final == 1 and pre == ""


# ---------- the release ----------


def test_parse_release_reads_tag_assets_and_digest():
    rel = hap_update.parse_release(SAMPLE_API)
    assert rel.version == "0.3.0" and rel.tag == "hap-sync-v0.3.0"
    assert rel.asset("HapSync.exe").sha256 == "ab" * 32
    assert rel.asset("HapSync.exe").size == 14849799
    assert rel.asset("nope") is None
    assert rel.zipball.endswith("/zipball/hap-sync-v0.3.0")
    assert Release.from_dict(rel.to_dict()) == rel


def test_parse_release_rejects_a_tag_without_a_version():
    with pytest.raises(UpdateError, match="carries no version"):
        hap_update.parse_release({"tag_name": "nightly"})


def test_resolve_sha256_falls_back_to_sums_file_then_notes(monkeypatch):
    rel = hap_update.parse_release({**SAMPLE_API, "assets": [
        {"name": "HapSync.exe", "browser_download_url": "u"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "sums"},
    ]})
    exe = rel.asset("HapSync.exe")
    assert exe.sha256 is None
    monkeypatch.setattr(hap_update, "fetch_text",
                        lambda url, timeout=0: f"{'cd' * 32}  *HapSync.exe\n{'ef' * 32}  other\n")
    assert hap_update.resolve_sha256(rel, exe) == "cd" * 32

    no_sums = hap_update.parse_release({**SAMPLE_API, "assets": [
        {"name": "HapSync.exe", "browser_download_url": "u"}]})
    assert hap_update.resolve_sha256(no_sums, no_sums.asset("HapSync.exe")) == "5207e0d1" * 8

    nothing = hap_update.parse_release({**SAMPLE_API, "body": "", "assets": [
        {"name": "HapSync.exe", "browser_download_url": "u"}]})
    assert hap_update.resolve_sha256(nothing, nothing.asset("HapSync.exe")) is None


def test_fetch_latest_against_a_local_server(monkeypatch, http_files):
    http_files["/latest"] = json.dumps(SAMPLE_API).encode()
    monkeypatch.setattr(hap_update, "API_URL", base(http_files) + "/latest")
    assert hap_update.fetch_latest().version == "0.3.0"

    http_files["/latest"] = 503
    with pytest.raises(UpdateError, match="HTTP 503"):
        hap_update.fetch_latest()
    http_files["/latest"] = b"[1, 2]"
    with pytest.raises(UpdateError, match="unexpected answer"):
        hap_update.fetch_latest()
    http_files["/latest"] = b"not json"
    with pytest.raises(UpdateError, match="could not reach"):
        hap_update.fetch_latest()
    monkeypatch.setattr(hap_update, "API_URL", "http://127.0.0.1:1/latest")
    with pytest.raises(UpdateError, match="could not reach"):
        hap_update.fetch_latest()
    with pytest.raises(UpdateError, match="could not download"):
        hap_update.fetch_text("http://127.0.0.1:1/sums")


# ---------- the check ----------


def test_check_is_a_no_op_when_opted_out(monkeypatch):
    calls = []
    status = hap_update.check(fetch=lambda: calls.append(1))
    assert status.disabled and not status.available and calls == []
    assert hap_update.cached_status().disabled
    monkeypatch.setenv(hap_update.OPT_OUT_ENV, "0")
    assert not hap_update.is_disabled()


def test_check_caches_for_a_day_and_keeps_the_last_release_on_failure(enabled, tmp_path):
    cache = tmp_path / "update-check.json"
    clock = [1_000_000.0]
    fetched = []

    def fetch():
        fetched.append(1)
        return release("9.9.9")

    first = hap_update.check(path=cache, now=lambda: clock[0], fetch=fetch)
    assert first.available and not first.from_cache and first.latest.version == "9.9.9"
    assert json.loads(cache.read_text())["release"]["tag"] == "hap-sync-v9.9.9"

    clock[0] += 3600
    again = hap_update.check(path=cache, now=lambda: clock[0], fetch=fetch)
    assert again.from_cache and again.available and len(fetched) == 1

    clock[0] += hap_update.CHECK_INTERVAL_SEC

    def failing():
        raise UpdateError("offline")

    third = hap_update.check(path=cache, now=lambda: clock[0], fetch=failing)
    assert third.error == "offline" and third.latest.version == "9.9.9", "last answer kept"
    assert third.available

    clock[0] += hap_update.RETRY_INTERVAL_SEC - 1
    fourth = hap_update.check(path=cache, now=lambda: clock[0], fetch=fetch)
    assert fourth.from_cache and fourth.error == "offline", "an error is retried sooner, not now"
    clock[0] += 2
    fifth = hap_update.check(path=cache, now=lambda: clock[0], fetch=fetch)
    assert fifth.error is None and len(fetched) == 2

    forced = hap_update.check(force=True, path=cache, now=lambda: clock[0], fetch=fetch)
    assert not forced.from_cache and len(fetched) == 3

    cached = hap_update.cached_status(cache)
    assert cached.from_cache and cached.latest.version == "9.9.9"


def test_check_survives_a_corrupt_cache_and_an_unwritable_one(enabled, tmp_path):
    cache = tmp_path / "update-check.json"
    cache.write_text('{"checked_at": "soon", "release": {"nope": 1}}', encoding="utf-8")
    status = hap_update.check(path=cache, fetch=lambda: release("0.0.1"))
    assert status.latest.version == "0.0.1" and not status.available
    assert hap_update.cached_status(tmp_path / "missing.json").latest is None

    blocked = tmp_path / "dir-not-file"
    blocked.mkdir()
    status = hap_update.check(path=blocked, fetch=lambda: release("9.9.9"))
    assert status.available and status.error is None


def test_status_handles_an_unparsable_latest():
    assert not Status(latest=release("weird")).available
    assert Status(latest=None).to_dict()["latest"] is None


def test_check_in_background_calls_back(enabled, monkeypatch):
    monkeypatch.setattr(hap_update, "check", lambda force=False: Status(latest=release()))
    seen = []
    done = threading.Event()
    hap_update.check_in_background(lambda s: (seen.append(s), done.set())).join(5)
    assert done.wait(5) and seen[0].available

    def boom(force=False):
        raise RuntimeError("thread must not die")

    monkeypatch.setattr(hap_update, "check", boom)
    seen.clear()
    hap_update.check_in_background(lambda s: seen.append(s)).join(5)
    assert "thread must not die" in seen[0].error
    hap_update.check_in_background(lambda s: 1 / 0).join(5)  # a bad callback is swallowed too


# ---------- installs ----------


def test_install_kind(monkeypatch, tmp_path):
    monkeypatch.setattr(hap_update.sys, "frozen", True, raising=False)
    assert hap_update.install_kind() == "frozen"
    monkeypatch.delattr(hap_update.sys, "frozen")
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(hap_update.shutil, "which", lambda name: "/usr/bin/git")
    assert hap_update.install_kind(tmp_path) == "git"
    monkeypatch.setattr(hap_update.shutil, "which", lambda name: None)
    assert hap_update.install_kind(tmp_path) == "source"
    assert hap_update.install_kind(tmp_path / "elsewhere") == "source"


def test_download_verifies_and_cleans_up(http_files, tmp_path):
    payload = b"exe bytes " * 1000
    http_files["/HapSync.exe"] = payload
    dest = tmp_path / "HapSync.exe.new"
    seen = []
    digest = hap_update.download(base(http_files) + "/HapSync.exe", dest,
                                 expected_sha256=hashlib.sha256(payload).hexdigest().upper(),
                                 progress=lambda d, t: seen.append((d, t)))
    assert dest.read_bytes() == payload and digest == hashlib.sha256(payload).hexdigest()
    assert seen[-1] == (len(payload), len(payload))

    with pytest.raises(UpdateError, match="checksum mismatch"):
        hap_update.download(base(http_files) + "/HapSync.exe", tmp_path / "bad",
                            expected_sha256="00" * 32)
    assert not (tmp_path / "bad").exists() and not (tmp_path / "bad.part").exists()

    with pytest.raises(UpdateError, match="download failed"):
        hap_update.download(base(http_files) + "/missing", tmp_path / "gone")
    assert not list(tmp_path.glob("gone*"))


def test_update_frozen_swaps_the_exe_and_starts_it(http_files, tmp_path):
    new_bytes = b"new exe"
    http_files["/HapSync.exe"] = new_bytes
    exe = tmp_path / "HapSync.exe"
    exe.write_bytes(b"old exe")
    (tmp_path / "HapSync.exe.old").write_bytes(b"older")  # a leftover from last time
    rel = release(assets=(Asset("HapSync.exe", base(http_files) + "/HapSync.exe",
                                sha256=hashlib.sha256(new_bytes).hexdigest()),))
    spawned = []
    result = hap_update.update_frozen(rel, executable=exe, spawn=lambda *a, **k: spawned.append(a))
    assert result.kind == "frozen" and result.restart and result.launched
    assert exe.read_bytes() == new_bytes
    assert (tmp_path / "HapSync.exe.old").read_bytes() == b"old exe"
    assert spawned == [([str(exe)],)]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["HapSync.exe", "HapSync.exe.old"]
    assert hap_update.remove_leftovers(exe) == ["HapSync.exe.old"]
    assert hap_update.remove_leftovers(exe) == []

    quiet = hap_update.update_frozen(rel, executable=exe, launch=False,
                                     spawn=lambda *a, **k: spawned.append(a))
    assert not quiet.launched and len(spawned) == 1


def test_update_frozen_refuses_without_asset_or_checksum(tmp_path, http_files):
    exe = tmp_path / "HapSync.exe"
    exe.write_bytes(b"old")
    with pytest.raises(UpdateError, match=r"carries no HapSync\.exe"):
        hap_update.update_frozen(release(), executable=exe)
    unverified = release(assets=(Asset("HapSync.exe", base(http_files) + "/x"),))
    with pytest.raises(UpdateError, match="unverified"):
        hap_update.update_frozen(unverified, executable=exe)
    assert exe.read_bytes() == b"old"


def test_update_frozen_restores_the_old_exe_when_the_swap_fails(http_files, tmp_path, monkeypatch):
    http_files["/HapSync.exe"] = b"new"
    exe = tmp_path / "HapSync.exe"
    exe.write_bytes(b"old")
    rel = release(assets=(Asset("HapSync.exe", base(http_files) + "/HapSync.exe",
                                sha256=hashlib.sha256(b"new").hexdigest()),))
    real_rename = hap_update.Path.rename

    def rename(self, target):
        if self.name.endswith(".new"):
            raise PermissionError("locked")
        return real_rename(self, target)

    monkeypatch.setattr(hap_update.Path, "rename", rename)
    with pytest.raises(PermissionError):
        hap_update.update_frozen(rel, executable=exe, spawn=lambda *a, **k: None)
    assert exe.read_bytes() == b"old"


def test_remove_leftovers_is_a_no_op_when_not_frozen(monkeypatch):
    monkeypatch.delattr(hap_update.sys, "frozen", raising=False)
    assert hap_update.remove_leftovers() == []


class Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_update_git_pulls_a_clean_clone_only(tmp_path):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[3:])
        if cmd[3] == "status":
            return Done(0, "")
        return Done(0, "Updating 1234..5678\nFast-forward\n 3 files changed\n")

    result = hap_update.update_git(tmp_path, run=run)
    assert result.kind == "git" and result.restart and result.message == " 3 files changed"
    assert calls == [["status", "--porcelain", "--untracked-files=no"], ["pull", "--ff-only"]]

    with pytest.raises(UpdateError, match="local changes"):
        hap_update.update_git(tmp_path, run=lambda cmd, **kw: Done(0, " M tools/x.py\n"))
    with pytest.raises(UpdateError, match="git status failed"):
        hap_update.update_git(tmp_path, run=lambda cmd, **kw: Done(128, "", "not a repo"))

    def pull_fails(cmd, **kw):
        return Done(0, "") if cmd[3] == "status" else Done(1, "", "diverged")

    with pytest.raises(UpdateError, match="git pull failed: diverged"):
        hap_update.update_git(tmp_path, run=pull_fails)

    def no_git(cmd, **kw):
        raise FileNotFoundError("git")

    with pytest.raises(UpdateError, match="git status failed"):
        hap_update.update_git(tmp_path, run=no_git)

    assert hap_update.update_git(tmp_path, run=lambda cmd, **kw: Done(0, "")).message == "pulled"


def make_zip(top: str, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if top:
            z.writestr(f"{top}/", "")
        for name, data in files.items():
            z.writestr(f"{top}/{name}" if top else name, data)
    return buf.getvalue()


def test_update_source_lays_the_release_over_the_folder(http_files, tmp_path):
    root = tmp_path / "HAP-Revival"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "hap_update.py").write_text("old", encoding="utf-8")
    (root / "tools" / "hap_sync.json").write_text("mine", encoding="utf-8")
    http_files["/zip"] = make_zip("Guillain-RDCDE-HAP-Revival-abc123", {
        "tools/hap_update.py": b"new",
        "docs/new.md": b"# new",
    })
    rel = release(zipball=base(http_files) + "/zip")
    result = hap_update.update_source(rel, root=root)
    assert result.kind == "source" and result.restart and result.message.startswith("2 files")
    assert (root / "tools" / "hap_update.py").read_text(encoding="utf-8") == "new"
    assert (root / "docs" / "new.md").read_text(encoding="utf-8") == "# new"
    assert (root / "tools" / "hap_sync.json").read_text(encoding="utf-8") == "mine", "untouched"


def test_update_source_refuses_bad_inputs(http_files, tmp_path):
    root = tmp_path / "HAP-Revival"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "hap_update.py").write_text("old", encoding="utf-8")
    with pytest.raises(UpdateError, match="does not look like"):
        hap_update.update_source(release(zipball="x"), root=tmp_path)
    with pytest.raises(UpdateError, match="no source archive"):
        hap_update.update_source(release(), root=root)

    http_files["/zip"] = make_zip("top", {"../escape.txt": b"x"})
    with pytest.raises(UpdateError, match="refusing archive member"):
        hap_update.update_source(release(zipball=base(http_files) + "/zip"), root=root)
    assert not (tmp_path / "escape.txt").exists()

    http_files["/zip"] = make_zip("", {"a/x": b"1", "b/y": b"2"})
    with pytest.raises(UpdateError, match="single release folder"):
        hap_update.update_source(release(zipball=base(http_files) + "/zip"), root=root)

    http_files["/zip"] = b"this is not a zip"
    with pytest.raises(UpdateError, match="unreadable"):
        hap_update.update_source(release(zipball=base(http_files) + "/zip"), root=root)
    assert (root / "tools" / "hap_update.py").read_text(encoding="utf-8") == "old"


def test_apply_dispatches_on_the_install_kind(monkeypatch):
    status = Status(latest=release("9.9.9"))
    monkeypatch.setattr(hap_update, "install_kind", lambda root=None: "git")
    monkeypatch.setattr(hap_update, "update_git", lambda: hap_update.Result("git", "ok", True))
    assert hap_update.apply(status).kind == "git"

    monkeypatch.setattr(hap_update, "install_kind", lambda root=None: "frozen")
    monkeypatch.setattr(hap_update, "update_frozen",
                        lambda rel, progress=None, launch=True:
                        hap_update.Result("frozen", rel.version, True, launch))
    assert hap_update.apply(status, launch=False).message == "9.9.9"

    monkeypatch.setattr(hap_update, "install_kind", lambda root=None: "source")
    monkeypatch.setattr(hap_update, "update_source",
                        lambda rel, progress=None: hap_update.Result("source", "zip", True))
    assert hap_update.apply(status).message == "zip"

    assert hap_update.apply(Status(latest=release("0.0.1"))).message.endswith("latest release")
    with pytest.raises(UpdateError, match="disabled"):
        hap_update.apply(Status(disabled=True))
    with pytest.raises(UpdateError, match="offline"):
        hap_update.apply(Status(error="offline"))
    monkeypatch.setattr(hap_update, "check", lambda force=False: status)
    assert hap_update.apply().message == "zip", "no status given: a forced check"


def test_restart_self_execs_the_same_command_line(monkeypatch):
    seen = []
    monkeypatch.setattr(hap_update.os, "execv", lambda exe, args: seen.append((exe, args)))
    monkeypatch.setattr(hap_update.sys, "platform", "linux")
    hap_update.restart_self(["tools/webui.py", "--demo"])
    python = hap_update.sys.executable
    assert seen == [(python, [python, "tools/webui.py", "--demo"])]


# ---------- for tools ----------


def test_version_flag(capsys):
    import argparse

    parser = hap_update.add_version_flag(argparse.ArgumentParser(prog="hap_x"))
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"hap_x {hap_update.VERSION} (HAP-Revival)"


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_notice_at_exit_prints_from_the_cache_on_a_terminal(enabled, monkeypatch):
    registered = []
    monkeypatch.setattr(hap_update.atexit, "register", lambda fn: registered.append(fn))
    monkeypatch.setattr(hap_update, "check_in_background",
                        lambda callback=None, force=False: None)
    monkeypatch.setattr(hap_update, "_NOTICE_INSTALLED", False)

    assert not hap_update.notice_at_exit(io.StringIO()), "a pipe never gets the notice"
    out = Tty()
    assert hap_update.notice_at_exit(out)
    assert not hap_update.notice_at_exit(out), "armed once per process"

    monkeypatch.setattr(hap_update, "cached_status", lambda path=None: Status())
    registered[0]()
    assert out.getvalue() == ""
    monkeypatch.setattr(hap_update, "cached_status",
                        lambda path=None: Status(current="0.1.0", latest=release("0.2.0")))
    registered[0]()
    assert "0.2.0" in out.getvalue() and "0.1.0" in out.getvalue()

    monkeypatch.setattr(hap_update, "_NOTICE_INSTALLED", False)
    monkeypatch.setenv(hap_update.OPT_OUT_ENV, "1")
    assert not hap_update.notice_at_exit(Tty())


# ---------- command line ----------


def test_cli_check(enabled, monkeypatch, capsys):
    monkeypatch.setenv("HAP_LANG", "en")
    monkeypatch.setattr(hap_update, "fetch_latest", lambda timeout=0: release("9.9.9"))
    assert hap_update.main(["check", "--force"]) == 3
    out = capsys.readouterr().out
    assert "9.9.9" in out and "newer version" in out

    assert hap_update.main(["check", "--json"]) == 3
    data = json.loads(capsys.readouterr().out)
    assert data["available"] and data["latest"]["version"] == "9.9.9"

    monkeypatch.setattr(hap_update, "fetch_latest", lambda timeout=0: release("0.0.1"))
    assert hap_update.main(["check", "--force"]) == 0
    assert "latest version" in capsys.readouterr().out

    def offline(timeout=0):
        raise UpdateError("offline")

    monkeypatch.setattr(hap_update, "fetch_latest", offline)
    assert hap_update.main(["check", "--force"]) == 0, "last answer still known"
    assert "offline" in capsys.readouterr().err
    monkeypatch.setattr(hap_update, "CACHE_PATH", hap_update.CACHE_PATH.with_name("empty.json"))
    assert hap_update.main(["check", "--force"]) == 2

    monkeypatch.setenv(hap_update.OPT_OUT_ENV, "1")
    assert hap_update.main(["check"]) == 0
    assert "off" in capsys.readouterr().out


def test_cli_apply(monkeypatch, capsys):
    monkeypatch.setenv("HAP_LANG", "en")
    seen = []

    def fake_apply(progress=None, launch=True):
        progress(50, 100)
        seen.append(launch)
        return hap_update.Result("git", "Fast-forward", restart=True)

    monkeypatch.setattr(hap_update, "apply", fake_apply)
    assert hap_update.main(["apply", "--no-launch"]) == 0
    captured = capsys.readouterr()
    assert "Fast-forward" in captured.out and "again" in captured.out and "50%" in captured.err
    assert seen == [False]

    def refuse(progress=None, launch=True):
        raise UpdateError("no way")

    monkeypatch.setattr(hap_update, "apply", refuse)
    assert hap_update.main(["apply"]) == 2
    assert "no way" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        hap_update.main(["--version"])
