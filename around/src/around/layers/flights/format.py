from __future__ import annotations

import math

from around.layers.flights.settings import ARROW_GLYPHS, UNKNOWN_HEADING_GLYPH


def finite_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def heading_to_arrow(true_track) -> str:
    heading = finite_float(true_track)
    if heading is None:
        return UNKNOWN_HEADING_GLYPH
    heading = heading % 360.0
    index = int((heading + 22.5) // 45) % 8
    return ARROW_GLYPHS[index]


def format_altitude(value) -> str:
    meters = finite_float(value)
    if meters is None:
        return "N/A"
    feet = meters * 3.28084
    return f"{feet:,.0f} ft"


def format_speed(value) -> str:
    meters_per_second = finite_float(value)
    if meters_per_second is None:
        return "N/A"
    knots = meters_per_second * 1.943844
    return f"{knots:,.0f} kt"


def format_vertical_rate(value) -> str:
    meters_per_second = finite_float(value)
    if meters_per_second is None:
        return "N/A"
    feet_per_minute = meters_per_second * 196.850394
    return f"{feet_per_minute:+,.0f} ft/min"


def format_heading(value) -> str:
    heading = finite_float(value)
    if heading is None:
        return "N/A"
    return f"{heading:.0f}°"


def format_ground(value) -> str:
    if value is True:
        return "YES"
    if value is False:
        return "NO"
    return "N/A"


def format_position_source(value) -> str:
    sources = {0: "ADS-B", 1: "ASTERIX", 2: "MLAT", 3: "FLARM"}
    try:
        source = int(value)
    except (TypeError, ValueError):
        return "N/A"
    return sources.get(source, str(source))