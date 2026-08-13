#!/usr/bin/env bash
# Install pySim for macOS — required for all SimGUI SIM card operations.
# Called automatically by scripts/build-macos.sh; also safe to run standalone.
#
# When called from build-macos.sh, VENV_PYTHON is set to the project venv Python.
# When run standalone, falls back to system python3.
#
# Requirements:
#   - python3 3.9+  (system python3 or https://python.org — no Homebrew needed)
#   - git           (from Xcode Command Line Tools: xcode-select --install)

set -e

PYTHON="${VENV_PYTHON:-python3}"

echo "SimGUI for macOS — pySim Setup"
echo "================================"
echo ""
echo "This script will install:"
echo "  • pySim (cloned to ~/pysim)"
echo "  • pySim Python dependencies (into ~/pysim/.venv)"
echo ""

# Check for git (ships with Xcode Command Line Tools, no Homebrew needed)
if ! command -v git &> /dev/null; then
    echo "Error: git is required."
    echo "Install Xcode Command Line Tools with: xcode-select --install"
    exit 1
fi

# Clone or update pySim
if [ -d ~/pysim ]; then
    echo "pySim already exists at ~/pysim — updating..."
    git -C ~/pysim pull origin master 2>/dev/null || git -C ~/pysim pull origin main 2>/dev/null || {
        echo "Warning: git pull failed (network issue?); using existing clone."
    }
else
    echo "Cloning pySim to ~/pysim..."
    git clone https://gitea.osmocom.org/sim-card/pysim.git ~/pysim
    echo "Cloned pySim successfully."
fi

# Create pySim venv if it does not already exist
if [ ! -d ~/pysim/.venv ]; then
    echo ""
    echo "Creating pySim virtual environment at ~/pysim/.venv ..."
    "$PYTHON" -m venv ~/pysim/.venv
fi

# Install pySim dependencies into its own isolated venv
echo ""
echo "Installing pySim Python dependencies into ~/pysim/.venv ..."
~/pysim/.venv/bin/python -m pip install --upgrade pip --quiet
if ! ~/pysim/.venv/bin/python -m pip install -r ~/pysim/requirements.txt --quiet; then
    echo ""
    echo "pySim dependency installation failed."
    echo "If pyscard failed to build, install Xcode Command Line Tools:"
    echo "  xcode-select --install"
    echo "Then re-run: bash scripts/build-macos.sh"
    exit 1
fi
echo "pySim dependencies installed."

# pyscard: pre-built universal2 wheels are ABI-incompatible with some Python
# distributions (including Xcode CLT Python 3.9). Always validate and rebuild
# from source so the native _scard extension matches the running interpreter.
echo "Validating pyscard in ~/pysim/.venv ..."
if ! ~/pysim/.venv/bin/python -c "from smartcard.System import readers" 2>/dev/null; then
    echo "  Rebuilding pyscard from source in ~/pysim/.venv ..."
    if ! ~/pysim/.venv/bin/python -m pip install pyscard --no-binary pyscard --no-cache-dir --force-reinstall --quiet; then
        echo ""
        echo "Error: pyscard build failed in ~/pysim/.venv."
        echo "Install Apple Command Line Tools or use python.org Python 3.12+."
        echo ""
        echo "  Apple CLT:   xcode-select --install"
        echo "  python.org:  https://python.org/downloads"
        echo ""
        echo "After installing, delete ~/pysim/.venv and re-run: bash scripts/build-macos.sh"
        exit 1
    fi
fi
echo "  pyscard OK"

# Apply GialerSim SPN patch
echo ""
echo "Checking for GialerSim SPN patch..."
GIALERSIM_PATCH_FILE="$HOME/pysim/pySim/legacy/cards.py"
if [ -f "$GIALERSIM_PATCH_FILE" ]; then
    if grep -q "'name'" "$GIALERSIM_PATCH_FILE"; then
        echo "GialerSim SPN patch already applied."
    else
        echo "Applying GialerSim SPN support patch..."
        "$PYTHON" - "$GIALERSIM_PATCH_FILE" <<'PYEOF'
