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

# --- Dirty-worktree guard ---
# Any locally-modified tracked .py file will be frozen into the bundle by
# PyInstaller, silently overriding what git pull just fetched.
# This catches the case before wasting a full build cycle.
DIRTY_PY=$(git status --short | grep -E '^.M.*\.py$' || true)
if [ -n "$DIRTY_PY" ]; then
    echo ""
    echo "✗ Dirty worktree: the following .py file(s) have local modifications."
    echo "  PyInstaller will freeze the MODIFIED version, not the repo version."
    echo ""
    echo "$DIRTY_PY"
    echo ""
    echo "  To discard local edits and build from clean HEAD:"
    echo "    git checkout -- <file>    # specific file"
    echo "    git checkout -- .         # all tracked files"
    echo ""
    exit 1
fi

# Cleanup function — remove staging dirs created by this script
cleanup() {
    rm -rf "$PROJECT_ROOT/pysim-bundle" "$PROJECT_ROOT/pysim-site-packages" 2>/dev/null || true
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
# Remove dist/ and all __pycache__ dirs before building.
# - dist/: PyInstaller --clean only wipes build/, not dist/. Stale .pyc files
#   from a previous build can survive an in-place overwrite.
# - __pycache__: git pull restores .py files but their mtime may be older than
#   existing .pyc bytecache. PyInstaller picks the .pyc, bundling stale code.
#   Removing __pycache__ forces recompilation from the current .py sources.
echo "Removing stale dist/ and __pycache__ before build..."
rm -rf "$PROJECT_ROOT/dist" 2>/dev/null || true
find "$PROJECT_ROOT" -name '__pycache__' -not -path '*/.venv*' -type d -exec rm -rf {} + 2>/dev/null || true
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

# --- Bundle Python executable ---
# Provide a real Python interpreter inside the .app so pySim scripts can be
# launched as subprocesses by card_manager at runtime.
#
# The CommandLineTools python3.9 binary is a launcher that posix_spawns
#   Resources/Python.app/Contents/MacOS/Python
# which is the actual interpreter stub. Both are required, along with the
# Python3 framework dylib. Layout mirrors the system framework structure.
BUNDLED_FWK_DIR="dist/SimGUI.app/Contents/Frameworks/Python3.framework/Versions/3.9"
BUNDLED_PYTHON_DIR="$BUNDLED_FWK_DIR/bin"
BUNDLED_PYTHON="$BUNDLED_PYTHON_DIR/python3.9"
BUNDLED_STUB_DIR="$BUNDLED_FWK_DIR/Resources/Python.app/Contents/MacOS"
mkdir -p "$BUNDLED_PYTHON_DIR" "$BUNDLED_STUB_DIR"

# Resolve the real Python binary behind the venv symlink.
# Uses Python's own os.path.realpath — no readlink, bash 3.2 safe.
REAL_PYTHON=$("$PYSIM_VENV_PYTHON" -c "import os, sys; print(os.path.realpath(sys.executable))")
if [ ! -f "$REAL_PYTHON" ]; then
    echo "✗ Could not locate real Python executable (resolved to: $REAL_PYTHON) — aborting"
    exit 1
fi

REAL_FWK_DIR=$(dirname "$(dirname "$REAL_PYTHON")")   # .../Versions/3.9

# Framework dylib: python3.9 launcher links @executable_path/../Python3
REAL_PYTHON_DYLIB="$REAL_FWK_DIR/Python3"
if [ ! -f "$REAL_PYTHON_DYLIB" ]; then
    echo "✗ Python3 framework dylib not found at $REAL_PYTHON_DYLIB — aborting"
    exit 1
fi

# Actual interpreter stub: python3.9 posix_spawns this binary
REAL_PYTHON_STUB="$REAL_FWK_DIR/Resources/Python.app/Contents/MacOS/Python"
if [ ! -f "$REAL_PYTHON_STUB" ]; then
    echo "✗ Python interpreter stub not found at $REAL_PYTHON_STUB — aborting"
    exit 1
fi

echo "Bundling Python launcher from: $REAL_PYTHON"
echo "Bundling Python3 dylib from:   $REAL_PYTHON_DYLIB"
echo "Bundling Python stub from:     $REAL_PYTHON_STUB"

cp "$REAL_PYTHON"       "$BUNDLED_PYTHON"
chmod +x "$BUNDLED_PYTHON"
cp "$REAL_PYTHON_DYLIB" "$BUNDLED_FWK_DIR/Python3"
cp "$REAL_PYTHON_STUB"  "$BUNDLED_STUB_DIR/Python"
chmod +x "$BUNDLED_STUB_DIR/Python"

# Bundle the Python stdlib so the app is self-contained and PYTHONHOME works.
REAL_STDLIB="$REAL_FWK_DIR/lib/python3.9"
if [ ! -d "$REAL_STDLIB" ]; then
    echo "✗ Python stdlib not found at $REAL_STDLIB — aborting"
    exit 1
fi
echo "Bundling Python stdlib from: $REAL_STDLIB ($(du -sh "$REAL_STDLIB" | cut -f1))"
mkdir -p "$BUNDLED_FWK_DIR/lib"
COPYFILE_DISABLE=1 cp -R "$REAL_STDLIB" "$BUNDLED_FWK_DIR/lib/python3.9"

# Re-sign the bundle ad-hoc after adding all files (required on Apple Silicon).
codesign --force --deep --sign - "dist/SimGUI.app" 2>/dev/null || true

# Check 1: must be a Mach-O executable, not a dylib/shared library
FILE_OUTPUT=$(file "$BUNDLED_PYTHON")
echo "  file: $FILE_OUTPUT"
if echo "$FILE_OUTPUT" | grep -q "Mach-O.*executable"; then
    echo "✓ Bundled Python is a Mach-O executable"
else
    echo "✗ Bundled Python is not a Mach-O executable — aborting"
    exit 1
fi

# Check 2: --version must succeed
PY_VERSION_OUTPUT=$("$BUNDLED_PYTHON" --version 2>&1) || {
    echo "✗ Bundled Python --version failed — aborting"
    exit 1
}
echo "✓ Bundled Python version: $PY_VERSION_OUTPUT"

# Check 3: pySim-read.py -h smoke test with bundled stdlib and pySim on PYTHONPATH.
# PYTHONHOME points at the bundled framework so the stdlib is found without the
# system CLT Python being present.
PYSIM_READ_PATH=$(find "$BUNDLE_RESOURCES" -name "pySim-read.py" 2>/dev/null | head -1)
BUNDLE_PYSIM_DIR=$(dirname "$PYSIM_READ_PATH")

PYTHONHOME="$BUNDLED_FWK_DIR" PYTHONPATH="$BUNDLE_PYSIM_DIR:$SP_PATH" \
    "$BUNDLED_PYTHON" "$BUNDLE_PYSIM_DIR/pySim-read.py" -h >/dev/null 2>&1 || {
    echo "✗ pySim-read.py -h smoke test failed with bundled Python — aborting"
    exit 1
}
echo "✓ pySim-read.py -h smoke test passed"
echo "  Bundled Python path: $BUNDLED_PYTHON"

# Check 4: import smoke test — verify smpp.pdu, pySim.sms, and pySim.app
# are all importable with the bundled Python + bundled site-packages.
# pySim-shell.py imports pySim.app which transitively imports smpp.pdu
# unconditionally; a missing smpp package is caught here, not on another Mac.
PYSIM_IMPORT_ERR=$(PYTHONHOME="$BUNDLED_FWK_DIR" PYTHONPATH="$BUNDLE_PYSIM_DIR:$SP_PATH" \
    "$BUNDLED_PYTHON" -c "import smpp.pdu; import pySim.sms; import pySim.app" 2>&1) || {
    echo "✗ pySim import smoke test failed — missing bundled dependency:"
    echo "$PYSIM_IMPORT_ERR"
    echo "  Check scripts/requirements-pysim-bundle.txt for missing smpp/pySim packages"
    exit 1
}
echo "✓ pySim import smoke test passed (smpp.pdu, pySim.sms, pySim.app)"

# Check 4b: crypto backend for the gialersim USIM AUTHENTICATE self-check.
# hiddenimports only DECLARES the dependency; PyInstaller can still drop it, and
# the failure is SILENT until a card fails verification in the field. A bundle
# without a working crypto backend disables gialersim programming entirely
# (VERIFY_UNAVAILABLE), so this FAILS the build rather than warning.
#
# The check MUST run through the FROZEN EXECUTABLE, not a framework python -c:
# PyInstaller stores pure-Python modules (e.g. Crypto/Cipher/AES.py) inside its
# PYZ archive, which only the frozen app's bootloader can import — a raw
# framework python sees the on-disk .so extensions but not the .py, and would
# report a false failure. `main.py --selfcheck-crypto` runs selftest() inside
# the frozen process, exactly as the app does at startup.
APP_EXE="$PROJECT_ROOT/dist/SimGUI.app/Contents/MacOS/SimGUI"
CRYPTO_SELFCHECK_ERR=$("$APP_EXE" --selfcheck-crypto 2>&1) || {
    echo "✗ Frozen-app crypto self-check FAILED — aborting"
    echo "$CRYPTO_SELFCHECK_ERR"
    echo "  gialersim key verification would be UNAVAILABLE in the shipped app,"
    echo "  disabling gialersim programming. Ensure 'pycryptodome' is installed"
    echo "  in the build venv and present in SimGUI.spec hiddenimports"
    echo "  (Crypto, Crypto.Cipher, Crypto.Cipher.AES)."
    exit 1
}
echo "✓ Frozen-app crypto self-check passed ($CRYPTO_SELFCHECK_ERR)"

# Check 5: simulate worker preload using bundled Python against the built bundle.
# This catches any missing stdlib module or broken import before the .pkg reaches
# the target machine. Runs card_worker_inproc.py preload() directly.
# Uses same PYTHONHOME + PYTHONPATH as the real worker.
PRELOAD_ERR=$(PYTHONHOME="$BUNDLED_FWK_DIR" \
    PYTHONPATH="$BUNDLE_PYSIM_DIR:$SP_PATH:$PROJECT_ROOT" \
    SIMGUI_WORKER_INPROCESS=1 \
    "$BUNDLED_PYTHON" -c "
import sys
import card_worker_inproc
result = card_worker_inproc.preload()
if result[0]:
    print('PRELOAD_OK')
    sys.exit(0)
else:
    print('PRELOAD_FAIL: ' + result[1])
    sys.exit(1)
" 2>&1) || {
    echo "✗ Worker preload simulation failed — aborting"
    echo "$PRELOAD_ERR"
    exit 1
}
echo "✓ Worker preload simulation passed"

# Check 6: verify 'probe' verb is present in the worker source file.
# Imports directly from PROJECT_ROOT (not the frozen bundle) to test the source
# that PyInstaller will compile into the bundle.  A dirty worktree on the build
# machine can leave card_worker_process.py locally modified so that git pull
# silently skips it (git only refuses to overwrite on conflict; if no upstream
# commit touches the file, a local edit survives every pull indefinitely).
# Fix on M4:  git checkout -- card_worker_process.py
PROBE_CHECK=$(PYTHONHOME="$BUNDLED_FWK_DIR" \
    PYTHONPATH="$PROJECT_ROOT:$BUNDLE_PYSIM_DIR:$SP_PATH" \
    SIMGUI_WORKER_INPROCESS=1 \
    "$BUNDLED_PYTHON" -c "
import sys, card_worker_process
print('SOURCE: ' + card_worker_process.__file__)
caps = card_worker_process._capabilities()
if 'probe' in caps:
    print('PROBE_OK')
    sys.exit(0)
else:
    print('PROBE_MISSING: capabilities=' + str(caps))
    sys.exit(1)
" 2>&1) || {
    echo "✗ Worker 'probe' capability missing in source — dirty worktree suspected."
    echo "$PROBE_CHECK"
    echo ""
    echo "  Run on M4:  git checkout -- card_worker_process.py"
    echo "  Then rebuild."
    exit 1
}
echo "✓ Worker probe capability present"
echo "  $PROBE_CHECK" | grep '^SOURCE:' || true

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
