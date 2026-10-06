# cli.py — COMMAND-LINE ARGUMENT PARSING
# Responsible for: everything that reads argv or sets environment variables —
# defining the `terrascope` command's flags, parsing them, applying them as
# overrides of default.yaml (see config.py), resolving which layers start
# enabled/disabled, and either printing information (layer / tab / key lists,
# paths, the effective config) or handing off to terrascope.core.main.launch()
# to actually start the app.
# terrascope/__main__.py calls run() from here.
#
# How overrides work: most flags map one-to-one onto a setting in
# default.yaml (see OPTIONS below: the dotted path is the setting's address in
# the YAML). The settings are changed in memory BEFORE the rest of the app is
# imported, because every module reads them at import time. Anything without
# its own flag can be changed with --set KEY=VALUE.
#
# Edit this file to: add, remove, or change a CLI flag or its help text. To
# expose another default.yaml setting as a flag, add one line to OPTIONS.
# Not here: starting curses or building the WorldMap (main.py).

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import yaml

try:
    from terrascope import __version__
except ImportError:
    # Happens if src/terrascope/__init__.py is missing (Python then treats "terrascope"
    # as a namespace package with no __version__). Don't crash on that.
    try:
        from importlib.metadata import PackageNotFoundError, version

        __version__ = version("terrascope")
    except Exception:
        __version__ = "unknown"

# Only config.py may be imported at this point: it holds the settings that the
# flags below change. Everything else is imported lazily in run().
try:
    from terrascope.core import config
except Exception as error:  # a broken terrascope_CONFIG file, for example
    sys.exit(f"terrascope: could not load configuration: {error}")

# Command-line texts (hardcoded; edit here).
CLI_DESCRIPTION = (
    "A Braille terminal map with live air, weather, and quake layers.\n"
    "Every option below overrides the matching value in default.yaml for this run only."
)

# Settings that have no entry in default.yaml but may still be set with --set.
OPTIONAL_KEYS = config.OPTIONAL_KEYS

# Files terrascope writes into its cache directory; --clear-cache removes only these.
CACHE_FILE_PATTERNS = ("*.geojson", "*.tmp", "*_cache.json")

# ---------------------------------------------------------------------------
# Value parsers (argparse "type=" callables)
# ---------------------------------------------------------------------------

def _number(kind: type, low=None, high=None, low_open: bool = False) -> Callable[[str], Any]:
    def parse(text: str):
        try:
            value = kind(text)
        except ValueError:
            what = "an integer" if kind is int else "a number"
            raise argparse.ArgumentTypeError(f"{text!r} is not {what}")
        if kind is float and not math.isfinite(value):
            raise argparse.ArgumentTypeError(f"{text!r} is not a finite number")
        if low is not None and (value < low or (low_open and value == low)):
            raise argparse.ArgumentTypeError(f"must be {'>' if low_open else '>='} {low}")
        if high is not None and value > high:
            raise argparse.ArgumentTypeError(f"must be <= {high}")
        return value

    parse.__name__ = kind.__name__
    return parse

INT = _number(int)
FLOAT = _number(float)
POS_INT = _number(int, 1)
NONNEG_INT = _number(int, 0)
POS_FLOAT = _number(float, 0, low_open=True)
NONNEG_FLOAT = _number(float, 0)
UNIT_FLOAT = _number(float, 0, 1)

_HEX_OPAQUE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_HEX_ALPHA = re.compile(r"^#?([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_OFF_WORDS = {"none", "off", "false", "transparent"}

def _color(text: str) -> str:
    """#rgb or #rrggbb (the leading # is optional on the command line)."""
    match = _HEX_OPAQUE.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"{text!r} is not a colour like #rrggbb")
    return "#" + match.group(1).lower()

def _color_alpha(text: str) -> Any:
    """#rrggbb, #rrggbbaa (aa = opacity), or none/off/transparent -> False."""
    stripped = text.strip().lower()
    if stripped in _OFF_WORDS:
        return False
    match = _HEX_ALPHA.match(stripped)
    if not match:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a colour like #rrggbb or #rrggbbaa (or 'none')"
        )
    return "#" + match.group(1)

