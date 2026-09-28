from __future__ import annotations

from PIL import ImageDraw

from around.core.layer import Layer, LayerRender, Marker, SidebarLine
from around.core.projection import WRAP_SHIFTS
from around.core.view import View
from around.layers.flights.format import heading_to_arrow
from around.layers.ships.cache import ShipCache
from around.layers.ships.settings import SHIP_CONFIG


class ShipsLayer(Layer):
    name = "ships"
    toggle_key = "s"
    order = 15
    info_title = "VESSEL INFO"
    enabled = SHIP_CONFIG["enabled"]

    def __init__(self) -> None:
        super().__init__()
        self.cache = ShipCache()
        self.ships: list[dict] = []

    def is_due(self) -> bool:
        return self.cache.should_fetch()

    def refresh_if_due(self, force: bool = False) -> bool:
        return self.enabled and self.cache.refresh_if_due()

    def reload(self) -> None:
        selected_mmsi = self.selected.get("mmsi") if self.selected else None
        self.ships = self.cache.get_ships() if self.enabled else []
        self.selected = next(
            (ship for ship in self.ships if ship["mmsi"] == selected_mmsi), None
        )
        self.dirty = True

    def clear(self) -> None:
        self.ships = []
        self.selected = None
        self.dirty = True

    def shown_count(self) -> int:
        return len(self.ships)

    def legend_lines(self) -> list[SidebarLine]:
        return [
            SidebarLine(
                "SHIPS",
                legend_items=(("●", " AIS vessel", SHIP_CONFIG["color"]),),
            )
        ]

    def build(self, view: View) -> LayerRender:
        image = view.new_image()
        draw = ImageDraw.Draw(image)
        for ship in self.ships:
            for shift in WRAP_SHIFTS:
                x, y = view.to_pixel(ship["longitude"], ship["latitude"], shift)
                if -1 <= x < view.pixel_width + 1 and -1 <= y < view.pixel_height + 1:
                    draw.point((round(x), round(y)), fill=255)
                    break
        lines = view.to_lines(image)
        selected_mmsi = self.selected.get("mmsi") if self.selected else None
        markers = []
        for ship in self.ships:
            cell = view.to_cell(ship["longitude"], ship["latitude"])
            if cell is None:
                continue
            course = ship.get("course")
            markers.append(
                Marker(
                    x=cell[0],
                    y=cell[1],
                    color=SHIP_CONFIG["color"],
                    glyph=heading_to_arrow(course) if view.zoom >= 8 else None,
                    item=ship,
                    selected=ship.get("mmsi") == selected_mmsi,
                )
            )
        return LayerRender(lines, SHIP_CONFIG["color"], markers)

    def info_rows(self) -> list[tuple[str, str]]:
        ship = self.selected
        if ship is None:
            return []
        speed = ship.get("speed_knots")
        course = ship.get("course")
        return [
            ("NAME", ship.get("name") or "UNKNOWN"),
            ("MMSI", ship.get("mmsi") or "UNKNOWN"),
            ("CALL SIGN", ship.get("call_sign") or "N/A"),
            ("SPEED", f"{speed:.1f} kn" if speed is not None else "N/A"),
            ("COURSE", f"{course:.0f}°" if course is not None else "N/A"),
            ("POSITION", f"{ship['latitude']:.3f}, {ship['longitude']:.3f}"),
        ]
