# basemap_layer.py — PLACE NAME LABELS ON THE MAP
# Responsible for: the "basemap" layer. The coastlines, country outlines and
# state / province borders are drawn by the core map (world.py); this layer
# only adds place name labels: country names, national capitals and cities.
# The names come from Natural Earth (the same source, download and cache as
# the borders, see mapdata.py), so there is no live API call: they are
# downloaded once, then read from disk.
# What shows depends on the zoom:
#   * world view: country names, plus capitals wherever there is room;
#   * zooming in: ever smaller cities (see CITY_LEVELS), biggest first;
#   * zoomed far in: country names are dropped so the cities take over.
# Every label is placed highest priority first (countries, then capitals, then
# cities by population) and only drawn if it doesn't collide with one already
# placed, so a crowded view thins itself out instead of piling labels up.
# Edit this file to: change which places show at which zoom, the label colours,
# or the label spacing.

from __future__ import annotations

import sys
import threading
import time
from terrascope.core.config import CFG
from terrascope.core.layer import Layer, LayerRender, Marker, SidebarLine
from terrascope.core.mapdata import (
    MapDataError,
    load_country_labels,
    load_places,
)
from terrascope.core.ui import hex_to_rgb
from terrascope.core.view import View

# --- what shows at which zoom (all from default.yaml, layers: basemap:) -------
BASEMAP_CONFIG = CFG["layers"]["basemap"]
COUNTRY_MAX_ZOOM = float(BASEMAP_CONFIG["country_max_zoom"])  # country names show up to this zoom, then give way to cities
CAPITAL_MIN_ZOOM = float(BASEMAP_CONFIG["capital_min_zoom"])  # national capitals show from this zoom (room permitting)
# (min_zoom, min_population): from min_zoom on, non-capital cities with at least
# this many people are candidates. Below the first row no cities are shown.
CITY_LEVELS: tuple[tuple[float, int], ...] = tuple(
    (float(zoom), int(population)) for zoom, population in BASEMAP_CONFIG["city_levels"]
)

# Outside the MAP tab only capitals and cities at least this big are labelled.
MAJOR_CITY_MIN_POPULATION = int(BASEMAP_CONFIG["major_city_min_population"])
COUNTRY_CLICK_EXPANDS = bool(BASEMAP_CONFIG["country_click_expands"])  # click a country code: full name <-> code

# --- label look ------------------------------------------------------------
COUNTRY_COLOR = BASEMAP_CONFIG["country_color"]
CAPITAL_COLOR = BASEMAP_CONFIG["capital_color"]
# (min_population, colour) checked top down, for non-capital cities.
CITY_COLORS: tuple[tuple[int, str], ...] = tuple(
    (int(population), str(color)) for population, color in BASEMAP_CONFIG["city_colors"]
)

# Label-collision placement (the "only if there is space" rule).
LABEL_PADDING = int(BASEMAP_CONFIG["label_padding"])  # blank columns required between two labels on the same row
MAX_PLACED_LABELS = int(BASEMAP_CONFIG["max_labels"])  # hard safety cap regardless of available space

LOAD_RETRY_SECONDS = BASEMAP_CONFIG["load_retry_seconds"]  # wait this long after a failed load before trying again
LOADING_TEXT = "loading place names..."
UNAVAILABLE_TEXT = "place names unavailable"

def population_floor(zoom: float) -> int | None:
    """Smallest city population shown at this zoom (None = no cities yet)."""
    floor = None
    for min_zoom, population in CITY_LEVELS:
        if zoom >= min_zoom:
            floor = population
    return floor

def city_color(population: int) -> str:
    for minimum, color in CITY_COLORS:
        if population >= minimum:
            return color
    return CITY_COLORS[-1][1]

def _short_population(population: int) -> str:
    if population >= 1_000_000:
        return f"{population / 1_000_000:g}M"
    return f"{population // 1000}K"

def _dimmed(color: str, factor: float = 0.6) -> str:
    """The colour a dimmed line is roughly drawn in (province borders)."""
    return "#{:02x}{:02x}{:02x}".format(*(round(c * factor) for c in hex_to_rgb(color)))