def _pair(text: str) -> list[int]:
    try:
        first, second = (int(part) for part in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not two integers like 2,1")
    if first < 0 or second < 0:
        raise argparse.ArgumentTypeError("values must be >= 0")
    return [first, second]

# ---------------------------------------------------------------------------
# The option table: one row per default.yaml setting that has a flag
# ---------------------------------------------------------------------------

G_STARTUP = "Startup and layers"
G_DATA = "Data, network and cache"
G_TERMINAL = "Terminal and main loop"
G_MAP = "Map appearance"
G_ZOOM = "Zoom and panning"
G_LAYOUT = "Screen layout"
G_BASEMAP = "Place names (basemap layer)"
G_PLANES = "Planes and airports (PLANES tab)"
G_CITIES = "Weather: cities and forecast (WEATHER tab)"
G_RADAR = "Weather: radar / cloud overlay (WEATHER tab)"
G_QUAKES = "Weather: earthquakes (WEATHER tab)"
G_NIGHT = "Day / night (TIME tab)"
G_ADVANCED = "Configuration files and raw settings"
G_INFO = "Information (print something and exit)"

GROUP_ORDER = (
    G_STARTUP, G_DATA, G_TERMINAL, G_MAP, G_ZOOM, G_LAYOUT, G_BASEMAP,
    G_PLANES, G_CITIES, G_RADAR, G_QUAKES, G_NIGHT, G_ADVANCED, G_INFO,
)

@dataclass(frozen=True)
class Opt:
    group: str
    flags: tuple[str, ...]
    path: str  # dotted address of the setting in default.yaml
    kind: Any  # a parser from above, str, or "bool" for --x / --no-x pairs
    help: str
    metavar: str | None = None
    choices: tuple | None = None

    @property
    def dest(self) -> str:
        return "opt_" + self.path.replace(".", "_")

def _o(group, flags, path, kind, help, metavar=None, choices=None) -> Opt:
    return Opt(group, tuple(flags) if isinstance(flags, (tuple, list)) else (flags,), path, kind, help, metavar, choices)

OPTIONS: tuple[Opt, ...] = (
    # -- startup
    _o(G_STARTUP, "--panel", "app.panel_visible_at_start", "bool",
       "Show the panel at launch (the H key toggles it)."),
    # -- data and network
    _o(G_DATA, "--download-timeout", "data.download_timeout_seconds", POS_FLOAT,
       "Timeout for downloading Natural Earth map data.", "SECONDS"),
    _o(G_DATA, "--map-data-url", "data.natural_earth_base_url", str,
       "Base URL the Natural Earth GeoJSON files are downloaded from.", "URL"),
    # -- terminal and main loop
    _o(G_TERMINAL, "--redefine-palette", "terminal.redefine_palette", "bool",
       "Redefine terminal palette slots to the exact colours (turn off if "
       "colours look wrong or stay garbled after exit)."),
    _o(G_TERMINAL, "--max-color-pairs", "terminal.max_color_pairs", _number(int, 2),
       "Upper bound on curses colour pairs (default: automatic, capped at 255).", "N"),
    _o(G_TERMINAL, "--min-width", "app.min_terminal_width", POS_INT,
       "Below this many columns the app shows 'Terminal too small'.", "COLS"),
    _o(G_TERMINAL, "--min-height", "app.min_terminal_height", POS_INT,
       "Below this many rows the app shows 'Terminal too small'.", "ROWS"),
    _o(G_TERMINAL, "--frame-delay", "app.frame_delay_ms", NONNEG_INT,
       "Main-loop sleep between passes.", "MS"),
    _o(G_TERMINAL, "--drag-frame-delay", "app.drag_frame_delay_ms", NONNEG_INT,
       "Main-loop sleep while dragging the map.", "MS"),
    _o(G_TERMINAL, "--heartbeat", "app.heartbeat_seconds", POS_FLOAT,
       "Forced repaint interval when nothing changes.", "SECONDS"),
    _o(G_TERMINAL, "--max-keys", "app.max_keys_per_loop", POS_INT,
       "Input events drained per loop pass (so held keys don't lag).", "N"),
    _o(G_TERMINAL, "--log-file", "app.log_file", str,
       "Name of the log file inside the cache directory (stderr goes there).", "NAME"),
    # -- map appearance
    _o(G_MAP, "--country-color", "map.country_color", _color, "Country outlines.", "HEX"),
    _o(G_MAP, "--province-color", "map.province_color", _color,
       "State / province borders (default: the country colour, dimmed).", "HEX"),
    _o(G_MAP, "--water-color", "map.water_color", _color_alpha,
       "Ocean background: #rrggbb, #rrggbbaa (aa = opacity) or 'none' for transparent.", "HEX|none"),
    _o(G_MAP, "--land-color", "map.land_color", _color_alpha,
       "Land background: #rrggbb, #rrggbbaa (aa = opacity) or 'none' for transparent.", "HEX|none"),
    _o(G_MAP, "--blend-color", "map.transparent_blend_color", _color,
       "Colour partial opacity is blended against (roughly your terminal's background).", "HEX"),
    _o(G_MAP, "--cell-aspect", "map.cell_aspect", POS_FLOAT,
       "Terminal cell height / width; try 1.8-2.2 if the map looks stretched.", "RATIO"),
    _o(G_MAP, "--coast-fade-steps", "map.coast_fade_steps", POS_INT,
       "Shades between water and land (fewer = fewer colour pairs used).", "N"),
    _o(G_MAP, "--lat-min", "map.lat_min", _number(float, -90, 90),
       "Southern edge of the visible latitude band.", "DEG"),
    _o(G_MAP, "--lat-max", "map.lat_max", _number(float, -90, 90),
       "Northern edge of the visible latitude band.", "DEG"),
    # -- zoom and panning
    _o(G_ZOOM, "--zoom-min", "map.zoom.min", POS_FLOAT,
       "Fully zoomed-out level (also the starting zoom).", "ZOOM"),
    _o(G_ZOOM, "--zoom-max", "map.zoom.max", POS_FLOAT, "Most zoomed-in level.", "ZOOM"),
    _o(G_ZOOM, "--zoom-step", "map.zoom.step", _number(float, 1, low_open=True),
       "Zoom multiplier per key press / wheel notch.", "FACTOR"),
    _o(G_ZOOM, "--pan-step", "map.zoom.pan_step", _number(float, 0, 1, low_open=True),
       "Fraction of the visible span moved per key press.", "FRACTION"),
    _o(G_ZOOM, "--province-zoom", "map.zoom.province_min", POS_FLOAT,
       "State / province borders appear from this zoom on.", "ZOOM"),
    # -- screen layout
    _o(G_LAYOUT, "--outer-margin", "ui.outer_margin", _pair,
       "Columns,rows kept free around the screen, e.g. 2,1.", "COLS,ROWS"),
    _o(G_LAYOUT, "--panel-height", "ui.panel_height", _number(int, 5),
       "Horizontal panel height in rows, borders included.", "ROWS"),
    _o(G_LAYOUT, "--panel-orientation", "ui.panel_orientation", str,
       "Panel placement: horizontal along the bottom or vertical on the left.",
       "MODE", ("horizontal", "vertical")),
    _o(G_LAYOUT, "--tab-gap", "ui.tab_gap", NONNEG_INT, "Blank columns between tabs.", "COLS"),
    _o(G_LAYOUT, "--legend-color", "ui.legend_text_color", _color, "Legend text on the map.", "HEX"),
    # -- basemap
    _o(G_BASEMAP, "--country-click", "layers.basemap.country_click_expands", "bool",
       "Clicking a country code toggles its full name."),
    _o(G_BASEMAP, "--country-max-zoom", "layers.basemap.country_max_zoom", POS_FLOAT,
       "Country names show up to this zoom, then give way to cities.", "ZOOM"),
    _o(G_BASEMAP, "--capital-min-zoom", "layers.basemap.capital_min_zoom", POS_FLOAT,
       "National capitals show from this zoom on.", "ZOOM"),
    _o(G_BASEMAP, "--major-city-population", "layers.basemap.major_city_min_population", NONNEG_INT,
       "Tabs without full detail only label cities at least this big.", "PEOPLE"),
    _o(G_BASEMAP, "--label-padding", "layers.basemap.label_padding", NONNEG_INT,
       "Blank columns required between two labels on a row.", "COLS"),
    _o(G_BASEMAP, "--max-labels", "layers.basemap.max_labels", POS_INT,
       "Hard cap on place-name labels.", "N"),
    # -- planes and airports
    _o(G_PLANES, "--flights-refresh", "layers.flights.refresh_interval_seconds", POS_INT,
       "Minimum time between OpenSky requests (anonymous use is rate-limited).", "SECONDS"),
    _o(G_PLANES, "--flights-timeout", "layers.flights.request_timeout_seconds", POS_FLOAT,
       "OpenSky request timeout.", "SECONDS"),
    _o(G_PLANES, "--opensky-url", "layers.flights.api_url", str, "OpenSky states endpoint.", "URL"),
    _o(G_PLANES, "--flight-history", "layers.flights.history_points", POS_INT,
       "Positions remembered per aircraft (tail length and time-slider range).", "N"),
    _o(G_PLANES, "--arrow-zoom", "layers.flights.arrow_zoom_threshold", POS_FLOAT,
       "At this zoom or higher plane dots become heading arrows.", "ZOOM"),
    _o(G_PLANES, "--airports", "layers.flights.airports.enabled", "bool",
       "Airport markers on the planes tab (the K key toggles them)."),
    _o(G_PLANES, "--airport-label-zoom", "layers.flights.airports.label_min_zoom", POS_FLOAT,
       "IATA/ICAO codes appear from this zoom on.", "ZOOM"),
    _o(G_PLANES, "--airport-max-labels", "layers.flights.airports.max_labels", POS_INT,
       "Hard cap on airport markers.", "N"),
    _o(G_PLANES, "--airport-color", "layers.flights.airports.color", _color,
       "Airport marker colour.", "HEX"),
    # -- weather: cities
    _o(G_CITIES, "--cities", "layers.weather.cities.enabled", "bool",
       "City labels with temperatures (the C key toggles them)."),
    _o(G_CITIES, "--weather-refresh", "layers.weather.cities.weather_refresh_interval_seconds", POS_INT,
       "How often a city's weather is refreshed.", "SECONDS"),
    _o(G_CITIES, "--weather-url", "layers.weather.cities.api_url", str, "Open-Meteo endpoint.", "URL"),
    _o(G_CITIES, "--weather-concurrency", "layers.weather.cities.max_concurrent_requests", POS_INT,
       "Simultaneous weather requests.", "N"),
    _o(G_CITIES, "--forecast-days", "layers.weather.cities.forecast_days_ahead", _number(int, 0, 15),
       "Days after today shown in the forecast box (0-15).", "N"),
    _o(G_CITIES, "--city-max-labels", "layers.weather.cities.max_labels", POS_INT,
       "Most cities labelled (and weather-fetched) at once.", "N"),
    _o(G_CITIES, "--cold-color", "layers.weather.cities.temperature_cold_color", _color,
       "Colour of the coldest city.", "HEX"),
    _o(G_CITIES, "--hot-color", "layers.weather.cities.temperature_hot_color", _color,
       "Colour of the hottest city.", "HEX"),
    # -- weather: radar
    _o(G_RADAR, "--radar", "layers.weather.radar.enabled", "bool", "Rain radar / cloud overlay."),
    _o(G_RADAR, "--radar-mode", "layers.weather.radar.mode", str,
       "Show rain radar or satellite clouds.", "MODE", ("radar", "satellite")),
    _o(G_RADAR, "--radar-url", "layers.weather.radar.url", str,
       "LibreWXR server (the terrascope_LIBREWXR_URL variable overrides this).", "URL"),
    _o(G_RADAR, "--radar-opacity", "layers.weather.radar.opacity", UNIT_FLOAT,
       "1 = full palette colours, lower = fainter.", "0-1"),
    _o(G_RADAR, "--radar-animate", "layers.weather.radar.animate", "bool",
       "Loop all frames instead of holding the live frame."),
    _o(G_RADAR, "--radar-past-frames", "layers.weather.radar.past_frames", NONNEG_INT,
       "Most observed frames kept (10 minutes apart).", "N"),
    _o(G_RADAR, "--radar-nowcast-frames", "layers.weather.radar.nowcast_frames", NONNEG_INT,
       "Most forecast frames after LIVE (0 = none).", "N"),
    _o(G_RADAR, "--radar-history-minutes", "layers.weather.radar.history_minutes", NONNEG_FLOAT,
       "Drop observed frames older than this (0 = keep everything offered).", "MINUTES"),
    _o(G_RADAR, "--radar-world-zoom", "layers.weather.radar.world_zoom", _number(int, 1, 4),
       "Raster detail: each step quadruples the tile requests per frame.", "Z"),
    _o(G_RADAR, "--radar-color-steps", "layers.weather.radar.color_steps", _number(int, 2, 16),
       "Intensity levels / colours (above ~10 colours may get mixed up).", "N"),
    _o(G_RADAR, "--radar-supersample", "layers.weather.radar.supersample", _number(int, 1, 4),
       "Samples per half-cell per axis (1 = fastest, 3 = smoothest).", "N"),
    _o(G_RADAR, "--radar-blend-color", "layers.weather.radar.blend_color", _color,
       "Colour the radar fades towards (roughly the map's colour).", "HEX"),
    # -- weather: earthquakes
    _o(G_QUAKES, "--quakes", "layers.weather.earthquakes.enabled", "bool",
       "Earthquake markers (the E key toggles them)."),
    _o(G_QUAKES, "--quake-min-magnitude", "layers.weather.earthquakes.min_magnitude", FLOAT,
       "Events below this magnitude are hidden.", "MAG"),
    _o(G_QUAKES, "--quake-refresh", "layers.weather.earthquakes.refresh_interval_seconds", POS_INT,
       "Minimum time between USGS requests.", "SECONDS"),
    _o(G_QUAKES, "--quake-dim-hours", "layers.weather.earthquakes.dim_after_hours", NONNEG_FLOAT,
       "Quakes older than this are drawn faded.", "HOURS"),
    _o(G_QUAKES, "--quake-feed", "layers.weather.earthquakes.api_url", str, "USGS GeoJSON feed.", "URL"),
    # -- day / night
    _o(G_NIGHT, "--night-look", "layers.night.look", str,
       "Starting look: 'tint' (coloured land background) or 'fill' (dotted fill).", "LOOK", ("tint", "fill")),
    _o(G_NIGHT, "--tint-opacity", "layers.night.tint_opacity", UNIT_FLOAT,
       "Opacity of the land tint (0 = none, 1 = full colour).", "0-1"),
    _o(G_NIGHT, "--night-update", "layers.night.update_seconds", POS_FLOAT,
       "How often the day/night bands are recalculated.", "SECONDS"),
)

# Dotted settings that only exist as comments in default.yaml; flags for them
# must be allowed to create the key.
_CREATABLE = OPTIONAL_KEYS

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _show(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)

def _option_help(opt: Opt) -> str:
    text = opt.help
    if opt.choices:
        text += f" One of: {', '.join(opt.choices)}."
    default = config.get_path(opt.path)
    if default is not None and not isinstance(default, (dict, list)):
        text += f" (default: {_show(default)})"
    elif isinstance(default, list):
        text += f" (default: {','.join(str(item) for item in default)})"
    return text.replace("%", "%%")

def _tab_names() -> list[str]:
    return [str(item["name"]) for item in config.CFG["tabs"]["items"]]

def build_parser() -> argparse.ArgumentParser:
    tabs = ", ".join(f"{i + 1}={name}" for i, name in enumerate(_tab_names()))
    epilog = f"""\
examples:
  terrascope                                   start on the first tab
  terrascope --tab planes --offline            planes tab, cached data only
  terrascope -t 3 --radar-mode satellite --radar-opacity 0.8
  terrascope --water-color '#0b1d2e' --land-color none
  terrascope --no-airports --flights-refresh 600
  terrascope --disable-layer night --no-redefine-palette
  terrascope --set 'map.zoom.max=128' --set 'map.country_code_overrides={{DE: "GER"}}'
  terrascope --config ~/terrascope.yaml --dump-config

tabs: {tabs}

precedence (later wins):
  default.yaml  <  $terrascope_CONFIG file  <  --config files  <  flags  <  --set

notes:
  * Flags with a --no-X form switch a feature on or off (e.g. --airports / --no-airports).
  * Colours are #rrggbb (quote them in your shell: '#rrggbb').
  * --set takes YAML values, so colours must be quoted inside: --set 'map.land_color="#101018"'.
  * Run --dump-config to see every setting you can change with --set.

environment variables:
  terrascope_OFFLINE=1        same as --offline
  terrascope_CONFIG=FILE      same as --config FILE (applied first)
  terrascope_LIBREWXR_URL     LibreWXR radar server (beats --radar-url)
  XDG_CACHE_HOME            cache location when --cache-dir is not given

in-app keys: run `terrascope --list-keys`.
"""
    parser = argparse.ArgumentParser(
        prog="terrascope",
        usage="%(prog)s [OPTIONS]",
        description=CLI_DESCRIPTION,
        epilog=epilog,
        formatter_class=lambda prog: argparse.RawDescriptionHelpFormatter(
            prog, max_help_position=34
        ),
        add_help=False,
        allow_abbrev=False,
    )
    groups = {name: parser.add_argument_group(name) for name in GROUP_ORDER}

    # -- information
    info = groups[G_INFO]
    info.add_argument("-h", "--help", action="help", help="Show this help and exit.")
    info.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}",
                      help="Show the version and exit.")
    info.add_argument("-l", "--list-layers", action="store_true",
                      help="List layers (name, on/off, toggle key) and exit.")
    info.add_argument("--list-tabs", action="store_true",
                      help="List tabs (number, name, layers they switch on) and exit.")
    info.add_argument("--list-keys", action="store_true",
                      help="List keyboard shortcuts as currently configured and exit.")
    info.add_argument("--show-paths", action="store_true",
                      help="Show cache directory, log file, config files and online/offline state, then exit.")

    # -- startup
    startup = groups[G_STARTUP]
    startup.add_argument("-t", "--tab", metavar="NAME|N",
                         help="Tab to open at launch: a name or its number (1 = first).")
    startup.add_argument("-d", "--disable-layer", action="append", default=[], metavar="NAME",
                         help="Start with a layer disabled, whatever the tab says (repeatable; see --list-layers).")

    # -- data / network / cache
    data = groups[G_DATA]
    data.add_argument("--offline", action="store_true",
                      help="Use cached data only and disable live API requests.")
    data.add_argument("--online", action="store_true",
                      help="Force live requests on (overrides the config file and terrascope_OFFLINE).")
    data.add_argument("--cache-dir", metavar="DIR",
                      help="Where caches, downloaded map data and the log file live "
                           "(default: $XDG_CACHE_HOME/terrascope or ~/.cache/terrascope).")
    data.add_argument("--user-agent", metavar="TEXT",
                      help="User-Agent sent with every HTTP request "
                           f"(default: {config.CFG['data']['user_agent']}).".replace("%", "%%"))
    data.add_argument("--clear-cache", action="store_true",
                      help="Delete downloaded map data and flight / weather / quake caches from the cache directory, then exit.")

    # -- advanced
    advanced = groups[G_ADVANCED]
    advanced.add_argument("-c", "--config", action="append", default=[], metavar="FILE",
                          help="YAML file merged over default.yaml; same layout (repeatable).")
    advanced.add_argument("-s", "--set", action="append", default=[], metavar="KEY=VALUE", dest="set_values",
                          help="Set any default.yaml value by dotted path, value in YAML "
                               "(repeatable), e.g. --set map.zoom.step=2.")
    advanced.add_argument("--dump-config", action="store_true",
                          help="Print the effective settings (after all overrides) as YAML and exit.")

    # -- the table
    for opt in OPTIONS:
        group = groups[opt.group]
        if opt.kind == "bool":
            group.add_argument(*opt.flags, dest=opt.dest, action=argparse.BooleanOptionalAction,
                               default=None, help=_option_help(opt))
        else:
            group.add_argument(*opt.flags, dest=opt.dest, type=opt.kind, metavar=opt.metavar,
                               choices=opt.choices, default=None, help=_option_help(opt))
    return parser

