# app.py — THE MAIN LOOP AND INPUT HANDLING
# Responsible for: the AroundApp class that runs the curses loop (run()), reads
# keyboard and mouse input (handle_key / handle_mouse), the "/" search and "o"
# filter typing modes, showing/hiding the info box, and calling the drawing
# functions each frame.
# Edit this file to: add or change key bindings, change mouse-click behaviour,
# or change what happens on each tick / redraw.
# Not here: how things look (ui.py), map state like zoom/pan (world.py).

from __future__ import annotations
import curses
import sys
import time
from queue import Empty, SimpleQueue
from around.config import CACHE_DIR, CONTROL_BAR_HEIGHT, OUTER_MARGIN
from around.core.colors import ColorManager
from around.core.ui import (
    draw_controls_bar,
    draw_info_box,
    draw_map_box,
    info_arrow_positions,
    info_box_rect,
    safe_addstr,
)
from around.core.world import Frame, WorldMap

MAX_KEYS_PER_LOOP = 32
HEARTBEAT_SECONDS = 1.0


class AroundApp:
    def __init__(self, stdscr, world: WorldMap) -> None:
        self.stdscr = stdscr
        self.world = world
        self.running = True
        self.colors = ColorManager()
        self.mode = "normal"
        self.filter_buffer = ""
        self.search_buffer = ""
        self.frame: Frame | None = None
        self._frame_size: tuple[int, int] | None = None
        self.info_visible = False
        self.map_data_queue: SimpleQueue = SimpleQueue()
        self.map_loading = False
        self.map_error = ""
        self._original_stderr = None
        self._log_file = None

    def redirect_stderr(self) -> None:
        """Send stray stderr output (library warnings, thread tracebacks) to a
        log file so it can't scribble over the curses screen."""
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._log_file = open(
                CACHE_DIR / "around.log", "a", encoding="utf-8", buffering=1
            )
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
        curses.mousemask(curses.BUTTON1_PRESSED)
        curses.mouseinterval(0)
        self.colors.setup()

    def map_box(self, height: int, width: int) -> tuple[int, int, int, int]:
        top = OUTER_MARGIN[1]
        left = OUTER_MARGIN[0]
        box_width = width - OUTER_MARGIN[0] * 2
        box_height = height - OUTER_MARGIN[1] * 2 - CONTROL_BAR_HEIGHT
        return top, left, box_height, box_width

    def handle_mouse(self) -> None:
        try:
            _, mouse_x, mouse_y, _, button_state = curses.getmouse()
        except curses.error:
            return
        # Act on button-down only. Treating release as another click makes
        # one physical press select twice on terminals reporting both events.
        if not button_state & curses.BUTTON1_PRESSED:
            return
        height, width = self.stdscr.getmaxyx()
        map_top, map_left, map_height, map_width = self.map_box(height, width)
        inner_left = map_left + 2
        inner_top = map_top + 1
        inner_width = map_width - 4
        inner_height = map_height - 2
        rect = info_box_rect(
            map_top, map_left, map_height, map_width, self.world.selected_layer
        )
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
                        if abs(mouse_x - left_arrow_x) <= 1:
                            self.world.cycle_selection(-1)
                            return
                        if abs(mouse_x - right_arrow_x) <= 1:
                            self.world.cycle_selection(1)
                            return
                return
        local_x = mouse_x - inner_left
        local_y = mouse_y - inner_top
        if local_x < 0:
            return
        if local_x >= inner_width:
            return
        if local_y < 0:
            return
        if local_y >= inner_height:
            return
        self.world.select_at(local_x, local_y)
        self.info_visible = self.world.selected_layer is not None

    def enter_search_mode(self) -> None:
        self.search_buffer = self.world.search_text
        self.mode = "search"

    def enter_filter_mode(self) -> None:
        self.filter_buffer = ""
        self.mode = "filter"

    def current_filter_suggestion(self) -> str | None:
        query = self.filter_buffer.strip().lower()
        if not query:
            return None
        options = self.world.filter_options()
        for option in options:
            if option.lower().startswith(query):
                return option
        for option in options:
            if query in option.lower():
                return option
        return None

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
                self.world.set_filter(None)
                self.filter_buffer = ""
                self.mode = "normal"
                return
            suggestion = self.current_filter_suggestion()
            if suggestion is not None:
                self.world.set_filter(suggestion)
                self.filter_buffer = ""
                self.mode = "normal"

    def handle_text_input(self, key: int) -> None:
        if key == 27:
            self.cancel_input_mode()
            return
        if key in (10, 13, curses.KEY_ENTER):
            self.commit_input_mode()
            return
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.mode == "search":
                self.search_buffer = self.search_buffer[:-1]
            elif self.mode == "filter":
                self.filter_buffer = self.filter_buffer[:-1]
            return
        if 32 <= key <= 126:
            character = chr(key)
            if self.mode == "search":
                self.search_buffer += character
            elif self.mode == "filter":
                self.filter_buffer += character

    def handle_key(self, key: int) -> None:
        if self.mode != "normal":
            self.handle_text_input(key)
            return
        if key in (ord("q"), ord("Q")):
            self.running = False
            return
        if key == 12:  # Ctrl+L: force a full repaint (clears any stray text)
            self.stdscr.clearok(True)
            self.world.dirty = True
            return
        if key == 27:
            self.world.clear_filters()
            self.info_visible = False
            return
        if key == ord("/"):
            self.enter_search_mode()
            return
        if key in (ord("o"), ord("O")):
            self.enter_filter_mode()
            return
        if key == curses.KEY_MOUSE:
            self.handle_mouse()
            return
        if key == ord("<"):
            self.world.cycle_selection(-1)
            return
        if key == ord(">"):
            self.world.cycle_selection(1)
            return
        if key in (curses.KEY_UP, ord("w"), ord("W")):
            self.world.pan(0, 1)
            return
        if key == curses.KEY_DOWN:
            self.world.pan(0, -1)
            return
        if key in (curses.KEY_LEFT, ord("a"), ord("A")):
            self.world.pan(-1, 0)
            return
        if key in (curses.KEY_RIGHT, ord("d"), ord("D")):
            self.world.pan(1, 0)
            return
        if key in (ord("+"), ord("=")):
            self.world.zoom_in()
            return
        if key in (ord("-"), ord("_")):
            self.world.zoom_out()
            return
        if key == ord("0"):
            self.world.reset_view()
            return
        for layer in self.world.layers:
            if layer.handle_key(key):
                self.world.clear_selection()
                self.info_visible = False
                self.world.dirty = True
                return

    def draw(self) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        minimum_width = 20
        if width < minimum_width or height < 20:
            safe_addstr(self.stdscr, 0, 0, "Terminal too small")
            self.stdscr.refresh()
            return
        map_top, map_left, map_height, map_width = self.map_box(height, width)
        frame_size = (map_width - 4, map_height - 2)
        if self._frame_size != frame_size:
            self.world.dirty = True
        if self.frame is None or self.world.needs_render():
            self.frame = self.world.render(*frame_size)
            self._frame_size = frame_size
        draw_map_box(
            self.stdscr,
            map_top,
            map_left,
            map_height,
            map_width,
            self.frame,
            self.colors,
            self.world.zoom,
            self.world.center_lat,
        )
        if self.info_visible and self.world.selected_layer is not None:
            rect = info_box_rect(
                map_top,
                map_left,
                map_height,
                map_width,
                self.world.selected_layer,
            )
            if rect is not None:
                draw_info_box(
                    self.stdscr,
                    *rect,
                    self.world.selected_layer,
                    self.world.selection_position,
                )
        draw_controls_bar(self.stdscr, height, width, self.world, self)
        if self.map_loading:
            safe_addstr(
                self.stdscr, map_top + 2, map_left + 3, "Loading country data..."
            )
        elif self.map_error:
            safe_addstr(
                self.stdscr,
                map_top + 2,
                map_left + 3,
                self.map_error[: max(0, map_width - 6)],
            )
        self.stdscr.refresh()

    def _collect_map_data(self) -> bool:
        """Apply finished map data; return True if the screen needs a redraw."""
        try:
            countries, error = self.map_data_queue.get_nowait()
        except Empty:
            return False
        self.map_loading = False
        if error:
            self.map_error = error
        else:
            self.world.countries = countries
            self.world.dirty = True
        return True

    def run(self) -> None:
        self.setup()
        try:
            self._loop()
        finally:
            self.restore_stderr()

    def _loop(self) -> None:
        last_draw = 0.0
        last_size = None
        while self.running:
            redraw = self._collect_map_data()
            # Drain queued input so held keys don't lag behind the screen.
            for _ in range(MAX_KEYS_PER_LOOP):
                key = self.stdscr.getch()
                if key == -1:
                    break
                self.handle_key(key)
                redraw = True
                if not self.running:
                    return
            for layer in self.world.layers:
                layer.tick()
            size = self.stdscr.getmaxyx()
            now = time.monotonic()
            # Only repaint when something changed (input, new data, resize),
            # plus a slow heartbeat as a safety net.
            if (
                redraw
                or self.frame is None
                or size != last_size
                or self.world.needs_render()
                or now - last_draw >= HEARTBEAT_SECONDS
            ):
                self.draw()
                last_draw = now
                last_size = size
            curses.napms(50)