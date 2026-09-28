from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

from around.config import FETCH_NEW_DATA_FROM_API
from around.layers.flights.api import (
    FlightFetchError,
    fetch_opensky_states,
    normalize_states,
)
from around.layers.flights.settings import (
    FLIGHT_CACHE_FILE,
    FLIGHT_HISTORY_POINTS,
    FLIGHT_REFRESH_INTERVAL_SECONDS,
)


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


def valid_history_point(point) -> bool:
    if not isinstance(point, dict):
        return False
    try:
        lon = float(point["longitude"])
        lat = float(point["latitude"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        math.isfinite(lon)
        and math.isfinite(lat)
        and -180 <= lon <= 180
        and -90 <= lat <= 90
    )


def distance_between_points(a: dict, b: dict) -> float:
    return math.hypot(
        float(a["longitude"]) - float(b["longitude"]),
        float(a["latitude"]) - float(b["latitude"]),
    )


class FlightCache:
    def __init__(self, path: Path = FLIGHT_CACHE_FILE) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.last_fetch: float | None = None
        self.flights: list[dict] = []
        self.history: dict[str, list[dict]] = {}
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
        self.flights = normalize_flights(data.get("flights", []))
        raw_history = data.get("history", {})
        if isinstance(raw_history, dict):
            self.history = {}
            for icao, points in raw_history.items():
                if not isinstance(points, list):
                    continue
                clean = [point for point in points if valid_history_point(point)]
                if clean:
                    self.history[str(icao).upper()] = clean[-FLIGHT_HISTORY_POINTS:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_fetch": self.last_fetch,
            "flights": self.flights,
            "history": self.history,
        }
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
        return age is None or age >= FLIGHT_REFRESH_INTERVAL_SECONDS

    def refresh_if_due(self, force: bool = False) -> bool:
        if not force and not self.should_fetch():
            return False
        if not FETCH_NEW_DATA_FROM_API:
            return False
        with self.lock:
            if not force and not self.should_fetch():
                return False
            try:
                states = fetch_opensky_states()
            except FlightFetchError as error:
                self.last_error = str(error)
                return False
            self._merge(states)
            self.last_fetch = time.time()
            self.last_error = ""
            try:
                self.save()
            except OSError as error:
                self.last_error = f"Could not save flight cache: {error}"
            return True

    def _merge(self, states: list) -> None:
        current = normalize_states(states)
        current_by_icao = {flight["icao24"]: flight for flight in current}
        self.history = {
            icao: points
            for icao, points in self.history.items()
            if icao in current_by_icao
        }
        now = time.time()
        for icao, flight in current_by_icao.items():
            point = {
                "timestamp": flight.get("last_contact") or now,
                "latitude": flight["latitude"],
                "longitude": flight["longitude"],
            }
            points = self.history.setdefault(icao, [])
            if not points or distance_between_points(points[-1], point) > 0.001:
                points.append(point)
            self.history[icao] = points[-FLIGHT_HISTORY_POINTS:]
        self.flights = current

    def get_flights(self) -> list[dict]:
        with self.lock:
            return [dict(flight) for flight in self.flights]

    def get_history(self, icao24: str) -> list[dict]:
        with self.lock:
            return [dict(point) for point in self.history.get(icao24.upper(), [])]
