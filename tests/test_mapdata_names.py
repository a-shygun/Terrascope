"""Portuguese country names taken from the downloaded countries file (core/mapdata.py).

The features and the reference rows are copied from ne_50m_admin_0_countries.geojson
(Natural Earth) and from reference_data.json: the reference table uses NAME_EN
("People's Republic of China"), and the file's NAME is the short form ("China").
"""

from __future__ import annotations

import json

import pytest

from terrascope.core import i18n, mapdata

FILE = "countries_test.geojson"


def _feature(name, name_en, iso_a2, iso_a2_eh, name_pt):
    return {"type": "Feature", "properties": {
        "NAME": name, "NAME_EN": name_en, "ISO_A2": iso_a2, "ISO_A2_EH": iso_a2_eh,
        "NAME_PT": name_pt}, "geometry": None}


# Codes repeat in Natural Earth: AU is Australia and a territory, -99 stands for many
# countries. Names must decide, and a code only when it identifies one feature.
FEATURES = [
    _feature("China", "People's Republic of China", "CN", "CN", "China"),
    _feature("N. Cyprus", "Turkish Republic of Northern Cyprus", -99, -99, "República Turca do Chipre do Norte"),
    _feature("Singapore", "Singapore", "SG", "SG", "Singapura"),
    _feature("Siachen Glacier", "Siachen Glacier", -99, -99, "Glaciar de Siachen"),
    _feature("Sierra Leone", "Sierra Leone", "SL", "SL", "Serra Leoa"),
    _feature("Somaliland", "Somaliland", -99, -99, "Somalilândia"),
    _feature("Australia", "Australia", "AU", "AU", "Austrália"),
    _feature("Indian Ocean Ter.", "Australian Indian Ocean Territories", -99, "AU",
             "Territórios australianos do Oceano Índico"),
    _feature("Norway", "Norway", -99, "NO", "Noruega"),
    _feature("Kosovo", "Kosovo", -99, "XK", "Kosovo"),
    _feature("Taiwan", "Taiwan", "CN-TW", "TW", "Taiwan"),
]

# (code, English name) as in reference_data.json; coordinates and sizes are not used here.
REFERENCE = [
    ("CN", "People's Republic of China"),
    ("CN", "Turkish Republic of Northern Cyprus"),
    ("SG", "Singapore"),
    ("SG", "Siachen Glacier"),
    ("SL", "Sierra Leone"),
    ("SL", "Somaliland"),
    ("AU", "Australia"),
    ("AU", "Australian Indian Ocean Territories"),
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


def test_china_is_matched_by_its_english_name(portuguese):
    """The reference label is NAME_EN; matching NAME ("China") alone left it in English."""
    _write(portuguese, FEATURES)
    assert _labels()[0] == "China"


def test_repeated_code_does_not_pick_the_wrong_country(portuguese):
    """CN belongs to China and to Northern Cyprus in the reference table: each label
    takes its own name, and Northern Cyprus does not read 'China'."""
    _write(portuguese, FEATURES)
    labels = _labels()
    assert labels[1] == "República Turca do Chipre do Norte"
    assert labels[1] != "China"


def test_singapore_and_sierra_leone_keep_their_own_names(portuguese):
    _write(portuguese, FEATURES)
    labels = _labels()
    assert labels[2] == "Singapura"  # SG is shared by Singapore and Siachen Glacier
    assert labels[4] == "Serra Leoa"  # SL is shared by Sierra Leone and Somaliland
    assert labels[5] == "Somalilândia"


def test_australia_is_not_taken_from_a_territory(portuguese):
    _write(portuguese, FEATURES)
    labels = _labels()
    assert labels[6] == "Austrália"
    assert labels[7] == "Territórios australianos do Oceano Índico"


def test_iso_a2_minus_99_does_not_block_the_unique_eh_code(portuguese):
    """ISO_A2 is -99 for Norway (and France, Kosovo...), but ISO_A2_EH has the code."""
    _write(portuguese, FEATURES)
    assert _names()["NO"] == "Noruega"
    assert _names()["XK"] == "Kosovo"


def test_name_is_the_fallback_when_name_en_is_missing(portuguese):
    """A feature without NAME_EN is matched by NAME."""
    feature = {"type": "Feature", "properties": {
        "NAME": "Norway", "NAME_PT": "Noruega", "ISO_A2": "-99", "ISO_A2_EH": "NO"}, "geometry": None}
    _write(portuguese, [feature])
    assert _labels()[8] == "Noruega"


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
    assert _labels()[0] == "People's Republic of China"
