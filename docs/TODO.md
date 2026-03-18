# SimGUI — TODO / Backlog

## Test Quality Audit

- [ ] **Audit tests for "tautological assertions"** — tests that only verify the code
  does what it does, rather than validating it does the *right* thing.
  - Example: `test_safe_shell_includes_noprompt` asserted `--noprompt` was in the
    command — matching the broken implementation. A correct test would have validated
    that piped stdin commands are actually processed by pySim-shell.
  - Example: `test_check_sudo_mount_uses_absolute_paths` asserted the subprocess
    call included `/usr/bin/mount`, but never checked whether the probe command
    (`mount --help`) actually matched the sudoers NOPASSWD rule pattern.
  - **Pattern to watch for**: any test that mocks the exact implementation detail
    and asserts it back, rather than testing observable behavior or contract.
  - Priority: medium — these tests give false confidence and mask real bugs.

## Completed (v0.5.18–0.5.20)

- [x] Detect pySim-shell APDU errors (SwMatchError/6f00) even on exit code 0
- [x] Eliminate double ADM1 authentication during programming
- [x] ADM1 format detection by length (16=hex, ≤8=ASCII)
- [x] Blank card safety — skip VERIFY ADM1 on unpersonalised cards
- [x] Gialersim card type auto-detection and programming support
- [x] `-t gialersim -a` flag routing in `_run_pysim_prog()`

## Future Improvements

- [ ] **REFACTOR: Unify all card programming through pySim-prog** — Currently there are two write paths: `_program_empty_card()` uses pySim-prog for core fields, then calls `_program_nonempty_card()` (pySim-shell) for "extra fields" like FPLMN. This split is the root cause of gialersim auth failures on FPLMN writes and adds unnecessary complexity. **pySim-prog already supports ALL the fields we need** — including `-f` for FPLMN — and handles auth correctly per card type (`-t gialersim -a` vs `-A`). It also works on non-empty cards, not just blank ones. **Refactor:** (1) Add `-f` FPLMN flag(s) to `_run_pysim_prog()`, (2) Route ALL programming (empty AND non-empty) through pySim-prog as the single write engine, (3) Eliminate `_program_nonempty_card()` as a write path — keep pySim-shell only for reads and interactive commands, (4) Remove the `_PYSIM_PROG_FIELDS` / extra_fields split entirely. One tool, one auth path, one invocation, all card types, all fields. Priority: HIGH — this is a modularity and reliability improvement that eliminates an entire class of card-type-specific auth bugs.

- [ ] **SIM standard as Markdown** — Replace `standards.json` with a version-controlled Markdown document (e.g. `sim-standard.md`) defining the Teleaura SIM PLMN Numbering Standard. The top of the document is human-readable prose and tables (site register, IMSI structure, ICCID structure, FPLMN per country). The bottom contains a fenced JSON block (`\`\`\`json ... \`\`\``) with the machine-parseable data — SimGUI parses only that block. This way the document is readable, diffable, and version-controlled, while SimGUI gets structured data without a separate file. Should include: IMSI range allocations per site, ICCID range allocations, SPN canonical values, LI values, FPLMN defaults per country, and site register. Enables richer UI: dropdowns in batch programming for IMSI ranges, ICCID ranges, site codes, and country-based FPLMN defaults.

- [ ] **ICCID mismatch override for blank cards** — Currently, ICCID cross-verification aborts authentication when the card's ICCID doesn't match the CSV row. This blocks blank card programming because blank cards have a factory ICCID (e.g. `8901901557518313028`) that differs from the target ICCID in the CSV (the one to be written). For blank/gialersim cards this check is wrong — the whole point is to *overwrite* the ICCID. Fix: allow an override ("I know what I'm doing") for blank cards. The safety argument is weaker here because all Fiskarheden blank cards share the same default ADM1 (`3838383838383838` / `88888888`), so a mismatch doesn't risk locking the wrong card. Consider: auto-skip the check when `card_type == GIALERSIM`, or show a confirmation dialog instead of a hard abort.

