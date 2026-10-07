#!/usr/bin/env python3
"""
HAP-Revival i18n — one tiny, dependency-free translation layer shared by every
user-facing surface in the project (the web UI, the CLI client, the tkinter
sync GUI, and the library tools).

Design goals:
    - **Stdlib only.** No gettext .mo compilation, no babel, no jinja. One JSON
      file per language under `tools/locales/` and a `t()` function.
    - **One source of truth.** Every translatable string lives in those files,
      keyed by a dotted path (e.g. "web.sound.dsee"). Python code calls
      `t("web.sound.dsee")`; the web UI embeds `all_catalogs()` as a JSON blob
      and translates in the browser so the language switch is instant.
    - **Graceful fallback.** A missing key in the active language falls back to
      English; a key missing even in English returns the key itself (so a typo
      is visible, never a crash).
    - **Auto-detect, manual override.** Language is chosen from, in order:
      an explicit override (CLI `--lang`, env `HAP_LANG`, web `?lang=` / saved
      choice) → the browser `Accept-Language` header (web) → the OS locale
      (CLI/GUI) → English.

Keys are grouped by surface:
    common.*   shared atoms (on/off/auto, yes/no…)
    cli.*      hap_client.py's command-line output
    notify.*   hap_notify.py
    web.*      the browser control surface (webui.py)
    gui.*      the tkinter sync app (hap_gui.py)
    fix.*      hap_fixit.py's findings and report

English (`locales/en.json`) is complete and authoritative; every other file is
expected to mirror it, and any gap silently falls back to English. Adding a
language is one new file plus one line in LANGUAGES below.

Supported languages: en (source), fr, ja, de, es, it.

CLI smoke test:
    python tools/i18n.py            # list languages + a sample line in each
    python tools/i18n.py fr web.sound.dsee
"""

from __future__ import annotations

import json
import locale
import os
import sys
from pathlib import Path

# Order matters: the first entry is the canonical source language and the
# universal fallback. Keep "en" first.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "ja": "日本語",
    "de": "Deutsch",
    "es": "Español",
    "it": "Italiano",
}

DEFAULT_LANG = "en"

# Next to this file in source; inside the PyInstaller bundle when frozen
# (tools/build_gui.ps1 adds the folder with --add-data).
LOCALES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "locales"


def load_catalog(code: str, folder: Path = LOCALES_DIR) -> dict[str, str]:
    """Read one language's `<code>.json`. A missing file is an empty catalog."""
    path = folder / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected an object of key -> string")
    return {str(k): str(v) for k, v in data.items()}


def load_catalogs(folder: Path = LOCALES_DIR) -> dict[str, dict[str, str]]:
    """Every language's catalogue. A malformed file is reported and skipped,
    so one bad edit degrades that language to English instead of breaking
    every tool at import time."""
    catalogs: dict[str, dict[str, str]] = {}
    for code in LANGUAGES:
        try:
            catalogs[code] = load_catalog(code, folder)
        except ValueError as exc:
            print(f"i18n: ignoring {folder / (code + '.json')}: {exc}", file=sys.stderr)
            catalogs[code] = {}
    return catalogs


CATALOGS: dict[str, dict[str, str]] = load_catalogs()
EN: dict[str, str] = CATALOGS[DEFAULT_LANG]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_lang(code: str | None) -> str | None:
    """Map a locale/code string to one of our supported language codes, or None.

    Accepts things like 'fr', 'fr_FR', 'fr-FR.UTF-8', 'JA', 'de_DE' — only the
    leading two-letter primary subtag is considered.
    """
    if not code:
        return None
    primary = code.replace("_", "-").split("-", 1)[0].strip().lower()
    return primary if primary in CATALOGS else None


def parse_accept_language(header: str | None) -> str | None:
    """Pick the best supported language from an HTTP Accept-Language header.

    Honors q-weights ('fr;q=0.9, en;q=0.8'); returns None if nothing matches.
    """
    if not header:
        return None
    best: tuple[float, str] | None = None
    for part in header.split(","):
        token = part.strip()
        if not token:
            continue
        q = 1.0
        if ";" in token:
            token, _, params = token.partition(";")
            for p in params.split(";"):
                p = p.strip()
                if p.startswith("q="):
                    try:
                        q = float(p[2:])
                    except ValueError:
                        q = 0.0
        lang = normalize_lang(token.strip())
        if lang and (best is None or q > best[0]):
            best = (q, lang)
    return best[1] if best else None


def _os_lang() -> str | None:
    """Best-effort OS locale → supported language, or None."""
    # Respect the standard env vars first (set on Linux/macOS, sometimes Windows).
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        lang = normalize_lang(os.environ.get(var, "").split(":", 1)[0])
        if lang:
            return lang
    try:
        loc = locale.getlocale()[0]
    except (ValueError, TypeError):
        loc = None
    if not loc:
        try:  # getdefaultlocale is deprecated (3.11+) but still the only
            # reliable read of the Windows UI language without ctypes.
            loc = locale.getdefaultlocale()[0]  # type: ignore[attr-defined]
        except (ValueError, AttributeError):
            loc = None
    return normalize_lang(loc)


def detect_lang(
    accept_language: str | None = None,
    override: str | None = None,
    use_os: bool = True,
) -> str:
    """Resolve the active language.

    Priority: explicit `override` (CLI flag / saved web choice / ?lang=) →
    `HAP_LANG` env var → HTTP `accept_language` → OS locale → DEFAULT_LANG.
    Always returns a supported code.
    """
    return (
        normalize_lang(override)
        or normalize_lang(os.environ.get("HAP_LANG"))
        or parse_accept_language(accept_language)
        or (_os_lang() if use_os else None)
        or DEFAULT_LANG
    )


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    """Translate `key` into `lang` (default: detected), formatting with kwargs.

    Lookup order for the string: active language → English → the key itself.
    `str.format` is applied with kwargs; a malformed placeholder degrades to the
    unformatted string rather than raising.
    """
    active = lang or detect_lang()
    catalog = CATALOGS.get(active, EN)
    template = catalog.get(key) or EN.get(key) or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def catalog_for(lang: str) -> dict[str, str]:
    """Return the *complete* catalog for `lang`, with English filling any gaps.

    This is what the web UI embeds (as JSON) so the browser can translate every
    key client-side and switch languages with zero server round-trips.
    """
    merged = dict(EN)
    merged.update(CATALOGS.get(lang, {}))
    return merged


def all_catalogs() -> dict[str, dict[str, str]]:
    """Every language's complete (English-backfilled) catalog, for embedding the
    whole set so the web language switch is instant and offline."""
    return {code: catalog_for(code) for code in CATALOGS}


def language_options() -> list[dict[str, str]]:
    """[{code, name}] in canonical order — for building a language <select>."""
    return [{"code": code, "name": name} for code, name in LANGUAGES.items()]


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    if len(argv) >= 2:
        lang = normalize_lang(argv[0]) or DEFAULT_LANG
        key = argv[1]
        print(t(key, lang))
        return 0
    print(f"Detected language: {detect_lang()}")
    print("Supported:")
    for code, name in LANGUAGES.items():
        sample = t("web.sound.dsee_note", code)
        print(f"  {code}  {name:10s}  {sample[:60]}…")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
