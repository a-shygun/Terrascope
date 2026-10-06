# view.py — MAP MATH AND VIEWPORT -> PIXEL / TERMINAL CELL CONVERSION
# Responsible for: the pure map maths (calculate_viewport, viewport_aspect,
# project_location, visible, normalize_longitude, clamp_center) and the View
# class that turns lon/lat into pixel and cell positions for the current
# zoom/centre/terminal size, creates the drawing images, converts images to
# braille characters (2x4 dots per cell), and computes the smoothed per-cell
# land coverage used for water/land backgrounds.
# Settings (cell aspect, coastline blur, visible latitude band) come from
# default.yaml (map:).
# Edit this file to: change the projection, how the world wraps horizontally,
# panning limits, map resolution, braille rendering, or the softness of the
# coastline blur (to_cell_coverage).
# Not here: map state and drawing the map (world.py), colours (ui.py).

from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
from PIL import Image
from terrascope.core.config import CFG
from terrascope.core.mapdata import Ring

# --- fixed map settings (hardcoded; edit here) --------------------------------
MAP_CONFIG = CFG["map"]
CELL_ASPECT = float(MAP_CONFIG["cell_aspect"])  # terminal cell height / width
# Softness of the coastline fade: blur weights (longer / flatter = softer).
COAST_BLUR_HORIZONTAL = tuple(MAP_CONFIG["coast_blur_horizontal"])
COAST_BLUR_VERTICAL = tuple(MAP_CONFIG["coast_blur_vertical"])

# Visible latitude band. Antarctica is not loaded, so the map only needs to
# reach from the southern tip of South America up to northern Greenland.
LAT_MIN = float(MAP_CONFIG["lat_min"])
LAT_MAX = float(MAP_CONFIG["lat_max"])
LAT_RANGE = LAT_MAX - LAT_MIN
LAT_MID = (LAT_MAX + LAT_MIN) / 2

BRAILLE_BIT_ORDER = np.array([[0, 3], [1, 4], [2, 5], [6, 7]], dtype=np.uint8)
BRAILLE_BIT_WEIGHTS = (1 << BRAILLE_BIT_ORDER).astype(np.uint8)
BLANK_BRAILLE = "\u2800"

# ---------------------------------------------------------------------------
# Pure map maths (no drawing, no state)
# ---------------------------------------------------------------------------

WRAP_SHIFTS = (-360.0, 0.0, 360.0)

def visible(
    polygon: Ring,
    center_lon: float,
    center_lat: float,
    lon_span: float,
    lat_span: float,
) -> list[float]:
    _, min_lon, max_lon, min_lat, max_lat = polygon
    view_min_lon = center_lon - lon_span / 2
    view_max_lon = center_lon + lon_span / 2
    view_min_lat = center_lat - lat_span / 2
    view_max_lat = center_lat + lat_span / 2
    if max_lat < view_min_lat:
        return []
    if min_lat > view_max_lat:
        return []
    shifts = []
    for shift in WRAP_SHIFTS:
        shifted_min = min_lon + shift
        shifted_max = max_lon + shift
        if shifted_max < view_min_lon:
            continue
        if shifted_min > view_max_lon:
            continue
        shifts.append(shift)
    return shifts

def project_location(
    longitude: float,
    latitude: float,
    center_lon: float,
    center_lat: float,
    lon_span: float,
    lat_span: float,
    render_width: int,
    render_height: int,
) -> tuple[float, float] | None:
    relative_lon = (longitude - (center_lon - lon_span / 2)) % 360.0
    if relative_lon > lon_span:
        return None
    x = relative_lon / lon_span * render_width
    y = (center_lat + lat_span / 2 - latitude) / lat_span * render_height
    if x < 0 or x >= render_width or y < 0 or y >= render_height:
        return None
    return x, y

def calculate_viewport(zoom: float, aspect: float = 2.0) -> tuple[float, float]:
    """Latitude span always fills the full height of the view
    ((LAT_MAX - LAT_MIN) / zoom, i.e. 142 degrees fully zoomed out).
    Longitude span follows from `aspect` (physical width / height of the map
    area), so degrees are the same size horizontally and vertically. Tall
    windows show a narrow slice of the world; wide ones show more."""
    lat_span = LAT_RANGE / zoom
    lon_span = lat_span * aspect
    return lon_span, lat_span

def viewport_aspect(width: int, height: int, cell_aspect: float = 2.0) -> float:
    """Physical width/height of a width x height grid of terminal cells, where
    each cell is `cell_aspect` times taller than it is wide."""
    if height <= 0:
        return 2.0
    return width / (height * cell_aspect)

def normalize_longitude(longitude: float) -> float:
    return ((longitude + 180.0) % 360.0) - 180.0