- [ ] **Batch programming: Site Code and SPN not populated** — The Batch Preview table shows Site Code and SPN columns, but they are empty when loading files like `uk1_100_sims.txt` that don't contain these fields. Currently there is no way for an operator to enter or configure them in the batch UI. Two approaches to consider:
  1. **Auto-populate from `sim-standard.json`** — Parse the ICCID's SSSS (site code) field and look up the site in the standard to derive the Site Code label and SPN value automatically. E.g. ICCID `8999988000100000019` → SSSS=`0001` → site `uk1` → SPN `Teleaura UK`.
  2. **Manual entry in batch panel** — Add input fields or dropdowns in the batch panel header (alongside Start Row / Count) for Site Code and SPN that apply to all rows in the batch.
  Approach 1 is preferred (less manual work, uses the standard as source of truth). Ties into the "SIM standard as Markdown" item above — richer standard data enables richer auto-population. Also consider: LI (language) and FPLMN defaults per site/country from the standard.

- [x] **FIXED v0.5.23: Support SPN and FPLMN columns in CSV/TXT import files** — Added `SPN` and `FPLMN` to `STANDARD_COLUMNS` in `csv_manager.py` with normalization entries (`spn`, `fplmn`, `service_provider_name`, `forbidden_plmn`). Write handlers already exist in `card_manager.py`. Added FPLMN column to Batch Preview Treeview. Added SPN and FPLMN manual override input fields in the CSV-mode batch panel header — operator input overrides CSV values. Settings persistence for both fields.

- [ ] **Reader-agnostic: auto-detect and select USB smartcard reader** — The app should work with any PCSC-compatible smartcard reader, not just OMNIKEY 3x21. Two phases:
  1. **Auto-detect first available reader** — On startup and when no reader is connected, scan for available PCSC readers and automatically connect to the first one found. Show the reader name in Card Status or status bar. If no reader is found, show a clear message ("No smartcard reader detected — connect a USB reader").
  2. **Reader selection UI** — If multiple readers are connected, allow the operator to choose which one to use. Location: **Settings dialog** (accessible from a menu bar — Help → Settings, or a dedicated Settings menu). Show a dropdown of available readers, with the current selection highlighted. Reader change should be hot-swappable (no app restart). Also consider: a "Refresh" button to rescan for readers, and remembering the last-used reader in settings.
  - Currently CardWatcher uses `pyscard` and pySim uses `-p 0` (reader slot 0). The reader index may need to be configurable and passed through to all pySim commands.
  - Should also handle reader disconnect gracefully (USB removed mid-session) — show a warning, pause batch if running, and resume when reconnected.
  - **Confirmed working readers**: OMNIKEY 3x21 (HID Global), Realtek 0bda:0165 (cheap Amazon USB reader). Both work via PCSC passthrough in UTM VM.
  - Consider: detect if reader is read-only vs read/write capable and warn the operator if a read-only reader is connected when programming is attempted.

- [ ] **Remove standalone ADM1 Authenticate button** — The separate "Authenticate" step in the Program SIM panel is unnecessary and confusing for operators. ADM1 authentication happens automatically when programming, so the button adds an extra step with no value. **Exception:** keep an authenticate action if there are protected fields that require ADM1 to *read* (e.g. Ki, OPc read-back). If read-back is the only use case, rename to "Read Protected Fields" or similar. The goal: operators should go from card-detected → program in one click, not card-detected → authenticate → program.

## Critical Bugs (Batch Programming)

- [x] **FIXED v0.5.21: ATR-based ICCID caching breaks batch for blank cards** — All blank gialersim cards share the same ATR. After Card 1 is programmed, its ICCID was cached against that ATR. Card 2 (same ATR) was misidentified as Card 1. **Fix**: `_atr_iccid_cache.clear()` in both card-removal paths of `card_watcher.py` (`_handle_probe_result` and `_check_once_slow`).

- [x] **FIXED v0.5.21: ADM1 retry counter burned during auto-read** — `detect_card()` was calling `check_adm1_retry_counter()` which sends a VERIFY APDU, consuming attempts on gialersim cards (CHV 0x0C vs 0x0A mismatch). Fresh blank cards showed only 1 remaining attempt. **Fix**: removed ALL `check_adm1_retry_counter()` calls from `detect_card()`. Retry counter is checked lazily in `authenticate()` only.

