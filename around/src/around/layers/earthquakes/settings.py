from around.config import DATA_DIR

USGS_FEED_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"
)
EARTHQUAKE_REFRESH_INTERVAL_SECONDS = 5 * 60
EARTHQUAKE_CACHE_FILE = DATA_DIR / "earthquake_cache.json"

EARTHQUAKE_CONFIG = {
    "enabled": True,
    "trail_color": "#8a5a2b",
    # USGS feed above is pre-filtered to M2.5+, this is a client-side floor
    # in case a different feed URL is configured.
    "min_magnitude": 2.5,
}

MAGNITUDE_COLOR_BANDS = (
    (3.0, "#ffd93d"),
    (4.5, "#ff9f43"),
    (6.0, "#ff4d4d"),
    (7.5, "#c0392b"),
)
MAGNITUDE_COLOR_MAJOR = "#7c2d92"
MAGNITUDE_COLOR_UNKNOWN = "#888888"

ALERT_COLORS = {
    "green": "#6bcb77",
    "yellow": "#ffd93d",
    "orange": "#ff9f43",
    "red": "#ff4d4d",
}
