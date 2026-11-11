"""Startup stage labels (core/main.py): every stage has a translation, and the
text shown while it runs and when it fails is built from translated pieces."""

from __future__ import annotations

import pytest

from terrascope.core import i18n
from terrascope.core.main import STAGE_LABELS


@pytest.fixture(autouse=True)
def restore_language():
    yield
    i18n.activate("en")


def test_every_stage_label_is_translated_in_portuguese():
    i18n.activate("pt_BR")
    for label in STAGE_LABELS.values():
        assert i18n._(label) != label, label


def test_stage_labels_stay_english_in_english():
    i18n.activate("en")
    for label in STAGE_LABELS.values():
        assert i18n._(label) == label


def test_capital_weather_and_radar_history_have_their_own_text():
    """These two had no catalogue entry for the text shown on failure."""
    i18n.activate("pt_BR")
    assert i18n._(STAGE_LABELS["WEATHER"]) == "CARREGANDO CLIMA DAS CIDADES"
    assert i18n._(STAGE_LABELS["RADAR HISTORY"]) == "OBTENDO OUTROS HORÁRIOS DO RADAR"
