# main.py — APP STARTUP (curses wrapper + ordered background data loading)

from __future__ import annotations

from threading import Thread

MAP_LOAD_ERROR = "Could not load map data: {error}"

def _main(stdscr, layers, forced_off) -> None:
    from terrascope.core.app import TerrascopeApp
    from terrascope.core.config import FETCH_NEW_DATA_FROM_API
    from terrascope.core.mapdata import (
        MapDataError,
        load_airports,
        load_country_labels,
        load_map_data,
        load_places,
        set_live_progress,
    )
    from terrascope.core.world import WorldMap, prepare_ring_set

    for layer in layers:
        layer.startup()
    world = WorldMap([], layers)
    app = TerrascopeApp(stdscr, world, frozenset(forced_off))
    app.map_loading = True

    def status(name: str, message: str) -> None:
        app.map_data_queue.put(("status", (name, message), ""))

    def layer_named(name: str):
        return next((layer for layer in layers if layer.name == name), None)

    weather_disabled = "weather" in forced_off

    def run_stage(name: str, label: str, action) -> None:
        status(name, label)
        try:
            action()
            status(name, "")
        except Exception as error:
            live_stage = {
                "AIRCRAFT": "planes",
                "RADAR": "radar",
                "WEATHER": "weather",
                "RADAR HISTORY": "radar-history",
            }.get(name)
            if live_stage is not None:
                # Live API feeds are optional; a provider outage must not keep
                # the first-run data setup bar from reaching completion.
                set_live_progress(live_stage, state="ready")
            status(name, f"{label.removesuffix('…')} UNAVAILABLE: {error}")

    def startup_downloads() -> None:
        places: list = []

        def countries() -> None:
            status("MAP", "LOADING COUNTRIES 50M")
            try:
                app.map_data_queue.put(("countries_prepared", prepare_ring_set(load_map_data()), ""))
            except Exception as error:
                app.map_data_queue.put(("countries", [], MAP_LOAD_ERROR.format(error=error)))
                raise
            finally:
                status("MAP", "")

        def cities() -> None:
            status("CITIES", "LOADING CITIES 10M")
            places.extend(load_places())
            basemap = layer_named("basemap")
            if basemap is not None:
                basemap.set_prepared_detail(basemap._prepare_places(load_country_labels(), places))
            weather = layer_named("weather")
            if weather is not None:
                ordered = sorted(places, key=lambda place: place[4], reverse=True)
                app.map_data_queue.put(("startup_weather_places", (
                    [place for place in ordered if place[3]],
                    [place for place in ordered if not place[3]],
                ), ""))
            status("CITIES", "")

        def airports() -> None:
            status("AIRPORTS", "LOADING AIRPORTS")
            airports_data = load_airports()
            app.map_data_queue.put(("startup_airports", airports_data, ""))
            status("AIRPORTS", "")

        def aircraft() -> None:
            if not FETCH_NEW_DATA_FROM_API:
                set_live_progress("planes", state="disabled")
                return
            flights = layer_named("flights")
            if flights is None:
                set_live_progress("planes", state="disabled")
                return
            status("AIRCRAFT", "FETCHING AIRCRAFT FEED")
            flights.cache.refresh_if_due(force=True)
            app.map_data_queue.put(("startup_flights", None, ""))
            flights._ordered_startup = False
            status("AIRCRAFT", "")

        def radar_present() -> None:
            if not FETCH_NEW_DATA_FROM_API:
                set_live_progress("radar", state="disabled")
                set_live_progress("radar-history", state="disabled")
                return
            weather = layer_named("weather")
            if weather is None or weather_disabled or not weather.show_cities:
                set_live_progress("radar", state="disabled")
                set_live_progress("radar-history", state="disabled")
                return
            from terrascope.layers.weather.radar import fetch_catalog, fetch_frame_raster

            status("RADAR", "FETCHING PRESENT RADAR FRAME")
            set_live_progress("radar", state="downloading")
            try:
                frames = fetch_catalog(weather.radar._mode)
                weather.radar.install_catalog(frames)
                past = [frame for frame in frames if not frame.get("nowcast")]
                current = max(past or frames, key=lambda frame: frame["time"], default=None)
                if current is not None:
                    raster = fetch_frame_raster(current, weather.radar._mode)
                    weather.radar.install_raster(current, raster)
                set_live_progress("radar", state="ready" if current else "failed", downloaded=1 if current else 0, total=max(1, len(frames)))
            except Exception as error:
                weather.radar.mark_failed(str(error))
                set_live_progress("radar", state="failed", error=str(error))
                raise
            status("RADAR", "")

        def capital_weather() -> None:
            if not FETCH_NEW_DATA_FROM_API:
                set_live_progress("weather", state="disabled")
                return
            weather = layer_named("weather")
            if weather is None or weather_disabled or not weather.show_cities:
                set_live_progress("weather", state="disabled")
                return
            from terrascope.layers.weather.forecast import city_key
            from terrascope.layers.weather.config import (
                MAX_CONCURRENT_WEATHER_REQUESTS,
                MAX_WEATHER_CITIES,
            )

            try:
                capitals = [place for place in sorted(places, key=lambda place: place[4], reverse=True) if place[3]][:MAX_WEATHER_CITIES]
                status("WEATHER", "FETCHING CITY WEATHER")
                # Weather reports are optional live data. Queue a small batch
                # and let the city's normal visible-marker path warm the rest;
                # network timeouts must not hold first-run setup open.
                warm_batch = capitals[:MAX_CONCURRENT_WEATHER_REQUESTS]
                for lon, lat, name, _capital, _population, _country in warm_batch:
                    weather.weather.ensure_fresh(city_key(name, lat, lon), lat, lon)
                set_live_progress("weather", state="ready", downloaded=len(warm_batch), total=max(1, len(capitals)))
            finally:
                weather._startup_weather_ready = True
                status("WEATHER", "")

        def radar_history() -> None:
            if not FETCH_NEW_DATA_FROM_API:
                set_live_progress("radar-history", state="disabled")
                return
            weather = layer_named("weather")
            if weather is None or weather_disabled or not weather.show_cities:
                set_live_progress("radar-history", state="disabled")
                return
            # Historical frames improve the radar animation but are not needed
            # to start exploring. Warm them quietly after setup in the background.
            set_live_progress("radar-history", state="ready", downloaded=1, total=1)

        def warm_radar_history(weather) -> None:
            from terrascope.layers.weather.radar import fetch_frame_raster

            frames = [
                frame for frame in weather.radar.catalog_frames()
                if not frame.get("nowcast")
            ]
            if frames:
                latest_observed = max(frame["time"] for frame in frames)
                frames = [frame for frame in frames if frame["time"] < latest_observed]
            loaded = {frame["time"] for frame, _raster in weather.radar.loaded_frames()}
            for frame in frames:
                if frame["time"] in loaded:
                    continue
                try:
                    weather.radar.install_raster(frame, fetch_frame_raster(frame, weather.radar._mode))
                except Exception:
                    continue

        stages = (
            ("MAP", "LOADING COUNTRIES 50M…", countries),
            ("CITIES", "LOADING CITIES 10M…", cities),
            ("AIRPORTS", "LOADING AIRPORTS…", airports),
            ("AIRCRAFT", "FETCHING AIRCRAFT FEED…", aircraft),
            ("RADAR", "FETCHING PRESENT RADAR FRAME…", radar_present),
            ("WEATHER", "LOADING CITY WEATHER…", capital_weather),
            ("RADAR HISTORY", "FETCHING OTHER RADAR TIMES…", radar_history),
        )
        for name, label, action in stages:
            run_stage(name, label, action)
        weather = layer_named("weather")
        if weather is not None:
            # Release the layer gates even when an earlier stage failed.
            weather._startup_weather_ready = True
            weather._startup_complete = True
            weather._ordered_startup = False
            if FETCH_NEW_DATA_FROM_API and not weather_disabled and weather.show_cities:
                if not weather.radar.catalog_frames() or weather.radar.failed():
                    weather.radar.ensure_fresh()
                else:
                    Thread(
                        target=warm_radar_history,
                        args=(weather,),
                        name="terrascope-radar-history",
                        daemon=True,
                    ).start()
        elif not FETCH_NEW_DATA_FROM_API:
            set_live_progress("radar", state="disabled")

    Thread(target=startup_downloads, name="terrascope-startup-downloads", daemon=True).start()
    app.run()

def launch(layers, forced_off) -> None:
    """Start curses after CLI options and layer selection are resolved."""
    import curses

    curses.wrapper(_main, layers, forced_off)
