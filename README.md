# SimGUI

Lightweight GUI wrapper for SIM card CLI tools. This project is independent from
[sysmo-usim-tool](https://github.com/SeJohnEff/sysmo-usim-tool) and
[pySim](https://github.com/osmocom/pysim) — point SimGUI at either CLI repo
to run card operations from a desktop GUI.

## Features

- **CSV batch editor** — load, edit, validate, and save SIM card configurations
- **Card detection** — detect inserted cards via sysmo-usim-tool or pySim
- **ADM1 authentication** — secure key entry with attempt tracking and input validation
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
only card reader operations are disabled.

## Architecture

```
SimGUI/
├── main.py                 # Entry point — SimGUIApp class
├── theme.py                # ModernTheme (colors, fonts, ttk styles)
├── managers/
│   ├── card_manager.py     # Card detection / auth via CLI subprocess
│   ├── csv_manager.py      # CSV load / save / validate
│   └── backup_manager.py   # JSON backup / restore
├── widgets/
│   ├── card_status_panel.py   # Card info + status indicator
│   ├── csv_editor_panel.py    # Treeview-based CSV table editor
│   └── progress_panel.py      # Progress bar + log output
├── dialogs/
│   └── adm1_dialog.py      # ADM1 key entry dialog
├── utils/
│   └── validation.py        # Shared validation (ADM1, IMSI, ICCID, hex)
└── tests/                   # pytest test suite
```

## License

MIT
