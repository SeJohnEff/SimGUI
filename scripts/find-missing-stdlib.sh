#!/bin/bash
set -e
APP="/Applications/SimGUI.app"
BUNDLED_PYTHON=$(find "$APP/Contents" -name "python3*" -type f ! -name "*.pyc" | head -1)
PYSIM_DIR=$(find "$APP/Contents" -name "__init__.py" -path "*/pySim/*" | head -1 | xargs dirname | xargs dirname)
SITE_PKG=$(find "$APP/Contents" -name "pySim-site-packages" -o -name "pysim-site-packages" 2>/dev/null | head -1)
echo "Bundled Python: $BUNDLED_PYTHON"
echo "pySim dir: $PYSIM_DIR"
echo "Site-packages: $SITE_PKG"
"$BUNDLED_PYTHON" - <<EOF
import sys, modulefinder, sysconfig
sys.path.insert(0, '$PYSIM_DIR')
sys.path.insert(0, '$SITE_PKG')
f = modulefinder.ModuleFinder(path=sys.path)
f.run_script('$PYSIM_DIR/pySim-shell.py')
missing = sorted(f.badmodules.keys())
print('\nMISSING MODULES:', missing)
EOF
