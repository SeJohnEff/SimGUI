#!/usr/bin/env bash
# Build a macOS installer .pkg for SimGUI.app
# Usage: ./scripts/build-macos-pkg.sh
#
# Produces: dist/SimGUI-v<VERSION>.pkg
# Installs: /Applications/SimGUI.app
# Unsigned — suitable for local/test distribution only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# --- Version ---
if [ ! -f version.py ]; then
    echo "Error: version.py not found in $PROJECT_ROOT" >&2
    exit 1
fi
VERSION=$(python3 -c "import sys; sys.path.insert(0, '.'); from version import __version__; print(__version__)")
echo "SimGUI version: $VERSION"

# --- Ensure SimGUI.app exists ---
APP_SRC="$PROJECT_ROOT/dist/SimGUI.app"
if [ ! -d "$APP_SRC" ]; then
    echo "dist/SimGUI.app not found — running build-macos-app.sh first..."
    bash "$SCRIPT_DIR/build-macos-app.sh"
fi
if [ ! -d "$APP_SRC" ]; then
    echo "Error: dist/SimGUI.app still missing after build attempt." >&2
    exit 1
fi
echo "App source: $APP_SRC"

# --- Check required tools ---
if ! command -v pkgbuild &>/dev/null; then
    echo "Error: pkgbuild not found. Install Xcode Command Line Tools." >&2
    exit 1
fi

# --- Temp package root ---
PKG_ROOT=$(mktemp -d)
trap 'rm -rf "$PKG_ROOT"' EXIT

INSTALL_DIR="$PKG_ROOT/Applications"
mkdir -p "$INSTALL_DIR"
cp -R "$APP_SRC" "$INSTALL_DIR/SimGUI.app"
echo "Staged: $INSTALL_DIR/SimGUI.app"

# --- Build .pkg ---
mkdir -p "$PROJECT_ROOT/dist"
PKG_OUT="$PROJECT_ROOT/dist/SimGUI-v${VERSION}.pkg"

echo "Building $PKG_OUT ..."
pkgbuild \
    --root        "$PKG_ROOT" \
    --identifier  "com.virtugrp.simgui" \
    --version     "$VERSION" \
    --install-location "/" \
    "$PKG_OUT"

if [ ! -f "$PKG_OUT" ]; then
    echo "Error: pkgbuild did not produce $PKG_OUT" >&2
    exit 1
fi

echo ""
echo "✓ Package built (unsigned)!"
echo ""
echo "  Output:   $PKG_OUT"
echo "  Installs: /Applications/SimGUI.app"
echo "  Version:  $VERSION"
echo "  ID:       com.virtugrp.simgui"
echo ""
echo "To install on this or another Mac:"
echo "  sudo installer -pkg \"$PKG_OUT\" -target /"
echo "  # or: double-click the .pkg in Finder"
