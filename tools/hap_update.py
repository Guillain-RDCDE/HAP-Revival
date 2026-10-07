#!/usr/bin/env python3
"""
One version number, and one way to find out whether a newer one exists.

Every tool in this repository shares `VERSION`. The GitHub release that
carries `HapSync.exe` is tagged `hap-sync-v<VERSION>`, and this module asks
GitHub's releases API for the latest one, compares, and remembers the answer
for a day under `~/.hap-revival/update-check.json` so a tool run twice in a
row makes one request, not two. Setting `HAP_NO_UPDATE_CHECK=1` turns the
whole thing off (the test suite does, so no test ever touches the network).

Applying the update depends on how the tool was installed:

- **frozen** (`HapSync.exe` built by PyInstaller): the new exe is downloaded
  next to the running one, its SHA-256 is checked against what GitHub
  published for the asset, and the two files are swapped by rename (Windows
  lets a running exe be renamed, not overwritten). The new exe is started and
  the old one exits; the leftover `.old` is removed on the next start.
- **git** (a clone): `git pull --ff-only`, refused while the tree has local
  changes so nothing of the owner's is ever overwritten.
- **source** (a downloaded zip): the release's zipball is extracted over the
  folder, file by file. Files that exist only locally (config, caches) stay.

Stdlib only. Nothing here runs without being asked: a tool calls `check()`
or `notice_at_exit()`, a GUI calls `apply()` after the owner clicked.

Command line:

    python tools/hap_update.py check [--force] [--json]
    python tools/hap_update.py apply [--no-launch]
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import i18n
from hap_common import REPO_ROOT, USER_CACHE_DIR, force_utf8_stdio, read_json_dict, write_json

# ---------------------------------------------------------------- identity

#: The version every tool reports. Bump it with the CHANGELOG entry; the
#: release workflow refuses a tag that does not match it.
VERSION = "0.4.0"
REPO = "Guillain-RDCDE/HAP-Revival"
#: Release tags are `hap-sync-v<VERSION>`: the exe is what most people download.
TAG_PREFIX = "hap-sync-v"
EXE_NAME = "HapSync.exe"
SUMS_NAME = "SHA256SUMS.txt"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
#: Set to 1 to never contact GitHub. The tests set it.
OPT_OUT_ENV = "HAP_NO_UPDATE_CHECK"
USER_AGENT = f"HAP-Revival/{VERSION} (+https://github.com/{REPO})"

#: Where the last answer is kept, and for how long it counts as fresh.
CACHE_PATH = USER_CACHE_DIR / "update-check.json"
CHECK_INTERVAL_SEC = 24 * 3600
#: After a failed check, try again sooner than a full day.
RETRY_INTERVAL_SEC = 3600
FETCH_TIMEOUT_SEC = 6
DOWNLOAD_TIMEOUT_SEC = 30


class UpdateError(RuntimeError):
    """Anything that stops a check or an update, with a message for the owner."""


# ---------------------------------------------------------------- versions

_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+)|\.?([A-Za-z][0-9A-Za-z.]*))?$")


def parse_version(text: str) -> tuple[int, int, int, int, str]:
    """``0.4.0`` -> ``(0, 4, 0, 1, "")``; ``0.4.0-rc1`` -> ``(0, 4, 0, 0, "rc1")``.

    The fourth element makes a pre-release sort before its final version.
    Raises ValueError on anything that is not a version.
    """
    m = _VERSION_RE.match(text.strip())
    if not m:
        raise ValueError(f"not a version: {text!r}")
    major, minor, patch, dashed, dotted = m.groups()
    pre = dashed or dotted
    return int(major), int(minor), int(patch), 0 if pre else 1, pre or ""


def compare_versions(a: str, b: str) -> int:
    """-1, 0 or 1 as `a` is older than, the same as, or newer than `b`."""
    pa, pb = parse_version(a), parse_version(b)
    return (pa > pb) - (pa < pb)


def version_from_tag(tag: str) -> str:
    """``hap-sync-v0.3.0`` -> ``0.3.0`` (a bare ``v0.3.0`` is accepted too)."""
    text = tag.strip()
    if text.startswith(TAG_PREFIX):
        text = text[len(TAG_PREFIX):]
    return text[1:] if text.startswith("v") else text


def tag_for(version: str = VERSION) -> str:
    return f"{TAG_PREFIX}{version}"


# ---------------------------------------------------------------- the release


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int = 0
    #: Hex digest when GitHub published one for the upload (it does since 2025).
    sha256: str | None = None


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    url: str
    notes: str = ""
    published: str = ""
    zipball: str = ""
    assets: tuple[Asset, ...] = ()

    def asset(self, name: str) -> Asset | None:
        return next((a for a in self.assets if a.name == name), None)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Release:
        assets = tuple(Asset(**a) for a in data.get("assets", ()))
        fields = {k: v for k, v in data.items() if k != "assets"}
        return cls(assets=assets, **fields)


_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


def parse_release(data: dict) -> Release:
    """A `Release` from the releases API's JSON. Raises UpdateError when it is not one."""
    tag = str(data.get("tag_name") or "")
    try:
        version = version_from_tag(tag)
        parse_version(version)
    except ValueError as exc:
        raise UpdateError(f"release tag {tag!r} carries no version") from exc
    assets = []
    for item in data.get("assets") or ():
        digest = str(item.get("digest") or "")
        sha = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None
        assets.append(Asset(
            name=str(item.get("name") or ""),
            url=str(item.get("browser_download_url") or ""),
            size=int(item.get("size") or 0),
            sha256=sha,
        ))
    return Release(
        version=version,
        tag=tag,
        url=str(data.get("html_url") or RELEASES_URL),
        notes=str(data.get("body") or ""),
        published=str(data.get("published_at") or ""),
        zipball=str(data.get("zipball_url") or ""),
        assets=tuple(assets),
    )


