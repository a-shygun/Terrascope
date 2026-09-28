from __future__ import annotations

import time

from around.config import FETCH_NEW_DATA_FROM_API
from around.core.layer import Layer, LayerRender, Marker, SidebarLine
from around.core.view import View
from around.layers.cities.settings import (
    CITY_CAPITAL_ZOOM,
    CITY_CONFIG,
    CITY_DATA,
    CITY_MAJOR_ZOOM,
    FORECAST_DAYS_AHEAD,
)
from around.layers.cities.weather_api import describe_weather_code, temperature_to_color
from around.layers.cities.weather_cache import WeatherStationCache


class CitiesLayer(Layer):
    name = "cities"
    toggle_key = "c"
    order = 20
    info_title = "CITY INFO"
    enabled = CITY_CONFIG["enabled"]

    def __init__(self) -> None:
        super().__init__()
        self.weather = WeatherStationCache(on_update=self._weather_updated)
        self._last_retry_scan = 0.0

    def _weather_updated(self) -> None:
        # The cache fetch runs off-thread; dirty is consumed by the UI loop.
        self.dirty = True

    def tick(self) -> None:
        super().tick()
        if not self.enabled:
            return
        now = time.time()
        # Checking every second is cheap; it's just a dict scan over
        # already-cached entries, no network calls of its own.
        if now - self._last_retry_scan < 1.0:
            return
        self._last_retry_scan = now
        if self.weather.has_pending_retry():
            # Nothing else may have changed (no pan/zoom/click), so force a
            # redraw -- build() is what actually calls ensure_fresh() for
            # each visible city.
            self.dirty = True

    def visible_cities(self, view: View) -> list[tuple]:
        result = []
        for city in CITY_DATA:
            _, _, _, is_capital = city[:4]
            if is_capital and view.zoom < CITY_CAPITAL_ZOOM:
                continue
            if not is_capital and view.zoom < CITY_MAJOR_ZOOM:
                continue
            result.append(city)
        return result

    def shown_count(self) -> int:
        # Visibility depends on zoom, which is only known at build() time, so
        # this reports the count from the most recent render.
        return len(self.last_markers)

    def legend_lines(self) -> list[SidebarLine]:
        return [
            SidebarLine(
                "CITY TEMP",
                legend_items=(
                    ("●", " cold", CITY_CONFIG["temperature_cold_color"]),
                    ("●", " hot", CITY_CONFIG["temperature_hot_color"]),
                    ("●", " no data", CITY_CONFIG["color"]),
                ),
            )
        ]

    def build(self, view: View) -> LayerRender:
        selected_name = self.selected["name"] if self.selected is not None else None
        visible = self.visible_cities(view)
        for name, latitude, longitude, is_capital, country, population, area in visible:
            # Every visible city keeps its own reading warm in the
            # background; ensure_fresh is a cheap no-op once a city is
            # cached and not yet stale, so this doesn't re-fetch on every
            # frame.
            if FETCH_NEW_DATA_FROM_API:
                self.weather.ensure_fresh(name, latitude, longitude)

        # Colors are relative to the coldest/hottest city we have a
        # reading for across the whole cache (not just what's on screen
        # right now), so the gradient doesn't jump around while panning.
        temperature_range = self.weather.temperature_range()

        markers = []
        for name, latitude, longitude, is_capital, country, population, area in visible:
            cell = view.to_cell(longitude, latitude)
            if cell is None:
                continue
            reading = self.weather.get(name)
            temperature = reading.get("temperature") if reading else None
            color = CITY_CONFIG["color"]
            if temperature_range is not None:
                cold_c, hot_c = temperature_range
                color = (
                    temperature_to_color(temperature, cold_c, hot_c)
                    or CITY_CONFIG["color"]
                )
            markers.append(
                Marker(
                    x=cell[0],
                    y=cell[1],
                    color=color,
                    label=f"\u2022 {name}",
                    item={
                        "name": name,
                        "latitude": latitude,
                        "longitude": longitude,
                        "capital": is_capital,
                        "country": country,
                        "population": population,
                        "area_km2": area,
                    },
                    selected=selected_name is not None and name == selected_name,
                )
            )
        return LayerRender(None, CITY_CONFIG["color"], markers)

    def info_rows(self) -> list[tuple[str, str]]:
        city = self.selected
        rows = [
            ("NAME", city["name"]),
            ("COUNTRY", city["country"]),
            ("TYPE", "CAPITAL" if city["capital"] else "MAJOR CITY"),
            ("POPULATION", f"{city['population']:,}"),
            ("AREA", f"{city['area_km2']:,} km\u00b2"),
            ("POSITION", f"{city['latitude']:.3f}, {city['longitude']:.3f}"),
        ]
        rows.extend(self._weather_rows(city["name"]))
        return rows

    def _weather_rows(self, city_name: str) -> list[tuple[str, str]]:
        reading = self.weather.get(city_name)
        if reading is None:
            return [("WEATHER", "FETCHING...")]
        if reading.get("temperature") is None:
            message = reading.get("error") or "UNAVAILABLE"
            return [("WEATHER", message.upper()[:24])]
        rows = [
            ("TEMP", f"{reading['temperature']:.1f}\u00b0C"),
            ("CONDITIONS", describe_weather_code(reading.get("weathercode"))),
            ("WIND", f"{reading['windspeed']:.0f} km/h @ {reading['winddirection']:.0f}\u00b0"),
            ("OBSERVED", str(reading.get("observed_at") or "N/A")),
        ]
        rows.extend(self._forecast_rows(reading))
        return rows

    def _forecast_rows(self, reading: dict) -> list[tuple[str, str]]:
        forecast = reading.get("forecast") or []
        rows = []
        for day in forecast[:FORECAST_DAYS_AHEAD]:
            date = day.get("date")
            label = date[5:] if date else "?"
            temp_max = day.get("temp_max")
            temp_min = day.get("temp_min")
            if temp_max is None or temp_min is None:
                temps = "N/A"
            else:
                temps = f"{temp_min:.0f}-{temp_max:.0f}\u00b0C"
            condition = describe_weather_code(day.get("weathercode"))
            rows.append((label, f"{temps} {condition}"))
        return rows
