# mapdata.py — LOADING THE COUNTRY MAP DATA
# Responsible for: downloading the Natural Earth GeoJSON (and caching it),
# parsing it into polygon "rings" with bounding boxes, unwrapping longitudes
# across the antimeridian, and recovering from a corrupt cache. Also loads the
# populated places the basemap needs, from Natural Earth and the same cache.
# Country labels and airport locations are bundled in assets/reference_data.json.
# Edit this file to: change the map data source/format, caching behaviour, or
# which polygon parts (e.g. holes, lakes, Antarctica) are loaded.
# Not here: how the map is drawn (world.py, ui.py).

from __future__ import annotations

import json
import math
import threading
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
from terrascope.core.config import CACHE_DIR, CFG, FETCH_NEW_DATA_FROM_API, USER_AGENT

# Data-source settings (from default.yaml, data:).
DATA_CONFIG = CFG["data"]
NATURAL_EARTH_BASE_URL = DATA_CONFIG["natural_earth_base_url"]
# Migrate the former bundled low-detail defaults in existing user configs to
# the supported 50m defaults. Keep any deliberately different source.
MAP_FILE = DATA_CONFIG["countries_file"]
if MAP_FILE == "ne_110m_admin_0_countries.geojson":
    MAP_FILE = "ne_50m_admin_0_countries.geojson"
# State / province boundaries (lines, worldwide). Downloaded once in the
# background after the countries and cached next to them.
PROVINCE_FILE = DATA_CONFIG["provinces_file"]
if PROVINCE_FILE == "ne_50m_admin_1_states_provinces_lines.geojson":
    PROVINCE_FILE = "ne_10m_admin_1_states_provinces_lines.geojson"
# Cities / towns worldwide (points with name, population and a capital flag).
PLACES_FILE = DATA_CONFIG["places_file"]
if PLACES_FILE == "ne_50m_populated_places_simple.geojson":
    PLACES_FILE = "ne_10m_populated_places_simple.geojson"
MAP_DOWNLOAD_TIMEOUT_SECONDS = DATA_CONFIG["download_timeout_seconds"]
REFERENCE_DATA_FILE = Path(__file__).resolve().parents[1] / "assets" / "reference_data.json"

Ring = tuple[list[tuple[float, float]], float, float, float, float]
CountryLabel = tuple[float, float, str, float, str]  # lon, lat, short code, size (bigger = more important), full name
Place = tuple[float, float, str, bool, int, str]  # lon, lat, name, is_capital, population, country
Airport = tuple[float, float, str, str, int]  # lon, lat, name, IATA/ICAO code, scalerank (lower = more major)

# The map loader and the place-name loader both start at launch and may both
# want the same file; one download at a time, so they never write the same
# temporary file together.
_DOWNLOAD_LOCKS_LOCK = threading.Lock()
_DOWNLOAD_LOCKS: dict[str, threading.Lock] = {}

def _download_lock(filename: str) -> threading.Lock:
    with _DOWNLOAD_LOCKS_LOCK:
        return _DOWNLOAD_LOCKS.setdefault(filename, threading.Lock())

@dataclass
class DownloadProgress:
    filename: str
    downloaded: int = 0
    total: int | None = None
    state: str = "waiting"  # waiting | downloading | ready | failed
    optional: bool = False
    error: str = ""

_DOWNLOAD_PROGRESS_LOCK = threading.Lock()
_DOWNLOAD_PROGRESS = {
    filename: DownloadProgress(filename)
    for filename in (MAP_FILE, PLACES_FILE, PROVINCE_FILE)
}
_DOWNLOAD_PROGRESS["api:planes"] = DownloadProgress("LIVE AIRCRAFT")
_DOWNLOAD_PROGRESS["api:radar"] = DownloadProgress("WEATHER RADAR")
_DOWNLOAD_PROGRESS["api:weather"] = DownloadProgress("CITY WEATHER")
_DOWNLOAD_PROGRESS["api:radar-history"] = DownloadProgress("RADAR HISTORY")

STARTUP_PROGRESS_KEYS = (
    MAP_FILE,
    PLACES_FILE,
    "api:planes",
    "api:radar",
    "api:weather",
    "api:radar-history",
)

def set_live_progress(
    name: str,
    *,
    state: str,
    downloaded: int = 0,
    total: int | None = None,
    error: str = "",
) -> None:
    """Publish progress for a live API feed such as aircraft or radar."""
    _set_download_progress(
        f"api:{name}", state=state, downloaded=downloaded, total=total,
        error=error if state == "failed" else "",
    )

