"""Checks on the translation catalogues (pt_BR) and the extraction template."""

from __future__ import annotations

import re

from babel.messages.pofile import read_po

from conftest import LOCALE  # noqa: E402  (tests/conftest.py sets up the paths)

PO = LOCALE / "pt_BR" / "LC_MESSAGES" / "terrascope.po"
POT = LOCALE / "terrascope.pot"
PLACEHOLDER = re.compile(r"\{[a-zA-Z_]+\}")


def _catalogue(path):
    with open(path, "rb") as handle:
        return read_po(handle)


def test_every_message_is_translated_and_none_is_fuzzy():
    catalogue = _catalogue(PO)
    empty, fuzzy = [], []
    for message in catalogue:
        if not message.id:
            continue
        if message.fuzzy:
            fuzzy.append(message.id)
        strings = message.string if isinstance(message.string, tuple) else (message.string,)
        if not all(strings):
            empty.append(message.id)
    assert not fuzzy, fuzzy
    assert not empty, empty


def test_catalogue_matches_the_template():
    template = {m.id for m in _catalogue(POT) if m.id}
    translated = {m.id for m in _catalogue(PO) if m.id}
    assert template == translated, (template ^ translated)


def test_placeholders_survive_translation():
    for message in _catalogue(PO):
        if not message.id or isinstance(message.id, tuple):
            continue
        source = set(PLACEHOLDER.findall(message.id))
        target = set(PLACEHOLDER.findall(message.string or ""))
        assert source == target, (message.id, source, target)


def test_plural_form_header_for_portuguese():
    header = _catalogue(PO).mime_headers
    values = dict(header)
    assert values["Plural-Forms"].startswith("nplurals=2")
    assert values["Language"] == "pt_BR"
