#!/usr/bin/env bash
# Build an RPM package from a PyInstaller onefile binary.
# Usage: build_rpm.sh --version 0.3.0 --arch x86_64|aarch64 --platform linux_x86_64 --binary dist/terrascope --output dist
set -euo pipefail

VERSION=""
ARCH=""
PLATFORM=""
BINARY=""
OUTPUT="dist"

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$VERSION" ] || [ -z "$ARCH" ] || [ -z "$BINARY" ]; then
  echo "usage: $0 --version VERSION --arch x86_64|aarch64 [--platform PLATFORM] --binary PATH [--output DIR]" >&2
  exit 1
fi

case "$ARCH" in
  x86_64|aarch64) ;;
  *) echo "unsupported rpm arch: $ARCH (want x86_64|aarch64)" >&2; exit 1 ;;
esac

if [ -z "$PLATFORM" ]; then
  case "$ARCH" in
    x86_64) PLATFORM="linux_x86_64" ;;
    aarch64) PLATFORM="linux_arm64" ;;
  esac
fi

if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "rpmbuild not found. On Debian/Ubuntu: sudo apt-get install rpm; on Fedora: sudo dnf install rpm-build; on Arch: sudo pacman -S base-devel" >&2
  exit 1
fi

if [ ! -f "$BINARY" ]; then
  echo "binary not found: $BINARY" >&2
  exit 1
fi

mkdir -p "$OUTPUT"
topdir="$(mktemp -d)"
trap 'rm -rf "$topdir"' EXIT
mkdir -p "$topdir"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
mkdir -p "$topdir/SOURCES/terrascope-$VERSION/usr/bin"
cp "$BINARY" "$topdir/SOURCES/terrascope-$VERSION/usr/bin/terrascope"
chmod 755 "$topdir/SOURCES/terrascope-$VERSION/usr/bin/terrascope"

# Optional desktop/icon assets shipped when present in the checkout.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -f "$REPO_ROOT/packaging/linux/terrascope.desktop" ]; then
  mkdir -p "$topdir/SOURCES/terrascope-$VERSION/usr/share/applications"
  cp "$REPO_ROOT/packaging/linux/terrascope.desktop" "$topdir/SOURCES/terrascope-$VERSION/usr/share/applications/"
fi
if [ -f "$REPO_ROOT/packaging/linux/terrascope.png" ]; then
  mkdir -p "$topdir/SOURCES/terrascope-$VERSION/usr/share/pixmaps"
  cp "$REPO_ROOT/packaging/linux/terrascope.png" "$topdir/SOURCES/terrascope-$VERSION/usr/share/pixmaps/terrascope.png"
fi

cat > "$topdir/SPECS/terrascope.spec" <<EOF
Name:           terrascope
Version:        ${VERSION}
Release:        1%{?dist}
Summary:        Braille-rendered interactive world map for the terminal
License:        MIT
URL:            https://github.com/a-shygun/terrascope
BuildArch:      ${ARCH}
Requires:       glibc, ncurses-libs

%description
Terrascope shows live weather, aircraft, earthquakes, and day/night layers
in a Braille terminal map.

%install
mkdir -p %{buildroot}/usr/bin
install -m 755 $topdir/SOURCES/terrascope-$VERSION/usr/bin/terrascope %{buildroot}/usr/bin/terrascope
if [ -f "$topdir/SOURCES/terrascope-$VERSION/usr/share/applications/terrascope.desktop" ]; then
  mkdir -p %{buildroot}/usr/share/applications
  install -m 644 $topdir/SOURCES/terrascope-$VERSION/usr/share/applications/terrascope.desktop %{buildroot}/usr/share/applications/terrascope.desktop
fi
if [ -f "$topdir/SOURCES/terrascope-$VERSION/usr/share/pixmaps/terrascope.png" ]; then
  mkdir -p %{buildroot}/usr/share/pixmaps
  install -m 644 $topdir/SOURCES/terrascope-$VERSION/usr/share/pixmaps/terrascope.png %{buildroot}/usr/share/pixmaps/terrascope.png
fi

%files
/usr/bin/terrascope
%defattr(-,root,root,-)
/usr/share/applications/terrascope.desktop
/usr/share/pixmaps/terrascope.png

%changelog
* Thu Oct 22 2026 Terrascope maintainers <a-shygun@users.noreply.github.com> - ${VERSION}-1
- Release ${VERSION}
EOF

rpmbuild --define "_topdir $topdir" -bb "$topdir/SPECS/terrascope.spec"
built_rpm="$(find "$topdir/RPMS" -name '*.rpm' | head -n 1)"
if [ -z "${built_rpm:-}" ]; then
  echo "rpmbuild produced no .rpm" >&2
  exit 1
fi

out="$OUTPUT/terrascope_${VERSION}_${PLATFORM}.rpm"
cp "$built_rpm" "$out"
echo "built $out"
rpm -qpi "$out" || true
