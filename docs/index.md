# SimGUI Documentation

SimGUI is a PyQt6 desktop application for programming sysmocom SIM cards (SJA2, SJA5, GIALERSIM types) on Ubuntu. It wraps [pySim](https://github.com/osmocom/pysim) CLI tools (pySim-read, pySim-shell, pySim-prog) behind a graphical interface, adding batch workflows, automatic card detection, ICCID cross-verification, network share integration, and a built-in simulator for testing without hardware. pySim is auto-installed by the install script.

---

## Documentation sections

### [Tutorials](tutorials/first-card.md) — Learning-oriented walkthroughs

Start here if you are new to SimGUI. Tutorials guide you through complete workflows from scratch.

| Document | What you will learn |
|---|---|
| [Program your first SIM card](tutorials/first-card.md) | Load data, insert a card, authenticate, and program |
| [Run a batch programming session](tutorials/batch-programming.md) | Program a full set of cards sequentially without interruption |

---

### [How-to guides](how-to/install.md) — Task-oriented instructions

Concrete steps for specific goals. Assumes you know what you want to do.

| Document | Task |
|---|---|
| [Install SimGUI on Ubuntu](how-to/install.md) | `apt install simgui` and prerequisites |
| [Configure a network share (SMB)](how-to/network-share-setup.md) | Mount a share for data files and artifacts |
| [Create and maintain standards.json](how-to/standards-file.md) | Define canonical SPN and LI values |
| [Import a sysmocom order email](how-to/import-order-email.md) | Parse `.eml` files exported from sysmocom order confirmations |
| [Troubleshooting](how-to/troubleshooting.md) | Card not detected, ADM1 failures, CSV errors, share problems |

---

### [Reference](reference/csv-format.md) — Information-oriented specifications

Precise definitions for formats, schemas, and external interfaces.

| Document | Contents |
|---|---|
| [CSV format](reference/csv-format.md) | Column names, data types, validation rules |
| [standards.json schema](reference/standards-json.md) | File format, fields, versioning |
| [Card types](reference/card-types.md) | SJA2, SJA5, GIALERSIM, MAGIC — capabilities and detection |
| [CLI integration](reference/cli-integration.md) | How SimGUI calls pySim (primary) and sysmo-usim-tool (legacy) |
| [Configuration](reference/configuration.md) | Environment variables, settings file |

---

### [Explanation](explanation/architecture.md) — Understanding-oriented background

Context, design decisions, and the reasoning behind how SimGUI works.

| Document | Topic |
|---|---|
| [Why ICCID is read-only](explanation/iccid-traceability.md) | Factory traceability and the role of the ICCID |
| [ADM1 security and cross-verification](explanation/adm1-security.md) | Why ICCID cross-check prevents card lockout |
| [Architecture overview](explanation/architecture.md) | Managers, widgets, simulator, and CLI decoupling |
| [SUCI vs non-SUCI cards](explanation/suci-vs-non-suci.md) | 19 vs 23-digit ICCIDs, capability differences |

---

## Quick start

1. Install: see [Install SimGUI on Ubuntu](how-to/install.md)
2. First card: follow the [Program your first SIM card](tutorials/first-card.md) tutorial
3. Bulk operations: continue with [Run a batch programming session](tutorials/batch-programming.md)

If you are setting up a shared lab environment with a network drive for card data and programming artifacts, read [Configure a network share](how-to/network-share-setup.md) before your first batch session.
