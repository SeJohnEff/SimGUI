#!/usr/bin/env bash
# Build SimGUI.app for macOS using PyInstaller
# Usage: ./scripts/build-macos-app.sh

set -euo pipefail

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

# Cleanup function — remove staging dirs created by this script
cleanup() {
    rm -rf "$PROJECT_ROOT/pysim-bundle" "$PROJECT_ROOT/pysim-site-packages"
}
trap cleanup EXIT

# Read version from canonical source
VERSION=$(python3 -c "import sys; sys.path.insert(0, '.'); from version import __version__; print(__version__)")
echo "Version: $VERSION"

# --- pySim source location ---
# PYSIM_PATH env var overrides; default to ~/pysim.
# NOTE: this is only used during BUILD to stage files into the bundle.
# The packaged app uses the bundled copy and never looks at ~/pysim at runtime.
PYSIM_SRC="${PYSIM_PATH:-$HOME/pysim}"
if [ ! -d "$PYSIM_SRC" ]; then
    echo "Error: pySim not found at $PYSIM_SRC"
    echo "  Install pySim there or set PYSIM_PATH=/path/to/pysim"
    exit 1
fi

# Verify the three scripts and the package directory are present
for f in pySim-read.py pySim-prog.py pySim-shell.py; do
    if [ ! -f "$PYSIM_SRC/$f" ]; then
        echo "Error: $PYSIM_SRC/$f not found — is this a complete pySim checkout?"
        exit 1
    fi
done
if [ ! -f "$PYSIM_SRC/pySim/__init__.py" ]; then
    echo "Error: $PYSIM_SRC/pySim/__init__.py not found — pySim package missing"
    exit 1
fi
echo "pySim source: $PYSIM_SRC"

# --- Build venv (PyInstaller + SimGUI runtime deps) ---
VENV_DIR="$PROJECT_ROOT/.venv-build"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating build venv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if ! "$VENV_PYTHON" -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller into build venv..."
    "$VENV_PIP" install --quiet PyInstaller
fi

# pyscard's PyPI wheel has a broken arm64 slice — force source build.
"$VENV_PIP" install --quiet --no-binary pyscard -r requirements.txt

# --- pySim runtime venv (separate from build venv) ---
PYSIM_VENV_DIR="$PROJECT_ROOT/.venv-pysim"
if [ ! -d "$PYSIM_VENV_DIR" ]; then
    echo "Creating pySim runtime venv at $PYSIM_VENV_DIR ..."
    python3 -m venv "$PYSIM_VENV_DIR"
fi

PYSIM_VENV_PYTHON="$PYSIM_VENV_DIR/bin/python"
PYSIM_VENV_PIP="$PYSIM_VENV_DIR/bin/pip"

echo "Installing pySim runtime dependencies into pySim venv..."
"$PYSIM_VENV_PIP" install --quiet --upgrade pip
# pyscard: force source build for same arm64 slice reason
"$PYSIM_VENV_PIP" install --quiet --no-binary pyscard \
    -r "$SCRIPT_DIR/requirements-pysim-bundle.txt"

# Resolve site-packages path without relying on GNU readlink -f
PYSIM_SITEPACKAGES=$("$PYSIM_VENV_PYTHON" -c \
    "import site; print(site.getsitepackages()[0])")
echo "pySim site-packages: $PYSIM_SITEPACKAGES"

if [ ! -d "$PYSIM_SITEPACKAGES" ]; then
    echo "Error: pySim site-packages directory not found at $PYSIM_SITEPACKAGES"
    exit 1
fi

# --- Stage pySim bundle ---
echo "Staging pySim scripts and package..."
rm -rf "$PROJECT_ROOT/pysim-bundle"
mkdir -p "$PROJECT_ROOT/pysim-bundle"

# Copy the three entry-point scripts
cp "$PYSIM_SRC/pySim-read.py"  "$PROJECT_ROOT/pysim-bundle/"
cp "$PYSIM_SRC/pySim-prog.py"  "$PROJECT_ROOT/pysim-bundle/"
cp "$PYSIM_SRC/pySim-shell.py" "$PROJECT_ROOT/pysim-bundle/"

