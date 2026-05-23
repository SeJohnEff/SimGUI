# Plan: Remove Simulator Mode

**Status:** COMPLETE — all 10 commits implemented and pushed. New Ubuntu baseline: 1900 passed, 313 skipped.  
**Goal:** Remove simulator mode entirely. The application will have one operational mode: hardware mode. The Card menu mode switch will also be removed.

---

## 1. Human Decisions — Recorded

These were open questions in the original audit. All three are now answered and binding.

### Decision 1 — Startup with no pySim found

**Decision:** No simulator fallback. The application is hardware-only.

If `CLIBackend.NONE` (no pySim found at startup), the app must fail safely with a clear setup/install message. Options that were considered and rejected: falling back to simulator mode (not allowed), silent startup (not allowed). The message must tell the user how to install pySim and must not leave the app in an ambiguous state. Exact UX (blocking dialog vs. persistent banner) to be confirmed during Commit 5 implementation, but the principle is fixed: no simulator fallback under any circumstances.

### Decision 2 — Test suite strategy

**Decision:** Two-track approach.

- **Delete** tests that specifically validate simulator mode as a product feature (e.g. `test_simulator.py`, AppMode toggle tests, simulator-mode startup tests). These tests have no hardware equivalent and nothing to rewrite toward.
- **Rewrite** tests that only use the simulator as a convenient test double for real business logic. Coverage must be preserved for: SIM programming, authentication, card detection, retry safety, CSV handling, batch sequencing, and state machine behavior. Rewrites use `unittest.mock` to mock `CardManager` internals directly — the simulator backend is never a dependency in rewritten tests.

Coverage areas that must not shrink: SIM programming, auth, card detection, retry safety, CSV, batch, state behavior.

### Decision 3 — `simulator/` directory deletion

**Decision:** Approved for deletion — but only in a late commit, after all references in application code and tests are removed or replaced, and after the full test suite passes without importing from `simulator/`.

Deleting the directory before references are cleaned up causes import errors that mask real failures.

### Decision 4 (standing rule) — macOS-specific code authority

macOS-specific code is untested as business logic. It may only provide thin platform adapter values. It must never be treated as a source of behavioral truth. Ubuntu active baseline and `state-machine.md` are the behavioral authorities for this work.

---

## 2. What References Simulator Mode

### 2.1 State / Business Logic

These are the load-bearing references — the ones that actually implement simulator behavior.

| File | Lines | What it does |
|------|-------|--------------|
| `state_manager.py` | 61–64 | `AppMode` enum: `HARDWARE = "hardware"`, `SIMULATOR = "simulator"` |
| `state_manager.py` | 130–136 | `SimulatorInfo` dataclass (current_index, total_cards, active) |
| `state_manager.py` | 154, 162, 179, 183 | `mode_changed` and `simulator_info_changed` signal definitions |
| `state_manager.py` | 247–256 | `mode` property getter/setter with change detection |
| `state_manager.py` | 318–339 | `simulator_info` property and `update_simulator_info()` method |
| `managers/card_manager.py` | 125–130 | `CLIBackend.SIMULATOR` enum value (vestigial, unused) |
| `managers/card_manager.py` | 287 | `self._simulator = None` instance field |
| `managers/card_manager.py` | 296–309 | `enable_simulator()`, `disable_simulator()`, `is_simulator_active` |
| `managers/card_manager.py` | 312–1352 | 30+ `if self._simulator:` routing gates inside every card operation |
| `managers/batch_manager.py` | 139 | `simulator_mode = self._cm.is_simulator_active` capture |
| `managers/batch_manager.py` | 156–158 | Auto-advance logic: simulator → auto-swap; hardware → wait for operator |
| `managers/settings_manager.py` | 25 | `"simulator_mode": False` default key (never written, vestigial) |
| `simulator/__init__.py` | all | Module exports |
| `simulator/settings.py` | all | `SimulatorSettings` dataclass |
| `simulator/simulator_backend.py` | all | Full simulator card operations API |
| `simulator/virtual_card.py` | all | `VirtualCard` class |
| `simulator/card_deck.py` | all | `generate_deck()`, `load_from_csv()`, 20 SJA5 profiles |

