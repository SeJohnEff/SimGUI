# Stale Simulator Reference Audit

**Date:** 2026-05-23
**Branch:** main
**Head commit:** `dd90d2b` — docs: record post simulator removal baseline
**Scope:** All references to `simulator`, `simulation`, `virtual card`, `virtual_card`,
`card_deck`, `AppMode`, `simulator_mode`, `hardware mode`, `mode switch` across docs,
scripts, tests, and packaging.

This is an **audit only** — no changes were made.

---

## Summary

The simulator runtime was fully removed from application code (Commits 1–9). However,
stale references remain in documentation, tests, and scripts. They fall into three
buckets:

1. **Historical/internal docs** — records of what was done; safe to keep.
2. **User-facing stale docs** — describe a feature that no longer exists; should be cleaned.
3. **Test stale references** — dead mock attributes or outdated comments in active test
   files; should be cleaned.
4. **Script stale references** — release and install scripts that mention simulator mode;
   need care (install.sh has a behavioral implication).

---

## File-by-File Inventory

### CLAUDE.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 68 | `simulator/` in architecture tree | **User-facing stale doc** — directory no longer exists |
| 205–206 | "post simulator removal" baseline text | **Historical/internal doc** — OK to keep |
| 292–303 | Platform refactor rules reference simulator-removal baseline | **Historical/internal doc** — OK to keep |
| 466 | `mode_changed(AppMode) # HARDWARE ↔ SIMULATOR` in signal table | **User-facing stale doc** — `AppMode` and `mode_changed` signal deleted; table is wrong |

### README.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 21 | "**Simulator mode** — built-in SIM programmer simulator with 20 real sysmoISIM-SJA5 profiles" | **User-facing stale doc** — feature no longer exists |
| 87 | "**For simulator mode** (no hardware needed):" | **User-facing stale doc** — section describes removed feature |

### docs/explanation/architecture.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 26 | `SimulatorSettings` in architecture diagram | **User-facing stale doc** — component deleted |
| 36–38 | `SimulatorBackend (opt)`, `virtual_card.py`, `card_deck.py` in diagram | **User-facing stale doc** — package deleted |
| 83 | "Simulator delegation (when `_simulator` is set …)" | **User-facing stale doc** — routing gates removed |
| 160 | `mode_changed(AppMode)` in signal table | **User-facing stale doc** — signal deleted |
| 197–211 | "The simulator backend" section | **User-facing stale doc** — entire section describes deleted code |

### docs/explanation/adm1-security.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 91 | "In the simulator, each virtual card tracks attempts …" | **User-facing stale doc** — simulator removed |

### docs/explanation/suci-vs-non-suci.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 102–104 | "In the simulator" section | **User-facing stale doc** — simulator removed |
| 119 | Comparison table row "SimGUI simulator" | **User-facing stale doc** — row should be removed |

### docs/how-to/install.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 117 | "5 minutes (simulator mode)" | **User-facing stale doc** — no simulator mode |
| 147 | "Simulator mode works immediately — 20 virtual SIM cards …" | **User-facing stale doc** — feature removed |
| 247 | "enable **Simulator Mode** in Settings" | **User-facing stale doc** — setting removed |

### docs/how-to/troubleshooting.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 211–221 | "Simulator mode" troubleshooting section (3 subsections) | **User-facing stale doc** — whole section obsolete |
| 251 | "Whether the issue reproduces in simulator mode" | **User-facing stale doc** — question no longer applicable |

### docs/how-to/network-share-setup.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 112 | "Program a card (or run a simulator session)" | **User-facing stale doc** — parenthetical obsolete |

### docs/tutorials/batch-programming.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 130–141 | "Using the simulator for a dry run" subsection (7 lines) | **User-facing stale doc** — entire subsection obsolete |

### docs/index.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 3 | "built-in simulator for testing without hardware" in description | **User-facing stale doc** — no longer accurate |
| 56 | "Managers, widgets, simulator, and CLI decoupling" in table | **User-facing stale doc** — simulator no longer described there |

### docs/reference/card-types.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 51 | "The built-in SimGUI simulator loads 20 real sysmoISIM-SJA5 profiles …" | **User-facing stale doc** — simulator removed |

### docs/reference/cli-integration.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 15 | `CLIBackend.SIMULATOR` row in table | **User-facing stale doc** — enum value deleted |
| 173–177 | "Simulator mode" section | **User-facing stale doc** — entire section obsolete |

