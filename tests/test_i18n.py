"""Language resolution, translation lookup and regional formats (core/i18n.py)."""

from __future__ import annotations

import gettext
from datetime import date, datetime

import pytest

from terrascope.core import config, i18n


@pytest.fixture(autouse=True)
def restore_state(monkeypatch):
    """Each test starts from English and gets its own copy of the app settings."""
    saved = {"language": i18n._state["language"], "catalog": i18n._state["catalog"],
             "activated": i18n._state["activated"]}
    saved_app = dict(config.CFG["app"])
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(i18n, "_windows_ui_language", lambda: None)
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *args: (None, None))
    yield
    i18n._state.update(saved)
    config.CFG["app"].clear()
    config.CFG["app"].update(saved_app)


def _set_app(key: str, value) -> None:
    config.set_path(f"app.{key}", value, create=True)


# --- names and matching ------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("pt_BR", "pt_BR"),
    ("pt-BR", "pt_BR"),
    ("pt_BR.UTF-8", "pt_BR"),
    ("pt_BR@euro", "pt_BR"),
    ("pt_BR:en", "pt_BR"),
    ("PT", "pt"),
    ("C", None),
    ("POSIX", None),
    ("auto", None),
    ("", None),
    (None, None),
])
def test_normalize(raw, expected):
    assert i18n._normalize(raw) == expected


def test_available_languages_always_has_english():
    assert "en" in i18n.available_languages()
    assert "pt_BR" in i18n.available_languages()


def test_unknown_language_falls_back_to_english():
    assert i18n.activate("fr") == "en"
    assert i18n.is_supported("fr") is False


def test_base_language_match_pt_pt_uses_pt_br():
    assert i18n.activate("pt_PT") == "pt_BR"
    assert i18n.is_supported("pt-PT")


# --- resolution order ----------------------------------------------------------------

def test_explicit_request_wins_over_config_and_environment(monkeypatch):
    _set_app("language", "en")
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    assert i18n.activate("pt_BR") == "pt_BR"


def test_config_wins_over_environment(monkeypatch):
    _set_app("language", "pt_BR")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.activate(None) == "pt_BR"


def test_auto_config_defers_to_environment(monkeypatch):
    _set_app("language", "auto")
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    assert i18n.activate(None) == "pt_BR"


def test_language_variables_order(monkeypatch):
    _set_app("language", "auto")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_MESSAGES", "pt_BR.UTF-8")
    assert i18n.activate(None) == "pt_BR"  # LC_MESSAGES comes before LANG
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert i18n.activate(None) == "en"  # LC_ALL comes before LC_MESSAGES


def test_windows_ui_language_is_the_last_resort(monkeypatch):
    _set_app("language", "auto")
    monkeypatch.setattr(i18n, "_windows_ui_language", lambda: "pt-BR")
    assert i18n.activate(None) == "pt_BR"


def test_language_list_is_read_item_by_item(monkeypatch):
    """LANGUAGE may list several languages: the first one with a catalogue wins."""
    _set_app("language", "auto")
    monkeypatch.setenv("LANGUAGE", "de:pt_BR:en")
    assert i18n.activate(None) == "pt_BR"


def test_variable_without_a_catalogue_falls_through_to_the_next(monkeypatch):
    """LC_ALL=fr_FR has no catalogue: LANG=pt_BR is used instead of English."""
    _set_app("language", "auto")
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    assert i18n.activate(None) == "pt_BR"


def test_no_catalogue_in_the_environment_falls_through_to_windows(monkeypatch):
    """LANG=de_DE has no catalogue here, so the Windows interface language decides."""
    _set_app("language", "auto")
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setattr(i18n, "_windows_ui_language", lambda: "pt-BR")
    assert i18n.activate(None) == "pt_BR"


def test_english_when_nothing_is_set():
    _set_app("language", "auto")
    assert i18n.activate(None) == "en"


# --- lookup ---------------------------------------------------------------------------

def test_translation_in_pt_and_english_fallback():
    i18n.activate("pt_BR")
    assert i18n._("Show this help and exit.") == "Mostra esta ajuda e encerra."
    assert i18n._("A message nobody translated") == "A message nobody translated"


def test_empty_string_is_not_the_catalogue_header():
    i18n.activate("pt_BR")
    assert i18n._("") == ""


def test_english_is_unchanged():
    i18n.activate("en")
    assert i18n._("Show this help and exit.") == "Show this help and exit."
    assert i18n.language() == "en"


