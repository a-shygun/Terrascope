# world.py — MAP STATE AND FRAME BUILDING
# Responsible for: the WorldMap class — zoom level, map centre, panning/zooming/
# reset, drawing country outlines and the land mask into a Frame, asking each
# layer to render, and the selection / search / filter state shared by layers.
# Edit this file to: change how zoom/pan behave, how the base map is rasterised,
# or how selection, search and filtering are coordinated across layers.
# Not here: screen drawing (ui.py), key handling (app.py), per-layer data.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import numpy as np
from PIL import ImageDraw
from terrascope.core.config import CFG
from terrascope.core.layer import Layer, LayerRender
from terrascope.core.mapdata import Ring
from terrascope.core.view import WRAP_SHIFTS, View, calculate_viewport, clamp_center, visible

ZOOM_CONFIG = CFG["map"]["zoom"]
ZOOM_MIN = ZOOM_CONFIG["min"]  # fully zoomed out = whole world (also the starting zoom)
ZOOM_MAX = ZOOM_CONFIG["max"]
ZOOM_STEP = ZOOM_CONFIG["step"]  # zoom multiplier per key press
PROVINCE_ZOOM_MIN = ZOOM_CONFIG["province_min"]  # state / province borders appear from this zoom on
PAN_STEP = ZOOM_CONFIG["pan_step"]  # fraction of the visible span moved per key press

START_LON, START_LAT = clamp_center(0.0, 0.0, *calculate_viewport(ZOOM_MIN))

RingPoints = tuple[Ring, np.ndarray]

@dataclass
class Frame:
    country_lines: list[str]
    layers: list[LayerRender]
    lon_span: float
    render_width: int
    background_cache: Any = None  # filled in by ui.py (per-cell background colours)
    land_cover: Any = None  # np.ndarray[float] (rows, cols), 0 = water .. 1 = land
    province_lines: list[str] | None = None  # braille rows, None = not drawn at this zoom

def _rings_with_points(rings: list[Ring]) -> list[RingPoints]:
    """Convert every ring to a NumPy array once so render() can project a
    whole ring in one vectorised step. Rings too short to draw are dropped
    here, not re-checked every frame. Shared by the countries and provinces
    setters below."""
    return [
        (ring, points)
        for ring in rings
        if len(points := np.asarray(ring[0], dtype=np.float64)) >= 2
    ]

def prepare_ring_set(rings: list[Ring]):
    """Build render arrays and spatial boxes away from the curses UI thread."""
    items = _rings_with_points(rings)
    boxes = np.array([ring[1:5] for ring, _ in items], dtype=np.float64).reshape(-1, 4)
    return rings, items, boxes

def _draw_rings(
    rings: list[RingPoints],
    view: View,
    outline: ImageDraw.ImageDraw,
    fill: ImageDraw.ImageDraw | None = None,
) -> None:
    """Project each ring (and every antimeridian-wrapped copy of it that's
    visible) into pixel space and draw its outline, optionally also filling it
    as a solid polygon (used for the land mask). Shared by the country-border
    and province-border passes of render(), which differ only in whether they
    fill."""
    for ring, points in rings:
        shifts = visible(
            ring, view.center_lon, view.center_lat, view.lon_span, view.lat_span
        )
        if not shifts:
            continue
        # One reusable (n, 2) buffer: y is constant across wrap-terrascope
        # shifts, only x changes, and ravel() gives PIL its flat x,y,x,y list.
        xy = np.empty((len(points), 2), dtype=np.int64)
        xy[:, 1] = np.rint((view.origin_lat - points[:, 1]) * view.scale_y)
        for shift in shifts:
            xy[:, 0] = np.rint((points[:, 0] + shift - view.origin_lon) * view.scale_x)
            flat = xy.ravel().tolist()
            outline.line(flat, fill=255, width=1)
            if fill is not None:
                fill.polygon(flat, fill=255)

def _visible_rings(tier, view: View) -> list[RingPoints]:
    """Rings whose bounding box touches the view."""
    items, boxes = tier
    if not items:
        return []
    view_min_lon = view.center_lon - view.lon_span / 2
    view_max_lon = view.center_lon + view.lon_span / 2
    view_min_lat = view.center_lat - view.lat_span / 2
    view_max_lat = view.center_lat + view.lat_span / 2
    keep = (boxes[:, 3] >= view_min_lat) & (boxes[:, 2] <= view_max_lat)
    in_lon = np.zeros(len(items), dtype=bool)
    for shift in WRAP_SHIFTS:
        in_lon |= (boxes[:, 1] + shift >= view_min_lon) & (boxes[:, 0] + shift <= view_max_lon)
    return [items[index] for index in np.nonzero(keep & in_lon)[0].tolist()]

