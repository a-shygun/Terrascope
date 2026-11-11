"""Zone labels in the clock: the abbreviation when there is one, else the offset."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from terrascope.core.ui.layout import zone_label


def _at(tzinfo) -> datetime:
    return datetime(2026, 1, 15, 12, 0, tzinfo=tzinfo)


def test_iana_abbreviation_is_kept():
    assert zone_label(_at(ZoneInfo("Europe/Paris"))) == "CET"


def test_numeric_abbreviation_is_kept():
    assert zone_label(_at(ZoneInfo("America/Sao_Paulo"))) == "-03"


def test_long_localised_name_with_spaces_becomes_the_offset():
    moment = _at(timezone(timedelta(hours=-8), "Pacific Standard Time"))
    assert zone_label(moment) == "-0800"


def test_name_without_spaces_but_not_short_becomes_the_offset():
    # Windows names in Chinese or Japanese have no spaces; the old check
    # let them through and the clock overflowed its panel.
    moment = _at(timezone(timedelta(hours=8), "中国标准时间"))
    assert zone_label(moment) == "+0800"


def test_long_ascii_name_becomes_the_offset():
    moment = _at(timezone(timedelta(hours=-3), "Hora_padrao_do_Brasil"))
    assert zone_label(moment) == "-0300"


def test_short_ascii_name_is_kept_even_without_a_database_abbreviation():
    moment = _at(timezone(timedelta(hours=0), "UTC"))
    assert zone_label(moment) == "UTC"


def test_offset_fallback_keeps_minutes():
    moment = _at(timezone(timedelta(hours=3, minutes=30), "Iran Standard Time"))
    assert zone_label(moment) == "+0330"
