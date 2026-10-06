"""Settings for aircraft, airport, and history rendering."""

from __future__ import annotations

from pathlib import Path
from terrascope.core.config import CACHE_DIR, CFG

FLIGHT_CONFIG = CFG["layers"]["flights"]

OPEN_SKY_API_URL = FLIGHT_CONFIG["api_url"]

FLIGHT_REFRESH_INTERVAL_SECONDS = FLIGHT_CONFIG["refresh_interval_seconds"]

REQUEST_TIMEOUT_SECONDS = FLIGHT_CONFIG["request_timeout_seconds"]

FLIGHT_HISTORY_POINTS = FLIGHT_CONFIG["history_points"]

FLIGHT_CACHE_FILE = CACHE_DIR / "flight_cache.json"

ARROW_ZOOM_THRESHOLD = FLIGHT_CONFIG["arrow_zoom_threshold"]

ARROW_GLYPHS = tuple(FLIGHT_CONFIG["arrow_glyphs"])

UNKNOWN_HEADING_GLYPH = FLIGHT_CONFIG["unknown_heading_glyph"]

POSITION_SOURCES = {0: "ADS-B", 1: "ASTERIX", 2: "MLAT", 3: "FLARM"}

CATEGORY_ORDER = (
    "emergency", "heavy", "airliner", "regional", "light", "helicopter", "fast", "other",
)

CATEGORY_LABELS = {
    "emergency": "emergency", "heavy": "heavy", "airliner": "airliner",
    "regional": "regional", "light": "light", "helicopter": "helicopter",
    "fast": "fast/mil", "other": "other",
}

CATEGORY_COLORS = FLIGHT_CONFIG["category_colors"]

EMERGENCY_SQUAWKS = ("7500", "7600", "7700")

CATEGORY_BY_CODE = {
    2: "light", 12: "light",  # light, ultralight
    3: "regional",  # small (15,500 - 75,000 lb)
    4: "airliner",  # large (75,000 - 300,000 lb)
    5: "heavy", 6: "heavy",  # high vortex large (B757), heavy (> 300,000 lb)
    7: "fast",  # high performance (> 5 g, > 400 kt)
    8: "helicopter",
    9: "other", 10: "other", 11: "other", 14: "other",  # glider, balloon, skydiver, UAV
}

LIGHT_MAX_SPEED = FLIGHT_CONFIG["light_max_speed_ms"]

REGIONAL_MAX_SPEED = FLIGHT_CONFIG["regional_max_speed_ms"]

HIGH_ALTITUDE_METERS = FLIGHT_CONFIG["high_altitude_m"]

LEGEND_GLYPH = FLIGHT_CONFIG["legend_glyph"]

AIRPORT_CONFIG = FLIGHT_CONFIG["airports"]

AIRPORT_COLOR = AIRPORT_CONFIG["color"]

AIRPORT_LABEL_COLOR = AIRPORT_CONFIG["label_color"]

AIRPORT_GLYPH = AIRPORT_CONFIG["glyph"]

AIRPORT_LEVELS: tuple[tuple[float, int], ...] = tuple(
    (float(zoom), int(max_scalerank)) for zoom, max_scalerank in AIRPORT_CONFIG["levels"]
)

AIRPORT_LABEL_MIN_ZOOM = float(AIRPORT_CONFIG["label_min_zoom"])

AIRPORT_LABEL_PADDING = int(AIRPORT_CONFIG["label_padding"])

AIRPORT_MAX_LABELS = int(AIRPORT_CONFIG["max_labels"])

AIRPORT_LOAD_RETRY_SECONDS = AIRPORT_CONFIG["load_retry_seconds"]

AIRPORTS_LOADING_TEXT = "loading airports..."

AIRPORTS_UNAVAILABLE_TEXT = "airports unavailable"

EARTH_RADIUS_M = 6_371_000.0

MAX_EXTRAPOLATE_AGE_SECONDS = FLIGHT_CONFIG["max_extrapolate_age_seconds"]

_TEXT = {"not_available": "N/A", "unknown": "UNKNOWN"}

_LABELS = {
    "callsign": "CALLSIGN",
    "type": "TYPE",
    "icao24": "ICAO24",
    "country": "COUNTRY",
    "altitude": "ALTITUDE",
    "geo_altitude": "GEO ALT",
    "speed": "SPEED",
    "heading": "HEADING",
    "vertical_rate": "VERT RATE",
    "squawk": "SQUAWK",
    "position": "POSITION",
    "source": "SOURCE",
}
