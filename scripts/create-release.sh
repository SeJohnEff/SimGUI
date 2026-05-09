#!/usr/bin/env bash
# Create GitHub release for SimGUI with macOS support

set -e

VERSION="v0.5.37"
ARTIFACT="dist/SimGUI.dmg"

if [ ! -f "$ARTIFACT" ]; then
    echo "Error: $ARTIFACT not found"
    echo "Run: ./scripts/build-macos-app.sh"
    exit 1
fi

if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) not installed"
    echo "Install with: brew install gh"
    echo "Or visit: https://github.com/cli/cli"
    exit 1
fi

echo "Creating GitHub release: $VERSION"
echo "Artifact: $ARTIFACT"
echo ""

gh release create "$VERSION" \
  --title "SimGUI $VERSION — Native macOS Support" \
  --notes "## 🎉 Native macOS Support

SimGUI now runs natively on macOS (Intel and Apple Silicon) with zero prerequisites!

### What's New

✨ **Zero-Setup Simulator Mode**
- Download \`SimGUI.dmg\` → drag to Applications → run
- 20 virtual SIM card profiles included
- No Python, no pySim, no pcscd needed
- Works immediately for learning and testing

🔧 **Optional Hardware Support**
- Run \`bash scripts/install-macos.sh\` for pySim setup
- Set \`export PYSIM_PATH=~/pysim\`
- Plug in OMNIKEY reader → auto-detected
- Full programming capabilities with real cards

🌐 **macOS Integration**
- Native SMB mount via \`mount_smbfs\`
- macOS Bonjour mDNS discovery (\`dns-sd\`)
- Built-in PCSC.framework (no daemon needed)

### Downloads

- **SimGUI.dmg** (4.7 MB) — Recommended
- **SimGUI.app** (4.3 MB) — Direct .app bundle

### Installation (Zero Setup)

\`\`\`bash
1. Download SimGUI.dmg
2. Double-click to mount
3. Drag SimGUI.app to /Applications
4. Double-click to run
\`\`\`

### Platform Support

- ✅ macOS 12+ (Monterey and later)
- ✅ Apple Silicon (M1/M2/M3/M4)
- ✅ Intel Macs
- ✅ Ubuntu 22.04+ (unchanged)

---

**Built:** May 9, 2026 | **Commit:** 9066a10 | **Tool:** PyInstaller 6.20.0" \
  "$ARTIFACT"

echo ""
echo "✓ Release created successfully!"
echo ""
echo "View at: https://github.com/SeJohnEff/SimGUI/releases/tag/$VERSION"
