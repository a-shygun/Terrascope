from __future__ import annotations

import math
import sys
import threading
import time
from PIL import ImageDraw
from terrascope.core.config import FETCH_NEW_DATA_FROM_API
from terrascope.core.layer import Layer, LayerRender, Marker, PanelBox, SidebarLine, SliderSpec
from terrascope.core.mapdata import MapDataError, load_airports, set_live_progress
from terrascope.core.view import BLANK_BRAILLE, WRAP_SHIFTS, View
from terrascope.layers.flights.api import fetch_opensky_states
from terrascope.layers.flights.cache import FlightCache
from terrascope.layers.flights.formatting import (
    airport_scalerank_floor,
    categorize,
    finite_float,
    format_altitude,
    format_heading,
    format_position_source,
    format_speed,
    format_vertical_rate,
    heading_to_arrow,
    position_at,
    valid_history_point,
)
from terrascope.layers.flights.settings import (
    AIRPORTS_LOADING_TEXT,
    AIRPORTS_UNAVAILABLE_TEXT,
    AIRPORT_COLOR,
    AIRPORT_CONFIG,
    AIRPORT_GLYPH,
    AIRPORT_LABEL_COLOR,
    AIRPORT_LABEL_MIN_ZOOM,
    AIRPORT_LABEL_PADDING,
    AIRPORT_LOAD_RETRY_SECONDS,
    AIRPORT_MAX_LABELS,
    ARROW_ZOOM_THRESHOLD,
    CATEGORY_COLORS,
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    FLIGHT_CONFIG,
    LEGEND_GLYPH,
    _LABELS,
    _TEXT,
)

