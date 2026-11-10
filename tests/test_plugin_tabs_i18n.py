"""Plugin tab labels and blurbs go through the core translation (`_()`)."""

from __future__ import annotations

import copy
import importlib.metadata

import pytest

from terrascope.core import i18n, plugins
from terrascope.core.config import CFG
from terrascope.core.tabs import _build


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
def tab_entry_points(monkeypatch):
    table: dict[str, list[FakeEntryPoint]] = {}

    def fake_entry_points(group=None, **_):
        return list(table.get(group, []))

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)
    monkeypatch.setattr(plugins, "TAB_ORIGINS", {})
    yield table
    i18n.activate("en")


def test_plugin_tab_text_is_translated_when_the_core_has_the_message(tab_entry_points):
    # "MAP" and "live aircraft" are msgids of the core pt_BR catalogue.
    provided = [{"name": "demo", "label": "MAP", "color": "#123456",
                 "blurb": "live aircraft", "layers": ["basemap"]}]
    tab_entry_points[plugins.TAB_GROUP] = [FakeEntryPoint("demo", lambda: provided)]
    items = copy.deepcopy(CFG["tabs"]["items"])
    plugins.install_plugin_tabs(items)

    i18n.activate("pt_BR")
    tab = _build(items[-1])
    assert tab.label == "MAPA"
    assert tab.blurb == "aeronaves ao vivo"


def test_plugin_tab_text_stays_as_written_when_there_is_no_translation(tab_entry_points):
    provided = [{"name": "demo", "label": "DEMO", "color": "#123456", "blurb": "a demo tab"}]
    tab_entry_points[plugins.TAB_GROUP] = [FakeEntryPoint("demo", lambda: provided)]
    items = copy.deepcopy(CFG["tabs"]["items"])
    plugins.install_plugin_tabs(items)

    i18n.activate("pt_BR")
    tab = _build(items[-1])
    assert tab.label == "DEMO"
    assert tab.blurb == "a demo tab"
