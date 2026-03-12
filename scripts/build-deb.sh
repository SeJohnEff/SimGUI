#!/bin/bash
# Build a .deb package for SimGUI.
#
# Usage:
#   ./scripts/build-deb.sh
#
# Prerequisites:
#   sudo apt install build-essential debhelper devscripts
#
# The resulting .deb will be placed in the parent directory of the repo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

echo "Building SimGUI .deb package..."
dpkg-buildpackage -us -uc -b

echo ""
echo "Build complete. Package:"
ls -1 ../simgui_*.deb 2>/dev/null || echo "(check parent directory for .deb file)"
