"""Tests for the i18n layer: detection precedence, graceful fallback, safe
formatting, and catalog completeness across all six languages."""

import pytest

import i18n


# ---------- normalize_lang ----------


@pytest.mark.parametrize("code,expected", [
    ("fr", "fr"), ("FR", "fr"), ("fr_FR", "fr"), ("fr-FR.UTF-8", "fr"),
    ("ja", "ja"), ("de_DE", "de"), ("en-US", "en"),
    ("xx", None), ("", None), (None, None), ("zz-ZZ", None),
])
def test_normalize_lang(code, expected):
    assert i18n.normalize_lang(code) == expected


# ---------- parse_accept_language ----------


@pytest.mark.parametrize("header,expected", [
    ("fr-FR,fr;q=0.9,en;q=0.8", "fr"),
    ("de-DE,de;q=0.9,en;q=0.5", "de"),
    ("en;q=0.8, ja;q=0.9", "ja"),           # q-weight wins over order
    ("xx,zz", None),
    ("", None),
    (None, None),
    ("it", "it"),
])
def test_parse_accept_language(header, expected):
    assert i18n.parse_accept_language(header) == expected


# ---------- detect_lang precedence ----------


def test_detect_override_beats_everything(monkeypatch):
    monkeypatch.setenv("HAP_LANG", "de")
    assert i18n.detect_lang(accept_language="fr", override="it") == "it"


def test_detect_env_beats_accept(monkeypatch):
    monkeypatch.setenv("HAP_LANG", "de")
    assert i18n.detect_lang(accept_language="fr") == "de"


def test_detect_accept_beats_os(monkeypatch):
    monkeypatch.delenv("HAP_LANG", raising=False)
    assert i18n.detect_lang(accept_language="ja", use_os=False) == "ja"


def test_detect_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("HAP_LANG", raising=False)
    assert i18n.detect_lang(accept_language="xx", use_os=False) == i18n.DEFAULT_LANG


def test_detect_invalid_override_ignored(monkeypatch):
    monkeypatch.delenv("HAP_LANG", raising=False)
    assert i18n.detect_lang(accept_language="fr", override="zz") == "fr"


# ---------- t() ----------


def test_t_returns_translation():
    assert i18n.t("web.connecting", "fr") == "connexion…"
    assert i18n.t("web.connecting", "ja") == "接続中…"


def test_t_unknown_key_returns_key():
    assert i18n.t("does.not.exist", "fr") == "does.not.exist"


def test_t_formats_named_placeholders():
    assert i18n.t("web.minutes", "fr", n=30) == "30 min"
    msg = i18n.t("web.fav.nonhdd", "en", src="spotify")
    assert "spotify" in msg and "{src}" not in msg


def test_t_missing_param_does_not_raise():
    # A template with {src} called without it degrades to the raw template,
    # never an exception.
    out = i18n.t("web.fav.nonhdd", "en")
    assert isinstance(out, str)


def test_t_falls_back_to_english_for_untranslated_key(monkeypatch):
    # Inject a key that exists only in EN; every other language must surface it.
    monkeypatch.setitem(i18n.EN, "test.only_en", "ENGLISH ONLY")
    assert i18n.t("test.only_en", "fr") == "ENGLISH ONLY"
    assert i18n.t("test.only_en", "ja") == "ENGLISH ONLY"


# ---------- catalogs ----------


def test_six_languages():
    assert set(i18n.CATALOGS) == {"en", "fr", "ja", "de", "es", "it"}
    assert i18n.DEFAULT_LANG == "en"


def test_catalog_for_backfills_english():
    for code in i18n.CATALOGS:
        merged = i18n.catalog_for(code)
        # Every EN key is present after backfill (no holes for the web UI to hit).
        assert set(merged) >= set(i18n.EN)


def test_all_catalogs_complete():
    every = i18n.all_catalogs()
    assert set(every) == set(i18n.CATALOGS)
    for code, cat in every.items():
        assert len(cat) == len(i18n.EN), f"{code} missing keys after backfill"


def test_language_options_shape():
    opts = i18n.language_options()
    codes = [o["code"] for o in opts]
    assert codes[0] == "en"                       # canonical order, EN first
    assert set(codes) == set(i18n.CATALOGS)
    assert all(o["name"] for o in opts)           # every language has a display name


def test_no_empty_braces_in_any_template():
    # An accidental bare "{}" would format-explode; catch it for every value.
    for code, cat in i18n.CATALOGS.items():
        for key, val in cat.items():
            assert "{}" not in val, f"{code}:{key} has empty braces"


def test_every_value_is_nonempty_string():
    for code, cat in i18n.CATALOGS.items():
        for key, val in cat.items():
            assert isinstance(val, str) and val, f"{code}:{key} empty"