class FlightsLayer(Layer):
    name = "flights"
    toggle_key = FLIGHT_CONFIG["toggle_key"]
    info_title = "AIRCRAFT INFO"
    enabled = FLIGHT_CONFIG["enabled"]
    # Bottom row: [info | plane search | country filter]
    panel_layout = (
        PanelBox("info", FLIGHT_CONFIG["panel_ratios"][0]),
        PanelBox("search", FLIGHT_CONFIG["panel_ratios"][1], "SEARCH PLANE", "callsign / ICAO"),
        PanelBox("filter", FLIGHT_CONFIG["panel_ratios"][2], "FILTER COUNTRY", "country name"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.cache = FlightCache()
        self.flights: list[dict] = []
        self.history: dict[str, list[dict]] = {}
        self.search_text = ""
        self.filter_countries: set[str] = set()
        self.minutes_back = 0  # slider: how far in the past the map shows (0 = live)
        self._live: dict[str, tuple[float, float]] = {}  # icao24 -> (lon, lat) at the shown time
        self._target = time.time()  # the unix time being shown
        # Airports (Natural Earth, loaded once off the UI thread; not OpenSky
        # data). Sorted most major (lowest scalerank) first.
        self.show_airports = bool(AIRPORT_CONFIG["enabled"])
        self._airports: list[tuple] = []
        self._expanded_airports: set[tuple] = set()
        self._airport_hits: list[tuple[int, int, int, tuple]] = []
        self._airports_pending = None
        self._airports_state = "idle"  # idle | loading | ready | failed
        self._airports_error = ""
        self._ordered_startup = True
        self._airports_retry_at = 0.0

    def prefetch(self) -> None:
        """Warm feeds after the ordered first-run download sequence."""
        if self._ordered_startup:
            return
        if self.show_airports and self._airports_state == "idle":
            self._start_loading_airports()
        if FETCH_NEW_DATA_FROM_API:
            with self.lock:
                if self.refresh_in_progress:
                    return
                self.refresh_in_progress = True
            threading.Thread(target=self._prefetch_live, name="terrascope-planes-prefetch", daemon=True).start()

    def _prefetch_live(self) -> None:
        try:
            if self.cache.refresh_if_due(force=True):
                with self.lock:
                    self.refresh_completed = True
        finally:
            with self.lock:
                self.refresh_in_progress = False
            self.dirty = True

    def is_due(self) -> bool:
        return self.cache.should_fetch()

    def refresh_if_due(self, force: bool = False) -> bool:
        if not force and not self.enabled:
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
        self.minutes_back = min(self.minutes_back, self._history_range_minutes())
        previous = self.selected
        self.selected = None
        if selected_icao:
            for flight in flights:
                if flight.get("icao24") == selected_icao:
                    self.selected = flight
                    break
            else:
                # Aircraft dropped out of the new data (landed, out of
                # coverage, etc.): keep its last known state so the info
                # box doesn't end up with a dangling selection.
                self.selected = previous
        self.dirty = True

    def clear(self) -> None:
        self.flights = []
        self.history = {}
        self.selected = None
        self.dirty = True

    def visible_flights(self) -> list[dict]:
        flights = self.flights
        if self.filter_countries:
            flights = [
                flight
                for flight in flights
                if flight.get("origin_country") in self.filter_countries
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

    def search_target(self, query: str) -> tuple[float, float] | None:
        """Return the position of the strongest current callsign/ICAO match."""
        needle = query.strip().lower()
        if not needle:
            return None
        candidates = self.visible_flights()
        if not candidates:
            return None

        def rank(entry: tuple[int, dict]) -> tuple[int, int]:
            index, flight = entry
            terms = (
                str(flight.get("callsign") or "").strip().lower(),
                str(flight.get("icao24") or "").lower(),
            )
            score = 0 if needle in terms else 1 if any(term.startswith(needle) for term in terms) else 2
            return score, index

        flight = min(enumerate(candidates), key=rank)[1]
        position = self._live.get(flight.get("icao24"))
        if position is None:
            longitude = finite_float(flight.get("longitude"))
            latitude = finite_float(flight.get("latitude"))
            if longitude is None or latitude is None:
                return None
            position = (longitude, latitude)
        return position

    def apply_filter(self, value) -> None:
        values = {value} if isinstance(value, str) else set(value or ())
        self.filter_countries = values.intersection(self.filter_options())
        self.dirty = True

    def filter_options(self) -> list[str]:
        countries = {
            flight["origin_country"]
            for flight in self.flights
            if flight.get("origin_country")
        }
        return sorted(countries)

    # ---- time slider and legend ----------------------------------------------

    def tick(self) -> None:
        super().tick()
        # Live markers no longer animate between fetches (they stay put at
        # their last reported fix), so there is nothing to redraw here on a
        # timer anymore; see build().
        if self.enabled and self.show_airports:
            self._poll_airports()

    def handle_key(self, key: int) -> bool:
        if super().handle_key(key):  # the layer's own toggle_key (planes on/off)
            return True
        if 0 <= key < 256 and chr(key).lower() == str(AIRPORT_CONFIG["toggle_key"]).lower():
            self.show_airports = not self.show_airports
            self.dirty = True
            return True
        return False

    # ---- airports (Natural Earth, loaded off the UI thread) -------------------

    def _start_loading_airports(self) -> None:
        self._airports_state = "loading"
        threading.Thread(target=self._load_airports, name="terrascope-airports", daemon=True).start()

    def _load_airports(self) -> None:
        try:
            airports = load_airports()
        except (MapDataError, OSError, ValueError) as error:
            # stderr is redirected to terrascope.log while the app runs.
            print(f"airports: {error}", file=sys.stderr)
            self._airports_state = "failed"
            self._airports_error = str(error)
            self._airports_retry_at = time.monotonic() + AIRPORT_LOAD_RETRY_SECONDS
            self.dirty = True
            return
        with self.lock:
            self._airports_pending = sorted(airports, key=lambda airport: airport[4])

    def _poll_airports(self) -> None:
        with self.lock:
            pending, self._airports_pending = self._airports_pending, None
        if pending is not None:
            self._airports = pending  # swap in on the UI thread
            self._airports_state = "ready"
            self._airports_error = ""
            self.dirty = True
        elif not self._ordered_startup and (self._airports_state == "idle" or (
            self._airports_state == "failed" and time.monotonic() >= self._airports_retry_at
        )):
            self._start_loading_airports()

    def _airport_markers(self, view: View) -> list[Marker]:
        """One marker per shown airport: a glyph always, plus its IATA/ICAO
        code as a label once zoomed in enough. Clicking toggles that marker
        between its short label and the full airport name, like country labels."""
        self._airport_hits = []
        if not self._airports:
            return []
        max_scalerank = airport_scalerank_floor(view.zoom)
        if max_scalerank is None:
            return []
        show_labels = view.zoom >= AIRPORT_LABEL_MIN_ZOOM
        occupied: dict[int, list[tuple[int, int]]] = {}
        markers: list[Marker] = []
        for longitude, latitude, name, code, scalerank in self._airports:
            if len(markers) >= AIRPORT_MAX_LABELS:
                break
            if scalerank > max_scalerank:
                continue  # sorted most-major first: nothing bigger qualifies later
            cell = view.to_cell(longitude, latitude)
            if cell is None:
                continue
            x, y = cell
            airport = (longitude, latitude, name, code, scalerank)
            expanded = airport in self._expanded_airports
            compact_label = f"{AIRPORT_GLYPH} {code}" if (show_labels and code) else None
            full_label = f"{AIRPORT_GLYPH} {name}"
            label = full_label if expanded and len(full_label) <= view.width else compact_label
            if expanded and label == full_label:
                x = max(0, min(x, view.width - len(full_label)))
            if label is not None:
                if x + len(label) > view.width:
                    label = None  # fall back to the airport glyph at the map edge
                else:
                    start, end = x - AIRPORT_LABEL_PADDING, x + len(label) + AIRPORT_LABEL_PADDING
                    collision = any(
                        start < seg_end and seg_start < end
                        for row in (y - 1, y, y + 1)
                        for seg_start, seg_end in occupied.get(row, ())
                    )
                    if collision:
                        continue
                    occupied.setdefault(y, []).append((x, x + len(label)))
            display_width = len(label) if label is not None else len(AIRPORT_GLYPH)
            markers.append(
                Marker(
                    x=x,
                    y=y,
                    color=AIRPORT_LABEL_COLOR if label else AIRPORT_COLOR,
                    glyph=None if label else AIRPORT_GLYPH,
                    label=label,
                )
            )
            self._airport_hits.append((x, x + display_width, y, airport))
        return markers

    def click_at(self, x: int, y: int) -> bool:
        """Toggle an airport marker between its short label and full name."""
        if not self.show_airports:
            return False
        for x0, x1, row, airport in self._airport_hits:
            if row == y and x0 <= x < x1:
                if airport in self._expanded_airports:
                    self._expanded_airports.remove(airport)
                else:
                    self._expanded_airports.add(airport)
                self.dirty = True
                return True
        return False

    def slider(self) -> SliderSpec | None:
        max_minutes = self._history_range_minutes()
        if max_minutes < 1:
            self.minutes_back = 0
            return SliderSpec("PLANES", 2, 0, "LIVE", status="HISTORY NOT LOADED", disabled=True)
        self.minutes_back = min(self.minutes_back, max_minutes)
        caption = "LIVE" if self.minutes_back == 0 else f"-{self.minutes_back}m"
        return SliderSpec("PLANES", max_minutes + 1, max_minutes - self.minutes_back, caption)

    def set_slider(self, index: int) -> None:
        max_minutes = self._history_range_minutes()
        self.minutes_back = max_minutes - max(0, min(max_minutes, index))
        self.dirty = True

    def _history_range_minutes(self) -> int:
        longest_span = 0.0
        for points in self.history.values():
            # valid_history_point only checks lon and lat, so filter the
            # timestamp here too. Old cache entries may hold strings.
            # Same guard position_at uses, keeps one bad point from
            # raising out of the render path.
            timestamps = [
                float(point["timestamp"])
                for point in points
                if valid_history_point(point)
                and finite_float(point.get("timestamp")) is not None
            ]
            if len(timestamps) > 1:
                longest_span = max(longest_span, max(timestamps) - min(timestamps))
        return max(0, int(longest_span // 60))

    def loading_messages(self) -> list[str]:
        messages = []
        if self.refresh_in_progress:
            messages.append("LOADING PLANES")
        if self.show_airports and self._airports_state == "loading":
            messages.append("LOADING AIRPORTS")
        elif self.show_airports and self._airports_state == "failed":
            detail = f": {self._airports_error[:42]}" if self._airports_error else ""
            messages.append(f"AIRPORTS UNAVAILABLE{detail}")
        return messages

    def hit_test_all(self, x: int, y: int, radius: float | None = None):
        # Trail cells are markers without an item: they are not clickable.
        return [hit for hit in super().hit_test_all(x, y, radius) if hit[1] is not None]

    def legend_lines(self) -> list[SidebarLine]:
        """Vertical legend: a heading, then one "NAME ●" line per category, the
        dots right-aligned in one column."""
        lines = []
        for key in CATEGORY_ORDER:
            lines.append(
                SidebarLine(
                    CATEGORY_LABELS[key].upper(),
                    swatches=(CATEGORY_COLORS[key],),
                    swatch_glyph=LEGEND_GLYPH,
                )
            )
        if self.show_airports:
            lines.append(SidebarLine("AIRPORT", swatches=(AIRPORT_COLOR,), swatch_glyph=AIRPORT_GLYPH))
            if self._airports_state == "loading":
                lines.append(SidebarLine(AIRPORTS_LOADING_TEXT))
            elif self._airports_state == "failed":
                lines.append(SidebarLine(AIRPORTS_UNAVAILABLE_TEXT))
        return lines

    # ---- drawing ---------------------------------------------------------------

    def _trail_markers(self, view: View) -> list[Marker]:
        """The flight-history tail of the selected aircraft only, ending at its
        shown position, as braille cells in that aircraft's own colour."""
        if self.selected is None:
            return []
        selected_icao = self.selected.get("icao24")
        if not selected_icao:
            return []
        points = [
            point
            for point in self.history.get(selected_icao, [])
            if valid_history_point(point)
            and (finite_float(point.get("timestamp")) or 0.0) <= self._target
        ]
        live = self._live.get(selected_icao)
        if live is not None:
            points.append({"longitude": live[0], "latitude": live[1]})
        if len(points) < 2:
            return []
        image = view.new_image()
        draw = ImageDraw.Draw(image)
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
        color = CATEGORY_COLORS[categorize(self.selected)]
        return [
            Marker(x=x, y=y, color=color, glyph=char)
            for y, row in enumerate(view.to_lines(image))
            for x, char in enumerate(row)
            if char != BLANK_BRAILLE
        ]

    def build(self, view: View) -> LayerRender:
        self.minutes_back = min(self.minutes_back, self._history_range_minutes())
        flights = self.visible_flights()
        self._target = time.time() - self.minutes_back * 60
        located = []
        for flight in flights:
            if self.minutes_back == 0:
                # Live: show the last reported fix as-is rather than dead-
                # reckoning forward from it. Dead-reckoning on every redraw
                # (including ones triggered by an unrelated click/pan/zoom)
                # made markers drift continuously instead of only moving when
                # the cache actually refreshes, and could also push the arrow
                # slightly out of step with its own trail's last point,
                # showing up as a stray dot next to it.
                position = (flight["longitude"], flight["latitude"])
            else:
                position = position_at(flight, self.history.get(flight["icao24"], []), self._target)
            if position is not None:  # None = not yet tracked at that time
                located.append((flight, position))
        flights = [flight for flight, _ in located]
        positions = [position for _, position in located]
        self._live = {f["icao24"]: pos for f, pos in located}
        arrow_mode = view.zoom >= ARROW_ZOOM_THRESHOLD

        # In arrow mode every flight gets an explicit glyph Marker below, so
        # this raw pixel pass isn't needed there. Skipping it also avoids a
        # rounding mismatch: this draws at a rounded pixel position while the
        # arrow Marker is placed via view.to_cell()'s own (floor-based) cell
        # math, so right at a cell boundary the two could disagree about
        # which cell a flight belongs in — the arrow would then land in one
        # cell and this dot in the next, leaving a stray dot beside it
        # instead of being covered by the arrow.
        lines = None
        if not arrow_mode:
            image = view.new_image()
            draw = ImageDraw.Draw(image)
            for lon, lat in positions:
                for shift in WRAP_SHIFTS:
                    x, y = view.to_pixel(lon, lat, shift)
                    if -1 <= x < view.pixel_width + 1 and -1 <= y < view.pixel_height + 1:
                        draw.point((round(x), round(y)), fill=255)
                        break
            lines = view.to_lines(image)

        selected_icao = (
            self.selected.get("icao24") if self.selected is not None else None
        )
        ranked: list[tuple[int, Marker]] = []
        for flight, (lon, lat) in zip(flights, positions):
            cell = view.to_cell(lon, lat)
            if cell is None:
                continue
            category = categorize(flight)
            glyph = heading_to_arrow(flight.get("true_track")) if arrow_mode else None
            ranked.append(
                (
                    CATEGORY_ORDER.index(category),
                    Marker(
                        x=cell[0],
                        y=cell[1],
                        color=CATEGORY_COLORS[category],
                        glyph=glyph,
                        item=flight,
                        selected=selected_icao is not None
                        and flight.get("icao24") == selected_icao,
                    ),
                )
            )
        # Where planes share a cell the last marker drawn wins, so draw the
        # rarer categories (emergency first in CATEGORY_ORDER) last.
        ranked.sort(key=lambda pair: -pair[0])
        # Airports first (drawn underneath), then the trail, then the planes
        # on top of both. Only the selected aircraft has a trail; everything
        # else is a bare dot/arrow.
        markers = []
        if self.show_airports:
            markers.extend(self._airport_markers(view))
        markers += self._trail_markers(view) + [marker for _, marker in ranked]
        return LayerRender(lines, FLIGHT_CONFIG["color"], markers)

    def info_rows(self) -> list[tuple[str, str]]:
        flight = self.selected
        if flight is None:
            return []
        unknown = _TEXT["unknown"]
        lon, lat = self._live.get(
            flight.get("icao24"), (flight["longitude"], flight["latitude"])
        )
        return [
            (_LABELS["callsign"], flight.get("callsign") or unknown),
            (_LABELS["type"], CATEGORY_LABELS[categorize(flight)]),
            (_LABELS["country"], flight.get("origin_country") or unknown),
            (_LABELS["altitude"], format_altitude(flight.get("baro_altitude"))),
            (_LABELS["speed"], format_speed(flight.get("velocity"))),
            (_LABELS["heading"], format_heading(flight.get("true_track"))),
            (_LABELS["vertical_rate"], format_vertical_rate(flight.get("vertical_rate"))),
            (_LABELS["position"], f"{lat:.3f}, {lon:.3f}"),
            (_LABELS["icao24"], flight.get("icao24") or unknown),
            (_LABELS["squawk"], str(flight.get("squawk") or _TEXT["not_available"])),
            (_LABELS["geo_altitude"], format_altitude(flight.get("geo_altitude"))),
            (_LABELS["source"], format_position_source(flight.get("position_source"))),
        ]
