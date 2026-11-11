"""Test setup: keep configuration and cache out of the user's profile.

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
