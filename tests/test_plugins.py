"""Entry-point plugins for layers and tabs. The entry points come from the
`entry_points` and `fake_entry_point` fixtures in conftest.py."""

from __future__ import annotations

import pytest

from terrascope.core import config, plugins, registry
from terrascope.core.config import CFG, ConfigError
from terrascope.core.layer import Layer, LayerRender


class DemoLayer(Layer):
    name = "demo"
    toggle_key = "j"

    def build(self, view) -> LayerRender:
        return LayerRender(None, "#000000")


class OtherLayer(Layer):
    name = "other"
    toggle_key = "v"  # "y" is a key the app uses (the welcome dialog)

    def build(self, view) -> LayerRender:
        return LayerRender(None, "#000000")


class BrokenInitLayer(Layer):
    name = "broken"
    toggle_key = "m"

    def __init__(self) -> None:
        raise RuntimeError("no sensor")

    def build(self, view) -> LayerRender:
        return LayerRender(None, "#000000")


class KeyClashLayer(Layer):
    name = "clash"
    toggle_key = "P"  # same key as the built-in planes layer ("p")

    def build(self, view) -> LayerRender:
        return LayerRender(None, "#000000")


class AppKeyLayer(Layer):
    name = "appkey"
    toggle_key = "r"  # radar refresh on the WEATHER tab

    def build(self, view) -> LayerRender:
        return LayerRender(None, "#000000")


class NotALayer:
    name = "not-a-layer"


def tab(**overrides):
    """A valid plugin tab, with some keys replaced."""
    item = {"name": "demo", "label": "DEMO", "color": "#123456", "blurb": "a demo tab",
            "layers": ["basemap", "demo"]}
    item.update(overrides)
    return item


# ---- layers --------------------------------------------------------------

def test_without_plugins_build_layers_is_unchanged(entry_points):
    layers = registry.build_layers()
    assert [layer.name for layer in layers] == [
        layer_class.name for layer_class in registry.ALL_LAYER_CLASSES
    ]
    assert {layer.origin for layer in layers} == {"built-in"}


def test_plugin_layer_is_added_after_built_ins(entry_points, fake_entry_point):
    entry_points[plugins.LAYER_GROUP] = [fake_entry_point("demo", DemoLayer)]
    layers = registry.build_layers()
    assert layers[-1].name == "demo"
    assert layers[-1].origin == "plugin:terrascope-demo"
    assert isinstance(layers[-1], DemoLayer)


def test_broken_entry_point_is_skipped(entry_points, fake_entry_point, caplog):
    entry_points[plugins.LAYER_GROUP] = [
        fake_entry_point("broken-import", ImportError("missing module")),
        fake_entry_point("demo", DemoLayer),
    ]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        layers = registry.build_layers()
    assert layers[-1].name == "demo"
    assert "broken-import" in caplog.text


def test_entry_point_that_is_not_a_layer_is_skipped(entry_points, fake_entry_point):
    entry_points[plugins.LAYER_GROUP] = [fake_entry_point("not-layer", NotALayer)]
    assert len(registry.build_layers()) == len(registry.ALL_LAYER_CLASSES)


def test_plugin_whose_constructor_fails_is_skipped(entry_points, fake_entry_point, caplog):
    entry_points[plugins.LAYER_GROUP] = [fake_entry_point("broken", BrokenInitLayer)]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        layers = registry.build_layers()
    assert "broken" not in [layer.name for layer in layers]
    assert "could not start" in caplog.text


def test_plugin_cannot_reuse_a_built_in_name(entry_points, fake_entry_point, caplog):
    class Impostor(DemoLayer):
        name = "flights"
        toggle_key = "q"

    entry_points[plugins.LAYER_GROUP] = [fake_entry_point("impostor", Impostor)]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        layers = registry.build_layers()
    assert [layer.name for layer in layers].count("flights") == 1
    assert "already used" in caplog.text


