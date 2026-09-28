from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

from around.layers.flights.settings import OPEN_SKY_API_URL


class FlightFetchError(Exception):
    pass


def fetch_opensky_states() -> list:
    request = urllib.request.Request(
        OPEN_SKY_API_URL,
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
        raise FlightFetchError(f"OpenSky request failed: {error}") from error
    if not isinstance(payload, dict):
        raise FlightFetchError("OpenSky returned an unexpected response format")
    states = payload.get("states", [])
    if not isinstance(states, list):
        raise FlightFetchError("OpenSky returned an unexpected response format")
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
            }
        )
    return flights