# ---------------------------------------------------------------------------
# Applying the settings
# ---------------------------------------------------------------------------

def _apply_set(parser: argparse.ArgumentParser, item: str) -> None:
    if "=" not in item:
        parser.error(f"--set expects KEY=VALUE, got {item!r}")
    key, raw = item.split("=", 1)
    key = key.strip()
    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError as error:
        parser.error(f"--set {key}: value is not valid YAML ({error}); quote colours like '\"#rrggbb\"'")
    try:
        config.set_path(key, value, create=key in OPTIONAL_KEYS)
    except KeyError:
        parser.error(f"--set: unknown setting {key!r} (see --dump-config for the valid ones)")

def _resolve_tab(parser: argparse.ArgumentParser, spec: str) -> int:
    names = [name.lower() for name in _tab_names()]
    text = spec.strip().lower()
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(names):
            return index
    elif text in names:
        return names.index(text)
    parser.error(
        f"unknown tab {spec!r}; choose a number 1-{len(names)} or one of: {', '.join(names)}"
    )

def apply_settings(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Fold every flag into config.CFG, then recompute the derived values."""
    if args.offline and args.online:
        parser.error("--offline and --online cannot be used together")

    for path in args.config:
        try:
            config.merge_user_config(path)
        except config.ConfigError as error:
            parser.error(str(error))

    for opt in OPTIONS:
        value = getattr(args, opt.dest)
        if value is not None:
            config.set_path(opt.path, value, create=opt.path in _CREATABLE)

    if args.cache_dir:
        config.set_path("paths.cache_dir", str(Path(args.cache_dir).expanduser()))
    if args.user_agent:
        config.set_path("data.user_agent", args.user_agent)
    if args.online:
        os.environ.pop("terrascope_OFFLINE", None)
        config.set_path("data.fetch_new_data_from_api", True)
    if args.offline:
        # Layers and mapdata read this when they are imported, so it must be
        # set before they are.
        os.environ["terrascope_OFFLINE"] = "1"
        config.set_path("data.fetch_new_data_from_api", False)

    for item in args.set_values:
        _apply_set(parser, item)

    if args.tab is not None:
        config.set_path("tabs.start_tab", _resolve_tab(parser, args.tab))
    else:
        start = config.CFG["tabs"]["start_tab"]
        if not isinstance(start, int) or not 0 <= start < len(_tab_names()):
            parser.error(f"tabs.start_tab must be 0-{len(_tab_names()) - 1}, got {start!r}")

    try:
        config.validate_config()
    except config.ConfigError as error:
        parser.error(str(error))
    config.refresh_derived()

# ---------------------------------------------------------------------------
# Information commands
# ---------------------------------------------------------------------------

def print_layer_list(layers) -> None:
    for layer in layers:
        state = "on" if layer.enabled else "off"
        print(f"{layer.name}\t{state}\t{layer.toggle_key.upper() or '-'}")

def print_tab_list() -> None:
    start = config.CFG["tabs"]["start_tab"]
    for index, item in enumerate(config.CFG["tabs"]["items"]):
        marker = "*" if index == start else " "
        layers = ",".join(item.get("layers") or ())
        print(f"{marker}{index + 1}\t{item['name']}\t{layers}\t{item.get('blurb', '')}")

_LAYER_KEYS = (
    ("planes on/off", "layers.flights.toggle_key"),
    ("airports on/off", "layers.flights.airports.toggle_key"),
    ("cities on/off", "layers.weather.cities.toggle_key"),
    ("earthquakes on/off", "layers.weather.earthquakes.toggle_key"),
    ("day/night layer on/off", "layers.night.toggle_key"),
    ("tint / fill look", "layers.night.look_key"),
)

def print_key_list() -> None:
    rows: list[tuple[str, str]] = []
    for action, spec in config.CFG["app"]["keys"].items():
        keys = " ".join(str(k) for k in spec) if isinstance(spec, (list, tuple)) else str(spec)
        rows.append((action.replace("_", " "), keys))
    for label, path in _LAYER_KEYS:
        key = config.get_path(path)
        if key:
            rows.append((label, str(key)))
    rows += [
        ("select tab", "1-9"),
        ("clear filters / close dialogs", "Esc"),
        ("force repaint", "Ctrl+L"),
        ("mouse", "drag = pan, wheel = zoom, click = select"),
    ]
    width = max(len(action) for action, _ in rows)
    for action, keys in rows:
        print(f"{action.ljust(width)}  {keys}")

def print_paths() -> None:
    log_name = config.CFG["app"]["log_file"]
    print(f"cache dir      {config.CACHE_DIR}")
    print(f"log file       {config.CACHE_DIR / log_name}")
    print("config files   " + "\n               ".join(str(p) for p in config.LOADED_FILES))
    print(f"live requests  {'on' if config.FETCH_NEW_DATA_FROM_API else 'off (offline)'}")

def clear_cache() -> None:
    cache = config.CACHE_DIR
    if not cache.is_dir():
        print(f"nothing to clear: {cache} does not exist")
        return
    targets: list[Path] = []
    for pattern in CACHE_FILE_PATTERNS:
        targets += [p for p in cache.glob(pattern) if p.is_file()]
    removed = 0
    for target in targets:
        try:
            shutil.rmtree(target) if target.is_dir() else target.unlink()
            removed += 1
        except OSError as error:
            print(f"could not remove {target}: {error}", file=sys.stderr)
    print(f"removed {removed} cached item(s) from {cache}")

def dump_config() -> None:
    yaml.safe_dump(config.CFG, sys.stdout, sort_keys=False, allow_unicode=True,
                   default_flow_style=None, width=100)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    """Console-script entry point (registered as `terrascope` in pyproject.toml)."""
    parser = build_parser()
    args = parser.parse_args()

    # Every setting must be final before the rest of the app is imported.
    apply_settings(args, parser)

    handled = False
    if args.dump_config:
        dump_config()
        handled = True
    if args.show_paths:
        print_paths()
        handled = True
    if args.list_tabs:
        print_tab_list()
        handled = True
    if args.list_keys:
        print_key_list()
        handled = True
    if args.clear_cache:
        clear_cache()
        handled = True

    if handled and not args.list_layers:
        return

    from terrascope.core.registry import build_layers

    layers = build_layers()
    available = {layer.name for layer in layers}
    unknown = set(args.disable_layer) - available
    if unknown:
        parser.error(
            "unknown layer name(s): " + ", ".join(sorted(unknown))
            + " (available: " + ", ".join(sorted(available)) + ")"
        )
    for layer in layers:
        if layer.name in args.disable_layer:
            layer.enabled = False

    if args.list_layers:
        print_layer_list(layers)
        return

    from terrascope.core.main import launch

    launch(layers, args.disable_layer)

if __name__ == "__main__":
    run()
