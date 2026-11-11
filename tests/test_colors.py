"""Colour pair allocation, quantising, dim drawing and palette reset."""

from __future__ import annotations

import curses
import random
import sys

import pytest

from terrascope.core.ui.colors import (
    ColorManager,
    osc_palette_reset_works,
    pair_id_limit,
    rgb_to_nearest_basic,
)
from terrascope.core.ui.constants import DIM_ATTR


def test_pair_limit_on_ncurses_layout():
    # ncurses keeps the pair id in 0xff00.
    assert pair_id_limit(0xFF00) == 256


def test_pair_limit_on_pdcurses_layout():
    # PDCurses keeps it in the top byte and reports A_COLOR as a negative number.
    assert pair_id_limit(-0x1000000) == 256


def test_pair_limit_survives_a_64_bit_chtype_without_low_bits():
    # The field sits above bit 31, so masking to 32 bits leaves nothing.
    # This used to give a negative shift and a ValueError at setup.
    assert pair_id_limit(0xFF << 40) == 256
    assert pair_id_limit(0) == 256


def test_basic_quantiser_keeps_the_eight_colours_by_default():
    assert rgb_to_nearest_basic((127, 127, 127)) != 8
    assert rgb_to_nearest_basic((0, 0, 0)) == 0
    assert rgb_to_nearest_basic((255, 255, 255)) == 7


def test_bright_quantiser_reaches_the_grey():
    assert rgb_to_nearest_basic((127, 127, 127), bright=True) == 8
    assert rgb_to_nearest_basic((255, 255, 255), bright=True) == 15


def test_dimmed_white_stays_visible_on_a_16_colour_terminal(monkeypatch):
    monkeypatch.setattr(curses, "COLORS", 16, raising=False)
    manager = ColorManager()
    manager.enabled = True
    # White dimmed on a black background is mid grey: it must not quantise
    # back to white, which is what made dim text vanish on 16-colour consoles.
    assert manager._resolve_color_slot((127, 127, 127)) == 8


def test_palette_reset_is_skipped_on_the_classic_windows_console():
    assert osc_palette_reset_works("win32", {}) is False
    assert osc_palette_reset_works("win32", {"WT_SESSION": "abc"}) is True
    assert osc_palette_reset_works("linux", {}) is True
    assert osc_palette_reset_works("darwin", {}) is True


def test_dim_attr_is_terrascope_own_and_curses_is_not_patched():
    assert DIM_ATTR
    if sys.platform == "win32":
        # windows-curses has no dim bit; the blink bit stands in, and the
        # module-level curses attribute must stay as the library ships it.
        assert DIM_ATTR == curses.A_BLINK
        assert curses.A_DIM == 0


class _FakeCurses:
    """Records colour pair and palette calls instead of drawing anything."""

    def __init__(self):
        self.pairs = {}
        self.init_pair_calls = 0

    def init_pair(self, pair_id, fg, bg):
        self.init_pair_calls += 1
        self.pairs[pair_id] = (fg, bg)

    def init_color(self, slot, r, g, b):
        raise curses.error("no palette changes in this test")

    @staticmethod
    def color_pair(pair_id):
        # Place the pair id in the real A_COLOR field of this platform.
        mask = curses.A_COLOR & 0xFFFFFFFF
        return pair_id << ((mask & -mask).bit_length() - 1)


@pytest.fixture
def fake_curses(monkeypatch):
    fake = _FakeCurses()
    monkeypatch.setattr(curses, "init_pair", fake.init_pair, raising=False)
    monkeypatch.setattr(curses, "init_color", fake.init_color, raising=False)
    monkeypatch.setattr(curses, "color_pair", fake.color_pair, raising=False)
    monkeypatch.setattr(curses, "COLORS", 256, raising=False)
    return fake


def _manager():
    manager = ColorManager()
    manager.enabled = True
    manager._pair_limit = 256
    return manager


def test_colours_on_the_same_slots_share_one_pair(fake_curses):
    manager = _manager()
    # Both resolve to palette slot 0 (black): the 256-colour quantiser takes
    # the nearest slot, and #000000 is exact.
    assert manager._slot_for_hex("#000000") == manager._slot_for_hex("#010000") == 0
    first = manager.get_pair("#000000")
    assert manager.get_pair("#010000") == first
    assert fake_curses.init_pair_calls == 1


def test_many_distinct_colours_do_not_exhaust_the_pair_budget(fake_curses):
    # 300 distinct colours land on at most 256 palette slots, so with pairs
    # shared by slot the 255-pair budget is never used up. Before pairs were
    # shared by slot, the budget ran out and every new colour was reused.
    manager = _manager()
    rng = random.Random(7)
    for _ in range(300):
        rgb = tuple(rng.randrange(256) for _ in range(3))
        manager.get_pair("#{:02x}{:02x}{:02x}".format(*rgb))
    assert manager.exhausted is False
    assert fake_curses.init_pair_calls < 255


def test_dimmed_attributes_are_cached_per_attribute(fake_curses):
    manager = _manager()
    attribute = manager.get_pair("#ffffff")
    calls_before = fake_curses.init_pair_calls
    first = manager.dimmed(attribute | DIM_ATTR)
    second = manager.dimmed(attribute | DIM_ATTR)
    assert first == second
    # The dimmed colour is one new pair; asking again creates nothing.
    assert fake_curses.init_pair_calls == calls_before + 1
    assert manager.dimmed(attribute | DIM_ATTR) == first
    assert fake_curses.init_pair_calls == calls_before + 1


def test_reset_forgets_shared_pairs_and_dim_cache(fake_curses):
    manager = _manager()
    manager.get_pair("#ffffff")
    manager.dimmed(manager.get_pair("#ffffff") | DIM_ATTR)
    manager.reset()
    assert manager._pair_by_slots == {}
    assert manager._dimmed_by_attr == {}
    assert manager._pair_by_hex == {}
