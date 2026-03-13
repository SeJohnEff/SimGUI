#!/bin/bash
# ---------------------------------------------------------------
#  SimGUI installer — run on a fresh Ubuntu 22.04+ desktop:
#
#    curl -fsSL https://raw.githubusercontent.com/SeJohnEff/SimGUI/main/scripts/install.sh | sudo bash
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
set -euo pipefail

REPO_URL="https://github.com/SeJohnEff/SimGUI.git"
BRANCH="main"

# --- Colours (if terminal supports them) -----------------------
if [ -t 1 ]; then
    BOLD="\033[1m"
    GREEN="\033[32m"
    YELLOW="\033[33m"
    RED="\033[31m"
    RESET="\033[0m"
else
    BOLD="" GREEN="" YELLOW="" RED="" RESET=""
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
apt-get update -qq
apt-get install -y -qq git dpkg-dev debhelper > /dev/null

# --- Clone into temp directory ----------------------------------
BUILD_DIR=$(mktemp -d /tmp/simgui-build.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT

info "Cloning SimGUI ($BRANCH)..."
git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$BUILD_DIR/SimGUI" 2>&1 | tail -1

# --- Build .deb -------------------------------------------------
info "Building .deb package..."
cd "$BUILD_DIR/SimGUI"
BUILD_LOG="$BUILD_DIR/build.log"
if ! dpkg-buildpackage -us -uc -b > "$BUILD_LOG" 2>&1; then
    error "Build failed. Last 30 lines of build log:"
    tail -30 "$BUILD_LOG" >&2
    exit 1
fi

DEB=$(ls "$BUILD_DIR"/simgui_*.deb 2>/dev/null | head -1)
if [ -z "$DEB" ]; then
    error "Build failed — no .deb produced."
    exit 1
fi

# --- Install ----------------------------------------------------
info "Installing $(basename "$DEB")..."
# dpkg -i will exit non-zero when dependencies are missing — that is
# expected.  apt-get install -f resolves them immediately after.
dpkg -i "$DEB" 2>&1 | grep -v "^dpkg:" || true
apt-get install -f -y -qq

# Verify the package is fully installed
if ! dpkg -s simgui >/dev/null 2>&1; then
    error "Installation failed. Run 'sudo apt install -f' manually and check for errors."
    exit 1
fi

# --- Done -------------------------------------------------------
VERSION=$(dpkg-query -W -f='${Version}' simgui 2>/dev/null || echo "unknown")
info "SimGUI $VERSION installed successfully."
echo ""
echo -e "  Launch from terminal:  ${BOLD}simgui${RESET}"
echo -e "  Or find ${BOLD}SimGUI${RESET} in your applications menu."
echo ""