def test_plural_forms():
    i18n.activate("pt_BR")
    assert i18n.ngettext("PLANE", "PLANES", 1) == "AVIÃO"
    assert i18n.ngettext("PLANE", "PLANES", 2) == "AVIÕES"
    i18n.activate("en")
    assert i18n.ngettext("PLANE", "PLANES", 1) == "PLANE"
    assert i18n.ngettext("PLANE", "PLANES", 0) == "PLANES"


def test_translation_of_another_domain_falls_back_to_null(tmp_path):
    catalog = i18n.translation("terrascope_br", tmp_path)
    assert isinstance(catalog, gettext.NullTranslations)
    assert catalog.gettext("Hello") == "Hello"


def test_translation_of_the_app_domain_is_the_active_language():
    i18n.activate("pt_BR")
    catalog = i18n.translation("terrascope", i18n.LOCALE_DIR)
    assert catalog.gettext("OFF") == "DESLIGADO"


def test_yaml_texts_are_all_in_the_catalogue_list():
    """Every tab label / blurb and timezone label in default.yaml must be listed in
    i18n.YAML_TEXTS, otherwise pybabel extract does not see it."""
    listed = set(i18n.YAML_TEXTS)
    for item in config.CFG["tabs"]["items"]:
        assert item["label"] in listed
        if item.get("blurb"):
            assert item["blurb"] in listed
    for label, _zone in config.CFG["ui"]["timezones"]:
        assert label in listed


# --- regional formats -------------------------------------------------------------------

def test_english_formats_keep_the_previous_output():
    i18n.activate("en")
    assert i18n.format_number(12.5, 1) == "12.5"
    assert i18n.format_temperature(12.4) == "12°C"
    assert i18n.format_temperature(12.4, 1, unit=False) == "12.4°"
    assert i18n.format_speed(12.3) == "12 km/h"
    assert i18n.format_integer(1234567) == "1,234,567"
    assert i18n.format_distance(1000) == "1,000 km"
    assert i18n.format_distance(12) == "12 km"
    assert i18n.format_distance(0.3) == "300 m"
    assert i18n.format_date(date(2026, 11, 10)) == "2026-11-10"
    assert i18n.format_month_day(date(2026, 11, 10)) == "11-10"
    assert i18n.format_clock(datetime(2026, 11, 10, 15, 4, 5)) == "15:04:05"


def test_portuguese_formats():
    i18n.activate("pt_BR")
    assert i18n.format_number(12.5, 1) == "12,5"
    assert i18n.format_temperature(12.4) == "12°C"
    assert i18n.format_speed(12.3) == "12 km/h"
    assert i18n.format_integer(1234567) == "1.234.567"
    assert i18n.format_distance(1000) == "1.000 km"
    assert i18n.format_date(date(2026, 11, 10)) == "10/11/2026"
    assert i18n.format_month_day(date(2026, 11, 10)) == "10/11"
    assert i18n.format_clock(datetime(2026, 11, 10, 15, 4, 5)) == "15:04:05"


def test_imperial_units_override_the_language(monkeypatch):
    i18n.activate("pt_BR")
    _set_app("units", "imperial")
    assert i18n.format_temperature(0) == "32°F"
    assert i18n.format_temperature(100, unit=False) == "212°"
    assert i18n.format_speed(100) == "62 mph"
    assert i18n.format_distance(1.6094) == "1 mi"  # 1 mile, just over the rounding edge
    assert i18n.format_distance(1000) == "621 mi"
    assert i18n.format_distance(3000) == "1.864 mi"  # thousands grouping in pt


def test_metric_units_override_english_imperial_default():
    i18n.activate("en")
    _set_app("units", "metric")
    assert i18n.format_temperature(0) == "0°C"


def test_twelve_hour_clock_override():
    i18n.activate("pt_BR")
    _set_app("time_format", "12h")
    moment = datetime(2026, 11, 10, 15, 4, 5)
    assert i18n.format_clock(moment) == "03:04:05 PM"
    assert i18n.format_clock(moment, seconds=False) == "03:04 PM"
    _set_app("time_format", "24h")
    assert i18n.format_clock(moment) == "15:04:05"


def test_invalid_override_values_are_ignored():
    i18n.activate("en")
    _set_app("units", "furlongs")
    _set_app("time_format", "24 hours")
    assert i18n.units() == "metric"
    assert i18n.time_format() == "24h"
