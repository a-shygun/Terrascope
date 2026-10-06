"""Terminal mouse input and pointer interactions."""

from __future__ import annotations

from .shared import (
    ARROW_HIT_TOLERANCE,
    DRAG_RESUME_SECONDS,
    GITHUB_URL,
    MAP_EDGE_PAD_Y,
    SCROLL_DOWN,
    SCROLL_UP,
    TABS,
    _skip_welcome_at_launch,
    curses,
    info_arrow_positions,
    panel_button_slot,
    tab_slots,
    time,
    webbrowser
)

class MouseMixin:

    def handle_mouse(self) -> None:
        """Mouse event decoded by ncurses (KEY_MOUSE)."""
        try:
            _, mouse_x, mouse_y, _, state = curses.getmouse()
        except curses.error:
            return
        if state & SCROLL_UP:
            kind = "scroll_up"
        elif state & SCROLL_DOWN:
            kind = "scroll_down"
        elif state & curses.BUTTON1_RELEASED:
            kind = "release"
        elif state & curses.REPORT_MOUSE_POSITION:
            kind = "motion"
        elif state & curses.BUTTON1_PRESSED:
            kind = "press"
        else:
            return
        self._mouse_event(kind, mouse_x, mouse_y)

    def _try_sgr_mouse(self) -> bool:
        """Called after an ESC key code. If an SGR mouse report follows
        (ESC [ < b ; x ; y M|m) read it, act on it and return True; otherwise
        put back anything read and return False (a plain Esc key)."""
        first = self.stdscr.getch()
        if first == -1:
            return False
        if first != ord("["):
            curses.ungetch(first)
            return False
        second = self.stdscr.getch()
        if second != ord("<"):
            if second != -1:
                curses.ungetch(second)
            curses.ungetch(first)
            return False
        text = ""
        final = ""
        for _ in range(24):
            code = self.stdscr.getch()
            if code == -1:
                break
            char = chr(code) if 0 <= code < 256 else "?"
            if char in "Mm":
                final = char
                break
            text += char
        try:
            button, x, y = (int(part) for part in text.split(";"))
        except ValueError:
            return True  # garbled report: swallow it
        if not final:
            return True
        x -= 1  # reports are 1-based
        y -= 1
        if button & 64:  # wheel: 64 = up, 65 = down
            kind = "scroll_down" if button & 1 else "scroll_up"
        elif button & 3:  # middle / right button: not used
            return True
        elif final == "m":
            kind = "release"
        elif button & 32:
            kind = "motion"
        else:
            kind = "press"
            self._drag = None  # a real button-down always starts a new grab
        self._mouse_event(kind, x, y)
        return True

    def _mouse_event(self, kind: str, mouse_x: int, mouse_y: int) -> None:
        """kind: "press" | "motion" | "release" | "scroll_up" | "scroll_down"."""
        # The welcome modal and the timezone dropdown are modal: while either
        # is open it alone decides what a click does, and nothing underneath
        # (panning, zooming, tabs...) reacts to the mouse.
        if self.welcome_visible:
            if kind == "press":
                self._click_welcome(mouse_x, mouse_y)
            return
        if self.tz_dropdown_open:
            if kind == "press":
                self._click_dropdown(mouse_x, mouse_y)
            elif kind == "scroll_up":
                self._tz_move(-1)
            elif kind == "scroll_down":
                self._tz_move(1)
            return

        height, width = self.stdscr.getmaxyx()
        layout = self.layout(height, width)
        map_top, map_left, map_height, map_width = layout.map
        inner_left = map_left + 2
        inner_top = map_top + 1
        inner_width = map_width - 4
        inner_height = map_height - 2

        def in_map(x: int, y: int) -> bool:
            return 0 <= x - inner_left < inner_width and 0 <= y - inner_top < inner_height

        if kind == "press":
            for row, x0, x1, message, action in self._status_hits:
                if mouse_y == row and x0 <= mouse_x < x1:
                    if action == "retry-provinces":
                        self._choose_provinces(True)
                    elif action == "retry-radar":
                        self._retry_radar()
                    elif action == "toggle-radar-status":
                        self.radar_status_expanded = not self.radar_status_expanded
                    else:
                        self.dismissed_statuses.add(message)
                        if message.startswith("PROVINCE BORDERS") or "DOWNLOAD BORDERS FAILED" in message:
                            self.province_error = ""
                    self.world.dirty = True
                    return
            for row, x0, x1, enabled in self._province_prompt_hits:
                if mouse_y == row and x0 <= mouse_x < x1:
                    self._choose_provinces(enabled)
                    return

        # The country filter panel is a scrollable, multi-select list.
        if kind in ("scroll_up", "scroll_down"):
            filter_rect = layout.rect_of("filter")
            if filter_rect is not None:
                top, left, box_height, box_width = filter_rect
                if left <= mouse_x < left + box_width and top <= mouse_y < top + box_height:
                    if self.mode != "filter":
                        self.enter_filter_mode()
                    options = self.filter_suggestions()
                    room = max(1, box_height - 3)
                    delta = -1 if kind == "scroll_up" else 1
                    self.filter_scroll = max(0, min(max(0, len(options) - room), self.filter_scroll + delta))
                    self.world.dirty = True
                    return
            # Wheel: zoom terrascope the pointer.
            if in_map(mouse_x, mouse_y):
                self.world.zoom_at(
                    1 if kind == "scroll_up" else -1,
                    mouse_x - inner_left,
                    mouse_y - inner_top,
                    inner_width,
                    inner_height,
                )
            return
        # A click on a clickable legend line (the TINT / FILL toggle). Checked on
        # button-down, before anything can start a drag, so it always wins.
        if kind == "press":
            for row, x0, x1, action in self._legend_hits:
                if mouse_y == row and x0 <= mouse_x < x1:
                    if action == "provinces":
                        self.provinces_visible = not self.provinces_visible
                        self.world.show_provinces = self.provinces_visible and TABS[self.active_tab].name == "map"
                        for layer in self.world.layers:
                            if layer.name == "basemap":
                                layer.provinces_visible = self.provinces_visible and TABS[self.active_tab].name == "map"
                    else:
                        for layer in self.world.active_layers():
                            layer.press_legend(action)
                    self._drag = None
                    self.world.dirty = True
                    return
            filter_rect = layout.rect_of("filter")
            if filter_rect is not None:
                top, left, box_height, box_width = filter_rect
                if left <= mouse_x < left + box_width and top <= mouse_y < top + box_height:
                    if self.mode != "filter":
                        self.enter_filter_mode()
                    else:
                        option_index = self.filter_scroll + mouse_y - (top + 2)
                        options = self.filter_suggestions()
                        if 0 <= option_index < len(options):
                            option = options[option_index]
                            if option in self.filter_selected:
                                self.filter_selected.remove(option)
                            else:
                                self.filter_selected.add(option)
                            self._apply_country_filter()
                    self.world.dirty = True
                    return
        # Dragging the slider (it lives on the map's bottom row).
        if self._slider_drag:
            if kind == "motion":
                self._slider_to(mouse_x, inner_left, inner_width)
                return
            self._slider_drag = False
            if kind == "release":
                return
        # Button released: end a drag, or treat a drag that never moved as a click.
        if kind == "release":
            drag, self._drag = self._drag, None
            if drag is not None and not drag[4]:
                self.world.select_at(drag[2] - inner_left, drag[3] - inner_top)
                self.info_visible = self.world.selected_layer is not None
            return
        # Pointer moved while the left button is held: pan by the cells moved.
        if self._drag is not None:
            now = time.monotonic()
            dx = mouse_x - self._drag[0]
            dy = mouse_y - self._drag[1]
            stale = kind == "press" and now - self._drag[5] > DRAG_RESUME_SECONDS
            self._drag[5] = now
            if stale:
                # A button-down after a pause (e.g. the earlier release got
                # lost): grab the map again here instead of jumping.
                self._drag[0], self._drag[1] = mouse_x, mouse_y
            elif dx or dy:
                self._drag[0], self._drag[1] = mouse_x, mouse_y
                self._drag[4] = True
                self.world.pan_cells(dx, dy, inner_width, inner_height)
            return
        # Everything below acts on button-down only.
        if kind != "press":
            return
        # Panel toggle button on the map box's bottom-left border.
        button = panel_button_slot(layout.map, self.panel_visible) if self.panel_allowed() else None
        if button is not None:
            button_row, button_x, button_text = button
            if mouse_y == button_row and button_x <= mouse_x < button_x + len(button_text):
                self.toggle_panel()
                return
        # Top row: click a numbered tab to switch tab, or the controls bar
        # (expand/collapse button, or the clock to open the timezone dropdown).
        if layout.tabs is not None:
            tabs_top, tabs_left, _, tabs_width = layout.tabs
            if mouse_y == tabs_top:
                for index, start, text in tab_slots(TABS, tabs_left, tabs_width):
                    if start <= mouse_x < start + len(text):
                        self.select_tab(index)
                        return
                controls = self._controls_layout
                if controls is not None:
                    for action, hit_x, hit_width in controls.help_hits:
                        if hit_x <= mouse_x < hit_x + hit_width:
                            if action == "about":
                                self.welcome_visible = True
                                self.world.dirty = True
                            elif action == "quit":
                                self.running = False
                            return
                    if controls.button_x <= mouse_x < controls.button_x + controls.button_width:
                        self.controls_expanded = not self.controls_expanded
                        self.world.dirty = True
                        return
                    if controls.datetime_x <= mouse_x < controls.datetime_x + controls.datetime_width:
                        self.open_tz_dropdown()
                        return
                return
        if mouse_y == inner_top + inner_height - 1 - MAP_EDGE_PAD_Y:
            found = self._slider_track(inner_width)
            if found is not None:
                _, _, first, length = found
                if first - 1 <= mouse_x - inner_left <= first + length:
                    self._slider_drag = True
                    self._slider_to(mouse_x, inner_left, inner_width)
                    return
        for box, (box_top, box_left, box_height, box_width) in layout.boxes:
            if (
                box.kind in ("search", "filter")
                and box_left <= mouse_x < box_left + box_width
                and box_top <= mouse_y < box_top + box_height
            ):
                if box.kind == "search":
                    self.enter_search_mode()
                else:
                    self.enter_filter_mode()
                return
        rect = layout.info
        if self.info_visible and rect is not None:
            info_top, info_left, info_height, info_width = rect
            if (
                info_left <= mouse_x < info_left + info_width
                and info_top <= mouse_y < info_top + info_height
            ):
                selected = self.world.selected_layer
                if selected is not None and mouse_y == info_top:
                    arrows = info_arrow_positions(
                        info_left, selected, self.world.selection_position
                    )
                    if arrows is not None:
                        left_arrow_x, right_arrow_x = arrows
                        tolerance = ARROW_HIT_TOLERANCE
                        if abs(mouse_x - left_arrow_x) <= tolerance:
                            self.world.cycle_selection(-1)
                            return
                        if abs(mouse_x - right_arrow_x) <= tolerance:
                            self.world.cycle_selection(1)
                            return
                return
        if in_map(mouse_x, mouse_y):
            # Start a drag. If the pointer never moves before the button is
            # released, that release selects the marker under it (see above).
            self._drag = [mouse_x, mouse_y, mouse_x, mouse_y, False, time.monotonic()]

    def _click_welcome(self, x: int, y: int) -> None:
        """A click while the welcome modal is open: inside it, open the
        GitHub link if that's what was clicked; otherwise (including anywhere
        outside the modal) just close it."""
        rect = self._welcome_rect
        if rect is not None:
            top, left, height, width = rect
            if left <= x < left + width and top <= y < top + height:
                link = self._welcome_link
                if link is not None and y == link.row and link.left <= x < link.left + link.width:
                    try:
                        webbrowser.open(GITHUB_URL)
                    except Exception:
                        pass
                    return
                yes = self._welcome_province_yes
                if yes is not None and y == yes.row and yes.left <= x < yes.left + yes.width:
                    self._choose_provinces(True)
                    self.welcome_visible = False
                    return
                no = self._welcome_province_no
                if no is not None and y == no.row and no.left <= x < no.left + no.width:
                    self._choose_provinces(False)
                    self.welcome_visible = False
                    return
                button = self._welcome_button
                if button is not None and y == button.row and button.left <= x < button.left + button.width:
                    _skip_welcome_at_launch()
                    self.welcome_visible = False
                    self.world.dirty = True
                return
        self.welcome_visible = False
        self.world.dirty = True