# Copy the pySim package directory
cp -R "$PYSIM_SRC/pySim" "$PROJECT_ROOT/pysim-bundle/pySim"

echo "Staged: pysim-bundle/ ($(find "$PROJECT_ROOT/pysim-bundle" -name '*.py' | wc -l | tr -d ' ') .py files)"

# --- Stage pySim site-packages ---
echo "Staging pySim site-packages..."
rm -rf "$PROJECT_ROOT/pysim-site-packages"
COPYFILE_DISABLE=1 cp -R "$PYSIM_SITEPACKAGES" "$PROJECT_ROOT/pysim-site-packages"
echo "Staged: pysim-site-packages/ ($(du -sh "$PROJECT_ROOT/pysim-site-packages" | cut -f1))"

# --- Write GITHASH ---
git rev-parse --short HEAD > "$PROJECT_ROOT/GITHASH" 2>/dev/null \
    || echo "unknown" > "$PROJECT_ROOT/GITHASH"
echo "GITHASH: $(cat "$PROJECT_ROOT/GITHASH")"

# --- Run PyInstaller ---
echo "Running PyInstaller with SimGUI.spec..."
"$VENV_PYTHON" -m PyInstaller SimGUI.spec --clean -y

# Verify the .app bundle was created
if [ ! -d "dist/SimGUI.app" ]; then
    echo "✗ Build failed: dist/SimGUI.app not found"
    exit 1
fi

# --- Verify GITHASH bundled ---
GITHASH_FOUND=""
while IFS= read -r f; do
    if [ -z "$GITHASH_FOUND" ]; then
        echo "✓ GITHASH bundled at:"
    fi
    GITHASH_FOUND="yes"
    echo "    $f  →  $(cat "$f")"
done < <(find dist/SimGUI.app/Contents -name "GITHASH" 2>/dev/null)

if [ -z "$GITHASH_FOUND" ]; then
    echo "✗ GITHASH not found inside dist/SimGUI.app/Contents — aborting"
    exit 1
fi

# Remove GITHASH from the source tree — it's a build artifact
rm -f "$PROJECT_ROOT/GITHASH"

# --- Verify bundled pySim ---
# PyInstaller BUNDLE+COLLECT layout: data files land in Contents/Resources/
BUNDLE_RESOURCES="dist/SimGUI.app/Contents/Resources"
PYSIM_ERRORS=0

for script in pySim-read.py pySim-prog.py pySim-shell.py; do
    path=$(find "$BUNDLE_RESOURCES" -name "$script" 2>/dev/null | head -1)
    if [ -n "$path" ]; then
        echo "✓ Bundled: $path"
    else
        echo "✗ Missing: $script inside dist/SimGUI.app/Contents/Resources"
        PYSIM_ERRORS=$((PYSIM_ERRORS + 1))
    fi
done

INIT_PATH=$(find "$BUNDLE_RESOURCES" -path "*/pySim/__init__.py" 2>/dev/null | head -1)
if [ -n "$INIT_PATH" ]; then
    echo "✓ Bundled: $INIT_PATH"
else
    echo "✗ Missing: pySim/__init__.py inside dist/SimGUI.app/Contents/Resources"
    PYSIM_ERRORS=$((PYSIM_ERRORS + 1))
fi

SP_PATH=$(find "$BUNDLE_RESOURCES" -maxdepth 2 -name "pysim-site-packages" -type d 2>/dev/null | head -1)
if [ -n "$SP_PATH" ]; then
    echo "✓ Bundled: $SP_PATH"
else
    echo "✗ Missing: pysim-site-packages/ inside dist/SimGUI.app/Contents/Resources"
    PYSIM_ERRORS=$((PYSIM_ERRORS + 1))
fi

if [ "$PYSIM_ERRORS" -gt 0 ]; then
    echo ""
    echo "✗ $PYSIM_ERRORS bundled pySim file(s) missing — build incomplete"
    exit 1
fi

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
