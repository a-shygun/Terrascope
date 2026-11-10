"""Home view of a tab (`view: {lat, lon, zoom}`) for built-in and plugin tabs."""

from __future__ import annotations

import copy
import importlib.metadata
import math
import types

import pytest

from terrascope.core import config, plugins
from terrascope.core.app import input as input_module
from terrascope.core.app.input import InputMixin
from terrascope.core.config import CFG, ConfigError, parse_tab_view
from terrascope.core.tabs import Tab, _build
from terrascope.core.world import WorldMap

BRAZIL = {"lat": -14, "lon": -52, "zoom": 3}


class FakeDist:
    def __init__(self, name: str) -> None:
        self.metadata = {"Name": name}


class FakeEntryPoint:
    def __init__(self, name: str, target) -> None:
        self.name = name
        self._target = target
        self.dist = FakeDist("terrascope-demo")

    def load(self):
        return self._target


@pytest.fixture
def entry_points(monkeypatch):
    table: dict[str, list[FakeEntryPoint]] = {}

    def fake_entry_points(group=None, **_):
        return list(table.get(group, []))

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)
    monkeypatch.setattr(plugins, "TAB_ORIGINS", {})
    return table


# ---- parsing -------------------------------------------------------------

def test_no_view_means_none():
    assert parse_tab_view(None) is None


def test_view_is_returned_as_longitude_latitude_zoom():
    assert parse_tab_view(BRAZIL) == (-52.0, -14.0, 3.0)


@pytest.mark.parametrize(
    "value",
    [
        {"lat": -14, "lon": -52},                 # no zoom
        {"lat": -14, "lon": -52, "zoom": 3, "x": 1},  # unknown key
        "Brazil",
        {"lat": True, "lon": -52, "zoom": 3},     # bool is not a number
        {"lat": "-14", "lon": -52, "zoom": 3},
        {"lat": 95, "lon": -52, "zoom": 3},
        {"lat": -14, "lon": 200, "zoom": 3},
        {"lat": -14, "lon": -52, "zoom": 100},    # above map.zoom.max
        {"lat": -14, "lon": -52, "zoom": 0.5},    # below map.zoom.min
        {"lat": math.nan, "lon": -52, "zoom": 3},
    ],
)
def test_invalid_views_are_rejected(value):
    with pytest.raises(ConfigError):
        parse_tab_view(value, where="tab 'x' view")


def test_built_in_tab_builds_with_its_view():
    tab = _build({"name": "brasil", "label": "BRASIL", "color": "#e15759", "view": BRAZIL})
    assert isinstance(tab, Tab)
    assert tab.view == (-52.0, -14.0, 3.0)


def test_tab_without_view_has_none():
    tab = _build({"name": "map", "label": "MAP", "color": "#6bcb77"})
    assert tab.view is None


# ---- plugin tabs ---------------------------------------------------------

def test_plugin_tab_with_a_valid_view_keeps_it(entry_points):
    tab_item = {"name": "demo", "label": "DEMO", "color": "#123456", "view": BRAZIL}
    entry_points[plugins.TAB_GROUP] = [FakeEntryPoint("demo", lambda: [tab_item])]
    items = copy.deepcopy(CFG["tabs"]["items"])
    plugins.install_plugin_tabs(items)
    assert _build(items[-1]).view == (-52.0, -14.0, 3.0)


def test_plugin_tab_with_an_invalid_view_is_skipped(entry_points, caplog):
    bad = {"name": "demo", "label": "DEMO", "color": "#123456",
           "view": {"lat": 95, "lon": -52, "zoom": 3}}
    entry_points[plugins.TAB_GROUP] = [FakeEntryPoint("demo", lambda: [bad])]
    items = copy.deepcopy(CFG["tabs"]["items"])
    before = len(items)
    with caplog.at_level("WARNING", logger="terrascope.plugins"):
        plugins.install_plugin_tabs(items)
    assert len(items) == before
    assert "lat must be between" in caplog.text


# ---- the world and the tab switch ----------------------------------------

def test_set_view_sets_centre_and_zoom_and_can_zoom_out():
    world = WorldMap([], [])
    world.zoom = 20.0
    world.set_view(-52.0, -14.0, 3.0)
    assert world.zoom == pytest.approx(3.0)
    assert (world.center_lon, world.center_lat) == pytest.approx((-52.0, -14.0))


class _TabSwitch(InputMixin):
    """Only the attributes select_tab() reads; the layer and colour code is out of scope."""

    def __init__(self, world: WorldMap) -> None:
        self.world = world
        self.forced_off = frozenset()
        self.provinces_visible = False
        self.info_visible = False
        self._drag = None
        self.active_tab = 0
        self._colors_reset_at = 0.0
        self.colors = types.SimpleNamespace(reset=lambda: None)
        self.mode = "normal"
        self.filter_buffer = ""
        self.search_buffer = ""

    def cancel_input_mode(self) -> None:
        pass


def test_selecting_a_tab_applies_its_home_view(monkeypatch):
    tabs = (
        Tab(name="plain", label="PLAIN", color="#000000", blurb=""),
        Tab(name="home", label="HOME", color="#000000", blurb="", view=(-52.0, -14.0, 3.0)),
    )
    monkeypatch.setattr(input_module, "TABS", tabs)
    world = WorldMap([], [])
    world.zoom = 20.0
    app = _TabSwitch(world)

    app.select_tab(0)  # no view: the current view stays
    assert world.zoom == pytest.approx(20.0)

    app.select_tab(1)  # the home view is applied, every time the tab opens
    assert world.zoom == pytest.approx(3.0)
    assert (world.center_lon, world.center_lat) == pytest.approx((-52.0, -14.0))

    world.pan(1, 0)
    app.select_tab(0)
    app.select_tab(1)
    assert world.center_lon == pytest.approx(-52.0)
