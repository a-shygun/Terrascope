"""City selection helpers and rich forecast-panel formatting."""

from __future__ import annotations

import math
from datetime import date
from terrascope.layers.weather.city_weather import describe_weather_code, temperature_to_color
from terrascope.layers.weather.config import (
    CITY_CONFIG,
    CITY_LEVELS,
    FORECAST_COLD_C,
    FORECAST_HOT_C,
    FORECAST_MIN_COLUMN_WIDTH,
    FORECAST_TODAY_COLOR,
    FORECAST_WEEKEND_COLOR,
    WEATHER_ICONS,
    _CITY_TEXT,
)

def city_population_floor(zoom: float) -> int | None:
    """Smallest non-capital city population shown at this zoom (None = none yet)."""
    floor = None
    for min_zoom, population in CITY_LEVELS:
        if zoom >= min_zoom:
            floor = population
    return floor

def city_key(name: str, latitude: float, longitude: float) -> str:
    """Cache key of a city. Names alone are not unique (there are several
    Victorias), so the position is part of it."""
    return f"{name}|{latitude:.2f}|{longitude:.2f}"

def item_kind(item) -> str:
    """"quake", "radar" (a cloud / rain cell) or "city" for a selected item."""
    if isinstance(item, dict):
        if item.get("radar"):
            return "radar"
        if "magnitude" in item:
            return "quake"
    return "city"

# ---------------------------------------------------------------------------
# Weather icons and the forecast box (bottom row)
# ---------------------------------------------------------------------------
# A forecast line is a list of (text, "#rrggbb" or None, style) pieces, style
# being "", "bold" or "dim"; ui.draw_rich_box paints them.

FORECAST_ROWS = 10  # lines in one day column (the bottom panel has room for 10)
FORECAST_SEPARATOR = " │ "
SPARK_BLOCKS = "▁▂▃▄▅▆▇█"
NO_DATA = [("—", None, "dim")]

# Weather codes from mildest to roughest, to pick the best and worst hour of a day.
_SEVERITY_ORDER = (
    0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 80, 81, 65, 66, 67,
    71, 73, 85, 86, 77, 75, 82, 95, 96, 99,
)
_SEVERITY_INDEX = {code: rank for rank, code in enumerate(_SEVERITY_ORDER)}

# (limit, colour): the first step whose limit is above the value.
PRECIP_STEPS = ((0.1, "#6b7785"), (1.0, "#6cb4ee"), (5.0, "#3f8cff"), (15.0, "#6a5cff"), (math.inf, "#c77dff"))
WIND_STEPS = ((20, "#6bcb77"), (40, "#ffd93d"), (60, "#ff9f43"), (math.inf, "#ff4d4d"))
UV_STEPS = ((3, "#6bcb77"), (6, "#ffd93d"), (8, "#ff9f43"), (11, "#ff4d4d"), (math.inf, "#c77dff"))
SUNRISE_COLOR = "#ffb347"
SUNSET_COLOR = "#c77dff"

