"""Plugin tab labels and blurbs go through the core translation (`_()`)."""

from __future__ import annotations

import pytest

from terrascope.core import config, i18n, plugins
from terrascope.core.tabs import _build


@pytest.fixture
def language():
    yield
    i18n.activate("en")


def test_plugin_tab_text_is_translated_when_the_core_has_the_message(entry_points, fake_entry_point, language):
    # "MAP" and "live aircraft" are msgids of the core pt_BR catalogue.
    provided = [{"name": "demo", "label": "MAP", "color": "#123456",
                 "blurb": "live aircraft", "layers": ["basemap"]}]
    entry_points[plugins.TAB_GROUP] = [fake_entry_point("demo", lambda: provided)]
    item = config.tab_items()[-1]

    i18n.activate("pt_BR")
    tab = _build(item)
    assert tab.label == "MAPA"
    assert tab.blurb == "aeronaves ao vivo"


def test_plugin_tab_text_stays_as_written_when_there_is_no_translation(entry_points, fake_entry_point, language):
    provided = [{"name": "demo", "label": "DEMO", "color": "#123456", "blurb": "a demo tab"}]
    entry_points[plugins.TAB_GROUP] = [fake_entry_point("demo", lambda: provided)]
    item = config.tab_items()[-1]

    i18n.activate("pt_BR")
    tab = _build(item)
    assert tab.label == "DEMO"
    assert tab.blurb == "a demo tab"
