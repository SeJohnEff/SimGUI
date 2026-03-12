#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Check dependencies
for cmd in dpkg-buildpackage; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Missing: $cmd"
        echo "Install with: sudo apt install dpkg-dev debhelper"
        exit 1
    fi
done

echo "Building SimGUI .deb package..."
dpkg-buildpackage -us -uc -b

echo ""
echo "Build complete!"
ls -lh ../simgui_*.deb 2>/dev/null
echo ""
echo "Install with:"
echo "  sudo apt install ../simgui_*.deb"