import sys
path = sys.argv[1]
try:
    text = open(path).read()
    old = "'opc': lambda opc: self.update_uicc_auth_key(ki=None, opc=opc),"
    new = (old + "\n            'name': lambda name: self.update_spn("
           "name=name, show_in_hplmn=True, hide_in_oplmn=False),")
    if old in text and "'name'" not in text:
        open(path, 'w').write(text.replace(old, new))
        print("Patch applied.")
    else:
        print("Patch skipped (already applied or pattern not found).")
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
        if grep -q "'name'" "$GIALERSIM_PATCH_FILE"; then
            echo "GialerSim SPN patch applied successfully."
        else
            echo "Warning: GialerSim SPN patch could not be applied — SPN writes to blank cards will be silently skipped."
        fi
    fi
else
    echo "Patch target not found at $GIALERSIM_PATCH_FILE — skipping (pySim may use a different layout)."
fi

# Apply GialerSim dual-ADM (0x0B) VERIFY patch
# These cards require a SECOND ADM VERIFY (ref 0x0B) in addition to the
# existing 0x0C for writes to MF/0001 (Ki) and MF/6002 (OPc) to actually
# commit. With 0x0C alone, UPDATE returns 9000 but the write is silently
# discarded (USIM AUTHENTICATE still verifies against the OLD Ki).
echo ""
echo "Checking for GialerSim dual-ADM (0x0B) VERIFY patch..."
if [ -f "$GIALERSIM_PATCH_FILE" ]; then
    if grep -q "verify_chv(0xb" "$GIALERSIM_PATCH_FILE"; then
        echo "GialerSim 0x0B VERIFY patch already applied."
    else
        echo "Applying GialerSim dual-ADM (0x0B) VERIFY patch..."
        "$PYTHON" - "$GIALERSIM_PATCH_FILE" <<'PYEOF'
import sys
path = sys.argv[1]
try:
    text = open(path).read()
    anchor = "        self._scc.verify_chv(0xc, h2b('3834373936313533'))\n"
    block = (
        "        # SimGUI patch: dual-ADM — writes to MF/0001 (Ki) and MF/6002\n"
        "        # (OPc) only commit if ADM ref 0x0B is also verified. 0x0C alone\n"
        "        # returns 9000 on UPDATE but silently discards the write.\n"
        "        try:\n"
        "            self._scc.verify_chv(0xb, h2b('3838383838383838'))\n"
        "        except Exception as e:\n"
        "            print(\"GialerSim: ADM 0x0B VERIFY failed (%s) — continuing; \"\n"
        "                  \"Ki/OPc writes may not commit on this card variant\" % e)\n"
    )
    if anchor in text and "verify_chv(0xb" not in text:
        open(path, 'w').write(text.replace(anchor, anchor + block, 1))
        print("Patch applied.")
    else:
        print("Patch skipped (already applied or anchor not found).")
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
        if grep -q "verify_chv(0xb" "$GIALERSIM_PATCH_FILE"; then
            echo "GialerSim 0x0B VERIFY patch applied successfully."
        else
            echo "Warning: GialerSim 0x0B VERIFY patch could not be applied — Ki/OPc writes to blank cards may be silently discarded."
        fi
    fi
else
    echo "Patch target not found at $GIALERSIM_PATCH_FILE — skipping (pySim may use a different layout)."
fi

# Apply PCSC protocol reconnect patch
# pySim's connect() calls setProtocol() on an already-active connection.
# On macOS, PCSC.framework rejects this with SCARD_E_PROTO_MISMATCH.
# Fix: disconnect then reconnect with an explicit protocol constant.
echo ""
echo "Checking for PCSC protocol reconnect patch..."
PCSC_TRANSPORT_FILE="$HOME/pysim/pySim/transport/pcsc.py"
if [ -f "$PCSC_TRANSPORT_FILE" ]; then
    "$PYTHON" - "$PCSC_TRANSPORT_FILE" <<'PYEOF'
import sys
path = sys.argv[1]

