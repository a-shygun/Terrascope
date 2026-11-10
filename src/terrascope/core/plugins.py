# plugins.py — THIRD-PARTY EXTENSION POINTS (entry points)
# Responsible for: finding the layer and tab plugins that other installed
# packages register under the entry-point groups "terrascope.layers" and
# "terrascope.tabs", validating them, and skipping (with a log line) any plugin
# that fails, so a broken plugin never stops the app. Also remembers where each
# plugin came from ("plugin:<distribution>") for --list-layers / --list-tabs.
# Edit this file to: change how plugins are discovered or validated.
# Not here: the built-in layers (registry.py) or the built-in tabs
# (assets/default.yaml). This module imports only the standard library on
# purpose: the CLI imports it before every setting is final, and importing
# layer or tab modules at that point would freeze their constants too early.

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any

LAYER_GROUP = "terrascope.layers"
TAB_GROUP = "terrascope.tabs"
BUILTIN_ORIGIN = "built-in"

log = logging.getLogger("terrascope.plugins")

# Tab name -> origin, for the tabs install_plugin_tabs() added.
TAB_ORIGINS: dict[str, str] = {}

# Keys a plugin tab must have (same meaning as in tabs.items of default.yaml).
REQUIRED_TAB_KEYS = ("name", "label", "color")

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

def install_plugin_tabs(items: list) -> None:
    """Append the tabs that "terrascope.tabs" plugins provide to `items` (the
    tabs.items list of the config), in place. Each entry point is a callable
    returning a list of dicts in the same shape as tabs.items. A tab with a
    missing key or a name that is already taken is skipped with a log line."""
    names = {str(item.get("name")) for item in items if isinstance(item, dict)}
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
                if not isinstance(item, dict):
                    raise TypeError("a tab must be a dict")
                missing = [key for key in REQUIRED_TAB_KEYS if not item.get(key)]
                if missing:
                    raise ValueError("missing " + ", ".join(missing))
                name = str(item["name"])
                if name in names:
                    raise ValueError(f"tab name {name!r} is already used")
            except (TypeError, ValueError) as error:
                log.warning("ignoring a tab from %s (%s): %s", entry_point.name, origin, error)
                continue
            names.add(name)
            items.append(dict(item))
            TAB_ORIGINS[name] = origin

def tab_origin(name: str) -> str:
    return TAB_ORIGINS.get(name, BUILTIN_ORIGIN)
