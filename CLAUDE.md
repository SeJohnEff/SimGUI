# Instructions

You are an autonomous coding subagent spawned by a parent agent to complete a specific task. You run unattended — there is no human in the loop and no way to ask for clarification. You must complete the task fully on your own and then exit.

You have two categories of skills:

- **Coding skills** (`coding-workflow`, `commit-push-pr`, `pr-description`, `code-simplifier`, `code-review`): For repository work, writing code, git operations, pull requests, and code quality
- **Data skills** (`data-triage`, `data-analyst`, `data-model-explorer`): For database queries, metrics, data analysis, and visualizations
- **Repo skills** (`repo-skills`): After cloning any repo, scan for and index its skill definitions

Load the appropriate skill based on the task. If the task involves both code and data, load both. Always load `repo-skills` after cloning a repository.

## Execution Rules

- Do NOT stall. If an approach isn't working, try a different one immediately.
- Do NOT explore the codebase endlessly. Get oriented quickly, then start making changes.
- If a tool is missing (e.g., `rg`), use an available alternative (e.g., `grep -r`) and move on.
- If a git operation fails, try a different approach (e.g., `gh repo clone` instead of `git clone`).
- Stay focused on the objective. Do not go on tangents or investigate unrelated code.
- If you are stuck after multiple retries, abort and report what went wrong rather than looping forever.

## Repo Conventions

After cloning any repository, immediately check for and read these files at the repo root:
- `CLAUDE.md` — Claude Code instructions and project conventions
- `AGENTS.md` — Agent-specific instructions

Follow all instructions and conventions found in these files. They define the project's coding standards, test requirements, commit conventions, and PR expectations. If they conflict with these instructions, the repo's files take precedence.

## Core Rules

- Ensure all changes follow the project's coding standards (as discovered from repo convention files above)
- NEVER approve PRs — you are not authorized to approve pull requests. Only create and comment on PRs.
- Complete the task autonomously and create the PR(s) when done.

## Output Persistence

IMPORTANT: Before finishing, you MUST write your complete final response to `/tmp/claude_code_output.md` using the Write tool. This file must contain your full analysis, findings, code, or whatever the final deliverable is. This is a hard requirement — do not skip it.

---

# SimGUI — Project Knowledge

## Overview

SimGUI is a PyQt6 desktop application for programming SIM cards (sysmoISIM-SJA5 and gialersim types) via pySim CLI tools. It wraps `pySim-shell`, `pySim-prog`, and `pySim-read` with a GUI for single-card and batch programming workflows. Targets Ubuntu 22.04+ (x86-64 and ARM/aarch64). Packaged as a `.deb`.

## Architecture

```
main.py                    # Entry point
version.py                 # Single source of truth for version string
managers/
  card_manager.py          # Core: card detection, auth, programming (pySim wrapper)
  csv_manager.py           # CSV file loading/saving/validation
  batch_manager.py         # Batch programming orchestration
  settings_manager.py      # App settings persistence
  state_manager.py         # UI state management
  network_storage_manager.py  # NFS/SMB mount management
  backup_manager.py        # Card data backup/restore
  auto_artifact_manager.py # Per-card artifact export after programming
ui/
  main_window.py           # Main application window
  panels/                  # Tab panels (CSV editor, Read SIM, Program SIM, Batch)
  dialogs/                 # ADM1 dialog, network storage, etc.
  widgets/                 # Reusable Qt widgets
  theme.py                 # Qt stylesheet / theming
simulator/                 # Built-in SIM programmer simulator (20 test profiles)
tests/                     # pytest suite (2044+ tests)
debian/                    # Debian packaging
scripts/install.sh         # One-liner installer
docs/                      # Diátaxis documentation
```

## SIM Card Types — CRITICAL KNOWLEDGE

### Card Type Enum (`CardType` in card_manager.py)
- `UNKNOWN` — Not yet detected
- `SJA2` — sysmoISIM-SJA2
- `SJA5` — sysmoISIM-SJA5 (pre-programmed Fiskarheden cards)
- `MAGIC` — magicSIM
- `GIALERSIM` — Blank/unpersonalised Fiskarheden cards

### Gialersim vs SJA5 — The Key Difference
- **SJA5 cards** (non-empty, pre-programmed): Use CHV `0x0A` for ADM1 authentication. Standard `verify_adm` works via pySim-shell.
- **Gialersim cards** (blank, unpersonalised): Use CHV `0x0C` internally with a hardcoded key. Standard `verify_adm` (CHV `0x0A`) returns `6f00` and **consumes retry attempts**. After 3 failures the card is permanently blocked.
- pySim-read auto-detects gialersim cards: output contains `Autodetected card type: gialersim`
- Blank gialersim cards have no ICCID or IMSI, but may have `ACC: ffff` from pySim-read

### Programming Flows
- **Non-empty cards (SJA5)**: Use `pySim-shell` with `-A <hex_ADM1>` and piped commands for delta writes. ICCID is read-only (factory-assigned, used for traceability).
- **Empty/gialersim cards**: Use `pySim-prog` with `-t gialersim -a <ASCII_ADM1>` for full card programming. ICCID is written from CSV because blank cards have no ICCID.
- **NEVER** use `-t auto` for gialersim — it causes CHV 0x0A VERIFY which fails with 6f00.
- **NEVER** change ICCID on non-empty cards.

