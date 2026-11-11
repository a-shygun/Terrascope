"""Generate the Scoop and winget manifests for a Terrascope release.

Usage:
    python packaging/windows/make_manifests.py --version 1.1.0 \
        --checksums release-assets/terrascope_checksums.txt --output release-assets

Writes, under OUTPUT:
    terrascope.json                       Scoop manifest (`scoop install <url-of-this-file>`)
    winget/<version>/AShygun.Terrascope*.yaml  winget manifests, ready for a winget-pkgs pull request

Both point at the `terrascope_<version>_windows_x86_64.zip` release asset and take its SHA-256
from the release checksum file, so nothing has to be edited by hand.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPOSITORY = "https://github.com/a-shygun/Terrascope"
PACKAGE_ID = "AShygun.Terrascope"
PUBLISHER = "Amir Shygun"
DESCRIPTION = "A Braille terminal map with live weather, aircraft, and earthquake layers."
MANIFEST_VERSION = "1.10.0"


def asset_name(version: str) -> str:
    return f"terrascope_{version}_windows_x86_64.zip"


def asset_url(version: str) -> str:
    return f"{REPOSITORY}/releases/download/v{version}/{asset_name(version)}"


def read_sha256(checksums: Path, name: str) -> str:
    for line in checksums.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    raise SystemExit(f"{name} not found in {checksums}")


def scoop_manifest(version: str, sha256: str) -> dict:
    return {
        "version": version,
        "description": DESCRIPTION,
        "homepage": REPOSITORY,
        "license": "MIT",
        "architecture": {"64bit": {"url": asset_url(version), "hash": sha256}},
        "bin": "terrascope.exe",
        "checkver": "github",
        "autoupdate": {
            "architecture": {
                "64bit": {
                    "url": f"{REPOSITORY}/releases/download/v$version/terrascope_$version_windows_x86_64.zip"
                }
            },
            "hash": {"url": "$baseurl/terrascope_checksums.txt"},
        },
    }


def winget_manifests(version: str, sha256: str) -> dict[str, str]:
    header = "# yaml-language-server: $schema=https://aka.ms/winget-manifest.{kind}.{mv}.schema.json\n\n"
    common = f"PackageIdentifier: {PACKAGE_ID}\nPackageVersion: {version}\n"
    return {
        f"{PACKAGE_ID}.yaml": header.format(kind="version", mv=MANIFEST_VERSION)
        + common
        + f"DefaultLocale: en-US\nManifestType: version\nManifestVersion: {MANIFEST_VERSION}\n",
        f"{PACKAGE_ID}.installer.yaml": header.format(kind="installer", mv=MANIFEST_VERSION)
        + common
        + "InstallerType: zip\n"
        + "NestedInstallerType: portable\n"
        + "NestedInstallerFiles:\n"
        + "  - RelativeFilePath: terrascope.exe\n"
        + "    PortableCommandAlias: terrascope\n"
        + "Installers:\n"
        + "  - Architecture: x64\n"
        + f"    InstallerUrl: {asset_url(version)}\n"
        + f"    InstallerSha256: {sha256.upper()}\n"
        + f"ManifestType: installer\nManifestVersion: {MANIFEST_VERSION}\n",
        f"{PACKAGE_ID}.locale.en-US.yaml": header.format(kind="defaultLocale", mv=MANIFEST_VERSION)
        + common
        + "PackageLocale: en-US\n"
        + f"Publisher: {PUBLISHER}\n"
        + f"PublisherUrl: https://github.com/a-shygun\n"
        + "PackageName: Terrascope\n"
        + f"PackageUrl: {REPOSITORY}\n"
        + "License: MIT\n"
        + f"LicenseUrl: {REPOSITORY}/blob/main/LICENSE\n"
        + f"ShortDescription: {DESCRIPTION}\n"
        + "Moniker: terrascope\n"
        + "Tags:\n  - terminal\n  - tui\n  - map\n  - weather\n  - flight-tracking\n"
        + f"ReleaseNotesUrl: {REPOSITORY}/releases/tag/v{version}\n"
        + f"ManifestType: defaultLocale\nManifestVersion: {MANIFEST_VERSION}\n",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True)
    parser.add_argument("--checksums", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    version = args.version.removeprefix("v")
    sha256 = read_sha256(args.checksums, asset_name(version))

    args.output.mkdir(parents=True, exist_ok=True)
    scoop = args.output / "terrascope.json"
    scoop.write_text(json.dumps(scoop_manifest(version, sha256), indent=4) + "\n", encoding="utf-8", newline="\n")
    print(scoop)
    winget_dir = args.output / "winget" / version
    winget_dir.mkdir(parents=True, exist_ok=True)
    for name, text in winget_manifests(version, sha256).items():
        path = winget_dir / name
        path.write_text(text, encoding="utf-8", newline="\n")
        print(path)


if __name__ == "__main__":
    main()
