"""Terminal colors and curses color-pair allocation."""

from __future__ import annotations

import os

from .constants import (
    DIM_ATTR,
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

def rgb_to_nearest_basic(rgb: tuple[int, int, int], bright: bool = False) -> int:
    """Nearest of the eight basic colours, or of the sixteen when bright is set.
    The bright set has the grey at index 8, the only grey a 16-colour terminal
    offers; without it a dimmed white quantises back to white."""
    candidates = (
        (color, _XTERM_BASIC_16_RGB[color])
        for color in range(16 if bright else 8)
    )
    return _nearest_by_distance(rgb, candidates)

def osc_palette_reset_works(platform: str = sys.platform, environ=os.environ) -> bool:
    """OSC 104 (reset palette) is written everywhere except the classic Windows
    console, which has no escape-sequence parser and would print it. Windows
    Terminal (WT_SESSION set) honours it."""
    return platform != "win32" or bool(environ.get("WT_SESSION"))

def pair_id_limit(a_color: int) -> int:
    """Number of colour pair ids the A_COLOR field can hold (ids 0 .. n-1).
    ncurses keeps the pair in 0xff00, so 256; PDCurses keeps it in the top byte
    (A_COLOR = -0x1000000), which gives the same 256. The field's lowest set bit
    is its shift. A mask with no bits in the low 32 bits (a 64-bit chtype)
    falls back to 256 instead of a negative shift."""
    mask = a_color & 0xFFFFFFFF
    if not mask:
        return 256
    shift = (mask & -mask).bit_length() - 1
    return (mask >> shift) + 1

# The ColorManager of the running app, for drawing helpers that only see attributes.
ACTIVE = None

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
        self._key_by_pair: dict[int, str] = {}  # colour-pair attribute -> "fg|bg" key
        # (fg slot, bg slot) -> pair attribute: colours that resolve to the same
        # palette slots share one pair id instead of spending another.
        self._pair_by_slots: dict[tuple[int, int], int] = {}
        self._dimmed_by_attr: dict[int, int] = {}  # attributes -> dimmed attributes
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
        global ACTIVE
        ACTIVE = self
        wanted = bool(TERMINAL_CONFIG.get("redefine_palette", True))
        self.supports_exact_color = (
            wanted and curses.can_change_color() and curses.COLORS > self.FIRST_FREE_SLOT
        )
        limit = min(curses.COLOR_PAIRS, pair_id_limit(curses.A_COLOR))
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
        self._key_by_pair.clear()
        self._pair_by_slots.clear()
        self._dimmed_by_attr.clear()
        self._next_pair_id = 1
        self.exhausted = False

    def restore(self) -> None:
        """Put the terminal's palette back if it was redefined (xterm OSC 104)."""
        if self._redefined and sys.stdout.isatty() and osc_palette_reset_works():
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
        self._key_by_pair.setdefault(attribute, key)
        return attribute

    def dimmed(self, attributes: int) -> int:
        """DIM_ATTR drawn as a colour: the cell's colour pair with the foreground
        halfway to its background. PDCurses (windows-curses) ignores A_DIM on
        coloured text, which left inactive tabs and hints at full brightness."""
        cached = self._dimmed_by_attr.get(attributes)
        if cached is not None:
            return cached
        result = self._dimmed(attributes)
        self._dimmed_by_attr[attributes] = result
        return result

    def _dimmed(self, attributes: int) -> int:
        key = self._key_by_pair.get(attributes & curses.A_COLOR)
        if key is None:
            return attributes
        fg, bg = key.split("|", 1)
        bg = None if bg == "None" else bg
        try:
            fg_rgb = hex_to_rgb(fg)
            base = hex_to_rgb(bg) if bg else (0, 0, 0)
        except ValueError:
            return attributes
        mixed = "#{:02x}{:02x}{:02x}".format(*((a + b) // 2 for a, b in zip(fg_rgb, base)))
        return (attributes & ~curses.A_COLOR & ~DIM_ATTR) | self.get_pair(mixed, bg)

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
        foreground = self._slot_for_hex(hex_color)
        if foreground is None:
            return 0
        bg_slot = -1
        if background:
            resolved = self._slot_for_hex(background)
            if resolved is not None:
                bg_slot = resolved
        slots = (foreground, bg_slot)
        shared = self._pair_by_slots.get(slots)
        if shared is not None:
            # Same palette slots, so the same pair looks identical on screen.
            self._pair_colors[key] = (fg_rgb, bg_rgb)
            return shared
        if self._next_pair_id >= self._pair_limit:
            self.exhausted = True
            return self._closest_pair(fg_rgb, bg_rgb)
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
        self._pair_by_slots[slots] = attribute
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
        return rgb_to_nearest_basic(rgb, bright=curses.COLORS >= 16)
