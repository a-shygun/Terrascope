from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

from around.config import FETCH_NEW_DATA_FROM_API
from around.layers.earthquakes.api import (
    EarthquakeFetchError,
    fetch_usgs_earthquakes,
    normalize_features,
)
from around.layers.earthquakes.settings import (
    EARTHQUAKE_CACHE_FILE,
    EARTHQUAKE_REFRESH_INTERVAL_SECONDS,
)


def normalize_cached(quakes) -> list[dict]:
    if not isinstance(quakes, list):
        return []
    result = []
    for quake in quakes:
        if not isinstance(quake, dict):
            continue
        try:
            longitude = float(quake["longitude"])
            latitude = float(quake["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(longitude) and math.isfinite(latitude)):
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        item = dict(quake)
        item["longitude"] = longitude
        item["latitude"] = latitude
        result.append(item)
    return result


class EarthquakeCache:
    def __init__(self, path: Path = EARTHQUAKE_CACHE_FILE) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.last_fetch: float | None = None
        self.quakes: list[dict] = []
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
        self.quakes = normalize_cached(data.get("quakes", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_fetch": self.last_fetch, "quakes": self.quakes}
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
        return age is None or age >= EARTHQUAKE_REFRESH_INTERVAL_SECONDS

    def refresh_if_due(self, force: bool = False) -> bool:
        if not force and not self.should_fetch():
            return False
        if not FETCH_NEW_DATA_FROM_API:
            return False
        with self.lock:
            if not force and not self.should_fetch():
                return False
            try:
                features = fetch_usgs_earthquakes()
            except EarthquakeFetchError as error:
                self.last_error = str(error)
                return False
            self.quakes = normalize_features(features)
            self.last_fetch = time.time()
            self.last_error = ""
            try:
                self.save()
            except OSError as error:
                self.last_error = f"Could not save earthquake cache: {error}"
            return True

    def get_quakes(self) -> list[dict]:
        with self.lock:
            return [dict(quake) for quake in self.quakes]
