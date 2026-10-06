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
    """One instance of each layer in ALL_LAYER_CLASSES, in order."""
    layers = [layer_class() for layer_class in ALL_LAYER_CLASSES]
    check_toggle_keys(layers)
    return layers
