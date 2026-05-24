#!/usr/bin/env bash
# Install pySim for macOS — required for all SimGUI SIM card operations.
# Called automatically by scripts/build-macos.sh; also safe to run standalone.
#
# Requirements:
#   - python3 3.9+  (system python3 or https://python.org — no Homebrew needed)
#   - git           (from Xcode Command Line Tools: xcode-select --install)

set -e

echo "SimGUI for macOS — pySim Setup"
echo "================================"
echo ""
echo "This script will install:"
echo "  • pySim (cloned to ~/pysim)"
echo "  • pySim Python dependencies"
echo ""

# Check for git (ships with Xcode Command Line Tools, no Homebrew needed)
if ! command -v git &> /dev/null; then
    echo "Error: git is required."
    echo "Install Xcode Command Line Tools with: xcode-select --install"
    exit 1
fi

# Install pySim to ~/pysim
if [ -d ~/pysim ]; then
    echo "pySim already exists at ~/pysim — updating..."
    cd ~/pysim
    git pull origin master 2>/dev/null || git pull origin main 2>/dev/null || {
        echo "Warning: git pull failed (network issue?); using existing clone."
    }
else
    echo "Cloning pySim to ~/pysim..."
    git clone https://gitea.osmocom.org/sim-card/pysim.git ~/pysim
    echo "Cloned pySim successfully."
fi

# Install pySim dependencies.
# Uses pip --user so no venv or Homebrew is required.
echo ""
echo "Installing pySim Python dependencies..."
python3 -m pip install --user -r ~/pysim/requirements.txt --quiet
echo "pySim dependencies installed."

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

echo ""
echo "pySim installed at ~/pysim"
echo ""
echo "  1. Plug in your USB card reader (OMNIKEY 3x21 or compatible)"
echo "  2. Launch SimGUI: python3 main.py"
echo ""
echo "SimGUI auto-detects pySim at ~/pysim — no PYSIM_PATH export needed."
echo ""
