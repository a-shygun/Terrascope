"""Test setup: keep configuration and cache out of the user's profile, and compile the catalogues.

terrascope reads its config and creates its cache directory when the modules
are imported, so the XDG locations must be set before any test imports them.
"""

from __future__ import annotations

import os
from pathlib import Path

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
