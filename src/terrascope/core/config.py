# config.py — SHARED CONFIG (loaded once, used everywhere)
# Responsible for: reading src/terrascope/assets/default.yaml a single time and
# exposing it (CFG) plus the settings almost every other module needs: where
# the on-disk cache lives (CACHE_DIR), whether live API requests are allowed
# (FETCH_NEW_DATA_FROM_API, off with `terrascope --offline` / terrascope_OFFLINE=1),
# and the User-Agent sent with every HTTP request (USER_AGENT). Every layer
# imports these from here instead of re-reading default.yaml itself, so the
# file is parsed once and these values live in one place.
#
# Overrides: after default.yaml is read, an optional user config file (the
# environment variable terrascope_CONFIG, or `terrascope --config FILE`) is
# deep-merged on top, and cli.py applies command-line overrides with
# set_path(). Because the derived values (CACHE_DIR, FETCH_NEW_DATA_FROM_API,
# USER_AGENT) are computed from CFG, cli.py calls refresh_derived() once all
# overrides are in. This must happen BEFORE any other terrascope module is
# imported, since those read CFG / these constants at import time.
#
# Edit this file to: change where default.yaml is loaded from, how user config
# files are merged, or how the cache directory / offline flag are derived.
# Not here: the *contents* of default.yaml (colours, hotkeys, etc.) — modules
# that need a specific section read CFG[...] themselves.

from __future__ import annotations

import copy
import math
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import yaml

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
BUNDLED_DEFAULT_CONFIG_FILE = ASSETS_DIR / "default.yaml"
USER_CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
) / "terrascope"
USER_DEFAULT_CONFIG_FILE = USER_CONFIG_DIR / "default.yaml"

def _install_default_config() -> Path:
    """Create the user's editable default config on first launch.

    Existing user files are never replaced by package upgrades. If the config
    directory cannot be written, continue with the bundled defaults.
    """
    try:
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not USER_DEFAULT_CONFIG_FILE.exists():
            shutil.copyfile(BUNDLED_DEFAULT_CONFIG_FILE, USER_DEFAULT_CONFIG_FILE)
        return USER_DEFAULT_CONFIG_FILE
    except OSError:
        return BUNDLED_DEFAULT_CONFIG_FILE

DEFAULT_CONFIG_FILE = _install_default_config()

# Settings that are not in default.yaml (commented out / optional) but that
# are valid to set. Without this, user config files and `--set` would flag
# them as unknown.
OPTIONAL_KEYS = frozenset({
    "map.province_color", "layers.night.seam_glyph", "ui.panel_orientation",
})
# Sections whose keys are free-form (users may add their own entries).
FREE_FORM_KEYS = frozenset({"map.country_code_overrides"})

_URL_PATHS = (
    "data.natural_earth_base_url",
    "layers.flights.api_url",
    "layers.weather.cities.api_url",
    "layers.weather.radar.url",
    "layers.weather.earthquakes.api_url",
)
_POSITIVE_PATHS = (
    "data.download_timeout_seconds",
    "app.min_terminal_width",
    "app.min_terminal_height",
    "app.max_keys_per_loop",
    "app.heartbeat_seconds",
    "map.cell_aspect",
    "map.zoom.min",
    "map.zoom.max",
    "map.zoom.step",
    "layers.flights.refresh_interval_seconds",
    "layers.flights.request_timeout_seconds",
    "layers.weather.cities.weather_refresh_interval_seconds",
    "layers.weather.cities.max_concurrent_requests",
    "layers.weather.cities.request_timeout_seconds",
    "layers.weather.radar.request_timeout_seconds",
    "layers.weather.earthquakes.refresh_interval_seconds",
    "layers.weather.earthquakes.request_timeout_seconds",
)
_UNIT_INTERVAL_PATHS = (
    "layers.weather.radar.opacity",
    "layers.night.tint_opacity",
)
_COLOR_PATHS = {
    "map.province_color",
    "map.transparent_blend_color",
    "ui.modal_bg_color",
}
_NULLABLE_PATHS = {
    "paths.cache_dir": str,
    "terminal.max_color_pairs": int,
    "map.transparent_blend_color": str,
    "ui.modal_bg_color": str,
}

class ConfigError(Exception):
    """A config file could not be read or is not valid."""

def _read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error.strerror or error}") from error
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {path}: {error}") from error

def deep_merge(base: dict, extra: dict) -> dict:
    """Merge `extra` into `base` in place: dicts merge key by key, everything
    else (including lists) is replaced."""
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base

