from __future__ import annotations

import curses
import math
import sys
import textwrap
from dataclasses import dataclass, replace
from functools import lru_cache
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones
import numpy as np
from terrascope.core.config import CFG
from terrascope.core.layer import DEFAULT_INFO_TITLE, InfoImage, Layer, PanelBox, SliderSpec
from terrascope.core.tabs import TABS
from terrascope.core.view import BLANK_BRAILLE

if TYPE_CHECKING:
    from terrascope.core.world import Frame

MAP_CONFIG = CFG["map"]

UI = CFG["ui"]

TERMINAL_CONFIG = CFG["terminal"]

def _first_key(value) -> str:
    return str(value[0] if isinstance(value, (list, tuple)) else value)

QUIT_KEY = _first_key(CFG["app"]["keys"]["quit"]).upper()

PANEL_KEY = _first_key(CFG["app"]["keys"]["toggle_panel"]).upper()

OUTER_MARGIN = tuple(UI["outer_margin"])

LAYER_BAR_HEIGHT = UI["tab_bar_height"]

LAYER_TAB_GAP = UI["tab_gap"]

PANEL_HEIGHT = UI["panel_height"]

PANEL_WIDTH = 32

PANEL_MIN_HEIGHT = UI["panel_min_height"]

PANEL_MIN_MAP_HEIGHT = UI["panel_min_map_height"]

BOX_GAP = UI["box_gap"]

DEFAULT_PANEL_LAYOUT = (PanelBox("info", 1.0),)

LIVE_BOX_MAX_LABEL_WIDTH = UI["live_box_max_label_width"]

INFO_BOX_MIN_WIDTH = UI["info_box_min_width"]

INFO_BOX_LABEL_WIDTH = UI["info_box_label_width"]

KM_PER_DEGREE_LAT = 111.32

SCALE_BAR_TARGET_COLUMNS = UI["scale_bar_target_columns"]

SCALE_BAR_MIN_COLUMNS = UI["scale_bar_min_columns"]

SCALE_BAR_MIN_BAR_COLUMNS = UI["scale_bar_min_bar_columns"]

MAP_EDGE_PAD_X = UI["map_edge_pad_x"]

MAP_EDGE_PAD_Y = max(0, UI["map_edge_pad_y"]) + 1

SLIDER_TRACK_COLUMNS = UI["slider_track_columns"]

SLIDER_CAPTION_WIDTH = UI["slider_caption_width"]

SLIDER_KNOB = UI["slider_knob"]

SLIDER_FILLED = UI["slider_filled"]

SLIDER_EMPTY = UI["slider_empty"]

EDGE_STEPS = int(MAP_CONFIG["coast_fade_steps"])

HELP_ITEMS = (
    ("WASD/ARROWS", "PAN", None),
    ("+/-/0", "ZOOM", None),
    ("?", "ABOUT", "about"),
    (QUIT_KEY, "QUIT", "quit"),
)

HELP_SHORT_KEYS = {"WASD/ARROWS": "WASD"}

HELP_SEPARATOR = UI["help_separator"]

HELP_MIN_GAP = UI["help_min_gap"]

LEGEND_TEXT_COLOR = UI["legend_text_color"]

MAP_BOX_TITLE = "WORLD MAP"

PANEL_BUTTON_SHOW = f"[{PANEL_KEY}] SHOW PANEL"

PANEL_BUTTON_HIDE = f"[{PANEL_KEY}] HIDE PANEL"

INFO_PLACEHOLDER = ("CLICK A MARKER", "", "to inspect its", "information.")

_BOX = dict(UI["box_chars"])

_SCALE_SYMBOLS = {"end": UI["scale_bar_end"], "fill": UI["scale_bar_fill"]}

INFO_IMAGE_GAP = 2

INFO_IMAGE_MIN_VALUE_WIDTH = 16

_XTERM_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)

_XTERM_BASIC_16_RGB = (
    (0, 0, 0),
    (205, 0, 0),
    (0, 205, 0),
    (205, 205, 0),
    (0, 0, 238),
    (205, 0, 205),
    (0, 205, 205),
    (229, 229, 229),
    (127, 127, 127),
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (92, 92, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255)
)

