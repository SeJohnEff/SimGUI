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
- **Read SIM** — read card data (ICCID, IMSI, Ki, OPc, etc.) from physical cards
- **ADM1 authentication** — secure key entry with attempt tracking and input validation
- **ICCID cross-verification** — prevents card lockout by verifying card identity before ADM1 auth
- **Network storage** — mount NFS and SMB/CIFS shares for reading SIM data files and saving artifacts
- **Network discovery** — auto-discover SMB servers on the local network via mDNS and NetBIOS
- **Artifact export** — export programming artifacts to network shares with duplicate detection
- **Simulator mode** — built-in SIM programmer simulator with 20 real sysmoISIM-SJA5 profiles
- **Backup / restore** — JSON backups of card data
- **Progress tracking** — thread-safe progress bar and log output for long operations
- **Modern theme** — platform-aware fonts and macOS-inspired styling (Linux, Windows, macOS)

## Installation (Ubuntu)

On a fresh Ubuntu desktop (22.04+):

```bash
curl -fsSL https://raw.githubusercontent.com/SeJohnEff/SimGUI/main/scripts/install.sh | sudo bash
```

That's it. The script installs build dependencies, builds the `.deb` package,
installs it (including runtime dependencies like `smbclient`, `avahi-utils`,
`cifs-utils`, and `nfs-common`), and cleans up.

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

## Requirements

- Ubuntu 22.04+ (x86-64)
- Python 3.10+
- PyQt6
- At least one of:
  - [sysmo-usim-tool](https://github.com/SeJohnEff/sysmo-usim-tool) (recommended)
  - [pySim](https://github.com/osmocom/pysim)
- A USB PCSC card reader (for hardware operations)

Simulator mode works without a card reader.

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