def download_progress() -> tuple[DownloadProgress, ...]:
    """Return a thread-safe snapshot of first-run Natural Earth downloads."""
    with _DOWNLOAD_PROGRESS_LOCK:
        snapshot = []
        for key, item in _DOWNLOAD_PROGRESS.items():
            if key.startswith("api:"):
                snapshot.append(DownloadProgress(
                    item.filename, item.downloaded, item.total, item.state,
                    item.optional, item.error,
                ))
                continue
            cached = CACHE_DIR / item.filename
            if cached.exists() and item.state not in {"downloading", "failed"}:
                snapshot.append(DownloadProgress(
                    item.filename, cached.stat().st_size, cached.stat().st_size,
                    "ready", item.optional, "",
                ))
            elif item.optional and item.state == "waiting":
                continue
            else:
                snapshot.append(DownloadProgress(
                    item.filename, item.downloaded, item.total, item.state,
                    item.optional, item.error,
                ))
        return tuple(snapshot)

def startup_progress() -> tuple[str, int, str, str]:
    """Return (step label, overall percent, state, error) for the installer UI."""
    snapshots = {item.filename: item for item in download_progress()}
    names = {
        "api:planes": "LIVE AIRCRAFT",
        "api:radar": "WEATHER RADAR",
        "api:weather": "CITY WEATHER",
        "api:radar-history": "RADAR HISTORY",
    }
    steps = [
        snapshots[names.get(key, key)]
        for key in STARTUP_PROGRESS_KEYS
        if names.get(key, key) in snapshots
    ]
    if not steps:
        return "SETUP COMPLETE", 100, "ready", ""
    for index, item in enumerate(steps):
        if item.state in {"ready", "disabled"}:
            continue
        local = 0
        if item.state == "downloading" and item.total:
            local = max(0, min(100, int(item.downloaded * 100 / item.total)))
        percent = int((index + local / 100) * 100 / len(steps))
        return item.filename, percent, item.state, item.error
    return "SETUP COMPLETE", 100, "ready", ""

def _set_download_progress(filename: str, **values) -> None:
    with _DOWNLOAD_PROGRESS_LOCK:
        progress = _DOWNLOAD_PROGRESS.get(filename)
        if progress is not None:
            for name, value in values.items():
                setattr(progress, name, value)

class MapDataError(Exception):
    pass