def clamp_center(
    center_lon: float, center_lat: float, lon_span: float, lat_span: float
) -> tuple[float, float]:
    center_lon = normalize_longitude(center_lon)
    if lat_span >= LAT_RANGE - 1e-9:
        center_lat = LAT_MID
    else:
        half_lat = lat_span / 2
        center_lat = max(LAT_MIN + half_lat, min(LAT_MAX - half_lat, center_lat))
    return center_lon, center_lat

# ---------------------------------------------------------------------------
# View: viewport -> pixels / terminal cells
# ---------------------------------------------------------------------------

def _blur(values: np.ndarray, axis: int, kernel: tuple[float, ...]) -> np.ndarray:
    weights = np.asarray(kernel, dtype=np.float32)
    weights /= weights.sum()
    radius = len(weights) // 2
    pad = [(0, 0), (0, 0)]
    pad[axis] = (radius, radius)
    padded = np.pad(values, pad, mode="edge")
    length = values.shape[axis]
    result = np.zeros_like(values)
    for offset, weight in enumerate(weights):
        result += weight * np.take(padded, range(offset, offset + length), axis=axis)
    return result

@dataclass
class View:
    center_lon: float
    center_lat: float
    zoom: float
    width: int
    height: int
    lon_span: float = field(init=False)
    lat_span: float = field(init=False)
    pixel_width: int = field(init=False)
    pixel_height: int = field(init=False)
    scale_x: float = field(init=False)
    scale_y: float = field(init=False)
    origin_lon: float = field(init=False)
    origin_lat: float = field(init=False)
    aspect: float = field(init=False)

    def __post_init__(self) -> None:
        self.aspect = viewport_aspect(
            self.width, self.height, CELL_ASPECT
        )
        self.lon_span, self.lat_span = calculate_viewport(self.zoom, self.aspect)
        self.pixel_width = self.width * 2
        self.pixel_height = self.height * 4
        self.scale_x = self.pixel_width / self.lon_span
        self.scale_y = self.pixel_height / self.lat_span
        self.origin_lon = self.center_lon - self.lon_span / 2
        self.origin_lat = self.center_lat + self.lat_span / 2

    def new_image(self) -> Image.Image:
        return Image.new("L", (self.pixel_width, self.pixel_height), 0)

    def _cell_array(self, image: Image.Image, dtype) -> np.ndarray:
        """A (height, 4, width, 2) array of an image's 2x4 sub-pixels per
        terminal cell, resizing first if the image isn't already pixel-sized.
        Shared by to_lines (braille bits) and to_cell_coverage (land/water)."""
        expected = (self.width * 2, self.height * 4)
        if image.size != expected:
            image = image.resize(expected)
        array = np.asarray(image.convert("1"), dtype=dtype)
        return array.reshape(self.height, 4, self.width, 2)

    def to_lines(self, image: Image.Image) -> list[str]:
        array = self._cell_array(image, np.uint8)
        weights = BRAILLE_BIT_WEIGHTS[np.newaxis, :, np.newaxis, :]
        values = (array * weights).sum(axis=(1, 3))
        # Braille block starts at U+2800; decode each row in one go.
        codes = np.ascontiguousarray(values + 0x2800, dtype="<u2")
        return [row.tobytes().decode("utf-16-le") for row in codes]

    def to_cell_coverage(self, image: Image.Image, smooth: bool = True) -> np.ndarray:
        """Return a (height, width) float array in 0..1: the fraction of each
        cell's 2x4 sub-pixels set in `image`, optionally blurred so land/water
        transitions spread over a few cells instead of a hard edge."""
        coverage = self._cell_array(image, np.float32).mean(axis=(1, 3))
        if smooth:
            # Cells are about twice as tall as wide, so blur wider horizontally.
            coverage = _blur(
                coverage, axis=1, kernel=COAST_BLUR_HORIZONTAL
            )
            coverage = _blur(
                coverage, axis=0, kernel=COAST_BLUR_VERTICAL
            )
        return coverage

    def to_pixel(
        self, longitude: float, latitude: float, shift: float = 0.0
    ) -> tuple[float, float]:
        x = (longitude + shift - self.origin_lon) * self.scale_x
        y = (self.origin_lat - latitude) * self.scale_y
        return x, y

    def project(self, longitude: float, latitude: float) -> tuple[float, float] | None:
        return project_location(
            longitude,
            latitude,
            self.center_lon,
            self.center_lat,
            self.lon_span,
            self.lat_span,
            self.width,
            self.height,
        )

    def to_cell(self, longitude: float, latitude: float) -> tuple[int, int] | None:
        position = self.project(longitude, latitude)
        if position is None:
            return None
        cell_x = int(position[0])
        cell_y = int(position[1])
        if cell_x < 0 or cell_x >= self.width:
            return None
        if cell_y < 0 or cell_y >= self.height:
            return None
        return cell_x, cell_y