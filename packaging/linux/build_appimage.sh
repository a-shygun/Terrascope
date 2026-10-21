#!/usr/bin/env bash
# Build an AppImage from a PyInstaller onefile binary.
# Usage: build_appimage.sh --version 0.3.0 --platform linux_x86_64 --arch x86_64 --binary dist/terrascope --output dist
set -euo pipefail

VERSION=""
PLATFORM=""
ARCH=""
BINARY=""
OUTPUT="dist"
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --appimagetool) APPIMAGETOOL="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$VERSION" ] || [ -z "$BINARY" ]; then
  echo "usage: $0 --version VERSION --binary PATH [--platform PLATFORM] [--arch ARCH] [--output DIR]" >&2
  exit 1
fi

if [ -z "$PLATFORM" ]; then
  case "${ARCH:-x86_64}" in
    x86_64) PLATFORM="linux_x86_64" ;;
    aarch64) PLATFORM="linux_arm64" ;;
    *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
  esac
fi
if [ -z "$ARCH" ]; then
  case "$PLATFORM" in
    linux_x86_64) ARCH="x86_64" ;;
    linux_arm64) ARCH="aarch64" ;;
    *) ARCH="x86_64" ;;
  esac
fi

if [ ! -f "$BINARY" ]; then
  echo "binary not found: $BINARY" >&2
  exit 1
fi

if ! command -v "$APPIMAGETOOL" >/dev/null 2>&1; then
  echo "appimagetool not found (tried '$APPIMAGETOOL')." >&2
  echo "Download from https://github.com/AppImage/appimagetool/releases and set --appimagetool PATH or APPIMAGETOOL env." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP="$REPO_ROOT/packaging/linux/terrascope.desktop"
ICON="$REPO_ROOT/packaging/linux/terrascope.png"
APPRUN_SRC="$REPO_ROOT/packaging/linux/AppRun"

for f in "$DESKTOP" "$ICON" "$APPRUN_SRC"; do
  if [ ! -f "$f" ]; then
    echo "missing packaging asset: $f" >&2
    exit 1
  fi
done

mkdir -p "$OUTPUT"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
appdir="$workdir/Terrascope.AppDir"
mkdir -p "$appdir/usr/bin"

cp "$BINARY" "$appdir/usr/bin/terrascope"
chmod 755 "$appdir/usr/bin/terrascope"
cp "$DESKTOP" "$appdir/terrascope.desktop"
cp "$DESKTOP" "$appdir/usr/share/applications/" 2>/dev/null || (mkdir -p "$appdir/usr/share/applications" && cp "$DESKTOP" "$appdir/usr/share/applications/")
cp "$ICON" "$appdir/terrascope.png"
mkdir -p "$appdir/usr/share/icons/hicolor/256x256/apps"
cp "$ICON" "$appdir/usr/share/icons/hicolor/256x256/apps/terrascope.png"
cp "$APPRUN_SRC" "$appdir/AppRun"
chmod 755 "$appdir/AppRun"

out="$OUTPUT/terrascope_${VERSION}_${PLATFORM}.AppImage"
rm -f "$out"
ARCH="$ARCH" "$APPIMAGETOOL" "$appdir" "$out"
chmod 755 "$out"
echo "built $out"