@pytest.mark.parametrize("layer_class", [AppKeyLayer])
def test_plugin_cannot_take_a_key_the_app_uses(entry_points, fake_entry_point, caplog, layer_class):
    entry_points[plugins.LAYER_GROUP] = [fake_entry_point("appkey", layer_class)]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        layers = registry.build_layers()
    assert "appkey" not in [layer.name for layer in layers]
    assert "used by the app" in caplog.text


def test_plugin_with_a_built_in_layers_key_is_skipped(entry_points, fake_entry_point, caplog):
    entry_points[plugins.LAYER_GROUP] = [fake_entry_point("clash", KeyClashLayer)]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        layers = registry.build_layers()
    assert "clash" not in [layer.name for layer in layers]
    assert "used by the app or a built-in layer" in caplog.text


def test_second_plugin_with_the_same_key_is_skipped_and_the_first_kept(entry_points, fake_entry_point, caplog):
    second = type("SecondDemo", (DemoLayer,), {"name": "second-demo"})
    entry_points[plugins.LAYER_GROUP] = [
        fake_entry_point("demo", DemoLayer),
        fake_entry_point("second", second),
    ]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        names = [layer.name for layer in registry.build_layers()]
    assert names[-1] == "demo"
    assert "second-demo" not in names
    assert "already used by layer 'demo'" in caplog.text


def test_two_built_in_layers_with_one_key_are_still_an_error(monkeypatch):
    class SameKeyLayer(Layer):
        name = "same-key"
        toggle_key = "j"

        def build(self, view) -> LayerRender:
            return LayerRender(None, "#000000")

    monkeypatch.setattr(registry, "ALL_LAYER_CLASSES", (DemoLayer, SameKeyLayer))
    with pytest.raises(ValueError, match="both use key 'j'"):
        registry.build_layers()


@pytest.mark.parametrize("key", ["k", "c", "e", "l"])
def test_plugin_cannot_take_a_built_in_layers_own_key(entry_points, fake_entry_point, caplog, key):
    """k (airports), c (cities), e (earthquakes) and l (day/night look) are read by
    built-in layers, not by app.keys, so they are reserved from their settings."""
    clash = type("KeyClash", (DemoLayer,), {"name": f"clash-{key}", "toggle_key": key})
    entry_points[plugins.LAYER_GROUP] = [fake_entry_point("clash", clash)]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        names = [layer.name for layer in registry.build_layers()]
    assert f"clash-{key}" not in names
    assert "used by the app or a built-in layer" in caplog.text


@pytest.mark.parametrize("key", [5, b"k", "jk", " ", "\n", "ñ"])
def test_toggle_key_that_is_not_one_visible_ascii_character_is_skipped(entry_points, fake_entry_point, caplog, key):
    odd = type("OddKey", (DemoLayer,), {"name": "odd", "toggle_key": key})
    entry_points[plugins.LAYER_GROUP] = [fake_entry_point("odd", odd)]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        names = [layer.name for layer in registry.build_layers()]
    assert "odd" not in names
    assert "toggle key must be" in caplog.text


def test_toggle_key_set_in_init_is_checked_as_well(entry_points, fake_entry_point, caplog):
    class InitKey(DemoLayer):
        name = "init-key"

        def __init__(self) -> None:
            super().__init__()
            self.toggle_key = 7  # the class says nothing; the instance sets a number

    entry_points[plugins.LAYER_GROUP] = [fake_entry_point("init", InitKey)]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        names = [layer.name for layer in registry.build_layers()]
    assert "init-key" not in names
    assert "toggle key must be one character" in caplog.text


def test_reserved_keys_cover_the_app_keys_digits_and_fixed_letters(entry_points):
    reserved = plugins.reserved_toggle_keys()
    for key in ("q", "h", "o", "w", "a", "s", "d", "z", "0", "1", "9", "r", "x", "y", "n", "+", "["):
        assert key in reserved, key
    assert "v" not in reserved and "j" not in reserved


