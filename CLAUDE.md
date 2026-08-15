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

### Programming Flows (routed by card type in `program_card`)
- **Gialersim cards → NATIVE (v0.8.0)**: Programmed by `managers/gialersim.py`
  via pyscard directly — **pySim is bypassed entirely**. pySim's `GialerSim`
  class writes Ki/OPc in UICC class (`CLA=00`) and omits the algorithm config
  (`EF 2FE5`/`2FE6`), so its writes return `9000` but never commit and the SIM
  fails Milenage auth (MAC failure `9862`). The native path uses GSM class
  (`CLA=A0`, SELECT `P2=00`), VERIFY ADM at ref `0x0C` with the **fixed family
  key `84796153`** (NOT the CSV ADM1), and writes all ADM-gated files
  (key-definition files, Ki, OPc, algorithm config, ICCID) with MF current and
  **no DF reselect**, then IMSI/ACC in `DF_GSM`. Writes ICCID/IMSI/Ki/OPc/ACC;
  **SPN/FPLMN are not in the verified recipe and are not written**. See
  `docs/GIALERSIM_PROGRAMMING.md` and `TODO(gialersim-spn-fplmn)`.
- **Non-gialersim empty/blank cards**: Use `pySim-prog` (full write of all
  non-empty fields in a single invocation).
- **Non-empty cards (SJA5/SJA2)**: Use `pySim-shell` for field writes
  (delta-write — only changed fields). Authenticate first via
  `pySim-shell -A <hex_ADM1>`, then write fields via pySim-shell commands
  (select, update_binary_decoded). ICCID is factory-assigned and excluded from
  writes. **These sysmocom paths are unchanged and must stay that way.**
- **NEVER** use `-t auto` for gialersim (not that it matters now — gialersim
  never touches pySim; `-t auto` would cause CHV 0x0A VERIFY which fails 6f00).
- **NEVER** change ICCID on non-empty cards.
- Ki and OPc share the same EF — if either changes, both are written together.
- **`9000` on a Ki write proves NOTHING** — Ki/OPc are READ=NEVER; positive
  confirmation needs an offline USIM AUTHENTICATE self-check
  (`TODO(gialersim-selfcheck)`).

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

### pySim-prog (non-gialersim empty cards)
> Gialersim cards do NOT use pySim-prog — they are programmed natively (see
> `managers/gialersim.py` and `docs/GIALERSIM_PROGRAMMING.md`). pySim-prog is
> used only for non-gialersim blank cards.
```bash
pySim-prog.py -p 0 -a <ASCII_ADM1> -s <ICCID> -i <IMSI> -k <Ki> --opc <OPc> -n <SPN> --acc <ACC> -x <MCC> -y <MNC>
```
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

**This patch is applied automatically after every pySim clone** by both
`scripts/install.sh` (Ubuntu) and `scripts/install-macos.sh` (macOS), idempotent
and marker-guarded. It is retained for any residual pySim use, but note that
gialersim SPN is not written at all now (native path omits it — see
`TODO(gialersim-spn-fplmn)`).

## Native GialerSim Programming (v0.8.0) — pySim is bypassed

**File:** `managers/gialersim.py` (framework-free, pyscard directly).

**Why native.** pySim's `GialerSim` class writes Ki/OPc in **UICC class**
(`CLA=00`, SELECT `P2=04`) and never writes the algorithm config (`EF 2FE5`,
`2FE6`). On these cards every APDU returns `9000`, yet the key writes are
silently discarded and the SIM fails Milenage auth (MAC failure `9862`). Two
independent defects, both fatal:
1. **Wrong class byte** — key writes only *commit* in **GSM class** (`CLA=A0`,
   SELECT `P2=00`).
2. **Missing algorithm config** — `EF 2FE5`/`2FE6` bind an algorithm to the key
   set; without them `AUTHENTICATE` fails no matter how correct the Ki is.

**The verified recipe** (USB-captured from GRSIMWrite, hardware-verified
2026-08-13 — full APDU listing in `docs/GIALERSIM_PROGRAMMING.md`):
1. VERIFY ADM ref `0x0C` = **`84796153`** (fixed family key, NOT the CSV ADM1;
   no SELECT MF first — MF is implicit after reset).
2. key-definition files `0100`/`0200`/`0B00` (verbatim).
3. Ki → `MF/0001`.  4. OPc → `MF/6002` (`01` prefix).
5. algorithm config `2FE5` + `2FE6` records.  6. ICCID → `MF/2FE2`.
7. **only now** descend DF: IMSI → `7F20/6F07`, ACC → `6F78`.

**Order is load-bearing:** steps 2–6 run with MF current and **no DF reselect** —
selecting a DF drops the ADM security state, after which every ADM-gated UPDATE
returns `9000` but is silently discarded. Abort on any non-`9000` for a recipe
step; **never treat `9000` on a Ki write as success**.

