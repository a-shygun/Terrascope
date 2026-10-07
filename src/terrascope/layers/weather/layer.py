"""Weather tab layer: city weather, radar overlay, and earthquakes."""

from __future__ import annotations

import math
import sys
import textwrap
import threading
import time
import numpy as np
from terrascope.core.config import FETCH_NEW_DATA_FROM_API
from terrascope.core.layer import CLICK_RADIUS, Layer, LayerRender, Marker, PanelBox, SidebarLine, SliderSpec
from terrascope.core.mapdata import MapDataError, load_places
from terrascope.core.ui.constants import INFO_BOX_LABEL_WIDTH
from terrascope.core.view import View
from terrascope.layers.weather.city_weather import (
    WeatherStationCache,
    describe_weather_code,
    temperature_to_color,
)
from terrascope.layers.weather.config import (
    ANIMATE,
    CAPITAL_ALL_ZOOM,
    CAPITAL_MIN_POPULATION,
    CITY_CAPITAL_ZOOM,
    CITY_CONFIG,
    CITY_LABEL_PADDING,
    FORECAST_DAYS_AHEAD,
    HALF_BLOCK_LOWER,
    HALF_BLOCK_UPPER,
    INTENSITY_MAX,
    INTENSITY_MIN,
    LEGEND_COLD,
    LEGEND_GLYPH,
    LEGEND_HOT,
    LEGEND_NO_DATA,
    MARKER_PREFIX,
    MAX_WEATHER_CITIES,
    PLACES_LOADING_TEXT,
    PLACES_RETRY_SECONDS,
    PLACES_UNAVAILABLE_TEXT,
    RADAR_ENABLED,
    RADAR_LOADING_TEXT,
    RADAR_MODE,
    WEATHER_CONFIG,
    WEATHER_SCHEMA,
    _CITY_LABELS,
    _CITY_TEXT,
    _RADAR_LABELS,
)
from terrascope.layers.weather.earthquakes import (
    EarthquakeCache,
    FILTER_OPTIONS,
    LEGEND_LABELS,
    MAGNITUDE_COLOR_BANDS,
    MAGNITUDE_COLOR_MAJOR,
    MIN_MAGNITUDE,
    QUAKE_DIM_AFTER_SECONDS,
    EARTHQUAKE_CONFIG,
    _QUAKE_LABELS,
    _QUAKE_TEXT,
    format_depth,
    format_magnitude,
    format_time_ago,
    format_tsunami,
    magnitude_to_color,
    magnitude_to_glyph,
)
from terrascope.layers.weather.forecast import (
    FORECAST_ROWS,
    VERTICAL_DAY_SEPARATOR_ROWS,
    city_key,
    city_population_floor,
    forecast_lines,
    forecast_vertical_lines,
    forecast_vertical_placeholder,
    forecast_placeholder,
    item_kind,
    weather_icon,
)
from terrascope.layers.weather.radar import (
    RADAR_LEVEL_COLORS,
    RadarStore,
    _LEVEL_COUNT,
    sample_raster,
)

# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------