### docs/reference/configuration.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 88 | `simulator_mode` key in settings table | **User-facing stale doc** — key removed |
| 116–120 | JSON example with `"simulator_mode": false` | **User-facing stale doc** — key no longer present |

### docs/auto-read-flow.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 241 | "Simulator mode | CardWatcher pauses …" table row | **User-facing stale doc** — row obsolete |

### docs/TODO.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 174 | "exercise the actual pySim tools against the simulator or real cards" | **Historical/internal doc** — planning note, not user-facing, acceptable to keep or rephrase |
| 176 | "A card programmer simulator that doesn't integrate with pySim is theater" | **Historical/internal doc** — planning note; references the now-deleted simulator but the underlying point about future testing strategy is still valid |

### docs/reference/remove-simulator-mode-plan.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| All | Entire document | **Historical/internal doc** — permanent record of the removal plan and decisions; OK to keep |

### docs/reference/current-platform-refactor-status.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 107–123 | "Simulator mode removal (Commits 1–10)" section | **Historical/internal doc** — accurate post-removal record; OK to keep |
| 31–36 | Baseline count table with simulator-removal row | **Historical/internal doc** — OK to keep |

### docs/reference/test-baseline-ubuntu-post-simulator-removal.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| All | Entire document | **Historical/internal doc** — authoritative baseline record; must not be changed |

### docs/reference/test-baseline-macos-v0.5.50.md

| Line | Reference | Classification |
|------|-----------|----------------|
| 157–159 | "Category 5 — Simulator deck loading" in skipped/failed section | **Historical/internal doc** — frozen baseline snapshot; OK to keep |

### docs/reference/post-v0.5.50-forensic-report.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 29–30, 34–36 | References to simulator mode in forensic report | **Historical/internal doc** — forensic record; must not be changed |

### docs/reference/packaging-configuration-plan.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 39 | `simulator/` in `cp -r` file list | **Packaging/release reference — NEEDS CARE** — the `debian/rules` `cp` command still references `simulator/`. If building a `.deb` with this plan, the copy will fail because the directory no longer exists. This does not affect the current Makefile (`debian/rules`) directly — must verify if the plan is still in use. |
| 116 | Same `cp` line in updated Makefile block | **Packaging/release reference — NEEDS CARE** — same issue |
| 274 | "Confirm simulator mode is functional in the bundle" | **Packaging/release reference** — a release checklist step that can no longer pass; should be removed from checklist |

### docs/PYQT6_MIGRATION_PLAN.md

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 17 | "4,663 (25 files — managers, utils, simulator)" | **Historical/internal doc** — old line count snapshot; planning doc, not user-facing |
| 150 | `dialogs/simulator_settings_dialog.py` migration row | **Historical/internal doc** — migration plan for a dialog that has since been deleted |
| 313 | `→ qt_dialogs/simulator_settings_dialog.py` checklist item | **Historical/internal doc** — planning doc item for a deleted file; should be marked done/removed during next PyQt6 migration pass |

### test_audit_report.md (root)

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 104, 107, 123, 124, 182–202, 217, 248–252, 268 | Multiple references to `SimulatorBackend`, `card_deck`, internal simulator details | **Historical/internal doc** — audit report from before simulator removal; frozen historical record, not user-facing documentation |

---

## Active Tests with Stale References

These are currently passing tests (within the 1900 baseline) that contain stale simulator
symbol references. They do not fail because the symbols are set on mock objects (MagicMock
accepts any attribute assignment without error) or because the file is globally skipped.

### tests/test_main_app.py — GLOBALLY SKIPPED

**All 300+ tests in this file are skipped** (`pytestmark = pytest.mark.skip`). They are
part of the 313 skipped count in the baseline. The file is deprecated (tkinter-based tests
incompatible with PyQt6). The simulator references here are therefore **inert** and do not
run.

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 245, 266, 289, 354, 372, 382, 392, 417–499, 650 | `is_simulator_active`, `SimulatorSettingsDialog`, `_on_mode_change_to_simulator`, `next_virtual_card`, `previous_virtual_card` | **Test stale reference** — globally skipped file; references are dead but the file itself is a candidate for deletion |

### tests/test_audit_fixes.py — ACTIVE

`is_simulator_active = False` set on `MagicMock(spec=CardManager)` objects at lines 100,
111, 136, 156, 175, 838. Because `CardManager` no longer has `is_simulator_active`, the
`spec=CardManager` mock will **raise AttributeError** if `is_simulator_active` is accessed
by code under test — but these lines simply set the attribute on the mock itself (harmless
since MagicMock allows arbitrary attribute writes even with spec). The real risk: if
`batch_manager.py` ever reads `is_simulator_active`, it will raise because the live
`CardManager` no longer has that attribute. Currently batch_manager does not read it —
confirmed by grep. These are dead assignments.

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 100, 111, 136, 156, 175, 838 | `cm.is_simulator_active = False` on mock | **Test stale reference — should clean** — dead mock attribute; confuses readers |

