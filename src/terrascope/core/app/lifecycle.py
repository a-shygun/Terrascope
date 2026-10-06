"""App setup, panel state, and startup layer coordination."""

from __future__ import annotations

import os
from .shared import (
    CACHE_DIR,
    LOG_FILE,
    Layout,
    MOUSE_MASK,
    MOUSE_MOTION_ON,
    PROVINCE_CHOICE_FILE,
    PanelBox,
    TABS,
    Thread,
    compute_layout,
    curses,
    sys
)

class LifecycleMixin:

    def _choose_provinces(self, enabled: bool) -> None:
        self.province_choice = "yes" if enabled else "no"
        self.provinces_visible = False
        self.world.show_provinces = False
        self.province_error = ""
        self.map_statuses.pop("PROVINCE BORDERS", None)
        self.map_statuses.pop("BORDERS", None)
        self.dismissed_statuses = {
            message for message in self.dismissed_statuses if "BORDERS" not in message.upper()
        }
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            (CACHE_DIR / PROVINCE_CHOICE_FILE).write_text(self.province_choice, encoding="utf-8")
        except OSError:
            pass
        if enabled:
            self._start_province_download()
        self.world.dirty = True

    def _start_province_download(self) -> None:
        if self.province_state == "loading" or self.province_state == "ready":
            return
        self.province_state = "loading"
        self.map_statuses.pop("PROVINCE BORDERS", None)
        self.map_statuses["BORDERS"] = "LOADING STATE/PROVINCE BORDERS"

        def worker() -> None:
            try:
                from terrascope.core.mapdata import load_province_lines
                from terrascope.core.world import prepare_ring_set

                prepared = prepare_ring_set(load_province_lines())
                self.map_data_queue.put(("province_borders", prepared, ""))
            except Exception as error:
                self.map_data_queue.put(("province_borders", None, str(error)))

        Thread(target=worker, name="terrascope-province-borders", daemon=True).start()
        self.world.dirty = True

    def _retry_radar(self) -> None:
        for layer in self.world.layers:
            if layer.name == "weather" and hasattr(layer, "radar"):
                self.map_statuses.pop("RADAR", None)
                layer.radar.retry()
                layer.dirty = True
                self.world.dirty = True
                return

    def redirect_stderr(self) -> None:
        """Send stray stderr output (library warnings, thread tracebacks) to a
        log file so it can't scribble over the curses screen."""
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(CACHE_DIR / LOG_FILE, flags, 0o600)
            try:
                self._log_file = os.fdopen(
                    descriptor, "a", encoding="utf-8", buffering=1
                )
            except OSError:
                os.close(descriptor)
                raise
        except OSError:
            return
        self._original_stderr = sys.stderr
        sys.stderr = self._log_file

    def restore_stderr(self) -> None:
        if self._original_stderr is not None:
            sys.stderr = self._original_stderr
            self._original_stderr = None
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def setup(self) -> None:
        self.redirect_stderr()
        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.stdscr.nodelay(True)
        curses.mousemask(MOUSE_MASK)
        curses.mouseinterval(0)
        if sys.stdout.isatty():
            sys.stdout.write(MOUSE_MOTION_ON)
            sys.stdout.flush()
        self.colors.setup()

    def panel_owner(self):
        """The layer that defines the bottom row: the first enabled layer of
        the active tab (in the tab's order) that sets a panel_layout."""
        for name in TABS[self.active_tab].layers:
            for layer in self.world.layers:
                if layer.name == name and layer.enabled and layer.panel_layout:
                    return layer
        return None

    def panel_allowed(self) -> bool:
        """The MAP tab is just the map: no bottom panel and no HIDE PANEL button."""
        return TABS[self.active_tab].name != "map"

    def layout(self, height: int, width: int) -> Layout:
        owner = self.panel_owner()
        panel_layout = None
        if owner is not None and owner.name == "flights" and width < 104:
            show_filter = self.mode == "filter" or (
                not self.world.search_text and bool(self.world.filter_value)
            )
            kind = "filter" if show_filter else "search"
            hint = "country name" if show_filter else "/ search  ·  O filter"
            title = "SEARCH / FILTER" if self.mode == "normal" else (
                "FILTER COUNTRY" if show_filter else "SEARCH PLANE"
            )
            panel_layout = (
                PanelBox("info", 0.43),
                PanelBox(kind, 0.57, title, hint),
            )
        return compute_layout(
            height, width, self.panel_visible and self.panel_allowed(), owner,
            panel_layout,
        )
