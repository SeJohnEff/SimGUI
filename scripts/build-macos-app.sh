#!/usr/bin/env bash
# Build SimGUI.app for macOS using PyInstaller
# Usage: ./scripts/build-macos-app.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Building SimGUI.app for macOS..."
echo "Project root: $PROJECT_ROOT"

# Check dependencies
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 3.9+ is required. Install from https://www.python.org/downloads/"
    exit 1
fi

cd "$PROJECT_ROOT"

# Read version from canonical source
VERSION=$(python3 -c "import sys; sys.path.insert(0, '.'); from version import __version__; print(__version__)")
echo "Version: $VERSION"

# Use a local venv so PyInstaller is not installed into the system Python
VENV_DIR="$PROJECT_ROOT/.venv-build"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating build venv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Install PyInstaller into the build venv if not already present
if ! "$VENV_PYTHON" -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller into build venv..."
    "$VENV_PIP" install --quiet PyInstaller
fi

# Install project runtime dependencies into the build venv
"$VENV_PIP" install --quiet -r requirements.txt

# Run PyInstaller
echo "Running PyInstaller with SimGUI.spec..."
"$VENV_PYTHON" -m PyInstaller SimGUI.spec --clean

# Verify the output
if [ -d "dist/SimGUI.app" ]; then
    echo ""
    echo "✓ Build succeeded!"
    echo ""
    echo "Output: $PROJECT_ROOT/dist/SimGUI.app"
    echo ""
    echo "To run the app:"
    echo "  open dist/SimGUI.app"
    echo ""
    echo "To create a distributable DMG:"
    echo "  hdiutil create -volname \"SimGUI $VERSION\" -srcfolder dist/SimGUI.app -ov -format UDZO \"dist/SimGUI-v${VERSION}.dmg\""
    exit 0
else
    echo "✗ Build failed: dist/SimGUI.app not found"
    exit 1
fi
