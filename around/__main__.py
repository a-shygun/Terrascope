from __future__ import annotations

import argparse
import curses

from around import __version__
from around.core.app import aroundApp
from around.core.mapdata import MapDataError, load_map_data
from around.core.ui import safe_addstr
from around.core.world import WorldMap
from around.layers import discover_layers


def _main(stdscr, layers) -> None:
    try:
        for layer in layers:
            layer.startup()
        world = WorldMap(load_map_data(), layers)
        app = aroundApp(stdscr, world)
        app.run()
    except MapDataError as error:
        stdscr.erase()
        safe_addstr(stdscr, 1, 2, "MAP ERROR")
        safe_addstr(stdscr, 3, 2, str(error))
        safe_addstr(stdscr, 5, 2, "Press any key to exit")
        stdscr.nodelay(False)
        stdscr.getch()


def run() -> None:
    """Console-script entry point (registered as `around` in pyproject.toml)."""
    parser = argparse.ArgumentParser(
        prog="around",
        description="A braille-rendered terminal world map with live flight tracking.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.parse_args()

    curses.wrapper(_main, discover_layers())


if __name__ == "__main__":
    run()
