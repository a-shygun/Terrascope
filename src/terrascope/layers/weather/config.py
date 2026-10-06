"""Shared settings and display text for the weather layer."""

from __future__ import annotations

import os
from terrascope.core.config import CACHE_DIR, CFG
from terrascope.core.ui import hex_to_rgb

# ---------------------------------------------------------------------------
# Settings. From default.yaml (layers: weather:), with a cities: and an
# earthquakes: section. Everything else is hardcoded here.
# ---------------------------------------------------------------------------

WEATHER_CONFIG = CFG["layers"]["weather"]

CITY_CONFIG = WEATHER_CONFIG["cities"]

CITY_CAPITAL_ZOOM = float(CITY_CONFIG["capital_zoom"])  # capitals appear at this zoom or higher
# Cities come from the Natural Earth populated-places file (the same one the
# basemap uses), not a hardcoded list. Non-capitals appear once the zoom reaches
# a row of this table and are at least that big: (min zoom, min population).
CITY_LEVELS = tuple((float(zoom), int(population)) for zoom, population in CITY_CONFIG["city_levels"])
CAPITAL_MIN_POPULATION = int(CITY_CONFIG["capital_min_population"])  # below CAPITAL_ALL_ZOOM only capitals this big are labelled
CAPITAL_ALL_ZOOM = float(CITY_CONFIG["capital_all_zoom"])  # from this zoom every capital is labelled
MAX_WEATHER_CITIES = int(CITY_CONFIG["max_labels"])  # most cities labelled (and weather-fetched) at once
CITY_LABEL_PADDING = int(CITY_CONFIG["label_padding"])  # blank columns required between two city labels on a row
PLACES_RETRY_SECONDS = CITY_CONFIG["places_retry_seconds"]  # wait this long after a failed city load
PLACES_LOADING_TEXT = "loading cities..."
PLACES_UNAVAILABLE_TEXT = "cities unavailable"
FORECAST_DAYS_AHEAD = int(CITY_CONFIG["forecast_days_ahead"])  # days after today in the forecast box (today is always the first column)
FORECAST_MIN_COLUMN_WIDTH = int(CITY_CONFIG["forecast_min_column_width"])  # a day column is dropped rather than made narrower than this
# The forecast box colours temperatures on this fixed scale (cold colour at the
# first, hot colour at the second), so a cold day looks cold whatever the other
# cities are doing.
FORECAST_COLD_C = float(CITY_CONFIG["forecast_cold_c"])
FORECAST_HOT_C = float(CITY_CONFIG["forecast_hot_c"])
FORECAST_TODAY_COLOR = CITY_CONFIG["forecast_today_color"]
FORECAST_WEEKEND_COLOR = CITY_CONFIG["forecast_weekend_color"]
# Conditions icon and colour per weather category (see weather_category()).
WEATHER_ICONS = {str(name): (str(glyph), str(color)) for name, (glyph, color) in CITY_CONFIG["icons"].items()}
MARKER_PREFIX = str(CITY_CONFIG["marker_prefix"])  # drawn before each city name

# Open-Meteo needs no API key. Weather is fetched on demand for whichever
# cities are visible, not pre-fetched for the whole list.
WEATHER_API_URL = CITY_CONFIG["api_url"]
WEATHER_REFRESH_INTERVAL_SECONDS = CITY_CONFIG["weather_refresh_interval_seconds"]
# A city whose last fetch failed is retried much sooner than a healthy one.
WEATHER_RETRY_INTERVAL_SECONDS = CITY_CONFIG["retry_interval_seconds"]
# Readings are persisted here so a failure (or restart) falls back to the
# last known data instead of showing nothing.
WEATHER_CACHE_FILE = CACHE_DIR / "weather_cache.json"  # inside the cache dir
WEATHER_SCHEMA = 3  # refetch old entries after migrating to Open-Meteo's current response fields
MAX_CONCURRENT_WEATHER_REQUESTS = CITY_CONFIG["max_concurrent_requests"]
WEATHER_TIMEOUT_SECONDS = CITY_CONFIG["request_timeout_seconds"]
WEATHER_ERROR_MAX_CHARS = 24  # a fetch error shown in the info box is cut to this
# Number of discrete colour pairs the temperature gradient is snapped to.
# Curses has a limited colour-pair budget, so nearby readings share a pair.
_COLOR_STEPS = int(CITY_CONFIG["color_steps"])

# ---------------------------------------------------------------------------
# Radar / cloud overlay settings (LibreWXR), from default.yaml (layers: weather: radar:).
# ---------------------------------------------------------------------------

# Everything below comes from default.yaml (layers: weather: radar:).
RADAR_CONFIG = WEATHER_CONFIG["radar"]
RADAR_ENABLED = bool(RADAR_CONFIG["enabled"])
RADAR_MODE = RADAR_CONFIG["mode"]  # "radar" | "satellite"
# Public LibreWXR instance (the one linecast defaults to). Point this at your
# own instance with terrascope_LIBREWXR_URL=http://localhost:8080
LIBREWXR_URL = os.environ.get("terrascope_LIBREWXR_URL", RADAR_CONFIG["url"]).rstrip("/")

CATALOG_REFRESH_SECONDS = RADAR_CONFIG["catalog_refresh_seconds"]  # LibreWXR publishes a new frame every ~10 min
CATALOG_RETRY_SECONDS = RADAR_CONFIG["catalog_retry_seconds"]  # retry sooner after a failure
REQUEST_TIMEOUT_SECONDS = RADAR_CONFIG["request_timeout_seconds"]
MAX_CONCURRENT_TILE_REQUESTS = RADAR_CONFIG["max_concurrent_tile_requests"]