class WeatherLayer(Layer):
    name = "weather"
    toggle_key = ""  # the tab switches the layer on; C and E (below) switch its two parts
    enabled = WEATHER_CONFIG["enabled"]
    # Bottom row: [info of the selected city / quake | multi-day forecast]
    panel_layout = (
        PanelBox("info", WEATHER_CONFIG["panel_ratios"][0]),
        PanelBox("rich", WEATHER_CONFIG["panel_ratios"][1], "FORECAST"),
    )

    def __init__(self) -> None:
        super().__init__()
        # -- cities, with the radar / cloud overlay drawn underneath them
        self.show_cities = bool(CITY_CONFIG["enabled"])
        self.weather = WeatherStationCache(on_update=self._weather_updated)
        self._last_retry_scan = 0.0
        self.radar = RadarStore(RADAR_MODE, on_update=self._weather_updated)
        self._ordered_startup = True
        self._startup_weather_ready = False
        self._startup_complete = False
        self._radar_index = 0
        self._radar_last_step = 0.0
        self._radar_pin: float | None = None  # frame time held by the slider (None = follow live)
        # Natural Earth places, biggest first (loaded off the UI thread).
        self._capitals: list[tuple] = []
        self._cities: list[tuple] = []
        self._places_pending = None
        self._places_state = "idle"  # idle | loading | ready | failed
        self._places_retry_at = 0.0
        # -- earthquakes
        self.show_quakes = bool(EARTHQUAKE_CONFIG["enabled"])
        self.quake_cache = EarthquakeCache()
        self.quakes: list[dict] = []
        self.search_text = ""
        self.min_magnitude_filter: str | None = None

    def _weather_updated(self) -> None:
        # Fetches run off-thread; dirty is consumed by the UI loop.
        self.dirty = True

    def prefetch(self) -> None:
        """Warm weather feeds and place data during launch, independent of tab."""
        if not self._ordered_startup and self.show_cities and self._places_state == "idle":
            self._start_loading_places()
        if not self._ordered_startup and RADAR_ENABLED and FETCH_NEW_DATA_FROM_API:
            self.radar.ensure_fresh()
        if self.show_quakes and FETCH_NEW_DATA_FROM_API:
            with self.lock:
                self.refresh_in_progress = True
            threading.Thread(target=self._prefetch_quakes, name="terrascope-quakes", daemon=True).start()

    def _prefetch_quakes(self) -> None:
        try:
            self.quake_cache.refresh_if_due(force=True)
            with self.lock:
                self.refresh_completed = True
        finally:
            with self.lock:
                self.refresh_in_progress = False
            self.dirty = True

    # ---- the two parts' keys -------------------------------------------------

    def handle_key(self, key: int) -> bool:
        if not 0 <= key < 256:
            return False
        char = chr(key).lower()
        if char == str(CITY_CONFIG["toggle_key"]).lower():
            self.show_cities = not self.show_cities
        elif char == str(EARTHQUAKE_CONFIG["toggle_key"]).lower():
            self.show_quakes = not self.show_quakes
        else:
            return False
        self.dirty = True
        return True

    # ---- selection / info box title -------------------------------------------

    def _selected_kind(self) -> str:
        return item_kind(self.selected) if self.selected is not None else "city"

    @property
    def info_title(self) -> str:
        return "EARTHQUAKE INFO" if self._selected_kind() == "quake" else "CITY INFO"

    def panel_layout_for(self, available_height: int, panel_width: int) -> tuple[PanelBox, ...]:
        """Size the left info box to its wrapped content; give the rest to forecast."""
        rows = self.info_rows()
        value_width = max(1, panel_width - INFO_BOX_LABEL_WIDTH - 5)
        content_height = sum(
            len(textwrap.wrap(str(value), width=value_width, break_long_words=True,
                              break_on_hyphens=False) or [""])
            for _label, value in rows
        )
        # Two border rows plus one blank row below the final value.
        info_height = min(max(3, content_height + 3), max(3, available_height - 3))
        ratio = info_height / max(1, available_height)
        return (
            PanelBox("info", ratio),
            PanelBox("rich", 1.0 - ratio, "FORECAST"),
        )

    # ---- clicking and the forecast box ---------------------------------------------

    def rich_title(self, title: str | None) -> str:
        title = title or ""
        if self.selected is not None and self._selected_kind() == "city":
            return f"{title} \u00b7 {self.selected['name']}".strip()
        return title

    def rich_lines(
        self, title: str | None, width: int, height: int,
        vertical: bool = False, scroll: int = 0,
    ) -> list[list]:
        """The FORECAST box: the selected city's next days, or a how-to / key."""
        if self.selected is None or self._selected_kind() != "city":
            if vertical:
                return forecast_vertical_placeholder(width, height)
            return forecast_placeholder()
        reading = self.weather.get(self.selected["key"])
        if reading is None:
            return [[(_CITY_TEXT["fetching"], None, "dim")]]
        days = [day for day in reading.get("forecast") or [] if isinstance(day, dict)]
        if reading.get("schema") != WEATHER_SCHEMA or not days:
            return [[("FORECAST UNAVAILABLE", None, "dim")]]
        if vertical:
            return forecast_vertical_lines(days, width, height, scroll)
        return forecast_lines(days, width)

    def forecast_line_count(self) -> int:
        """Number of stacked detail rows available for the selected city."""
        if self.selected is None or self._selected_kind() != "city":
            return 0
        reading = self.weather.get(self.selected["key"])
        days = reading.get("forecast") or [] if reading else []
        day_count = sum(isinstance(day, dict) for day in days)
        return day_count * FORECAST_ROWS + max(0, day_count - 1) * VERTICAL_DAY_SEPARATOR_ROWS

    # ---- data refresh (earthquakes; weather and radar fetch themselves) --------

    def is_due(self) -> bool:
        return self.show_quakes and self.quake_cache.should_fetch()

    def refresh_if_due(self, force: bool = False) -> bool:
        if not self.enabled or not self.show_quakes:
            return False
        return self.quake_cache.refresh_if_due(force)

    def reload(self) -> None:
        quakes = self.quake_cache.get_quakes() if self.enabled else []
        self.quakes = quakes
        if self.selected is not None and self._selected_kind() == "quake":
            selected_id = self.selected.get("id")
            self.selected = None
            if selected_id:
                for quake in quakes:
                    if quake.get("id") == selected_id:
                        self.selected = quake
                        break
        self.dirty = True

    def clear(self) -> None:
        self.quakes = []
        self.selected = None
        self.dirty = True

    def tick(self) -> None:
        super().tick()
        if not self.enabled or not self.show_cities:
            return
        self._poll_places()
        now = time.time()
        self._radar_tick(now)
        # Checking every second is cheap; it's just a dict scan over
        # already-cached entries, no network calls of its own.
        if now - self._last_retry_scan < 1.0:
            return
        self._last_retry_scan = now
        if self.weather.has_pending_retry():
            # Nothing else may have changed (no pan/zoom/click), so force a
            # redraw -- build() is what actually calls ensure_fresh().
            self.dirty = True

    # ---- loading the city list ---------------------------------------------------

    def _start_loading_places(self) -> None:
        self._places_state = "loading"
        threading.Thread(target=self._load_places, name="terrascope-weather-cities", daemon=True).start()

    def _load_places(self) -> None:
        try:
            places = load_places()
        except (MapDataError, OSError, ValueError) as error:
            # stderr is redirected to terrascope.log while the app runs.
            print(f"weather cities: {error}", file=sys.stderr)
            self._places_state = "failed"
            self._places_retry_at = time.monotonic() + PLACES_RETRY_SECONDS
            self.dirty = True
            return
        by_population = sorted(places, key=lambda place: place[4], reverse=True)
        capitals = [place for place in by_population if place[3]]
        cities = [place for place in by_population if not place[3]]
        with self.lock:
            self._places_pending = (capitals, cities)
        # Fetch currently useful city readings in the background as soon as the
        # 50m place list is ready, even while another tab is selected.
        for lon, lat, name, is_capital, population, country in by_population[:MAX_WEATHER_CITIES]:
            self.weather.ensure_fresh(city_key(name, lat, lon), lat, lon)

    def _poll_places(self) -> None:
        with self.lock:
            pending, self._places_pending = self._places_pending, None
        if pending is not None:
            self._capitals, self._cities = pending  # swap in on the UI thread
            self._places_state = "ready"
            self.dirty = True
        if not self._ordered_startup and (self._places_state == "idle" or (
            self._places_state == "failed" and time.monotonic() >= self._places_retry_at
        )):
            self._start_loading_places()

    def set_prepared_places_detail(self, places) -> None:
        with self.lock:
            self._places_pending = places

    def loading_messages(self) -> list[str]:
        messages = []
        if self._places_state == "loading":
            messages.append("LOADING WEATHER PLACES")
        elif self._places_state == "failed":
            messages.append("CITY LIST UNAVAILABLE · RETRYING")
        weather_loading = self.weather.loading_count()
        if weather_loading:
            messages.append("UPDATING CITY WEATHER")
        elif self.weather.failed_count():
            messages.append("WEATHER UNAVAILABLE · RETRYING")
        if self.radar.loading():
            messages.append("LOADING RADAR")
        elif self.radar.failed():
            messages.append("RADAR UNAVAILABLE · RETRYING")
        if self.refresh_in_progress:
            messages.append("LOADING EARTHQUAKES")
        return messages

    def hit_test_all(self, x: int, y: int, radius: float | None = None):
        """Select cities anywhere along their drawn label, not just at its dot."""
        if radius is None:
            radius = CLICK_RADIUS
        hits = []
        for marker in self.last_markers:
            item = marker.item
            if item is None or (isinstance(item, dict) and item.get("radar")):
                continue
            span = len(marker.label) if marker.label else 1
            dx = max(marker.x - x, 0, x - (marker.x + span - 1))
            distance = math.hypot(dx, marker.y - y)
            if distance <= radius:
                hits.append((distance, item))
        return sorted(hits, key=lambda hit: hit[0])

    def _city_label(
        self, key: str, name: str, selected: bool
    ) -> tuple[str, tuple[str, str] | None]:
        """(label text, (icon glyph, icon colour) or None). The selected city,
        once its weather is known, shows its conditions icon and temperature in
        place of the plain dot."""
        if selected:
            reading = self.weather.get(key)
            if reading and reading.get("temperature") is not None:
                icon = weather_icon(reading.get("weathercode"))
                return f"{icon[0]} {name} {reading['temperature']:.0f}\u00b0C", icon
        return f"{MARKER_PREFIX}{name}", None

    def _place_cities(
        self, view: View
    ) -> list[tuple[dict, tuple[int, int], str, tuple[str, str] | None]]:
        """(city, (x, y) cell, label, icon) for the cities to label in this view:
        the selected city first (so it always gets room), then capitals, then
        bigger cities, each kept only if its label fits on screen and doesn't
        collide with one already placed. At most MAX_WEATHER_CITIES."""
        zoom = view.zoom
        floor = city_population_floor(zoom)
        selected = (
            self.selected
            if self.selected is not None and self._selected_kind() == "city"
            else None
        )
        selected_key = selected.get("key") if selected is not None else None

        def candidates():
            if selected is not None:
                yield (
                    selected["longitude"], selected["latitude"], selected["name"],
                    selected["capital"], selected["population"], selected["country"],
                )
            if zoom >= CITY_CAPITAL_ZOOM:
                for place in self._capitals:  # sorted biggest first
                    if zoom < CAPITAL_ALL_ZOOM and place[4] < CAPITAL_MIN_POPULATION:
                        break
                    yield place
            if floor is not None:
                for place in self._cities:
                    if place[4] < floor:
                        break  # sorted biggest first: nothing smaller qualifies
                    yield place

        occupied: dict[int, list[tuple[int, int]]] = {}
        placed: list = []
        names: set[str] = set()
        for longitude, latitude, name, is_capital, population, country in candidates():
            if len(placed) >= MAX_WEATHER_CITIES:
                break
            if name in names:
                continue
            cell = view.to_cell(longitude, latitude)
            if cell is None:
                continue
            x, y = cell
            key = city_key(name, latitude, longitude)
            label, icon = self._city_label(key, name, key == selected_key)
            width = len(label)
            if x + width > view.width:
                if key != selected_key:
                    continue  # would be cut off at the edge of the map
                x = max(0, view.width - width)  # the selected city slides in rather than vanishing
                cell = (x, y)
            start, end = x - CITY_LABEL_PADDING, x + width + CITY_LABEL_PADDING
            if any(
                start < seg_end and seg_start < end
                for row in (y - 1, y, y + 1)
                for seg_start, seg_end in occupied.get(row, ())
            ):
                continue
            occupied.setdefault(y, []).append((x, x + width))
            names.add(name)
            placed.append(
                (
                    {
                        "key": key,
                        "name": name,
                        "latitude": latitude,
                        "longitude": longitude,
                        "capital": is_capital,
                        "country": country,
                        "population": population,
                    },
                    cell,
                    label,
                    icon,
                )
            )
        return placed

    # -- radar overlay -------------------------------------------------------

    @staticmethod
    def _radar_live_index(frames) -> int:
        """Index of the newest observed frame ("live"); frames after it are forecast."""
        for index in range(len(frames) - 1, -1, -1):
            if not frames[index][0]["nowcast"]:
                return index
        return len(frames) - 1

    def _radar_shown_index(self, frames) -> int:
        if self._radar_pin is not None:
            return min(range(len(frames)), key=lambda i: abs(frames[i][0]["time"] - self._radar_pin))
        if self.radar.cached_fallback():
            return self._radar_live_index(frames)
        if ANIMATE:
            return min(self._radar_index, len(frames) - 1)
        return self._radar_live_index(frames)

    def _radar_tick(self, now: float) -> None:
        if not (RADAR_ENABLED and FETCH_NEW_DATA_FROM_API):
            return
        # Startup owns the initial radar schedule so its present frame can load
        # before city weather and historical radar frames.
        if not ANIMATE or self._radar_pin is not None:
            return  # static: only moves when new data arrives or the slider is used
        count = len(self.radar.loaded_frames())
        if count < 2:
            return
        newest = self._radar_index >= count - 1
        hold = FRAME_HOLD_LAST_SECONDS if newest else FRAME_SECONDS
        if now - self._radar_last_step >= hold:
            self._radar_index = 0 if newest else self._radar_index + 1
            self._radar_last_step = now
            self.dirty = True

    def _radar_current(self):
        frames = self.radar.loaded_frames()
        if not frames:
            return None
        return frames[self._radar_shown_index(frames)]

    # ---- time slider (same widget as the planes layer) -------------------------

    def slider(self) -> SliderSpec | None:
        """Steps through radar frames in the catalog, oldest to newest.

        The range comes from the catalog, not from what has downloaded so far,
        so it does not grow while frames are still arriving; a step whose frame
        is not loaded yet shows the nearest loaded one.
        """
        if not (self.enabled and RADAR_ENABLED):
            return None
        catalog = self.radar.catalog_frames()
        loaded_frames = self.radar.loaded_frames()
        using_cache = self.radar.cached_fallback()
        if not catalog and loaded_frames:
            catalog = [frame for frame, _raster in loaded_frames]
        if len(catalog) < 2:
            if using_cache and loaded_frames:
                frame = max(
                    (item for item, _raster in loaded_frames if not item["nowcast"]),
                    key=lambda item: item["time"],
                    default=loaded_frames[-1][0],
                )
                age = self._radar_age_caption(frame["time"])
                return SliderSpec(
                    "RAINVIEWER", 2, 0, age, status="CACHED",
                    loaded_steps=(0,), disabled=True,
                )
            status = "RADAR UNAVAILABLE" if self.radar.failed() else RADAR_LOADING_TEXT
            return SliderSpec("RAINVIEWER", 2, 0, "LIVE", status=status, disabled=True)
        live = self._catalog_live_index(catalog)
        live_time = catalog[live]["time"]
        index = self._catalog_shown_index(catalog)
        if using_cache and loaded_frames:
            shown = loaded_frames[self._radar_shown_index(loaded_frames)][0]
            caption = self._radar_age_caption(shown["time"])
            status = "CACHED"
        else:
            minutes = round((catalog[index]["time"] - live_time) / 60)
            caption = "LIVE" if minutes == 0 else f"{minutes:+d}m"
        if not using_cache and self.radar.failed():
            status = "RADAR UNAVAILABLE"
        elif not using_cache and not loaded_frames:
            status = RADAR_LOADING_TEXT
        elif not using_cache and len(loaded_frames) < len(catalog):
            status = "LOADING RADAR"
        elif not using_cache:
            status = ""
        loaded_times = {frame["time"] for frame, _raster in loaded_frames}
        loaded_steps = tuple(
            index for index, frame in enumerate(catalog)
            if frame["time"] in loaded_times
        )
        return SliderSpec(
            "RAINVIEWER", len(catalog), index, caption, marker=live, wide=True,
            status=status, loaded_steps=loaded_steps,
        )

    @staticmethod
    def _radar_age_caption(timestamp: int) -> str:
        """Compact age label for a cached radar frame, sized for the slider."""
        minutes = max(0, int((time.time() - timestamp) // 60))
        if minutes < 60:
            return f"{minutes}m AGO"
        hours, minute = divmod(minutes, 60)
        if hours < 24:
            return f"{hours}h{minute:02d}m AGO"
        days = hours // 24
        return f"{days}d AGO"

    @staticmethod
    def _catalog_live_index(catalog: list[dict]) -> int:
        for index in range(len(catalog) - 1, -1, -1):
            if not catalog[index]["nowcast"]:
                return index
        return len(catalog) - 1

    def _catalog_shown_index(self, catalog: list[dict]) -> int:
        if self._radar_pin is not None:
            target = self._radar_pin
        else:
            current = self._radar_current()
            if current is None:
                return self._catalog_live_index(catalog)
            target = current[0]["time"]
        return min(range(len(catalog)), key=lambda i: abs(catalog[i]["time"] - target))

    def set_slider(self, index: int) -> None:
        catalog = self.radar.catalog_frames()
        if not catalog:
            return
        index = max(0, min(len(catalog) - 1, index))
        # Pin by frame time, so the held frame stays put when the catalogue refreshes.
        self._radar_pin = None if index == self._catalog_live_index(catalog) else catalog[index]["time"]
        frames = self.radar.loaded_frames()
        if frames:
            target = catalog[index]["time"]
            self._radar_index = min(range(len(frames)), key=lambda i: abs(frames[i][0]["time"] - target))
        self.dirty = True

    def radar_markers(self, view: View, blocked: set[tuple]) -> list[Marker]:
        """Coloured cells for the shown frame. Each terminal cell has a top and a
        bottom half-reading (see sample_raster), quantised to a few levels:
          * both halves the same level  -> one solid cell (a space on a coloured
            background: a single curses colour pair per level);
          * different levels            -> a half block, top colour as foreground,
            bottom colour as background;
          * only one half has rain      -> that half block over the map's own colour.
        `blocked` holds terminal cells used by city labels, which stay free."""
        current = self._radar_current()
        if current is None:
            return []
        frame, raster = current
        values = sample_raster(raster, view)
        span = float(INTENSITY_MAX - INTENSITY_MIN)
        levels = np.where(
            values >= INTENSITY_MIN,
            np.clip(((values - INTENSITY_MIN) / span * _LEVEL_COUNT).astype(int), 0, _LEVEL_COUNT - 1) + 1,
            0,
        )
        top_levels = levels[0::2]
        bottom_levels = levels[1::2]
        shown = (top_levels > 0) | (bottom_levels > 0)
        for x, y in blocked:
            if 0 <= x < view.width and 0 <= y < view.height:
                shown[y, x] = False

        markers = []
        rows, cols = np.nonzero(shown)
        for y, x in zip(rows.tolist(), cols.tolist()):
            top = int(top_levels[y, x])
            bottom = int(bottom_levels[y, x])
            # Radar pixels are an overlay, not clickable observations. Keeping
            # a full metadata dict on every colored terminal cell made weather
            # tab redraws allocate thousands of short-lived objects.
            if top and bottom:
                if top == bottom:
                    color = RADAR_LEVEL_COLORS[top - 1]
                    markers.append(Marker(x=x, y=y, color=color, bg_color=color, label=" "))
                else:
                    markers.append(
                        Marker(
                            x=x, y=y,
                            color=RADAR_LEVEL_COLORS[top - 1],
                            bg_color=RADAR_LEVEL_COLORS[bottom - 1],
                            label=HALF_BLOCK_UPPER,
                        )
                    )
            elif top:
                markers.append(Marker(x=x, y=y, color=RADAR_LEVEL_COLORS[top - 1], label=HALF_BLOCK_UPPER))
            else:
                markers.append(Marker(x=x, y=y, color=RADAR_LEVEL_COLORS[bottom - 1], label=HALF_BLOCK_LOWER))
        return markers

    # ---- search / filter (earthquakes) ----------------------------------------------

    def visible_quakes(self) -> list[dict]:
        quakes = [
            quake
            for quake in self.quakes
            if quake.get("magnitude") is None or quake["magnitude"] >= MIN_MAGNITUDE
        ]
        if self.min_magnitude_filter:
            threshold = float(self.min_magnitude_filter.rstrip("+"))
            quakes = [
                quake
                for quake in quakes
                if quake.get("magnitude") is not None and quake["magnitude"] >= threshold
            ]
        if self.search_text:
            needle = self.search_text.strip().lower()
            quakes = [quake for quake in quakes if needle in quake.get("place", "").lower()]
        return quakes

    def apply_search(self, text: str) -> None:
        self.search_text = text
        self.dirty = True

    def apply_filter(self, value: str | None) -> None:
        self.min_magnitude_filter = value if value in FILTER_OPTIONS else None
        self.dirty = True

    def filter_options(self) -> list[str]:
        return list(FILTER_OPTIONS) if self.show_quakes else []

    # ---- legend -----------------------------------------------------------------------

    def legend_lines(self) -> list[SidebarLine]:
        """Vertical legend: a heading per group, then one "NAME ●" line per
        entry, the dots right-aligned in one column."""

        def entry(label: str, color: str) -> SidebarLine:
            return SidebarLine(label.strip().upper(), swatches=(color,), swatch_glyph=LEGEND_GLYPH)

        lines: list[SidebarLine] = []
        if self.show_cities:
            lines += [
                entry(LEGEND_COLD, CITY_CONFIG["temperature_cold_color"]),
                entry(LEGEND_HOT, CITY_CONFIG["temperature_hot_color"]),
                entry(LEGEND_NO_DATA, CITY_CONFIG["color"]),
            ]
            if self._places_state == "loading":
                lines.append(SidebarLine(PLACES_LOADING_TEXT))
            elif self._places_state == "failed":
                lines.append(SidebarLine(PLACES_UNAVAILABLE_TEXT))
        if self.show_quakes:
            colors = [color for _, color in MAGNITUDE_COLOR_BANDS]
            colors.append(MAGNITUDE_COLOR_MAJOR)
            lines += [entry(label, color) for label, color in zip(LEGEND_LABELS, colors)]
        return lines

    # ---- drawing ------------------------------------------------------------------------

    def build(self, view: View) -> LayerRender:
        markers: list[Marker] = []
        if self.show_cities:
            markers.extend(self._city_markers(view))
        lines = None
        if self.show_quakes:
            lines, quake_markers = self._quake_render(view)
            markers.extend(quake_markers)  # quakes are drawn on top of the cities
        return LayerRender(lines, "#000000", markers)

    def _city_markers(self, view: View) -> list[Marker]:
        placed = self._place_cities(view)
        if FETCH_NEW_DATA_FROM_API and self._startup_weather_ready:
            # Every labelled city keeps its own reading warm in the background;
            # ensure_fresh is a cheap no-op once a city is cached and not stale.
            for city, _, _, _ in placed:
                self.weather.ensure_fresh(city["key"], city["latitude"], city["longitude"])
            if RADAR_ENABLED and self._startup_complete:
                self.radar.ensure_fresh()

        # Colors are relative to the coldest/hottest city we have a reading for
        # across the whole cache (not just what's on screen right now), so the
        # gradient doesn't jump terrascope while panning.
        temperature_range = self.weather.temperature_range()
        selected_key = None
        if self.selected is not None and self._selected_kind() == "city":
            selected_key = self.selected.get("key")

        city_markers = []
        for city, (x, y), label, icon in placed:
            reading = self.weather.get(city["key"])
            temperature = reading.get("temperature") if reading else None
            color = CITY_CONFIG["color"]
            if temperature_range is not None:
                cold_c, hot_c = temperature_range
                color = temperature_to_color(temperature, cold_c, hot_c) or CITY_CONFIG["color"]
            is_selected = selected_key is not None and city["key"] == selected_key
            city_markers.append(
                Marker(x=x, y=y, color=color, label=label, item=city, selected=is_selected)
            )
            if icon is not None:
                # The icon is drawn over the label's first character in its own colour.
                city_markers.append(
                    Marker(x=x, y=y, color=icon[1], label=icon[0], selected=is_selected)
                )
        # Radar goes first (drawn underneath); city markers last so their
        # labels sit on top. Cells under a city label are left empty.
        markers: list[Marker] = []
        if RADAR_ENABLED:
            blocked = {(m.x + dx, m.y) for m in city_markers for dx in range(len(m.label))}
            markers.extend(self.radar_markers(view, blocked))
        markers.extend(city_markers)
        return markers

    def _quake_render(self, view: View) -> tuple[None, list[Marker]]:
        """One glyph per quake (no extra braille dots): size by magnitude, colour
        by magnitude band, faded when old. Sorted weakest first, so where quakes
        share a cell the strongest is the one drawn on top."""
        selected_id = None
        if self.selected is not None and self._selected_kind() == "quake":
            selected_id = self.selected.get("id")
        now = time.time()
        ranked: list[tuple[float, Marker]] = []
        for quake in self.visible_quakes():
            cell = view.to_cell(quake["longitude"], quake["latitude"])
            if cell is None:
                continue
            magnitude = quake.get("magnitude")
            try:
                age = now - float(quake["time"]) / 1000.0
            except (KeyError, TypeError, ValueError):
                age = 0.0
            ranked.append(
                (
                    -1.0 if magnitude is None else magnitude,
                    Marker(
                        x=cell[0],
                        y=cell[1],
                        color=magnitude_to_color(magnitude),
                        glyph=magnitude_to_glyph(magnitude),
                        item=quake,
                        selected=selected_id is not None and quake.get("id") == selected_id,
                        dim=age > QUAKE_DIM_AFTER_SECONDS,
                    ),
                )
            )
        ranked.sort(key=lambda pair: pair[0])
        return None, [marker for _, marker in ranked]

    # ---- info box -------------------------------------------------------------------------

    def info_rows(self) -> list[tuple[str, str]]:
        item = self.selected
        if item is None:
            return []
        kind = self._selected_kind()
        if kind == "radar":
            return self._radar_info_rows(item)
        if kind == "quake":
            return self._quake_info_rows(item)
        rows = [
            (_CITY_LABELS["name"], item["name"]),
            (_CITY_LABELS["country"], item.get("country") or _CITY_TEXT["not_available"]),
            (_CITY_LABELS["type"], _CITY_TEXT["capital"] if item["capital"] else _CITY_TEXT["city"]),
            (_CITY_LABELS["population"], f"{item['population']:,}"),
            (_CITY_LABELS["position"], f"{item['latitude']:.3f}, {item['longitude']:.3f}"),
        ]
        rows.extend(self._weather_rows(item["key"]))
        return rows

    def _quake_info_rows(self, quake: dict) -> list[tuple[str, str]]:
        unknown = _QUAKE_TEXT["unknown"]
        na = _QUAKE_TEXT["not_available"]
        return [
            (_QUAKE_LABELS["magnitude"], format_magnitude(quake.get("magnitude"))),
            (_QUAKE_LABELS["place"], quake.get("place") or unknown),
            (_QUAKE_LABELS["depth"], format_depth(quake.get("depth_km"))),
            (_QUAKE_LABELS["time"], format_time_ago(quake.get("time"))),
            (_QUAKE_LABELS["tsunami"], format_tsunami(quake.get("tsunami"))),
            (_QUAKE_LABELS["alert"], (quake.get("alert") or na).upper()),
            (_QUAKE_LABELS["status"], (quake.get("status") or na).upper()),
            (_QUAKE_LABELS["position"], f"{quake['latitude']:.3f}, {quake['longitude']:.3f}"),
        ]

    def _radar_info_rows(self, cell: dict) -> list[tuple[str, str]]:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime(cell["time"]))
        return [
            ("SOURCE", "RAINVIEWER.COM"),
            (_RADAR_LABELS["name"], cell["name"]),
            (_RADAR_LABELS["kind"], cell["kind"]),
            (_RADAR_LABELS["intensity"], f"{cell['intensity'] * 100:.0f}%"),
            (_RADAR_LABELS["position"], f"{cell['latitude']:.2f}, {cell['longitude']:.2f}"),
            (_RADAR_LABELS["frame"], stamp),
        ]

    def _weather_rows(self, city_name: str) -> list[tuple[str, str]]:
        reading = self.weather.get(city_name)
        if reading is None:
            return [(_CITY_LABELS["weather"], _CITY_TEXT["fetching"])]
        if reading.get("temperature") is None:
            return [(_CITY_LABELS["weather"], "UNAVAILABLE")]
        rows = [
            (_CITY_LABELS["temperature"], f"{reading['temperature']:.1f}\u00b0C"),
            (_CITY_LABELS["conditions"], describe_weather_code(reading.get("weathercode"))),
            (_CITY_LABELS["wind"], f"{reading['windspeed']:.0f} km/h @ {reading['winddirection']:.0f}\u00b0"),
            (_CITY_LABELS["observed"], str(reading.get("observed_at") or _CITY_TEXT["not_available"])),
        ]
        return rows
