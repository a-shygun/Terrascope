"""Check that built Terrascope distributions contain their required files."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path


def check_distributions(directory: Path) -> None:
    wheels = list(directory.glob("*.whl"))
    sdists = list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit("expected exactly one wheel and one source archive")

    required_assets = {
        "terrascope/assets/default.yaml",
        "terrascope/assets/reference_data.json",
    }
    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel_files = set(wheel.namelist())
        missing = required_assets - wheel_files
        if missing:
            raise SystemExit(f"wheel is missing required assets: {sorted(missing)}")

    required_sdist_files = {
        "/src/terrascope/assets/default.yaml",
        "/src/terrascope/assets/reference_data.json",
        "/README.md",
        "/LICENSE",
        "/docs/RELEASING.md",
    }
    with tarfile.open(sdists[0], "r:gz") as archive:
        sdist_files = {"/" + name.split("/", 1)[1] for name in archive.getnames() if "/" in name}
        missing = required_sdist_files - sdist_files
        if missing:
            raise SystemExit(f"source archive is missing required files: {sorted(missing)}")


if __name__ == "__main__":
    check_distributions(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist"))
