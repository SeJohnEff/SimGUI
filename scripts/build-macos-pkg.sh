#!/usr/bin/env bash
# Build a macOS installer .pkg for SimGUI.app
# Usage: ./scripts/build-macos-pkg.sh [--no-rebuild]
#
#   (default)     Rebuild SimGUI.app from current source, then package it.
#   --no-rebuild  Skip the PyInstaller rebuild and package the existing
#                 dist/SimGUI.app — only for when you JUST built it yourself.
#                 A GITHASH-vs-HEAD guard still refuses to package a stale app.
#
# Produces: dist/SimGUI-v<VERSION>.pkg
# Installs: /Applications/SimGUI.app
# Unsigned — suitable for local/test distribution only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# --- Parse args ---
REBUILD=1
for arg in "$@"; do
    case "$arg" in
        --no-rebuild) REBUILD=0 ;;
        -h|--help) awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; exit 0 ;;
        *) echo "Error: unknown argument '$arg' (see --help)." >&2; exit 1 ;;
    esac
done

# --- Version ---
if [ ! -f version.py ]; then
    echo "Error: version.py not found in $PROJECT_ROOT" >&2
    exit 1
fi
VERSION=$(python3 -c "import sys; sys.path.insert(0, '.'); from version import __version__; print(__version__)")
echo "SimGUI version: $VERSION"

# --- Build the app fresh (unless explicitly skipped) ---
# The .pkg must NEVER wrap a stale bundle. pkgbuild only reads whatever is on
# disk, so by default we rebuild SimGUI.app from the current source first. This
# is the whole point: reusing an old dist/SimGUI.app silently ships old code.
APP_SRC="$PROJECT_ROOT/dist/SimGUI.app"
if [ "$REBUILD" -eq 1 ]; then
    echo "Rebuilding SimGUI.app from current source (use --no-rebuild to skip)..."
    bash "$SCRIPT_DIR/build-macos-app.sh"
elif [ ! -d "$APP_SRC" ]; then
    echo "dist/SimGUI.app not found — building it (--no-rebuild ignored)..."
    bash "$SCRIPT_DIR/build-macos-app.sh"
fi
if [ ! -d "$APP_SRC" ]; then
    echo "Error: dist/SimGUI.app missing after build attempt." >&2
    exit 1
fi
echo "App source: $APP_SRC"

# --- Guard: the bundle must match the current commit ---
# build-macos-app.sh writes the short git hash to Contents/Resources/GITHASH.
# If it doesn't match HEAD (e.g. --no-rebuild over an old bundle), the app is
# stale — refuse to package it rather than ship out-of-date code.
HEAD_HASH="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUNDLE_HASH_FILE="$APP_SRC/Contents/Resources/GITHASH"
if [ -f "$BUNDLE_HASH_FILE" ]; then
    BUNDLE_HASH="$(tr -d '[:space:]' < "$BUNDLE_HASH_FILE")"
    if [ "$HEAD_HASH" != "unknown" ] && [ "$BUNDLE_HASH" != "$HEAD_HASH" ]; then
        echo "✗ Stale bundle: SimGUI.app GITHASH ($BUNDLE_HASH) != HEAD ($HEAD_HASH)." >&2
        echo "  Rebuild the app (run without --no-rebuild) before packaging." >&2
        exit 1
    fi
    echo "✓ Bundle GITHASH matches HEAD: $BUNDLE_HASH"
else
    echo "Warning: no GITHASH in bundle — cannot verify it matches HEAD." >&2
fi

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
