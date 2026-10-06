"""Aircraft labels, categories, and position calculations."""

from __future__ import annotations

import math
from terrascope.layers.flights.settings import *
from terrascope.layers.flights.settings import _TEXT

def valid_history_point(point) -> bool:
    if not isinstance(point, dict):
        return False
    try:
        lon = float(point["longitude"])
        lat = float(point["latitude"])
    except (KeyError, TypeError, ValueError):
        return False
    return math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90

def distance_between_points(a: dict, b: dict) -> float:
    return math.hypot(
        float(a["longitude"]) - float(b["longitude"]),
        float(a["latitude"]) - float(b["latitude"]),
    )

def airport_scalerank_floor(zoom: float) -> int | None:
    """Largest (least major) scalerank shown at this zoom (None = none yet)."""
    floor = None
    for min_zoom, max_scalerank in AIRPORT_LEVELS:
        if zoom >= min_zoom:
            floor = max_scalerank
    return floor

def finite_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number

def heading_to_arrow(true_track) -> str:
    heading = finite_float(true_track)
    if heading is None:
        return UNKNOWN_HEADING_GLYPH
    heading = heading % 360.0
    index = int((heading + 22.5) // 45) % 8
    return ARROW_GLYPHS[index]

def format_altitude(value) -> str:
    meters = finite_float(value)
    if meters is None:
        return _TEXT["not_available"]
    feet = meters * 3.28084
    return f"{feet:,.0f} ft"

def format_speed(value) -> str:
    meters_per_second = finite_float(value)
    if meters_per_second is None:
        return _TEXT["not_available"]
    knots = meters_per_second * 1.943844
    return f"{knots:,.0f} kt"

def format_vertical_rate(value) -> str:
    meters_per_second = finite_float(value)
    if meters_per_second is None:
        return _TEXT["not_available"]
    feet_per_minute = meters_per_second * 196.850394
    return f"{feet_per_minute:+,.0f} ft/min"

def format_heading(value) -> str:
    heading = finite_float(value)
    if heading is None:
        return _TEXT["not_available"]
    return f"{heading:.0f}°"

def format_position_source(value) -> str:
    sources = POSITION_SOURCES
    try:
        source = int(value)
    except (TypeError, ValueError):
        return _TEXT["not_available"]
    return sources.get(source, str(source))

def categorize(flight: dict) -> str:
    """One of CATEGORY_ORDER for an aircraft: emergency squawk first, then the
    reported category code, then a guess from speed and altitude."""
    if str(flight.get("squawk") or "") in EMERGENCY_SQUAWKS:
        return "emergency"
    category = CATEGORY_BY_CODE.get(flight.get("category"))
    if category:
        return category
    speed = finite_float(flight.get("velocity"))
    if speed is None:
        return "other"
    altitude = finite_float(flight.get("baro_altitude"))
    if speed < LIGHT_MAX_SPEED:
        return "light"
    if speed < REGIONAL_MAX_SPEED and (altitude is None or altitude < HIGH_ALTITUDE_METERS):
        return "regional"
    return "airliner"

def live_position(flight: dict, at_time: float) -> tuple[float, float]:
    """(lon, lat) of an aircraft at unix time `at_time`, for a time at or after
    its last report: that position moved along its heading at its reported
    speed for the time since the report (capped)."""
    lon = flight["longitude"]
    lat = flight["latitude"]
    speed = finite_float(flight.get("velocity"))
    track = finite_float(flight.get("true_track"))
    if speed is None or track is None or speed <= 0:
        return lon, lat
    stamp = finite_float(flight.get("time_position")) or finite_float(flight.get("last_contact"))
    seconds = 0.0 if stamp is None else min(max(0.0, at_time - stamp), MAX_EXTRAPOLATE_AGE_SECONDS)
    if seconds <= 0:
        return lon, lat
    distance = speed * seconds / EARTH_RADIUS_M
    bearing = math.radians(track)
    phi1 = math.radians(lat)
    new_phi = math.asin(
        math.sin(phi1) * math.cos(distance)
        + math.cos(phi1) * math.sin(distance) * math.cos(bearing)
    )
    new_lambda = math.radians(lon) + math.atan2(
        math.sin(bearing) * math.sin(distance) * math.cos(phi1),
        math.cos(distance) - math.sin(phi1) * math.sin(new_phi),
    )
    return ((math.degrees(new_lambda) + 540.0) % 360.0) - 180.0, math.degrees(new_phi)

def position_at(flight: dict, history: list[dict], at_time: float) -> tuple[float, float] | None:
    """(lon, lat) of an aircraft at unix time `at_time`: interpolated between
    the recorded positions terrascope that time, moved on from the last one when
    the time is newer, or None if it was not being tracked yet."""
    points = [
        point
        for point in history
        if valid_history_point(point) and finite_float(point.get("timestamp")) is not None
    ]
    if not points:
        return live_position(flight, at_time)
    if at_time < float(points[0]["timestamp"]):
        return None
    if at_time >= float(points[-1]["timestamp"]):
        return live_position(flight, at_time)
    for before, after in zip(points, points[1:]):
        t0 = float(before["timestamp"])
        t1 = float(after["timestamp"])
        if t0 <= at_time <= t1:
            fraction = 0.0 if t1 <= t0 else (at_time - t0) / (t1 - t0)
            delta_lon = ((after["longitude"] - before["longitude"] + 180.0) % 360.0) - 180.0
            lon = ((before["longitude"] + delta_lon * fraction + 540.0) % 360.0) - 180.0
            lat = before["latitude"] + (after["latitude"] - before["latitude"]) * fraction
            return lon, lat
    return live_position(flight, at_time)
