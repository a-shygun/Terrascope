# mapdata.py — LOADING THE COUNTRY MAP DATA
# Responsible for: downloading the Natural Earth GeoJSON (and caching it),
# parsing it into polygon "rings" with bounding boxes, unwrapping longitudes
# across the antimeridian, and recovering from a corrupt cache.
# Edit this file to: change the map data source/format, caching behaviour, or
# which polygon parts (e.g. holes, lakes) are loaded.
# Not here: how the map is drawn (world.py, ui.py).

from __future__ import annotations
import json
import math
import urllib.error
import urllib.request
from pathlib import Path
from around.config import (
    CACHE_DIR,
    FETCH_NEW_DATA_FROM_API,
    MAP_FILE,
    NATURAL_EARTH_BASE_URL,
)

Ring = tuple[list[tuple[float, float]], float, float, float, float]


class MapDataError(Exception):
    pass


def download_map(filename: str, status_callback=None) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / filename
    if target.exists():
        return target
    if not FETCH_NEW_DATA_FROM_API:
        raise MapDataError(
            f"No cached {filename} is available in offline mode. Run once online to download it."
        )
    url = NATURAL_EARTH_BASE_URL + filename
    if status_callback:
        status_callback(f"Downloading {filename}")
    request = urllib.request.Request(
        url, headers={"User-Agent": "around/1.0", "Accept": "application/json"}
    )
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        temporary.write_bytes(data)
        temporary.replace(target)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
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


def load_polygons(path: Path, status_callback=None) -> list[Ring]:
    if status_callback:
        status_callback(f"Parsing {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MapDataError(f"Could not parse {path.name}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise MapDataError(f"Could not parse {path.name}: unexpected GeoJSON format")
    rings = []
    for feature in data.get("features", []):
        if not isinstance(feature, dict):
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


def load_map_data(status_callback=None) -> list[Ring]:
    country_path = download_map(MAP_FILE, status_callback)
    try:
        return load_polygons(country_path, status_callback)
    except MapDataError:
        # A truncated cache should not make every later launch fail. Remove
        # this generated artifact and make one clean download attempt.
        try:
            country_path.unlink(missing_ok=True)
        except OSError:
            raise
        fresh_path = download_map(MAP_FILE, status_callback)
        return load_polygons(fresh_path, status_callback)
