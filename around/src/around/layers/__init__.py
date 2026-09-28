from __future__ import annotations
import importlib
import pkgutil
from around.config import RESERVED_KEYS
from around.core.layer import Layer


def check_toggle_keys(layers: list[Layer]) -> None:
    seen: dict[str, str] = {}
    for layer in layers:
        key = layer.toggle_key.lower()
        if not key:
            continue
        if key in RESERVED_KEYS:
            raise ValueError(f"Layer '{layer.name}' uses reserved key '{key}'")
        if key in seen:
            raise ValueError(
                f"Layers '{seen[key]}' and '{layer.name}' both use key '{key}'"
            )
        seen[key] = layer.name


def discover_layers() -> list[Layer]:
    classes: list[type[Layer]] = []
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        for value in vars(module).values():
            if (
                not isinstance(value, type)
                or not issubclass(value, Layer)
                or value is Layer
            ):
                continue
            owned = value.__module__ == module.__name__ or value.__module__.startswith(
                module.__name__ + "."
            )
            if owned and value not in classes:
                classes.append(value)
    layers = [layer_class() for layer_class in classes]
    layers.sort(key=lambda layer: layer.order)
    check_toggle_keys(layers)
    return layers