**ADM clarification:** the credential at `0x0C` is `84796153`. The
`88888888`/`3838383838383838` value is the *contents* of key file `0B00`, not a
second credential — the earlier "dual-ADM 0x0B" hypothesis (v0.7.3) was a **red
herring** and has been removed from the install scripts and the reference
snapshot.

**Verification:** Ki/OPc are READ=NEVER (EF_ARR `0x13`); a `9000` proves
nothing. ICCID/IMSI are confirmed by read-back; positive key confirmation
requires an offline USIM AUTHENTICATE self-check (`TODO(gialersim-selfcheck)`,
reference: `~/projects/sim_snippet/auth_validate_harness.py`).

**Routing:** `CardManager.program_card()` routes `CardType.GIALERSIM` to
`_program_gialersim_native()` (a thin adapter) → `managers/gialersim.py`.
Non-gialersim empty cards still use pySim-prog; non-empty cards still use
pySim-shell. sysmocom (SJA5/SJA2) paths are untouched.

## Testing

- Framework: pytest
- Active Ubuntu baseline: **1900 passed, 0 failed, 313 skipped** (post simulator removal, Commits 1–9)
- See `docs/reference/test-baseline-ubuntu-post-simulator-removal.md` for the authoritative count.
- Prior counts (2123, 2051) are historical — do not use them as the current regression guard.
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
- **No blocking on the event loop** — Any I/O, network, or filesystem work must run in a `QThread` worker, not on the main thread. Workers emit signals; slots update StateManager. Never use `time.sleep()`, blocking subprocess calls, or loops on the main thread. The GUI must stay responsive.
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
- PyInstaller bundles Python 3.9 but codebase initially used Python 3.10+ union type syntax (`X | Y`) — all type annotations must use `typing.Optional` and `typing.Union` for compatibility. Fixed in v0.5.37.
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
- Blocking I/O on event loop freezes the UI — Initial implementation of background startup tasks used `QTimer.singleShot(0, lambda: blocking_work())`. This schedules blocking work on the main thread, freezing the UI. Solution: use `QThread` worker pattern (v0.5.38). Worker class emits signals, main window connects them to slots. Slots call StateManager methods. No lambdas with direct state manipulation, no blocking on event loop. See `docs/explanation/architecture.md` for the pattern.

## Platform Refactoring Ground Rules

These rules are non-negotiable. They apply to every task, every commit, and every agent
that touches this repository. They exist because macOS work in versions after v0.5.50
accidentally broke Ubuntu application logic, requiring a full rollback.

### The Baseline

**Rule 1 — Ubuntu behavior is the baseline; active test-count guard is post-simulator-removal.**
Ubuntu application behavior as shipped in v0.5.50 is correct and must be preserved exactly.
Any change that alters Ubuntu card programming behavior, authentication behavior, or state
transitions is invalid — regardless of how useful it might be for macOS. There are no
exceptions.

The active Ubuntu test-count regression guard is **1900 passed, 0 failed, 313 skipped**
(recorded after simulator-removal Commits 1–9). Any future Ubuntu run that drops below this
count without an approved explanation is a regression and must be reverted. The historical
counts (2123 passed at `v0.5.54-post-qt-main-baseline`, 2051 passed at v0.5.50) are
preserved in their respective baseline documents but are superseded by
`docs/reference/test-baseline-ubuntu-post-simulator-removal.md`.

### Common Logic Must Stay Common

**Rule 2 — Common logic must remain common.**
Business logic, state transitions, SIM programming logic (card detection, authentication,
programming flows), CSV parsing, and network-share mount logic must NOT be duplicated
across platforms. If two platforms need the same behavior, that behavior lives in exactly
one shared location.

**Rule 3 — Only true platform-specific behavior may be split.**
Platform-specific code is limited to: filesystem paths, packaging conventions, permissions
models, process invocation differences (e.g. pySim path resolution), UI integration
differences (e.g. macOS-specific Qt quirks), or OS-specific dependency handling (e.g.
`pcscd` vs `PCSC.framework`). If you are considering splitting something that does the
same thing on both platforms, it must stay common.

**Rule 4 — Do not duplicate the following across platforms under any circumstances:**
- Business logic
- State transitions (`CardState`, `CardWatcher`, `StateManager`)
- SIM programming logic (`_program_via_pysim_prog`, `_run_pysim_prog`, delta-write vs full-write)
- Card detection logic (`detect_card`, `probe_card_presence`, `_parse_pysim_output`)
- Authentication logic (`authenticate`, `check_adm1_retry_counter`, ADM1 format handling)
- CSV parsing and network-share logic (`csv_manager.py`, `network_storage_manager.py`)

