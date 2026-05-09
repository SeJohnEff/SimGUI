# SimGUI

Lightweight GUI wrapper for SIM card CLI tools. This project is independent from
[sysmo-usim-tool](https://github.com/SeJohnEff/sysmo-usim-tool) and
[pySim](https://github.com/osmocom/pysim) — point SimGUI at either CLI repo
to run card operations from a desktop GUI.

## Features

- **CSV batch editor** — load, edit, validate, and save SIM card configurations
- **EML import** — parse sysmocom order confirmation emails (.eml) directly, field-order independent
- **Batch programming** — program multiple SIM cards in sequence with progress tracking
- **Card detection** — detect inserted cards via sysmo-usim-tool or pySim
- **Blank card programming** — program unpersonalised SIM cards (gialersim type) using pySim-prog with auto-detected card type
- **Read SIM** — read card data (ICCID, IMSI, Ki, OPc, etc.) from physical cards
- **ADM1 authentication** — secure key entry with attempt tracking and input validation; blank/gialersim cards skip VERIFY to avoid consuming retry attempts
- **ICCID cross-verification** — prevents card lockout by verifying card identity before ADM1 auth
- **Network storage** — mount NFS and SMB/CIFS shares for reading SIM data files and saving artifacts
- **Network discovery** — auto-discover SMB servers on the local network via mDNS and NetBIOS
- **Artifact export** — export programming artifacts to network shares with duplicate detection
- **Simulator mode** — built-in SIM programmer simulator with 20 real sysmoISIM-SJA5 profiles
- **Backup / restore** — JSON backups of card data
- **Progress tracking** — thread-safe progress bar and log output for long operations
- **Modern theme** — platform-aware fonts and macOS-inspired styling (Linux, Windows, macOS)

## Installation

### macOS (v0.5.37+)

**From source** (recommended for now):

```bash
git clone https://github.com/SeJohnEff/SimGUI
cd SimGUI
pip install -r requirements.txt
python3 main.py
```

For hardware support (programming real SIM cards), also install pySim:

```bash
git clone https://gitea.osmocom.org/sim-card/pysim.git ~/pysim
cd ~/pysim && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export PYSIM_PATH=~/pysim
```

**Note**: PyInstaller `.pkg` bundle is in progress (v0.5.37 fixed Python 3.9 compatibility; GUI asset loading blocked v0.5.38 release).

### Ubuntu (22.04+)

One-liner (downloads, builds, and installs `.deb`):

```bash
curl -fsSL https://raw.githubusercontent.com/SeJohnEff/SimGUI/main/scripts/install.sh | sudo bash
```

For manual installation or CLI tool setup, see the [documentation](docs/index.md).

## Documentation

Full documentation is in the [`docs/`](docs/index.md) directory, organised using the [Diátaxis](https://diataxis.fr/) framework:

| Section | Contents |
|---|---|
| [Tutorials](docs/tutorials/first-card.md) | Step-by-step walkthroughs for new users |
| [How-to guides](docs/how-to/install.md) | Task-oriented instructions for specific goals |
| [Reference](docs/reference/csv-format.md) | Format specs, schemas, CLI interface |
| [Explanation](docs/explanation/architecture.md) | Architecture, design decisions, background |

## Quick start (after install)

```bash
simgui
```

Or follow the [first-card tutorial](docs/tutorials/first-card.md).

## Platform Support

| Platform | Status | Package |
|----------|--------|---------|
| **macOS 12+** (Apple Silicon & Intel) | ✅ Native .app (v0.5.37+) | `.pkg` installer |
| **Ubuntu 22.04+** (x86-64, ARM/aarch64) | ✅ Stable | `.deb` package |

### Requirements

**For simulator mode** (no hardware needed):
- macOS 12+ or Ubuntu 22.04+
- That's it — 20 virtual SIM profiles included

**For hardware support** (programming real SIM cards):
- [pySim](https://github.com/osmocom/pysim) (or sysmo-usim-tool for older versions)
- A USB PCSC-compatible card reader (e.g., OMNIKEY 3x21)
- macOS: uses built-in `PCSC.framework`
- Ubuntu: requires `pcscd` service (installed automatically)

## Development

```bash
git clone https://github.com/SeJohnEff/SimGUI
cd SimGUI
pip install -r requirements.txt
python main.py
```

Run tests:

```bash
pytest
```

Run linter:

```bash
ruff check .
```

## Licence

MIT
