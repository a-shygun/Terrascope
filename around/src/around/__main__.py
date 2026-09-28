from __future__ import annotations

import argparse
import curses
from threading import Thread

try:
    from around import __version__
except ImportError:
    # Happens if src/around/__init__.py is missing (Python then treats "around"
    # as a namespace package with no __version__). Don't crash on that.
    try:
        from importlib.metadata import PackageNotFoundError, version

        __version__ = version("around")
    except Exception:
        __version__ = "unknown"


def _main(stdscr, layers) -> None:
    from around.core.app import AroundApp
    from around.core.mapdata import MapDataError, load_map_data
    from around.core.world import WorldMap

    for layer in layers:
        layer.startup()
    world = WorldMap([], layers)
    app = AroundApp(stdscr, world)
    app.map_loading = True

    def load_map() -> None:
        try:
            app.map_data_queue.put((load_map_data(), ""))
        except MapDataError as error:
            app.map_data_queue.put(([], str(error)))
        except OSError as error:
            app.map_data_queue.put(([], f"Could not load map data: {error}"))

    Thread(target=load_map, name="around-map-loader", daemon=True).start()
    app.run()


def run() -> None:
    """Console-script entry point (registered as `around` in pyproject.toml)."""
    parser = argparse.ArgumentParser(
        prog="around",
        description=(
            "A Braille terminal map with live air, ship, weather, and quake layers."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use cached data only and disable live API requests.",
    )
    parser.add_argument(
        "--list-layers", action="store_true", help="List available layers and exit."
    )
    parser.add_argument(
        "--disable-layer",
        action="append",
        default=[],
        metavar="NAME",
        help="Start with a layer disabled (repeatable).",
    )
    args = parser.parse_args()

    import around.config as config

    if args.offline:
        config.FETCH_NEW_DATA_FROM_API = False

    from around.layers import discover_layers

    layers = discover_layers()
    available = {layer.name for layer in layers}
    unknown = set(args.disable_layer) - available
    if unknown:
        parser.error("unknown layer name(s): " + ", ".join(sorted(unknown)))
    for layer in layers:
        if layer.name in args.disable_layer:
            layer.enabled = False
    if args.list_layers:
        for layer in layers:
            state = "on" if layer.enabled else "off"
            print(f"{layer.name}\t{state}\t{layer.toggle_key.upper() or '-'}")
        return

    curses.wrapper(_main, layers)


if __name__ == "__main__":
    run()