class WorldMap:
    def __init__(self, countries: list[Ring], layers: list[Layer]) -> None:
        self.countries = countries
        self.provinces = []
        self.province_resolution = "10M"
        self._province_tier = ([], np.empty((0, 4), dtype=np.float64))
        self.detailed = True  # set from the active tab (see tabs.py)
        self.show_provinces = False  # opt-in state / province borders
        self.show_places = True  # likewise: basemap capital / city names
        self.show_countries = True  # likewise: basemap country names
        self.layers = layers
        self.zoom = ZOOM_MIN
        self.center_lon = START_LON
        self.center_lat = START_LAT
        self.dirty = True
        self.aspect = 2.0  # updated from the real window size in render()
        self.search_text = ""
        self.filter_value: str | None = None
        self._selection_candidates: list[tuple[Layer, object]] = []
        self._selection_index = 0

    @property
    def countries(self) -> list[Ring]:
        return self._countries

    @countries.setter
    def countries(self, value: list[Ring]) -> None:
        self._countries = value
        self._rings = _rings_with_points(value)
        boxes = np.array([ring[1:5] for ring, _ in self._rings], dtype=np.float64).reshape(-1, 4)
        self._country_tier = (self._rings, boxes)

    def set_prepared_countries(self, prepared) -> None:
        self._countries, self._rings, boxes = prepared
        self._country_tier = (self._rings, boxes)

    @property
    def provinces(self) -> list[Ring]:
        return self._provinces

    @provinces.setter
    def provinces(self, value: list[Ring]) -> None:
        self._provinces = value
        self._province_rings = _rings_with_points(value)
        boxes = np.array([ring[1:5] for ring, _ in self._province_rings], dtype=np.float64).reshape(-1, 4)
        self._province_tier = (self._province_rings, boxes)

    def set_prepared_provinces(self, prepared) -> None:
        self.set_prepared_provinces_at_resolution(prepared, "10M")

    def set_prepared_provinces_at_resolution(self, prepared, resolution: str) -> None:
        self._provinces, self._province_rings, boxes = prepared
        self._province_tier = (self._province_rings, boxes)
        self.province_resolution = resolution

    # ---- selection -------------------------------------------------------

    @property
    def selected_layer(self) -> Layer | None:
        if self._selection_candidates:
            return self._selection_candidates[self._selection_index][0]
        return next(
            (l for l in self.layers if l.enabled and l.selected is not None), None
        )

    @property
    def selection_position(self) -> tuple[int, int]:
        count = len(self._selection_candidates)
        return (self._selection_index + 1, count) if count else (0, 0)

    def cycle_selection(self, direction: int) -> None:
        count = len(self._selection_candidates)
        if count < 2:
            return
        self._selection_index = (self._selection_index + direction) % count
        self._activate_selection()

    def _activate_selection(self) -> None:
        for layer in self.layers:
            layer.select(None)
        if self._selection_candidates:
            layer, item = self._selection_candidates[self._selection_index]
            layer.select(item)
        self.dirty = True

    def select_at(self, x: int, y: int) -> None:
        # A layer may claim the click first (basemap: country code <-> full name).
        for layer in self.active_layers():
            if layer.click_at(x, y):
                self.clear_selection()
                return
        hits = sorted(
            (
                (distance, layer, item)
                for layer in self.active_layers()
                for distance, item in layer.hit_test_all(x, y)
            ),
            key=lambda hit: hit[0],
        )
        self._selection_candidates = [(layer, item) for _, layer, item in hits]
        self._selection_index = 0
        self._activate_selection()

    def clear_selection(self) -> None:
        self._selection_candidates = []
        self._selection_index = 0
        for layer in self.layers:
            layer.select(None)
        self.dirty = True

    # ---- layers, search, filter -------------------------------------------

    def active_layers(self) -> list[Layer]:
        return [layer for layer in self.layers if layer.enabled]

    def slider_layer(self) -> Layer | None:
        return next((l for l in self.active_layers() if l.slider() is not None), None)

    def needs_render(self) -> bool:
        return self.dirty or any(layer.dirty for layer in self.layers)

    def filter_options(self) -> list[str]:
        return sorted(
            {option for layer in self.active_layers() for option in layer.filter_options()}
        )

    def set_search(self, text: str) -> None:
        self.search_text = text
        for layer in self.layers:
            layer.apply_search(text)
        self.clear_selection()

    def set_filter(self, value: str | None) -> None:
        self.filter_value = value
        for layer in self.layers:
            layer.apply_filter(value)
        self.clear_selection()

    def clear_filters(self) -> None:
        self.search_text = ""
        self.filter_value = None
        for layer in self.layers:
            layer.apply_search("")
            layer.apply_filter(None)
        self.clear_selection()

    # ---- view: pan / zoom / reset -----------------------------------------

    def _clamp_center(self) -> None:
        self.center_lon, self.center_lat = clamp_center(
            self.center_lon,
            self.center_lat,
            *calculate_viewport(self.zoom, self.aspect),
        )

    def pan(self, lon_direction: int, lat_direction: int) -> None:
        lon_span, lat_span = calculate_viewport(self.zoom, self.aspect)
        self.center_lon += lon_direction * lon_span * PAN_STEP
        self.center_lat += lat_direction * lat_span * PAN_STEP
        self._clamp_center()
        self.dirty = True

    def pan_cells(self, dx: int, dy: int, cols: int, rows: int) -> None:
        """Drag the map: move its content by (dx, dy) terminal cells. Dragging
        right/down shows what lies to the left/above, like grabbing the map."""
        if cols <= 0 or rows <= 0:
            return
        lon_span, lat_span = calculate_viewport(self.zoom, self.aspect)
        self.center_lon -= dx * lon_span / cols
        self.center_lat += dy * lat_span / rows
        self._clamp_center()
        self.dirty = True

    def zoom_at(self, direction: int, col: int, row: int, cols: int, rows: int) -> None:
        """Zoom in (direction > 0) or out terrascope the map cell (col, row), so
        the spot under the mouse pointer stays where it is."""
        if cols <= 0 or rows <= 0:
            return
        old_lon_span, old_lat_span = calculate_viewport(self.zoom, self.aspect)
        fx = (col + 0.5) / cols
        fy = (row + 0.5) / rows
        lon = self.center_lon - old_lon_span / 2 + fx * old_lon_span
        lat = self.center_lat + old_lat_span / 2 - fy * old_lat_span
        old_zoom = self.zoom
        self._set_zoom(self.zoom * ZOOM_STEP if direction > 0 else self.zoom / ZOOM_STEP)
        if self.zoom == old_zoom:
            return
        lon_span, lat_span = calculate_viewport(self.zoom, self.aspect)
        self.center_lon = lon - (fx - 0.5) * lon_span
        self.center_lat = lat + (fy - 0.5) * lat_span
        self._clamp_center()
        self.dirty = True

    def _set_zoom(self, zoom: float) -> None:
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        if zoom != self.zoom:
            self.zoom = zoom
            self._clamp_center()  # a wider view can push the old centre out of range
            self.dirty = True

    def zoom_in(self) -> None:
        self._set_zoom(self.zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        self._set_zoom(self.zoom / ZOOM_STEP)

    def reset_view(self) -> None:
        self.zoom = ZOOM_MIN
        self.center_lon = START_LON
        self.center_lat = START_LAT
        self.clear_selection()

    # ---- frame building ---------------------------------------------------

    def render(self, width: int, height: int) -> Frame:
        view = View(self.center_lon, self.center_lat, self.zoom, width, height)
        self.aspect = view.aspect
        country_image = view.new_image()
        land_mask = view.new_image()
        outline_draw = ImageDraw.Draw(country_image)
        land_draw = ImageDraw.Draw(land_mask)
        _draw_rings(_visible_rings(self._country_tier, view), view, outline_draw, fill=land_draw)

        # State / province borders, only once zoomed in far enough. Country
        # border pixels are cut out so the country line always wins.
        province_lines = None
        visible_provinces = []
        if self.show_provinces and self._province_rings and self.zoom >= PROVINCE_ZOOM_MIN:
            visible_provinces = _visible_rings(self._province_tier, view)
        if visible_provinces:
            province_image = view.new_image()
            province_draw = ImageDraw.Draw(province_image)
            _draw_rings(visible_provinces, view, province_draw)
            province_image.paste(0, mask=country_image)
            province_lines = view.to_lines(province_image)

        # Keep daylight stipple inside land rather than painting over the
        # country outlines, which remain visible in the base map layer.
        land_cover = view.to_cell_coverage(land_mask)
        land_mask.paste(0, mask=country_image)

        renders = []
        for layer in self.layers:
            layer.detailed = self.detailed
            layer.show_places = self.show_places
            layer.show_countries = self.show_countries
            if not layer.enabled:
                layer.dirty = False
                continue
            extra = (country_image,) if layer.wants_country_image else ()
            renders.append(layer.render_with_land(view, land_mask, *extra))
        self.dirty = False

        return Frame(
            country_lines=view.to_lines(country_image),
            layers=renders,
            lon_span=view.lon_span,
            render_width=width,
            land_cover=land_cover,
            province_lines=province_lines,
        )