def _request(url: str, accept: str) -> Request:
    return Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})


def fetch_latest(timeout: float = FETCH_TIMEOUT_SEC) -> Release:
    """Ask GitHub for the latest published release. Raises UpdateError when it cannot."""
    try:
        with urlopen(_request(API_URL, "application/vnd.github+json"), timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except HTTPError as exc:
        raise UpdateError(f"GitHub answered HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise UpdateError(f"could not reach GitHub: {exc}") from exc
    if not isinstance(data, dict):
        raise UpdateError("unexpected answer from GitHub")
    return parse_release(data)


def fetch_text(url: str, timeout: float = FETCH_TIMEOUT_SEC) -> str:
    try:
        with urlopen(_request(url, "text/plain"), timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"could not download {url}: {exc}") from exc


def resolve_sha256(release: Release, asset: Asset) -> str | None:
    """The published SHA-256 for `asset`, from the API's digest, the release's
    SHA256SUMS file, or the hash written in the release notes; None if nowhere."""
    if asset.sha256:
        return asset.sha256
    sums = release.asset(SUMS_NAME)
    if sums is not None:
        for line in fetch_text(sums.url).splitlines():
            parts = line.split()
            if (len(parts) >= 2 and parts[-1].lstrip("*") == asset.name
                    and _SHA256_RE.match(parts[0])):
                return parts[0].lower()
    where = release.notes.find(asset.name)
    if where >= 0:
        m = _SHA256_RE.search(release.notes, where)
        if m:
            return m.group(1).lower()
    return None


# ---------------------------------------------------------------- the check


@dataclass
class Status:
    """What a check found. `available` is the only thing most callers look at."""

    current: str = VERSION
    latest: Release | None = None
    checked_at: float = 0.0
    error: str | None = None
    disabled: bool = False
    from_cache: bool = False

    @property
    def available(self) -> bool:
        if self.latest is None:
            return False
        try:
            return compare_versions(self.latest.version, self.current) > 0
        except ValueError:
            return False

    def to_dict(self) -> dict:
        return {
            "current": self.current,
            "latest": self.latest.to_dict() if self.latest else None,
            "available": self.available,
            "checked_at": self.checked_at,
            "error": self.error,
            "disabled": self.disabled,
            "from_cache": self.from_cache,
        }


def is_disabled() -> bool:
    return os.environ.get(OPT_OUT_ENV, "").strip().lower() not in ("", "0", "no", "false")


def _load_cache(path: Path) -> tuple[Release | None, float, str | None]:
    data = read_json_dict(path)
    if not data:
        return None, 0.0, None
    release = None
    if isinstance(data.get("release"), dict):
        try:
            release = Release.from_dict(data["release"])
        except (TypeError, ValueError):
            release = None
    try:
        checked_at = float(data.get("checked_at") or 0.0)
    except (TypeError, ValueError):
        checked_at = 0.0
    error = data.get("error")
    return release, checked_at, str(error) if error else None


def cached_status(path: Path | None = None) -> Status:
    """The last answer, without touching the network (for the exit-time notice)."""
    if is_disabled():
        return Status(disabled=True)
    release, checked_at, error = _load_cache(path or CACHE_PATH)
    return Status(latest=release, checked_at=checked_at, error=error, from_cache=True)


def check(force: bool = False, *, path: Path | None = None, now: Callable[[], float] = time.time,
          fetch: Callable[[], Release] | None = None) -> Status:
    """Is a newer release out? Cached for a day; `force` asks GitHub now.

    Never raises: a network failure comes back as `error`, with the last known
    release still filled in so the owner is not told "unknown" after one
    flaky morning.
    """
    if is_disabled():
        return Status(disabled=True)
    cache = path or CACHE_PATH
    release, checked_at, error = _load_cache(cache)
    age = now() - checked_at
    fresh_for = RETRY_INTERVAL_SEC if error else CHECK_INTERVAL_SEC
    if not force and checked_at and age < fresh_for:
        return Status(latest=release, checked_at=checked_at, error=error, from_cache=True)
    try:
        release, error = (fetch or fetch_latest)(), None
    except UpdateError as exc:
        error = str(exc)
    checked_at = now()
    try:
        write_json(cache, {
            "checked_at": checked_at,
            "release": release.to_dict() if release else None,
            "error": error,
        }, indent=2, atomic=True)
    except OSError:
        pass  # a read-only home must not turn a check into a failure
    return Status(latest=release, checked_at=checked_at, error=error)


def check_in_background(callback: Callable[[Status], None] | None = None,
                        force: bool = False) -> threading.Thread:
    """Run `check` on a daemon thread; `callback(status)` when it is done.

    The thread is never joined: a tool that exits first simply leaves the
    cache for the next run.
    """
    def run() -> None:
        try:
            status = check(force=force)
        except Exception as exc:  # the thread must never die with a traceback
            status = Status(error=f"{type(exc).__name__}: {exc}")
        if callback is not None:
            try:
                callback(status)
            except Exception:
                pass

    thread = threading.Thread(target=run, name="hap-update-check", daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------- installs

Progress = Callable[[int, int], None]


@dataclass
class Result:
    """What `apply` did. `restart` means the running program is still the old code."""

    kind: str
    message: str
    restart: bool = False
    launched: bool = False
    executable: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def install_kind(root: Path | None = None) -> str:
    """``frozen`` for HapSync.exe, ``git`` for a clone, ``source`` for a zip."""
    if getattr(sys, "frozen", False):
        return "frozen"
    base = root or REPO_ROOT
    if (base / ".git").exists() and shutil.which("git"):
        return "git"
    return "source"


def download(url: str, dest: Path, *, expected_sha256: str | None = None,
             progress: Progress | None = None, timeout: float = DOWNLOAD_TIMEOUT_SEC,
             chunk_size: int = 1 << 16) -> str:
    """Stream `url` into `dest`, verifying the SHA-256 when one is expected.

    Writes a `.part` sibling first, so an interrupted download never leaves a
    half file under the real name. Returns the hex digest. On a mismatch the
    file is deleted and UpdateError is raised.
    """
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    done = 0
    try:
        with urlopen(_request(url, "application/octet-stream"), timeout=timeout) as r, \
                open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0)
            while True:
                block = r.read(chunk_size)
                if not block:
                    break
                out.write(block)
                digest.update(block)
                done += len(block)
                if progress is not None:
                    progress(done, total)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"download failed: {exc}") from exc
    actual = digest.hexdigest()
    if expected_sha256 and actual != expected_sha256.lower():
        part.unlink(missing_ok=True)
        raise UpdateError(
            f"checksum mismatch for {dest.name}: expected {expected_sha256.lower()[:16]}…, "
            f"got {actual[:16]}…; the download was discarded")
    os.replace(part, dest)
    return actual


def update_frozen(release: Release, *, progress: Progress | None = None, launch: bool = True,
                  executable: Path | None = None,
                  spawn: Callable[..., object] = subprocess.Popen) -> Result:
    """Replace the running HapSync.exe with the release's, verified, and start it."""
    exe = Path(executable or sys.executable).resolve()
    asset = release.asset(EXE_NAME)
    if asset is None:
        raise UpdateError(f"release {release.tag} carries no {EXE_NAME}; see {release.url}")
    expected = resolve_sha256(release, asset)
    if not expected:
        raise UpdateError(
            f"no SHA-256 is published for {EXE_NAME} in {release.tag}; "
            f"refusing to install an unverified file (download it from {release.url})")
    new = exe.with_name(exe.name + ".new")
    old = exe.with_name(exe.name + ".old")
    download(asset.url, new, expected_sha256=expected, progress=progress)
    old.unlink(missing_ok=True)
    exe.rename(old)
    try:
        new.rename(exe)
    except OSError:
        old.rename(exe)  # put the working one back before reporting
        raise
    if launch:
        spawn([str(exe)], cwd=str(exe.parent), close_fds=True)
    return Result("frozen", f"installed {EXE_NAME} {release.version}", restart=True,
                  launched=launch, executable=str(exe))


def remove_leftovers(executable: Path | None = None) -> list[str]:
    """Delete the `.old` / `.new` / `.part` files a previous update left next to the exe."""
    if executable is None and not getattr(sys, "frozen", False):
        return []
    exe = Path(executable or sys.executable)
    removed = []
    for suffix in (".old", ".new", ".new.part"):
        leftover = exe.with_name(exe.name + suffix)
        try:
            if leftover.exists():
                leftover.unlink()
                removed.append(leftover.name)
        except OSError:
            pass  # still locked by the exiting process; next start gets it
    return removed


def update_git(root: Path | None = None, run: Callable[..., object] = subprocess.run) -> Result:
    """`git pull --ff-only` in the clone, refused while the tree has local changes."""
    base = Path(root or REPO_ROOT)

    def git(*args: str):
        try:
            return run(["git", "-C", str(base), *args], capture_output=True, text=True,
                       timeout=120, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(f"git {args[0]} failed: {exc}") from exc

    status = git("status", "--porcelain", "--untracked-files=no")
    if status.returncode != 0:
        raise UpdateError(f"git status failed: {(status.stderr or status.stdout).strip()}")
    if status.stdout.strip():
        raise UpdateError("the clone has local changes; commit or stash them, "
                          "then run `git pull --ff-only`")
    pull = git("pull", "--ff-only")
    if pull.returncode != 0:
        raise UpdateError(f"git pull failed: {(pull.stderr or pull.stdout).strip()}")
    lines = [ln for ln in pull.stdout.strip().splitlines() if ln.strip()]
    return Result("git", lines[-1] if lines else "pulled", restart=True)


def _safe_members(archive: zipfile.ZipFile) -> tuple[str, list[zipfile.ZipInfo]]:
    """The zipball's single top folder and its file members, refusing paths that escape."""
    members = []
    tops: set[str] = set()
    for info in archive.infolist():
        name = info.filename
        parts = Path(name).parts
        if not parts or ".." in parts or name.startswith(("/", "\\")):
            raise UpdateError(f"refusing archive member {name!r}")
        tops.add(parts[0])
        if not info.is_dir():
            members.append(info)
    if len(tops) != 1:
        raise UpdateError("the archive is not a single release folder")
    return tops.pop(), members


def update_source(release: Release, *, root: Path | None = None,
                  progress: Progress | None = None) -> Result:
    """Lay the release's files over a folder that came from a zip download.

    Only files that exist in the release are written; `hap_sync.json` and
    everything else the owner added stay untouched. The zipball comes over
    HTTPS from GitHub; it has no published checksum.
    """
    base = Path(root or REPO_ROOT)
    if not (base / "tools" / "hap_update.py").exists():
        raise UpdateError(f"{base} does not look like a HAP-Revival folder")
    if not release.zipball:
        raise UpdateError(f"release {release.tag} has no source archive")
    written = 0
    with tempfile.TemporaryDirectory(prefix="hap-update-") as tmp:
        archive_path = Path(tmp) / "release.zip"
        download(release.zipball, archive_path, progress=progress)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                top, members = _safe_members(archive)
                for info in members:
                    rel = Path(info.filename).relative_to(top)
                    target = base / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    written += 1
        except zipfile.BadZipFile as exc:
            raise UpdateError(f"the downloaded archive is unreadable: {exc}") from exc
    return Result("source", f"{written} files written from {release.tag}", restart=True)


def apply(status: Status | None = None, *, progress: Progress | None = None,
          launch: bool = True) -> Result:
    """Install the latest release the way this copy was installed.

    Returns a `Result` whose `restart` says the running program is still the
    old code (`launched` when the new exe is already starting). Raises
    UpdateError with a message for the owner when it cannot.
    """
    if status is None:
        status = check(force=True)
    if status.disabled:
        raise UpdateError(f"update checks are disabled ({OPT_OUT_ENV})")
    if status.latest is None:
        raise UpdateError(status.error or "no release information")
    if not status.available:
        return Result(install_kind(), f"{status.current} is the latest release")
    kind = install_kind()
    if kind == "frozen":
        return update_frozen(status.latest, progress=progress, launch=launch)
    if kind == "git":
        return update_git()
    return update_source(status.latest, progress=progress)


def restart_self(argv: list[str] | None = None) -> None:
    """Start this program again with the same command line, and leave.

    `execv` on POSIX; Windows has no exec, so a child is started and this
    process exits once it is running.
    """
    args = [sys.executable, *(sys.argv if argv is None else argv)]
    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "win32":  # pragma: no cover - needs Windows
        subprocess.Popen(args, close_fds=True)
        os._exit(0)
    os.execv(sys.executable, args)


# ---------------------------------------------------------------- for tools


def add_version_flag(parser: argparse.ArgumentParser,
                     flag: str = "--version") -> argparse.ArgumentParser:
    """`--version` on a tool's parser: prints `<prog> <VERSION>` and exits.

    `flag` is for the one tool whose `--version` already means something else
    (`call.py`, where it is the API method's version).
    """
    parser.add_argument(flag, action="version", version=f"%(prog)s {VERSION} (HAP-Revival)")
    return parser


_NOTICE_INSTALLED = False


def notice_line(status: Status, lang: str | None = None) -> str | None:
    """The one line a tool prints when a newer release is known, else None."""
    if not status.available or status.latest is None:
        return None
    return i18n.t("update.notice", lang, latest=status.latest.version, current=status.current,
                  url=status.latest.url)


def notice_at_exit(stream=None) -> bool:
    """For command-line tools: say once, at exit, that a newer release exists.

    Prints only when the stream is a terminal (never into a pipe or a JSON
    consumer), only from the cache (the network is refreshed on a background
    thread for the *next* run), and never when opted out. Returns whether
    the notice was armed.
    """
    global _NOTICE_INSTALLED
    out = stream if stream is not None else sys.stderr
    if _NOTICE_INSTALLED or is_disabled() or not getattr(out, "isatty", lambda: False)():
        return False
    _NOTICE_INSTALLED = True
    check_in_background()

    def say() -> None:
        line = notice_line(cached_status())
        if line:
            print(line, file=out)

    atexit.register(say)
    return True


# ---------------------------------------------------------------- command line


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_version_flag(parser)
    sub = parser.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="Say whether a newer release exists (exit 3 when it does).")
    chk.add_argument("--force", action="store_true", help="Ask GitHub now, ignoring the cache.")
    chk.add_argument("--json", action="store_true", help="Print the status as JSON.")
    app = sub.add_parser("apply",
                         help="Install the latest release the way this copy was installed.")
    app.add_argument("--no-launch", action="store_true",
                     help="For HapSync.exe: swap the file but do not start the new one.")
    return parser


def _cmd_check(args: argparse.Namespace) -> int:
    status = check(force=args.force)
    if args.json:
        print(json.dumps(status.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(i18n.t("update.cli.current", current=status.current))
        if status.disabled:
            print(i18n.t("update.cli.disabled", env=OPT_OUT_ENV))
        elif status.latest is not None:
            print(i18n.t("update.cli.latest", latest=status.latest.version, url=status.latest.url))
        if status.error:
            print(i18n.t("update.cli.error", err=status.error), file=sys.stderr)
        if status.available:
            print(i18n.t("update.cli.available", latest=status.latest.version))
        elif status.latest is not None:
            print(i18n.t("update.cli.up_to_date"))
    if status.disabled:
        return 0
    if status.error and status.latest is None:
        return 2
    return 3 if status.available else 0


def _cmd_apply(args: argparse.Namespace) -> int:
    def progress(done: int, total: int) -> None:
        if total:
            print(f"\r  {done * 100 // total:3d}%", end="", file=sys.stderr, flush=True)

    try:
        result = apply(progress=progress, launch=not args.no_launch)
    except UpdateError as exc:
        print(i18n.t("update.cli.error", err=exc), file=sys.stderr)
        return 2
    print(i18n.t("update.cli.applied", kind=result.kind, msg=result.message))
    if result.restart and not result.launched:
        print(i18n.t("update.cli.restart"))
    return 0


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    args = build_parser().parse_args(argv)
    return _cmd_check(args) if args.cmd == "check" else _cmd_apply(args)


if __name__ == "__main__":
    raise SystemExit(main())
