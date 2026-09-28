from __future__ import annotations

from PIL import ImageDraw

from around.config import FETCH_NEW_DATA_FROM_API
from around.core.layer import Layer, LayerRender, Marker, SidebarLine
from around.core.projection import WRAP_SHIFTS
from around.core.view import View
from around.layers.earthquakes.cache import EarthquakeCache
from around.layers.earthquakes.format import (
    format_depth,
    format_magnitude,
    format_time_ago,
    format_tsunami,
    magnitude_to_color,
    magnitude_to_glyph,
)
from around.layers.earthquakes.settings import (
    EARTHQUAKE_CONFIG,
    MAGNITUDE_COLOR_BANDS,
    MAGNITUDE_COLOR_MAJOR,
)


class EarthquakesLayer(Layer):
    name = "earthquakes"
    toggle_key = "e"
    order = 20
    info_title = "EARTHQUAKE INFO"
    enabled = EARTHQUAKE_CONFIG["enabled"]

    def __init__(self) -> None:
        super().__init__()
        self.cache = EarthquakeCache()
        self.quakes: list[dict] = []
        self.search_text = ""
        self.min_magnitude_filter: str | None = None

    def is_due(self) -> bool:
        return self.cache.should_fetch()

    def refresh_if_due(self, force: bool = False) -> bool:
        if not self.enabled:
            return False
        return self.cache.refresh_if_due(force)

    def reload(self) -> None:
        quakes = self.cache.get_quakes() if self.enabled else []
        selected_id = self.selected.get("id") if self.selected is not None else None
        self.quakes = quakes
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

    def visible_quakes(self) -> list[dict]:
        quakes = [
            quake
            for quake in self.quakes
            if quake.get("magnitude") is None
            or quake["magnitude"] >= EARTHQUAKE_CONFIG["min_magnitude"]
        ]
        if self.min_magnitude_filter:
            threshold = float(self.min_magnitude_filter.rstrip("+"))
            quakes = [
                quake
                for quake in quakes
                if quake.get("magnitude") is not None
                and quake["magnitude"] >= threshold
            ]
        if self.search_text:
            needle = self.search_text.strip().lower()
            quakes = [
                quake for quake in quakes if needle in quake.get("place", "").lower()
            ]
        return quakes

    def apply_search(self, text: str) -> None:
        self.search_text = text
        self.dirty = True

    def apply_filter(self, value: str | None) -> None:
        self.min_magnitude_filter = value if value in self.filter_options() else None
        self.dirty = True

    def filter_options(self) -> list[str]:
        return ["3.0+", "4.5+", "6.0+", "7.5+"]

    def shown_count(self) -> int:
        return len(self.visible_quakes())

    def legend_lines(self) -> list[SidebarLine]:
        colors = [color for _, color in MAGNITUDE_COLOR_BANDS]
        colors.append(MAGNITUDE_COLOR_MAJOR)
        labels = (" <3", " 3-4.4", " 4.5-5.9", " 6-7.4", " 7.5+")
        items = tuple(
            ("●", label, color)
            for label, color in zip(labels, colors)
        )
        return [SidebarLine("QUAKE M", legend_items=items)]

    def build(self, view: View) -> LayerRender:
        quakes = self.visible_quakes()
        image = view.new_image()
        draw = ImageDraw.Draw(image)
        for quake in quakes:
            for shift in WRAP_SHIFTS:
                x, y = view.to_pixel(quake["longitude"], quake["latitude"], shift)
                if -1 <= x < view.pixel_width + 1 and -1 <= y < view.pixel_height + 1:
                    draw.point((round(x), round(y)), fill=255)
                    break
        lines = view.to_lines(image)
        selected_id = self.selected.get("id") if self.selected is not None else None
        markers = []
        for quake in quakes:
            cell = view.to_cell(quake["longitude"], quake["latitude"])
            if cell is None:
                continue
            markers.append(
                Marker(
                    x=cell[0],
                    y=cell[1],
                    color=magnitude_to_color(quake.get("magnitude")),
                    glyph=magnitude_to_glyph(quake.get("magnitude")),
                    item=quake,
                    selected=selected_id is not None and quake.get("id") == selected_id,
                )
            )
        return LayerRender(lines, EARTHQUAKE_CONFIG["trail_color"], markers)

    def info_rows(self) -> list[tuple[str, str]]:
        quake = self.selected
        return [
            ("MAGNITUDE", format_magnitude(quake.get("magnitude"))),
            ("PLACE", quake.get("place") or "UNKNOWN"),
            ("DEPTH", format_depth(quake.get("depth_km"))),
            ("TIME", format_time_ago(quake.get("time"))),
            ("TSUNAMI", format_tsunami(quake.get("tsunami"))),
            ("ALERT", (quake.get("alert") or "N/A").upper()),
            ("STATUS", (quake.get("status") or "N/A").upper()),
            ("POSITION", f"{quake['latitude']:.3f}, {quake['longitude']:.3f}"),
        ]
