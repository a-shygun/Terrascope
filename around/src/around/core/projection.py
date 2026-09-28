# projection.py — PURE MAP MATH (no drawing, no state)
# Responsible for: viewport size from zoom (calculate_viewport), lon/lat ->
# screen position (project_location), longitude wrap-around (visible,
# normalize_longitude) and keeping the map centre within bounds (clamp_center).
# Edit this file to: change the projection, how the world wraps horizontally,
# or panning limits.

from __future__ import annotations
from around.core.mapdata import Ring

WRAP_SHIFTS = (-360.0, 0.0, 360.0)


def visible(
    polygon: Ring,
    center_lon: float,
    center_lat: float,
    lon_span: float,
    lat_span: float,
) -> list[float]:
    _, min_lon, max_lon, min_lat, max_lat = polygon
    view_min_lon = center_lon - lon_span / 2
    view_max_lon = center_lon + lon_span / 2
    view_min_lat = center_lat - lat_span / 2
    view_max_lat = center_lat + lat_span / 2
    if max_lat < view_min_lat:
        return []
    if min_lat > view_max_lat:
        return []
    shifts = []
    for shift in WRAP_SHIFTS:
        shifted_min = min_lon + shift
        shifted_max = max_lon + shift
        if shifted_max < view_min_lon:
            continue
        if shifted_min > view_max_lon:
            continue
        shifts.append(shift)
    return shifts


def project_location(
    longitude: float,
    latitude: float,
    center_lon: float,
    center_lat: float,
    lon_span: float,
    lat_span: float,
    render_width: int,
    render_height: int,
) -> tuple[float, float] | None:
    relative_lon = (longitude - (center_lon - lon_span / 2)) % 360.0
    if relative_lon > lon_span:
        return None
    x = relative_lon / lon_span * render_width
    y = (center_lat + lat_span / 2 - latitude) / lat_span * render_height
    if x < 0 or x >= render_width or y < 0 or y >= render_height:
        return None
    return x, y


def calculate_viewport(zoom: float) -> tuple[float, float]:
    lon_span = 360.0 / zoom
    lat_span = 180.0 / zoom
    return lon_span, lat_span


def normalize_longitude(longitude: float) -> float:
    return ((longitude + 180.0) % 360.0) - 180.0


def clamp_center(
    center_lon: float, center_lat: float, lon_span: float, lat_span: float
) -> tuple[float, float]:
    center_lon = normalize_longitude(center_lon)
    if lat_span >= 180:
        center_lat = 0.0
    else:
        half_lat = lat_span / 2
        center_lat = max(-90 + half_lat, min(90 - half_lat, center_lat))
    return center_lon, center_lat
