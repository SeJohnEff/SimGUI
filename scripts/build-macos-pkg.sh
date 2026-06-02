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
# Layout: $PKG_ROOT/SimGUI.app + --install-location /Applications
# is unambiguous. Avoid nesting under Applications/ inside the root,
# which causes pkgbuild's component inference to produce a double-path.
PKG_ROOT=$(mktemp -d)
trap 'rm -rf "$PKG_ROOT"' EXIT

# COPYFILE_DISABLE=1 suppresses AppleDouble (._*) metadata files.
COPYFILE_DISABLE=1 cp -R "$APP_SRC" "$PKG_ROOT/SimGUI.app"
echo "Staged: $PKG_ROOT/SimGUI.app"

# --- Build .pkg ---
mkdir -p "$PROJECT_ROOT/dist"
PKG_OUT="$PROJECT_ROOT/dist/SimGUI-v${VERSION}.pkg"

echo "Building $PKG_OUT ..."
COPYFILE_DISABLE=1 pkgbuild \
    --root             "$PKG_ROOT" \
    --install-location "/Applications" \
    --identifier       "com.virtugrp.simgui" \
    --version          "$VERSION" \
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
echo "  sudo xattr -dr com.apple.quarantine /Applications/SimGUI.app 2>/dev/null || true"
echo "  # or: double-click the .pkg in Finder (then run the xattr line above)"
