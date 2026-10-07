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

FORECAST_ROWS = 7  # date, conditions, range, chart, precipitation, wind, sun
VERTICAL_DAY_SEPARATOR_ROWS = 2  # divider and one blank row
FORECAST_SEPARATOR = " │ "
SPARK_BLOCKS = "▁▂▃▄▅▆▇█"
NO_DATA = [("—", None, "dim")]

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

def _temp_extremes(day: dict) -> list:
    """Compact daily low-to-high range, with colour showing each endpoint."""
    low, high = day.get("tmin"), day.get("tmax")
    if low is None or high is None:
        return [("N/A", None, "dim")]
    cold, hot = forecast_temp_color(low), forecast_temp_color(high)
    return [
        ("▼ ", cold, ""), (f"{low:.0f}°", cold, "bold"),
        ("  →  ", None, "dim"),
        ("▲ ", hot, ""), (f"{high:.0f}°", hot, "bold"),
    ]

def _temp_sparkline(hours: list, width: int) -> list:
    """Full-width hourly temperature curve, scaled between the day's low/high."""
    temps = [row[1] for row in hours if row[1] is not None]
    if not temps:
        return NO_DATA
    width = max(1, width)
    low, high = min(temps), max(temps)
    out = []
    for position in range(width):
        sample = position * (len(temps) - 1) / max(1, width - 1)
        start = int(sample)
        end = min(start + 1, len(temps) - 1)
        fraction = sample - start
        temperature = temps[start] * (1 - fraction) + temps[end] * fraction
        level = round((temperature - low) / (high - low) * (len(SPARK_BLOCKS) - 1)) if high > low else 3
        out.append((SPARK_BLOCKS[level], forecast_temp_color(temperature), ""))
    return out

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

def _day_rows(day: dict, today: bool, cell: int) -> list[list]:
    """Seven compact, scannable rows for one forecast day."""
    hours = [row for row in day.get("hours") or [] if isinstance(row, list) and len(row) >= 5]
    return [
        _day_header(day, today),
        _day_conditions(day),
        _temp_extremes(day),
        _temp_sparkline(hours, cell),
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
    available = max(count, width - gap * (count - 1))
    base, remainder = divmod(available, count)
    cells = [base + (index < remainder) for index in range(count)]
    columns = [_day_rows(day, index == 0, cells[index]) for index, day in enumerate(days)]
    lines = []
    for row in range(FORECAST_ROWS):
        line: list = []
        for index, column in enumerate(columns):
            if index:
                line.append((FORECAST_SEPARATOR, None, "dim"))
            line.extend(_fit(column[row], cells[index]))
        lines.append(line)
    return lines

def forecast_vertical_lines(
    days: list[dict], width: int, height: int, scroll: int = 0
) -> list[list]:
    """Stack compact day forecasts, then return the visible slice."""
    if not days or height <= 0:
        return []
    lines = []
    for index, day in enumerate(days):
        lines.extend(_day_rows(day, index == 0, width))
        if index < len(days) - 1:
            separator = [("─" * width, None, "dim")]
            lines.extend((separator, []))
    start = max(0, min(scroll, max(0, len(lines) - height)))
    return lines[start : start + height]

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
        ("READ   ", None, "dim"), ("▼ → ▲", forecast_temp_color(20), "bold"),
        (" daily low to high · chart shows the hourly temperature", None, "dim"),
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

def forecast_vertical_placeholder(width: int, height: int) -> list[list]:
    """Compact legend for the narrow forecast sidebar; keep every line readable."""
    sun = WEATHER_ICONS["clear"]
    partly = WEATHER_ICONS["partly"]
    cloud = WEATHER_ICONS["cloud"]
    fog = WEATHER_ICONS["fog"]
    rain = WEATHER_ICONS["rain"]
    snow = WEATHER_ICONS["snow"]
    storm = WEATHER_ICONS["storm"]
    lines = [
        [("CLICK A CITY NAME", None, "bold")],
        [("to show its forecast here.", None, "dim")],
        [],
        [("ICONS", None, "dim")],
        [(f"{sun[0]} clear", sun[1], "bold"), (" · ", None, "dim"), (f"{partly[0]} partly", partly[1], "bold")],
        [
            (f"{cloud[0]} cloud", cloud[1], "bold"), (" · ", None, "dim"),
            (f"{fog[0]} fog", fog[1], "bold"), (" · ", None, "dim"),
            (f"{rain[0]} rain", rain[1], "bold"),
        ],
        [(f"{snow[0]} snow", snow[1], "bold"), (" · ", None, "dim"), (f"{storm[0]} storm", storm[1], "bold")],
        [("TEMP ", None, "dim"), ("COLD ", None, "dim")]
        + [("██", forecast_temp_color(value), "") for value in range(-10, 31, 10)]
        + [(" HOT", None, "dim")],
        [("RANGE", None, "dim"), ("▼ low → ▲ high", forecast_temp_color(20), "bold")],
        [("CHART", None, "dim"), ("hourly temperature", forecast_temp_color(25), "")],
    ]
    return [_fit(line, width) for line in lines[:height]]
