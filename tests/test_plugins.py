"""Entry-point plugins for layers and tabs.

The entry points are simulated by replacing importlib.metadata.entry_points,
so no package has to be installed for these tests.
"""

from __future__ import annotations

import copy
import importlib.metadata

import pytest

from terrascope.core import plugins, registry
from terrascope.core.layer import Layer, LayerRender
from terrascope.core.tabs import Tab, _build
from terrascope.core.config import CFG


class FakeDist:
    def __init__(self, name: str) -> None:
        self.metadata = {"Name": name}


class FakeEntryPoint:
    def __init__(self, name: str, target, dist: str = "terrascope-demo", group: str = "") -> None:
        self.name = name
        self._target = target
        self.dist = FakeDist(dist)
        self.group = group

    def load(self):
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


class DemoLayer(Layer):
    name = "demo"
    toggle_key = "j"

    def build(self, view) -> LayerRender:
        return LayerRender(None, "#000000")


class OtherLayer(Layer):
    name = "other"
    toggle_key = "y"

    def build(self, view) -> LayerRender:
        return LayerRender(None, "#000000")


class BrokenInitLayer(Layer):
    name = "broken"
    toggle_key = "z"

    def __init__(self) -> None:
        raise RuntimeError("no sensor")

    def build(self, view) -> LayerRender:
        return LayerRender(None, "#000000")


class KeyClashLayer(Layer):
    name = "clash"
    toggle_key = "P"  # same key as the built-in planes layer ("p")

    def build(self, view) -> LayerRender:
        return LayerRender(None, "#000000")


class NotALayer:
    name = "not-a-layer"


def tab_provider():
    return [
        {"name": "demo", "label": "DEMO", "color": "#123456", "blurb": "demo tab",
         "layers": ["basemap", "demo"]},
    ]


@pytest.fixture
def entry_points(monkeypatch):
    """Install a fake importlib.metadata.entry_points and reset plugin state."""
    table: dict[str, list[FakeEntryPoint]] = {}

    def fake_entry_points(group=None, **_):
        return list(table.get(group, []))

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)
    monkeypatch.setattr(plugins, "TAB_ORIGINS", {})
    return table


def add(table, group: str, entry_point: FakeEntryPoint) -> None:
    entry_point.group = group
    table.setdefault(group, []).append(entry_point)


# ---- layers --------------------------------------------------------------

def test_without_plugins_build_layers_is_unchanged(entry_points):
    layers = registry.build_layers()
    assert [layer.name for layer in layers] == [
        layer_class.name for layer_class in registry.ALL_LAYER_CLASSES
    ]
    assert {layer.origin for layer in layers} == {"built-in"}


def test_plugin_layer_is_added_after_built_ins(entry_points):
    add(entry_points, plugins.LAYER_GROUP, FakeEntryPoint("demo", DemoLayer))
    layers = registry.build_layers()
    assert [layer.name for layer in layers][-1] == "demo"
    assert layers[-1].origin == "plugin:terrascope-demo"
    assert isinstance(layers[-1], DemoLayer)


def test_broken_entry_point_is_skipped(entry_points, caplog):
    add(entry_points, plugins.LAYER_GROUP,
        FakeEntryPoint("broken-import", ImportError("missing module")))
    add(entry_points, plugins.LAYER_GROUP, FakeEntryPoint("demo", DemoLayer))
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        layers = registry.build_layers()
    assert [layer.name for layer in layers][-1] == "demo"
    assert "broken-import" in caplog.text


def test_entry_point_that_is_not_a_layer_is_skipped(entry_points):
    add(entry_points, plugins.LAYER_GROUP, FakeEntryPoint("not-layer", NotALayer))
    layers = registry.build_layers()
    assert len(layers) == len(registry.ALL_LAYER_CLASSES)


def test_plugin_whose_constructor_fails_is_skipped(entry_points, caplog):
    add(entry_points, plugins.LAYER_GROUP, FakeEntryPoint("broken", BrokenInitLayer))
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        layers = registry.build_layers()
    assert "broken" not in [layer.name for layer in layers]
    assert "could not start" in caplog.text


def test_plugin_cannot_reuse_a_built_in_name(entry_points, caplog):
    class Impostor(DemoLayer):
        name = "flights"
        toggle_key = "q"

    add(entry_points, plugins.LAYER_GROUP, FakeEntryPoint("impostor", Impostor))
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        layers = registry.build_layers()
    assert [layer.name for layer in layers].count("flights") == 1
    assert "already used" in caplog.text


def test_repeated_toggle_key_is_still_an_error(entry_points):
    add(entry_points, plugins.LAYER_GROUP, FakeEntryPoint("clash", KeyClashLayer))
    with pytest.raises(ValueError, match="both use key 'p'"):
        registry.build_layers()


# ---- tabs ----------------------------------------------------------------

def test_plugin_tab_is_appended_with_origin(entry_points):
    add(entry_points, plugins.TAB_GROUP, FakeEntryPoint("demo", tab_provider))
    items = copy.deepcopy(CFG["tabs"]["items"])
    before = len(items)
    plugins.install_plugin_tabs(items)
    assert len(items) == before + 1
    assert items[-1]["name"] == "demo"
    assert plugins.tab_origin("demo") == "plugin:terrascope-demo"
    assert plugins.tab_origin("map") == "built-in"
    tab = _build(items[-1])
    assert isinstance(tab, Tab) and tab.layers == ("basemap", "demo")


@pytest.mark.parametrize(
    "provided",
    [
        [{"name": "x", "label": "X"}],                 # no colour
        [{"name": "map", "label": "M", "color": "#000000"}],  # name taken
        ["not a dict"],
    ],
)
def test_bad_plugin_tabs_are_skipped(entry_points, caplog, provided):
    add(entry_points, plugins.TAB_GROUP, FakeEntryPoint("bad", lambda: provided))
    items = copy.deepcopy(CFG["tabs"]["items"])
    before = len(items)
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        plugins.install_plugin_tabs(items)
    assert len(items) == before
    assert "ignoring a tab from bad" in caplog.text


def test_tab_provider_that_raises_is_skipped(entry_points, caplog):
    def explode():
        raise RuntimeError("boom")

    add(entry_points, plugins.TAB_GROUP, FakeEntryPoint("explode", explode))
    items = copy.deepcopy(CFG["tabs"]["items"])
    before = len(items)
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        plugins.install_plugin_tabs(items)
    assert len(items) == before
    assert "boom" in caplog.text