def _unknown_paths(base: dict, extra: dict, prefix: str = "") -> list[str]:
    unknown = []
    for key, value in extra.items():
        path = f"{prefix}{key}"
        if key not in base:
            if path not in OPTIONAL_KEYS and prefix.rstrip(".") not in FREE_FORM_KEYS:
                unknown.append(path)
        elif isinstance(value, dict) and isinstance(base[key], dict):
            unknown += _unknown_paths(base[key], value, path + ".")
    return unknown

def _check_types(default: Any, value: Any, path: str) -> None:
    """Check known settings against their bundled default value types."""
    if isinstance(default, dict):
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: expected a mapping")
        if path in FREE_FORM_KEYS:
            if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
                raise ConfigError(f"{path}: expected string keys and values")
            return
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in default:
                _check_types(default[key], item, child_path)
            elif child_path in OPTIONAL_KEYS:
                if not isinstance(item, str):
                    raise ConfigError(f"{child_path}: expected a string")
    elif isinstance(default, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"{path}: expected true or false")
    elif isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{path}: expected an integer")
    elif isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ConfigError(f"{path}: expected a finite number")
    elif isinstance(default, str):
        if path in {"map.water_color", "map.land_color"} and value is False:
            return
        if path.startswith("layers.night.") and path.endswith("_color") and (value is None or value is False):
            return
        if not isinstance(value, str):
            raise ConfigError(f"{path}: expected a string")
        if default.startswith("#") or path in _COLOR_PATHS:
            if not re.fullmatch(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value):
                raise ConfigError(f"{path}: expected a hex color")
    elif isinstance(default, list):
        if not isinstance(value, list):
            raise ConfigError(f"{path}: expected a list")
        if default:
            for index, item in enumerate(value):
                template = default[index] if index < len(default) else default[0]
                _check_types(template, item, f"{path}[{index}]")

def validate_config(candidate: dict | None = None) -> None:
    """Validate known setting types and safety-sensitive path/value rules."""
    values = CFG if candidate is None else candidate
    _check_types(_DEFAULTS, values, "")

    cache_dir = values["paths"]["cache_dir"]
    if cache_dir is not None and (not isinstance(cache_dir, str) or not cache_dir.strip()):
        raise ConfigError("paths.cache_dir: expected a non-empty path or null")

    for path, expected in _NULLABLE_PATHS.items():
        value = get_path_from(values, path)
        if value is not None and (isinstance(value, bool) or not isinstance(value, expected)):
            raise ConfigError(f"{path}: expected {expected.__name__} or null")
    max_pairs = values["terminal"]["max_color_pairs"]
    if max_pairs is not None and max_pairs < 2:
        raise ConfigError("terminal.max_color_pairs must be at least 2 or null")
    for path in _COLOR_PATHS:
        value = get_path_from(values, path) if path not in OPTIONAL_KEYS else values.get("map", {}).get("province_color")
        if value is not None and not re.fullmatch(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value):
            raise ConfigError(f"{path}: expected a hex color or null")

    orientation = values.get("ui", {}).get("panel_orientation", "horizontal")
    if orientation not in {"horizontal", "vertical"}:
        raise ConfigError("ui.panel_orientation must be horizontal or vertical")

    log_file = values["app"]["log_file"]
    if (not log_file or log_file in {".", ".."}
            or Path(log_file).name != log_file or "/" in log_file or "\\" in log_file):
        raise ConfigError("app.log_file must be a filename inside the cache directory")

    user_agent = values["data"]["user_agent"]
    if not user_agent.strip() or any(ord(char) < 32 for char in user_agent):
        raise ConfigError("data.user_agent must be non-empty and contain no control characters")

    for path in _URL_PATHS:
        url = get_path_from(values, path)
        try:
            parsed = urlparse(url)
        except ValueError as error:
            raise ConfigError(f"{path}: invalid URL ({error})") from error
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(f"{path}: expected an http or https URL")

    for path in _POSITIVE_PATHS:
        number = get_path_from(values, path)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number <= 0:
            raise ConfigError(f"{path}: must be a positive finite number")

    for path in _UNIT_INTERVAL_PATHS:
        number = get_path_from(values, path)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number <= 1:
            raise ConfigError(f"{path}: must be between 0 and 1")

    map_settings = values["map"]
    if map_settings["lat_min"] >= map_settings["lat_max"]:
        raise ConfigError("map.lat_min must be less than map.lat_max")
    if map_settings["zoom"]["min"] > map_settings["zoom"]["max"]:
        raise ConfigError("map.zoom.min must not exceed map.zoom.max")
    if map_settings["zoom"]["step"] <= 1:
        raise ConfigError("map.zoom.step must be greater than 1")
    if not 0 < map_settings["zoom"]["pan_step"] <= 1:
        raise ConfigError("map.zoom.pan_step must be greater than 0 and at most 1")
    if not (-90 <= map_settings["lat_min"] < map_settings["lat_max"] <= 90):
        raise ConfigError("map latitude bounds must be ordered and within -90..90")
    forecast_days = values["layers"]["weather"]["cities"]["forecast_days_ahead"]
    if not 0 <= forecast_days <= 15:
        raise ConfigError("layers.weather.cities.forecast_days_ahead must be between 0 and 15")
    radar_mode = values["layers"]["weather"]["radar"]["mode"]
    if radar_mode not in {"radar", "satellite"}:
        raise ConfigError("layers.weather.radar.mode must be radar or satellite")
    if values["layers"]["night"]["look"] not in {"tint", "fill"}:
        raise ConfigError("layers.night.look must be tint or fill")
    tabs = values["tabs"]
    if not 0 <= tabs["start_tab"] < len(tabs["items"]):
        raise ConfigError("tabs.start_tab is outside the configured tab list")