### 2.2 UI Only

These references only affect what the user sees; they have no business logic.

| File | Lines | What it does |
|------|-------|--------------|
| `main.py` | 379–403 | Card menu: "Hardware Mode" and "Simulator Mode" checkable actions |
| `main.py` | 591–595 | `_on_mode_hardware()` and `_on_mode_simulator()` handlers (each 1 line) |
| `main.py` | 438–443 | `_on_mode_changed()`: updates menu checkboxes and status bar with `[SIM]` prefix |
| `main.py` | 419 | Signal connection: `mode_changed.connect(_on_mode_changed)` |

### 2.3 Startup Logic (mixed: business + UI)

| File | Lines | What it does |
|------|-------|--------------|
| `main.py` | 228–231 | If `CLIBackend.NONE`, start in `AppMode.SIMULATOR`; else `AppMode.HARDWARE` |
| `main.py` | 506–509 | `_startup_detect_card()` skips detection if `mode == AppMode.SIMULATOR` |

### 2.4 Documentation

| File | Lines | What it does |
|------|-------|--------------|
| `docs/explanation/architecture.md` | 26, 36, 83, 160, 197–211 | Simulator backend design, signal table, architecture diagram |
| `docs/reference/state-machine.md` | 170 | Signal table: `mode_changed \| AppMode \| Hardware ↔ Simulator toggle` |
| `docs/reference/configuration.md` | 88, 116–120 | `simulator_mode` settings key definition |
| `docs/how-to/troubleshooting.md` | 216–221 | "Simulator mode" troubleshooting section |
| `README.md` | 21, 87 | Feature list and getting-started simulator mention |

### 2.5 Tests — Delete or Rewrite

Per Decision 2, each test file is classified below.

**Delete entirely** (tests simulator as a product feature — nothing to rewrite toward):

| File | Reason |
|------|--------|
| `tests/test_simulator.py` | SimulatorBackend unit tests (~70 tests). The backend is being deleted. |
| `tests/test_simulator_full.py` | Full simulator integration tests. |
| `tests/test_simulator_settings_logic.py` | Simulator settings handling. |
| `tests/test_state_manager.py` lines 216–242 | AppMode enum and mode property tests. AppMode is being deleted. |
| `tests/test_main_app.py` lines 649–683 | Simulator mode restored from settings — feature is deleted. |
| `tests/test_main_app.py` lines 685+ | No CLI → simulator mode — behavior is deleted. |
| `tests/test_settings_manager.py` lines 51–52 | `simulator_mode` key get/set — key is deleted. |
| `tests/test_settings_manager_extended.py` lines 82–85 | `simulator_mode` default value — key is deleted. |

**Rewrite with mocks** (simulator was only a test double; the logic under test survives):

| File | Coverage to preserve |
|------|---------------------|
| `tests/test_batch_manager_full.py` | Batch sequencing, card-swap wait, retry behavior, CSV iteration. Remove simulator auto-advance tests; rewrite remaining with mock `CardManager`. |
| `tests/test_card_manager_full.py` | Card detection, authentication, programming logic, retry safety, ADM1 format handling. Replace `enable_simulator()` calls with mock `CardManager` methods. |
| `tests/test_verify_after_program.py` | Verification flow after programming. Rewrite with mock `CardManager.verify_card()`. |
| `tests/test_e2e_contracts.py` | End-to-end state machine contracts. Rewrite hardware path scenarios with mock `CardManager`. |
| `tests/test_phase1_bugfixes.py` | Lines using `cm._simulator = None` — remove those lines; keep the underlying bug assertions if the behavior still exists. |

---

## 3. Can AppMode Be Removed Entirely?

**Yes.** `AppMode` has exactly two values: `HARDWARE` and `SIMULATOR`. After simulator removal there is one operational mode. The enum, its signal (`mode_changed`), its property, and all connected handlers are deleted entirely.

`AppMode` removal must be its own isolated commit (Commit 4 in the sequence below). No other concerns may be bundled into that commit.

