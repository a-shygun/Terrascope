"""terrascope: an interactive terminal map."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _project_version() -> str | None:
    project_file = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if not project_file.is_file():
        return None

    contents = project_file.read_text(encoding="utf-8")
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        try:
            import tomli as tomllib
        except ModuleNotFoundError:
            tomllib = None

    if tomllib is not None:
        return tomllib.loads(contents)["project"]["version"]

    # Keep source checkouts usable on Python 3.10 without adding a TOML runtime
    # dependency; pyproject.toml's project version is a simple quoted value.
    project = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", contents)
    match = (
        re.search(r"(?m)^version\s*=\s*['\"]([^'\"]+)['\"]\s*$", project[1])
        if project
        else None
    )
    return match[1] if match else None


__version__ = _project_version()
if __version__ is None:
    try:
        __version__ = version("terrascope")
    except PackageNotFoundError:
        __version__ = "unknown"
