from __future__ import annotations

from PIL import ImageDraw

from around.config import FETCH_NEW_DATA_FROM_API
from around.core.layer import Layer, LayerRender, Marker, SidebarLine
from around.core.projection import WRAP_SHIFTS
from around.core.view import View
from around.layers.flights.cache import FlightCache, valid_history_point
from around.layers.flights.format import (
    format_altitude,
    format_ground,
    format_heading,
    format_position_source,
    format_speed,
    format_vertical_rate,
    heading_to_arrow,
)
from around.layers.flights.settings import FLIGHT_CONFIG


class FlightsLayer(Layer):
    name = "flights"
    toggle_key = "p"
    order = 10
    info_title = "AIRCRAFT INFO"
    enabled = FLIGHT_CONFIG["enabled"]

    def __init__(self) -> None:
        super().__init__()
        self.cache = FlightCache()
        self.flights: list[dict] = []
        self.history: dict[str, list[dict]] = {}
        self.search_text = ""
        self.filter_country: str | None = None

    def is_due(self) -> bool:
        return self.cache.should_fetch()

    def refresh_if_due(self, force: bool = False) -> bool:
        if not self.enabled:
            return False
        return self.cache.refresh_if_due(force)

    def reload(self) -> None:
        flights = self.cache.get_flights() if self.enabled else []
        selected_icao = (
            self.selected.get("icao24") if self.selected is not None else None
        )
        self.flights = flights
        self.history = {
            flight["icao24"]: self.cache.get_history(flight["icao24"])
            for flight in flights
        }
        self.selected = None
        if selected_icao:
            for flight in flights:
                if flight.get("icao24") == selected_icao:
                    self.selected = flight
                    break
        self.dirty = True

    def clear(self) -> None:
        self.flights = []
        self.history = {}
        self.selected = None
        self.dirty = True

    def visible_flights(self) -> list[dict]:
        flights = self.flights
        if self.filter_country:
            flights = [
                flight
                for flight in flights
                if flight.get("origin_country") == self.filter_country
            ]
        if self.search_text:
            needle = self.search_text.strip().lower()
            flights = [
                flight
                for flight in flights
                if needle in (flight.get("callsign") or "").lower()
                or needle in (flight.get("icao24") or "").lower()
            ]
        return flights

    def apply_search(self, text: str) -> None:
        self.search_text = text
        self.dirty = True

    def apply_filter(self, value: str | None) -> None:
        self.filter_country = value if value in self.filter_options() else None
        self.dirty = True

    def filter_options(self) -> list[str]:
        countries = {
            flight["origin_country"]
            for flight in self.flights
            if flight.get("origin_country")
        }
        return sorted(countries)

    def shown_count(self) -> int:
        return len(self.visible_flights())

    def legend_lines(self) -> list[SidebarLine]:
        return [
            SidebarLine(
                "FLIGHTS",
                legend_items=(("✈", " aircraft", FLIGHT_CONFIG["color"]),),
            )
        ]

    def _draw_selected_tail(self, draw: ImageDraw.ImageDraw, view: View) -> None:
        """Draw the flight-history tail for the selected aircraft only."""
        if self.selected is None:
            return
        selected_icao = self.selected.get("icao24")
        if not selected_icao:
            return
        points = [
            point
            for point in self.history.get(selected_icao, [])
            if valid_history_point(point)
        ]
        if len(points) < 2:
            return
        for first, second in zip(points, points[1:]):
            for shift in WRAP_SHIFTS:
                x1, y1 = view.to_pixel(first["longitude"], first["latitude"], shift)
                x2, y2 = view.to_pixel(second["longitude"], second["latitude"], shift)
                if (
                    max(x1, x2) < -2
                    or min(x1, x2) > view.pixel_width + 2
                    or max(y1, y2) < -2
                    or min(y1, y2) > view.pixel_height + 2
                ):
                    continue
                draw.line(
                    (round(x1), round(y1), round(x2), round(y2)),
                    fill=255,
                    width=1,
                )

    def build(self, view: View) -> LayerRender:
        flights = self.visible_flights()
        image = view.new_image()
        draw = ImageDraw.Draw(image)

        # Tail is only ever shown for the currently-selected (clicked)
        # aircraft; everything else stays a bare dot/arrow with no trail.
        self._draw_selected_tail(draw, view)

        for flight in flights:
            for shift in WRAP_SHIFTS:
                x, y = view.to_pixel(flight["longitude"], flight["latitude"], shift)
                if -1 <= x < view.pixel_width + 1 and -1 <= y < view.pixel_height + 1:
                    draw.point((round(x), round(y)), fill=255)
                    break

        lines = view.to_lines(image)
        arrow_mode = view.zoom >= FLIGHT_CONFIG["arrow_zoom_threshold"]
        selected_icao = (
            self.selected.get("icao24") if self.selected is not None else None
        )
        markers = []
        for flight in flights:
            cell = view.to_cell(flight["longitude"], flight["latitude"])
            if cell is None:
                continue
            glyph = heading_to_arrow(flight.get("true_track")) if arrow_mode else None
            markers.append(
                Marker(
                    x=cell[0],
                    y=cell[1],
                    color=FLIGHT_CONFIG["color"],
                    glyph=glyph,
                    item=flight,
                    selected=selected_icao is not None
                    and flight.get("icao24") == selected_icao,
                )
            )
        return LayerRender(lines, FLIGHT_CONFIG["color"], markers)

    def info_rows(self) -> list[tuple[str, str]]:
        flight = self.selected
        return [
            ("CALLSIGN", flight.get("callsign") or "UNKNOWN"),
            ("ICAO24", flight.get("icao24") or "UNKNOWN"),
            ("COUNTRY", flight.get("origin_country") or "UNKNOWN"),
            ("ALTITUDE", format_altitude(flight.get("baro_altitude"))),
            ("GEO ALT", format_altitude(flight.get("geo_altitude"))),
            ("SPEED", format_speed(flight.get("velocity"))),
            ("HEADING", format_heading(flight.get("true_track"))),
            ("VERT RATE", format_vertical_rate(flight.get("vertical_rate"))),
            ("ON GROUND", format_ground(flight.get("on_ground"))),
            ("SQUAWK", str(flight.get("squawk") or "N/A")),
            ("POSITION", f"{flight['latitude']:.3f}, {flight['longitude']:.3f}"),
            ("SOURCE", format_position_source(flight.get("position_source"))),
        ]