### tests/test_batch_manager.py — ACTIVE

| Line | Reference | Classification |
|------|-----------|----------------|
| 23 | `cm.is_simulator_active = False` on mock | **Test stale reference — should clean** |

### tests/test_batch_manager_full.py — ACTIVE

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 30 | `cm.is_simulator_active = False` on mock | **Test stale reference — should clean** |
| 389, 407 | Comments "real CM, no simulator — hardware path" | **Test stale reference** — comment is harmless but no longer meaningful; the hardware path is now the only path |

### tests/test_card_manager_full.py — ACTIVE

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 12 | "- Simulator path edge cases" in module docstring | **Test stale reference — should clean** |
| 112 | "hardware and simulator modes" in class docstring | **Test stale reference — should clean** |
| 130–170 | `test_simulator_program_success`, `test_simulator_program_unauthenticated`, `test_simulator_program_multiple_fields` | **Test stale reference — REQUIRES ANALYSIS** — these test names say "simulator" but the test bodies use `CLIBackend.PYSIM` with mocked `_run_pysim_prog`. They test the hardware programming path, not the simulator backend. They are **valid hardware-path tests with misleading names** — should be renamed, not deleted. |
| 182–224 | "Hardware mode:" comments in method docstrings | **Historical/internal doc** — the word "hardware" here is correct (contrasting with what no longer exists); harmless |
| 550, 578 | "hardware and simulator modes" in class docstring; "hardware mode" in method docstring | **Test stale reference — should clean** — class docstring; method docstring is accurate |

### tests/test_card_safety.py — ACTIVE

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 39, 105, 182, 292, 348, 386, 416, 492, 524, 531, 566, 607, 680, 715, 820, 895, 913, 930 | `cm._simulator = None` set directly on live `CardManager` instances | **Test stale reference — REQUIRES CARE** — `_simulator` no longer exists on `CardManager`. Setting it on a real (not mocked) instance adds a spurious attribute that does nothing, but is misleading. Should be removed. Confirm no test logic depends on this assignment. Removal is safe if `card_manager.py` no longer reads `_simulator` (confirmed by grep). |

### tests/test_e2e_contracts.py — ACTIVE

| Line | Reference | Classification |
|------|-----------|----------------|
| 18 | "The rest of the test-suite mocks subprocess and uses SimulatorBackend." | **Test stale reference — should clean** — `SimulatorBackend` no longer exists; module docstring is misleading |

### tests/test_from_read_card.py — ACTIVE

| Line | Reference | Classification |
|------|-----------|----------------|
| 4 | "Uses the simulator backend so no hardware is needed." | **Test stale reference — should clean** — misleading; the test uses mocks, not the simulator backend |

---

## Scripts

### scripts/install.sh

| Line | Reference | Classification |
|------|-----------|----------------|
| 114 | `warn "pySim clone failed — SimGUI will run in simulator-only mode."` | **Script stale reference — DANGEROUS** — simulator mode no longer exists. If pySim clone fails, the app will fail at startup with "pySim not found", not gracefully fall back to simulator. This warn message gives users a false expectation. Should be changed to: "You can install pySim manually later; the app will not work without it." |

### scripts/install-macos.sh

| Line | Reference | Classification |
|------|-----------|----------------|
| 4 | "Casual users should just download SimGUI.app and run it (simulator mode works out of the box)." | **Script stale reference** — `.app` distribution is blocked (see docs/TODO.md); simulator mode removed. Comment is doubly stale. |

### scripts/create-release.sh

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 34–39 | "**Zero-Setup Simulator Mode**" section in release notes template | **Script stale reference** — the GitHub release note template still advertises simulator mode. Any new release created with this script will publish incorrect information. This is a **user-visible documentation defect at release time**. |

### widgets/program_sim_panel.py

| Line | Reference | Classification |
|------|-----------|----------------|
| 267 | `# TODO: implement mode switching logic` | **Source comment — NOT simulator-related** — `_mode_var` here is `"csv"` vs `"manual"` (data-entry mode, not hardware/simulator mode). This is unrelated to the simulator removal audit. Included because the search term `mode switch` matched it. No cleanup needed from this audit. |

---

## Danger Assessment

