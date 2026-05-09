#!/usr/bin/env bash
# SimGUI macOS Installation Script
# Download and run this script to install SimGUI with zero Gatekeeper warnings

set -e

echo "🎉 SimGUI macOS Installer"
echo "========================================"
echo ""

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This script only works on macOS"
    exit 1
fi

# Download latest release
echo "Downloading SimGUI..."
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

cd "$TEMP_DIR"
curl -fsSL -o SimGUI.pkg https://github.com/SeJohnEff/SimGUI/releases/download/v0.5.37/SimGUI.pkg

# Remove Gatekeeper quarantine
echo "Preparing installer..."
xattr -d com.apple.quarantine SimGUI.pkg 2>/dev/null || true

# Install
echo "Installing SimGUI..."
sudo installer -pkg SimGUI.pkg -target /

# Remove quarantine from installed app
echo "Finalizing..."
xattr -d com.apple.quarantine /Applications/SimGUI.app 2>/dev/null || true

echo ""
echo "✅ Installation complete!"
echo ""
echo "🚀 Launch SimGUI:"
echo "   open /Applications/SimGUI.app"
echo ""
echo "📚 For hardware support (optional):"
echo "   bash ~/SimGUI/scripts/install-macos.sh"
echo ""
