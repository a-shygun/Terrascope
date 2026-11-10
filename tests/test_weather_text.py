"""Weather panel text: the gust figure follows the units shown beside it (forecast.py)."""

from __future__ import annotations

import pytest

from terrascope.core import config, i18n
from terrascope.layers.weather.forecast import _wind_row


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
