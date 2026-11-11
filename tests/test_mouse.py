"""Pointer event decoding, including the drag that a lost release leaves behind."""

from __future__ import annotations

import curses
import sys

import pytest

from terrascope.core.app.mouse import MouseMixin, pointer_event_kind
from terrascope.core.app.shared import mouse_tracking_sequences, MOUSE_MOTION_ON, MOUSE_MOTION_OFF


HOVER = curses.REPORT_MOUSE_POSITION
HELD_OR_NONE = 0


def test_press_release_and_wheel_keep_their_meaning():
    assert pointer_event_kind(curses.BUTTON1_PRESSED, False, True) == "press"
    assert pointer_event_kind(curses.BUTTON1_RELEASED, True, True) == "release"
    assert pointer_event_kind(curses.BUTTON4_PRESSED, False, True) == "scroll_up"
    assert pointer_event_kind(curses.BUTTON5_PRESSED, False, True) == "scroll_down"


def test_bstate_zero_is_motion_only_during_a_drag():
    assert pointer_event_kind(HELD_OR_NONE, True, True) == "motion"
    assert pointer_event_kind(HELD_OR_NONE, False, True) is None


def test_hover_with_no_button_ends_a_drag_on_windows():
    assert pointer_event_kind(HOVER, True, True) == "lost_release"


def test_hover_with_no_button_on_ncurses_is_plain_motion():
    # Other platforms keep the drag going, as before.
    assert pointer_event_kind(HOVER, True, False) == "motion"


def test_move_with_the_button_bit_set_keeps_the_drag_on_windows():
    assert pointer_event_kind(HOVER | curses.BUTTON1_PRESSED, True, True) == "motion"


def test_hover_without_a_drag_is_motion():
    assert pointer_event_kind(HOVER, False, True) == "motion"


class _Pointer(MouseMixin):
    """Just enough of the app for handle_mouse(): drag state and a recorder."""

    def __init__(self):
        self._drag = None
        self._slider_drag = False
        self.events = []

    def _mouse_event(self, kind, x, y):
        self.events.append((kind, x, y))


@pytest.fixture
def windows_console(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    return monkeypatch


def _report(monkeypatch, state, x=10, y=5):
    monkeypatch.setattr(curses, "getmouse", lambda: (0, x, y, 0, state), raising=False)


def test_lost_release_drops_the_map_grab_instead_of_panning(windows_console):
    app = _Pointer()
    app._drag = [10, 5, 10, 5, True, 0.0]
    _report(windows_console, HOVER, x=30, y=9)
    app.handle_mouse()
    assert app._drag is None
    assert app.events == []


def test_lost_release_drops_the_slider_grab(windows_console):
    app = _Pointer()
    app._slider_drag = True
    _report(windows_console, HOVER)
    app.handle_mouse()
    assert app._slider_drag is False
    assert app.events == []


def test_drag_continues_while_the_button_is_reported_held(windows_console):
    app = _Pointer()
    app._drag = [10, 5, 10, 5, False, 0.0]
    _report(windows_console, HELD_OR_NONE, x=12, y=5)
    app.handle_mouse()
    assert app._drag is not None
    assert app.events == [("motion", 12, 5)]


def test_click_without_a_drag_is_still_a_press(windows_console):
    app = _Pointer()
    _report(windows_console, curses.BUTTON1_PRESSED, x=3, y=4)
    app.handle_mouse()
    assert app.events == [("press", 3, 4)]


def test_mouse_tracking_is_not_requested_on_windows():
    assert mouse_tracking_sequences("win32") == ("", "")


def test_mouse_tracking_is_requested_elsewhere():
    assert mouse_tracking_sequences("linux") == (MOUSE_MOTION_ON, MOUSE_MOTION_OFF)
    assert MOUSE_MOTION_ON.startswith("\033[")
