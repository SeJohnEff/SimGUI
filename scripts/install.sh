#!/bin/bash
# ---------------------------------------------------------------
#  SimGUI installer — run on a fresh Ubuntu 22.04+ desktop:
#
#  Latest:   curl -fsSL https://raw.githubusercontent.com/SeJohnEff/SimGUI/main/scripts/install.sh | sudo bash
#  Specific: curl -fsSL https://raw.githubusercontent.com/SeJohnEff/SimGUI/main/scripts/install.sh | sudo bash -s -- v0.5.1
#
#  What it does:
#    1. Installs build dependencies (git, dpkg-dev, debhelper)
#    2. Clones the repo into a temp directory
#    3. Builds the .deb package
#    4. Installs the .deb (pulls in runtime deps automatically)
#    5. Cleans up the temp directory
#
#  After install, launch with:  simgui
# ---------------------------------------------------------------
set -eo pipefail

REPO_URL="https://github.com/SeJohnEff/SimGUI.git"
# Install a specific version:  curl ... | sudo bash -s -- v0.5.1
# or latest:                   curl ... | sudo bash
BRANCH="${1:-main}"

# --- Colours (if terminal supports them) -----------------------
if [ -t 1 ]; then
    BOLD="\033[1m"
    GREEN="\033[32m"
    YELLOW="\033[33m"
    RED="\033[31m"
    RESET="\033[0m"
else
    BOLD="" ; GREEN="" ; YELLOW="" ; RED="" ; RESET=""
fi

info()  { echo -e "${GREEN}${BOLD}[SimGUI]${RESET} $*"; }
warn()  { echo -e "${YELLOW}${BOLD}[SimGUI]${RESET} $*"; }
error() { echo -e "${RED}${BOLD}[SimGUI]${RESET} $*" >&2; }

# --- Pre-flight checks -----------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    error "This script must be run as root (use sudo)."
    exit 1
fi

info "Installing build dependencies..."
if ! apt-get update -qq 2>&1; then
    warn "apt-get update had warnings (continuing anyway)"
fi
apt-get install -y -qq git dpkg-dev debhelper 2>&1 | grep -v "is already the newest" || true

# --- Clone into temp directory ----------------------------------
BUILD_DIR=$(mktemp -d /tmp/simgui-build.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT

info "Cloning SimGUI ($BRANCH)..."
if ! git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$BUILD_DIR/SimGUI" 2>&1; then
    error "Git clone failed."
    exit 1
fi

# --- Bake build hash into source --------------------------------
cd "$BUILD_DIR/SimGUI"
BUILD_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "$BUILD_HASH" > BUILD
info "Build hash: $BUILD_HASH"

# --- Build .deb -------------------------------------------------
info "Building .deb package..."
BUILD_LOG="$BUILD_DIR/build.log"
if ! dpkg-buildpackage -us -uc -b > "$BUILD_LOG" 2>&1; then
    error "Build failed. Last 30 lines of build log:"
    tail -30 "$BUILD_LOG" >&2
    exit 1
fi

DEB=$(find "$BUILD_DIR" -maxdepth 1 -name "simgui_*.deb" -print -quit)
if [ -z "$DEB" ]; then
    error "Build failed — no .deb produced."
    exit 1
fi

# --- Install ----------------------------------------------------
info "Installing $(basename "$DEB")..."
# dpkg -i will exit non-zero when dependencies are missing — that is
# expected.  apt-get install -f resolves them immediately after.
dpkg -i "$DEB" 2>&1 || true
apt-get install -f -y -qq 2>&1

# Verify the package is fully installed
if ! dpkg -s simgui >/dev/null 2>&1; then
    error "Installation failed. Run 'sudo apt install -f' manually and check for errors."
    exit 1
fi

# --- Install pySim -----------------------------------------------
PYSIM_DIR="/opt/pysim"
PYSIM_REPO="https://gitea.osmocom.org/sim-card/pysim.git"

if [ -d "$PYSIM_DIR" ] && [ -f "$PYSIM_DIR/pySim-shell.py" ]; then
    info "pySim already installed at $PYSIM_DIR — updating..."
    cd "$PYSIM_DIR" && git pull --quiet 2>&1 || warn "pySim update failed (continuing with existing version)"
else
    info "Installing pySim to $PYSIM_DIR..."
    rm -rf "$PYSIM_DIR"
    if ! git clone --depth 1 "$PYSIM_REPO" "$PYSIM_DIR" 2>&1; then
        warn "pySim clone failed — SimGUI will run in simulator-only mode."
        warn "You can install pySim manually later: git clone $PYSIM_REPO $PYSIM_DIR"
    fi
fi

# Set up pySim venv with dependencies
if [ -d "$PYSIM_DIR" ] && [ -f "$PYSIM_DIR/pySim-shell.py" ]; then
    info "Setting up pySim virtual environment..."
    # Ensure python3-venv is available
    apt-get install -y -qq python3-venv 2>&1 | grep -v "is already the newest" || true
    if [ ! -d "$PYSIM_DIR/.venv" ]; then
        python3 -m venv "$PYSIM_DIR/.venv" 2>&1
    fi
    # Install pySim dependencies into the venv
    if [ -f "$PYSIM_DIR/requirements.txt" ]; then
        "$PYSIM_DIR/.venv/bin/pip" install --quiet -r "$PYSIM_DIR/requirements.txt" 2>&1 || \
            warn "Some pySim dependencies failed to install"
    fi
    # Also install pySim itself in editable mode if setup.py exists
    if [ -f "$PYSIM_DIR/setup.py" ] || [ -f "$PYSIM_DIR/pyproject.toml" ]; then
        "$PYSIM_DIR/.venv/bin/pip" install --quiet -e "$PYSIM_DIR" 2>&1 || \
            warn "pySim package install failed"
    fi
    info "pySim ready at $PYSIM_DIR"
fi

# --- Sudoers rule for network mounts ----------------------------
# Allow SimGUI to mount/unmount network shares without a password prompt.
# The postinst script does this too, but we run it here as well in case
# the .deb postinst was skipped or the sudoers file was updated.
SUDOERS_SRC="/opt/simgui/etc/simgui-mount.sudoers"
SUDOERS_DST="/etc/sudoers.d/simgui-mount"
if [ -f "$SUDOERS_SRC" ]; then
    if visudo -c -f "$SUDOERS_SRC" >/dev/null 2>&1; then
        cp "$SUDOERS_SRC" "$SUDOERS_DST"
        chmod 0440 "$SUDOERS_DST"
        info "Sudoers rule installed for passwordless network mounts."
    else
        warn "Sudoers syntax check failed — skipping (mounts may require password)."
    fi
fi

# Ensure cifs-utils is available for SMB mounts
if ! command -v mount.cifs >/dev/null 2>&1; then
    info "Installing cifs-utils for SMB mount support..."
    apt-get install -y -qq cifs-utils 2>&1 || warn "cifs-utils install failed"
fi

# --- Done -------------------------------------------------------
VERSION=$(dpkg-query -W -f='${Version}' simgui 2>/dev/null || echo "unknown")
info "SimGUI $VERSION installed successfully."
echo ""
echo -e "  Launch from terminal:  ${BOLD}simgui${RESET}"
echo -e "  Or find ${BOLD}SimGUI${RESET} in your applications menu."
echo ""