- [x] **FIXED v0.5.21: Authenticate + Program Card double-gate** — User forced past low-retry warning in Authenticate, but `program_card()` independently re-checked and blocked again. **Fix**: added `_safety_override_acknowledged` flag — set by `authenticate(force=True)`, checked by `program_card()`, cleared by `disconnect()`. Override carries forward.

- [x] **FIXED v0.5.21: ICCID index not updated after programming** — After programming, re-inserting the card showed "not in index" because the index had no API to add a single ICCID. **Fix**: added `IccidIndex.add_iccid(iccid, file_path)` method, called from `main.py:_on_card_programmed()` after artifact save.

- [x] **FIXED v0.5.23: FPLMN not programmed on gialersim — pySim-shell ADM1 auth fails after pySim-prog** — Root cause: `_run_pysim_shell_impl()` used `-A <hex>` (standard VERIFY) for all card types, but gialersim cards need `-t gialersim -a <ascii>` (like pySim-prog). Fix: `_run_pysim_shell_impl()` now detects `card_type == GIALERSIM` and passes `-t gialersim -a <ascii_adm1>` instead of `-A <hex>`. This applies globally to all pySim-shell uses (programming, read-back, detect_card).

- [x] **FIXED v0.5.23: SPN shows "Not available" after programming** — Root cause: `verify_after_program()` called `pySim-read.py -p0` without card type, so pySim-read couldn't locate EF_SPN on gialersim cards. Fix: passes `-t gialersim` to pySim-read when `card_type == GIALERSIM`, enabling SPN read-back.

- [x] **FIXED v0.5.23: PIN1/PUK1/PIN2/PUK2 skipped silently** — Fields without write handlers were logged but not visible to the operator. Fix: `_program_nonempty_card()` now collects skipped field names and appends them to the return message as a visible warning (e.g. "Warning: skipped fields (no write handler): PIN1, PUK1").

