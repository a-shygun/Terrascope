"""Dismissing a failed state/province border download clears the error (core/app/mouse.py)."""

from __future__ import annotations

import pytest

from terrascope.core import i18n
from terrascope.core.app.mouse import is_border_download_failure


@pytest.fixture(autouse=True)
def restore_language():
    yield
    i18n.activate("en")


@pytest.mark.parametrize("language", ["en", "pt_BR"])
def test_failed_border_download_with_size_is_recognised(language):
    """The status is 'DOWNLOAD BORDERS 10M FAILED: …', not 'DOWNLOAD BORDERS FAILED'."""
    i18n.activate(language)
    message = f"{i18n._('DOWNLOAD')} {i18n._('BORDERS')} 10M {i18n._('FAILED')}: timed out"
    assert is_border_download_failure(message)


@pytest.mark.parametrize("language", ["en", "pt_BR"])
def test_other_statuses_are_not_borders(language):
    i18n.activate(language)
    assert not is_border_download_failure(f"{i18n._('LOADING')} {i18n._('BORDERS')} 10M 40%")
    assert not is_border_download_failure(f"{i18n._('DOWNLOAD')} {i18n._('COUNTRIES')} 50M {i18n._('FAILED')}")
