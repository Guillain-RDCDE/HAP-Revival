"""The catalogues now live in tools/locales/*.json; i18n.py only loads them.

What can go wrong with files rather than dicts: a missing one, a malformed one,
a key present in one language and not the others, and the loader's own
location logic (next to i18n.py in source, in the bundle when frozen)."""

import json

import pytest

import i18n


def test_every_language_has_a_complete_catalogue():
    en = set(i18n.EN)
    for code, cat in i18n.CATALOGS.items():
        assert set(cat) == en, f"{code}: {set(cat) ^ en}"
    assert set(i18n.CATALOGS) == set(i18n.LANGUAGES)


def test_catalogue_files_match_what_is_loaded():
    for code in i18n.LANGUAGES:
        on_disk = json.loads((i18n.LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))
        assert on_disk == i18n.CATALOGS[code]


def test_placeholders_agree_across_languages():
    """A translation that drops or invents a {placeholder} would format wrongly."""
    import re

    holes = re.compile(r"\{(\w+)\}")
    for key, en_value in i18n.EN.items():
        expected = set(holes.findall(en_value))
        for code, cat in i18n.CATALOGS.items():
            assert set(holes.findall(cat[key])) == expected, f"{code}:{key}"


def test_load_catalog_handles_missing_and_malformed_files(tmp_path):
    assert i18n.load_catalog("xx", tmp_path) == {}
    (tmp_path / "xx.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="expected an object"):
        i18n.load_catalog("xx", tmp_path)
    (tmp_path / "xx.json").write_text('{"a.b": 1}', encoding="utf-8")
    assert i18n.load_catalog("xx", tmp_path) == {"a.b": "1"}, "values are coerced to text"


def test_load_catalogs_survives_a_broken_file(tmp_path, capsys):
    for code in i18n.LANGUAGES:
        (tmp_path / f"{code}.json").write_text('{"k": "v"}', encoding="utf-8")
    (tmp_path / "fr.json").write_text("[]", encoding="utf-8")
    catalogs = i18n.load_catalogs(tmp_path)
    assert set(catalogs) == set(i18n.LANGUAGES)
    assert catalogs["fr"] == {} and catalogs["en"] == {"k": "v"}
    err = capsys.readouterr().err
    assert "ignoring" in err and "fr.json" in err and "expected an object" in err


def test_locales_dir_is_next_to_the_module():
    assert i18n.LOCALES_DIR.name == "locales"
    assert (i18n.LOCALES_DIR / "en.json").is_file()


def test_gui_strings_are_translated_everywhere():
    keys = [k for k in i18n.EN if k.startswith("gui.log.") or k.startswith("gui.msg.")]
    assert len(keys) > 30
    for code, cat in i18n.CATALOGS.items():
        if code == "en":
            continue
        untranslated = [k for k in keys if cat[k] == i18n.EN[k] and len(i18n.EN[k]) > 12]
        assert untranslated == [], f"{code} still shows English for {untranslated}"