def _map_key_lines() -> list[SidebarLine]:
    """Key of the MAP tab: border and place colours, in the same
    right-aligned "NAME ■" style as the TIME tab's legend."""
    map_config = CFG["map"]
    country = map_config["country_color"]
    province = map_config.get("province_color") or _dimmed(country)
    lines = [
        SidebarLine("COUNTRY BORDER", swatches=(country,)),
        SidebarLine("PROVINCE", swatches=(province,)),
        SidebarLine("CAPITAL", swatches=(CAPITAL_COLOR,)),
    ]
    previous = None
    for population, color in CITY_COLORS:  # biggest first
        if population > 0:
            label = f"CITY {_short_population(population)}+"
        else:
            label = f"CITY <{_short_population(previous)}" if previous else "CITY"
        previous = population
        lines.append(SidebarLine(label, swatches=(color,)))
    return lines

class BaseMapLayer(Layer):
    name = "basemap"
    toggle_key = ""  # switched on by the tabs, no hotkey of its own
    enabled = True

    def __init__(self) -> None:
        super().__init__()
        # Every list is sorted most important first.
        self._countries: list[tuple[float, float, str, str]] = []  # lon, lat, short code, full name
        self._expanded: set[str] = set()  # full names of countries shown in full
        self._country_hits: list[tuple[int, int, int, str]] = []  # (x0, x1, row, full name) of clickable labels
        self._capitals: list[tuple[float, float, str]] = []
        self._cities: list[tuple[float, float, str, int]] = []  # + population
        self._pending = None
        self._pending_detail = None
        self._state = "idle"  # idle | loading | ready | failed
        self._load_retry_at = 0.0
        self.provinces_visible = False
        self.provinces_ready = False

    # ---- loading (off the UI thread) ------------------------------------------

    def _start_loading(self) -> None:
        self._state = "loading"
        threading.Thread(target=self._load, name="terrascope-places", daemon=True).start()

    def _load(self) -> None:
        try:
            labels = load_country_labels()
            places = load_places()
        except (MapDataError, OSError, ValueError) as error:
            # stderr is redirected to terrascope.log while the app runs.
            print(f"place names: {error}", file=sys.stderr)
            self._state = "failed"
            self._load_retry_at = time.monotonic() + LOAD_RETRY_SECONDS
            self.dirty = True
            return
        initial = self._prepare_places(labels, places)
        with self.lock:
            self._pending = initial
        # The configured 50m country and place datasets load once. Higher
        # resolution place data is only fetched from the welcome modal.

    @staticmethod
    def _prepare_places(labels, places):
        countries = [
            (lon, lat, code, full)
            for lon, lat, code, _size, full in sorted(labels, key=lambda label: label[3], reverse=True)
        ]
        by_population = sorted(places, key=lambda place: place[4], reverse=True)
        capitals = [(lon, lat, name) for lon, lat, name, is_capital, *_ in by_population if is_capital]
        cities = [
            (lon, lat, name, population)
            for lon, lat, name, is_capital, population, *_ in by_population
            if not is_capital
        ]
        return countries, capitals, cities

    def set_prepared_detail(self, places) -> None:
        with self.lock:
            self._pending_detail = places
        self.dirty = True

    def tick(self) -> None:
        super().tick()
        with self.lock:
            pending, self._pending = self._pending, None
            pending_detail, self._pending_detail = self._pending_detail, None
        if pending is not None:
            self._countries, self._capitals, self._cities = pending  # swap in on the UI thread
            self._state = "ready"
            self.dirty = True
        if pending_detail is not None:
            self._countries, self._capitals, self._cities = pending_detail
            self.dirty = True
        if self._state == "idle" or (
            self._state == "failed" and time.monotonic() >= self._load_retry_at
        ):
            self._start_loading()

    def loading_messages(self) -> list[str]:
        messages = []
        if self._state == "loading":
            messages.append("LOADING PLACE NAMES")
        return messages

    # ---- labels -----------------------------------------------------------------

    def _candidates(self, zoom: float):
        """(lon, lat, text, colour, centred, country) in priority order for this
        zoom. `country` is the full name for clickable country labels, else None.
        Countries the user expanded come first, so they always get room."""
        if self.show_countries and zoom <= COUNTRY_MAX_ZOOM:
            for lon, lat, code, full in self._countries:
                if full in self._expanded:
                    yield lon, lat, full, COUNTRY_COLOR, True, full
            for lon, lat, code, full in self._countries:
                if full not in self._expanded:
                    yield lon, lat, code, COUNTRY_COLOR, True, full
        if self.show_places and zoom >= CAPITAL_MIN_ZOOM:
            for lon, lat, name in self._capitals:
                yield lon, lat, name, CAPITAL_COLOR, False, None
        floor = population_floor(zoom) if self.show_places else None
        if floor is not None and not self.detailed:
            floor = max(floor, MAJOR_CITY_MIN_POPULATION)
        if floor is not None:
            for lon, lat, name, population in self._cities:
                if population < floor:
                    break  # sorted biggest first: nothing smaller qualifies
                yield lon, lat, name, city_color(population), False, None

    def _place_markers(self, view: View) -> list[Marker]:
        """Walk the candidates highest priority first and keep each label that
        fits on screen and doesn't collide (within LABEL_PADDING columns, or on
        the row above / below) with one already placed. This is what keeps the
        world view to a few names instead of every city at once."""
        occupied: dict[int, list[tuple[int, int]]] = {}
        placed_names: set[str] = set()
        markers: list[Marker] = []
        hits: list[tuple[int, int, int, str]] = []
        for lon, lat, name, color, centred, country in self._candidates(view.zoom):
            if len(markers) >= MAX_PLACED_LABELS:
                break
            if name in placed_names:  # e.g. "Singapore" the country and the city
                continue
            cell = view.to_cell(lon, lat)
            if cell is None:
                continue
            x, y = cell
            if centred:
                x = max(0, x - len(name) // 2)
                if country in self._expanded and x + len(name) > view.width:
                    x = max(0, view.width - len(name))  # an expanded name slides in rather than vanishing
            if x + len(name) > view.width:
                continue  # would be cut off at the edge of the map
            start, end = x - LABEL_PADDING, x + len(name) + LABEL_PADDING
            collision = False
            for row in (y - 1, y, y + 1):
                for seg_start, seg_end in occupied.get(row, ()):
                    if start < seg_end and seg_start < end:
                        collision = True
                        break
                if collision:
                    break
            if collision:
                continue
            occupied.setdefault(y, []).append((x, x + len(name)))
            placed_names.add(name)
            markers.append(Marker(x=x, y=y, color=color, label=name))
            if country is not None:
                hits.append((x, x + len(name), y, country))
        self._country_hits = hits
        return markers

    # ---- Layer interface ----------------------------------------------------------

    def hit_test_all(self, x: int, y: int, radius: float | None = None):
        return []  # labels are never selected as markers (see click_at)

    def click_at(self, x: int, y: int) -> bool:
        """Clicking a country label toggles code <-> full name."""
        if not COUNTRY_CLICK_EXPANDS:
            return False
        for x0, x1, row, country in self._country_hits:
            if row == y and x0 <= x < x1:
                self._expanded.symmetric_difference_update({country})
                self.dirty = True
                return True
        return False

    def build(self, view: View) -> LayerRender:
        return LayerRender(None, "#000000", markers=self._place_markers(view))

    def legend_lines(self) -> list[SidebarLine]:
        lines = []
        if self.detailed and self.provinces_ready:
            lines.append(SidebarLine(
                "PROVINCES",
                choices=("ON", "OFF"),
                choice_index=0 if self.provinces_visible else 1,
                action="provinces",
            ))
        if self.detailed:
            lines += [line for line in _map_key_lines() if self.provinces_ready or line.text != "PROVINCE"]
        if self._state == "loading":
            lines.append(SidebarLine(LOADING_TEXT))
        elif self._state == "failed":
            lines.append(SidebarLine(UNAVAILABLE_TEXT))
        return lines
