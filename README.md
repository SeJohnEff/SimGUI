# SimGUI

Lightweight GUI wrapper for SIM card CLI tools. This project is independent from
[sysmo-usim-tool](https://github.com/SeJohnEff/sysmo-usim-tool) and
[pySim](https://github.com/osmocom/pysim) — point SimGUI at either CLI repo
to run card operations from a desktop GUI.

## Features

- **CSV batch editor** — load, edit, validate, and save SIM card configurations
- **Card detection** — detect inserted cards via sysmo-usim-tool or pySim
- **ADM1 authentication** — secure key entry with attempt tracking and input validation
- **ICCID cross-verification** — prevents card lockout by verifying card identity before ADM1 auth
- **Simulator mode** — built-in SIM programmer simulator with 20 real sysmoISIM-SJA5 profiles
- **Backup / restore** — JSON backups of card data
- **Progress tracking** — thread-safe progress bar and log output for long operations
- **Modern theme** — platform-aware fonts and macOS-inspired styling (Linux, Windows, macOS)

## Installation

Create a virtualenv and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Or install with pip directly:

```bash
pip install .
```

### Installation on Ubuntu/Debian

Install the `.deb` package:

```bash
sudo apt install ./simgui_0.1.0_all.deb
```

This installs SimGUI to `/opt/simgui` with a `/usr/bin/simgui` launcher and a
desktop entry. Dependencies (`python3`, `python3-tk`) are pulled in
automatically.

To build the `.deb` from source:

```bash
sudo apt install build-essential debhelper devscripts
./scripts/build-deb.sh
```

## Usage

```bash
python main.py
```

Or, if installed via pip:

```bash
simgui
```

### CLI tool setup

SimGUI shells out to external CLI tools for card operations. Set one of these
environment variables so SimGUI can find the tool:

```bash
# sysmo-usim-tool
export SYSMO_USIM_TOOL_PATH=/path/to/sysmo-usim-tool

# pySim
export PYSIM_PATH=/path/to/pysim
```

SimGUI also checks common locations automatically (`~/sysmo-usim-tool`,
`~/pysim`, `/opt/sysmo-usim-tool`, `/opt/pysim`, or a sibling directory
next to the SimGUI repo).

If neither tool is found, CSV editing and offline preparation still work —
only card reader operations are disabled. SimGUI will default to **Simulator
Mode** so you can still exercise the full workflow (see below).

## Simulator Mode

SimGUI includes a built-in SIM programmer simulator so you can test the full
GUI workflow without a USB card reader or physical SIM cards.

**Activation** — Open the *Card* menu and select *Simulator Mode*. If no CLI
tool is detected on startup SimGUI defaults to simulator mode automatically.

**Real test data** — By default the simulator loads 20 real sysmoISIM-SJA5 card
profiles from sysmocom (bundled in `simulator/data/sysmocom_test_cards.csv`).
Each profile has realistic ICCID, IMSI, Ki, OPc, ADM1, PIN, and PUK values.
You can load your own CSV via *Card > Simulator Settings...* using the file
browser.

**Virtual card navigation** — Cycle through the deck with *Next Virtual Card*
(`Ctrl+N`) and *Previous Virtual Card* (`Ctrl+P`).

**Settings** — Open *Card > Simulator Settings...* to adjust:
- **CSV Data File** — path to a custom CSV file (or leave blank for bundled data)
- **Operation Delay** (0–2000 ms) — artificial delay per operation for realism
- **Error Rate** (0–50 %) — probability of random failures for error-handling
  testing
- **Number of Cards** (1–50) — size of the virtual card deck (used when no CSV
  is loaded)

**Use cases** — UI development, automated testing, demos, and training without
requiring hardware.

## Safety Features

### ICCID Cross-Verification

SIM cards lock permanently after 3 wrong ADM1 authentication attempts. To
prevent accidental lockout, SimGUI verifies the card's ICCID against the
selected CSV data row *before* sending the ADM1 key:

1. When you select a row in the CSV editor and click *Authenticate*, SimGUI
   reads the ICCID from the physical card (no authentication needed).
2. It compares the card's ICCID with the ICCID in the selected CSV row.
3. If they don't match, authentication is **refused** with a clear warning —
   no ADM1 attempt is consumed.
4. If they match (or no CSV row is selected), authentication proceeds normally.

This catches the most common cause of card lockout: authenticating with the
wrong card inserted or the wrong data row selected.

## Architecture

```
SimGUI/
├── main.py                 # Entry point — SimGUIApp class
├── theme.py                # ModernTheme (colors, fonts, ttk styles)
├── managers/
│   ├── card_manager.py     # Card detection / auth via CLI subprocess
│   ├── csv_manager.py      # CSV load / save / validate
│   └── backup_manager.py   # JSON backup / restore
├── simulator/
│   ├── virtual_card.py     # VirtualCard dataclass
│   ├── card_deck.py        # Card deck generation + CSV loading
│   ├── simulator_backend.py # SimulatorBackend (in-memory card ops)
│   ├── settings.py         # SimulatorSettings dataclass
│   └── data/
│       └── sysmocom_test_cards.csv  # 20 bundled sysmoISIM-SJA5 profiles
├── widgets/
│   ├── card_status_panel.py   # Card info + status indicator
│   ├── csv_editor_panel.py    # Treeview-based CSV table editor
│   └── progress_panel.py      # Progress bar + log output
├── dialogs/
│   ├── adm1_dialog.py      # ADM1 key entry dialog
│   └── simulator_settings_dialog.py  # Simulator settings dialog
├── utils/
│   └── validation.py        # Shared validation (ADM1, IMSI, ICCID, hex)
├── tests/                   # pytest test suite
├── debian/                  # Debian packaging files
└── scripts/
    └── build-deb.sh         # .deb build script
```

## License

MIT