**Rule 5 — Platform-specific code must be thin adapters only.**
An adapter wraps one call, translates one path, or handles one import difference. It must
not contain SIM card logic, state machine logic, ADM1 handling, or any business rule. If
an adapter is growing complex, the abstraction is wrong — stop and redesign.

**Rule 5a — No new platform branching in `card_manager.py` or `card_watcher.py`.**
These files are platform-free. The only permitted platform-specific code in
`card_manager.py` is the already-existing `_find_cli_tool()` path lookup adapter. No
platform branching (`if sys.platform`, `if _MACOS`, `if darwin`, etc.) is allowed inside
SIM logic, authentication logic, card detection logic, programming flows, or state
transitions in either file — without exception.

### The State Machine Is Holy

**Rule 6 — `docs/reference/state-machine.md` is authoritative.**
Every state, every transition, and every invariant defined in `state-machine.md` is a hard
constraint on the implementation. Nothing may contradict it. Read it before touching any
state-related code.

**Rule 7 — Check `state-machine.md` before touching logic or state.**
Before writing any code that involves `CardState`, `CardWatcher`, `StateManager`, card
detection, authentication, or programming flows, re-read `state-machine.md` and confirm
the change conforms to every relevant invariant.

**Rule 8 — If code and `state-machine.md` disagree, stop and report.**
Do not guess. Do not silently pick one. Do not paper over the conflict. Report: "Code at
`<file>:<line>` does `<X>`; `state-machine.md` says `<Y>`. These conflict." Then stop and
wait for explicit resolution. Only after the conflict is resolved in writing may coding
continue.

### Refactoring Process

**Rule 9 — Ubuntu baseline must be verified before adding macOS support.**
The mandatory sequence for any platform refactor is:
1. Confirm all Ubuntu tests pass unchanged on the current baseline.
2. Extract shared logic (no behavior change — tests must still pass).
3. Add the platform adapter.
4. Add macOS-specific tests.

Never add macOS support before the Ubuntu baseline is verified. Never combine steps.

Test baselines must be platform-labelled. A test run on macOS is a macOS baseline only;
it does not substitute for the authoritative Ubuntu baseline. The production baseline that
must be protected first is Ubuntu v0.5.50. Any baseline document must state the exact
platform and OS version it was recorded on.

**Rule 10 — Small, reviewable commits; tests after every behavioral change.**
No large combined refactor+feature commits. Each commit must be independently
understandable and verifiable. Run the full test suite (`python3 -m pytest tests/ -x -q`)
after every commit that touches behavior. No opportunistic changes: do not fix unrelated
bugs, rename variables, clean up formatting, or add features in a refactoring commit.
One concern per commit.

### Quarantine Zones

**`qt_main.py` has been permanently removed (v0.5.53).**
This file was a Phase 0 stub with a Python syntax error. It was never an entry point for
any platform. It has been deleted from the repository and removed from `debian/rules`.
Do not reintroduce it. `main.py` is and remains the only canonical entry point.

**Post-v0.5.50 git history is tainted.**
All commits, branches, and tags after v0.5.50 were rolled back because macOS work
accidentally broke Ubuntu application logic. Use post-v0.5.50 history only for forensic
comparison — never as a source of logic to copy. If a post-rollback branch is needed for
reference, use `backup-before-rollback-0.5.50` (if present), `git reflog`, or `dist.old/`.
Do not import any logic from those versions without explicit written approval.

**`main.py` is the canonical entry point for all platforms.**
Both Ubuntu and macOS run `python3 main.py`. No other entry point is authoritative.

### Forensic Guardrails (Phase 4)

These prohibitions are derived from `docs/reference/post-v0.5.50-forensic-report.md`,
which documents the exact change categories that broke Ubuntu in the tainted history.
They are concrete, unconditional rules — not guidelines.

**Prohibition 1 — No mandatory top-level platform runtime imports in common modules.**
Do not add `from platform_runtime import …` or any equivalent at the top level of
`card_manager.py`, `card_watcher.py`, `network_storage_manager.py`, `csv_manager.py`,
or any other shared manager module. A module-level import that fails on Ubuntu kills
every test that touches the importing module. Any platform runtime abstraction must be
optional (checked with `try/except ImportError` or guarded by a flag) or locally imported
inside the one function that needs it — never at module scope in a common file.

**Prohibition 2 — No shadow state machines.**
Do not create a parallel card-detection algorithm (`_macos_check_with_pysim()` or
equivalent) alongside the standard `CardWatcher` detection path. There is exactly one
card detection algorithm. macOS-specific constraints (PCSC contention, no-ATR probe,
settle delays) must be expressed as constructor parameters or narrowly-scoped adapter
calls that feed the same state machine — not as a second algorithm that redefines
removal semantics and runs on a separate code path.