- [x] **FIXED v0.5.22: Batch programming does not warn when ICCID was already programmed** — Injected `iccid_index` into `BatchProgramPanel` and added `_check_iccid_index_duplicates()` pre-batch check. Logs a warning for each ICCID already in the index (non-blocking, warns but doesn't prevent).

- [x] **FIXED v0.5.22: Batch programming: no per-card artifact for 2nd+ card** — Injected `auto_artifact_manager` into `BatchProgramPanel`. Added `_save_per_card_artifact()` called from `_on_card_result()` on each successful card. Also updates `iccid_index` per card. Independent of the single-card `_on_card_programmed()` flow (which is untouched).

- [x] **FIXED v0.5.22: Batch programming: no batch-level artifact file** — Added `save_batch_summary()` to `AutoArtifactManager` and `_save_batch_summary()` to `BatchProgramPanel`. Auto-saves a `batch_summary_YYYYMMDD_HHMMSS.csv` to all connected shares when batch completes. Includes all cards (success and failure), reuses `get_programmed_records()`.

- [x] **FIXED v0.5.22: Batch artifact file — verify it is saved** — Per-card artifacts are saved for each successful card. Batch summary CSV includes both successes and failures for full traceability.

- [x] **FIXED v0.5.24: ICCID index points to latest artifact when card is reprogrammed** — When a card is re-programmed, multiple artifact files exist for the same ICCID. Previously `add_iccid()` found the ICCID already indexed and only evicted the cache without updating `file_path`. **Fix**: `add_iccid()` now updates single-card entries' `file_path` in place; for range entries, appends a new override entry. `lookup()` now returns the last matching entry (most recent) instead of the first. Combined with `scan_directory()` processing files in sorted filename order (timestamps sort chronologically), the latest artifact always wins.

## Process Retrospective — CLAUDE.md Enhancement Plan

Estimate: +50% of bugs could have been avoided with a better CLAUDE.md and an early architecture/planning session. The following categories capture what was missing and what should be encoded as permanent project knowledge to prevent repeat mistakes.

### 1. Early Architecture & Planning Decisions

These questions should have been asked and answered ONCE in an upfront session, not discovered through trial and error across many sessions:

- [ ] **Packaging & distribution** — How should the app be packaged? What should be included (dependency installation, pySim bundling, pcscd setup)? Linux only or cross-platform? x86-64 only or also aarch64? This was resolved late and painfully.
- [ ] **PyQt6 should have been proposed early** — The migration from Tk to PyQt6 came mid-project. A Q&A at the start ("What UI framework? What platforms? What form factors?") would have avoided weeks of rework. CLAUDE.md should include a **Technology Choices** section documenting the rationale for PyQt6, Ubuntu, .deb, etc. — and the Q&A process for evaluating alternatives.
- [ ] **SIM card type research** — Gialersim cards, their CHV 0x0C auth method, and the difference from SJA5 should have been researched upfront. Instead it was discovered through failed attempts that burned ADM1 retries. CLAUDE.md now documents this, but only after the damage.
- [ ] **ADM1 hex vs ASCII** — Was treated as guesswork for too long. The rule is simple (16 chars = hex, ≤8 = ASCII) but it took multiple sessions to nail down. Should have been a Day 1 research task.

### 2. Event-Driven Architecture (Not Polling)

- [ ] **Card detection should be signal/interrupt-based, not polling** — CardWatcher polls the reader. This causes reader contention during programming (random 6f00 errors) and makes the ATR caching bug possible. Should use PC/SC event notifications or at minimum subscribe to system signals. This is an app-global concern.
- [ ] **Share mount status should use signals globally** — Share indicator was grey on startup, left pane updated but right pane didn't — because mount status wasn't propagated via signals everywhere. Pattern: if something is a global state, it must go through StateManager signals, not ad-hoc checks.
- [ ] **File scanning should be state-driven** — When a card is just programmed, removed, and re-inserted, it's obvious an artifact file exists. Don't re-scan the network share; use a signal/state (`card_programmed → artifact_exists`). Avoid continuous polling when state is already known.

### 3. Global Consistency (Not Per-Tab Fixes)

- [ ] **"Only in Program SIM tab?" problem** — Auth, card status, SPN, FPLMN — features were implemented in one tab but not others. CLAUDE.md says "think globally" but this was violated repeatedly. Every feature must be evaluated: "Does this apply to other tabs/panels?" If yes, implement via StateManager signal, not widget-local code.
- [ ] **Inconsistency between tabs** — No way to input SPN in batch programming. Should SPN come from CSV, manual input, or the standard? This inconsistency comes from not designing the data flow holistically. CLAUDE.md should document the canonical data source priority: CSV file → sim-standard.json → manual input.

### 4. Verify-After-Write (Always)

- [ ] **Every write must be verified with a read** — This is a fundamental principle for hardware programming. SPN was "written" but read-back showed "Not available". FPLMN was "written" but auth failed. These should have been caught immediately. CLAUDE.md should encode: **After every pySim write operation, read back and compare. If mismatch, flag as error. No silent successes.**

### 5. Workflow States & Data Integrity

- [ ] **Selecting a CSV row then inserting a card clears file data** — The card-insert event triggers a state reset that wipes the CSV selection. Workflows and states were not mapped out. CLAUDE.md should include a **State Machine** diagram showing: what triggers what, what gets cleared, what persists across card insert/remove cycles.
- [ ] **Aligned workflows with card-type variations** — The main workflow for SUCI, non-SUCI, and empty cards is the same (load data → authenticate → program → verify). Only card type detection and ADM1 handling differ. This should be one modular flow with pluggable card-type strategies, not separate code paths that diverge and get out of sync. CLAUDE.md should document this pattern.
- [ ] **Simplify by removing unnecessary steps** — The extra ADM1 verify before programming is redundant since ADM1 is provided again at point of programming. The Authenticate button adds a step with no value for gialersim cards. Simplify the operator workflow: insert card → load data → program. Fewer steps = fewer bugs.

### 6. Elegance & Silent Failures

- [ ] **No silent failures** — The whitespace CSV parser returned 0 SIMs with no warning when headers had one more field than data rows. PIN1/PUK1/PIN2/PUK2 were silently skipped. FPLMN auth failed but the overall status showed success for core fields. Every failure must be visible to the operator. CLAUDE.md should encode: **If something fails or is skipped, log it AND surface it in the UI. Never swallow errors.**
- [ ] **Elegant error handling** — The 0-SIMs case could have been handled more gracefully: "Parsed 0 rows out of 100. Possible cause: MSISDN column is empty (double-space between fields)." Give the operator actionable information.

### 7. Version & Build Visibility

- [ ] **Show version and build in the app** — For debugging and iteration tracking, the version (and ideally build/commit hash) should be visible in the app window title bar or About dialog. Currently `version.py` exists but it's not clear if it's displayed in the UI. This would have saved time in many debugging sessions ("which version are you running?").

### 8. GitHub Sync Issues

- [ ] **Minimize git sync bugs** — There have been many sync issues with GitHub (local vs remote divergence, API push conflicts). Root causes: (a) editing locally AND pushing via API creates divergence, (b) no pre-push check for remote HEAD, (c) no local `git fetch && git reset --hard origin/main` after API pushes. CLAUDE.md should encode a strict workflow: always push via API → always fetch after push → never edit local git directly. Consider adding a `scripts/push.sh` helper that handles the API push + local sync in one step.

### 9. Testing Strategy Overhaul

- [ ] **Tests were built without understanding the code** — Many tests mock implementation details and assert them back (tautological). They pass when the code is broken and break when the code is fixed. This is worse than no tests.
- [ ] **Unit tests are necessary but not sufficient** — Unit tests with mocks are good for isolated logic. But the real bugs (6f00 from reader contention, FPLMN auth failing after pySim-prog, ATR caching returning wrong ICCID) are integration/E2E bugs that no unit test catches.
- [ ] **E2E tests are a must** — Need end-to-end tests that exercise the actual pySim tools against the simulator or real cards. The built-in simulator is too high-level to catch real pySim integration issues. If the simulator wraps pySim, tests should go through pySim, not around it.
- [ ] **Test coverage must be 100%+** — Not just line coverage, but path coverage. Every card type × every operation × every error path.
- [ ] **Innovative testing** — A card programmer simulator that doesn't integrate with pySim is theater. Real integration tests should: start pySim-prog/shell → feed it commands → verify card state. Consider: a pySim test harness that uses sysmocom's PCSC emulator or a virtual smartcard.
- [ ] **CLAUDE.md should encode testing requirements** — "Every new feature must include: (1) unit tests for pure logic, (2) integration tests that exercise the real pySim CLI, (3) E2E tests that verify the full workflow from UI action to card state. Mocking is allowed for Qt/UI, NOT for pySim interaction."

### 10. CLAUDE.md as the Prevention Layer

The CLAUDE.md is already substantial (267 lines) but needs restructuring to serve as an effective prevention layer:

- [ ] **Add a "Decision Log" section** — Document every architectural decision with rationale (ADR-lite). When a decision was made the hard way, record why, so it's never revisited.
- [ ] **Add a "Pre-Implementation Checklist"** — Before writing any code:
  1. Is this a global or local concern? If global, use StateManager signals.
  2. Does this touch card auth? If yes, test with ALL card types (SJA5, gialersim, blank).
  3. Does this write to a card? If yes, add verify-after-write.
  4. Does this affect multiple tabs? If yes, implement in one place, signal to all.
  5. Can this fail silently? If yes, add explicit error surfacing.
- [ ] **Add a "Common Mistakes" section** — Expand the current "Lessons Learned" with the full list from this retrospective.
- [ ] **Add a "Q&A Gate" for new features** — Before implementing, answer: What card types? What file formats? Which tabs? What error modes? What's the verify step? This prevents the "implement first, discover edge cases later" pattern.

## Known Issues (Acceptable / Deferred)

- [ ] Share indicator grey on startup (user: "Acceptable, don't look into this right now")
- [ ] App unresponsive after closing Network Storage dialog (user: "Acceptable")
- [ ] Right pane says "Insert SIM" even after blank card detected
- [ ] Card data blanks out when removing/inserting SIM
- [x] **PARTIALLY FIXED v0.5.21: "Card not in index" after just programming** — Fix 1.4 added `add_iccid()` to update the index after programming. The "add single card" part works (log confirms `ICCID index: added single card`). However, the full "card not in index" dialog may still appear if the auto-read flow triggers a second lookup before the index update propagates. Needs further testing to confirm fully resolved.
