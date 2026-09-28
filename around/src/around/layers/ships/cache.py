from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

from around.config import FETCH_NEW_DATA_FROM_API
from around.layers.ships.api import ShipFetchError, fetch_ship_locations
from around.layers.ships.settings import (
    SHIP_CACHE_FILE,
    SHIP_MAX_AGE_SECONDS,
    SHIP_REFRESH_INTERVAL_SECONDS,
)


def _normalize_cached(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            longitude = float(item["longitude"])
            latitude = float(item["latitude"])
            timestamp = float(item["timestamp"])
            mmsi = str(item["mmsi"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not mmsi.isdigit()
            or not math.isfinite(longitude)
            or not math.isfinite(latitude)
            or not math.isfinite(timestamp)
            or not (-180 <= longitude <= 180 and -90 <= latitude <= 90)
        ):
            continue
        normalized.append(
            {
                **item,
                "longitude": longitude,
                "latitude": latitude,
                "timestamp": timestamp,
            }
        )
    return normalized


class ShipCache:
    def __init__(self, path: Path = SHIP_CACHE_FILE) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.last_fetch: float | None = None
        self.ships: list[dict] = []
        self.last_error = ""
        self.load()

    def load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        try:
            last_fetch = float(payload["last_fetch"])
            if math.isfinite(last_fetch):
                self.last_fetch = last_fetch
        except (KeyError, TypeError, ValueError):
            pass
        self.ships = _normalize_cached(payload.get("ships"))

    def should_fetch(self) -> bool:
        if not FETCH_NEW_DATA_FROM_API:
            return False
        return (
            self.last_fetch is None
            or time.time() - self.last_fetch >= SHIP_REFRESH_INTERVAL_SECONDS
        )

    def refresh_if_due(self) -> bool:
        if not self.should_fetch():
            return False
        with self.lock:
            if not self.should_fetch():
                return False
            try:
                ships = fetch_ship_locations()
            except ShipFetchError as error:
                self.last_error = str(error)
                return False
            self.ships = ships
            self.last_fetch = time.time()
            self.last_error = ""
            try:
                self.save()
            except OSError as error:
                self.last_error = f"Could not save ship cache: {error}"
            return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps({"last_fetch": self.last_fetch, "ships": self.ships}),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def get_ships(self) -> list[dict]:
        with self.lock:
            cutoff = time.time() - SHIP_MAX_AGE_SECONDS
            return [dict(ship) for ship in self.ships if ship["timestamp"] >= cutoff]
