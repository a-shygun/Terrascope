from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

from around.layers.ships.settings import SHIP_API_URL, SHIP_MAX_AGE_SECONDS


class ShipFetchError(Exception):
    pass


def fetch_ship_locations() -> list[dict]:
    # Digitraffic is open data focused on Finnish waters. Request only a
    # recent window to avoid pulling a full day of AIS reports each refresh.
    query = urllib.parse.urlencode(
        {"from": int((time.time() - SHIP_MAX_AGE_SECONDS) * 1000)}
    )
    request = urllib.request.Request(
        f"{SHIP_API_URL}?{query}",
        headers={
            "User-Agent": "around-terminal-map/0.1",
            "Accept": "application/geo+json, application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read())
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeError,
    ) as error:
        raise ShipFetchError(f"Digitraffic AIS request failed: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ShipFetchError("Digitraffic returned an unexpected AIS response")
    return normalize_locations(payload["features"])


def normalize_locations(features: list) -> list[dict]:
    now = time.time()
    newest: dict[str, dict] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, dict) or not isinstance(properties, dict):
            continue
        coordinates = geometry.get("coordinates")
        if (
            geometry.get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            continue
        try:
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
            mmsi = str(feature.get("mmsi") or properties.get("mmsi") or "").strip()
            timestamp_ms = float(properties.get("timestampExternal"))
        except (TypeError, ValueError):
            continue
        timestamp = timestamp_ms / 1000.0
        if (
            not mmsi
            or not mmsi.isdigit()
            or not math.isfinite(longitude)
            or not math.isfinite(latitude)
            or not (-180 <= longitude <= 180 and -90 <= latitude <= 90)
            or timestamp < now - SHIP_MAX_AGE_SECONDS
            or timestamp > now + 300
        ):
            continue
        try:
            speed = float(properties.get("sog"))
            if not math.isfinite(speed) or speed >= 102.3 or speed < 0:
                speed = None
        except (TypeError, ValueError):
            speed = None
        try:
            course = float(properties.get("cog"))
            if not math.isfinite(course) or not 0 <= course <= 360:
                course = None
        except (TypeError, ValueError):
            course = None
        item = {
            "mmsi": mmsi,
            "name": str(properties.get("name") or "").strip() or f"SHIP {mmsi}",
            "call_sign": str(properties.get("callSign") or "").strip(),
            "longitude": longitude,
            "latitude": latitude,
            "speed_knots": speed,
            "course": course,
            "heading": properties.get("heading"),
            "nav_status": properties.get("navStat"),
            "timestamp": timestamp,
        }
        previous = newest.get(mmsi)
        if previous is None or item["timestamp"] > previous["timestamp"]:
            newest[mmsi] = item
    return list(newest.values())