**Prohibition 3 — Do not reimplement card detection outside `CardWatcher`.**
All card presence, card removal, and card-type detection logic lives in `CardWatcher`
and `CardManager.detect_card()`. Do not add detection loops, cooldown counters, or
fail-streak trackers anywhere else. If the existing detection path cannot accommodate
a platform constraint, fix the existing path — do not bypass it.

**Prohibition 4 — Do not bypass `state-machine.md`.**
This is a restatement of Rules 6–8, added here because the tainted history shows that
state-machine violations were introduced incrementally (one commit introducing them, the
next "fixing" two of them) without ever resolving all of them before rollback. The
correct response to discovering a state-machine violation is to stop coding and report —
not to issue a follow-up commit that fixes some violations while leaving others open.

**Prohibition 5 — No platform branches inside `card_watcher.py`.**
This is a restatement of Rule 5a, added here as a Forensic Guardrail because
`card_watcher.py` was the file most changed by the tainted history (new `sys.platform`
branches, new instance variables initialised on all platforms, new dispatch logic). The
file must remain a platform-free implementation of the state machine.

**Prohibition 6 — Do not partially fix known state-machine violations.**
If a code change introduces a state-machine violation, the commit that introduces it
must not be pushed. If a violation is discovered in an already-pushed commit, stop all
further work on that branch and report the violation with the exact file, line, and
conflicting `state-machine.md` invariant. Do not push a follow-up "fix two violations"
commit and continue as if the issue is resolved. Partial fixes mask the true scope of
the problem and leave the codebase in an unknown state.

**Prohibition 7 — Any macOS runtime abstraction must be optional, thin, and Ubuntu-safe.**
If a `platform_runtime.py` (or equivalent) module is introduced in a future phase:

- It must be imported locally (inside the one function that needs it), not at module scope.
- It must return correct Linux/Ubuntu values on Ubuntu — verified by the Ubuntu test suite.
- It must not change any hardcoded Linux path (e.g. `/tmp/simgui-mounts`,
  `~/.config/simgui`) without verifying that the new value is identical to the original
  on Linux.
- Its test suite must include Ubuntu-path assertions, not only macOS-path assertions.
- Ubuntu imports of all common modules must succeed without it being present.

---

## StateManager Signal Architecture

```
StateManager (QObject)
├── card_state_changed(CardState)     # NO_CARD → DETECTED → AUTHENTICATED
├── card_info_changed(CardInfo)       # ICCID, IMSI, card_type, etc.
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

**Primary (native macOS) — v0.5.37+:**
- MacBook Air M4, macOS 26.4.1
- USB Reader: HID Global OMNIKEY 3x21 (direct USB, no VM)
- pySim installed at `~/pysim` or via `PYSIM_PATH` env var (optional)
- Uses macOS built-in `PCSC.framework` — no daemon installation needed
- SimGUI runs from source: `python3 main.py` (PyInstaller bundle in progress)
- Distribution: Source-based for now; `.pkg` blocked by image asset loading issue
- **Status (v0.5.37)**: Python 3.9 compatibility fixed; all imports work; PyInstaller bundle crashes on GUI init due to tkinter PNG loading from temp directory (see docs/TODO.md)

**Legacy (Ubuntu via UTM):**
- MacBook Air M4 → UTM VM → Ubuntu (ARM/aarch64)
- USB Reader: HID Global OMNIKEY 3x21 (USB passthrough to VM)
- pySim installed at `/opt/pysim` with `.venv`
- pcscd service (systemd) required for PCSC reader access
- SimGUI installed as `.deb` package

## Project Stats

- Started: 2026-02-28
- ~48 hours of development across 14 sessions over 21 calendar days
- 12,600+ lines of application code, 2156+ tests
- 100+ commits, versions v0.1.0 through v0.5.30

## UI Refactor Mode (Token Efficiency Override)

When working on UI/layout tasks:

### Scope Control (CRITICAL)
- Only operate on the file explicitly provided in the prompt
- Do NOT search the repository
- Do NOT scan or explore other files
- Do NOT select files automatically
- If a file is specified, ignore all other files completely

### Task Focus
- Treat each task as fully self-contained
- Do NOT infer dependencies unless explicitly stated
- Do NOT modify other panels or widgets unless instructed

### Output Rules
- Default to minimal diff output only
- Do NOT include long explanations unless explicitly requested
- Prefer direct code changes over analysis

### Layout Guidelines
- Prefer QGridLayout over deep QVBoxLayout nesting
- Avoid QScrollArea unless explicitly required
- Use horizontal space before adding vertical height
- Keep layouts compact and aligned (macOS-style density)

### Safety Rule (UI)

- Never modify state handling, signals, or logic when doing layout work
- If layout changes affect behavior, stop and preserve original behavior

### Layout Stability Rule

- Never compress UI to the point of text truncation
- Always ensure minimum usable width for inputs and labels
- Balanced layouts are preferred over maximum density
