# registry.py — THE FIXED LIST OF LAYERS
# Responsible for: ALL_LAYER_CLASSES, the list of layer classes the app starts
# with, and build_layers(), which instantiates them in that order and checks
# that no two layers share a toggle key.
# Edit this file to: add or remove a layer class from the app entirely. To
# add a brand new layer, write its file under terrascope/layers/ first, then list
# its class here. The order of the list is the draw order (first = underneath).
# Not here: which layers are *enabled* at launch (each layer's own `enabled`
# default in its file / --disable-layer in cli.py; see tabs.py for which
# layers a tab switches on).

from __future__ import annotations

from terrascope.core import plugins
from terrascope.core.layer import Layer
from terrascope.layers.basemap import BaseMapLayer
from terrascope.layers.daynight import DayNightLayer
from terrascope.layers.flights import FlightsLayer
from terrascope.layers.weather import WeatherLayer

ALL_LAYER_CLASSES: tuple[type[Layer], ...] = (
    BaseMapLayer,
    DayNightLayer,
    FlightsLayer,
    WeatherLayer,
)

# Layers from installed packages (entry point group "terrascope.layers") come
# after the built-in ones, so they are drawn on top of them. See plugins.py.

def plugin_layer_classes() -> list[tuple[type[Layer], str]]:
    """Plugin layer classes that can be added, as (class, origin). A plugin is
    skipped when its `name` is already used by a built-in layer or by an
    earlier plugin, so --disable-layer and the tab lists stay unambiguous."""
    taken = {layer_class.name for layer_class in ALL_LAYER_CLASSES}
    reserved = plugins.reserved_toggle_keys()
    accepted: list[tuple[type[Layer], str]] = []
    for layer_class, origin in plugins.load_layer_classes():
        if layer_class.name in taken:
            plugins.log.warning(
                "ignoring layer plugin %s (%s): name %r is already used",
                layer_class.__name__, origin, layer_class.name,
            )
            continue
        key = str(layer_class.toggle_key or "").lower()
        if key and key in reserved:
            plugins.log.warning(
                "ignoring layer plugin %s (%s): toggle key %r is used by the app",
                layer_class.__name__, origin, layer_class.toggle_key,
            )
            continue
        taken.add(layer_class.name)
        accepted.append((layer_class, origin))
    return accepted

def check_toggle_keys(layers: list[Layer]) -> None:
    seen: dict[str, str] = {}
    for layer in layers:
        key = layer.toggle_key.lower()
        if not key:
            continue
        if key in seen:
            raise ValueError(
                f"Layers '{seen[key]}' and '{layer.name}' both use key '{key}'"
            )
        seen[key] = layer.name

def build_layers() -> list[Layer]:
    """One instance of each layer in ALL_LAYER_CLASSES, in order, then one of
    each usable plugin layer. A plugin layer whose constructor fails is skipped
    with a log line; a built-in one still raises."""
    entries: list[tuple[type[Layer], str]] = [
        (layer_class, plugins.BUILTIN_ORIGIN) for layer_class in ALL_LAYER_CLASSES
    ]
    entries.extend(plugin_layer_classes())
    layers: list[Layer] = []
    for layer_class, origin in entries:
        try:
            layer = layer_class()
        except Exception as error:
            if origin == plugins.BUILTIN_ORIGIN:
                raise
            plugins.log.warning(
                "ignoring layer plugin %s (%s): could not start it: %s",
                layer_class.__name__, origin, error,
            )
            continue
        layer.origin = origin
        layers.append(layer)
    check_toggle_keys(layers)
    return layers
