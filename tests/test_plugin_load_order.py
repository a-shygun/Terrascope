"""Plugin tabs are read after the settings are final. A plugin module that reads a
setting when it is imported must see the value the command line gave it, here
--offline (FETCH_NEW_DATA_FROM_API)."""

from __future__ import annotations

import copy
import importlib
import os
import sys
import uuid

import pytest

from terrascope.core import cli, config, plugins

PROBE_SOURCE = '''
from terrascope.core.config import FETCH_NEW_DATA_FROM_API

# Read once, when the module is imported, as a plugin module may do.
SEEN_FETCH = FETCH_NEW_DATA_FROM_API

def provider():
    return [{"name": "probe", "label": "PROBE", "color": "#123456", "blurb": str(SEEN_FETCH)}]
'''


@pytest.fixture
def restore_settings(monkeypatch):
    """Start the way a user's session starts: online, as terrascope.core.config saw
    it at import (the test sandbox sets terrascope_OFFLINE=1 for the whole run).
    cli.run() then changes the settings and the environment; both are put back
    afterwards, the sandbox value included."""
    snapshot = copy.deepcopy(config.CFG)
    saved = os.environ.pop("terrascope_OFFLINE", None)
    monkeypatch.setattr(config, "FETCH_NEW_DATA_FROM_API", True)
    yield
    if saved is None:
        os.environ.pop("terrascope_OFFLINE", None)
    else:
        os.environ["terrascope_OFFLINE"] = saved
    config.CFG.clear()
    config.CFG.update(snapshot)
    config.refresh_derived()


def _probe_entry_point(fake_entry_point, module_name):
    class ProbeEntryPoint(fake_entry_point):
        def load(self):
            return importlib.import_module(module_name).provider

    return ProbeEntryPoint("probe", None)


@pytest.mark.parametrize(
    "flags, fetch_seen",
    [(["--offline"], False), ([], True)],
)
def test_plugin_module_sees_the_flags_it_is_imported_with(
    tmp_path, monkeypatch, entry_points, fake_entry_point, restore_settings, flags, fetch_seen
):
    module_name = f"terrascope_probe_{uuid.uuid4().hex}"
    (tmp_path / f"{module_name}.py").write_text(PROBE_SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    entry_points[plugins.TAB_GROUP] = [_probe_entry_point(fake_entry_point, module_name)]
    monkeypatch.setattr(sys, "argv", ["terrascope", *flags, "--tab", "probe", "--list-tabs"])

    cli.run()

    assert sys.modules[module_name].SEEN_FETCH is fetch_seen
    assert plugins.tab_origin("probe") == "plugin:terrascope-demo"