# ---- tabs ----------------------------------------------------------------

def test_plugin_tab_is_added_with_its_origin(entry_points, fake_entry_point):
    entry_points[plugins.TAB_GROUP] = [fake_entry_point("demo", lambda: [tab()])]
    items = config.tab_items()
    assert items[-1]["name"] == "demo"
    assert items[-1]["blurb"] == "a demo tab"
    assert plugins.tab_origin("demo") == "plugin:terrascope-demo"
    assert plugins.tab_origin("map") == "built-in"


def test_plugin_tabs_are_not_saved_into_the_config(entry_points, fake_entry_point):
    entry_points[plugins.TAB_GROUP] = [fake_entry_point("demo", lambda: [tab()])]
    names_before = [item["name"] for item in CFG["tabs"]["items"]]
    assert "demo" in [item["name"] for item in config.tab_items()]
    assert [item["name"] for item in CFG["tabs"]["items"]] == names_before


def test_tuple_layers_and_null_blurb_are_accepted_and_normalised(entry_points, fake_entry_point):
    provided = [tab(layers=("basemap", "demo"), blurb=None, attribution=None)]
    entry_points[plugins.TAB_GROUP] = [fake_entry_point("demo", lambda: provided)]
    item = config.tab_items()[-1]
    assert item["layers"] == ["basemap", "demo"]
    assert item["blurb"] == "" and item["attribution"] == ""


@pytest.mark.parametrize(
    "bad",
    [
        tab(color="red"),                  # not #rrggbb
        tab(detailed=1),                   # not a bool
        tab(provinces="yes"),
        tab(layers="basemap"),             # text, not a list
        tab(layers=[1, 2]),
        tab(label=""),
        tab(name="MAP"),                   # a built-in name, in any case
        tab(name="3"),                     # digits pick a tab by number
        tab(name="  "),
        tab(unknown_key=True),
        tab(view={"lat": 95, "lon": -52, "zoom": 3}),
        tab(view={"lat": -70, "lon": -52, "zoom": 3}),  # below map.lat_min
        tab(view={"lat": -14, "lon": 10 ** 400, "zoom": 3}),  # a huge integer, not a crash
        "not a tab",
    ],
)
def test_bad_plugin_tabs_are_skipped_not_fatal(entry_points, fake_entry_point, caplog, bad):
    entry_points[plugins.TAB_GROUP] = [fake_entry_point("bad", lambda: [bad, tab(name="good")])]
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        names = [item["name"] for item in config.tab_items()]
    assert "good" in names
    assert names.count("good") == 1
    assert "ignoring a tab from bad" in caplog.text


def test_tab_names_are_compared_without_case(entry_points, fake_entry_point):
    entry_points[plugins.TAB_GROUP] = [fake_entry_point("a", lambda: [tab(name="Demo")]),
                                       fake_entry_point("b", lambda: [tab(name="DEMO")])]
    names = [item["name"] for item in config.tab_items()]
    assert names.count("Demo") + names.count("DEMO") == 1


def test_tab_provider_that_raises_is_skipped(entry_points, fake_entry_point, caplog):
    def explode():
        raise RuntimeError("boom")

    entry_points[plugins.TAB_GROUP] = [fake_entry_point("explode", explode)]
    before = len(CFG["tabs"]["items"])
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        assert len(config.tab_items()) == before
    assert "boom" in caplog.text


def test_entry_points_are_read_once_and_only_when_needed(entry_points, fake_entry_point):
    calls = []

    def provider():
        calls.append(1)
        return [tab()]

    entry_points[plugins.TAB_GROUP] = [fake_entry_point("demo", provider)]
    config.validate_config()  # the start tab is a built-in one: no plugin is read
    assert calls == []
    config.tab_items()
    config.tab_items()
    plugins.tab_origin("demo")
    assert calls == [1]
