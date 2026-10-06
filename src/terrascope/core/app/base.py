from __future__ import annotations

from .input import InputMixin
from .lifecycle import LifecycleMixin
from .mouse import MouseMixin
from .rendering import RenderingMixin
from .runtime import RuntimeMixin
from .timezone import TimezoneMixin
from .shared import (
    ColorManager,
    Frame,
    PANEL_VISIBLE_AT_START,
    PANEL_ORIENTATION_AT_START,
    START_TAB,
    SimpleQueue,
    WorldMap,
    _saved_province_choice,
    _welcome_skipped
)

class TerrascopeApp(LifecycleMixin, MouseMixin, TimezoneMixin, InputMixin, RenderingMixin, RuntimeMixin):
    def __init__(
        self, stdscr, world: WorldMap, forced_off: frozenset[str] = frozenset()
    ) -> None:
        self.stdscr = stdscr
        self.world = world
        # Layers switched off with --disable-layer stay off whatever the tab says.
        self.forced_off = forced_off
        self.active_tab = START_TAB
        self.province_choice = _saved_province_choice()
        self.province_state = "idle"  # idle | loading | ready | failed; never fetched unless enabled
        self.province_error = ""
        self.provinces_visible = False
        self.running = True
        self.colors = ColorManager()
        self._colors_reset_at = 0.0
        self.mode = "normal"
        self.filter_buffer = ""
        self.search_buffer = ""
        self.frame: Frame | None = None
        self._frame_size: tuple[int, int] | None = None
        self.info_visible = False
        self.panel_visible = PANEL_VISIBLE_AT_START
        self.panel_orientation = PANEL_ORIENTATION_AT_START
        self.map_data_queue: SimpleQueue = SimpleQueue()
        self.map_loading = False
        self.map_error = ""
        self.map_statuses: dict[str, str] = {}
        self._map_data_received = False
        self._original_stderr = None
        self._log_file = None
        # Left-button drag in progress: [last_x, last_y, start_x, start_y, moved, last_event_time]
        self._drag: list | None = None
        self._slider_drag = False
        # Clickable legend lines (e.g. the TINT / FILL toggle), set by draw()
        # each frame: (screen row, first x, end x, action).
        self._legend_hits: list[tuple[int, int, int, str]] = []
        self._province_prompt_hits: list[tuple[int, int, int, bool]] = []
        self._status_hits: list[tuple[int, int, int, str, str]] = []
        self.radar_status_expanded = True
        self.dismissed_statuses: set[str] = set()
        self.filter_scroll = 0
        self.filter_selected: set[str] = set()
        # Welcome modal: shown at launch, reopened with "?" or by clicking its
        # control; _welcome_rect / _welcome_link are set by draw() each frame
        # so mouse clicks can be tested against what's actually on screen.
        self.welcome_visible = not _welcome_skipped()
        self._welcome_rect: tuple[int, int, int, int] | None = None
        self._welcome_link = None
        self._welcome_button = None
        self._welcome_province_yes = None
        self._welcome_province_no = None
        # Controls bar (top-right): collapsed to the clock by default.
        self.controls_expanded = False
        self._controls_layout = None
        self.forecast_scroll = 0
        self._forecast_city_key = None
        # Timezone dropdown, opened by clicking the clock.
        self.tz_dropdown_open = False
        self.selected_timezone: str | None = None  # None = local system time
        self.tz_query = ""  # text typed into the dropdown's search row
        self.tz_index = 0  # highlighted entry of timezone_choices(tz_query)
        self._dropdown_layout = None
        self.select_tab(START_TAB)
        if self.province_choice == "yes":
            self._start_province_download()
