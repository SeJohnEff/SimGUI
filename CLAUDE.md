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

### Programming Flows (v0.5.32+)
- **ALL card types** use `pySim-prog` as the single write engine (`_program_via_pysim_prog`).
  - **Non-empty cards (SJA5)**: delta-write — only changed fields sent to pySim-prog; ICCID excluded (factory-assigned). pySim-prog uses `-t sysmoISIM-SJA5 -A <hex_ADM1>`.
  - **Empty/gialersim cards**: full write — all non-empty fields sent to pySim-prog. Uses `-t gialersim -a <ASCII_ADM1>`. ICCID written from CSV.
- **pySim-shell** is used ONLY for authentication (`_run_pysim_shell_safe`) — never for writes.
- **NEVER** use `-t auto` for gialersim — it causes CHV 0x0A VERIFY which fails with 6f00.
- **NEVER** change ICCID on non-empty cards.
- Ki and OPc share the same EF — if either changes, both are written together.

### ADM1 Key Format
- ADM1 is an **administrative key** (not a PIN). 8 bytes.
- Fiskarheden CSV files store ADM1 in **hex format**: 16 hex chars like `3838383838383838`
- Other files store ADM1 in **plain ASCII**: 8 chars like `88888888`
- Detection: length 16 = hex, length ≤8 = ASCII
- `3838383838383838` hex = `88888888` ASCII — this IS correct for Fiskarheden cards and is the default for blank cards
- `_hex_to_adm1_ascii()` converts hex to ASCII for the `-a` pySim-prog flag

### ICCID Lengths
- All card types: **19-digit ICCIDs** (conforms to ITU-T E.118 max 19 visible characters)
- Format: `89(2) + CCC(3) + II(2) + SSSS(4) + T(1) + NNNNNN(6) + L(1) = 19`
- IIN (7 digits): `89` + E.164 country code + issuer identifier (= MNC)
- Sequence: 6 digits (max 999,999 cards per site/type combination)
- Luhn check digit appended
- See `sim-standard.example.json` numbering section for full field definitions
- Factory-assigned by sysmocom; written from CSV for blank/gialersim cards

## Authentication Logic