@lru_cache(maxsize=1)
def _reference_data() -> dict:
    """Read the small, bundled Natural Earth reference tables once."""
    try:
        return json.loads(REFERENCE_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MapDataError(f"could not load bundled reference data: {error}") from error

def download_map(filename: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / filename
    with _download_lock(filename):
        if target.exists():
            _set_download_progress(filename, state="ready", downloaded=target.stat().st_size, error="")
            return target
        if not FETCH_NEW_DATA_FROM_API:
            raise MapDataError(
                f"No cached {filename} is available in offline mode. Run once online to download it."
            )
        temporary = target.with_suffix(target.suffix + ".tmp")
        try:
            _set_download_progress(filename, state="downloading", downloaded=0, total=None, error="")
            url = NATURAL_EARTH_BASE_URL + filename
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
            with urllib.request.urlopen(request, timeout=MAP_DOWNLOAD_TIMEOUT_SECONDS) as response:
                length = response.headers.get("Content-Length")
                _set_download_progress(
                    filename, state="downloading", downloaded=0,
                    total=int(length) if length and length.isdigit() else None,
                )
                downloaded = 0
                with temporary.open("wb") as output:
                    while chunk := response.read(64 * 1024):
                        output.write(chunk)
                        downloaded += len(chunk)
                        _set_download_progress(filename, downloaded=downloaded)
            temporary.replace(target)
            _set_download_progress(filename, state="ready", downloaded=downloaded)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            _set_download_progress(filename, state="failed", error=str(error))
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise MapDataError(f"Could not download {filename}: {error}") from error
        return target

def unwrap_ring(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not points:
        return points
    result = [points[0]]
    previous_lon = points[0][0]
    offset = 0.0
    for lon, lat in points[1:]:
        delta = lon - previous_lon
        if delta > 180:
            offset -= 360.0
        elif delta < -180:
            offset += 360.0
        adjusted_lon = lon + offset
        result.append((adjusted_lon, lat))
        previous_lon = lon
    return result

def make_ring(points) -> Ring | None:
    if not points:
        return None
    converted = []
    for point in points:
        if len(point) < 2:
            continue
        lon = float(point[0])
        lat = float(point[1])
        if not math.isfinite(lon):
            continue
        if not math.isfinite(lat):
            continue
        converted.append((lon, lat))
    if len(converted) < 2:
        return None
    converted = unwrap_ring(converted)
    lons = [point[0] for point in converted]
    lats = [point[1] for point in converted]
    return (converted, min(lons), max(lons), min(lats), max(lats))

def _is_antarctica(properties: object) -> bool:
    """True for the Antarctica feature in Natural Earth country files."""
    if not isinstance(properties, dict):
        return False
    props = {str(key).upper(): value for key, value in properties.items()}
    if props.get("CONTINENT") == "Antarctica":
        return True
    if props.get("ADM0_A3") == "ATA" or props.get("ISO_A3") == "ATA":
        return True
    return "Antarctica" in (props.get("ADMIN"), props.get("NAME"))

# ---------------------------------------------------------------------------
# Shared GeoJSON loading: parse + validate once, feed both parsers below.
# ---------------------------------------------------------------------------

def _load_geojson_features(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MapDataError(f"Could not parse {path.name}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise MapDataError(f"Could not parse {path.name}: unexpected GeoJSON format")
    return data["features"]

def _load_with_retry(
    filename: str,
    parser: Callable[[Path], list],
) -> list:
    """Download (if needed), parse, and on a corrupt cache remove it and make
    one clean re-download attempt. Shared by every loader in this file, which
    differ only in filename and parser."""
    path = download_map(filename)
    try:
        return parser(path)
    except MapDataError:
        # A truncated cache should not make every later launch fail. Remove
        # this generated artifact and make one clean download attempt.
        path.unlink(missing_ok=True)
        return parser(download_map(filename))

# ---------------------------------------------------------------------------
# Countries (filled polygons)
# ---------------------------------------------------------------------------

def load_polygons(path: Path) -> list[Ring]:
    rings = []
    for feature in _load_geojson_features(path):
        if not isinstance(feature, dict):
            continue
        if _is_antarctica(feature.get("properties")):
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type == "Polygon":
            if coordinates:
                ring = make_ring(coordinates[0])
                if ring:
                    rings.append(ring)
        elif geometry_type == "MultiPolygon" and coordinates:
            for polygon in coordinates:
                if not polygon:
                    continue
                ring = make_ring(polygon[0])
                if ring:
                    rings.append(ring)
    return rings

def load_map_data() -> list[Ring]:
    return load_map_data_from(MAP_FILE)

def load_map_data_from(filename: str) -> list[Ring]:
    return _load_with_retry(filename, load_polygons)

# ---------------------------------------------------------------------------
# Province / state border lines
# ---------------------------------------------------------------------------

def _geometry_lines(geometry: dict):
    """Yield every coordinate list in a LineString / MultiLineString (or, as a
    fallback, the rings of a Polygon / MultiPolygon) geometry."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if not coordinates:
        return
    if kind == "LineString":
        yield coordinates
    elif kind == "MultiLineString":
        yield from coordinates
    elif kind == "Polygon":
        yield from coordinates
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            yield from polygon

def load_province_lines_file(path: Path) -> list[Ring]:
    rings = []
    for feature in _load_geojson_features(path):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if isinstance(properties, dict):
            props = {str(key).lower(): value for key, value in properties.items()}
            # Country borders are already drawn from the countries file.
            if "country" in str(props.get("featurecla", "")).lower():
                continue
            if props.get("adm0_a3") == "ATA":
                continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        for part in _geometry_lines(geometry):
            ring = make_ring(part)
            if ring:
                rings.append(ring)
    return rings

def load_province_lines() -> list[Ring]:
    return load_province_lines_from(PROVINCE_FILE)

def load_province_lines_from(filename: str) -> list[Ring]:
    return _load_with_retry(filename, load_province_lines_file)

# Country names and codes are bundled; polygons are still downloaded for borders.
COUNTRY_CODE_OVERRIDES = dict(CFG["map"]["country_code_overrides"])

def load_country_labels() -> list[CountryLabel]:
    """Return (lon, lat, short code, size, full name) from bundled data."""
    return [
        (float(lon), float(lat), COUNTRY_CODE_OVERRIDES.get(code, code), float(size), str(name))
        for lon, lat, code, size, name in _reference_data()["country_labels"]
    ]

# ---------------------------------------------------------------------------
# Cities and towns (populated places)
# ---------------------------------------------------------------------------

def load_places_file(path: Path) -> list[Place]:
    """(lon, lat, name, is_capital, population, country) per populated place.
    is_capital is true for national capitals only (not state / province ones)."""
    places = []
    for feature in _load_geojson_features(path):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        coordinates = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        try:
            lon = float(coordinates[0])
            lat = float(coordinates[1])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(lon) and math.isfinite(lat)):
            continue
        props = {str(key).lower(): value for key, value in properties.items()}
        name = props.get("name") or props.get("nameascii")
        if not name:
            continue
        is_capital = str(props.get("featurecla", "")).lower().startswith("admin-0 capital")
        if str(props.get("adm0cap", "")).strip() in ("1", "1.0"):
            is_capital = True
        population = 0
        for key in ("pop_max", "pop_min"):
            try:
                population = max(population, int(float(props.get(key) or 0)))
            except (TypeError, ValueError):
                pass
        country = str(props.get("adm0name") or props.get("sov0name") or "")
        places.append((lon, lat, str(name), is_capital, population, country))
    return places

def load_places() -> list[Place]:
    return load_places_from(PLACES_FILE)

def load_places_from(filename: str) -> list[Place]:
    return _load_with_retry(filename, load_places_file)

# ---------------------------------------------------------------------------
# Airports
# ---------------------------------------------------------------------------

def load_airports() -> list[Airport]:
    """Return bundled Natural Earth airports as (lon, lat, name, code, rank)."""
    return [
        (float(lon), float(lat), str(name), str(code), int(rank))
        for lon, lat, name, code, rank in _reference_data()["airports"]
    ]