`state-machine.md` mentions `AppMode` once (line 170, signal table entry for `mode_changed`). That entry must be removed — in a separate, standalone commit (Commit 6) with no other changes. Human sign-off is required before that commit is made.

`SimulatorInfo` (the dataclass and its signal `simulator_info_changed`) is purely simulator-internal and is deleted in the same commit as `AppMode`.

---

## 4. What Can Be Removed vs. What Must Stay

### Safe to delete entirely (no other purpose)
- `AppMode` enum
- `SimulatorInfo` dataclass
- `mode_changed` signal and property
- `simulator_info_changed` signal and method
- `CardManager._simulator` field
- `CardManager.enable_simulator()`, `disable_simulator()`, `is_simulator_active`
- `CardManager.next_virtual_card()`, `previous_virtual_card()`, `get_simulator_info()`
- `CLIBackend.SIMULATOR` enum value (unused)
- `"simulator_mode"` settings key in `SettingsManager`
- Card menu Hardware Mode / Simulator Mode actions and handlers in `main.py`
- `_on_mode_changed()` handler in `main.py`
- `simulator/` directory — all 5 modules (late commit only, after all references cleared)

### Requires rewrite (not pure deletion)
- Every `if self._simulator:` gate in `card_manager.py` — remove the simulator branch, promote the hardware (`else`) path to unconditional.
- Batch manager auto-advance — remove the simulator branch; hardware wait-for-operator is the only path.
- Startup logic in `main.py` — remove the `AppMode.SIMULATOR` fallback; replace with a clear setup/install error message when `CLIBackend.NONE` (see Decision 1).
- `_startup_detect_card()` guard — remove the mode check; always run detection.

### Requires careful standalone edit (guarded file)
- `docs/reference/state-machine.md` — remove only the `mode_changed` row from the signal table. No other edits. Standalone commit. Human sign-off required.

### Tests: see 2.5 above
Delete simulator-feature tests. Rewrite test-double tests with `unittest.mock`. Coverage for SIM programming, auth, detection, retry safety, CSV, batch, and state behavior must not shrink.

---

## 5. Implementation Sequence

**Non-negotiable sequencing rules:**
- `simulator/` directory is deleted **late** — only after all application code references are removed and the full test suite passes without any import from `simulator/`.
- `AppMode` removal is its own isolated commit. No other concerns bundled.
- `state-machine.md` edit is a standalone commit with no other changes. Human sign-off required before it is made.
- A new Ubuntu test baseline is recorded and `CLAUDE.md` updated as the final commit of this sequence.
- macOS-specific code must never be a source of behavioral decisions during this work.

Each commit is a single concern. Run `python3 -m pytest tests/ -x -q` after every commit.

---

### Commit 1 — Rewrite test-double tests (no application code changes)

Before touching application code, convert tests that use the simulator as a test double to use `unittest.mock`. This ensures coverage is confirmed working before the backend is removed.

- Rewrite `test_batch_manager_full.py`: remove simulator auto-advance tests; rewrite remaining batch logic tests with mock `CardManager`.
- Rewrite `test_card_manager_full.py`: replace `enable_simulator()` calls with mock `CardManager` methods; preserve coverage for all hardware-path logic.
- Rewrite `test_verify_after_program.py`: replace simulator with mock `CardManager.verify_card()`.
- Rewrite `test_e2e_contracts.py`: replace simulator with mock `CardManager` for hardware path scenarios.
- Rewrite affected lines in `test_phase1_bugfixes.py`: remove `cm._simulator = None` lines; keep underlying behavior assertions.
- Do **not** touch application code in this commit.

**Test command:** `python3 -m pytest tests/ -x -q`  
**Expected:** All 2123 tests still pass (rewrites are behavior-equivalent).

---

### Commit 2 — Delete simulator-feature tests

Delete tests that validate simulator as a product feature — there is nothing to rewrite them toward.

