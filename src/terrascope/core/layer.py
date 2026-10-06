# layer.py — BASE CLASS FOR MAP LAYERS (flights, earthquakes, cities, ships, night)
# Responsible for: the Layer base class every data layer inherits from —
# enable/disable via its toggle key, background data refresh (threads, tick(),
# is_due), click hit-testing, selection, info-box rows, search/filter hooks —
# plus the Marker, LayerRender and SidebarLine data classes layers return.
# Edit this file to: change behaviour shared by ALL layers (refresh timing,
# click radius, toggling). To change one specific layer or add a new one, edit
# or create its file under terrascope/layers/ instead.

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from PIL import Image
from terrascope.core.config import CFG, FETCH_NEW_DATA_FROM_API

# Shared layer settings (hardcoded; edit here).
DEFAULT_INFO_TITLE = "INFO"  # info-box title for layers that don't set their own
CLICK_RADIUS = CFG["layer_defaults"]["click_radius"]  # how close a click must be to hit a marker
RETRY_BASE_SECONDS = CFG["layer_defaults"]["retry_base_seconds"]  # failed refresh: wait this long, then double...
RETRY_MAX_SECONDS = CFG["layer_defaults"]["retry_max_seconds"]  # ...up to this cap

if TYPE_CHECKING:
    from terrascope.core.view import View

@dataclass(frozen=True)
class InfoImage:
    """A picture drawn to the right of an info box's values. `lines` run top to
    bottom; each line is a sequence of (text, fg "#rrggbb" or None,
    bg "#rrggbb" or None) segments. `width` is the picture's width in columns."""

    width: int
    lines: tuple[tuple[tuple[str, str | None, str | None], ...], ...]

@dataclass
class Marker:
    x: int
    y: int
    color: str
    glyph: str | None = None
    label: str | None = None
    item: object = None
    selected: bool = False
    dim: bool = False  # draw faded (e.g. old earthquakes)
    # Explicit background colour for this one marker (e.g. a half-block cell
    # whose top and bottom half are different readings). None = the map's own
    # background (water/land/coastline fade) at that cell, as before.
    bg_color: str | None = None

@dataclass
class LayerRender:
    lines: list[str] | None
    line_color: str
    markers: list[Marker] = field(default_factory=list)
    # Background colour overrides, {(x, y): "#rrggbb"}: the map's own background
    # at these cells is replaced, so borders, labels and markers drawn there all
    # sit on that colour (e.g. the day / night tint of the land).
    bg_cells: dict[tuple[int, int], str] | None = None

@dataclass(frozen=True)
class PanelBox:
    """One box of the bottom row. A layer lists these in panel_layout.

    kind  "info":   details of the selected marker
          "search": shows / edits the search text (the / key)
          "filter": shows / edits the filter value (the O key)
          "live":   rows from the layer's live_rows(title), redrawn every frame
          "rich":   coloured text lines from the layer's rich_lines(title, width, height)
    ratio share of the row width (the last box takes whatever is left)
    title box title; for "live" boxes it is also passed to live_rows()
    """

    kind: str
    ratio: float
    title: str | None = None
    hint: str | None = None  # placeholder text of "search" / "filter" boxes

@dataclass(frozen=True)
class SliderSpec:
    """A slider drawn on the bottom row, left of the scale bar.

    label   short text in front of the track
    steps   number of positions (index 0 .. steps-1)
    index   current position
    caption short text after the track (e.g. "x60 +12m")
    marker  index of a special position (e.g. LIVE), drawn as a "|" on the track
    wide    True = give the track one column per step (if there is room), so
            every step can be hit with the mouse
    """

    label: str
    steps: int
    index: int
    caption: str = ""
    marker: int | None = None
    wide: bool = False
    status: str = ""  # short text drawn to the left of the label (e.g. "loading radar...")
    loaded_steps: tuple[int, ...] | None = None  # completed data frames, used to brighten radar ticks
    disabled: bool = False  # shown dimmed until history is available

@dataclass(frozen=True)
class SidebarLine:
    """One line of the map legend, right-aligned: the text, then one colour
    swatch (drawn with `swatch_glyph`) at the right end, so the swatches of
    consecutive lines form a column.  bold = a heading line."""

    text: str = ""
    swatches: tuple[str, ...] = ()
    legend_items: tuple[tuple[str, str, str], ...] = ()
    swatch_glyph: str = "\u25a0"
    bold: bool = False
    # A clickable toggle line: `choices` are drawn as "[ A | B ]" with the
    # choice at `choice_index` lit. Clicking the line calls the owning layer's
    # press_legend(action).
    choices: tuple[str, ...] = ()
    choice_index: int = 0
    action: str | None = None