PAST_FRAMES = RADAR_CONFIG["past_frames"]  # most observed frames kept (10 min apart)
HISTORY_MINUTES = float(RADAR_CONFIG["history_minutes"])  # drop observed frames older than this (0 = keep all the server offers)
RADAR_OPACITY = float(RADAR_CONFIG["opacity"])  # 1 = full palette colours, lower = fainter
_RADAR_BLEND_RGB = hex_to_rgb(RADAR_CONFIG["blend_color"])  # what the colours fade towards
NOWCAST_FRAMES = RADAR_CONFIG["nowcast_frames"]  # forecast frames to animate (10 min apart, up to 60 min)
SATELLITE_FRAMES = RADAR_CONFIG["satellite_frames"]  # hourly cloud frames

# The whole world is fetched as one Web-Mercator raster of 2^Z x 2^Z tiles.
# Z=2 with 512px tiles = 16 requests per frame and a 2048px raster (~0.18 deg
# per pixel). Raise Z for finer detail at 4x the requests per step.
WORLD_ZOOM = RADAR_CONFIG["world_zoom"]
TILE_SIZE = RADAR_CONFIG["tile_size"]

# Raw (grayscale, color=255) tiles are mapped to 0..1 intensity between these
# 8-bit values, then through the palette below.
INTENSITY_MIN = RADAR_CONFIG["intensity_min"]
INTENSITY_MAX = RADAR_CONFIG["intensity_max"]

FRAME_SECONDS = RADAR_CONFIG["frame_seconds"]  # time each animation frame is shown
FRAME_HOLD_LAST_SECONDS = RADAR_CONFIG["frame_hold_last_seconds"]  # pause on the newest frame before looping

# Every terminal half-cell is averaged from SUPERSAMPLE x SUPERSAMPLE bilinear
# samples of the radar raster, so zoomed-out views are area-averaged instead of
# aliased (no vertical banding) and zoomed-in views are smooth, not blocky.
SUPERSAMPLE = max(1, int(RADAR_CONFIG["supersample"]))
# false = show the newest observed frame and hold still (move with the slider);
# true = keep looping through all frames until the slider is touched.
ANIMATE = bool(RADAR_CONFIG["animate"])

# Half-block rendering: ▀ foreground paints a cell's top-half reading,
# background paints its bottom half, so one terminal cell shows two
# vertically-stacked samples instead of one flat colour (see radar_markers).
# ▄ is used for a cell with only a bottom-half reading, so the empty top
# half falls through to the map's own water/land colour instead of a hard
# edge. This supersedes layers.weather.radar.cell_glyph in default.yaml,
# which is no longer read.
HALF_BLOCK_UPPER = "\u2580"  # ▀
HALF_BLOCK_LOWER = "\u2584"  # ▄
# Number of intensity levels (= colours). A half-block cell needs one curses colour
# pair per (top, bottom) combination, i.e. up to steps^2 pairs, and curses only has
# ~255 pairs for the whole screen. Keep this small (6-10) or colours get mixed up.
_RADAR_COLOR_STEPS = int(RADAR_CONFIG["color_steps"])

# blue -> purple -> pink -> orange -> yellow, like the reference screenshot
_PALETTE_STOPS = [(float(at), str(color)) for at, color in RADAR_CONFIG["palette_stops"]]
# Satellite clouds: dark grey -> white.
_CLOUD_STOPS = [(float(at), str(color)) for at, color in RADAR_CONFIG["cloud_stops"]]

RADAR_LOADING_TEXT = "loading radar..."
RADAR_UNAVAILABLE_TEXT = "radar unavailable"
RADAR_LEGEND_TITLE = "RADAR"
RADAR_LEGEND_TITLE_CLOUDS = "CLOUDS"
RADAR_LEGEND_GLYPH = "\u25a0"
RADAR_LEGEND_ITEMS_RADAR = ((" light", 0.15), (" moderate", 0.55), (" heavy", 0.95))
RADAR_LEGEND_ITEMS_CLOUDS = ((" thin", 0.2), (" thick", 0.9))

_RADAR_TEXT = {"observed": "OBSERVED", "forecast": "FORECAST"}
_RADAR_LABELS = {
    "name": "NAME",
    "intensity": "INTENSITY",
    "position": "POSITION",
    "frame": "FRAME (UTC)",
    "kind": "KIND",
}

# Open-Meteo weather code -> description
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

LEGEND_TITLE = "CITY TEMP"
LEGEND_GLYPH = "●"
LEGEND_COLD = " cold"
LEGEND_HOT = " hot"
LEGEND_NO_DATA = " no data"

# Words shown in the info box.
_CITY_TEXT = {
    "capital": "CAPITAL",
    "city": "CITY",
    "fetching": "FETCHING...",
    "unavailable": "UNAVAILABLE",
    "not_available": "N/A",
    "unknown_weather": "Unknown",
    "unknown_date": "?",
}
# Row labels in the info box (keep them under 12 characters).
_CITY_LABELS = {
    "name": "NAME",
    "country": "COUNTRY",
    "type": "TYPE",
    "population": "POPULATION",
    "position": "POSITION",
    "weather": "WEATHER",
    "temperature": "TEMP",
    "conditions": "CONDITIONS",
    "wind": "WIND",
    "observed": "OBSERVED",
}
