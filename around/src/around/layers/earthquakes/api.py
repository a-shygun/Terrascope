from __future__ import annotations

import json
import urllib.error
import urllib.request

from around.layers.earthquakes.settings import USGS_FEED_URL


class EarthquakeFetchError(Exception):
    pass


def fetch_usgs_earthquakes() -> list:
    request = urllib.request.Request(
        USGS_FEED_URL,
        headers={"User-Agent": "around/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
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
                "place": properties.get("place") or "Unknown location",
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
