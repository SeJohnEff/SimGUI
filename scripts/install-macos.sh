#!/usr/bin/env bash
# Install SimGUI and pySim for macOS with full hardware support
# This script is for developers and users who want to program real SIM cards.
# Casual users should just download SimGUI.app and run it (simulator mode works out of the box).

set -e

echo "SimGUI for macOS — Developer Installation"
echo "==========================================="
echo ""
echo "This script will install:"
echo "  • pySim (cloned to ~/pysim)"
echo "  • Python dependencies (pyscard, etc.)"
echo ""

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo "Error: Homebrew is required. Install from https://brew.sh"
    exit 1
fi

# Check for git
if ! command -v git &> /dev/null; then
    echo "Error: git is required. Install with: brew install git"
    exit 1
fi

# Check for Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo "Installing Python 3.12 via Homebrew..."
    brew install python@3.12
    brew link python@3.12
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo "Using Python: $PYTHON_VERSION"
echo ""

# Install pySim to ~/pysim
if [ -d ~/pysim ]; then
    echo "pySim already exists at ~/pysim"
    read -p "Update it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cd ~/pysim
        git pull origin master
    fi
else
    echo "Cloning pySim to ~/pysim..."
    git clone https://gitea.osmocom.org/sim-card/pysim.git ~/pysim
    cd ~/pysim
    echo "Cloned pySim successfully"
fi

# Create and activate venv
if [ ! -d ~/pysim/.venv ]; then
    echo "Creating Python venv in ~/pysim/.venv..."
    python3 -m venv ~/pysim/.venv
fi

source ~/pysim/.venv/bin/activate
echo "Virtual environment activated"

# Install pySim dependencies
echo "Installing pySim dependencies..."
pip install --upgrade pip setuptools wheel
pip install -r ~/pysim/requirements.txt

# Apply GialerSIM SPN patch (optional, non-fatal)
echo ""
echo "Checking for GialerSIM SPN patch..."
GIALERSIM_PATCH_FILE="/opt/pysim/pySim/legacy/cards.py"
if [ -f "$GIALERSIM_PATCH_FILE" ]; then
    if ! grep -q "'name':" "$GIALERSIM_PATCH_FILE"; then
        echo "Applying GialerSIM SPN support patch..."
        # This would require editing the file; skipping for now as pySim may be updated
        echo "(Note: GialerSIM SPN support may require a manual pySim patch)"
    fi
fi

# Install SimGUI dependencies
echo ""
echo "Installing SimGUI dependencies (system)..."
pip3 install --user pyscard PyQt6

# Set environment variable for pySim discovery
echo ""
echo "Done! To use SimGUI with real SIM cards:"
echo ""
echo "  1. Plug in your USB card reader (OMNIKEY 3x21 or compatible)"
echo "  2. Set the PYSIM_PATH environment variable:"
echo "     export PYSIM_PATH=~/pysim"
echo ""
echo "  3. Run SimGUI:"
echo "     cd /path/to/SimGUI && python3 main.py"
echo ""
echo "Or, download SimGUI.app and set the env var before launching it."
