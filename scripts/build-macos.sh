#!/usr/bin/env bash
# Set up SimGUI to run from source on macOS.
# Creates an isolated project venv, installs all Python deps, and sets up pySim.
# Usage: bash scripts/build-macos.sh
# After this completes: .venv/bin/python main.py

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

# --- Create or reuse the project venv ----------------------------------------
VENV="$PROJECT_ROOT/.venv"
if [ ! -d "$VENV" ]; then
    echo "Creating project virtual environment at .venv ..."
    python3 -m venv "$VENV"
    echo ""
fi

VENV_PYTHON="$VENV/bin/python"

echo "Upgrading pip in .venv ..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet

# --- Install SimGUI runtime dependencies into the venv -----------------------
echo "Installing SimGUI runtime dependencies into .venv ..."
if ! "$VENV_PYTHON" -m pip install PyQt6 Pillow pytlv --quiet; then
    echo ""
    echo "Error: Failed to install Python dependencies."
    echo "Check your internet connection and re-run: bash scripts/build-macos.sh"
    exit 1
fi

# pyscard: pre-built universal2 wheels are ABI-incompatible with some Python
# distributions (including Xcode CLT Python 3.9). Always build from source so
# the native _scard extension matches the running interpreter exactly.
# If already installed but broken (e.g. from a previous binary-wheel install),
# force a clean source rebuild.
echo "Installing pyscard ..."
if ! "$VENV_PYTHON" -m pip install pyscard --no-binary pyscard --quiet; then
    true  # fall through to validation; force-rebuild handles the failure below
fi
if ! "$VENV_PYTHON" -c "from smartcard.System import readers" 2>/dev/null; then
    echo "  Rebuilding pyscard from source ..."
    if ! "$VENV_PYTHON" -m pip install pyscard --no-binary pyscard --no-cache-dir --force-reinstall --quiet; then
        echo ""
        echo "Error: pyscard build failed."
        echo "Install Apple Command Line Tools or use python.org Python 3.12+."
        echo ""
        echo "  Apple CLT:   xcode-select --install"
        echo "  python.org:  https://python.org/downloads"
        echo ""
        echo "After installing, delete .venv and re-run: bash scripts/build-macos.sh"
        exit 1
    fi
fi

# --- Set up pySim (cloned to ~/pysim with its own venv) ----------------------
echo ""
echo "Setting up pySim (required for SIM card operations)..."
echo ""
VENV_PYTHON="$VENV_PYTHON" bash "$SCRIPT_DIR/install-macos.sh"

# --- Verify pySim is present -------------------------------------------------
echo ""
echo "Verifying pySim installation..."
if [ ! -d ~/pysim ]; then
    echo "Error: ~/pysim not found after install."
    echo "Re-run: bash scripts/build-macos.sh"
    exit 1
fi
if [ ! -f ~/pysim/pySim-read.py ]; then
    echo "Error: pySim-read.py not found in ~/pysim."
    echo "The pySim clone may be incomplete. Remove ~/pysim and re-run this script."
    exit 1
fi
echo "  pySim at ~/pysim OK"

# Validate pySim venv pyscard (install-macos.sh builds from source, but verify)
if ! ~/pysim/.venv/bin/python -c "from smartcard.System import readers" 2>/dev/null; then
    echo "Error: pySim venv pyscard is not functional."
    echo "Delete ~/pysim/.venv and re-run: bash scripts/build-macos.sh"
    exit 1
fi
echo "  pySim venv pyscard OK"

# Validate that pySim-read.py is fully importable via the pySim venv interpreter.
# This is the exact invocation SimGUI uses at runtime (_venv_python = ~/pysim/.venv/bin/python).
if ! ~/pysim/.venv/bin/python ~/pysim/pySim-read.py --help >/dev/null 2>&1; then
    echo "Error: ~/pysim/.venv/bin/python ~/pysim/pySim-read.py --help failed."
    echo "pySim imports may be broken. Delete ~/pysim/.venv and re-run:"
    echo "  bash scripts/build-macos.sh"
    exit 1
fi
echo "  pySim-read --help via venv OK"

# --- Validate imports inside the venv ----------------------------------------
echo ""
echo "Validating Python environment ..."

if ! "$VENV_PYTHON" -c "import PyQt6" 2>/dev/null; then
    echo "Error: PyQt6 not importable from .venv."
    exit 1
fi
echo "  PyQt6 OK"

if ! "$VENV_PYTHON" -c "from PIL import Image" 2>/dev/null; then
    echo "Error: Pillow (PIL) not importable from .venv."
    exit 1
fi
echo "  Pillow OK"

if ! "$VENV_PYTHON" -c "import pytlv" 2>/dev/null; then
    echo "Error: pytlv not importable from .venv."
    exit 1
fi
echo "  pytlv OK"

if ! "$VENV_PYTHON" -c "from smartcard.System import readers" 2>/dev/null; then
    echo ""
    echo "Error: pyscard is not functional in .venv."
    echo "Install Apple Command Line Tools or use python.org Python 3.12+."
    echo ""
    echo "  Apple CLT:   xcode-select --install"
    echo "  python.org:  https://python.org/downloads"
    echo ""
    echo "After installing, delete .venv and re-run: bash scripts/build-macos.sh"
    exit 1
fi
echo "  pyscard OK"

# Validate pySim auto-detection
cd "$PROJECT_ROOT"
PYSIM_FOUND=$("$VENV_PYTHON" - 2>/dev/null <<'PYEOF'
import sys, os
sys.path.insert(0, '.')
try:
    from managers.card_manager import _find_cli_tool
    result = _find_cli_tool()
    print('found' if result and result[0] else 'not_found')
except Exception:
    print('found' if os.path.isdir(os.path.expanduser('~/pysim')) else 'not_found')
PYEOF
)
if [ "$PYSIM_FOUND" != "found" ]; then
    echo "Error: pySim not found by auto-detection."
    echo "Re-run: bash scripts/build-macos.sh"
    exit 1
fi
echo "  pySim CLI found OK"

# Validate PCSC reconnect patch (applied by install-macos.sh above)
if grep -q "SimGUI patch: disconnect and reconnect" ~/pysim/pySim/transport/pcsc.py 2>/dev/null; then
    echo "  PCSC reconnect patch OK"
else
    echo "Error: PCSC reconnect patch not found in ~/pysim/pySim/transport/pcsc.py"
    echo "Re-run: bash scripts/build-macos.sh"
    exit 1
fi

echo ""
echo "Setup complete."
echo ""
echo "To launch SimGUI:"
echo "  .venv/bin/python main.py"
echo ""
