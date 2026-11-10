"""Test setup: keep configuration and cache out of the user's profile, and compile the catalogues.

terrascope reads its config and creates its cache directory when the modules
are imported, so the XDG locations must be set before any test imports them.
"""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path

import pytest

_SANDBOX = Path(__file__).resolve().parents[1] / ".cache-test"
os.environ["XDG_CONFIG_HOME"] = str(_SANDBOX / "config")
os.environ["XDG_CACHE_HOME"] = str(_SANDBOX / "cache")
os.environ.setdefault("terrascope_OFFLINE", "1")
os.environ.pop("terrascope_CONFIG", None)
os.environ.pop("terrascope_LOCALE_DIR", None)

ROOT = Path(__file__).resolve().parents[1]
LOCALE = ROOT / "src" / "terrascope" / "locale"


def _compile_catalogues() -> None:
    """The .mo files are build output (not in git). Compile them when missing,
    so a fresh checkout with Babel installed can run the tests."""
    try:
        from babel.messages.mofile import write_mo
        from babel.messages.pofile import read_po
    except ImportError:  # Babel is a build dependency; tests need it for this
        return
    for po in LOCALE.glob("*/LC_MESSAGES/terrascope.po"):
        mo = po.with_suffix(".mo")
        if mo.exists() and mo.stat().st_mtime >= po.stat().st_mtime:
            continue
        with open(po, "rb") as source:
            catalog = read_po(source)
        with open(mo, "wb") as target:
            write_mo(target, catalog)


_compile_catalogues()


# ---- fake entry points ---------------------------------------------------------

class FakeDist:
    def __init__(self, name: str) -> None:
        self.metadata = {"Name": name}


class FakeEntryPoint:
    """Stands in for importlib.metadata.EntryPoint: a name, a target and a distribution."""

    def __init__(self, name: str, target, dist: str = "terrascope-demo") -> None:
        self.name = name
        self._target = target
        self.dist = FakeDist(dist)

    def load(self):
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


@pytest.fixture
def fake_entry_point():
    """The FakeEntryPoint class, for building entry points in a test."""
    return FakeEntryPoint


@pytest.fixture
def entry_points(monkeypatch):
    """A table {group: [entry points]} served by a fake importlib.metadata.entry_points,
    with the plugin state reset before and after each test."""
    from terrascope.core import plugins

    table: dict[str, list[FakeEntryPoint]] = {}

    def fake_entry_points(group=None, **_):
        return list(table.get(group, []))

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)
    monkeypatch.setattr(plugins, "TAB_ORIGINS", {})
    monkeypatch.setattr(plugins, "_PLUGIN_TABS", None)
    return table