The following references pose an active risk of misleading users or breaking builds:

| Risk | File | Line | Issue |
|------|------|------|-------|
| **HIGH — user-visible lie at runtime** | `scripts/install.sh` | 114 | Tells users the app will run in simulator-only mode when it will actually fail to start |
| **HIGH — user-visible lie at release** | `scripts/create-release.sh` | 34–39 | Release note template advertises a removed feature |
| **MEDIUM — packaging build failure** | `docs/reference/packaging-configuration-plan.md` | 39, 116 | `cp` command references deleted `simulator/` directory — build will fail if this plan is executed |
| **MEDIUM — spec mock leaks** | `tests/test_card_safety.py` | 18 lines | `cm._simulator = None` on live `CardManager` — spurious attribute; currently harmless but could mask a spec violation if `CardManager` is ever made strict |
| **LOW — misleading test names** | `tests/test_card_manager_full.py` | 130–170 | Valid hardware tests named "test_simulator_*"; could confuse future maintainers into deleting them |
| **LOW — inaccurate module docstrings** | `tests/test_e2e_contracts.py`, `test_from_read_card.py` | 18, 4 | Stale docstring references to SimulatorBackend |

---

## Recommended Cleanup Sequence

When cleanup is approved, the following sequence minimizes risk:

1. **Scripts first (dangerous items):**
   - `scripts/install.sh:114` — replace fallback message
   - `scripts/create-release.sh:34–39` — remove or replace simulator section
   - `scripts/install-macos.sh:4` — update comment

2. **User-facing docs (high-traffic pages first):**
   - `README.md` — remove simulator feature entry and getting-started section
   - `docs/how-to/install.md` — remove simulator references
   - `docs/how-to/troubleshooting.md` — remove simulator section
   - `docs/index.md` — update description
   - `docs/explanation/architecture.md` — remove simulator backend section, update diagram
   - `docs/reference/cli-integration.md` — remove simulator section and CLIBackend row
   - `docs/reference/configuration.md` — remove `simulator_mode` key
   - `docs/tutorials/batch-programming.md` — remove dry-run section
   - `CLAUDE.md` — remove `simulator/` from arch tree, fix signal table entry

3. **Remaining user-facing docs (lower traffic):**
   - `docs/explanation/adm1-security.md`
   - `docs/explanation/suci-vs-non-suci.md`
   - `docs/auto-read-flow.md`
   - `docs/how-to/network-share-setup.md`
   - `docs/reference/card-types.md`

4. **Packaging plan:**
   - `docs/reference/packaging-configuration-plan.md` — remove `simulator/` from `cp` command

5. **Active tests (safe-to-clean stale artifacts):**
   - `tests/test_card_safety.py` — remove 18× `cm._simulator = None`
   - `tests/test_audit_fixes.py`, `test_batch_manager.py`, `test_batch_manager_full.py` — remove `cm.is_simulator_active = False`
   - `tests/test_card_manager_full.py` — rename `test_simulator_*` methods to `test_program_*`; update docstrings
   - `tests/test_e2e_contracts.py`, `test_from_read_card.py` — update module docstrings

6. **Do not touch (historical records — dangerous to remove):**
   - `docs/reference/remove-simulator-mode-plan.md` — decision record
   - `docs/reference/test-baseline-ubuntu-post-simulator-removal.md` — authoritative baseline
   - `docs/reference/test-baseline-macos-v0.5.50.md` — frozen snapshot
   - `docs/reference/post-v0.5.50-forensic-report.md` — forensic record
   - `docs/reference/current-platform-refactor-status.md` — status history
   - `test_audit_report.md` — pre-removal audit snapshot
   - `docs/TODO.md` — planning notes (may rephrase, never delete)

7. **Skip (globally skipped file, delete when PyQt6 migration completes):**
   - `tests/test_main_app.py` — entire file is already skipped; do not clean individual simulator references; delete the whole file as part of the PyQt6 migration cleanup.

---

## What Would Be Dangerous to Remove

- Any entry in `docs/reference/test-baseline-ubuntu-post-simulator-removal.md` — it is the
  authoritative regression guard.
- Any entry in `docs/reference/remove-simulator-mode-plan.md` — it is the decision record
  explaining why simulator mode was removed and which commits did what.
- The `# TODO: implement mode switching logic` comment in `widgets/program_sim_panel.py:267`
  — it is about CSV/manual input mode, not simulator mode, and is still valid.
- Test methods in `tests/test_card_manager_full.py` named `test_simulator_*` — they test
  the hardware programming path and must be **renamed** rather than deleted.
