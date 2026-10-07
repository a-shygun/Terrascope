"""Map backgrounds, overlays, markers, legends, and scale bar."""

from __future__ import annotations

from .colors import (
    ColorManager,
    hex_to_rgb,
)
from .constants import (
    BLANK_BRAILLE,
    EDGE_STEPS,
    KM_PER_DEGREE_LAT,
    LEGEND_TEXT_COLOR,
    MAP_BOX_TITLE,
    MAP_CONFIG,
    MAP_EDGE_PAD_X,
    MAP_EDGE_PAD_Y,
    OSM_CREDIT,
    PANEL_BUTTON_HIDE,
    PANEL_BUTTON_SHOW,
    Rect,
    SCALE_BAR_MIN_BAR_COLUMNS,
    SCALE_BAR_MIN_COLUMNS,
    SCALE_BAR_TARGET_COLUMNS,
    SHADE_GLYPHS,
    SHADE_MIN_DENSITY,
    SHADE_SOLID_DENSITY,
    SLIDER_CAPTION_WIDTH,
    SLIDER_EMPTY,
    SLIDER_FILLED,
    SLIDER_KNOB,
    SLIDER_TRACK_COLUMNS,
    SliderSpec,
    _SCALE_SYMBOLS,
    curses,
    math,
    np
)
from .layout import (
    draw_box,
    safe_addstr
)

