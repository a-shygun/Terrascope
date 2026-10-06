"""OpenSky requests and flight-response normalization."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from terrascope.core.config import FETCH_NEW_DATA_FROM_API, USER_AGENT
from terrascope.core.mapdata import set_live_progress
from terrascope.layers.flights.formatting import categorize, finite_float
from terrascope.layers.flights.settings import OPEN_SKY_API_URL, REQUEST_TIMEOUT_SECONDS

class FlightFetchError(Exception):
    pass

def fetch_opensky_states() -> list:
    request = urllib.request.Request(
        OPEN_SKY_API_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        set_live_progress("planes", state="downloading")
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            length = response.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None
            set_live_progress("planes", state="downloading", total=total)
            chunks = []
            downloaded = 0
            while chunk := response.read(32 * 1024):
                chunks.append(chunk)
                downloaded += len(chunk)
                set_live_progress("planes", state="downloading", downloaded=downloaded, total=total)
            payload = json.loads(b"".join(chunks))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as error:
        set_live_progress("planes", state="failed", error=str(error))
        raise FlightFetchError(f"OpenSky request failed: {error}") from error
    if not isinstance(payload, dict):
        set_live_progress("planes", state="failed", error="Unexpected response format")
        raise FlightFetchError("OpenSky returned an unexpected response format")
    states = payload.get("states", [])
    if not isinstance(states, list):
        set_live_progress("planes", state="failed", error="Unexpected response format")
        raise FlightFetchError("OpenSky returned an unexpected response format")
    set_live_progress("planes", state="ready", downloaded=1, total=1)
    return states

def normalize_states(states: list) -> list[dict]:
    flights = []
    for state in states:
        if not isinstance(state, list) or len(state) < 17:
            continue
        if state[8] is not False:
            continue
        try:
            longitude = float(state[5])
            latitude = float(state[6])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(longitude) and math.isfinite(latitude)):
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        flights.append(
            {
                "icao24": str(state[0] or "").strip().upper(),
                "callsign": str(state[1] or "").strip(),
                "origin_country": str(state[2] or "Unknown"),
                "time_position": state[3],
                "last_contact": state[4],
                "longitude": longitude,
                "latitude": latitude,
                "baro_altitude": state[7],
                "on_ground": state[8],
                "velocity": state[9],
                "true_track": state[10],
                "vertical_rate": state[11],
                "sensors": state[12],
                "geo_altitude": state[13],
                "squawk": state[14],
                "spi": state[15],
                "position_source": state[16],
                "category": state[17] if len(state) > 17 else None,
            }
        )
    return flights

def normalize_flights(flights) -> list[dict]:
    if not isinstance(flights, list):
        return []
    result = []
    for flight in flights:
        if not isinstance(flight, dict):
            continue
        try:
            longitude = float(flight["longitude"])
            latitude = float(flight["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(longitude) and math.isfinite(latitude)):
            continue
        if flight.get("on_ground") is not False:
            continue
        item = dict(flight)
        item["icao24"] = str(item.get("icao24") or "").strip().upper()
        item["longitude"] = longitude
        item["latitude"] = latitude
        result.append(item)
    return result
