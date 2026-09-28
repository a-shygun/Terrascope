from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable

from around.config import CACHE_DIR
from around.layers.cities.settings import (
    FORECAST_DAYS_AHEAD,
    WEATHER_CACHE_FILENAME,
    WEATHER_REFRESH_INTERVAL_SECONDS,
    WEATHER_RETRY_INTERVAL_SECONDS,
)
from around.layers.cities.weather_api import WeatherFetchError, fetch_weather_snapshot

WEATHER_CACHE_FILE = CACHE_DIR / WEATHER_CACHE_FILENAME
MAX_CONCURRENT_WEATHER_REQUESTS = 4


def _parse_daily_forecast(daily: dict) -> list[dict]:
    """Turn Open-Meteo's daily arrays-of-values block into a list of
    per-day dicts, skipping index 0 (today, already covered by the
    'current' reading) and keeping up to FORECAST_DAYS_AHEAD entries.
    """
    dates = daily.get("time") or []
    codes = daily.get("weathercode") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    forecast = []
    for index in range(1, min(len(dates), FORECAST_DAYS_AHEAD + 1)):
        forecast.append(
            {
                "date": dates[index] if index < len(dates) else None,
                "weathercode": codes[index] if index < len(codes) else None,
                "temp_max": highs[index] if index < len(highs) else None,
                "temp_min": lows[index] if index < len(lows) else None,
            }
        )
    return forecast


class WeatherStationCache:
    """Fetches and caches a current-weather reading (plus a short forecast)
    per city, on demand.

    Nothing is fetched until a city is actually visible or selected (see
    CitiesLayer.build), and a city already fetched recently is served from
    cache instead of being re-requested on every render.

    Readings are persisted to WEATHER_CACHE_FILE, so a fresh process starts
    from the last known data instead of empty, and a failed fetch falls
    back to whatever was last successfully read (from this run or a past
    one) rather than showing nothing. A city whose last attempt errored is
    retried on the much shorter WEATHER_RETRY_INTERVAL_SECONDS cadence
    instead of the normal refresh interval.
    """

    def __init__(self, on_update: Callable[[], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = self._load_from_disk()
        self._in_progress: set[str] = set()
        self._on_update = on_update

    @staticmethod
    def _load_from_disk() -> dict[str, dict]:
        try:
            text = WEATHER_CACHE_FILE.read_text(encoding="utf-8")
        except OSError:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        clean = {}
        for key, entry in data.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            try:
                fetched_at = float(entry["fetched_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(fetched_at):
                clean[key] = {**entry, "fetched_at": fetched_at}
        return clean

    @staticmethod
    def _save_to_disk(entries: dict[str, dict]) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            temp_path = WEATHER_CACHE_FILE.with_suffix(
                WEATHER_CACHE_FILE.suffix + ".tmp"
            )
            temp_path.write_text(json.dumps(entries), encoding="utf-8")
            temp_path.replace(WEATHER_CACHE_FILE)
        except OSError:
            # Persistence is a nice-to-have; a failed write shouldn't take
            # down weather fetching.
            pass

    def get(self, city_key: str) -> dict | None:
        with self._lock:
            entry = self._entries.get(city_key)
            return dict(entry) if entry is not None else None

    def temperature_range(self) -> tuple[float, float] | None:
        """The (coldest, hottest) temperature currently known across every
        cached city -- not just the visible ones -- so the color gradient
        stays anchored to the actual coldest/hottest city we've read, and
        doesn't jump around as the map is panned. Returns None until at
        least one reading is known.
        """
        with self._lock:
            temperatures = [
                entry["temperature"]
                for entry in self._entries.values()
                if entry.get("temperature") is not None
            ]
        if not temperatures:
            return None
        return min(temperatures), max(temperatures)

    def _is_stale(self, city_key: str) -> bool:
        entry = self._entries.get(city_key)
        if entry is None:
            return True
        interval = (
            WEATHER_RETRY_INTERVAL_SECONDS
            if entry.get("error")
            else WEATHER_REFRESH_INTERVAL_SECONDS
        )
        return time.time() - entry["fetched_at"] >= interval

    def has_pending_retry(self) -> bool:
        """True if some cached city errored last time and is now due for
        another attempt. Lets the layer force a redraw so that retry
        actually gets kicked off even when nothing else is happening.
        """
        now = time.time()
        with self._lock:
            for city_key, entry in self._entries.items():
                if not entry.get("error"):
                    continue
                if city_key in self._in_progress:
                    continue
                if now - entry.get("fetched_at", 0) >= WEATHER_RETRY_INTERVAL_SECONDS:
                    return True
        return False

    def ensure_fresh(self, city_key: str, latitude: float, longitude: float) -> None:
        """Kick off a background fetch for this city if it's missing or
        stale. Returns immediately either way; check get() for the result.
        """
        with self._lock:
            if city_key in self._in_progress:
                return
            if len(self._in_progress) >= MAX_CONCURRENT_WEATHER_REQUESTS:
                return
            if not self._is_stale(city_key):
                return
            self._in_progress.add(city_key)
        thread = threading.Thread(
            target=self._fetch_worker,
            args=(city_key, latitude, longitude),
            daemon=True,
        )
        thread.start()

    def _fetch_worker(self, city_key: str, latitude: float, longitude: float) -> None:
        try:
            error = ""
            current = None
            daily: dict = {}
            try:
                snapshot = fetch_weather_snapshot(latitude, longitude)
                current = snapshot["current"]
                daily = snapshot["daily"]
            except WeatherFetchError as fetch_error:
                error = str(fetch_error)
            with self._lock:
                previous = self._entries.get(city_key, {})
                self._entries[city_key] = {
                    "temperature": (
                        current.get("temperature")
                        if current
                        else previous.get("temperature")
                    ),
                    "windspeed": (
                        current.get("windspeed")
                        if current
                        else previous.get("windspeed")
                    ),
                    "winddirection": (
                        current.get("winddirection")
                        if current
                        else previous.get("winddirection")
                    ),
                    "weathercode": (
                        current.get("weathercode")
                        if current
                        else previous.get("weathercode")
                    ),
                    "observed_at": (
                        current.get("time")
                        if current
                        else previous.get("observed_at")
                    ),
                    "forecast": (
                        _parse_daily_forecast(daily)
                        if daily
                        else previous.get("forecast", [])
                    ),
                    "fetched_at": time.time(),
                    "error": error,
                }
                snapshot_to_save = dict(self._entries)
            self._save_to_disk(snapshot_to_save)
            if self._on_update is not None:
                self._on_update()
        finally:
            with self._lock:
                self._in_progress.discard(city_key)
