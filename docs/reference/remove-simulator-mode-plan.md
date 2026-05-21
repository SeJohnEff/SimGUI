# Plan: Remove Simulator Mode

**Status:** Design only — no code has been changed.  
**Goal:** Remove simulator mode entirely. The application will have one operational mode: hardware mode. The Card menu mode switch will also be removed.

---

## 1. Human Decisions Required Before Implementation

These questions must be answered before any code is deleted:

1. **Startup fallback when no pySim is found:** Currently, if `CLIBackend.NONE` (no pySim found at startup), the app starts in `AppMode.SIMULATOR`. After removal, what should happen instead? Options:
   - Show a blocking error dialog and refuse to start.
   - Start normally but show a persistent warning in the status bar.
   - Start normally and let card detection fail naturally when the user tries to insert a card.

2. **Test suite strategy:** ~150+ tests use the simulator backend as a cheap stand-in for real hardware (no reader needed). After simulator removal they will fail. Two options:
   - Delete them (lose coverage of batching, programming logic, state transitions).
   - Rewrite them to use `unittest.mock` to mock `CardManager` internals directly.
   The rewrite is the correct choice, but it is a significant effort and must be scoped before starting.

3. **`simulator/` directory:** Delete the entire directory and all 5 modules? Confirm.

4. **`simulator_mode` settings key:** The key exists in `SettingsManager` but is never written. Delete the key and the default entry?

5. **`CLIBackend.SIMULATOR` enum value:** This value exists in `card_manager.py` but is not used anywhere. Delete it when removing other simulator code?

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

### 2.5 Tests That Will Fail or Need Removal

These test files test simulator behavior directly and will require deletion or full rewrite:

| File | What it tests |
|------|---------------|
| `tests/test_simulator.py` | SimulatorBackend unit tests (70+ tests) |
| `tests/test_simulator_full.py` | Full simulator integration tests |
| `tests/test_simulator_settings_logic.py` | Simulator settings handling |
| `tests/test_batch_manager_full.py` | Batch runs using simulator auto-advance |
| `tests/test_card_manager_full.py` | CardManager with simulator enabled |
| `tests/test_verify_after_program.py` | Verification flow via simulator |
| `tests/test_e2e_contracts.py` | End-to-end contracts using simulator |
| `tests/test_phase1_bugfixes.py` | References `cm._simulator = None` to disable |
| `tests/test_state_manager.py` | 216–242: AppMode enum and mode property tests |
| `tests/test_main_app.py` | 649–683: simulator mode restored from settings; 685+: no CLI → simulator |
| `tests/test_settings_manager.py` | 51–52: `simulator_mode` key get/set |
| `tests/test_settings_manager_extended.py` | 82–85: default value `False` |

---

## 3. Can AppMode Be Removed Entirely?

**Yes.** `AppMode` has exactly two values: `HARDWARE` and `SIMULATOR`. After simulator removal there would be one operational mode. The enum, its signal (`mode_changed`), its property, and all connected handlers can be removed entirely.

`state-machine.md` mentions `AppMode` once (line 170, signal table). That entry must be removed when `mode_changed` is removed. This requires editing `state-machine.md` — a guarded file. That edit should be a standalone commit with explicit human sign-off.

`SimulatorInfo` (the dataclass and its signal `simulator_info_changed`) is purely simulator-internal and can be deleted alongside `AppMode`.

---

## 4. What Can Be Removed vs. What Must Stay

### Safe to delete entirely (no other purpose)
- `simulator/` directory — all 5 modules
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

### Requires rewrite (not pure deletion)
- Every `if self._simulator:` gate in `card_manager.py` — remove the branch, keep the `else` (hardware) path as the unconditional path.
- Batch manager auto-advance — remove the simulator branch; hardware wait-for-operator is the only path.
- Startup logic in `main.py` — remove the `AppMode.SIMULATOR` fallback; decide what happens when `CLIBackend.NONE` (see Human Decisions section).
- `_startup_detect_card()` guard — remove the mode check; always run detection.

### Requires careful edit (guarded files)
- `docs/reference/state-machine.md` — remove the `mode_changed` row from the signal table. No other content changes.

### Tests: delete or rewrite
- All simulator-specific test files (listed in 2.5) must be deleted.
- Tests in `test_state_manager.py`, `test_main_app.py`, `test_settings_manager.py` that test simulator-specific behavior must be deleted (not rewritten — there is nothing to test).
- Tests in `test_batch_manager_full.py`, `test_card_manager_full.py`, `test_e2e_contracts.py` that use simulator as a test double need assessment: if they test logic that is still present (e.g. batch sequencing, card programming logic), they must be rewritten to use `unittest.mock` rather than the simulator backend.

---

## 5. Proposed Implementation Sequence

Each commit is a single concern. Run the full test suite after every commit.

### Commit 1 — Remove `simulator/` directory
- Delete `simulator/__init__.py`, `simulator/settings.py`, `simulator/simulator_backend.py`, `simulator/virtual_card.py`, `simulator/card_deck.py`.
- Delete all simulator-specific test files: `test_simulator.py`, `test_simulator_full.py`, `test_simulator_settings_logic.py`.
- **Test command:** `python3 -m pytest tests/ -x -q`
- **Expected:** Tests that imported from `simulator/` will no longer import it. The test count will drop. Any test that did `from simulator import ...` will now fail if not deleted — verify none remain.

