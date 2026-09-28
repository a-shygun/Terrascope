# colors.py — TERMINAL COLOUR HANDLING
# Responsible for: turning hex colours ("#rrggbb") into curses colour pairs
# (ColorManager.get_pair, with optional background), using exact colours when
# the terminal supports it and falling back to the nearest 256/8-colour match.
# Edit this file to: fix colour problems on certain terminals or change the
# fallback behaviour. The actual colours used are chosen in ui.py / settings.

from __future__ import annotations
import curses

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


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    text = hex_color.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) != 6:
        raise ValueError(f"Invalid hex color: {hex_color!r}")
    red = int(text[0:2], 16)
    green = int(text[2:4], 16)
    blue = int(text[4:6], 16)
    return red, green, blue


def xterm_256_index_to_rgb(index: int) -> tuple[int, int, int]:
    if index < 16:
        return _XTERM_BASIC_16_RGB[index]
    if index < 232:
        index -= 16
        red = index // 36
        green = (index % 36) // 6
        blue = index % 6
        return (
            _XTERM_CUBE_LEVELS[red],
            _XTERM_CUBE_LEVELS[green],
            _XTERM_CUBE_LEVELS[blue]
        )
    level = 8 + (index - 232) * 10
    return (level, level, level)


def _nearest_by_distance(target: tuple[int, int, int], candidates) -> int:
    red, green, blue = target
    best_index = 0
    best_distance = None
    for index, (candidate_r, candidate_g, candidate_b) in candidates:
        distance = (
            (candidate_r - red) ** 2
            + (candidate_g - green) ** 2
            + (candidate_b - blue) ** 2
        )
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def rgb_to_nearest_xterm_256(rgb: tuple[int, int, int]) -> int:
    candidates = ((index, xterm_256_index_to_rgb(index)) for index in range(256))
    return _nearest_by_distance(rgb, candidates)


def rgb_to_nearest_basic(rgb: tuple[int, int, int]) -> int:
    basic_colors = (
        curses.COLOR_BLACK,
        curses.COLOR_RED,
        curses.COLOR_GREEN,
        curses.COLOR_YELLOW,
        curses.COLOR_BLUE,
        curses.COLOR_MAGENTA,
        curses.COLOR_CYAN,
        curses.COLOR_WHITE
    )
    candidates = ((color, _XTERM_BASIC_16_RGB[color]) for color in basic_colors)
    return _nearest_by_distance(rgb, candidates)


class ColorManager:
    FIRST_FREE_SLOT = 16

    def __init__(self) -> None:
        self.enabled = False
        self.supports_exact_color = False
        self._pair_by_hex: dict[str, int] = {}
        self._slot_by_hex: dict[str, int] = {}
        self._next_pair_id = 1
        self._next_color_slot = self.FIRST_FREE_SLOT

    def setup(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        self.enabled = True
        self.supports_exact_color = (
            curses.can_change_color() and curses.COLORS > self.FIRST_FREE_SLOT
        )

    def get_pair(self, hex_color: str, background: str | None = None) -> int:
        if not self.enabled:
            return 0
        fg = hex_color.strip().lower()
        bg = background.strip().lower() if background else None
        key = f"{fg}|{bg}"
        cached = self._pair_by_hex.get(key)
        if cached is not None:
            return cached
        attribute = self._create_pair(fg, bg)
        self._pair_by_hex[key] = attribute
        return attribute

    def _slot_for_hex(self, hex_color: str) -> int | None:
        """Resolve a hex colour to a terminal colour slot (cached per colour)."""
        cached = self._slot_by_hex.get(hex_color)
        if cached is not None:
            return cached
        try:
            rgb = hex_to_rgb(hex_color)
        except ValueError:
            return None
        slot = self._resolve_color_slot(rgb)
        self._slot_by_hex[hex_color] = slot
        return slot

    def _create_pair(self, hex_color: str, background: str | None = None) -> int:
        if self._next_pair_id >= curses.COLOR_PAIRS:
            return 0
        foreground = self._slot_for_hex(hex_color)
        if foreground is None:
            return 0
        bg_slot = -1
        if background:
            resolved = self._slot_for_hex(background)
            if resolved is not None:
                bg_slot = resolved
        pair_id = self._next_pair_id
        self._next_pair_id += 1
        try:
            curses.init_pair(pair_id, foreground, bg_slot)
        except curses.error:
            try:
                curses.init_pair(pair_id, foreground, curses.COLOR_BLACK)
            except curses.error:
                return 0
        return curses.color_pair(pair_id)

    def _resolve_color_slot(self, rgb: tuple[int, int, int]) -> int:
        if self.supports_exact_color and self._next_color_slot < curses.COLORS:
            slot = self._next_color_slot
            red, green, blue = rgb
            try:
                curses.init_color(
                    slot,
                    round(red / 255 * 1000),
                    round(green / 255 * 1000),
                    round(blue / 255 * 1000)
                )
                self._next_color_slot += 1
                return slot
            except curses.error:
                pass
        if curses.COLORS >= 256:
            return rgb_to_nearest_xterm_256(rgb)
        return rgb_to_nearest_basic(rgb)
