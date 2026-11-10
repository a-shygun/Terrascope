"""Home view of a tab (`view: {lat, lon, zoom}`), validated for built-in and plugin
tabs, applied when the tab opens, and used by the reset key (0)."""

from __future__ import annotations

import copy
import math
import types

import pytest

from terrascope.core import config
from terrascope.core.app import input as input_module
from terrascope.core.app.input import InputMixin
from terrascope.core.config import CFG, ConfigError, parse_tab_view
from terrascope.core.tabs import Tab, _build
from terrascope.core.world import WorldMap

BRAZIL = {"lat": -14, "lon": -52, "zoom": 3}


# ---- parsing -------------------------------------------------------------

def test_no_view_means_none():
    assert parse_tab_view(None) is None


def test_view_is_returned_as_longitude_latitude_zoom():
    assert parse_tab_view(BRAZIL) == (-52.0, -14.0, 3.0)


@pytest.mark.parametrize(
    "value",
    [
        {"lat": -14, "lon": -52},                       # no zoom
        {"lat": -14, "lon": -52, "zoom": 3, "x": 1},    # unknown key
        "Brazil",
        {"lat": True, "lon": -52, "zoom": 3},           # bool is not a number
        {"lat": "-14", "lon": -52, "zoom": 3},
        {"lat": 95, "lon": -52, "zoom": 3},             # outside the map's range
        {"lat": -70, "lon": -52, "zoom": 3},            # below map.lat_min (-58)
        {"lat": 90, "lon": -52, "zoom": 3},             # above map.lat_max (84)
        {"lat": -14, "lon": 200, "zoom": 3},
        {"lat": -14, "lon": -52, "zoom": 100},          # above map.zoom.max
        {"lat": -14, "lon": -52, "zoom": 0.5},          # below map.zoom.min
        {"lat": math.nan, "lon": -52, "zoom": 3},
    ],
)
def test_invalid_views_are_rejected(value):
    with pytest.raises(ConfigError):
        parse_tab_view(value, where="tab 'x' view")


def test_latitude_limits_come_from_the_map_settings():
    assert parse_tab_view({"lat": CFG["map"]["lat_max"], "lon": 0, "zoom": 3})
    with pytest.raises(ConfigError):
        parse_tab_view({"lat": CFG["map"]["lat_max"] + 1, "lon": 0, "zoom": 3})


def test_built_in_tab_builds_with_its_view():
    tab = _build({"name": "brasil", "label": "BRASIL", "color": "#e15759", "view": BRAZIL})
    assert isinstance(tab, Tab)
    assert tab.view == (-52.0, -14.0, 3.0)


def test_tab_without_view_has_none():
    assert _build({"name": "map", "label": "MAP", "color": "#6bcb77"}).view is None


# ---- validation of the config ----------------------------------------------

def _config_with_tab(**overrides):
    """A copy of the live config with the first tab's keys replaced."""
    values = copy.deepcopy(CFG)
    values["tabs"]["items"][0].update(overrides)
    return values


def test_invalid_view_of_a_built_in_tab_fails_the_config_check():
    with pytest.raises(ConfigError, match="view"):
        config.validate_config(_config_with_tab(view={"lat": 95, "lon": 0, "zoom": 3}))


def test_start_tab_must_be_inside_the_tab_list():
    values = copy.deepcopy(CFG)
    values["tabs"]["start_tab"] = len(values["tabs"]["items"])
    with pytest.raises(ConfigError, match="start_tab"):
        config.validate_config(values)


# ---- the tab switch and the reset key ---------------------------------------

class _Stub(InputMixin):
    """Only the attributes that select_tab() and handle_key() read."""

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
        self.welcome_visible = False
        self.tz_dropdown_open = False
        self.panel_visible = True

    def cancel_input_mode(self) -> None:
        pass


@pytest.fixture
def two_tabs(monkeypatch):
    tabs = (
        Tab(name="plain", label="PLAIN", color="#000000", blurb=""),
        Tab(name="home", label="HOME", color="#000000", blurb="", view=(-52.0, -14.0, 3.0)),
    )
    monkeypatch.setattr(input_module, "TABS", tabs)
    return tabs


def test_selecting_a_tab_applies_its_home_view_when_it_opens(two_tabs):
    world = WorldMap([], [])
    world.zoom = 20.0
    app = _Stub(world)

    app.select_tab(0)  # no view: the current view stays
    assert world.zoom == pytest.approx(20.0)

    app.select_tab(1)  # opening the tab applies its home view
    assert world.zoom == pytest.approx(3.0)
    assert (world.center_lon, world.center_lat) == pytest.approx((-52.0, -14.0))


def test_selecting_the_same_tab_again_keeps_the_users_pan_and_zoom(two_tabs):
    world = WorldMap([], [])
    app = _Stub(world)
    app.select_tab(1)
    world.pan(1, 0)
    zoom_before = world.zoom
    center_before = (world.center_lon, world.center_lat)
    app.select_tab(1)  # same tab: nothing is reset
    assert (world.center_lon, world.center_lat) == pytest.approx(center_before)
    assert world.zoom == pytest.approx(zoom_before)


def test_reset_key_goes_back_to_the_tab_view_when_there_is_one(two_tabs):
    world = WorldMap([], [])
    app = _Stub(world)
    app.select_tab(1)
    world.pan(1, 0)
    world.zoom_in()
    app.handle_key(ord("0"))
    assert world.zoom == pytest.approx(3.0)
    assert (world.center_lon, world.center_lat) == pytest.approx((-52.0, -14.0))


def test_reset_key_goes_to_the_world_on_a_tab_without_a_view(two_tabs):
    world = WorldMap([], [])
    world.zoom = 20.0
    app = _Stub(world)
    app.select_tab(0)
    app.handle_key(ord("0"))
    assert world.zoom == pytest.approx(config.CFG["map"]["zoom"]["min"])


def test_set_view_sets_centre_and_zoom_and_can_zoom_out():
    world = WorldMap([], [])
    world.zoom = 20.0
    world.set_view(-52.0, -14.0, 3.0)
    assert world.zoom == pytest.approx(3.0)
    assert (world.center_lon, world.center_lat) == pytest.approx((-52.0, -14.0))
