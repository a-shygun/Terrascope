# world.py — MAP STATE AND FRAME BUILDING
# Responsible for: the WorldMap class — zoom level, map centre, panning/zooming/
# reset, drawing country outlines and the land mask into a Frame, asking each
# layer to render, and the selection / search / filter state shared by layers.
# Edit this file to: change how zoom/pan behave, how the base map is rasterised,
# or how selection, search and filtering are coordinated across layers.
# Not here: screen drawing (ui.py), key handling (app.py), per-layer data.

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import ImageDraw

from around.config import MAP_CONFIG
from around.core.layer import Layer, LayerRender
from around.core.mapdata import Ring
from around.core.projection import calculate_viewport, clamp_center, visible
from around.core.view import View


@dataclass
class Frame:
    country_lines: list[str]
    layers: list[LayerRender]
    lon_span: float
    render_width: int
    background_cache: object = None  # filled in by ui.py (per-cell background colours)
    land_cover: object = None  # np.ndarray[float] (rows, cols), 0 = water .. 1 = land


class WorldMap:
    def __init__(self, countries: list[Ring], layers: list[Layer]) -> None:
        self.countries = countries
        self.layers = layers
        self.zoom = MAP_CONFIG["min_zoom"]
        self.center_lon = 0.0
        self.center_lat = 0.0
        self.dirty = True
        self.search_text = ""
        self.filter_value: str | None = None
        self._selection_candidates: list[tuple[Layer, object]] = []
        self._selection_index = 0

    @property
    def countries(self) -> list[Ring]:
        return self._countries

    @countries.setter
    def countries(self, value: list[Ring]) -> None:
        # Convert every ring to a NumPy array once, so render() can project a
        # whole ring in one vectorised step instead of point by point.
        self._countries = value
        self._ring_points = [np.asarray(ring[0], dtype=np.float64) for ring in value]

    @property
    def selected_layer(self) -> Layer | None:
        if self._selection_candidates:
            return self._selection_candidates[self._selection_index][0]
        for layer in self.layers:
            if layer.enabled and layer.selected is not None:
                return layer
        return None

    @property
    def selection_position(self) -> tuple[int, int]:
        if not self._selection_candidates:
            return 0, 0
        return self._selection_index + 1, len(self._selection_candidates)

    def cycle_selection(self, direction: int) -> None:
        if len(self._selection_candidates) < 2:
            return
        self._selection_index = (
            self._selection_index + direction
        ) % len(self._selection_candidates)
        self._activate_selection()

    def _activate_selection(self) -> None:
        for layer in self.layers:
            layer.select(None)
        if self._selection_candidates:
            layer, item = self._selection_candidates[self._selection_index]
            layer.select(item)
        self.dirty = True

    def active_layers(self) -> list[Layer]:
        return [layer for layer in self.layers if layer.enabled]

    def needs_render(self) -> bool:
        return self.dirty or any(layer.dirty for layer in self.layers)

    def shown_count(self) -> int:
        return sum(layer.shown_count() for layer in self.active_layers())

    def filter_options(self) -> list[str]:
        options: set[str] = set()
        for layer in self.active_layers():
            options.update(layer.filter_options())
        return sorted(options)

    def render(self, width: int, height: int) -> Frame:
        view = View(self.center_lon, self.center_lat, self.zoom, width, height)
        country_image = view.new_image()
        land_mask = view.new_image()

        draw = ImageDraw.Draw(country_image)
        land_draw = ImageDraw.Draw(land_mask)
        origin_lon = view.origin_lon
        origin_lat = view.origin_lat
        scale_x = view.scale_x
        scale_y = view.scale_y
        for polygon, points in zip(self._countries, self._ring_points):
            if len(points) < 2:
                continue
            shifts = visible(
                polygon, view.center_lon, view.center_lat, view.lon_span, view.lat_span
            )
            if not shifts:
                continue
            y = np.rint((origin_lat - points[:, 1]) * scale_y).astype(np.int64)
            for shift in shifts:
                x = np.rint((points[:, 0] + shift - origin_lon) * scale_x).astype(
                    np.int64
                )
                coords = np.empty(len(points) * 2, dtype=np.int64)
                coords[0::2] = x
                coords[1::2] = y
                flat = coords.tolist()
                draw.line(flat, fill=255, width=1)
                land_draw.polygon(flat, fill=255)

        # Keep daylight stipple inside land rather than painting over the
        # country outlines, which remain visible in the base map layer.
        land_cover = view.to_cell_coverage(land_mask)
        land_mask.paste(0, mask=country_image)

        country_lines = view.to_lines(country_image)
        layer_renders = []
        for layer in self.layers:
            if layer.enabled:
                layer_renders.append(layer.render_with_land(view, land_mask))
            else:
                layer.dirty = False
        self.dirty = False
        return Frame(
            country_lines,
            layer_renders,
            view.lon_span,
            width,
            land_cover=land_cover,
        )

    def select_at(self, x: int, y: int) -> None:
        candidates = []
        for layer in self.active_layers():
            candidates.extend(
                (distance, layer, item)
                for distance, item in layer.hit_test_all(x, y)
            )
        candidates.sort(key=lambda candidate: candidate[0])
        self._selection_candidates = [
            (layer, item) for _, layer, item in candidates
        ]
        self._selection_index = 0
        self._activate_selection()

    def clear_selection(self) -> None:
        self._selection_candidates = []
        self._selection_index = 0
        for layer in self.layers:
            layer.select(None)
        self.dirty = True

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

    def pan(self, lon_direction: int, lat_direction: int) -> None:
        lon_span, lat_span = calculate_viewport(self.zoom)
        self.center_lon += lon_direction * lon_span * MAP_CONFIG["pan_step"]
        self.center_lat += lat_direction * lat_span * MAP_CONFIG["pan_step"]
        self.center_lon, self.center_lat = clamp_center(
            self.center_lon, self.center_lat, lon_span, lat_span
        )
        self.dirty = True

    def zoom_in(self) -> None:
        self.zoom = min(self.zoom * MAP_CONFIG["zoom_step"], MAP_CONFIG["max_zoom"])
        self.dirty = True

    def zoom_out(self) -> None:
        self.zoom = max(self.zoom / MAP_CONFIG["zoom_step"], MAP_CONFIG["min_zoom"])
        self.dirty = True

    def reset_view(self) -> None:
        self.zoom = MAP_CONFIG["min_zoom"]
        self.center_lon = 0.0
        self.center_lat = 0.0
        self.clear_selection()