Rect = tuple[int, int, int, int]

CONTROLS_GAP = UI["controls_gap"]

CONTROLS_COLLAPSED_BUTTON = UI["controls_collapsed_button"]

CONTROLS_EXPANDED_BUTTON = UI["controls_expanded_button"]

TIMEZONE_OPTIONS: tuple[tuple[str, str | None], ...] = tuple(
    (str(label), zone) for label, zone in UI["timezones"]
)

DROPDOWN_TITLE = "TIMEZONE"

DROPDOWN_WIDTH = min(UI["dropdown_width"], 34)

DROPDOWN_PADDING_X = UI.get("dropdown_padding_x", 1)

DROPDOWN_PADDING_Y = UI.get("dropdown_padding_y", 0)

DROPDOWN_MARGIN_X = UI.get("dropdown_margin_x", 1)

DROPDOWN_MARGIN_Y = UI.get("dropdown_margin_y", 0)

DROPDOWN_MAX_HEIGHT = min(UI["dropdown_max_height"], 14)

DROPDOWN_MIN_HEIGHT = min(UI["dropdown_min_height"], 8)

DROPDOWN_PLACEHOLDER = "> search all timezones"

DROPDOWN_ACTIVE_MARK = "\u25cf "

DROPDOWN_INACTIVE_MARK = "  "

DROPDOWN_NO_MATCH = "no match"

_IGNORED_ZONE_PREFIXES = ("Etc/", "posix/", "right/")

GITHUB_URL = UI["github_url"]

BANNER_TEXT = "terrascope"

BANNER_ROWS = 7

BANNER_FILL = UI["banner_fill"]

BANNER_COLOR = UI["banner_color"]

LINK_COLOR = UI["link_color"]

TERRA_COLOR = "#ffffff"

SCOPE_COLOR = LINK_COLOR

MODAL_BG_COLOR = None

MODAL_BORDER_COLOR = "#ffffff"

MODAL_TEXT_COLOR = UI["modal_text_color"]

MODAL_DIM_COLOR = UI["modal_dim_color"]

_BANNER_FONT: dict[str, tuple[str, ...]] = {
    "T": ("XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "..X.."),
    "E": ("XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"),
    "R": ("XXXX.", "X...X", "X...X", "XXXX.", "X.X..", "X..X.", "X...X"),
    "A": (".XXX.", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"),
    "S": (".XXXX", "X....", "X....", ".XXX.", "....X", "....X", "XXXX."),
    "C": (".XXXX", "X....", "X....", "X....", "X....", "X....", ".XXXX"),
    "O": (".XXX.", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."),
    "P": ("XXXX.", "X...X", "X...X", "XXXX.", "X....", "X....", "X...."),
}

WELCOME_TAGLINE = "A live map of the world, drawn in braille, right in your terminal."

WELCOME_DISMISS_HINT = "Esc/click outside: close"

WELCOME_REOPEN_HINT = "? to reopen this guide"

WELCOME_SKIP_BUTTON = "[ DON'T SHOW AGAIN ]"

MODAL_PADDING_X = max(4, int(UI["modal_padding_x"]))

MODAL_PADDING_Y = max(2, int(UI["modal_padding_y"]))

MODAL_MARGIN_X = max(2, int(UI["modal_margin_x"]))

MODAL_MARGIN_Y = max(1, int(UI["modal_margin_y"]))

MODAL_CONTENT: tuple[tuple[str, str | None], ...] = (
    ("EXPLORE", None),
    ("@tabs", None),
    ("", None),
    ("CONTROLS", None),
    ("WASD / arrows pan   ·   + / - zoom   ·   0 reset   ·   drag to pan", "text"),
    ("/ search   ·   O filter   ·   Esc clear   ·   H panel   ·   Q quit", "text"),
    ("Click markers to inspect them; use < and > when markers overlap.", "text"),
)

SHADE_GLYPHS = ("\u2591", "\u2592", "\u2593")

SHADE_MIN_DENSITY = 0.12

SHADE_SOLID_DENSITY = 0.87

OSM_CREDIT = "\u00a9 OpenStreetMap contributors"


__all__ = [name for name in globals() if not name.startswith("__")]
