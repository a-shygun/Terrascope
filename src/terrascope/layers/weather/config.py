"""Shared settings and display text for the weather layer."""

from __future__ import annotations

import os
from terrascope.core.config import CACHE_DIR, CFG
from terrascope.core.i18n import _
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
PLACES_LOADING_TEXT = _("loading cities...")
PLACES_UNAVAILABLE_TEXT = _("cities unavailable")
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
# Number of discrete colour pairs the temperature gradient is snapped to.
# Curses has a limited colour-pair budget, so nearby readings share a pair.
_COLOR_STEPS = int(CITY_CONFIG["color_steps"])

# ---------------------------------------------------------------------------
# Radar overlay settings (RainViewer), from default.yaml (layers: weather: radar:).
# ---------------------------------------------------------------------------

# Everything below comes from default.yaml (layers: weather: radar:).
RADAR_CONFIG = WEATHER_CONFIG["radar"]
RADAR_ENABLED = bool(RADAR_CONFIG["enabled"])
RADAR_MODE = RADAR_CONFIG["mode"]  # "radar" | "satellite"
# RainViewer catalog API. Tile requests use the host returned by its catalog.
# Older user config files keep the bundled default copied at first launch, so
# translate that former default while preserving any custom API URL.
_configured_radar_url = str(RADAR_CONFIG["url"]).rstrip("/")
if _configured_radar_url == "https://api.librewxr.net":
    _configured_radar_url = "https://api.rainviewer.com"
RAINVIEWER_URL = os.environ.get("terrascope_RAINVIEWER_URL", _configured_radar_url).rstrip("/")

CATALOG_REFRESH_SECONDS = RADAR_CONFIG["catalog_refresh_seconds"]  # RainViewer updates frames about every 10 min
CATALOG_RETRY_SECONDS = RADAR_CONFIG["catalog_retry_seconds"]  # retry sooner after a failure
REQUEST_TIMEOUT_SECONDS = RADAR_CONFIG["request_timeout_seconds"]
MAX_CONCURRENT_TILE_REQUESTS = RADAR_CONFIG["max_concurrent_tile_requests"]

PAST_FRAMES = RADAR_CONFIG["past_frames"]  # most observed frames kept (10 min apart)
HISTORY_MINUTES = float(RADAR_CONFIG["history_minutes"])  # drop observed frames older than this (0 = keep all the server offers)
RADAR_OPACITY = float(RADAR_CONFIG["opacity"])  # 1 = full palette colours, lower = fainter
_RADAR_BLEND_RGB = hex_to_rgb(RADAR_CONFIG["blend_color"])  # what the colours fade towards
# Legacy configuration values kept readable for existing user config files.

# The whole world is fetched as one Web-Mercator raster of 2^Z x 2^Z tiles.
# Z=2 with 512px tiles = 16 requests per frame and a 2048px raster (~0.18 deg
# per pixel). Raise Z for finer detail at 4x the requests per step.
WORLD_ZOOM = RADAR_CONFIG["world_zoom"]
TILE_SIZE = RADAR_CONFIG["tile_size"]

# Radar intensities are mapped to 0..1 between these 8-bit values, then through
# the configured terminal palette.
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

RADAR_LOADING_TEXT = _("loading radar...")
RADAR_UNAVAILABLE_TEXT = _("radar unavailable")
RADAR_LEGEND_TITLE = _("RADAR")
RADAR_LEGEND_TITLE_CLOUDS = _("CLOUDS")
RADAR_LEGEND_GLYPH = "\u25a0"
RADAR_LEGEND_ITEMS_RADAR = ((_(" light"), 0.15), (_(" moderate"), 0.55), (_(" heavy"), 0.95))
RADAR_LEGEND_ITEMS_CLOUDS = ((_(" thin"), 0.2), (_(" thick"), 0.9))

_RADAR_TEXT = {"observed": _("OBSERVED"), "forecast": _("FORECAST")}
_RADAR_LABELS = {
    "name": _("NAME"),
    "intensity": _("INTENSITY"),
    "position": _("POSITION"),
    "frame": _("FRAME (UTC)"),
    "kind": _("KIND"),
}

# Open-Meteo weather code -> description
WEATHER_CODES = {
    0: _("Clear sky"),
    1: _("Mainly clear"),
    2: _("Partly cloudy"),
    3: _("Overcast"),
    45: _("Fog"),
    48: _("Rime fog"),
    51: _("Light drizzle"),
    53: _("Drizzle"),
    55: _("Dense drizzle"),
    56: _("Freezing drizzle"),
    57: _("Freezing drizzle"),
    61: _("Slight rain"),
    63: _("Rain"),
    65: _("Heavy rain"),
    66: _("Freezing rain"),
    67: _("Freezing rain"),
    71: _("Slight snow"),
    73: _("Snow"),
    75: _("Heavy snow"),
    77: _("Snow grains"),
    80: _("Rain showers"),
    81: _("Rain showers"),
    82: _("Violent rain showers"),
    85: _("Snow showers"),
    86: _("Snow showers"),
    95: _("Thunderstorm"),
    96: _("Thunderstorm, hail"),
    99: _("Thunderstorm, heavy hail"),
}

LEGEND_TITLE = _("CITY TEMP")
LEGEND_GLYPH = "●"
LEGEND_COLD = _(" cold")
LEGEND_HOT = _(" hot")
LEGEND_NO_DATA = _(" no data")

# Words shown in the info box.
_CITY_TEXT = {
    "capital": _("CAPITAL"),
    "city": _("CITY"),
    "fetching": _("FETCHING..."),
    "unavailable": _("UNAVAILABLE"),
    "not_available": _("N/A"),
    "unknown_weather": _("Unknown"),
    "unknown_date": "?",
}
# Row labels in the info box (keep them under 12 characters).
_CITY_LABELS = {
    "name": _("NAME"),
    "country": _("COUNTRY"),
    "type": _("TYPE"),
    "population": _("POPULATION"),
    "position": _("POSITION"),
    "weather": _("WEATHER"),
    "temperature": _("TEMP"),
    "conditions": _("CONDITIONS"),
    "wind": _("WIND"),
    "observed": _("OBSERVED"),
}
