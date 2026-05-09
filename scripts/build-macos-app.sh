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
    echo "Error: python3 is required. Install Python 3.10+ from python.org or Homebrew."
    exit 1
fi

cd "$PROJECT_ROOT"

# Install build dependencies if not already present
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller..."
    pip3 install PyInstaller
fi

# Run PyInstaller
echo "Running PyInstaller with SimGUI.spec..."
python3 -m PyInstaller SimGUI.spec --clean

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
    echo "To distribute:"
    echo "  hdiutil create -volname SimGUI -srcfolder dist/SimGUI.app -ov -format UDZO dist/SimGUI.dmg"
    exit 0
else
    echo "✗ Build failed: dist/SimGUI.app not found"
    exit 1
fi
