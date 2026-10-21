#!/usr/bin/env bash
# Build a Debian package from a PyInstaller onefile binary.
# Usage: build_deb.sh --version 0.3.0 --arch amd64|arm64 --binary dist/terrascope --output dist
set -euo pipefail

VERSION=""
ARCH=""
BINARY=""
OUTPUT="dist"

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$VERSION" ] || [ -z "$ARCH" ] || [ -z "$BINARY" ]; then
  echo "usage: $0 --version VERSION --arch amd64|arm64 --binary PATH [--output DIR]" >&2
  exit 1
fi

# PLATFORM is derived from the Debian arch so .deb/.tar.gz/.rpm/.AppImage
# share one naming scheme: terrascope_<version>_<platform>.<ext>
case "$ARCH" in
  amd64) PLATFORM="linux_x86_64" ;;
  arm64) PLATFORM="linux_arm64" ;;
  *) echo "unsupported deb arch: $ARCH (want amd64|arm64)" >&2; exit 1 ;;
esac

if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "dpkg-deb not found. On Debian/Ubuntu: sudo apt-get install dpkg-dev" >&2
  exit 1
fi

if [ ! -x "$BINARY" ] && [ ! -f "$BINARY" ]; then
  echo "binary not found: $BINARY" >&2
  exit 1
fi

mkdir -p "$OUTPUT"
package_root="$(mktemp -d)"
trap 'rm -rf "$package_root"' EXIT

install -D -m 755 "$BINARY" "$package_root/usr/bin/terrascope"
install -d "$package_root/DEBIAN"
cat > "$package_root/DEBIAN/control" <<EOF
Package: terrascope
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: Terrascope maintainers <a-shygun@users.noreply.github.com>
Depends: libc6, libncursesw6, libtinfo6
Description: Braille-rendered interactive world map for the terminal
 Terrascope shows live weather, aircraft, earthquakes, and day/night layers.
EOF

out="$OUTPUT/terrascope_${VERSION}_${PLATFORM}.deb"
dpkg-deb --root-owner-group --build "$package_root" "$out"
echo "built $out"
