# daynight_layer.py — DAY/NIGHT SHADING + CLOCK, SUN AND MOON INFO BOX
# Responsible for: the "night" layer. On the map it paints the solar phase
# bands (day, sunrise, civil / nautical / astronomical twilight) with seams.
# In its own bottom row it shows CLOCK (UTC, local, day of year), SUN at the
# CENTRE of the view (phase, sunrise / sunset, solar time, subsolar point) and
# MOON (phase, age, next new / full).
# Seams over land are solid one-cell blocks; over open water they are traced per
# braille dot so the terminator reads as a smooth curve.
# Moon figures use the mean lunar cycle, so they can be off by about half a day.

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
import numpy as np
from PIL import Image
from terrascope.core.config import CFG
from terrascope.layers.daynight.astronomy import format_hemisphere, hhmm, moon_info, solar_position, sun_elevation, sun_phase_name, sunrise_sunset
from terrascope.core.layer import Layer, LayerRender, Marker, PanelBox, SidebarLine, SliderSpec
from terrascope.core.ui import parse_rgba
from terrascope.core.view import BLANK_BRAILLE, View, normalize_longitude

NIGHT_CONFIG = CFG["layers"]["night"]

# Fixed settings (hardcoded; edit here).
UPDATE_SECONDS = NIGHT_CONFIG["update_seconds"]  # how often the map phase bands are recalculated
# Glyph drawn in every seam cell (the line between two phases). A full braille
# cell keeps the line solid and exactly one cell wide; override with
# layers: night: seam_glyph in default.yaml (e.g. "\u2847" for a lighter line).
SEAM_GLYPH = NIGHT_CONFIG.get("seam_glyph") or "\u28ff"
# Land is tinted with each phase's colour as a background, at this opacity over
# the plain land colour (the normal country borders are drawn on top of it).
TINT_OPACITY = float(NIGHT_CONFIG.get("tint_opacity", 0.25))
LOOK_KEY = str(NIGHT_CONFIG.get("look_key", "l")).lower()  # switches between the two looks
LOOKS = ("fill", "tint")  # dotted fill of the lit land / tinted land background (first = default)
_LAND_RGB = parse_rgba(CFG["map"]["land_color"])[:3]

def _tint(color: str) -> str:
    """The land background for a phase colour: the colour blended into land."""
    red, green, blue, _ = parse_rgba(color)
    mixed = (
        round(c * TINT_OPACITY + base * (1.0 - TINT_OPACITY))
        for c, base in zip((red, green, blue), _LAND_RGB)
    )
    return "#{:02x}{:02x}{:02x}".format(*mixed)

# Solar elevation thresholds (degrees) and their yaml config keys.
# Bands are checked from highest elevation downward; the first one a pixel
# falls into wins.  Each entry: (min_elevation_degrees, config_key).
_THRESHOLDS = NIGHT_CONFIG["thresholds"]  # elevations come from default.yaml
PHASE_THRESHOLDS = [
    (float(_THRESHOLDS["day"]), "day_color"),                # full day
    (float(_THRESHOLDS["sunrise"]), "sunrise_color"),        # sunrise / sunset
    (float(_THRESHOLDS["civil"]), "civil_twilight_color"),   # civil twilight
    (float(_THRESHOLDS["nautical"]), "nautical_twilight_color"),  # nautical twilight
    (float(_THRESHOLDS["astro"]), "astro_twilight_color"),   # astronomical twilight
    # below the astro threshold = night → no color, no stipple
]

# --- bottom row (this layer's own layout) ------------------------------------
# [CLOCK | SUN | MOON]. The three live boxes are redrawn every frame, so the
# clock ticks without re-rendering the map.
PANEL_LAYOUT = (
    PanelBox("live", NIGHT_CONFIG["panel_ratios"][0], "CLOCK"),
    PanelBox("live", NIGHT_CONFIG["panel_ratios"][1], "SUN"),
    PanelBox("live", NIGHT_CONFIG["panel_ratios"][2], "MOON"),
)
PHASE_LEGEND = (  # (config key, label)
    ("day_color", "DAY"),
    ("sunrise_color", "SUNRISE / SUNSET"),
    ("civil_twilight_color", "CIVIL TWILIGHT"),
    ("nautical_twilight_color", "NAUTICAL TWILIGHT"),
    ("astro_twilight_color", "ASTRO TWILIGHT"),
)

# --- info constants -------------------------------------------------------
# Solar elevation (degrees) -> name, checked from the top down.

