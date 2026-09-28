# ui.py — EVERYTHING DRAWN ON SCREEN (curses drawing code)
# Responsible for: the boxes and borders, the map area (country outlines, layer
# symbols, markers), the water/land background colours and coastline fade
# (WATER_COLOR, LAND_COLOR, EDGE_STEPS), the info box for the selected marker,
# the CONTROLS bar at the bottom (labels, colours, layout) and the scale bar.
# Edit this file to: change colours or layout, the controls bar text, the info
# box size/content layout, or how markers and layers are painted.
# Not here: what data is shown (layers), input handling (app.py).

from __future__ import annotations

import curses
import math
import textwrap
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from around.config import (
    CONTROL_BAR_HEIGHT,
    KM_PER_DEGREE_LAT,
    MAP_CONFIG,
    OUTER_MARGIN,
    SIDEBAR_WIDTH,
)
from around.core.colors import hex_to_rgb
from around.core.layer import Layer
from around.core.view import BLANK_BRAILLE

if TYPE_CHECKING:
    from around.core.colors import ColorManager
    from around.core.world import Frame

WATER_COLOR = "#0a1a3a"  # dark blue
LAND_COLOR = "#000000"  # black
EDGE_STEPS = 8  # shades between water and land along coastlines
# Set either colour (here or in MAP_CONFIG "water_color" / "land_color") to
# False for a transparent background.


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def safe_addstr(window, y: int, x: int, text: str, attributes: int = 0) -> None:
    try:
        window.addnstr(y, x, text, max(0, window.getmaxyx()[1] - x - 1), attributes)
    except curses.error:
        pass


def draw_box(window, top: int, left: int, height: int, width: int, title: str) -> None:
    if height < 2 or width < 2:
        return
    safe_addstr(window, top, left, "┌" + "─" * (width - 2) + "┐")
    for row in range(top + 1, top + height - 1):
        safe_addstr(window, row, left, "│")
        safe_addstr(window, row, left + width - 1, "│")
    safe_addstr(window, top + height - 1, left, "└" + "─" * (width - 2) + "┘")
    title_text = f" {title} "
    if len(title_text) < width - 2:
        safe_addstr(window, top, left + 2, title_text)


# ---------------------------------------------------------------------------
# Info box (selected marker details)
# ---------------------------------------------------------------------------


def info_box_rect(
    map_top: int,
    map_left: int,
    map_height: int,
    map_width: int,
    layer: Layer | None,
) -> tuple[int, int, int, int] | None:
    if layer is None:
        return None
    inner_width = map_width - 4
    inner_height = map_height - 2
    box_width = min(SIDEBAR_WIDTH, inner_width)
    box_height = min(max(7, min(18, len(layer.info_rows()) + 3)), inner_height)
    if box_width < 10 or box_height < 3:
        return None
    return (
        map_top + map_height - box_height - 1,
        map_left + 1,
        box_height,
        box_width,
    )


def info_title_text(layer: Layer | None, selection_position: tuple[int, int]) -> str:
    title = layer.info_title if layer else "INFO"
    position, total = selection_position
    if total > 1:
        title = f"{title}  < {position} of {total} >"
    return title


def info_arrow_positions(
    info_left: int, layer: Layer | None, selection_position: tuple[int, int]
) -> tuple[int, int] | None:
    """Screen x of the "<" and ">" in the info box title (None if not shown).

    Shared by drawing and mouse handling so the two can never disagree."""
    if layer is None or selection_position[1] < 2:
        return None
    title_left = info_left + 3
    title = info_title_text(layer, selection_position)
    return title_left + len(layer.info_title) + 2, title_left + title.rfind(">")


