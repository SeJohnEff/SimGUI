#!/usr/bin/env bash
# Install pySim for macOS — required for all SimGUI SIM card operations.
# Called automatically by scripts/build-macos.sh; also safe to run standalone.
#
# When called from build-macos.sh, VENV_PYTHON is set to the project venv Python.
# When run standalone, falls back to system python3.
#
# Requirements:
#   - python3 3.9+  (system python3 or https://python.org — no Homebrew needed)
#   - git           (from Xcode Command Line Tools: xcode-select --install)

set -e

PYTHON="${VENV_PYTHON:-python3}"

echo "SimGUI for macOS — pySim Setup"
echo "================================"
echo ""
echo "This script will install:"
echo "  • pySim (cloned to ~/pysim)"
echo "  • pySim Python dependencies (into ~/pysim/.venv)"
echo ""

# Check for git (ships with Xcode Command Line Tools, no Homebrew needed)
if ! command -v git &> /dev/null; then
    echo "Error: git is required."
    echo "Install Xcode Command Line Tools with: xcode-select --install"
    exit 1
fi

# Clone or update pySim
if [ -d ~/pysim ]; then
    echo "pySim already exists at ~/pysim — updating..."
    git -C ~/pysim pull origin master 2>/dev/null || git -C ~/pysim pull origin main 2>/dev/null || {
        echo "Warning: git pull failed (network issue?); using existing clone."
    }
else
    echo "Cloning pySim to ~/pysim..."
    git clone https://gitea.osmocom.org/sim-card/pysim.git ~/pysim
    echo "Cloned pySim successfully."
fi

# Create pySim venv if it does not already exist
if [ ! -d ~/pysim/.venv ]; then
    echo ""
    echo "Creating pySim virtual environment at ~/pysim/.venv ..."
    "$PYTHON" -m venv ~/pysim/.venv
fi

# Install pySim dependencies into its own isolated venv
echo ""
echo "Installing pySim Python dependencies into ~/pysim/.venv ..."
~/pysim/.venv/bin/python -m pip install --upgrade pip --quiet
if ! ~/pysim/.venv/bin/python -m pip install -r ~/pysim/requirements.txt --quiet; then
    echo ""
    echo "pySim dependency installation failed."
    echo "If pyscard failed to build, install Xcode Command Line Tools:"
    echo "  xcode-select --install"
    echo "Then re-run: bash scripts/build-macos.sh"
    exit 1
fi
echo "pySim dependencies installed."

# pyscard: pre-built universal2 wheels are ABI-incompatible with some Python
# distributions (including Xcode CLT Python 3.9). Always validate and rebuild
# from source so the native _scard extension matches the running interpreter.
echo "Validating pyscard in ~/pysim/.venv ..."
if ! ~/pysim/.venv/bin/python -c "from smartcard.System import readers" 2>/dev/null; then
    echo "  Rebuilding pyscard from source in ~/pysim/.venv ..."
    if ! ~/pysim/.venv/bin/python -m pip install pyscard --no-binary pyscard --no-cache-dir --force-reinstall --quiet; then
        echo ""
        echo "Error: pyscard build failed in ~/pysim/.venv."
        echo "Install Apple Command Line Tools or use python.org Python 3.12+."
        echo ""
        echo "  Apple CLT:   xcode-select --install"
        echo "  python.org:  https://python.org/downloads"
        echo ""
        echo "After installing, delete ~/pysim/.venv and re-run: bash scripts/build-macos.sh"
        exit 1
    fi
fi
echo "  pyscard OK"

# Apply GialerSim SPN patch
echo ""
echo "Checking for GialerSim SPN patch..."
GIALERSIM_PATCH_FILE="$HOME/pysim/pySim/legacy/cards.py"
if [ -f "$GIALERSIM_PATCH_FILE" ]; then
    if grep -q "'name'" "$GIALERSIM_PATCH_FILE"; then
        echo "GialerSim SPN patch already applied."
    else
        echo "Applying GialerSim SPN support patch..."
        "$PYTHON" - "$GIALERSIM_PATCH_FILE" <<'PYEOF'
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
echo "pySim installed at ~/pysim (dependencies in ~/pysim/.venv)"
echo ""
echo "  1. Plug in your USB card reader (OMNIKEY 3x21 or compatible)"
echo "  2. Launch SimGUI: .venv/bin/python main.py"
echo ""
echo "SimGUI auto-detects pySim at ~/pysim — no PYSIM_PATH export needed."
echo ""