- Delete `tests/test_simulator.py`
- Delete `tests/test_simulator_full.py`
- Delete `tests/test_simulator_settings_logic.py`
- Delete AppMode test cases from `tests/test_state_manager.py` (lines 216–242)
- Delete simulator startup test cases from `tests/test_main_app.py` (lines 649–685+)
- Delete `simulator_mode` key test cases from `tests/test_settings_manager.py` (lines 51–52)
- Delete `simulator_mode` default test cases from `tests/test_settings_manager_extended.py` (lines 82–85)
- Do **not** touch application code in this commit.

**Test command:** `python3 -m pytest tests/ -x -q`  
**Expected:** Test count drops by ~150–200. No failures — only deletions. Any failure here means a rewrite in Commit 1 is incomplete; stop and fix before continuing.

---

### Commit 3 — Remove simulator routing from `card_manager.py`

- Remove `self._simulator = None` instance field.
- Remove all 30+ `if self._simulator:` routing gates — promote the hardware `else` path to unconditional in each case.
- Remove `enable_simulator()`, `disable_simulator()`, `is_simulator_active`.
- Remove `next_virtual_card()`, `previous_virtual_card()`, `get_simulator_info()`.
- Remove `CLIBackend.SIMULATOR` enum value.
- Do **not** delete `simulator/` yet — it is imported nowhere in tests after Commits 1–2, but confirm with a grep before deleting.

**Test command:** `python3 -m pytest tests/ -x -q`  
**Expected:** Same count as Commit 2. Any failure = a mock rewrite in Commit 1 missed something; stop and fix.

---

### Commit 4 — Remove simulator routing from `batch_manager.py`

- Remove `simulator_mode = self._cm.is_simulator_active` capture.
- Remove the `if simulator_mode:` auto-advance branch.
- Hardware wait-for-operator path becomes unconditional.

**Test command:** `python3 -m pytest tests/ -x -q`  
**Expected:** Same count as Commit 3.

---

### Commit 5 — Remove `AppMode`, `SimulatorInfo`, and signals from `state_manager.py` (isolated)

This commit removes `AppMode` and nothing else outside `state_manager.py` and `settings_manager.py`.

- Delete `AppMode` enum from `state_manager.py`.
- Delete `SimulatorInfo` dataclass from `state_manager.py`.
- Delete `mode_changed` signal definition, property getter/setter, and emission call.
- Delete `simulator_info_changed` signal, property, and `update_simulator_info()` method.
- Remove `"simulator_mode"` default key from `SettingsManager`.
- Remove any remaining `AppMode` imports in other files that referenced the signal.

**Test command:** `python3 -m pytest tests/ -x -q`  
**Expected:** Same count as Commit 4. Any remaining test that imports `AppMode` will now fail — those must have been deleted in Commit 2; stop and fix if any remain.

---

### Commit 6 — Remove Card menu and mode handlers from `main.py`; implement no-pySim message

- Remove Card menu "Hardware Mode" / "Simulator Mode" checkable actions (lines 379–403).
- Remove `_on_mode_hardware()`, `_on_mode_simulator()` handlers (lines 591–595).
- Remove `_on_mode_changed()` and its signal connection (lines 419, 438–443).
- Remove `self._hw_act`, `self._sim_act` attributes.
- Replace the `AppMode.SIMULATOR` startup fallback (lines 228–231) with a clear setup/install error message when `CLIBackend.NONE`. No simulator fallback under any circumstances.
- Remove mode check guard in `_startup_detect_card()` (lines 506–509) — detection always runs.

**Test command:** `python3 -m pytest tests/ -x -q`  
**Expected:** Same count as Commit 5.

---

### Commit 7 — Delete `simulator/` directory (late, after references confirmed clear)

Before deleting, run: `grep -r "from simulator" tests/ managers/ main.py state_manager.py` and `grep -r "import simulator" tests/ managers/ main.py state_manager.py`. Both must return zero results. If any import remains, stop and fix the reference first.

Only then:
- Delete `simulator/__init__.py`
- Delete `simulator/settings.py`
- Delete `simulator/simulator_backend.py`
- Delete `simulator/virtual_card.py`
- Delete `simulator/card_deck.py`
- Remove the `simulator/` directory.

