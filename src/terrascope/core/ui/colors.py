"""Terminal colors and curses color-pair allocation."""

from __future__ import annotations

from .constants import (
    TERMINAL_CONFIG,
    _XTERM_BASIC_16_RGB,
    _XTERM_CUBE_LEVELS,
    curses,
    sys
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

def rgb_to_nearest_xterm_256(rgb: tuple[int, int, int], exclude=()) -> int:
    """Nearest standard xterm colour, skipping slots the app redefined itself."""
    candidates = (
        (index, xterm_256_index_to_rgb(index))
        for index in range(256)
        if index not in exclude
    )
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

def _rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return sum((x - y) ** 2 for x, y in zip(a, b))

class ColorManager:
    """Hex colours -> curses colour pairs.

    Curses keeps the pair number in only 8 bits of each screen cell's
    attributes, so pair ids above 255 spill into the reverse / dim / blink bits
    (the white and green blocks, reversed letters). The number of pairs handed
    out is therefore capped, and once the budget is used up a new colour
    combination reuses the closest existing pair instead of a bogus id.
    """

    FIRST_FREE_SLOT = 16

    def __init__(self) -> None:
        self.enabled = False
        self.supports_exact_color = False
        # True once a colour pair or palette slot had to be reused because the
        # budget ran out (cells then get a "closest" colour, often with a wrong
        # background). The app calls reset() to start from a clean slate.
        self.exhausted = False
        self._pair_by_hex: dict[str, int] = {}
        self._pair_colors: dict[str, tuple] = {}  # key -> (fg rgb, bg rgb or None)
        self._slot_by_hex: dict[str, int] = {}
        self._redefined: set[int] = set()  # palette slots this app changed
        self._next_pair_id = 1
        self._pair_limit = 256  # pair ids 1 .. limit-1 may be used
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
        wanted = bool(TERMINAL_CONFIG.get("redefine_palette", True))
        self.supports_exact_color = (
            wanted and curses.can_change_color() and curses.COLORS > self.FIRST_FREE_SLOT
        )
        limit = min(curses.COLOR_PAIRS, (curses.A_COLOR >> 8) + 1)
        configured = TERMINAL_CONFIG.get("max_color_pairs")
        if configured:
            limit = min(limit, int(configured) + 1)
        self._pair_limit = max(2, limit)

    def reset(self) -> None:
        """Forget every colour PAIR handed out so far, so the pair budget is free
        again for whatever is on screen now. ncurses repaints the cells of a
        redefined pair on the next refresh, so no forced repaint is needed.

        Palette SLOTS are deliberately kept: redefining a slot (init_color) is
        applied by the terminal immediately, which recolours everything still on
        screen for a moment (the glitch seen when switching tabs). There are ~240
        slots, far more than the distinct colours the app uses; the scarce
        resource is the ~255 pairs."""
        self._pair_by_hex.clear()
        self._pair_colors.clear()
        self._next_pair_id = 1
        self.exhausted = False

    def restore(self) -> None:
        """Put the terminal's palette back if it was redefined (xterm OSC 104)."""
        if self._redefined and sys.stdout.isatty():
            try:
                sys.stdout.write("\033]104\007")
                sys.stdout.flush()
            except OSError:
                pass
            self._redefined.clear()

    def get_pair(self, hex_color: str, background: str | None = None) -> int:
        if not self.enabled:
            return 0
        fg = hex_color.strip().lower()
        bg = background.strip().lower() if background else None
        key = f"{fg}|{bg}"
        cached = self._pair_by_hex.get(key)
        if cached is not None:
            return cached
        attribute = self._create_pair(key, fg, bg)
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

    def _create_pair(self, key: str, hex_color: str, background: str | None = None) -> int:
        try:
            fg_rgb = hex_to_rgb(hex_color)
            bg_rgb = hex_to_rgb(background) if background else None
        except ValueError:
            return 0
        if self._next_pair_id >= self._pair_limit:
            self.exhausted = True
            return self._closest_pair(fg_rgb, bg_rgb)
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
        attribute = curses.color_pair(pair_id)
        self._pair_colors[key] = (fg_rgb, bg_rgb)
        self._pair_by_hex[key] = attribute
        return attribute

    def _closest_pair(self, fg_rgb, bg_rgb) -> int:
        """Pair budget used up: reuse the existing pair that looks most alike
        (foreground matters most, then the background)."""
        best_key = None
        best_distance = None
        for key, (fg, bg) in self._pair_colors.items():
            distance = 4 * _rgb_distance(fg, fg_rgb)
            if bg is None and bg_rgb is None:
                pass
            elif bg is None or bg_rgb is None:
                distance += 30000
            else:
                distance += _rgb_distance(bg, bg_rgb)
            if best_distance is None or distance < best_distance:
                best_key, best_distance = key, distance
        return self._pair_by_hex.get(best_key, 0) if best_key is not None else 0

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
                self._redefined.add(slot)
                return slot
            except curses.error:
                pass
        if curses.COLORS >= 256:
            return rgb_to_nearest_xterm_256(rgb, self._redefined)
        return rgb_to_nearest_basic(rgb)
