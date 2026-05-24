#!/usr/bin/env bash
# Set up SimGUI to run from source on macOS.
# Installs Python dependencies and pySim (required for SIM card operations).
# Usage: bash scripts/build-macos.sh
# After this completes: python3 main.py   (pySim is auto-detected at ~/pysim)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "SimGUI — macOS Setup"
echo "====================="
echo ""

if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This script is for macOS only."
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 is required."
    echo "Install Python 3.9+ from https://python.org"
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

echo "Upgrading pip..."
python3 -m pip install --upgrade pip --quiet

echo "Installing SimGUI runtime dependencies..."
python3 -m pip install --user PyQt6 Pillow pyscard pytlv

echo ""
echo "Installing pySim (required for SIM card operations)..."
echo ""
bash "$SCRIPT_DIR/install-macos.sh"

echo ""
echo "Verifying pySim installation..."
if [ ! -d ~/pysim ]; then
    echo "Error: ~/pysim not found after install."
    echo "Re-run: bash scripts/install-macos.sh"
    exit 1
fi
if [ ! -f ~/pysim/pySim-read.py ]; then
    echo "Error: pySim-read.py not found in ~/pysim."
    echo "The pySim clone may be incomplete. Remove ~/pysim and re-run this script."
    exit 1
fi
echo "pySim verified at ~/pysim (auto-detected on startup — no PYSIM_PATH needed)"
echo ""
echo "Setup complete. To launch SimGUI: python3 main.py"
