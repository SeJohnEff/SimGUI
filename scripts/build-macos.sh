#!/usr/bin/env bash
# Set up SimGUI to run from source on macOS.
# Usage: bash scripts/build-macos.sh
# After this completes, launch SimGUI with: python3 main.py

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "SimGUI — macOS Source Setup"
echo "============================"
echo ""

if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This script is for macOS only."
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 is required."
    echo "Install from https://python.org or: brew install python@3.12"
    exit 1
fi

PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]; }; then
    echo "Error: Python 3.9 or later is required (found $(python3 --version))."
    exit 1
fi

echo "Python $(python3 --version | cut -d' ' -f2) OK"
echo ""

echo "Installing SimGUI runtime dependencies..."
pip3 install --user PyQt6 Pillow pyscard pytlv

echo ""
echo "Setup complete."
echo ""
echo "To launch SimGUI:"
echo "  cd $PROJECT_ROOT && python3 main.py"
echo ""
echo "To enable hardware card support, also install pySim:"
echo "  bash $SCRIPT_DIR/install-macos.sh"
echo ""