### Commit 2 — Remove simulator routing from `card_manager.py`
- Remove `self._simulator` field and all 30+ `if self._simulator:` gates.
- Remove `enable_simulator()`, `disable_simulator()`, `is_simulator_active`, `next_virtual_card()`, `previous_virtual_card()`, `get_simulator_info()`.
- Remove `CLIBackend.SIMULATOR` enum value.
- **Test command:** `python3 -m pytest tests/ -x -q`
- **Expected:** Tests that called `enable_simulator()` or checked `is_simulator_active` will fail — these must have been deleted in Commit 1 or identified here for deletion.

### Commit 3 — Remove simulator routing from `batch_manager.py`
- Remove `simulator_mode = self._cm.is_simulator_active` capture.
- Remove the `if simulator_mode:` auto-advance branch; hardware wait path becomes unconditional.
- **Test command:** `python3 -m pytest tests/ -x -q`
- **Expected:** Batch tests that relied on auto-advance (test_batch_manager_full.py) must already be deleted or rewritten.

### Commit 4 — Remove `AppMode`, `SimulatorInfo`, and their signals from `state_manager.py`
- Delete `AppMode` enum.
- Delete `SimulatorInfo` dataclass.
- Delete `mode_changed` signal definition, property, and setter logic.
- Delete `simulator_info_changed` signal, property, and `update_simulator_info()`.
- Remove `"simulator_mode"` default from `SettingsManager`.
- **Test command:** `python3 -m pytest tests/ -x -q`
- **Expected:** `test_state_manager.py` AppMode tests and `test_settings_manager*.py` simulator key tests will fail — delete those test cases.

### Commit 5 — Remove Card menu and mode handlers from `main.py`
- Remove Card menu "Hardware Mode" / "Simulator Mode" actions (lines 379–403).
- Remove `_on_mode_hardware()`, `_on_mode_simulator()` (lines 591–595).
- Remove `_on_mode_changed()` and its signal connection (lines 419, 438–443).
- Remove startup mode selection (`AppMode.SIMULATOR` fallback) and implement the agreed-upon no-pySim fallback (see Human Decisions).
- Remove mode check guard in `_startup_detect_card()`.
- Remove `self._hw_act`, `self._sim_act` attributes.
- **Test command:** `python3 -m pytest tests/ -x -q`
- **Expected:** `test_main_app.py` simulator-mode startup tests will fail — delete those test cases.

### Commit 6 — Edit `state-machine.md`
- Remove the `mode_changed | AppMode | Hardware ↔ Simulator toggle` row from the signal table.
- No other edits to `state-machine.md`.
- **Human sign-off required before this commit.**
- **Test command:** `python3 -m pytest tests/ -x -q` (no change expected)

### Commit 7 — Update documentation
- `docs/explanation/architecture.md`: Remove simulator backend section (lines 197–211), update signal table, update architecture diagram.
- `docs/reference/configuration.md`: Remove `simulator_mode` key entry.
- `docs/how-to/troubleshooting.md`: Remove "Simulator mode" section (lines 216–221).
- `README.md`: Remove simulator mode from feature list and getting-started.
- Update `docs/reference/current-platform-refactor-status.md`.
- **Test command:** `python3 -m pytest tests/ -x -q` (no change expected)

### Commit 8 — Establish new test baseline
- Record the new passing count after all simulator tests are removed.
- Update `CLAUDE.md` with the new baseline count.
- Update `docs/reference/test-baseline-ubuntu-post-qt-main-removal.md` (or create a new baseline doc).

---

## 6. Test Count Impact Estimate

The current Ubuntu baseline is **2123 passed, 323 skipped**.

The following test files are expected to be deleted entirely:
- `test_simulator.py` — ~70 tests
- `test_simulator_full.py` — estimated ~40 tests
- `test_simulator_settings_logic.py` — estimated ~15 tests

Additional test cases within surviving files that will be deleted:
- `test_batch_manager_full.py` — some tests (those using simulator auto-advance)
- `test_card_manager_full.py` — some tests (those enabling simulator)
- `test_state_manager.py` — AppMode tests (~27 tests at lines 216–242)
- `test_main_app.py` — simulator startup tests (~35 tests at lines 649–685+)
- `test_settings_manager.py` / `test_settings_manager_extended.py` — ~3 tests

**Rough estimate:** 150–200 tests deleted. New baseline expected to be approximately 1923–1973 passed. The new baseline must be recorded and `CLAUDE.md` updated before any further work continues.

---

## 7. Rollback Condition

Stop and revert the current commit if:
- Any commit causes tests unrelated to simulator mode to fail.
- Any commit changes the behavior of card detection, authentication, or programming on hardware cards.
- A `state-machine.md` conflict is discovered that cannot be resolved without a design decision (report and stop — do not paper over it).
- The agreed-upon no-pySim fallback behavior (Human Decision 1) has not been decided before Commit 5.

---

## 8. Notes

- The `CLIBackend.SIMULATOR` enum value in `card_manager.py` (lines 125–130) is **not used anywhere** in the codebase. It can be deleted silently in Commit 2 with no behavior change.
- The `"simulator_mode"` settings key is **never written** to disk in the current codebase. It exists only as a default. Deleting it will not break any saved settings files — the key will simply be absent and ignored.
- `pySim-read`, `pySim-prog`, and `pySim-shell` integrations are unaffected. All three are hardware-only paths and will remain exactly as-is.
- The Ubuntu test baseline guardrail applies throughout: no commit may break hardware-path tests. If a commit in this sequence causes a hardware test to fail, the commit is invalid and must be reverted.