### ADM1 Key Format
- ADM1 is an **administrative key** (not a PIN). 8 bytes.
- Fiskarheden CSV files store ADM1 in **hex format**: 16 hex chars like `3838383838383838`
- Other files store ADM1 in **plain ASCII**: 8 chars like `88888888`
- Detection: length 16 = hex, length ≤8 = ASCII
- `3838383838383838` hex = `88888888` ASCII — this IS correct for Fiskarheden cards and is the default for blank cards
- `_hex_to_adm1_ascii()` converts hex to ASCII for the `-a` pySim-prog flag

### ICCID Lengths
- Non-SUCI cards: 23-digit ICCIDs
- SUCI cards: 19-digit ICCIDs
- Both are factory-assigned by sysmocom

## Authentication Logic

```
authenticate(adm1_ascii):
  1. Check retry counter (abort if 0 — card blocked)
  2. If card is blank/gialersim OR has no ICCID/IMSI:
     → Store ADM1 for later pySim-prog use
     → Do NOT send VERIFY (would fail with 6f00 and waste retries)
     → Return success
  3. If card is non-empty (SJA5):
     → Convert ASCII to hex if needed
     → Send VERIFY via pySim-shell -A <hex>
     → Parse result for success/failure
```

## pySim CLI Integration

### pySim-read
- Detects card type: `Autodetected card type: gialersim|sysmoISIM-SJA5|...`
- Reads: ICCID, IMSI, ACC, SPN, FPLMN
- Blank cards return empty ICCID/IMSI but may return ACC

### pySim-prog (empty cards)
```bash
pySim-prog.py -t gialersim -p 0 -a 88888888 -s <ICCID> -i <IMSI> -k <Ki> --opc <OPc> -n <SPN> --acc <ACC> -x <MCC> -y <MNC>
```
- `-t gialersim` — card type (NOT `-t auto`)
- `-a` — ASCII ADM1 key (NOT `-A` which is hex)
- `-p 0` — PCSC reader slot 0

### pySim-shell (non-empty cards)
```bash
python pySim-shell.py -p 0 -A <hex_ADM1>
```
- Commands piped via stdin, terminated with `quit`
- **Do NOT use `--noprompt`** — it prevents stdin processing
- `exit` does NOT work — must use `quit`
- Exit code 0 even on APDU failures — must scan output for errors:
  - `SwMatchError`, `6f00`, `not equipped`, `Card error`, `Autodetection failed`

### pySim-shell field write commands
- IMSI: `select MF/ADF.USIM/EF.IMSI` → `update_binary_dec <json>`
- Ki/OPc: `select MF/ADF.USIM/EF.USIM_AUTH_KEY` → `update_binary_dec <json>`
- SPN: `select MF/ADF.USIM/EF.SPN` → `update_binary_dec <json>`
- ACC: `select MF/ADF.USIM/EF.ACC` → `update_binary <hex>`
- FPLMN: `select MF/ADF.USIM/EF.FPLMN` → `update_binary <hex>`

## Empty Card Detection

`_is_empty_card()` returns True if ANY of:
1. `_original_card_data` is falsy (None or empty dict)
2. `_original_card_data` has no ICCID AND no IMSI (partial read, like ACC-only)
3. `card_type == CardType.GIALERSIM`

## Testing

- Framework: pytest
- 2044+ tests, 48 skipped (Qt/GUI tests needing display)
- Run: `python -m pytest tests/ -x -q`
- Key test files:
  - `tests/test_empty_card_programming.py` — blank/gialersim card flows
  - `tests/test_card_manager.py` — core card manager unit tests
  - `tests/test_card_safety.py` — ICCID cross-verification, ADM1 safety
  - `tests/test_e2e_contracts.py` — end-to-end contract tests

## Design Principles

- **v0.5.8 non-empty SIM flow is frozen** — do not change non-empty card programming
- **Elegant, robust, and flexible** — identify blockers early
- **Safety first**: Confirm ICCID matches before ADM1 auth. A mismatch = wrong ADM1 = card bricked after 3 fails.
- **ICCID is read-only for non-empty cards** (factory traceability). Only written on blank cards.
- **Make a plan before fixing bugs** — the workflow must be in the plan
- **Think globally** — auth changes apply everywhere auth is done, not just one tab

## Git & Deployment

- Push via GitHub API (blobs/trees/commits)
- Install: `curl -fsSL https://raw.githubusercontent.com/SeJohnEff/SimGUI/main/scripts/install.sh | sudo bash`
- After API push, sync local: `git fetch origin && git reset --hard origin/main`
- Version in `version.py`, mirrored in `debian/changelog`

## Hardware Environment

- MacBook Air M4 → UTM VM → Ubuntu (ARM/aarch64)
- USB Reader: HID Global OMNIKEY 3x21 (USB passthrough to VM)
- pySim installed at `/opt/pysim` with `.venv`
- pcscd service required for PCSC reader access
