"""The pseudo-language generator used to check layouts (tools/pseudo_locale.py)."""

from __future__ import annotations

import pathlib
import sys

from babel.messages.mofile import read_mo

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import pseudo_locale  # noqa: E402


def test_pseudo_text_is_wrapped_accented_and_longer():
    text = "Terminal too small"
    result = pseudo_locale.pseudo(text)
    assert result.startswith("[") and result.endswith("]")
    assert len(result) >= round(len(text) * 1.3) + 2
    assert "Ť" in result  # accented, not plain English


def test_placeholders_are_kept_intact():
    result = pseudo_locale.pseudo("Could not load map data: {error}")
    assert "{error}" in result


def test_printf_style_directives_are_kept_intact():
    assert "%d" in pseudo_locale.pseudo("%d planes")


def test_empty_message_stays_empty():
    assert pseudo_locale.pseudo("") == ""


def test_build_writes_a_loadable_catalogue(tmp_path):
    target = pseudo_locale.build(tmp_path)
    assert (target / "terrascope.po").is_file()
    with open(target / "terrascope.mo", "rb") as handle:
        catalog = read_mo(handle)
    assert catalog["OFF"].string.startswith("[")
