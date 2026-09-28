from __future__ import annotations

import json
import urllib.error
import urllib.request

from around.core.colors import hex_to_rgb
from around.layers.cities.settings import CITY_CONFIG, FORECAST_DAYS_AHEAD, WEATHER_API_URL

WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Slight snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm, hail",
    99: "Thunderstorm, heavy hail",
}

# Number of discrete color pairs the temperature gradient is snapped to.
# Curses only has a limited color-pair budget, so nearby readings share a
# pair instead of every city minting its own.
_COLOR_STEPS = 20


class WeatherFetchError(Exception):
    pass


def describe_weather_code(code) -> str:
    try:
        return WEATHER_CODES.get(int(code), "Unknown")
    except (TypeError, ValueError):
        return "Unknown"


def temperature_to_color(
    temperature: float | None, cold_c: float, hot_c: float
) -> str | None:
    """Map a Celsius reading onto the cold -> hot gradient in CITY_CONFIG,
    scaled between cold_c and hot_c (typically the coldest and hottest
    readings currently known across all cities -- see
    WeatherStationCache.temperature_range), so a city's marker/label
    reflects how hot or cold it is *relative to the other cities*, not a
    fixed absolute threshold.

    Returns None when there is no reading yet, so callers can fall back to
    a neutral default color.
    """
    if temperature is None:
        return None
    span = hot_c - cold_c
    if span <= 0:
        # Only one distinct temperature known so far -- nothing to scale
        # against yet.
        fraction = 0.5
    else:
        fraction = (temperature - cold_c) / span
        fraction = max(0.0, min(1.0, fraction))
    fraction = round(fraction * _COLOR_STEPS) / _COLOR_STEPS
    cold_r, cold_g, cold_b = hex_to_rgb(CITY_CONFIG["temperature_cold_color"])
    hot_r, hot_g, hot_b = hex_to_rgb(CITY_CONFIG["temperature_hot_color"])
    red = round(cold_r + (hot_r - cold_r) * fraction)
    green = round(cold_g + (hot_g - cold_g) * fraction)
    blue = round(cold_b + (hot_b - cold_b) * fraction)
    return f"#{red:02x}{green:02x}{blue:02x}"


def fetch_weather_snapshot(latitude: float, longitude: float) -> dict:
    """Fetch Open-Meteo's current conditions plus a short daily forecast.

    Returns {"current": {...}, "daily": {...}}. "current" is the raw
    `current_weather` object (temperature, windspeed, winddirection,
    weathercode, time). "daily" is Open-Meteo's arrays-of-values daily
    block (time, weathercode, temperature_2m_max, temperature_2m_min),
    covering today plus the next FORECAST_DAYS_AHEAD days.
    """
    query = (
        f"{WEATHER_API_URL}?latitude={latitude:.4f}&longitude={longitude:.4f}"
        "&current_weather=true&timezone=auto"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min"
        f"&forecast_days={FORECAST_DAYS_AHEAD + 1}"
    )
    request = urllib.request.Request(
        query, headers={"User-Agent": "around/1.0", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise WeatherFetchError(f"Weather request failed: {error}") from error
    current = payload.get("current_weather")
    if not isinstance(current, dict):
        raise WeatherFetchError("Weather response missing current_weather")
    daily = payload.get("daily")
    return {"current": current, "daily": daily if isinstance(daily, dict) else {}}