def weather_category(code) -> str:
    """Icon category of an Open-Meteo weather code."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "unknown"
    if code in (0, 1):
        return "clear"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "unknown"

def weather_icon(code) -> tuple[str, str]:
    """(glyph, colour) of a weather code."""
    return WEATHER_ICONS.get(weather_category(code)) or WEATHER_ICONS["unknown"]

def weather_severity(code) -> int:
    try:
        return _SEVERITY_INDEX.get(int(code), 0)
    except (TypeError, ValueError):
        return 0

def forecast_temp_color(temperature: float) -> str:
    return temperature_to_color(temperature, FORECAST_COLD_C, FORECAST_HOT_C) or CITY_CONFIG["color"]

def _step_color(value: float, steps) -> str:
    for limit, color in steps:
        if value < limit:
            return color
    return steps[-1][1]

def _fit(pieces: list, width: int) -> list:
    """Cut a line to `width` cells and pad it with spaces up to it."""
    out = []
    used = 0
    for text, color, style in pieces:
        if used >= width:
            break
        text = text[: width - used]
        out.append((text, color, style))
        used += len(text)
    if used < width:
        out.append((" " * (width - used), None, ""))
    return out

def _hour_buckets(count: int, width: int) -> list[tuple[int, int]]:
    """Split `count` hourly values into at most `width` runs of neighbours."""
    width = max(1, min(width, count))
    return [
        (index * count // width, max(index * count // width + 1, (index + 1) * count // width))
        for index in range(width)
    ]

def _day_header(day: dict, today: bool) -> list:
    shown = _CITY_TEXT["unknown_date"]
    weekend = False
    try:
        parsed = date.fromisoformat(str(day.get("date")))
        shown = parsed.strftime("%a %m-%d")
        weekend = parsed.weekday() >= 5
    except ValueError:
        pass
    if today:
        return [("TODAY ", FORECAST_TODAY_COLOR, "bold"), (shown, None, "bold")]
    return [(shown, FORECAST_WEEKEND_COLOR if weekend else None, "bold")]

def _day_conditions(day: dict) -> list:
    glyph, color = weather_icon(day.get("code"))
    return [(glyph + " ", color, "bold"), (describe_weather_code(day.get("code")), color, "")]

def _temp_extremes(day: dict, hours: list) -> list:
    """Lowest and highest temperature of the day and the hour each happens."""
    low, high = day.get("tmin"), day.get("tmax")
    if low is None or high is None:
        return [("N/A", None, "dim")]
    timed = [(row[1], row[0]) for row in hours if row[1] is not None]
    low_at = f" {min(timed, key=lambda item: (item[0], item[1]))[1]:02d}h" if timed else ""
    high_at = f" {max(timed, key=lambda item: (item[0], -item[1]))[1]:02d}h" if timed else ""
    cold, hot = forecast_temp_color(low), forecast_temp_color(high)
    return [
        ("▼", cold, ""), (f"{low:.0f}°", cold, "bold"), (low_at, None, "dim"),
        ("  ", None, ""),
        ("▲", hot, ""), (f"{high:.0f}°", hot, "bold"), (high_at, None, "dim"),
    ]

def _range_bar(day: dict, low: float, high: float, width: int) -> list:
    """The day's low-to-high as a coloured bar on the scale of every shown day,
    so the days line up and a warm day sits to the right of a cold one."""
    day_low, day_high = day.get("tmin"), day.get("tmax")
    if day_low is None or day_high is None or width < 1:
        return NO_DATA
    span = high - low
    half_cell = span / width / 2
    out = []
    for position in range(width):
        temperature = low + span * (position + 0.5) / width if span > 0 else day_low
        if day_low - half_cell <= temperature <= day_high + half_cell:
            out.append(("━", forecast_temp_color(temperature), "bold"))
        else:
            out.append(("─", None, "dim"))
    return out

def _temp_sparkline(hours: list, width: int) -> list:
    """The day hour by hour as ▁▂▃▄▅▆▇█, scaled between its own low and high."""
    temps = [row[1] for row in hours]
    known = [value for value in temps if value is not None]
    if not known:
        return NO_DATA
    low, high = min(known), max(known)
    out = []
    for start, end in _hour_buckets(len(temps), width):
        values = [value for value in temps[start:end] if value is not None]
        if not values:
            out.append((" ", None, ""))
            continue
        mean = sum(values) / len(values)
        level = round((mean - low) / (high - low) * (len(SPARK_BLOCKS) - 1)) if high > low else 3
        out.append((SPARK_BLOCKS[level], forecast_temp_color(mean), ""))
    return out

def _weather_strip(hours: list, width: int) -> list:
    """The day hour by hour as coloured blocks, in the colour of that hour's
    weather icon (the roughest weather wins where hours are merged)."""
    codes = [row[2] for row in hours]
    if not any(code is not None for code in codes):
        return NO_DATA
    out = []
    for start, end in _hour_buckets(len(codes), width):
        bucket = [code for code in codes[start:end] if code is not None]
        if not bucket:
            out.append((" ", None, ""))
            continue
        out.append(("█", weather_icon(max(bucket, key=weather_severity))[1], ""))
    return out

def _best_worst(hours: list) -> list:
    """The mildest and the roughest hour of the day (by weather code)."""
    rated = [(weather_severity(row[2]), row[0], row[2]) for row in hours if row[2] is not None]
    if not rated:
        return NO_DATA
    best = min(rated, key=lambda item: (item[0], item[1]))
    worst = max(rated, key=lambda item: (item[0], -item[1]))
    if best[0] == worst[0]:
        glyph, color = weather_icon(best[2])
        return [("steady ", None, "dim"), (glyph, color, "bold"), (" all day", None, "dim")]
    best_glyph, best_color = weather_icon(best[2])
    worst_glyph, worst_color = weather_icon(worst[2])
    return [
        ("best ", None, "dim"), (best_glyph, best_color, "bold"), (f"{best[1]:02d}h", None, ""),
        ("  ", None, ""),
        ("worst ", None, "dim"), (worst_glyph, worst_color, "bold"), (f"{worst[1]:02d}h", None, ""),
    ]

def _precip_row(day: dict) -> list:
    amount, chance = day.get("precip"), day.get("pop")
    if amount is None:
        return [("☂ ", None, "dim"), ("N/A", None, "dim")]
    color = _step_color(amount, PRECIP_STEPS)
    if amount < PRECIP_STEPS[0][0]:
        pieces = [("☂ ", color, ""), ("dry", color, "dim")]
    else:
        pieces = [("☂ ", color, ""), (f"{amount:.1f} mm", color, "bold")]
    if chance is not None:
        pieces.append((f"  {chance:.0f}%", color, "dim"))
    return pieces

def _wind_row(day: dict) -> list:
    wind, gust = day.get("wind"), day.get("gust")
    if wind is None:
        return [("≈ ", None, "dim"), ("N/A", None, "dim")]
    color = _step_color(gust if gust is not None else wind, WIND_STEPS)
    pieces = [("≈ ", color, ""), (f"{wind:.0f} km/h", color, "bold")]
    if gust is not None:
        pieces.append((f"  gust {gust:.0f}", color, "dim"))
    return pieces

def _sun_row(day: dict) -> list:
    pieces = []
    sunrise = str(day.get("sunrise") or "")[11:16]
    sunset = str(day.get("sunset") or "")[11:16]
    if sunrise:
        pieces += [("↑", SUNRISE_COLOR, ""), (sunrise, None, "")]
    if sunset:
        pieces += [(" " if pieces else "", None, ""), ("↓", SUNSET_COLOR, ""), (sunset, None, "")]
    uv = day.get("uv")
    if uv is not None:
        pieces += [("  UV ", None, "dim"), (f"{uv:.0f}", _step_color(uv, UV_STEPS), "bold")]
    return pieces or NO_DATA

def _day_rows(day: dict, today: bool, cell: int, low: float, high: float) -> list[list]:
    """The FORECAST_ROWS lines of one day column, most important first."""
    hours = [row for row in day.get("hours") or [] if isinstance(row, list) and len(row) >= 5]
    curve_width = min(24, cell)
    return [
        _day_header(day, today),
        _day_conditions(day),
        _temp_extremes(day, hours),
        _range_bar(day, low, high, cell),
        _temp_sparkline(hours, curve_width),
        _weather_strip(hours, curve_width),
        _best_worst(hours),
        _precip_row(day),
        _wind_row(day),
        _sun_row(day),
    ]

def forecast_lines(days: list[dict], width: int) -> list[list]:
    """The forecast box: one column per day (as many as fit `width`), the same
    rows in every column, thin separators between them."""
    gap = len(FORECAST_SEPARATOR)
    count = max(1, min(len(days), (width + gap) // (FORECAST_MIN_COLUMN_WIDTH + gap)))
    days = days[:count]
    cell = max(1, (width - gap * (count - 1)) // count)
    known = [value for day in days for value in (day.get("tmin"), day.get("tmax")) if value is not None]
    low, high = (min(known), max(known)) if known else (0.0, 0.0)
    columns = [_day_rows(day, index == 0, cell, low, high) for index, day in enumerate(days)]
    lines = []
    for row in range(FORECAST_ROWS):
        line: list = []
        for index, column in enumerate(columns):
            if index:
                line.append((FORECAST_SEPARATOR, None, "dim"))
            line.extend(_fit(column[row], cell))
        lines.append(line)
    return lines

def forecast_placeholder() -> list[list]:
    """What the forecast box shows while no city is selected: how to use it and
    a key to the icons, colours and glyphs."""
    icons: list = [("ICONS  ", None, "dim")]
    for name, label in (
        ("clear", "clear"), ("partly", "partly cloudy"), ("cloud", "cloudy"), ("fog", "fog"),
        ("drizzle", "drizzle"), ("rain", "rain"), ("snow", "snow"), ("storm", "thunder"),
    ):
        glyph, color = WEATHER_ICONS.get(name) or WEATHER_ICONS["unknown"]
        icons += [(glyph + " ", color, "bold"), (label + "   ", None, "")]
    cold, hot = int(FORECAST_COLD_C), int(FORECAST_HOT_C)
    scale: list = [("TEMP   ", None, "dim"), (f"{cold}° ", None, "dim")]
    for degrees in range(cold, hot + 1, 5):
        scale.append(("██", forecast_temp_color(degrees), ""))
    scale.append((f" {hot}°C", None, "dim"))
    key: list = [
        ("READ   ", None, "dim"),
        ("━━", forecast_temp_color(15), "bold"), (" the day's low-high against the other days   ", None, "dim"),
        ("▁▃▅█", forecast_temp_color(25), ""), (" temperature hour by hour   ", None, "dim"),
        ("██", weather_icon(63)[1], ""), (" weather hour by hour", None, "dim"),
    ]
    return [
        [("CLICK A CITY NAME", None, "bold")],
        [("its icon and temperature appear on the map, its forecast fills this box.", None, "dim")],
        [],
        icons,
        scale,
        [],
        key,
    ]

