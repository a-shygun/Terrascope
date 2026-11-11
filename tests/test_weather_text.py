"""Weather panel text: gust units (forecast.py) and the radar age caption that
must fit the slider caption (weather/layer.py)."""

from __future__ import annotations

import time

import pytest

from terrascope.core import config, i18n
from terrascope.core.ui.constants import SLIDER_CAPTION_WIDTH
from terrascope.layers.weather.forecast import _precip_row, _wind_row
from terrascope.layers.weather.layer import WeatherLayer


@pytest.fixture
def language(monkeypatch):
    """Switch language and units for one test, then restore them."""
    saved_app = dict(config.CFG["app"])
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *args: (None, None))

    def use(lang: str, units: str = "auto") -> None:
        i18n.activate(lang)
        config.set_path("app.units", units, create=True)

    yield use
    config.CFG["app"].clear()
    config.CFG["app"].update(saved_app)
    i18n.activate("en")


def _text(pieces) -> str:
    return "".join(text for text, _color, _style in pieces)


# --- item 5: the gust figure follows the units shown beside it ----------------------

def test_metric_gust_row_keeps_english_text(language):
    language("en", "metric")
    row = _text(_wind_row({"wind": 10.0, "gust": 20.0}))
    assert row == "≈ 10 km/h  gust 20"


def test_imperial_gust_is_in_mph_like_the_wind(language):
    language("en", "imperial")
    row = _text(_wind_row({"wind": 10.0, "gust": 20.0}))
    assert row.startswith("≈ 6 mph")
    assert "gust 12" in row  # 20 km/h is about 12 mph, not a raw 20 next to mph
    assert "gust 20" not in row


def test_gust_row_fits_the_minimum_column(language):
    """The row is cut at 21 columns (forecast._fit): the unit must not be repeated."""
    language("en", "metric")
    assert len(_text(_wind_row({"wind": 10.0, "gust": 20.0}))) <= 21
    language("pt_BR", "imperial")
    assert len(_text(_wind_row({"wind": 45.0, "gust": 80.0}))) <= 21


# --- N3: the dry-day caption is translated like the rest of the forecast ----------

def test_dry_day_caption_is_translated(language):
    language("en")
    assert _text(_precip_row({"precip": 0.0, "pop": 10.0})) == "☂ dry  10%"
    language("pt_BR")
    row = _text(_precip_row({"precip": 0.0, "pop": 10.0}))
    assert row == "☂ sem chuva  10%"
    assert len(row) <= 21


# --- item 6: the radar age caption fits the slider caption -------------------------

def _age(seconds: int) -> str:
    return WeatherLayer._radar_age_caption(int(time.time()) - seconds)


def test_english_age_captions_are_unchanged(language):
    language("en")
    assert _age(5 * 60) == "5m AGO"
    assert _age(23 * 3600 + 59 * 60 + 30) == "23h59m AGO"
    assert _age(3 * 86400 + 60) == "3d AGO"


def test_portuguese_age_caption_fits_the_slider_caption(language):
    language("pt_BR")
    longest = _age(23 * 3600 + 59 * 60 + 30)
    assert longest == "há 23h59m"
    assert len(longest) <= SLIDER_CAPTION_WIDTH
    assert len(_age(3 * 86400 + 60)) <= SLIDER_CAPTION_WIDTH
