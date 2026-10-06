"""Keyboard commands and search/filter interactions."""

from __future__ import annotations

from .shared import (
    KEYS,
    TABS,
    curses,
    slider_track,
    time
)

class InputMixin:

    def toggle_panel(self) -> None:
        """Show / hide the bottom panel (H key or the button on the map's
        bottom-left border)."""
        self.panel_visible = not self.panel_visible
        self.world.dirty = True  # the map box changes size

    def select_tab(self, index: int) -> None:
        """Make tab `index` active: switch on exactly the layers it lists."""
        if not 0 <= index < len(TABS):
            return
        # Colour pairs are never freed, so every tab's colours piled up until the
        # budget ran out (wrong backgrounds on map details / legend dots). Start each
        # tab with an empty pair table (palette slots are kept, see reset()).
        self.colors.reset()
        self._colors_reset_at = time.monotonic()
        wanted = set(TABS[index].layers) - self.forced_off
        for layer in self.world.layers:
            if layer.enabled != (layer.name in wanted):
                layer.toggle()  # reloads or clears the layer's data
        self.active_tab = index
        self.world.detailed = TABS[index].detailed
        self.world.show_provinces = self.provinces_visible and TABS[index].name == "map"
        for layer in self.world.layers:
            if layer.name == "basemap":
                layer.provinces_visible = self.provinces_visible and TABS[index].name == "map"
        self.world.show_places = TABS[index].place_names
        self.world.show_countries = TABS[index].country_names
        self.world.clear_selection()
        self.info_visible = False
        self._drag = None
        self.world.dirty = True

    def enter_search_mode(self) -> None:
        self.search_buffer = self.world.search_text
        self.mode = "search"

    def enter_filter_mode(self) -> None:
        self.filter_buffer = ""
        self.filter_scroll = 0
        flights = next((layer for layer in self.world.layers if layer.name == "flights"), None)
        self.filter_selected = set(getattr(flights, "filter_countries", set()))
        self.mode = "filter"

    def _apply_country_filter(self) -> None:
        flights = next((layer for layer in self.world.layers if layer.name == "flights"), None)
        if flights is not None:
            flights.apply_filter(self.filter_selected or None)
        self.world.filter_value = ", ".join(sorted(self.filter_selected)) or None
        self.world.clear_selection()

    def filter_suggestions(self) -> list[str]:
        """Filter options matching what is typed: prefix matches first, then
        the rest that contain it. Nothing typed = every option."""
        query = self.filter_buffer.strip().lower()
        options = self.world.filter_options()
        if not query:
            return options
        starts = [option for option in options if option.lower().startswith(query)]
        rest = [option for option in options if query in option.lower() and option not in starts]
        return starts + rest

    def current_filter_suggestion(self) -> str | None:
        if not self.filter_buffer.strip():
            return None
        suggestions = self.filter_suggestions()
        return suggestions[0] if suggestions else None

    def search_box_lines(self, hint: str | None) -> list[tuple[str, int]]:
        if self.mode == "search":
            return [(self.search_buffer + "█", curses.A_BOLD), ("", 0), ("Enter apply  Esc cancel", curses.A_DIM)]
        if self.world.search_text:
            return [(self.world.search_text, curses.A_BOLD), ("", 0), ("/ edit  Esc clear", curses.A_DIM)]
        if hint == "/ search  ·  O filter":
            return [(hint, 0), ("callsign / ICAO", curses.A_DIM)]
        return [("/ or click to search", 0), (hint or "", curses.A_DIM)]

    def filter_box_lines(self, hint: str | None, room: int) -> list[tuple[str, int]]:
        if self.mode == "filter":
            lines = [(self.filter_buffer + "█", curses.A_BOLD)]
            suggestions = self.filter_suggestions()
            if not suggestions:
                lines.append(("no match", curses.A_DIM))
            for option in suggestions[self.filter_scroll : self.filter_scroll + max(0, room)]:
                selected = option in self.filter_selected
                lines.append((("[x] " if selected else "[ ] ") + option, curses.A_BOLD if selected else curses.A_DIM))
            return lines
        if self.world.filter_value:
            return [(self.world.filter_value, curses.A_BOLD), ("", 0), ("O edit  Esc clear", curses.A_DIM)]
        return [("O or click to filter", 0), (hint or "", curses.A_DIM)]

    def _slider_spec(self):
        layer = self.world.slider_layer()
        return layer.slider() if layer is not None else None

    def _slider_track(self, inner_width: int):
        """(layer, spec, first track column, track length) or None."""
        layer = self.world.slider_layer()
        spec = layer.slider() if layer is not None else None
        if spec is None or spec.disabled or self.frame is None:
            return None
        track = slider_track(spec, inner_width, self.frame, self.world.center_lat)
        return None if track is None else (layer, spec, *track)

    def _slider_to(self, mouse_x: int, inner_left: int, inner_width: int) -> None:
        found = self._slider_track(inner_width)
        if found is None:
            return
        layer, spec, first, length = found
        fraction = (mouse_x - inner_left - first) / max(1, length - 1)
        layer.set_slider(max(0, min(spec.steps - 1, round(fraction * (spec.steps - 1)))))

    def _step_slider(self, direction: int) -> None:
        layer = self.world.slider_layer()
        spec = layer.slider() if layer is not None else None
        if spec is not None and not spec.disabled:
            layer.set_slider(max(0, min(spec.steps - 1, spec.index + direction)))

    def cancel_input_mode(self) -> None:
        self.search_buffer = ""
        self.filter_buffer = ""
        self.mode = "normal"

    def commit_input_mode(self) -> None:
        if self.mode == "search":
            self.world.set_search(self.search_buffer)
            self.mode = "normal"
            return
        if self.mode == "filter":
            if self.filter_buffer.strip() == "":
                self.filter_buffer = ""
                self.mode = "normal"
                return
            suggestion = self.current_filter_suggestion()
            if suggestion is not None:
                self.filter_selected = {suggestion}
                self._apply_country_filter()
                self.filter_buffer = ""
                self.mode = "normal"

    def handle_text_input(self, key: int) -> None:
        if key in KEYS["cancel"]:
            self.cancel_input_mode()
            return
        if key in KEYS["confirm"]:
            self.commit_input_mode()
            return
        if key in KEYS["backspace"]:
            if self.mode == "search":
                self.search_buffer = self.search_buffer[:-1]
            elif self.mode == "filter":
                self.filter_buffer = self.filter_buffer[:-1]
                self.filter_scroll = 0
            return
        if 32 <= key <= 126:
            character = chr(key)
            if self.mode == "search":
                self.search_buffer += character
            elif self.mode == "filter":
                self.filter_buffer += character
                self.filter_scroll = 0

    def handle_key(self, key: int) -> None:
        if key != curses.KEY_MOUSE:
            self._drag = None  # a key press always ends a drag
        if self.welcome_visible:
            # Modal: a click is handled by handle_mouse -> _click_welcome;
            # every other key either quits, dismisses it, or is swallowed so
            # it can't reach the map underneath.
            if key == curses.KEY_MOUSE:
                self.handle_mouse()
                return
            if key in KEYS["quit"]:
                self.running = False
                return
            if key in (ord("y"), ord("Y")) and self._welcome_province_yes is not None:
                self._choose_provinces(True)
                self.welcome_visible = False
                return
            if key in (ord("n"), ord("N")) and self._welcome_province_no is not None:
                self._choose_provinces(False)
                self.welcome_visible = False
                return
            if key in KEYS["clear"] or key in KEYS["about"]:
                self.welcome_visible = False
                self.world.dirty = True
            return
        if self.tz_dropdown_open:
            # Modal: a click goes to _mouse_event, every other key to the
            # dropdown's search / list, never to the map underneath.
            if key == curses.KEY_MOUSE:
                self.handle_mouse()
            else:
                self.handle_tz_key(key)
            return
        if self.mode != "normal":
            self.handle_text_input(key)
            return
        if key in KEYS["quit"]:
            self.running = False
            return
        if key in KEYS["redraw"]:  # force a full repaint (clears stray text)
            self.stdscr.clearok(True)
            self.world.dirty = True
            return
        if key in KEYS["toggle_panel"]:
            if self.panel_allowed():
                self.toggle_panel()
            return
        if key in KEYS["about"]:
            self.welcome_visible = True
            self.world.dirty = True
            return
        if key in KEYS["clear"]:
            self.world.clear_filters()
            self.info_visible = False
            return
        if key in KEYS["search"]:
            self.enter_search_mode()
            return
        if key in KEYS["filter"]:
            self.enter_filter_mode()
            return
        if key == curses.KEY_MOUSE:
            self.handle_mouse()
            return
        if key in KEYS["prev_selection"]:
            self.world.cycle_selection(-1)
            return
        if key in KEYS["next_selection"]:
            self.world.cycle_selection(1)
            return
        if key in KEYS["pan_up"]:
            self.world.pan(0, 1)
            return
        if key in KEYS["pan_down"]:
            self.world.pan(0, -1)
            return
        if key in KEYS["pan_left"]:
            self.world.pan(-1, 0)
            return
        if key in KEYS["pan_right"]:
            self.world.pan(1, 0)
            return
        if key in KEYS["zoom_in"]:
            self.world.zoom_in()
            return
        if key in KEYS["zoom_out"]:
            self.world.zoom_out()
            return
        if key in KEYS["reset_view"]:
            self.world.reset_view()
            return
        if key in KEYS["slider_down"] or key in KEYS["slider_up"]:
            self._step_slider(1 if key in KEYS["slider_up"] else -1)
            return
        if key in (ord("r"), ord("R")) and TABS[self.active_tab].name == "weather":
            if any(
                layer.name == "weather" and layer.radar.failed()
                for layer in self.world.layers
            ):
                self._retry_radar()
                return
        if ord("1") <= key < ord("1") + min(9, len(TABS)):  # number keys = tabs
            self.select_tab(key - ord("1"))
            return
        if key in (ord("x"), ord("X")):
            first = next((hit for hit in self._status_hits if hit[4] == "dismiss"), None)
            if first is not None:
                self.dismissed_statuses.add(first[3])
                self.world.dirty = True
                return
        if key in (ord("r"), ord("R")) and self.province_choice != "no" and self.province_state == "failed":
            self._choose_provinces(True)
            return
        tab_layers = TABS[self.active_tab].layers
        if (
            TABS[self.active_tab].name == "map"
            and self.province_choice != "no"
            and (self.province_choice is None or self.province_state == "failed")
        ):
            if key in (ord("y"), ord("Y")):
                self._choose_provinces(True)
                return
            if key in (ord("n"), ord("N")):
                self._choose_provinces(False)
                return
        for layer in self.world.layers:
            if layer.name not in tab_layers:
                continue  # a layer from another tab: its hotkey does nothing here
            if layer.handle_key(key):
                self.world.clear_selection()
                self.info_visible = False
                self.world.dirty = True
                return