MARKER = '# SimGUI patch: disconnect and reconnect'
OLD = (
    '            self._con.connect()\n'
    '            atr = ATR(self._con.getATR())\n'
    '            if atr.isT0Supported():\n'
    '                self._con.setProtocol(CardConnection.T0_protocol)\n'
    '                self.set_tpdu_format(0)\n'
    '            elif atr.isT1Supported():\n'
    '                self._con.setProtocol(CardConnection.T1_protocol)\n'
    '                self.set_tpdu_format(1)\n'
    '            else:\n'
    "                raise ReaderError('Unsupported card protocol')\n"
)
NEW = (
    '            self._con.connect()\n'
    '            atr = ATR(self._con.getATR())\n'
    '            # SimGUI patch: disconnect and reconnect with explicit protocol to avoid\n'
    '            # SCARD_E_PROTO_MISMATCH on macOS where setProtocol() cannot change\n'
    '            # an already-negotiated protocol on an active connection.\n'
    '            self._con.disconnect()\n'
    '            if atr.isT0Supported():\n'
    '                self._con.connect(CardConnection.T0_protocol)\n'
    '                self.set_tpdu_format(0)\n'
    '            elif atr.isT1Supported():\n'
    '                self._con.connect(CardConnection.T1_protocol)\n'
    '                self.set_tpdu_format(1)\n'
    '            else:\n'
    "                raise ReaderError('Unsupported card protocol')\n"
)

try:
    text = open(path).read()
    if MARKER in text:
        print('PCSC reconnect patch already applied.')
        sys.exit(0)
    if OLD not in text:
        print('Error: expected pattern not found in ' + path, file=sys.stderr)
        print('pySim source layout may have changed — patch could not be applied.', file=sys.stderr)
        print('SCARD_E_PROTO_MISMATCH / protocol mismatch will occur on macOS until this is resolved.', file=sys.stderr)
        sys.exit(1)
    open(path, 'w').write(text.replace(OLD, NEW, 1))
    print('PCSC reconnect patch applied.')
except Exception as e:
    print('Error: ' + str(e), file=sys.stderr)
    sys.exit(1)
PYEOF
    if grep -q "SimGUI patch: disconnect and reconnect" "$PCSC_TRANSPORT_FILE"; then
        echo "PCSC reconnect patch verified OK."
    else
        echo "Warning: PCSC reconnect patch could not be verified."
    fi
else
    echo "Patch target not found at $PCSC_TRANSPORT_FILE — skipping (pySim may use a different layout)."
fi

# Apply Python 3.9 staticmethod patch for pySim-shell
# In Python 3.10+, staticmethod descriptors became directly callable.
# In Python 3.9, calling one from a class body raises:
#   TypeError: 'staticmethod' object is not callable
# Fix: replace bare __add_pin_nr_to_ArgumentParser(p) calls with
# __add_pin_nr_to_ArgumentParser.__func__(p), which works in 3.9 and 3.10+.
echo ""
echo "Checking for pySim-shell Python 3.9 staticmethod patch..."
PYSIMSHELL_FILE="$HOME/pysim/pySim-shell.py"
if [ -f "$PYSIMSHELL_FILE" ]; then
    "$PYTHON" - "$PYSIMSHELL_FILE" <<'PYEOF'
import sys
path = sys.argv[1]

OLD = '    __add_pin_nr_to_ArgumentParser('
NEW = '    __add_pin_nr_to_ArgumentParser.__func__('

try:
    text = open(path).read()
    if NEW in text:
        print('pySim-shell Python 3.9 staticmethod patch already applied.')
        sys.exit(0)
    count = text.count(OLD)
    if count == 0:
        print('Warning: expected pattern not found in ' + path)
        print('pySim-shell may not work with Python 3.9 — source layout may have changed.')
        sys.exit(0)
    open(path, 'w').write(text.replace(OLD, NEW))
    print('pySim-shell Python 3.9 staticmethod patch applied (' + str(count) + ' call sites).')
except Exception as e:
    print('Error: ' + str(e), file=sys.stderr)
    sys.exit(1)
PYEOF
    if grep -q "__add_pin_nr_to_ArgumentParser\.__func__" "$PYSIMSHELL_FILE"; then
        echo "pySim-shell Python 3.9 staticmethod patch verified OK."
    else
        echo "Warning: pySim-shell Python 3.9 staticmethod patch could not be verified."
    fi
else
    echo "pySim-shell.py not found at $PYSIMSHELL_FILE — skipping."
fi

echo ""
echo "pySim installed at ~/pysim (dependencies in ~/pysim/.venv)"
echo ""
echo "  1. Plug in your USB card reader (OMNIKEY 3x21 or compatible)"
echo "  2. Launch SimGUI: .venv/bin/python main.py"
echo ""
echo "SimGUI auto-detects pySim at ~/pysim — no PYSIM_PATH export needed."
echo ""
