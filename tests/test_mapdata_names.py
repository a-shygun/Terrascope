"""Portuguese country names taken from the downloaded countries file (core/mapdata.py)."""

from __future__ import annotations

import json

import pytest

from terrascope.core import i18n, mapdata

FILE = "countries_test.geojson"


def _feature(name, iso_a2, iso_a2_eh, name_pt):
    return {"type": "Feature", "properties": {
        "NAME": name, "ISO_A2": iso_a2, "ISO_A2_EH": iso_a2_eh, "NAME_PT": name_pt}, "geometry": None}


# Codes repeat in Natural Earth: CN, SG and SL belong to two features each, and
# -99 stands for several countries. Names and unique codes must still decide.
FEATURES = [
    _feature("China", "CN", "CN", "China"),
    _feature("N. Cyprus", -99, -99, "Chipre do Norte"),
    _feature("Singapore", "SG", "SG", "Singapura"),
    _feature("Siachen Glacier", "SG", -99, "Glaciar de Siachen"),
    _feature("Sierra Leone", "SL", "SL", "Serra Leoa"),
    _feature("Somaliland", "SL", -99, "Somalilândia"),
    _feature("Australia", "AU", "AU", "Austrália"),
    _feature("Indian Ocean Ter.", -99, "AU", "Territórios australianos do Oceano Índico"),
    _feature("Norway (mainland)", -99, "NO", "Noruega"),
    _feature("Kosovo", -99, "XK", "Kosovo"),
    _feature("Taiwan", "CN-TW", "TW", "Taiwan"),
]

# (code, English name) as in reference_data.json; coordinates and sizes are not used here.
REFERENCE = [
    ("CN", "China"),
    ("CN", "Turkish Republic of Northern Cyprus"),
    ("SG", "Singapore"),
    ("SL", "Sierra Leone"),
    ("AU", "Australia"),
    ("NO", "Norway"),
    ("XK", "Kosovo"),
    ("TW", "Taiwan"),
]


@pytest.fixture
def portuguese(tmp_path, monkeypatch):
    monkeypatch.setattr(mapdata, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mapdata, "MAP_FILE", FILE)
    monkeypatch.setattr(mapdata, "_PORTUGUESE_NAMES", None)
    monkeypatch.setattr(mapdata, "_reference_data", lambda: {"country_labels": [
        (0.0, 0.0, code, 1.0, name) for code, name in REFERENCE]})
    i18n.activate("pt_BR")
    yield tmp_path
    i18n.activate("en")


def _write(folder, features):
    (folder / FILE).write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


def _names():
    return {code: name for _lon, _lat, code, _size, name in mapdata.load_country_labels()}


def _labels():
    return [name for _lon, _lat, _code, _size, name in mapdata.load_country_labels()]


def test_repeated_code_does_not_pick_the_wrong_country(portuguese):
    """The bundled table gives CN to China and to Northern Cyprus, while the file has no CN
    for Northern Cyprus: that label must not read 'China'."""
    _write(portuguese, FEATURES)
    labels = _labels()
    assert labels[0] == "China"
    assert labels[1] != "China"
    assert labels[1] == "Turkish Republic of Northern Cyprus"  # CN is ambiguous: English kept


def test_singapore_and_sierra_leone_keep_their_own_names(portuguese):
    _write(portuguese, FEATURES)
    labels = _labels()
    assert labels[2] == "Singapura"  # SG is shared with Siachen Glacier
    assert labels[3] == "Serra Leoa"  # SL is shared with Somaliland


def test_australia_is_not_taken_from_a_territory(portuguese):
    _write(portuguese, FEATURES)
    assert _labels()[4] == "Austrália"


def test_iso_a2_minus_99_does_not_block_the_unique_eh_code(portuguese):
    """ISO_A2 is -99 for Norway (and France, Kosovo...), but ISO_A2_EH has the code."""
    _write(portuguese, FEATURES)
    assert _names()["NO"] == "Noruega"
    assert _names()["XK"] == "Kosovo"


def test_missing_file_is_not_remembered(portuguese):
    """Before the countries file is cached the English names are used, and the
    next call must read the file once it appears (no empty result cached)."""
    before = _labels()
    assert before[2] == "Singapore"
    assert mapdata._PORTUGUESE_NAMES is None
    _write(portuguese, FEATURES)
    assert _labels()[2] == "Singapura"


def test_english_interface_ignores_the_file(portuguese):
    _write(portuguese, FEATURES)
    i18n.activate("en")
    assert _labels()[2] == "Singapore"
