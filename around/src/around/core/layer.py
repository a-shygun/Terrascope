# layer.py — BASE CLASS FOR MAP LAYERS (flights, earthquakes, cities, ships, night)
# Responsible for: the Layer base class every data layer inherits from —
# enable/disable via its toggle key, background data refresh (threads, tick(),
# is_due), click hit-testing, selection, info-box rows, search/filter hooks —
# plus the Marker, LayerRender and SidebarLine data classes layers return.
# Edit this file to: change behaviour shared by ALL layers (refresh timing,
# click radius, toggling). To change one specific layer or add a new one, edit
# or create its file under around/layers/ instead.

from __future__ import annotations
import math
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from PIL import Image
from around.config import FETCH_NEW_DATA_FROM_API

if TYPE_CHECKING:
    from around.core.view import View


@dataclass
class Marker:
    x: int
    y: int
    color: str
    glyph: str | None = None
    label: str | None = None
    item: object = None
    selected: bool = False


@dataclass
class LayerRender:
    lines: list[str] | None
    line_color: str
    markers: list[Marker] = field(default_factory=list)


@dataclass(frozen=True)
class SidebarLine:
    text: str = ""
    swatches: tuple[str, ...] = ()
    key_index: int | None = None
    legend_items: tuple[tuple[str, str, str], ...] = ()


class Layer:
    name = "layer"
    toggle_key = ""
    order = 100
    info_title = "INFO"
    # Shown in the CONTROLS bar. Set these on a layer subclass to control its
    # label (must contain the toggle key letter) and colour; if left as None,
    # ui.py falls back to its legacy table / the layer name.
    control_label: str | None = None
    control_color: str | None = None
    enabled = True

    def __init__(self) -> None:
        self.dirty = True
        self.selected = None
        self.last_markers: list[Marker] = []
        self.lock = threading.Lock()
        self.refresh_in_progress = False
        self.refresh_completed = False
        # Set when a background refresh fails (network error, bad response...).
        # The layer keeps showing its last good data and retries with backoff.
        self.last_error: str | None = None
        self._failures = 0
        self._retry_at = 0.0

    def startup(self) -> None:
        # Load stale-but-useful cache immediately. Network refreshes begin from
        # tick() after the UI is live, so a slow API cannot hold up startup.
        self.reload()

    def tick(self) -> None:
        with self.lock:
            completed = self.refresh_completed
            self.refresh_completed = False
        if completed:
            # Apply snapshots on the UI thread. Rendering never observes a
            # worker halfway through replacing layer state.
            self.reload()
        if (
            self.enabled
            and FETCH_NEW_DATA_FROM_API
            and time.monotonic() >= self._retry_at
            and self.is_due()
        ):
            self.refresh_async()

    def is_due(self) -> bool:
        return False

    def refresh_if_due(self, force: bool = False) -> bool:
        return False

    def reload(self) -> None:
        pass

    def clear(self) -> None:
        pass

    def refresh_async(self) -> None:
        with self.lock:
            if self.refresh_in_progress:
                return
            self.refresh_in_progress = True
        thread = threading.Thread(target=self._refresh_worker, daemon=True)
        thread.start()

    def _refresh_worker(self) -> None:
        try:
            if self.refresh_if_due():
                with self.lock:
                    self.refresh_completed = True
            self.last_error = None
            self._failures = 0
            self._retry_at = 0.0
        except Exception as error:
            # Swallow: an uncaught exception in a worker thread would print a
            # traceback straight onto the curses screen. Retry with backoff
            # (15s, 30s, 60s ... capped at 5 min) instead of every 50 ms.
            self._failures += 1
            self.last_error = f"{type(error).__name__}: {error}"
            self._retry_at = time.monotonic() + min(300.0, 15.0 * 2 ** (self._failures - 1))
        finally:
            with self.lock:
                self.refresh_in_progress = False

    def toggle(self) -> None:
        self.enabled = not self.enabled
        if self.enabled:
            self.reload()
        else:
            self.clear()
        self.dirty = True

    def handle_key(self, key: int) -> bool:
        if (
            self.toggle_key
            and 0 <= key < 256
            and chr(key).lower() == self.toggle_key.lower()
        ):
            self.toggle()
            return True
        return False

    def render(self, view: View) -> LayerRender:
        self.dirty = False
        result = self.build(view)
        self.last_markers = result.markers
        return result

    def render_with_land(self, view: View, land_mask: Image.Image) -> LayerRender:
        return self.render(view)

    def build(self, view: View) -> LayerRender:
        raise NotImplementedError

    def hit_test(
        self, x: int, y: int, radius: float = 1.5
    ) -> tuple[float, object] | None:
        nearest = None
        nearest_distance = None
        for marker in self.last_markers:
            distance_x = marker.x - x
            distance_y = marker.y - y
            distance = math.sqrt(distance_x * distance_x + distance_y * distance_y)
            if distance > radius:
                continue
            if nearest_distance is None or distance < nearest_distance:
                nearest = marker.item
                nearest_distance = distance
        if nearest is None:
            return None
        return nearest_distance, nearest

    def hit_test_all(
        self, x: int, y: int, radius: float = 1.5
    ) -> list[tuple[float, object]]:
        """Return all markers close enough to a click, nearest first."""
        hits = []
        for marker in self.last_markers:
            distance = math.hypot(marker.x - x, marker.y - y)
            if distance <= radius:
                hits.append((distance, marker.item))
        return sorted(hits, key=lambda hit: hit[0])

    def select(self, item) -> None:
        self.selected = item
        self.dirty = True

    def info_rows(self) -> list[tuple[str, str]]:
        return []

    def apply_search(self, text: str) -> None:
        pass

    def apply_filter(self, value: str | None) -> None:
        pass

    def filter_options(self) -> list[str]:
        return []

    def shown_count(self) -> int:
        return 0

    def status_lines(self) -> list[SidebarLine]:
        return []

    def legend_lines(self) -> list[SidebarLine]:
        return []