ATTRIBUTION_COLOR = "#{:02x}{:02x}{:02x}".format(
    *(channel // 2 for channel in hex_to_rgb(LEGEND_TEXT_COLOR))
)

def _put_clipped(window, y: int, x: int, text: str, limit_x: int, attributes: int = 0) -> int:
    """Draw text but never past limit_x. Returns the x after the drawn text."""
    room = limit_x - x
    if room <= 0 or not text:
        return x
    text = text[:room]
    safe_addstr(window, y, x, text, attributes)
    return x + len(text)

def _parse_legend_item(item) -> tuple[str, str | None, str]:
    """A legend item is a 3-tuple holding a glyph, a "#rrggbb" colour and a
    label. Identified by content rather than position: the colour is the
    "#..." entry, the glyph is the shorter of the two remaining strings."""
    parts = [str(part) for part in item]
    color_index = next((i for i, part in enumerate(parts) if part.startswith("#")), None)
    color = parts.pop(color_index) if color_index is not None else None
    if len(parts) >= 2:
        parts.sort(key=len)  # stable: glyph first, label second
        return parts[0], color, parts[1]
    return "", color, parts[0] if parts else ""

def parse_rgba(color) -> tuple[int, int, int, float]:
    """Parse false/None/"#rgb"/"#rgba"/"#rrggbb"/"#rrggbbaa" -> (r, g, b, alpha 0..1).

    false / None / "" mean fully transparent. No alpha digits means opaque.
    """
    if not color:
        return 0, 0, 0, 0.0
    text = str(color).strip().lstrip("#")
    if len(text) in (3, 4):
        text = "".join(character * 2 for character in text)
    if len(text) == 6:
        text += "ff"
    if len(text) != 8:
        raise ValueError(f"Invalid hex color: {color!r}")
    red, green, blue, alpha = (int(text[i : i + 2], 16) for i in range(0, 8, 2))
    return red, green, blue, alpha / 255

def _edge_palette(water, land) -> list[str | None]:
    """Background colour for each land-coverage step 0 (water) .. EDGE_STEPS (land).

    Water and land are interpolated as RGBA (premultiplied, so a transparent
    side doesn't tint the fade). Each step is then composited over the terminal
    background stand-in. A step whose alpha rounds to 0 stays None, i.e. truly
    transparent, so the terminal's own background shows through there.
    """
    blend = MAP_CONFIG.get("transparent_blend_color") or "#000000"
    blend_rgb = parse_rgba(blend)[:3]
    wr, wg, wb, wa = parse_rgba(water)
    lr, lg, lb, la = parse_rgba(land)
    palette: list[str | None] = []
    for step in range(EDGE_STEPS + 1):
        t = step / EDGE_STEPS if EDGE_STEPS else 1.0
        alpha = wa + (la - wa) * t
        if round(alpha * 255) == 0:
            palette.append(None)
            continue
        # premultiplied interpolation, then un-premultiply
        mixed = [
            (w * wa + (l * la - w * wa) * t) / alpha
            for w, l in ((wr, lr), (wg, lg), (wb, lb))
        ]
        # composite over the terminal background stand-in
        final = [
            round(c * alpha + b * (1 - alpha)) for c, b in zip(mixed, blend_rgb)
        ]
        palette.append("#{:02x}{:02x}{:02x}".format(*final))
    return palette

def _edge_cells(water, land):
    """Per land-coverage step 0 .. EDGE_STEPS: (background colour or None, shade
    glyph or None), plus the colour the shade glyphs are drawn in.

    When water and land are BOTH opaque (or both transparent) this is just
    _edge_palette: a real colour fade. A terminal cannot blend a cell with its
    own (transparent) background, so when exactly ONE side is transparent the
    fade over the transparent side is drawn with the shade characters
    (light / medium / dark) in the opaque colour and no background: the dots of
    the glyph let the terminal's own background show through, which is a true
    fade whatever is behind the terminal."""
    palette = _edge_palette(water, land)
    water_alpha = parse_rgba(water)[3]
    land_alpha = parse_rgba(land)[3]
    water_clear = round(water_alpha * 255) == 0
    land_clear = round(land_alpha * 255) == 0
    if water_clear == land_clear:
        return [(color, None) for color in palette], None
    solid, max_alpha = (land, land_alpha) if water_clear else (water, water_alpha)
    blend_rgb = parse_rgba(MAP_CONFIG.get("transparent_blend_color") or "#000000")[:3]
    shade_color = "#{:02x}{:02x}{:02x}".format(
        *(round(c * max_alpha + b * (1 - max_alpha)) for c, b in zip(parse_rgba(solid)[:3], blend_rgb))
    )
    cells = []
    for step in range(EDGE_STEPS + 1):
        t = step / EDGE_STEPS if EDGE_STEPS else 1.0
        alpha = water_alpha + (land_alpha - water_alpha) * t
        density = max(0.0, min(1.0, alpha / max_alpha)) if max_alpha > 0 else 0.0
        if density < SHADE_MIN_DENSITY:
            cells.append((None, None))
        elif density >= SHADE_SOLID_DENSITY:
            cells.append((shade_color, None))
        elif density < 0.31:
            cells.append((None, SHADE_GLYPHS[0]))
        elif density < 0.56:
            cells.append((None, SHADE_GLYPHS[1]))
        else:
            cells.append((None, SHADE_GLYPHS[2]))
    return cells, shade_color

def _background_data(frame: Frame, water, land):
    """(key, per-cell background colours, shades) cached on the frame so
    redraws of the same frame don't recompute it. shades is None, or
    (rows of shade glyph / None per cell, shade colour)."""
    key = (water, land)
    cached = frame.background_cache
    if cached is not None and len(cached) == 3 and cached[0] == key:
        return cached
    cells, shade_color = _edge_cells(water, land)
    cover = frame.land_cover
    shades = None
    if cover is None:
        grid: list[list[str | None]] = []
        if shade_color is not None:
            shades = ([], shade_color)
    else:
        steps = np.clip(np.rint(cover * EDGE_STEPS), 0, EDGE_STEPS).astype(int).tolist()
        grid = [[cells[step][0] for step in row] for row in steps]
        if shade_color is not None:
            shades = ([[cells[step][1] for step in row] for row in steps], shade_color)
    data = (key, grid, shades)
    frame.background_cache = data
    return data

def background_grid(frame: Frame, water, land) -> list[list[str | None]]:
    """Per-cell background colours (hex or None = transparent)."""
    return _background_data(frame, water, land)[1]

def edge_shades(frame: Frame, water, land):
    """None, or (shade glyph rows, shade colour) for the coastline fade drawn
    with shade characters (see _edge_cells)."""
    return _background_data(frame, water, land)[2]

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
        self.water = MAP_CONFIG["water_color"]
        self.land = MAP_CONFIG["land_color"]
        self.grid = background_grid(frame, self.water, self.land)
        overrides: dict[tuple[int, int], str] = {}
        for layer_render in frame.layers:
            if layer_render.bg_cells:
                overrides.update(layer_render.bg_cells)
        if overrides:
            grid = [row[:] for row in self.grid]  # the cached grid stays untouched
            for (x, y), color in overrides.items():
                if 0 <= y < len(grid) and 0 <= x < len(grid[y]):
                    grid[y][x] = color
            self.grid = grid
        self._fallback = [_edge_palette(self.water, self.land)[0]] * self.width
        self.override_cells = set(overrides)  # cells whose background a layer replaced: no shade there
        self.shades = edge_shades(frame, self.water, self.land)

    def shade_at(self, row: int, col: int) -> tuple[str, str] | None:
        """(shade glyph, colour) of the coastline fade at this cell, or None."""
        if not self.shades or (col, row) in self.override_cells:
            return None
        rows, color = self.shades
        if 0 <= row < len(rows) and 0 <= col < len(rows[row]):
            glyph = rows[row][col]
            if glyph:
                return glyph, color
        return None

    def bg_row(self, row: int) -> list[str | None]:
        if row < len(self.grid) and len(self.grid[row]) >= self.width:
            return self.grid[row]
        return self._fallback

    def bg_at(self, row: int, col: int) -> str | None:
        return self.bg_row(row)[col]

    def put(
        self, row: int, col: int, text: str, color: str, bg: str | None, extra: int = 0
    ) -> None:
        safe_addstr(
            self.window,
            self.top + row,
            self.left + col,
            text,
            self.colors.get_pair(color, bg) | extra,
        )

def draw_map_overlay_text(window, rect: Rect, frame: Frame, colors, y: int, x: int, text: str, extra: int = 0) -> None:
    """Draw status text over the map while retaining each map cell's background."""
    area = _MapArea(window, *rect, frame, colors)
    row = y - area.top
    col = x - area.left
    if not 0 <= row < area.height:
        return
    for offset, char in enumerate(text):
        target = col + offset
        if 0 <= target < area.width:
            area.put(row, target, char, LEGEND_TEXT_COLOR, area.bg_at(row, target), extra)

def draw_background(area: _MapArea) -> None:
    """Country outlines (braille) over the water/land background. Empty cells in
    the coastline fade show a shade glyph when one side of the map is transparent."""
    country_color = MAP_CONFIG["country_color"]
    # Optional yaml key map.province_color; without it provinces are the
    # country colour, dimmed.
    configured = MAP_CONFIG.get("province_color")
    province_color = configured or country_color
    province_extra = 0 if configured else curses.A_DIM
    province_lines = area.frame.province_lines
    empty = (BLANK_BRAILLE, " ")
    for row in range(area.height):
        line = area.frame.country_lines[row] if row < len(area.frame.country_lines) else ""
        text = line[: area.width].ljust(area.width)
        province_text = None
        if province_lines and row < len(province_lines):
            province_text = province_lines[row][: area.width].ljust(area.width)
        # Per column: (char, colour, extra attributes). Country border glyphs
        # win; province glyphs fill the empty cells; then the shade fade.
        cells = []
        for col in range(area.width):
            char = text[col]
            if char not in empty:
                cells.append((char, country_color, 0))
            elif province_text is not None and province_text[col] not in empty:
                cells.append((province_text[col], province_color, province_extra))
            else:
                shade = area.shade_at(row, col)
                cells.append((shade[0], shade[1], 0) if shade else (char, country_color, 0))
        bg_row = area.bg_row(row)
        col = 0
        while col < area.width:
            bg = bg_row[col]
            _, color, extra = cells[col]
            stop = col + 1
            while stop < area.width and bg_row[stop] == bg and cells[stop][1:] == (color, extra):
                stop += 1
            area.put(row, col, "".join(cell[0] for cell in cells[col:stop]), color, bg, extra)
            col = stop

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
    """Symbols first, then text labels, so a plane or quake glyph never cuts a
    letter out of a place name."""
    _draw_markers_pass(area, labels=False)
    _draw_markers_pass(area, labels=True)

def _draw_markers_pass(area: _MapArea, labels: bool) -> None:
    for layer_render in area.frame.layers:
        for marker in layer_render.markers:
            if bool(marker.label) != labels:
                continue
            x = int(marker.x)
            y = int(marker.y)
            if x < 0 or x >= area.width or y < 0 or y >= area.height:
                continue
            bg = marker.bg_color if marker.bg_color is not None else area.bg_at(y, x)
            attributes = area.colors.get_pair(marker.color, bg)
            # Braille glyphs (e.g. the daylight country fill) keep the same
            # weight as the country outlines; other markers stay bold.
            if not (marker.glyph and "\u2800" <= marker.glyph[0] <= "\u28ff"):
                attributes |= curses.A_BOLD
            if marker.dim:
                attributes = (attributes & ~curses.A_BOLD) | curses.A_DIM
            if marker.selected:
                attributes |= curses.A_REVERSE
            if marker.label:
                label = marker.label
                if x + len(label) > area.width:
                    label = label[: max(1, area.width - x)]
                # One cell at a time, so every letter keeps the background of
                # the map cell it sits on instead of the first letter's
                # (unless the marker fixes its own bg_color, e.g. a
                # half-block radar cell whose "background" is really its
                # own second reading, not the map underneath it).
                extra = attributes & ~curses.A_COLOR
                for offset, char in enumerate(label):
                    cell_bg = (
                        marker.bg_color
                        if marker.bg_color is not None
                        else area.bg_at(y, x + offset)
                    )
                    cell_attributes = extra | area.colors.get_pair(marker.color, cell_bg)
                    safe_addstr(
                        area.window, area.top + y, area.left + x + offset, char, cell_attributes
                    )
                continue
            character = marker.glyph
            if character is None:
                lines = layer_render.lines
                if lines is None or y >= len(lines) or x >= len(lines[y]):
                    continue
                character = lines[y][x]
                if character == BLANK_BRAILLE:
                    continue
            elif character == BLANK_BRAILLE and marker.bg_color is None:
                # An "empty" glyph cell (e.g. the night fill) must not wipe the
                # coastline shade fade: draw the shade there instead.
                shade = area.shade_at(y, x)
                if shade:
                    character = shade[0]
                    attributes = area.colors.get_pair(shade[1], bg)
            safe_addstr(area.window, area.top + y, area.left + x, character, attributes)

def _legend_segments(line) -> list[tuple[str, str | None, int]]:
    """(text, colour or None, extra curses attributes) pieces of one legend line."""
    segments: list[tuple[str, str | None, int]] = []
    segments.append((line.text or "", None, curses.A_BOLD if line.bold else 0))
    for swatch in line.swatches:  # the swatch goes after the text, at the right end
        segments.append((" ", None, 0))
        segments.append((line.swatch_glyph, swatch, 0))
    if line.choices:  # a clickable toggle: "[ TINT  FILL ]" with the active one lit
        segments.append(("[", None, curses.A_DIM))
        for index, choice in enumerate(line.choices):
            lit = index == line.choice_index
            segments.append(
                (f" {choice} ", None, curses.A_REVERSE | curses.A_BOLD if lit else curses.A_DIM)
            )
        segments.append(("]", None, curses.A_DIM))
    for item in line.legend_items:
        glyph, color, label = _parse_legend_item(item)
        if any(segment[0] for segment in segments):
            segments.append(("  ", None, 0))
        if glyph:
            segments.append((glyph + " ", color, 0))
        segments.append((label, None, 0))
    return [segment for segment in segments if segment[0]]

def draw_map_legend(area: _MapArea, lines) -> list[tuple[int, int, int, str]]:
    """Legend of the active layers, stacked directly above the fixed bottom
    row shared by the slider and scale bar."""
    hits: list[tuple[int, int, int, str]] = []
    if not lines or area.height < 5 + MAP_EDGE_PAD_Y:
        return hits
    lines = lines[: area.height - 2 - MAP_EDGE_PAD_Y]
    last_row = area.height - 2 - MAP_EDGE_PAD_Y
    room = area.width - MAP_EDGE_PAD_X
    first_row = last_row - len(lines) + 1
    for offset, line in enumerate(lines):
        segments = _legend_segments(line)
        total = sum(len(text) for text, _, _ in segments)
        if total == 0 or total > room:
            continue
        row = first_row + offset
        col = room - total
        if line.action:
            hits.append((area.top + row, area.left + col, area.left + col + total, line.action))
        for text, color, extra in segments:
            for char in text:
                area.put(row, col, char, color or LEGEND_TEXT_COLOR, area.bg_at(row, col), extra)
                col += 1
    return hits

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
    if render_width <= 0 or lon_span <= 0 or max_columns < SCALE_BAR_MIN_COLUMNS:
        return None
    degrees_per_column = lon_span / render_width
    clamped_lat = max(-85.0, min(85.0, center_lat))
    cos_lat = max(math.cos(math.radians(clamped_lat)), 0.05)
    km_per_column = degrees_per_column * KM_PER_DEGREE_LAT * cos_lat
    if km_per_column <= 0:
        return None
    target_columns = min(max_columns, SCALE_BAR_TARGET_COLUMNS)
    nice_km = _nice_round_km(km_per_column * target_columns)
    bar_columns = round(nice_km / km_per_column)
    bar_columns = max(
        SCALE_BAR_MIN_BAR_COLUMNS, min(max_columns, bar_columns)
    )
    end = _SCALE_SYMBOLS["end"]
    bar = end + _SCALE_SYMBOLS["fill"] * max(0, bar_columns - 2) + end
    return bar_columns, f"{bar} {_format_km(nice_km)}"

def _put_on_map(
    area: _MapArea, row: int, col: int, text: str, color: str = LEGEND_TEXT_COLOR, extra: int = 0
) -> None:
    """Draw text on the map one cell at a time, each cell keeping the map's own
    background colour at that spot (so the text never sits on a different
    background than the map terrascope it)."""
    for offset, char in enumerate(text):
        x = col + offset
        if 0 <= x < area.width:
            area.put(row, x, char, color, area.bg_at(row, x), extra)

def _scale_text(frame: Frame, center_lat: float, width: int) -> str | None:
    scale = compute_scale_bar(frame.lon_span, frame.render_width, center_lat, width - 2)
    if scale is None or len(scale[1]) > width:
        return None
    return scale[1]

def draw_scale_bar(area: _MapArea, center_lat: float) -> None:
    text = _scale_text(area.frame, center_lat, area.width - MAP_EDGE_PAD_X)
    if text is None or area.height < 1 + MAP_EDGE_PAD_Y:
        return
    _put_on_map(
        area,
        area.height - 1 - MAP_EDGE_PAD_Y,
        area.width - MAP_EDGE_PAD_X - len(text),
        text,
    )

def slider_track(
    spec: SliderSpec, width: int, frame: Frame, center_lat: float
) -> tuple[int, int] | None:
    """(first track column, track length) inside the map area, or None when
    there is no room. Shared by drawing and mouse handling."""
    label_width = max(5, len(spec.label))
    # Keep all tabs on the same fixed-width track; steps map proportionally
    # onto it even when a layer has a long history range.
    # Reserve a fixed scale-bar slot at the right edge. The slider therefore
    # stays put while the displayed scale length or distance label changes.
    scale_slot = SCALE_BAR_TARGET_COLUMNS * 2 + 4
    right = width - MAP_EDGE_PAD_X - scale_slot - 2
    if spec.wide:
        room = right - SLIDER_CAPTION_WIDTH - 1 - MAP_EDGE_PAD_X - label_width - 1
        length = min(spec.steps, room)
    else:
        length = SLIDER_TRACK_COLUMNS
    if spec.wide and spec.steps % 2 and length % 2 == 0:
        length -= 1  # keep the middle value directly selectable
    if length < 1:
        return None
    first = right - SLIDER_CAPTION_WIDTH - 1 - length
    if first - label_width - 1 < MAP_EDGE_PAD_X:
        return None
    return first, length

def draw_slider(area: _MapArea, spec: SliderSpec, center_lat: float) -> None:
    """Draw the active layer's time slider on the map footer row."""
    track = slider_track(spec, area.width, area.frame, center_lat)
    row = area.height - 1 - MAP_EDGE_PAD_Y
    if track is None or not 0 <= row < area.height:
        return

    first, length = track
    label_x = first - len(spec.label) - 1
    dim = curses.A_DIM if spec.disabled else 0
    _put_on_map(area, row, label_x, spec.label, extra=dim)

    last_step = max(0, spec.steps - 1)
    knob = round(max(0, min(last_step, spec.index)) * (length - 1) / max(1, last_step))
    loaded = set(spec.loaded_steps) if spec.loaded_steps is not None else None
    for offset in range(length):
        step = round(offset * last_step / max(1, length - 1))
        if spec.disabled:
            glyph = SLIDER_EMPTY
            extra = curses.A_DIM
        elif offset == knob:
            glyph = SLIDER_KNOB
            extra = 0
        elif spec.marker is not None and step == spec.marker:
            glyph = "|"
            extra = curses.A_BOLD
        elif loaded is not None and step in loaded:
            glyph = SLIDER_FILLED
            extra = 0
        else:
            glyph = SLIDER_FILLED if offset < knob else SLIDER_EMPTY
            extra = curses.A_DIM if glyph == SLIDER_EMPTY else 0
        _put_on_map(area, row, first + offset, glyph, extra=extra)

    caption = spec.caption[:SLIDER_CAPTION_WIDTH]
    caption_x = first + length + 1
    if caption:
        _put_on_map(area, row, caption_x, caption, extra=dim)

    if spec.status:
        status_end = label_x - 1
        status_start = MAP_EDGE_PAD_X
        status = spec.status[:max(0, status_end - status_start)]
        if status:
            _put_on_map(area, row, status_start, status, extra=curses.A_DIM)

def panel_button_slot(
    map_rect: Rect, panel_visible: bool, enabled: bool = True
) -> tuple[int, int, str] | None:
    """(screen row, screen x, text) of the panel toggle button on the map
    box's bottom-left border, or None if the box is too small for it.
    Shared by drawing and mouse handling so the two can never disagree."""
    if not enabled:
        return None
    top, left, height, width = map_rect
    label = PANEL_BUTTON_HIDE if panel_visible else PANEL_BUTTON_SHOW
    text = f" {label} "
    if height < 2 or len(text) + 4 >= width:
        return None
    return top + height - 1, left + 2, text

def border_button_slots(
    map_rect: Rect, panel_visible: bool, labels: list[str], panel_button: bool = True
) -> list[tuple[int, int, str]]:
    """(screen row, screen x, text) of the layer buttons on the map box's bottom
    border, laid out after the panel button; buttons that do not fit are left
    out. Shared by drawing and mouse handling so the two can never disagree."""
    top, left, height, width = map_rect
    if height < 2:
        return []
    panel = panel_button_slot(map_rect, panel_visible, panel_button)
    x = panel[1] + len(panel[2]) + 1 if panel is not None else left + 2
    slots = []
    for label in labels:
        text = f" {label} "
        if x + len(text) + 2 > left + width:
            break
        slots.append((top + height - 1, x, text))
        x += len(text) + 1
    return slots

def draw_attribution(area: _MapArea, text: str) -> None:
    """Credits at the map's bottom-left: the layer's own data source(s) on top,
    always \u00a9 OpenStreetMap contributors on the bottom row. `text` is the tab's
    credit(s), separated by " \u00b7 "; a "Flights: " style prefix is dropped."""
    layer_credits = []
    for part in text.split(" \u00b7 "):
        part = part.split(": ", 1)[-1].strip()
        if part and "OpenStreetMap" not in part:
            layer_credits.append(part)
    lines = layer_credits + [OSM_CREDIT]
    room = max(0, area.width - 2 * MAP_EDGE_PAD_X)
    # Align the OSM credit with the shared slider / scale footer row.
    bottom = area.height - 1 - MAP_EDGE_PAD_Y
    for offset, line in enumerate(reversed(lines)):
        row = bottom - offset
        if row < 0:
            break
        _put_on_map(area, row, MAP_EDGE_PAD_X, line[:room], color=ATTRIBUTION_COLOR)

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
    panel_visible: bool = True,
    panel_button: bool = True,
    legend=None,
    slider: SliderSpec | None = None,
    attribution: str = "",
    buttons: list[str] | None = None,
) -> list[tuple[int, int, int, str]]:
    """Draws the map box. Returns the clickable legend lines (see draw_map_legend)."""
    draw_box(window, top, left, height, width, MAP_BOX_TITLE)
    button = panel_button_slot((top, left, height, width), panel_visible, panel_button)
    if button is not None:
        button_row, button_x, button_text = button
        safe_addstr(window, button_row, button_x, button_text, curses.A_BOLD)
    for row, x, text in border_button_slots((top, left, height, width), panel_visible, buttons or [], panel_button):
        safe_addstr(window, row, x, text, curses.A_BOLD)
    area = _MapArea(window, top, left, height, width, frame, colors)
    draw_background(area)
    draw_layer_symbols(area)
    draw_markers(area)
    draw_attribution(area, attribution)
    draw_scale_bar(area, center_lat)
    if slider is not None:
        draw_slider(area, slider, center_lat)
    return draw_map_legend(area, legend)
