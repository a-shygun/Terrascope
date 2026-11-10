# plugins.py — THIRD-PARTY EXTENSION POINTS (entry points)
# Responsible for: finding the layer and tab plugins that other installed
# packages register under the entry-point groups "terrascope.layers" and
# "terrascope.tabs", normalising and validating them, and skipping (with a log
# line) any plugin or tab that is not usable, so a broken plugin never stops the
# app. Also remembers where each plugin came from ("plugin:<distribution>") for
# --list-layers / --list-tabs.
# Edit this file to: change how plugins are discovered or validated, or which
# keys a plugin layer may not use as its toggle key.
# Not here: the built-in layers (registry.py) or the built-in tabs
# (assets/default.yaml). At import time this module uses only the standard
# library: the CLI imports it before every setting is final, and importing
# layer or tab modules at that point would freeze their constants too early.
# The config module is imported only inside the functions that need it.
# Plugin tabs are kept here, not in the config, so --dump-config never saves them.

from __future__ import annotations

import importlib.metadata
import logging
import re
from typing import Any

LAYER_GROUP = "terrascope.layers"
TAB_GROUP = "terrascope.tabs"
BUILTIN_ORIGIN = "built-in"

log = logging.getLogger("terrascope.plugins")

# Tab name -> origin, for the tabs that plugins provide.
TAB_ORIGINS: dict[str, str] = {}

# The plugin tabs, normalised. None until first needed: the entry points are read
# once, and only by the commands that show or use tabs or layers.
_PLUGIN_TABS: list[dict] | None = None

# Keys a tab may have. Anything else is an error, so a typo is not silently ignored.
TAB_KEYS = frozenset({
    "name", "label", "color", "blurb", "layers", "detailed", "provinces",
    "place_names", "country_names", "attribution", "view",
})
_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")

def discover(group: str) -> list[Any]:
    """Entry points registered under `group`, in discovery order."""
    try:
        return list(importlib.metadata.entry_points(group=group))
    except Exception as error:  # a broken distribution must not stop the app
        log.warning("could not read %s entry points: %s", group, error)
        return []

def origin_of(entry_point: Any) -> str:
    """'plugin:<distribution name>' for an entry point, or 'plugin:unknown'."""
    name = None
    dist = getattr(entry_point, "dist", None)
    if dist is not None:
        try:
            name = dist.metadata["Name"]
        except Exception:
            name = None
    return f"plugin:{name or 'unknown'}"

def load_layer_classes() -> list[tuple[type, str]]:
    """Layer subclasses from the "terrascope.layers" group, as (class, origin).
    An entry point that fails to load or is not a Layer subclass is skipped."""
    from terrascope.core.layer import Layer  # imported late: see module header

    loaded: list[tuple[type, str]] = []
    for entry_point in discover(LAYER_GROUP):
        origin = origin_of(entry_point)
        try:
            layer_class = entry_point.load()
            if not (isinstance(layer_class, type) and issubclass(layer_class, Layer)):
                raise TypeError(f"{layer_class!r} is not a subclass of Layer")
        except Exception as error:
            log.warning("ignoring layer plugin %s (%s): %s", entry_point.name, origin, error)
            continue
        loaded.append((layer_class, origin))
    return loaded

def reserved_toggle_keys() -> frozenset[str]:
    """Single characters a plugin layer may not use as its toggle key: the keys
    the app itself reads (see app.keys in default.yaml), the digits (tabs), and
    r, x, y, n (radar refresh and other fixed keys)."""
    from terrascope.core.config import CFG

    keys = set("0123456789rxyn")
    for value in CFG["app"]["keys"].values():
        for item in value if isinstance(value, (list, tuple)) else [value]:
            keys.update(str(item).lower())
    return frozenset(key.lower() for key in keys)

def _text(item: dict, key: str, required: bool = False) -> str:
    value = item.get(key)
    if value is None:
        if required:
            raise ValueError(f"missing {key}")
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{key} must be text, got {value!r}")
    if required and not value.strip():
        raise ValueError(f"{key} must not be empty")
    return value

def _flag(item: dict, key: str, default: bool) -> bool:
    if key not in item or item[key] is None:
        return default
    if not isinstance(item[key], bool):
        raise TypeError(f"{key} must be true or false, got {item[key]!r}")
    return item[key]

def normalize_tab(item: Any, taken: set[str]) -> dict:
    """A plugin tab checked and rebuilt with the types the core expects, or
    ValueError / TypeError with the reason. `taken` holds the lower-case names
    already used by the built-in tabs and earlier plugin tabs."""
    from terrascope.core.config import ConfigError, parse_tab_view

    if not isinstance(item, dict):
        raise TypeError("a tab must be a mapping of keys to values")
    unknown = sorted(str(key) for key in item if key not in TAB_KEYS)
    if unknown:
        raise ValueError("unknown keys: " + ", ".join(unknown))
    name = _text(item, "name", required=True).strip()
    if name.isdigit():
        raise ValueError(f"tab name {name!r} must not be only digits (digits pick a tab by number)")
    if name.lower() in taken:
        raise ValueError(f"tab name {name!r} is already used")
    label = _text(item, "label", required=True)
    color = item.get("color")
    if not isinstance(color, str) or not _COLOUR.fullmatch(color):
        raise ValueError(f"color must be #rrggbb, got {color!r}")
    layers = item.get("layers")
    if layers is None:
        layers = []
    if not isinstance(layers, (list, tuple)) or not all(isinstance(name_, str) for name_ in layers):
        raise TypeError("layers must be a list of layer names")
    detailed = _flag(item, "detailed", False)
    try:
        view = parse_tab_view(item.get("view"), where=f"tab {name!r} view")
    except ConfigError as error:
        raise ValueError(str(error)) from error
    normalized = {
        "name": name,
        "label": label,
        "color": color,
        "blurb": _text(item, "blurb"),
        "layers": list(layers),
        "detailed": detailed,
        "provinces": _flag(item, "provinces", detailed),
        "place_names": _flag(item, "place_names", True),
        "country_names": _flag(item, "country_names", True),
        "attribution": _text(item, "attribution"),
    }
    if view is not None:
        normalized["view"] = {"lon": view[0], "lat": view[1], "zoom": view[2]}
    return normalized

def _load_plugin_tabs() -> None:
    from terrascope.core.config import CFG

    taken = {str(item.get("name")).lower() for item in CFG["tabs"]["items"] if isinstance(item, dict)}
    for entry_point in discover(TAB_GROUP):
        origin = origin_of(entry_point)
        try:
            provided = entry_point.load()()
            if not isinstance(provided, (list, tuple)):
                raise TypeError("expected a list of tab dicts")
        except Exception as error:
            log.warning("ignoring tab plugin %s (%s): %s", entry_point.name, origin, error)
            continue
        for item in provided:
            try:
                tab = normalize_tab(item, taken)
            except (TypeError, ValueError) as error:
                log.warning("ignoring a tab from %s (%s): %s", entry_point.name, origin, error)
                continue
            taken.add(tab["name"].lower())
            _PLUGIN_TABS.append(tab)
            TAB_ORIGINS[tab["name"]] = origin

def plugin_tab_items() -> list[dict]:
    """The normalised tabs of the "terrascope.tabs" plugins. Loaded on first use."""
    global _PLUGIN_TABS
    if _PLUGIN_TABS is None:
        _PLUGIN_TABS = []
        _load_plugin_tabs()
    return _PLUGIN_TABS

def tab_origin(name: str) -> str:
    plugin_tab_items()  # origins are known once the plugin tabs are loaded
    return TAB_ORIGINS.get(name, BUILTIN_ORIGIN)
