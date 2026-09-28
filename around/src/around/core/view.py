# view.py — VIEWPORT -> PIXEL / TERMINAL CELL CONVERSION
# Responsible for: the View class that turns lon/lat into pixel and cell
# positions for the current zoom/centre/terminal size, creates the drawing
# images, converts images to braille characters (2x4 dots per cell), and
# computes the smoothed per-cell land coverage used for water/land backgrounds.
# Edit this file to: change map resolution, braille rendering, or the softness
# of the coastline blur (to_cell_coverage).
# Not here: the projection maths itself (projection.py), colours (ui.py).

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from around.core.projection import calculate_viewport, project_location

BRAILLE_BIT_ORDER = np.array([[0, 3], [1, 4], [2, 5], [6, 7]], dtype=np.uint8)
BRAILLE_BIT_WEIGHTS = (1 << BRAILLE_BIT_ORDER).astype(np.uint8)
BLANK_BRAILLE = "\u2800"


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

    def __post_init__(self) -> None:
        self.lon_span, self.lat_span = calculate_viewport(self.zoom)
        self.pixel_width = self.width * 2
        self.pixel_height = self.height * 4
        self.scale_x = self.pixel_width / self.lon_span
        self.scale_y = self.pixel_height / self.lat_span
        self.origin_lon = self.center_lon - self.lon_span / 2
        self.origin_lat = self.center_lat + self.lat_span / 2

    def new_image(self) -> Image.Image:
        return Image.new("L", (self.pixel_width, self.pixel_height), 0)

    def to_lines(self, image: Image.Image) -> list[str]:
        expected = (self.width * 2, self.height * 4)
        if image.size != expected:
            image = image.resize(expected)
        array = np.asarray(image.convert("1"), dtype=np.uint8)
        array = array.reshape(self.height, 4, self.width, 2)
        weights = BRAILLE_BIT_WEIGHTS[np.newaxis, :, np.newaxis, :]
        values = (array * weights).sum(axis=(1, 3))
        # Braille block starts at U+2800; decode each row in one go.
        codes = np.ascontiguousarray(values + 0x2800, dtype="<u2")
        return [row.tobytes().decode("utf-16-le") for row in codes]

    def to_cell_coverage(self, image: Image.Image, smooth: bool = True) -> np.ndarray:
        """Return a (height, width) float array in 0..1: the fraction of each
        cell's 2x4 sub-pixels set in `image`, optionally blurred so land/water
        transitions spread over a few cells instead of a hard edge."""
        expected = (self.width * 2, self.height * 4)
        if image.size != expected:
            image = image.resize(expected)
        array = np.asarray(image.convert("1"), dtype=np.float32)
        array = array.reshape(self.height, 4, self.width, 2)
        coverage = array.mean(axis=(1, 3))
        if smooth:
            # Cells are about twice as tall as wide, so blur wider horizontally.
            coverage = _blur(coverage, axis=1, kernel=(1, 2, 3, 2, 1))
            coverage = _blur(coverage, axis=0, kernel=(1, 2, 1))
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
