"""USGS earthquake fetching, formatting, and cache."""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from terrascope.core.config import CACHE_DIR, USER_AGENT, FETCH_NEW_DATA_FROM_API
from terrascope.layers.weather.config import WEATHER_CONFIG

EARTHQUAKE_CONFIG = WEATHER_CONFIG["earthquakes"]

USGS_FEED_URL = EARTHQUAKE_CONFIG["api_url"]
EARTHQUAKE_REFRESH_INTERVAL_SECONDS = EARTHQUAKE_CONFIG["refresh_interval_seconds"]
EARTHQUAKE_CACHE_FILE = CACHE_DIR / "earthquake_cache.json"  # inside the cache dir
QUAKE_REQUEST_TIMEOUT_SECONDS = EARTHQUAKE_CONFIG["request_timeout_seconds"]
MIN_MAGNITUDE = EARTHQUAKE_CONFIG["min_magnitude"]  # events below this are hidden

# Choices offered by the "o" filter. Keep the "X.Y+" format: the number is the
# minimum magnitude.
FILTER_OPTIONS = tuple(EARTHQUAKE_CONFIG["filter_options"])

# Each entry is (limit, colour): an event takes the colour of the first entry
# whose limit is above its magnitude. At or above the last limit it gets the
# "major" colour. The last band's colour is also used in the controls bar.
MAGNITUDE_COLOR_BANDS = tuple(
    (float(limit), str(color)) for limit, color in EARTHQUAKE_CONFIG["magnitude_bands"]
)
MAGNITUDE_COLOR_MAJOR = EARTHQUAKE_CONFIG["major_color"]
MAGNITUDE_COLOR_UNKNOWN = EARTHQUAKE_CONFIG["unknown_color"]  # events with no magnitude
# Marker symbol by magnitude: (min magnitude, glyph), the first one is the default.
QUAKE_GLYPHS = tuple((float(minimum), str(glyph)) for minimum, glyph in EARTHQUAKE_CONFIG["glyphs"])
# Quakes older than this are drawn faded.
QUAKE_DIM_AFTER_SECONDS = float(EARTHQUAKE_CONFIG["dim_after_hours"]) * 3600

# Legend: one label per colour (the bands, then major).
LEGEND_LABELS = (" <3", " 3-4.4", " 4.5-5.9", " 6-7.4", " 7.5+")

# Texts shown in the info box (keep labels under 12 characters).
_QUAKE_TEXT = {
    "not_available": "N/A",
    "unknown": "UNKNOWN",
    "unknown_place": "Unknown location",
    "tsunami_warning": "WARNING",
    "tsunami_none": "NO",
}
_QUAKE_LABELS = {
    "magnitude": "MAGNITUDE",
    "place": "PLACE",
    "depth": "DEPTH",
    "time": "TIME",
    "tsunami": "TSUNAMI",
    "alert": "ALERT",
    "status": "STATUS",
    "position": "POSITION",
}

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def magnitude_to_color(magnitude) -> str:
    if magnitude is None:
        return MAGNITUDE_COLOR_UNKNOWN
    for threshold, color in MAGNITUDE_COLOR_BANDS:
        if magnitude < threshold:
            return color
    return MAGNITUDE_COLOR_MAJOR

def magnitude_to_glyph(magnitude) -> str:
    glyph = QUAKE_GLYPHS[0][1]
    if magnitude is None:
        return glyph
    for minimum, candidate in QUAKE_GLYPHS:
        if magnitude >= minimum:
            glyph = candidate
    return glyph

def format_magnitude(magnitude) -> str:
    if magnitude is None:
        return _QUAKE_TEXT["not_available"]
    return f"M {magnitude:.1f}"

def format_depth(depth_km) -> str:
    if depth_km is None:
        return _QUAKE_TEXT["not_available"]
    return f"{depth_km:.1f} km"

def format_time_ago(epoch_ms) -> str:
    if epoch_ms is None:
        return _QUAKE_TEXT["not_available"]
    try:
        seconds_ago = max(0.0, time.time() - float(epoch_ms) / 1000.0)
    except (TypeError, ValueError):
        return _QUAKE_TEXT["not_available"]
    if seconds_ago < 3600:
        return f"{seconds_ago / 60:.0f}m ago"
    if seconds_ago < 86400:
        return f"{seconds_ago / 3600:.1f}h ago"
    return f"{seconds_ago / 86400:.1f}d ago"