# ----------------------------------------------------------------------------
# Shared astronomy helpers (NOAA / Meeus, ch. 7 and 25)
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# The layer
# ----------------------------------------------------------------------------

class DayNightLayer(Layer):
    """Trace the day/night phase bands. Each terminal cell gets the phase of
    the sun's elevation at its centre; land cells are stippled in that
    phase's colour, and every cell on the lighter side of a boundary between
    two phases becomes a seam cell: one solid, unbroken, one-cell-wide line in
    the lighter phase's colour, over sea and land alike.
    The clock / sun / moon details live in the bottom row (see live_rows), and
    the time slider can scrub the solar phases 24 hours either side of now."""

    name = "night"
    toggle_key = NIGHT_CONFIG["toggle_key"]
    info_title = "DAY / NIGHT"
    enabled = NIGHT_CONFIG["enabled"]
    wants_country_image = True
    panel_layout = PANEL_LAYOUT

    def __init__(self) -> None:
        super().__init__()
        self._last_update = time.monotonic()
        look = str(NIGHT_CONFIG.get("look", "fill")).lower()
        self.look = look if look in LOOKS else LOOKS[0]
        # Centre of the last view built; the info box reports the sun here.
        self._center_lat = 0.0
        self._center_lon = 0.0
        self._time_offset_hours = 0

    def slider(self) -> SliderSpec:
        """Scrub solar phases through the 24 hours before and after now."""
        index = self._time_offset_hours + 24
        caption = "NOW" if self._time_offset_hours == 0 else f"{self._time_offset_hours:+d}h"
        return SliderSpec("TIME", 49, index, caption, marker=24)

    def set_slider(self, index: int) -> None:
        self._time_offset_hours = max(-24, min(24, int(index) - 24))
        self._last_update = 0.0
        self.dirty = True

    def _display_time(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=self._time_offset_hours)

    def tick(self) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self._last_update >= UPDATE_SECONDS:
            self._last_update = now
            self.dirty = True

    def render_with_land(
        self,
        view: View,
        land_mask: Image.Image,
        country_image: Image.Image,
    ) -> LayerRender:
        self.dirty = False
        self._remember_view(view)
        result = self._build(view, land_mask, country_image)
        self.last_markers = result.markers
        return result

    # ---- the two looks -------------------------------------------------------

    def toggle_look(self) -> None:
        self.look = LOOKS[(LOOKS.index(self.look) + 1) % len(LOOKS)]
        self.dirty = True

    def handle_key(self, key: int) -> bool:
        if super().handle_key(key):
            return True
        if 0 <= key < 256 and chr(key).lower() == LOOK_KEY:
            self.toggle_look()
            return True
        return False

    def press_legend(self, action: str) -> None:
        if action == "look":
            self.toggle_look()

    def hit_test_all(self, x: int, y: int, radius: float = 1.5):
        # Stipple markers are purely visual and must not be selectable.
        return []

    def _remember_view(self, view: View) -> None:
        self._center_lat = view.center_lat
        self._center_lon = view.center_lon

    # ------------------------------------------------------------------
    # Bottom row: legend + live CLOCK / SUN / MOON boxes
    # ------------------------------------------------------------------

    def legend_lines(self) -> list[SidebarLine]:
        lines = [
            SidebarLine(label, swatches=(NIGHT_CONFIG[key],))
            for key, label in PHASE_LEGEND
            if NIGHT_CONFIG.get(key)
        ]
        # Clickable switch between the two looks, right under the phase list.
        lines.append(
            SidebarLine(
                choices=tuple(look.upper() for look in LOOKS),
                choice_index=LOOKS.index(self.look),
                action="look",
            )
        )
        return lines

    def live_rows(self, title: str | None) -> list[tuple[str, str]]:
        """(label, value) rows for the CLOCK, SUN and MOON boxes. Computed
        fresh on every call, reflecting the selected time offset."""
        now = self._display_time()
        if title == "CLOCK":
            local = now.astimezone()
            return [
                ("DATE", f"{now:%Y-%m-%d}"),
                ("UTC", f"{now:%H:%M:%S}"),
                ("LOCAL", f"{local:%H:%M:%S} {local.tzname() or ''}".rstrip()),
                ("DAY", f"{now.timetuple().tm_yday} of year, week {now.isocalendar()[1]}"),
            ]
        if title == "SUN":
            return self._sun_rows(now)
        if title == "MOON":
            moon = moon_info(now)
            return [
                ("PHASE", moon["name"]),
                ("LIT", f"{moon['illumination'] * 100:.0f}%"),
                ("AGE", f"{moon['age']:.1f} days"),
                ("NEW IN", f"{moon['to_new']:.1f} days"),
                ("FULL IN", f"{moon['to_full']:.1f} days"),
            ]
        return []

    def _sun_rows(self, now: datetime) -> list[tuple[str, str]]:
        lat = self._center_lat
        lon = normalize_longitude(self._center_lon)
        declination, eq_time = solar_position(now)
        elevation = sun_elevation(lat, lon, now, declination, eq_time)
        minutes = now.hour * 60 + now.minute + now.second / 60
        solar_time = (minutes + eq_time + 4 * lon) % 1440
        subsolar_lon = normalize_longitude((720 - minutes - eq_time) / 4)
        rising = sunrise_sunset(lat, lon, declination, eq_time)

        rows = [
            ("CENTRE", f"{format_hemisphere(lat, 'N', 'S')} {format_hemisphere(lon, 'E', 'W')}"),
            ("PHASE", f"{sun_phase_name(elevation)} ({elevation:+.1f}\u00b0)"),
        ]
        if isinstance(rising, str):
            rows.append(("TIMES", rising))
        else:
            rise, sunset = rising
            day_length = (sunset - rise) % 1440
            rows += [
                ("RISE", f"{hhmm(rise)} UTC"),
                ("SET", f"{hhmm(sunset)} UTC"),
                ("LENGTH", f"{int(day_length // 60)}h{int(day_length % 60):02d}m"),
            ]
        rows += [
            ("SOLAR", f"{hhmm(solar_time)} solar time"),
            (
                "SUBSOLAR",
                f"{format_hemisphere(math.degrees(declination), 'N', 'S')} "
                f"{format_hemisphere(subsolar_lon, 'E', 'W')}",
            ),
        ]
        return rows

    # ------------------------------------------------------------------
    # Map shading
    # ------------------------------------------------------------------

    def _solar_elevation(self, view: View) -> np.ndarray:
        """Return a (pixel_height, pixel_width) array of true (geometric)
        solar elevation in degrees for every pixel in the current view,
        fully vectorized, using the shared NOAA/Meeus solar_position()."""
        now = self._display_time()
        declination, eq_time_minutes = solar_position(now)

        longitudes = (
            view.origin_lon
            + (np.arange(view.pixel_width, dtype=np.float64) + 0.5)
            / view.scale_x
        )
        latitudes = np.radians(
            view.origin_lat
            - (np.arange(view.pixel_height, dtype=np.float64) + 0.5)
            / view.scale_y
        )

        minutes_utc = now.hour * 60 + now.minute + now.second / 60
        true_solar_time = (minutes_utc + eq_time_minutes + 4 * longitudes) % 1440
        hour_angle = np.radians(true_solar_time / 4 - 180)

        cosine_zenith = (
            np.sin(latitudes)[:, None] * np.sin(declination)
            + np.cos(latitudes)[:, None]
            * np.cos(declination)
            * np.cos(hour_angle)[None, :]
        )
        return np.degrees(np.arcsin(np.clip(cosine_zenith, -1.0, 1.0))).astype(
            np.float32
        )

    @staticmethod

    def _water_seam_markers(
        view: View,
        elevation: np.ndarray,
        phase_colors: list,
        water_cells: np.ndarray,
    ) -> list[Marker]:
        """Smooth seams over open water. Instead of whole-cell blocks, the
        boundary between two phases is traced per braille dot (2x4 per cell),
        so the line follows the real curve of the terminator. Each seam dot
        sits on the lighter side of the boundary, in that phase's colour.
        Only cells in `water_cells` (no land or border pixels) are touched."""
        count = len(phase_colors)
        if not count:
            return []
        pixel_depth = np.full(elevation.shape, count, dtype=np.int16)
        for idx in reversed(range(count)):
            pixel_depth = np.where(elevation >= phase_colors[idx][0], idx, pixel_depth)
        seam = np.zeros(pixel_depth.shape, dtype=bool)
        seam[:, :-1] |= pixel_depth[:, 1:] > pixel_depth[:, :-1]
        seam[:, 1:] |= pixel_depth[:, :-1] > pixel_depth[:, 1:]
        seam[:-1, :] |= pixel_depth[1:, :] > pixel_depth[:-1, :]
        seam[1:, :] |= pixel_depth[:-1, :] > pixel_depth[1:, :]
        water_pixels = np.repeat(np.repeat(water_cells, 4, axis=0), 2, axis=1)
        markers: list[Marker] = []
        for idx, (_thresh, color) in enumerate(phase_colors):
            dots = seam & (pixel_depth == idx) & water_pixels
            if not dots.any():
                continue
            lines = view.to_lines(Image.fromarray(dots.astype(np.uint8) * 255))
            for y, row in enumerate(lines):
                for x, char in enumerate(row):
                    if char != BLANK_BRAILLE:
                        markers.append(Marker(x, y, color, glyph=char))
        return markers

    def _build(
        self,
        view: View,
        land_mask: Image.Image,
        country_image: Image.Image,
    ) -> LayerRender:
        elevation = self._solar_elevation(view)

        # Resolve colors from config once.
        phase_colors = [
            (thresh, NIGHT_CONFIG[key])
            for thresh, key in PHASE_THRESHOLDS
            if NIGHT_CONFIG.get(key)  # skip phases whose color is null/false
        ]
        count = len(phase_colors)

        # Per-CELL phase from the mean elevation of each cell. Seams are worked
        # out on this grid, not on pixels, so every seam is a clean chain of
        # whole cells: no staggered half-cells, no gaps, no two phases
        # fighting over the same cell. depth 0 = lightest phase ... count = night.
        cell_elevation = elevation.reshape(view.height, 4, view.width, 2).mean(axis=(1, 3))
        depth = np.full(cell_elevation.shape, count, dtype=np.int16)
        for idx in reversed(range(count)):
            depth = np.where(cell_elevation >= phase_colors[idx][0], idx, depth)

        # A seam cell is a cell with a darker neighbour (up / down / left /
        # right), so the line sits on the lighter side and takes its colour.
        seam = np.zeros(depth.shape, dtype=bool)
        seam[:, :-1] |= depth[:, 1:] > depth[:, :-1]
        seam[:, 1:] |= depth[:, :-1] > depth[:, 1:]
        seam[:-1, :] |= depth[1:, :] > depth[:-1, :]
        seam[1:, :] |= depth[:-1, :] > depth[1:, :]

        interior = np.asarray(land_mask) > 0
        border = np.asarray(country_image) > 0
        # Cells with no land / border pixel at all are open water: their seam is
        # drawn as a smooth dot-level curve instead of a whole-cell block.
        water_cells = ~(interior | border).reshape(view.height, 4, view.width, 2).any(axis=(1, 3))
        water_seam = self._water_seam_markers(view, elevation, phase_colors, water_cells)
        markers: list[Marker] = []

        if self.look == "fill":
            # Per-pixel phase index: lit land is stippled in its phase colour.
            phase_index = np.full(elevation.shape, -1, dtype=np.int8)
            for idx, (thresh, _color) in enumerate(phase_colors):
                phase_index = np.where(
                    (phase_index == -1) & (elevation >= thresh), idx, phase_index
                )
            for idx, (_thresh, color) in enumerate(phase_colors):
                rows, cols = np.nonzero(depth == idx)
                if not len(rows):
                    continue
                in_phase = phase_index == idx
                glyph_pixels = (interior & in_phase) | (border & ~in_phase)
                glyph_lines = view.to_lines(
                    Image.fromarray(glyph_pixels.astype(np.uint8) * 255)
                )
                for y, x in zip(rows.tolist(), cols.tolist()):
                    glyph = SEAM_GLYPH if seam[y, x] and not water_cells[y, x] else glyph_lines[y][x]
                    markers.append(Marker(x, y, color, glyph=glyph))
            markers.extend(water_seam)  # drawn last so the curve replaces the blank water cell
            return LayerRender(None, "#000000", markers)

        # "tint": a cell counts as land when at least half of its pixels are land
        # (or border) pixels; those cells get the phase colour as their background.
        land_cells = (interior | border).reshape(view.height, 4, view.width, 2).mean(axis=(1, 3)) >= 0.5
        bg_cells: dict[tuple[int, int], str] = {}
        for idx, (_thresh, color) in enumerate(phase_colors):
            rows, cols = np.nonzero(depth == idx)
            tint = _tint(color)
            for y, x in zip(rows.tolist(), cols.tolist()):
                if land_cells[y, x]:
                    bg_cells[(x, y)] = tint
                if seam[y, x] and not water_cells[y, x]:
                    markers.append(Marker(x, y, color, glyph=SEAM_GLYPH))
        markers.extend(water_seam)

        return LayerRender(None, "#000000", markers, bg_cells=bg_cells)
