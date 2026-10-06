"""Startup data handoff and the app's main loop."""

from __future__ import annotations

from .shared import (
    DRAG_FRAME_DELAY_MS,
    Empty,
    FRAME_DELAY_MS,
    HEARTBEAT_SECONDS,
    MAX_KEYS_PER_LOOP,
    MOUSE_MOTION_OFF,
    PROVINCE_FILE,
    RESIZE_SETTLE_SECONDS,
    TABS,
    concise_error_message,
    curses,
    download_progress,
    sys,
    time
)

class RuntimeMixin:

    def _collect_map_data(self) -> bool:
        """Apply finished map data; return True if the screen needs a redraw."""
        redraw = False
        while True:
            try:
                kind, data, error = self.map_data_queue.get_nowait()
            except Empty:
                return redraw
            redraw = True
            if kind == "status":
                name, message = data
                if message:
                    self.map_statuses[name] = message
                else:
                    self.map_statuses.pop(name, None)
            elif kind == "provinces":
                if not error:
                    self.world.provinces = data
                    self.world.dirty = True
            elif kind == "provinces_prepared":
                if not error:
                    self.world.set_prepared_provinces(data)
                    self.world.dirty = True
            elif kind == "province_borders":
                if error:
                    self.province_state = "failed"
                    self.province_error = error
                    self.map_statuses.pop("BORDERS", None)
                    border_progress = next(
                        (item for item in download_progress() if item.filename == PROVINCE_FILE),
                        None,
                    )
                    if border_progress is None or border_progress.state != "failed":
                        self.map_statuses["PROVINCE BORDERS"] = f"PROVINCE BORDERS FAILED: {concise_error_message(error, 80)}"
                elif self.province_choice == "yes":
                    self.world.set_prepared_provinces(data)
                    self.province_state = "ready"
                    self.province_error = ""
                    self.map_statuses.pop("BORDERS", None)
                    self.provinces_visible = True
                    for layer in self.world.layers:
                        if layer.name == "basemap":
                            layer.provinces_ready = True
                            layer.provinces_visible = True
                    self.world.show_provinces = TABS[self.active_tab].name == "map"
                    self.map_statuses.pop("PROVINCE BORDERS", None)
                    self.world.dirty = True
            elif kind == "detail":
                if "countries" in data:
                    self.world.countries = data["countries"]
                if "provinces" in data:
                    self.world.provinces = data["provinces"]
                self.world.dirty = True
            elif kind == "countries":
                self.map_loading = False
                self._map_data_received = True
                if error:
                    self.map_error = error
                else:
                    self.world.countries = data
            elif kind == "countries_prepared":
                self.map_loading = False
                self._map_data_received = True
                if error:
                    self.map_error = error
                else:
                    self.world.set_prepared_countries(data)
                    self.world.dirty = True
            elif kind == "startup_weather_places":
                for layer in self.world.layers:
                    if layer.name == "weather" and hasattr(layer, "set_prepared_places_detail"):
                        layer.set_prepared_places_detail(data)
                        break
            elif kind == "startup_airports":
                for layer in self.world.layers:
                    if layer.name == "flights":
                        with layer.lock:
                            layer._airports_pending = sorted(data, key=lambda airport: airport[4])
                        break
            elif kind == "startup_flights":
                for layer in self.world.layers:
                    if layer.name == "flights":
                        layer.reload()
                        break

    def run(self) -> None:
        self.setup()
        try:
            self._loop()
        finally:
            # Blank the screen BEFORE the terminal palette is reset: the map's
            # colours are redefined palette slots, so resetting them while the
            # map is still visible repaints it for one frame in default colours.
            try:
                self.stdscr.clear()
                self.stdscr.refresh()
            except curses.error:
                pass
            if sys.stdout.isatty():
                sys.stdout.write(MOUSE_MOTION_OFF)
                sys.stdout.flush()
            self.colors.restore()
            self.restore_stderr()

    def _loop(self) -> None:
        last_draw = 0.0
        last_size = None
        resizing_until = 0.0
        while self.running:
            redraw = self._collect_map_data()
            # Drain queued input so held keys don't lag behind the screen.
            for _ in range(MAX_KEYS_PER_LOOP):
                key = self.stdscr.getch()
                if key == -1:
                    break
                if key == 27 and self._try_sgr_mouse():
                    redraw = True
                    continue
                self.handle_key(key)
                redraw = True
                if not self.running:
                    return
            for layer in self.world.layers:
                layer.tick()
            size = self.stdscr.getmaxyx()
            now = time.monotonic()
            if last_size is not None and size != last_size:
                resizing_until = now + RESIZE_SETTLE_SECONDS
                last_size = size
                self.draw_resize_cover()
                curses.napms(FRAME_DELAY_MS)
                continue
            if now < resizing_until:
                curses.napms(FRAME_DELAY_MS)  # still settling: keep the cover up
                continue
            if resizing_until:
                # The size has been stable: repaint everything from scratch.
                resizing_until = 0.0
                self.stdscr.clearok(True)
                self.world.dirty = True
                redraw = True
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
            curses.napms(DRAG_FRAME_DELAY_MS if self._drag else FRAME_DELAY_MS)
