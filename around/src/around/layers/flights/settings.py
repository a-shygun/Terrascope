from around.config import DATA_DIR

OPEN_SKY_API_URL = "https://opensky-network.org/api/states/all"
FLIGHT_REFRESH_INTERVAL_SECONDS = 5 * 60
FLIGHT_HISTORY_POINTS = 8
FLIGHT_CACHE_FILE = DATA_DIR / "flight_cache.json"

FLIGHT_CONFIG = {
    "enabled": True,
    # Every aircraft (and its tail, when shown) renders in this one color.
    # "color": "#4169E1",
    "color": "#41AEE1",
    "arrow_zoom_threshold": 8.0,
}

ARROW_GLYPHS = ("↑", "↗", "→", "↘", "↓", "↙", "←", "↖")
UNKNOWN_HEADING_GLYPH = "●"