```
authenticate(adm1_ascii):
  0. If _original_card_data is None AND no card_info:
     → Return False, "No SIM card detected" (no detect_card() ever succeeded)
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

`_original_card_data` sentinel:
- `None` — no card detected yet (initial state; also set by `disconnect()`).
  `authenticate()` returns False immediately when sentinel is None.
- `{}` — card detected but blank (gialersim: no ICCID, no IMSI).
  `_is_empty_card()` returns True.
- `{…data…}` — card detected and has fields.

`_is_empty_card()` returns True if ANY of:
1. `_original_card_data` is falsy (`None` or `{}`)
2. `_original_card_data` has no ICCID AND no IMSI (partial read, like ACC-only)
3. `card_type == CardType.GIALERSIM`

## pySim Patch — GialerSim SPN Support

**File:** `/opt/pysim/pySim/legacy/cards.py`

**Problem:** The `GialerSim` class in pySim does not implement SPN writing.
pySim-prog's `-n` flag is silently ignored for gialersim cards because
`_program_handlers` has no `'name'` key.

**Fix:** Add a `'name'` handler to `GialerSim._program_handlers` in `__init__`:
```python
'name': lambda name: self.update_spn(name=name, show_in_hplmn=True, hide_in_oplmn=False),
```

**This patch must be applied manually after every pySim install/update.**
The install script (`scripts/install.sh`) should ideally apply this automatically.

**Why CHV 0x0A VERIFY fails on gialersim:**
- Standard ADM1 auth uses CHV 0x0A — gialersim cards reject this with SW 6f00
- pySim-shell does not support `-t` flag (unrecognized argument)
- pySim-prog with `-t gialersim` uses the correct internal auth sequence
- All gialersim field writes (ICCID, IMSI, Ki, OPc, ACC, SPN, FPLMN) must
  go through pySim-prog, not pySim-shell

## Testing

- Framework: pytest
- ~2200 passed, 14 skipped (Qt/GUI tests needing display, hardware-gated)
- Hardware-gated tests: `SIMGUI_HW_TEST=1 python3 -m pytest tests/test_e2e_contracts.py::TestHardwareGated -v`
- Run: `python3 -m pytest tests/ -x -q`
- Key test files:
  - `tests/test_empty_card_programming.py` — blank/gialersim card flows
  - `tests/test_card_manager.py` — core card manager unit tests
  - `tests/test_card_safety.py` — ICCID cross-verification, ADM1 safety
  - `tests/test_e2e_contracts.py` — end-to-end contract tests

## Design Principles

### Core Philosophy
- **Elegant, robust, and flexible** — these have highest priority
- **Identify blockers early** — surface problems before they cascade
- **Think simplicity** — break down complexity into small, clear pieces
- **Think globally** — a fix in one place (e.g. auth) must apply everywhere auth is done, not just one tab

### Architecture Mindset
- **Signals & subscriptions for globals** — use `StateManager` signals for cross-component communication, not direct coupling between widgets
- **Managers are framework-free** — `card_manager`, `csv_manager`, etc. have zero Qt imports. StateManager bridges them to the UI via signals.
- **Widgets never import each other** — they subscribe to StateManager signals. Only MainWindow (controller) writes to StateManager.
- **Plan before coding** — make a plan before fixing bugs. The workflow must be in the plan.

### Documentation Is Part of the Change
- **Every code change must include a docs check.** When you edit code, fix a bug, or add a feature, ask: "Which docs describe this behavior?" and update them in the same commit or push. Stale docs are bugs.
- Docs live in `docs/` (Diátaxis: tutorials, how-to, reference, explanation), `README.md`, `CLAUDE.md`, and `debian/changelog`.
- If you add a card type, update `docs/reference/card-types.md`. If you change CLI flags, update `docs/reference/cli-integration.md`. If you change auth flow, update `docs/explanation/architecture.md`. If you change install behavior, update `docs/how-to/install.md`. No exceptions.
- `debian/changelog` and `version.py` must be bumped together for every release.
- This is not optional cleanup — it is part of "done".

### Safety Rules
- **Safety first**: Confirm ICCID matches before ADM1 auth. A mismatch = wrong ADM1 = card bricked after 3 fails.
- **ICCID is read-only for non-empty cards** (factory traceability). Only written on blank cards.
- **Good checks everywhere**: e.g. confirm ICCID read from card matches data in file before any ADM1 operation

### Modularity — File Formats and Parsers
- The codebase already supports multiple input formats: CSV (`csv_manager.py`), EML/email (`utils/eml_parser.py`), and whitespace-delimited TXT.
- Each parser is self-contained. Adding a new format (e.g. XLSX, XML) should be a matter of writing one new parser module that returns the same `list[dict]` structure. If it isn't that easy, the abstraction is leaking and needs fixing.
- The **SIM standard** (IMSI ranges, ICCID ranges, SPN, LI, FPLMN defaults per site) is currently defined as `standards.json` on the network share. Future direction: migrate to a **Markdown document** (`sim-standard.md`) — human-readable prose and tables at the top, a fenced JSON block at the bottom for SimGUI to parse. One file that serves as both documentation and configuration. This would enable richer validation — e.g. dropdown menus in batch programming for IMSI ranges, ICCID ranges, site codes, and FPLMN per country.
- Think modular: card types, file formats, validators, and standard definitions should all be pluggable.

### What We Welcome
- Improvement ideas and robustness hardening
- Architecture considerations and refactoring proposals
- Testing strategies — how to test edge cases, what to mock, what to integration-test
- Future ideas and extensions (document them in `docs/TODO.md`)

### Lessons Learned (the hard way)
- `--noprompt` in pySim-shell silently breaks stdin piping — commands are ignored (pySim-shell is now auth-only via `_run_pysim_shell_safe`; writes go through pySim-prog)
- pySim-shell returns exit code 0 on APDU failures — you MUST scan stdout for errors
- `exit` doesn't work in pySim-shell — must use `quit`
- Blank gialersim cards use CHV 0x0C, not 0x0A — standard VERIFY burns retry attempts
- Reader contention (CardWatcher polling during operations) causes random 6f00 errors
- Double authentication (verify_adm in piped commands + -A flag) silently fails
- ADM1 format varies by file source — always detect by length (16=hex, ≤8=ASCII)
- Tests that mock implementation details and assert them back are tautological — test observable behavior instead
- pySim-read does not support `-t` flag — auto-detection works without it
- pySim-read outputs FPLMN as a multi-line block with tab-indented entries
  in format `\t42f010 # MCC: 240 MNC: 01` — parser must handle this