class Layer:
    name = "layer"
    toggle_key = ""
    info_title = DEFAULT_INFO_TITLE
    enabled = True
    # Set True on a layer whose render_with_land() takes a third argument: the
    # country-outline image (border pixels), so it can tell borders from land.
    wants_country_image = False
    # Set by WorldMap.render() from the active tab: True = show full map detail
    # (the MAP tab), False = keep it minimal. Layers that have optional detail read it.
    detailed = True
    # Also set by WorldMap.render(): False = the basemap leaves out capital / city
    # names (the WEATHER tab labels cities itself).
    show_places = True
    # Also set by WorldMap.render(): False = no country names (WEATHER tab).
    show_countries = True
    # Layout of the bottom row while this layer is the tab's panel owner (the
    # first enabled layer of the tab that sets one). None = the default
    # (a single info box) from ui.py.
    panel_layout: tuple[PanelBox, ...] | None = None

    def __init__(self) -> None:
        self.dirty = True
        self.selected = None
        self.last_markers: list[Marker] = []
        self.lock = threading.Lock()
        self.refresh_in_progress = False
        self.refresh_completed = False
        # A failed background refresh keeps the last good data and retries
        # with backoff.
        self._failures = 0
        self._retry_at = 0.0

    def startup(self) -> None:
        # Load stale-but-useful cache immediately. Network refreshes begin from
        # tick() after the UI is live, so a slow API cannot hold up startup.
        self.reload()

    def prefetch(self) -> None:
        """Start optional live-data warming while the initial map is loading."""
        return

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
            and not getattr(self, "_ordered_startup", False)
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
            self._failures = 0
            self._retry_at = 0.0
        except Exception as error:
            # Swallow: an uncaught exception in a worker thread would print a
            # traceback straight onto the curses screen. Retry with backoff
            # (base, 2x base, 4x base ... capped; see RETRY_* above)
            # instead of every 50 ms.
            self._failures += 1
            self._retry_at = time.monotonic() + min(
                RETRY_MAX_SECONDS,
                RETRY_BASE_SECONDS * 2 ** (self._failures - 1),
            )
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

    def hit_test_all(
        self, x: int, y: int, radius: float | None = None
    ) -> list[tuple[float, object]]:
        """Return all markers close enough to a click, nearest first."""
        if radius is None:
            radius = CLICK_RADIUS
        hits = []
        for marker in self.last_markers:
            distance = math.hypot(marker.x - x, marker.y - y)
            if distance <= radius:
                hits.append((distance, marker.item))
        return sorted(hits, key=lambda hit: hit[0])

    def click_at(self, x: int, y: int) -> bool:
        """A click on map cell (x, y) before marker selection. Return True if
        the layer used it (e.g. toggling a label); the click then selects nothing."""
        return False

    def select(self, item) -> None:
        self.selected = item
        self.dirty = True

    def info_rows(self) -> list[tuple[str, str]]:
        return []

    def info_image(self, rows: int, max_cols: int) -> InfoImage | None:
        """Picture to draw to the right of info_rows(), at most `rows` rows and
        `max_cols` columns. None = no picture."""
        return None

    def live_rows(self, title: str | None) -> list[tuple[str, str]]:
        """(label, value) rows for the "live" panel box called `title`."""
        return []

    def rich_title(self, title: str | None) -> str:
        """Title of the "rich" panel box called `title` (override to add to it)."""
        return title or ""

    def rich_lines(
        self, title: str | None, width: int, height: int,
        vertical: bool = False, scroll: int = 0,
    ) -> list[list[tuple]]:
        """Lines of the "rich" panel box called `title`; `width` x `height` is
        the room inside its border. Each line is a list of (text, "#rrggbb" or
        None, style) pieces, style being "", "bold" or "dim". `vertical`
        indicates that the panel is in a left-side column; `scroll` is its
        vertical content offset."""
        return []

    def border_buttons(self) -> list[str]:
        """Labels of clickable buttons drawn on the map box's bottom border, next
        to the panel button, while this layer is on."""
        return []

    def press_border_button(self, index: int) -> None:
        """Called when button `index` of border_buttons() is clicked."""

    def press_legend(self, action: str) -> None:
        """Called when a legend line with this `action` (see SidebarLine) is clicked."""

    def slider(self) -> SliderSpec | None:
        """Return a SliderSpec to show a slider while this layer is on."""
        return None

    def loading_messages(self) -> list[str]:
        """Short loading notices to show in the map's upper-left corner."""
        return []

    def set_slider(self, index: int) -> None:
        """Called when the user moves the slider (mouse, [ and ] keys)."""

    def apply_search(self, text: str) -> None:
        pass

    def apply_filter(self, value: str | None) -> None:
        pass

    def filter_options(self) -> list[str]:
        return []

    def legend_lines(self) -> list[SidebarLine]:
        return []
