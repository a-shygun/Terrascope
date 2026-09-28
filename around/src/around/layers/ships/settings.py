from around.config import DATA_DIR

SHIP_API_URL = "https://meri.digitraffic.fi/api/ais/v1/locations"
SHIP_REFRESH_INTERVAL_SECONDS = 5 * 60
SHIP_MAX_AGE_SECONDS = 30 * 60
SHIP_CACHE_FILE = DATA_DIR / "ship_cache.json"

SHIP_CONFIG = {
    "enabled": True,
    "color": "#43d17a",
}
