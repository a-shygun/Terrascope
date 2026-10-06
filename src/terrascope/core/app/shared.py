"""Settings and shared helpers for the terminal application mixins."""
from __future__ import annotations

import curses
import sys
import time
import webbrowser
from queue import Empty, SimpleQueue
from threading import Thread
from terrascope.core.config import CACHE_DIR, CFG
from terrascope.core.layer import PanelBox
from terrascope.core.ui import (
    GITHUB_URL,
    MAP_EDGE_PAD_Y,
    ColorManager,
    Layout,
    concise_error_message,
    compute_layout,
    current_time_text,
    draw_dropdown,
    draw_info_box,
    draw_live_box,
    draw_rich_box,
    draw_text_box,
    draw_tab_bar,
    draw_welcome_modal,
    draw_map_box,
    draw_map_overlay_text,
    dropdown_rect,
    info_arrow_positions,
    panel_button_slot,
    safe_addstr,
    draw_box,
    slider_track,
    tab_slots,
    timezone_choices,
)
from terrascope.core.tabs import START_TAB, TABS
from terrascope.core.mapdata import PROVINCE_FILE, download_progress, startup_progress
from terrascope.core.world import Frame, WorldMap

APP_CONFIG = CFG["app"]
RESIZE_SETTLE_SECONDS = 0.3
PANEL_VISIBLE_AT_START = bool(APP_CONFIG["panel_visible_at_start"])
MIN_TERMINAL_WIDTH = APP_CONFIG["min_terminal_width"]
MIN_TERMINAL_HEIGHT = APP_CONFIG["min_terminal_height"]
MAX_KEYS_PER_LOOP = APP_CONFIG["max_keys_per_loop"]
HEARTBEAT_SECONDS = APP_CONFIG["heartbeat_seconds"]
FRAME_DELAY_MS = APP_CONFIG["frame_delay_ms"]
LOG_FILE = APP_CONFIG["log_file"]
ARROW_HIT_TOLERANCE = APP_CONFIG["arrow_hit_tolerance"]
SCROLL_UP = curses.BUTTON4_PRESSED
SCROLL_DOWN = getattr(curses, "BUTTON5_PRESSED", 0)
MOUSE_MASK = (
    curses.BUTTON1_PRESSED
    | curses.BUTTON1_RELEASED
    | curses.REPORT_MOUSE_POSITION
    | SCROLL_UP
    | SCROLL_DOWN
)
MOUSE_MOTION_ON = "\033[?1003l\033[?1002h\033[?1006h"
MOUSE_MOTION_OFF = "\033[?1006l\033[?1002l\033[?1003l"
DRAG_RESUME_SECONDS = APP_CONFIG["drag_resume_seconds"]
DRAG_FRAME_DELAY_MS = APP_CONFIG["drag_frame_delay_ms"]
COLOR_RESET_MIN_SECONDS = 3.0
TERMINAL_TOO_SMALL_TEXT = "Terminal too small"
LOADING_MAP_TEXT = "Loading map data; first run may download Natural Earth files..."
STATUS_OFFSET = tuple(APP_CONFIG["status_offset"])
WELCOME_SKIP_FILE = APP_CONFIG["welcome_skip_file"]
PROVINCE_CHOICE_FILE = "province-borders-choice"

def _welcome_skipped() -> bool:
    return (CACHE_DIR / WELCOME_SKIP_FILE).exists()

def _skip_welcome_at_launch() -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / WELCOME_SKIP_FILE).write_text("1", encoding="utf-8")
    except OSError:
        pass

def _saved_province_choice() -> str | None:
    try:
        choice = (CACHE_DIR / PROVINCE_CHOICE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return choice if choice in {"yes", "no"} else None

def _chars(spec) -> set[int]:
    codes: set[int] = set()
    for char in spec:
        codes.add(ord(str(char).lower()))
        codes.add(ord(str(char).upper()))
    return codes

_KEY_CONFIG = APP_CONFIG["keys"]
KEYS = {
    "quit": _chars(_KEY_CONFIG["quit"]),
    "redraw": {12},
    "clear": {27},
    "toggle_panel": _chars(_KEY_CONFIG["toggle_panel"]),
    "search": _chars(_KEY_CONFIG["search"]),
    "filter": _chars(_KEY_CONFIG["filter"]),
    "about": _chars(_KEY_CONFIG["about"]),
    "prev_selection": _chars(_KEY_CONFIG["prev_selection"]),
    "next_selection": _chars(_KEY_CONFIG["next_selection"]),
    "pan_up": {curses.KEY_UP, *_chars(_KEY_CONFIG["pan_up"])},
    "pan_down": {curses.KEY_DOWN, *_chars(_KEY_CONFIG["pan_down"])},
    "pan_left": {curses.KEY_LEFT, *_chars(_KEY_CONFIG["pan_left"])},
    "pan_right": {curses.KEY_RIGHT, *_chars(_KEY_CONFIG["pan_right"])},
    "zoom_in": _chars(_KEY_CONFIG["zoom_in"]),
    "zoom_out": _chars(_KEY_CONFIG["zoom_out"]),
    "reset_view": _chars(_KEY_CONFIG["reset_view"]),
    "slider_down": _chars(_KEY_CONFIG["slider_down"]),
    "slider_up": _chars(_KEY_CONFIG["slider_up"]),
    "confirm": {10, 13, curses.KEY_ENTER},
    "cancel": {27},
    "backspace": {curses.KEY_BACKSPACE, 127, 8},
}

__all__ = [name for name in globals() if not name.startswith("__")]