def draw_info_box(
    window,
    top: int,
    left: int,
    height: int,
    width: int,
    layer: Layer | None,
    selection_position: tuple[int, int] = (0, 0),
) -> None:
    if height < 3 or width < 10:
        return

    draw_box(window, top, left, height, width, info_title_text(layer, selection_position))

    if layer is None:
        safe_addstr(window, top + 2, left + 2, "CLICK A MARKER")
        safe_addstr(window, top + 4, left + 2, "to inspect its")
        safe_addstr(window, top + 5, left + 2, "information.")
        return

    y = top + 2
    x = left + 2
    value_x = x + 13
    value_width = max(1, width - (value_x - left) - 2)

    for label, value in layer.info_rows():
        if y >= top + height - 1:
            break
        safe_addstr(window, y, x, label.ljust(12))
        wrapped = textwrap.wrap(
            str(value),
            width=value_width,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
        for line in wrapped:
            if y >= top + height - 1:
                break
            safe_addstr(window, y, value_x, line)
            y += 1


# ---------------------------------------------------------------------------
# Controls bar
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _legacy_layer_styles() -> dict[str, tuple[str, str]]:
    """Fallback label/colour for layers that don't set control_label /
    control_color themselves. Once every layer defines them, delete this."""
    labels = {
        "flights": "PLANE",
        "earthquakes": "EARTHQUAKE",
        "cities": "CITY",
        "ships": "SHIP",
        "night": "NIGHT",
    }
    colors = {"night": "#8194a8"}
    try:
        from around.layers.cities.settings import CITY_CONFIG
        from around.layers.earthquakes.settings import MAGNITUDE_COLOR_BANDS
        from around.layers.flights.settings import FLIGHT_CONFIG
        from around.layers.ships.settings import SHIP_CONFIG

        colors.update(
            {
                "flights": FLIGHT_CONFIG["color"],
                "earthquakes": MAGNITUDE_COLOR_BANDS[-1][1],
                "cities": CITY_CONFIG["color"],
                "ships": SHIP_CONFIG["color"],
            }
        )
    except ImportError:
        pass
    return {name: (label, colors.get(name, "#ffffff")) for name, label in labels.items()}


def layer_style(layer: Layer) -> tuple[str, str]:
    legacy = _legacy_layer_styles().get(layer.name)
    label = getattr(layer, "control_label", None) or (
        legacy[0] if legacy else layer.name.upper()
    )
    color = getattr(layer, "control_color", None) or (
        legacy[1] if legacy else "#ffffff"
    )
    return label, color


def draw_controls_bar(window, height: int, width: int, world, app) -> None:
    top = height - OUTER_MARGIN[1] - CONTROL_BAR_HEIGHT
    left = OUTER_MARGIN[0]
    box_width = width - OUTER_MARGIN[0] * 2
    if box_width < 10 or CONTROL_BAR_HEIGHT < 4:
        return
    draw_box(window, top, left, CONTROL_BAR_HEIGHT, box_width, "CONTROLS")
    x = left + 2
    tokens = ["WASD/ARROWS/+/-/0"]
    for layer in world.layers:
        label, color = layer_style(layer)
        tokens.append((label, layer, color))
    tokens.append(("QUIT", None, "#f2c14e"))
    available = max(1, box_width - 4)
    rows: list[list[object]] = [[], []]
    row_widths = [0, 0]
    for token in tokens:
        token_width = len(token) if isinstance(token, str) else len(token[0])
        row = 0 if row_widths[0] + token_width + (5 if rows[0] else 0) <= available else 1
        if row_widths[row] + token_width + (5 if rows[row] else 0) > available:
            continue
        rows[row].append(token)
        row_widths[row] += token_width + (5 if len(rows[row]) > 1 else 0)
    for row_index, row_tokens in enumerate(rows):
        cursor = x
        y = top + 1 + row_index
        for token_index, token in enumerate(row_tokens):
            if token_index:
                safe_addstr(window, y, cursor, "  ·  ")
                cursor += 5
            if isinstance(token, str):
                safe_addstr(window, y, cursor, token)
                cursor += len(token)
                continue
            label, layer, color = token
            attrs = app.colors.get_pair(color)
            if layer is not None:
                attrs |= curses.A_BOLD if layer.enabled else curses.A_DIM
            else:
                attrs |= curses.A_BOLD
            key = layer.toggle_key.upper() if layer is not None else "Q"
            key_index = label.find(key)
            if key_index < 0:
                safe_addstr(window, y, cursor, label, attrs)
            else:
                safe_addstr(window, y, cursor, label[:key_index])
                safe_addstr(window, y, cursor + key_index, key, attrs)
                safe_addstr(window, y, cursor + key_index + 1, label[key_index + 1:])
            cursor += len(label)


# ---------------------------------------------------------------------------
# Map box: background, outlines, layers, markers, scale bar
# ---------------------------------------------------------------------------


def _edge_palette(water: str | bool | None, land: str | bool | None) -> list[str | None]:
    """Background colour for each land-coverage step 0 (water) .. EDGE_STEPS (land)."""
    steps = range(EDGE_STEPS + 1)
    if not water and not land:
        return [None] * (EDGE_STEPS + 1)
    # A terminal cannot blend a colour with "no colour", so when one side is
    # transparent the edge switches at the halfway point instead of fading.
    if not water:
        return [land if step * 2 >= EDGE_STEPS else None for step in steps]
    if not land:
        return [water if step * 2 < EDGE_STEPS else None for step in steps]
    water_rgb = hex_to_rgb(water)
    land_rgb = hex_to_rgb(land)
    palette = []
    for step in steps:
        t = step / EDGE_STEPS
        mixed = [round(w + (l - w) * t) for w, l in zip(water_rgb, land_rgb)]
        palette.append("#{:02x}{:02x}{:02x}".format(*mixed))
    return palette


def background_grid(frame: Frame, water, land) -> list[list[str | None]]:
    """Per-cell background colours (hex or None = transparent), cached on the
    frame so redraws of the same frame don't recompute it."""
    key = (water, land)
    cached = frame.background_cache
    if cached is not None and cached[0] == key:
        return cached[1]
    palette = _edge_palette(water, land)
    cover = frame.land_cover
    if cover is None:
        grid: list[list[str | None]] = []
    else:
        steps = np.clip(np.rint(cover * EDGE_STEPS), 0, EDGE_STEPS).astype(int)
        grid = [[palette[step] for step in row] for row in steps.tolist()]
    frame.background_cache = (key, grid)
    return grid


def _segments(bg_row: list[str | None], start: int, end: int):
    """Yield (col_start, col_end, background) runs with a constant background."""
    col = start
    while col < end:
        bg = bg_row[col]
        stop = col + 1
        while stop < end and bg_row[stop] == bg:
            stop += 1
        yield col, stop, bg
        col = stop


class _MapArea:
    """Geometry + background lookup for the inside of the map box."""

    def __init__(self, window, top, left, height, width, frame, colors) -> None:
        self.window = window
        self.colors = colors
        self.frame = frame
        self.top = top + 1
        self.left = left + 2
        self.width = width - 4
        self.height = height - 2
        self.water = MAP_CONFIG.get("water_color", WATER_COLOR)
        self.land = MAP_CONFIG.get("land_color", LAND_COLOR)
        self.grid = background_grid(frame, self.water, self.land)
        self._fallback = [self.water or None] * self.width

    def bg_row(self, row: int) -> list[str | None]:
        if row < len(self.grid) and len(self.grid[row]) >= self.width:
            return self.grid[row]
        return self._fallback

    def bg_at(self, row: int, col: int) -> str | None:
        return self.bg_row(row)[col]

    def put(self, row: int, col: int, text: str, color: str, bg: str | None) -> None:
        safe_addstr(
            self.window,
            self.top + row,
            self.left + col,
            text,
            self.colors.get_pair(color, bg),
        )


def draw_background(area: _MapArea) -> None:
    """Country outlines (braille) over the water/land background."""
    country_color = MAP_CONFIG["country_color"]
    for row in range(area.height):
        line = area.frame.country_lines[row] if row < len(area.frame.country_lines) else ""
        text = line[: area.width].ljust(area.width)
        for start, stop, bg in _segments(area.bg_row(row), 0, area.width):
            area.put(row, start, text[start:stop], country_color, bg)


def draw_layer_symbols(area: _MapArea) -> None:
    """Braille content each layer produced (heatmaps, night stipple, ...)."""
    for layer_render in area.frame.layers:
        if layer_render.lines is None:
            continue
        color = layer_render.line_color
        for row in range(min(area.height, len(layer_render.lines))):
            line = layer_render.lines[row]
            bg_row = area.bg_row(row)
            limit = min(area.width, len(line))
            col = 0
            while col < limit:
                if line[col] == BLANK_BRAILLE:
                    col += 1
                    continue
                bg = bg_row[col]
                stop = col + 1
                while stop < limit and line[stop] != BLANK_BRAILLE and bg_row[stop] == bg:
                    stop += 1
                area.put(row, col, line[col:stop], color, bg)
                col = stop


def draw_markers(area: _MapArea) -> None:
    for layer_render in area.frame.layers:
        for marker in layer_render.markers:
            x = int(marker.x)
            y = int(marker.y)
            if x < 0 or x >= area.width or y < 0 or y >= area.height:
                continue
            attributes = (
                area.colors.get_pair(marker.color, area.bg_at(y, x)) | curses.A_BOLD
            )
            if marker.selected:
                attributes |= curses.A_REVERSE
            if marker.label:
                label = marker.label
                if x + len(label) > area.width:
                    label = label[: max(1, area.width - x)]
                safe_addstr(area.window, area.top + y, area.left + x, label, attributes)
                continue
            character = marker.glyph
            if character is None:
                lines = layer_render.lines
                if lines is None or y >= len(lines) or x >= len(lines[y]):
                    continue
                character = lines[y][x]
                if character == BLANK_BRAILLE:
                    continue
            safe_addstr(area.window, area.top + y, area.left + x, character, attributes)


def _nice_round_km(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    residual = value / magnitude
    if residual < 1.5:
        nice = 1
    elif residual < 3.5:
        nice = 2
    elif residual < 7.5:
        nice = 5
    else:
        nice = 10
    return nice * magnitude


def _format_km(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f} km"
    if value >= 1:
        return f"{value:.0f} km"
    return f"{value * 1000:.0f} m"


def compute_scale_bar(
    lon_span: float, render_width: int, center_lat: float, max_columns: int
) -> tuple[int, str] | None:
    if render_width <= 0 or lon_span <= 0 or max_columns < 6:
        return None
    degrees_per_column = lon_span / render_width
    clamped_lat = max(-85.0, min(85.0, center_lat))
    cos_lat = max(math.cos(math.radians(clamped_lat)), 0.05)
    km_per_column = degrees_per_column * KM_PER_DEGREE_LAT * cos_lat
    if km_per_column <= 0:
        return None
    target_columns = min(max_columns, 14)
    nice_km = _nice_round_km(km_per_column * target_columns)
    bar_columns = round(nice_km / km_per_column)
    bar_columns = max(3, min(max_columns, bar_columns))
    bar = "|" + "─" * max(0, bar_columns - 2) + "|"
    return bar_columns, f"{bar} {_format_km(nice_km)}"


def draw_scale_bar(area: _MapArea, center_lat: float) -> None:
    scale = compute_scale_bar(
        area.frame.lon_span, area.frame.render_width, center_lat, area.width - 2
    )
    if scale is None or area.height < 1:
        return
    _, text = scale
    if len(text) <= area.width:
        safe_addstr(
            area.window,
            area.top + area.height - 1,
            area.left + area.width - len(text),
            text,
        )


def draw_map_box(
    window,
    top: int,
    left: int,
    height: int,
    width: int,
    frame: Frame,
    colors: ColorManager,
    zoom: float,
    center_lat: float,
) -> None:
    draw_box(window, top, left, height, width, "WORLD MAP")
    area = _MapArea(window, top, left, height, width, frame, colors)
    draw_background(area)
    draw_layer_symbols(area)
    draw_markers(area)
    draw_scale_bar(area, center_lat)