def get_path_from(values: dict, dotted_path: str) -> Any:
    node: Any = values
    for part in dotted_path.split("."):
        node = node[part]
    return node

CFG: dict = _read_yaml(DEFAULT_CONFIG_FILE)
_DEFAULTS: dict = copy.deepcopy(CFG)
LOADED_FILES: list[Path] = [DEFAULT_CONFIG_FILE]
validate_config(CFG)

def merge_user_config(path: str | Path) -> None:
    """Deep-merge a user YAML file over the current settings. Keys that don't
    exist in default.yaml are reported on stderr (most likely typos) but kept."""
    path = Path(path).expanduser()
    data = _read_yaml(path)
    if data is None:
        return
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: the top level must be a mapping of sections")
    candidate = copy.deepcopy(CFG)
    for unknown in _unknown_paths(candidate, data):
        print(f"terrascope: warning: {path}: unknown setting '{unknown}'", file=sys.stderr)
    deep_merge(candidate, data)
    validate_config(candidate)
    CFG.clear()
    CFG.update(candidate)
    LOADED_FILES.append(path)

def get_path(path: str, default: Any = None) -> Any:
    """Value at a dotted path such as "layers.flights.toggle_key"."""
    node: Any = CFG
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node

def set_path(path: str, value: Any, create: bool = False) -> None:
    """Set the value at a dotted path. Raises KeyError if the section does not
    exist, or if the key itself does not exist and `create` is False."""
    parts = path.split(".")
    node: Any = CFG
    for part in parts[:-1]:
        child = node.get(part) if isinstance(node, dict) else None
        if not isinstance(child, dict):
            raise KeyError(path)
        node = child
    if parts[-1] not in node and not create:
        raise KeyError(path)
    node[parts[-1]] = value

# --- derived values -----------------------------------------------------------

CACHE_DIR: Path
FETCH_NEW_DATA_FROM_API: bool
USER_AGENT: str

def refresh_derived() -> None:
    """(Re)compute CACHE_DIR, FETCH_NEW_DATA_FROM_API and USER_AGENT from CFG."""
    global CACHE_DIR, FETCH_NEW_DATA_FROM_API, USER_AGENT
    cache_dir = CFG["paths"]["cache_dir"]
    CACHE_DIR = (
        Path(str(cache_dir)).expanduser()
        if cache_dir
        else Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "terrascope"
    )
    # `terrascope --offline` (or terrascope_OFFLINE=1) forces live requests off.
    FETCH_NEW_DATA_FROM_API = bool(CFG["data"]["fetch_new_data_from_api"]) and (
        os.environ.get("terrascope_OFFLINE") != "1"
    )
    # Shared across every module that makes an HTTP request (mapdata.py and
    # every layer file), so there's one string to update if it ever changes.
    USER_AGENT = str(CFG["data"]["user_agent"])

# A config file named in the environment is applied at import time, so even
# `python -c "import terrascope.core.layer"` sees it.
_env_config = os.environ.get("terrascope_CONFIG")
if _env_config:
    merge_user_config(_env_config)

refresh_derived()
