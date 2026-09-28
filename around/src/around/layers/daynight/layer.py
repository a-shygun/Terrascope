from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np
from PIL import Image

from around.config import MAP_CONFIG
from around.core.colors import hex_to_rgb
from around.core.layer import Layer, LayerRender, Marker
from around.core.view import View


class DayNightLayer(Layer):
    """Trace the day/night seam and dot-fill daylight over land."""

    name = "night"
    toggle_key = "n"
    order = 5
    info_title = "DAY / NIGHT"
    enabled = False

    def __init__(self) -> None:
        super().__init__()
        self._last_update = time.monotonic()

    def tick(self) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self._last_update >= 60:
            self._last_update = now
            self.dirty = True

    def build(self, view: View) -> LayerRender:
        return self._build(view, None)

    def render_with_land(self, view: View, land_mask: Image.Image) -> LayerRender:
        self.dirty = False
        result = self._build(view, land_mask)
        self.last_markers = result.markers
        return result

    def hit_test_all(self, x: int, y: int, radius: float = 1.5):
        # Stipple markers are purely visual and must not be selectable.
        return []

    def _build(self, view: View, land_mask: Image.Image | None) -> LayerRender:
        now = datetime.now(timezone.utc)
        day_of_year = now.timetuple().tm_yday
        declination = np.radians(
            23.44 * np.sin(2 * np.pi * (284 + day_of_year) / 365.0)
        )
        utc_hour = now.hour + now.minute / 60 + now.second / 3600
        subsolar_lon = np.radians((180.0 - utc_hour * 15.0 + 180.0) % 360.0 - 180.0)

        longitudes = np.radians(
            view.origin_lon
            + (np.arange(view.pixel_width, dtype=np.float32) + 0.5)
            / view.scale_x
        )
        latitudes = np.radians(
            view.origin_lat
            - (np.arange(view.pixel_height, dtype=np.float32) + 0.5)
            / view.scale_y
        )
        hour_angle = longitudes - subsolar_lon
        cosine_zenith = (
            np.sin(latitudes)[:, None] * np.sin(declination)
            + np.cos(latitudes)[:, None]
            * np.cos(declination)
            * np.cos(hour_angle)[None, :]
        )

        pixels = np.zeros(cosine_zenith.shape, dtype=np.uint8)
        pixels[np.abs(cosine_zenith) < 0.025] = 255
        lines = view.to_lines(Image.fromarray(pixels))
        border_rgb = hex_to_rgb(MAP_CONFIG["country_color"])
        day_color = "#" + "".join(f"{255 - channel:02x}" for channel in border_rgb)
        markers = []
        if land_mask is not None:
            land = np.asarray(land_mask, dtype=np.uint8)
            for y in range(view.height):
                pixel_y = min(view.pixel_height - 1, y * 4 + 2)
                for x in range(view.width):
                    pixel_x = min(view.pixel_width - 1, x * 2 + 1)
                    if (
                        land[pixel_y, pixel_x]
                        and cosine_zenith[pixel_y, pixel_x] > 0.025
                    ):
                        markers.append(Marker(x, y, day_color, glyph="."))
        return LayerRender(lines, "#8194a8", markers)