- FPLMN key line has empty value after colon — must set in_fplmn_block=True
  before the `if not val: continue` check fires
- ADM1 Left cannot be read for gialersim cards — CHV 0x0C counter not
  accessible via standard VERIFY-no-data APDU (shows as `-`, acceptable)
- gialersim cards are incompatible with 5G SA networks using 5G-AKA — Magma with `enable5gFeatures: true` sends `xresStar`/`kseaf` auth vectors that gialersim cannot compute. Use SJA5 cards for 5G SA deployments.
- pcscd must be installed as a system dependency — was missing from install.sh, causing "No card reader detected" on fresh Ubuntu installs. Fixed in v0.5.27.
- After dismissing "No card reader" popup and connecting a reader, the status label now refreshes to "Insert a SIM card..." via the `on_reader_ready` CardWatcher callback. Fixed in v0.5.28.
- `_original_card_data` sentinel: `None` = no card detected, `{}` = blank card detected. Never confuse the two — `authenticate()` returns False for `None` (no card), but succeeds (blank path) for `{}`.
- `detect_card()` retries pySim-read once after 1 s on "protocolerror" — transient PCSC lock contention clears within 1 s.
- Blank gialersim cards have no ICCID — hardware tests must NOT assert `"ICCID" in card_info`; assert `card_type != UNKNOWN or card_info` instead.
- Always verify ALL related changes are complete before committing — e.g. renaming a flag requires updating every reference across all files before pushing, not just the primary location.
- pyscard module-level cache (`_pyscard_available`) is set once and persists for the process lifetime — if pcscd is not running at app startup, the cache is set to `False` and never re-evaluated. Solution: add a `reset_pyscard()` function to clear the cache and force re-import. CardWatcher calls this periodically when no reader is detected, enabling automatic recovery when pcscd/USB becomes available. Fixed in v0.5.36.
- UTM USB passthrough auto-connect doesn't work reliably on macOS — with auto-connect enabled, the reader attaches at VM boot, but if unplugged/replugged during use, it won't re-attach automatically. User must toggle in UTM's USB menu. A systemd monitoring service (`smartcard-hotplug-monitor.service`) detects when the reader reappears and sends a desktop notification. This is a UTM/QEMU limitation, not fixable at the application level without requiring users to modify QEMU settings (which breaks vanilla install requirement). Documented in `docs/how-to/install.md`.
- Toast notifications should track state to prevent repeated display on every poll cycle — when CardWatcher polls at 1.5s intervals and encounters the same error repeatedly, naive toast display creates popup spam. Solution: add a flag (e.g., `_no_reader_toast_shown`) that is set when the toast is shown and reset only when the error condition clears. For dismissal, store the returned Toplevel widget from `show_toast()` and programmatically destroy it when the condition resolves (e.g., when reader is detected). Fixed in v0.5.36.

## StateManager Signal Architecture

```
StateManager (QObject)
├── card_state_changed(CardState)     # NO_CARD → DETECTED → AUTHENTICATED
├── card_info_changed(CardInfo)       # ICCID, IMSI, card_type, etc.
├── mode_changed(AppMode)             # HARDWARE ↔ SIMULATOR
├── status_changed(str)               # Status bar text
├── share_status_changed(ShareStatus) # Network mount state
├── csv_path_changed(str)             # Active CSV file
├── batch_running_changed(bool)       # Batch lock
├── card_programmed(dict)             # Triggers auto-artifact
├── iccid_index_updated()             # After rescan
├── toast_requested(str, str, int)    # UI notifications
└── error_occurred(str)               # Non-fatal errors
```

Pattern: Manager does work → MainWindow updates StateManager → Signal fires → Widgets react.
Widgets NEVER call managers directly. They read StateManager properties and react to signals.

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

## Project Stats

- Started: 2026-02-28
- ~48 hours of development across 14 sessions over 21 calendar days
- 12,600+ lines of application code, 2156+ tests
- 100+ commits, versions v0.1.0 through v0.5.30
