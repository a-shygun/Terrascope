"""Timezone picker interactions."""

from __future__ import annotations

from .shared import (
    KEYS,
    curses,
    timezone_choices
)

class TimezoneMixin:

    def open_tz_dropdown(self) -> None:
        self.tz_query = ""
        choices = timezone_choices("")
        self.tz_index = next(
            (i for i, (_, name) in enumerate(choices) if name == self.selected_timezone), 0
        )
        self.tz_dropdown_open = True
        self.world.dirty = True

    def close_tz_dropdown(self) -> None:
        self.tz_dropdown_open = False
        self.tz_query = ""
        self.world.dirty = True

    def _tz_move(self, delta: int) -> None:
        total = len(timezone_choices(self.tz_query))
        self.tz_index = max(0, min(max(0, total - 1), self.tz_index + delta))
        self.world.dirty = True

    def _tz_choose(self, index: int) -> None:
        """Use entry `index` of the current list and close the dropdown. With
        nothing listed (no match) the dropdown just stays open."""
        choices = timezone_choices(self.tz_query)
        if not choices:
            return
        self.selected_timezone = choices[max(0, min(index, len(choices) - 1))][1]
        self.close_tz_dropdown()

    def handle_tz_key(self, key: int) -> None:
        """Keys while the timezone dropdown is open: typing searches, Up/Down
        (PgUp/PgDn) move the highlight, Enter picks it, Esc closes."""
        if key in KEYS["cancel"]:
            self.close_tz_dropdown()
            return
        if key in KEYS["confirm"]:
            self._tz_choose(self.tz_index)
            return
        if key in KEYS["backspace"]:
            self.tz_query = self.tz_query[:-1]
            self.tz_index = 0
        elif key == curses.KEY_UP:
            self._tz_move(-1)
        elif key == curses.KEY_DOWN:
            self._tz_move(1)
        elif key == curses.KEY_PPAGE:
            self._tz_move(-8)
        elif key == curses.KEY_NPAGE:
            self._tz_move(8)
        elif 32 <= key <= 126:
            self.tz_query += chr(key)
            self.tz_index = 0
        self.world.dirty = True

    def _click_dropdown(self, x: int, y: int) -> None:
        """A click while the timezone dropdown is open: on an entry, pick it;
        elsewhere inside the box, nothing; outside it, close the dropdown."""
        layout = self._dropdown_layout
        if layout is not None:
            top, left, height, width = layout.rect
            if left <= x < left + width and top <= y < top + height:
                if y in layout.option_rows:
                    self._tz_choose(layout.first_index + layout.option_rows.index(y))
                return
        self.close_tz_dropdown()
