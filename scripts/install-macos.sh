#!/usr/bin/env bash
# Install pySim for macOS — required for all SimGUI SIM card operations.
# Called automatically by scripts/build-macos.sh; also safe to run standalone.

set -e

echo "SimGUI for macOS — pySim Setup"
echo "================================"
echo ""
echo "This script will install:"
echo "  • pySim (cloned to ~/pysim)"
echo "  • pySim Python dependencies"
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
pip install --upgrade pip setuptools wheel --quiet
pip install -r ~/pysim/requirements.txt --quiet

# Apply GialerSim SPN patch
echo ""
echo "Checking for GialerSim SPN patch..."
GIALERSIM_PATCH_FILE="$HOME/pysim/pySim/legacy/cards.py"
if [ -f "$GIALERSIM_PATCH_FILE" ]; then
    if grep -q "'name'" "$GIALERSIM_PATCH_FILE"; then
        echo "GialerSim SPN patch already applied."
    else
        echo "Applying GialerSim SPN support patch..."
        python3 - "$GIALERSIM_PATCH_FILE" <<'PYEOF'
import sys
path = sys.argv[1]
try:
    text = open(path).read()
    old = "'opc': lambda opc: self.update_uicc_auth_key(ki=None, opc=opc),"
    new = (old + "\n            'name': lambda name: self.update_spn("
           "name=name, show_in_hplmn=True, hide_in_oplmn=False),")
    if old in text and "'name'" not in text:
        open(path, 'w').write(text.replace(old, new))
        print("Patch applied.")
    else:
        print("Patch skipped (already applied or pattern not found).")
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
        if grep -q "'name'" "$GIALERSIM_PATCH_FILE"; then
            echo "GialerSim SPN patch applied successfully."
        else
            echo "Warning: GialerSim SPN patch could not be applied — SPN writes to blank cards will be silently skipped."
        fi
    fi
else
    echo "Patch target not found at $GIALERSIM_PATCH_FILE — skipping (pySim may use a different layout)."
fi

deactivate 2>/dev/null || true

echo ""
echo "pySim installed at ~/pysim"
echo ""
echo "To complete setup:"
echo "  1. Plug in your USB card reader (OMNIKEY 3x21 or compatible)"
echo ""
echo "  2. Launch SimGUI:"
echo "     python3 main.py"
echo ""
echo "SimGUI auto-detects pySim at ~/pysim — no PYSIM_PATH export needed."
echo ""
echo "Advanced: to use a non-standard pySim location, set:"
echo "  export PYSIM_PATH=/path/to/your/pysim"
echo ""