**Test command:** `python3 -m pytest tests/ -x -q`  
**Expected:** Same count as Commit 6. Any `ModuleNotFoundError` for `simulator` = a stale import was missed; stop and fix.

---

### Commit 8 — Edit `state-machine.md` (standalone, human sign-off required)

**Do not proceed with this commit until human sign-off is given.**

- Open `docs/reference/state-machine.md`.
- Remove the single row `mode_changed | AppMode | Hardware ↔ Simulator toggle` from the signal table (line 170).
- No other edits to `state-machine.md`. Not a single other character changed.

**Test command:** `python3 -m pytest tests/ -x -q` (no change expected — docs-only commit)

---

### Commit 9 — Update all other documentation

- `docs/explanation/architecture.md`: Remove simulator backend section (lines 197–211), remove `mode_changed` from signal table, update architecture diagram.
- `docs/reference/configuration.md`: Remove `simulator_mode` key entry (lines 88, 116–120).
- `docs/how-to/troubleshooting.md`: Remove "Simulator mode" troubleshooting section (lines 216–221).
- `README.md`: Remove simulator mode from feature list (line 21) and getting-started section (line 87).
- Update `docs/reference/current-platform-refactor-status.md`.

**Test command:** `python3 -m pytest tests/ -x -q` (no change expected — docs-only commit)

---

### Commit 10 — Record new Ubuntu baseline

- Run full test suite on Ubuntu and record the actual pass/skip/fail counts.
- Create `docs/reference/test-baseline-ubuntu-post-simulator-removal.md` with the new authoritative counts, Ubuntu version, and date.
- Update `CLAUDE.md` active baseline line to the new count.
- This commit completes the sequence.

**Test command:** `python3 -m pytest tests/ -x -q` (this run IS the new baseline)

---

## 6. Test Count Impact Estimate

Current Ubuntu baseline: **2123 passed, 323 skipped**.

Tests deleted in Commit 2 (approximate):
- `test_simulator.py` — ~70 tests
- `test_simulator_full.py` — ~40 tests
- `test_simulator_settings_logic.py` — ~15 tests
- AppMode cases from `test_state_manager.py` — ~27 tests
- Simulator startup cases from `test_main_app.py` — ~35 tests
- Settings key cases — ~3 tests

**Rough estimate:** 150–200 tests deleted. New baseline expected approximately **1923–1973 passed**. The actual count is recorded in Commit 10 and becomes the new authority.

Tests rewritten in Commit 1 preserve coverage and do not change the count.

---

## 7. Rollback Condition

Stop and revert the current commit if any of the following occur:

- A commit causes tests unrelated to simulator mode to fail.
- A commit changes the behavior of card detection, authentication, or programming on hardware cards.
- A `state-machine.md` conflict is discovered — report the exact file, line, and conflicting invariant; do not paper over it; do not push a partial fix.
- The no-pySim startup message behavior (Decision 1) has not been fully confirmed before Commit 6.
- The `simulator/` directory is deleted before Commit 7 (i.e., before all imports are confirmed clear).
- The `state-machine.md` edit is bundled into any commit other than Commit 8.
- Human sign-off for Commit 8 has not been received.

---

## 8. Notes

- `CLIBackend.SIMULATOR` in `card_manager.py` (lines 125–130) is not used anywhere. It is deleted silently in Commit 3 with no behavior change.
- The `"simulator_mode"` settings key is never written to disk. Deleting it will not break any saved user settings — the key will simply be absent and ignored by any existing `~/.config/simgui/settings.json`.
- `pySim-read`, `pySim-prog`, and `pySim-shell` CLI integrations are entirely unaffected by this work. All three are hardware-only paths and remain unchanged.
- The Ubuntu baseline guardrail applies to every commit in this sequence. If a hardware-path test fails at any point, that commit is invalid and must be reverted before continuing.
- macOS-specific code (`platform_runtime.py` or any `sys.platform` branch) must not be consulted or copied during this work. Ubuntu behavior and `state-machine.md` are the sole authorities.