def format_tsunami(flag: bool) -> str:
    return _QUAKE_TEXT["tsunami_warning"] if flag else _QUAKE_TEXT["tsunami_none"]

# ---------------------------------------------------------------------------
# USGS API
# ---------------------------------------------------------------------------

class EarthquakeFetchError(Exception):
    pass

def fetch_usgs_earthquakes() -> list:
    request = urllib.request.Request(
        USGS_FEED_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=QUAKE_REQUEST_TIMEOUT_SECONDS
        ) as response:
            payload = json.loads(response.read())
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise EarthquakeFetchError(f"USGS request failed: {error}") from error
    if not isinstance(payload, dict):
        raise EarthquakeFetchError("USGS returned an unexpected response format")
    features = payload.get("features", [])
    if not isinstance(features, list):
        raise EarthquakeFetchError("USGS returned an unexpected response format")
    return features

def normalize_features(features: list) -> list[dict]:
    quakes = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        try:
            longitude = float(coordinates[0])
            latitude = float(coordinates[1])
            depth_km = float(coordinates[2]) if len(coordinates) > 2 else None
        except (TypeError, ValueError):
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        magnitude = properties.get("mag")
        try:
            magnitude = float(magnitude) if magnitude is not None else None
        except (TypeError, ValueError):
            magnitude = None
        quakes.append(
            {
                "id": feature.get("id") or "",
                "place": properties.get("place") or _QUAKE_TEXT["unknown_place"],
                "magnitude": magnitude,
                "depth_km": depth_km,
                "time": properties.get("time"),
                "updated": properties.get("updated"),
                "tsunami": bool(properties.get("tsunami")),
                "alert": properties.get("alert"),
                "felt": properties.get("felt"),
                "status": properties.get("status"),
                "event_type": properties.get("type") or "earthquake",
                "url": properties.get("url") or "",
                "longitude": longitude,
                "latitude": latitude,
            }
        )
    return quakes

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def normalize_cached(quakes) -> list[dict]:
    if not isinstance(quakes, list):
        return []
    result = []
    for quake in quakes:
        if not isinstance(quake, dict):
            continue
        try:
            longitude = float(quake["longitude"])
            latitude = float(quake["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(longitude) and math.isfinite(latitude)):
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        item = dict(quake)
        item["longitude"] = longitude
        item["latitude"] = latitude
        result.append(item)
    return result

class EarthquakeCache:
    def __init__(self, path: Path = EARTHQUAKE_CACHE_FILE) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.last_fetch: float | None = None
        self.quakes: list[dict] = []
        self.last_error = ""
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        try:
            self.last_fetch = (
                float(data.get("last_fetch"))
                if data.get("last_fetch") is not None
                else None
            )
        except (TypeError, ValueError):
            self.last_fetch = None
        if self.last_fetch is not None and not math.isfinite(self.last_fetch):
            self.last_fetch = None
        self.quakes = normalize_cached(data.get("quakes", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_fetch": self.last_fetch, "quakes": self.quakes}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def age_seconds(self) -> float | None:
        if self.last_fetch is None:
            return None
        return max(0.0, time.time() - self.last_fetch)

    def should_fetch(self) -> bool:
        if not FETCH_NEW_DATA_FROM_API:
            return False
        age = self.age_seconds()
        return age is None or age >= EARTHQUAKE_REFRESH_INTERVAL_SECONDS

    def refresh_if_due(self, force: bool = False) -> bool:
        if not force and not self.should_fetch():
            return False
        if not FETCH_NEW_DATA_FROM_API:
            return False
        with self.lock:
            if not force and not self.should_fetch():
                return False
            try:
                features = fetch_usgs_earthquakes()
            except EarthquakeFetchError as error:
                self.last_error = str(error)
                return False
            self.quakes = normalize_features(features)
            self.last_fetch = time.time()
            self.last_error = ""
            try:
                self.save()
            except OSError as error:
                self.last_error = f"Could not save earthquake cache: {error}"
            return True

    def get_quakes(self) -> list[dict]:
        with self.lock:
            return [dict(quake) for quake in self.quakes]

# ---------------------------------------------------------------------------
