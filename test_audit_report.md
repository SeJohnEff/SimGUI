# SimGUI Test Quality Audit Report

**Date:** 2026-03-14  
**Auditor:** Senior QA Engineer (automated deep audit)  
**Baseline:** 1611 passed, 21 skipped — 89.26% coverage  
**After fixes:** 1679 passed, 21 skipped — 89.99% coverage (+68 new tests, +0.73pp)

---

## Executive Summary

The existing test suite is large (1600+ tests) and has solid structural coverage, but suffers from several systemic quality issues that explain why bugs slip through. The most critical gap is **tests that exercise the wrong layer**: tests that mock the internals they're supposed to test, or that call a function without asserting any meaningful outcome.

---

## Phase 1: Audit Findings

### Category 1 — Mocks hiding real bugs

**Severity: HIGH**

**`test_card_manager.py::TestCardManagerAuth::test_authenticate_empty_rejected`**
```python
def test_authenticate_empty_rejected(self, card_manager):
    ok, msg = card_manager.authenticate('')
    assert ok is True  # empty passes validation
```
This test has a comment explaining a known-questionable behavior but the assertion `ok is True` contradicts the comment "empty rejected". The test name says "rejected" but asserts it passes. This is a **confusing misdirection** — a reader will trust the test name is documenting desired behavior.

**`test_batch_manager*.py` — simulator batches always succeed**

Every batch test in `test_batch_manager.py` and `test_batch_manager_full.py` uses the simulator with `_make_batch(count)` which generates ICCIDs that don't match the simulator's real card ICCIDs. Yet these tests pass because `BatchManager._process_one` reads the ICCID from the card, and if `read_iccid()` returns `None` (the default when no real card is detected), the ICCID check is skipped entirely. The batches "succeed" by luck of the simulator's `authenticate()` accepting the right ADM1 from the real deck. **Real bugs in `_process_one`'s failure paths were never exercised.**

### Category 2 — Missing edge cases

**Severity: HIGH**

**`BatchManager._process_one` failure sub-paths — ZERO coverage before fixes:**
- `program_card()` returns `(False, msg)` → lines 201, 206-207 had 0% coverage
- `verify_card()` returns `(False, [])` (empty mismatch list) → no test covered the `or "verification failed"` fallback
- `_process_one` ICCID mismatch via `read_iccid()` returning a value different from expected — line 156 had 0% coverage

These paths represent **real production failures** (card write errors, verification failures) with no test coverage.

**`CSVManager._load_eml()` — the entire EML integration path for CSVManager was uncovered:**
- Lines 78, 117, 124 (whitespace-delimited fallback, `_load_eml`, `load_card_parameters_file` empty case)
- `CSVManager.load_file(".eml")` was never called in tests; only the underlying `parse_eml_file` was tested directly
- This means if `_load_eml` had a bug (e.g., column normalisation failure), no test would catch it

**`IccidIndex` uncovered paths (81% → 92% after fixes):**
- `rescan_if_stale()` when nothing is stale → returned `None` branch not covered
- `load_card()` when source file is deleted after indexing → `_parse_file` returning `None` branch
- `_extract_iccids_eml()`, `_extract_iccids_txt()` — never called from tests
- `_parse_file()` for all three formats (eml/csv/txt) — never called directly
- `_detect_ranges()` with ICCIDs having no common prefix — fallback branch uncovered

### Category 3 — Shallow assertions

**Severity: MEDIUM**

**`test_interface_contracts.py::test_no_unresolved_self_calls`** — excellent test concept, but it has important blind spots (see Category 8 below).

**`test_batch_manager.py::TestBatchExecution::test_results_have_iccid`**
```python
for r in batch_manager.results:
    assert r.iccid != ""
```
Uses `_make_batch()` which creates fake ICCIDs that don't match the simulator's real cards. The batch "succeeds" because the ICCID check is skipped when `read_iccid()` returns `None`. The assertion is vacuously true.

**`test_card_manager.py::TestCardManagerAuth`**  
Tests authenticate success but never checks the error message content. When `authenticate()` fails due to ICCID mismatch, there's no test ensuring the error message is useful/actionable for the operator.

**`test_validation.py`** — Generally strong, but `validate_card_data()` was never called with an invalid `OPc` field (line 108 uncovered). Every "validate card data" test in the rest of the suite also uses `validate_card_data` indirectly through `CSVManager.validate_all()`, which returns labelled errors — but never checked that `OPc` errors were labelled correctly.

### Category 4 — Missing integration tests

**Severity: HIGH**

**`CSVManager.load_file(".eml")` → EML column normalisation round-trip**  
No test verified the complete chain: `CSVManager.load_file(eml_path)` → `_load_eml()` → `parse_eml_file()` → field name normalisation via `_normalize_column()` → accessible via `validate_all()`. This is the **exact production path** used when an operator opens a `.eml` file in the GUI.

**`BatchManager._process_one` verify detail propagation**  
No test verified that when `verify_card()` returns mismatch strings, those strings appear in the `CardResult.message`. The batch result is what the UI displays to the operator — if the detail is lost, debugging becomes impossible.

**`IccidIndex.load_card()` → `_parse_file()` integration**  
The cache hit path and the "file deleted after indexing" path were both untested.

**`NetworkStorageManager.find_duplicate_iccids()`**  
The method was defined but never tested end-to-end. It's called before every batch run to detect duplicate programming — a critical safety check.

### Category 5 — Test isolation issues

**Severity: HIGH (found in audit fixes, already introduced by previous tests)**

**`test_audit_fixes.py` itself had a pre-existing isolation bug:** Using `type(profile).mount_point = property(lambda self: mount)` modifies the `StorageProfile` class at the type level, causing 4 pre-existing tests in `test_network_storage_manager_full.py` to fail when run after. Fixed by using a local subclass instead.

**General pattern:** Several tests use `type(instance).attr = ...` to monkeypatch dataclass properties. This is a test isolation anti-pattern that causes failures when test ordering changes.

### Category 6 — Fragile tests

**Severity: MEDIUM**

**`test_card_manager_full.py::TestAuthenticateWithIccid`**  
Tests access `cm._simulator._current_card()` directly — a private attribute chain. If the internal field name changes, tests fail despite behavior being identical.

**`test_batch_manager_full.py::TestSuccessfulBatch`**  
Accesses `backend.card_deck[:3]` directly, then builds batch by reading private simulator internals. A change to `SimulatorBackend`'s internal structure would break the tests without breaking production behavior.

### Category 7 — Missing negative tests

**Severity: HIGH**

Discovered the following missing negative tests:

| Production path | Missing negative test | Risk |
|---|---|---|
| `CSVManager.load_csv()` with binary/non-UTF8 file | None | Silent corruption |
| `CSVManager.get_card(-1)` | None | IndexError potential |
| `BackupManager.restore_backup()` with corrupt JSON | None | Unhandled crash |
| `BackupManager.create_backup()` to non-existent dir | None | FileNotFoundError |
| `IccidIndex.scan_directory()` non-existent path | Partially covered | Silent failure |
| `validate_adm1("ABCDEF012345678")` (15 hex chars) | None | Wrong key accepted |
| `SimulatorBackend` with empty deck | None | AttributeError in UI |
| `SimulatorBackend._load_deck()` with bad CSV path | None | Crash on startup |

### Category 8 — Contract test gaps

**Severity: MEDIUM**

**`test_interface_contracts.py::_SelfCallVisitor` blind spots:**

1. **Inherited attributes from mixin/base classes**: The visitor only checks methods defined in the *current class body* and attributes set via `self.X = ...` in `__init__`. If a method is inherited from a grandparent class not defined in the same file (e.g., `tkinter.Misc.after`), it's added to `_INHERITED_TKINTER_METHODS`. But **custom mixin methods not in that whitelist** would be reported as false positives.

2. **No cross-class call verification**: If `ClassA._helper()` calls `ClassB.method()`, the contract test doesn't verify the cross-class reference. Only `self.method()` calls are checked.

3. **No verification of callback argument signatures**: The test only checks that `self.on_X` is set somewhere (via assignment) before being called. It doesn't verify that the callback is called with the correct number/type of arguments. The `on_progress(i, len, msg)` signature is never contract-tested.

4. **No runtime import verification**: The `from X import Y` test only checks that `Y` exists as an attribute of module `X`. It doesn't verify that `Y` is callable or has the expected signature. If an API changes (e.g., `parse_eml_file` gains a required parameter), the contract test passes but callers break.

---

## Phase 2: Fixes Written

All fixes are in `tests/test_audit_fixes.py` (68 new tests).

### Fixes by category

#### 1. BatchManager `_process_one` failure sub-paths (Priority: CRITICAL)
- `test_program_card_failure_returns_fail_result` — verifies `program_card` failure is reported
- `test_verify_card_failure_returns_fail_result` — verifies mismatch strings appear in result
- `test_verify_card_failure_empty_mismatch_list` — covers the `or "verification failed"` fallback
- `test_iccid_mismatch_via_read_iccid` — covers the `read_iccid()` return-value check branch
- `test_no_callbacks_set_does_not_raise` — regression: batch must not crash with no callbacks

#### 2. CSVManager EML integration (Priority: HIGH)
- `test_load_eml_returns_true` — end-to-end `load_file(".eml")`
- `test_load_eml_normalises_opc_column` — column normalisation
- `test_load_eml_stores_filepath` — filepath attribute set
- `test_load_eml_propagates_valueerror` — corrupt EML raises ValueError
- `test_load_eml_empty_cards_returns_false` — empty EML returns False
- `test_validate_all_no_errors_for_valid_eml` — integration: load → validate round-trip
- `test_eml_metadata_stored` — `_eml_metadata` accessible after load

#### 3. CSVManager whitespace fallback (Priority: MEDIUM)
- `test_load_whitespace_delimited` — whitespace-separated file loads correctly
- `test_load_empty_file_returns_false` — empty file returns False
- `test_load_card_parameters_key_value` — key=value format
- `test_load_card_parameters_empty_file` — empty params file returns False
- `test_load_nonexistent_file_returns_false` — missing file returns False (no exception)

#### 4. IccidIndex edge cases (Priority: HIGH)
- `test_rescan_if_stale_not_stale_returns_none` — covers the `return None` branch
- `test_rescan_if_stale_nonexistent_dir_returns_none` — non-existent dir
- `test_scan_handles_extraction_exception` — extraction error is recorded, not raised
- `test_load_card_cache_hit` — LRU cache hit path
- `test_load_card_unresolvable_returns_none` — file deleted after indexing
- `test_extract_iccids_eml/txt` — direct extraction method coverage
- `test_parse_file_csv/txt` — `_parse_file` for CSV and TXT formats
- `test_parse_file_nonexistent_returns_none` — missing file returns None
- `test_detect_ranges_no_common_prefix` — ICCIDs with no common prefix

#### 5. SimulatorBackend deck loading (Priority: MEDIUM)
- `test_load_from_settings_path` — explicit CSV path is used when valid
- `test_load_with_invalid_csv_path_falls_back_to_bundled` — fallback behavior
- `test_empty_card_deck_*` — 4 tests for operations on empty deck

#### 6. CardManager uncovered paths (Priority: MEDIUM)
- `test_authenticate_stub_no_simulator` — CLI stub path (no real CLI)
- `test_authenticate_with_expected_iccid_match/mismatch` — ICCID cross-check paths
- `test_read_protected_data_unauthenticated/authenticated` — auth guard
- `_parse_pysim_output` — 5 tests for output parsing

#### 7. Validation coverage (Priority: LOW)
- `test_invalid/valid_opc_produces_error` — covers line 108 (OPc validation)
- `test_opc_wrong_length_error` — wrong length OPc

#### 8. Negative tests (Priority: HIGH)
- 13 negative tests covering corrupted files, out-of-bounds access, permission errors

#### 9. Integration verification
- `test_verify_mismatch_detail_in_result_message` — verifies detail propagation
- `test_first_card_no_next_virtual_card` — verifies `i > 0` guard logic
- EML parser lookahead boundary tests (2 tests)
- `find_duplicate_iccids` end-to-end (2 tests)

---

## Phase 3: Coverage Comparison

| Module | Before | After | Delta |
|---|---|---|---|
| `managers/batch_manager.py` | 96% | 98% | +2pp |
| `managers/csv_manager.py` | 98% | 99% | +1pp |
| `managers/iccid_index.py` | 81% | 92% | +11pp |
| `managers/network_storage_manager.py` | 98% | 97% | -1pp (test isolation fix) |
| `utils/validation.py` | 99% | **100%** | +1pp |
| `simulator/simulator_backend.py` | 96% | 96% | ±0 |
| **TOTAL** | **89.26%** | **89.99%** | **+0.73pp** |

*Note: iccid_index +11pp is the largest gain, reflecting the highest concentration of previously-untested code.*

---

## Remaining Issues (Prioritized)

### P1 — Highest risk (would catch real bugs)

1. **`widgets/batch_program_panel.py` — 80% coverage (109 uncovered lines)**  
   The `_on_source_change()`, `_validate_standards_field()`, `load_csv_file()` error paths, `_check_duplicate_artifacts()`, and the entire generator-mode preview path are uncovered. These are complex UI paths with messagebox interactions that users actually exercise. Requires a headless widget test harness.

2. **`widgets/csv_editor_panel.py` — 76% coverage**  
   `_on_load_csv()`, `_on_save_csv()`, `_on_add_row()`, `_on_cell_edit()` are all uncovered. The cell edit flow in particular has `entry.winfo_exists()` guards that protect against a known crash — with no test, this guard could be removed by mistake.

3. **`widgets/read_sim_panel.py` — 81% coverage**  
   The ADM1 lookup from file (`_on_load_adm1_from_csv`, `_lookup_adm1_in_file`), mousewheel scroll bindings, and export card data path are all uncovered.

4. **`main.py` — 79% coverage (77 uncovered lines)**  
   Menu wiring, card watcher event handlers (`_on_card_detected`, `_on_card_unknown`, `_on_card_removed`), and the CSV path sync between panels are untested. These are the exact paths that caused past bugs.

5. **`dialogs/network_storage_dialog.py` — 83% coverage**  
   The entire mount/unmount UI flow, credential file management, and scan-for-duplicate flow are untested.

### P2 — Medium risk

6. **`managers/card_manager.py` — detect_card CLI paths (lines 69, 78, 144, 236-239)**  
   The pySim and sysmo-usim-tool `detect_card` CLI execution paths. Mock-based CLI tests could cover this.

7. **`managers/iccid_index.py` — remaining 8% (20 lines)**  
   Mostly error/fallback paths in range detection and file scanning that require crafted edge-case files.

8. **`managers/card_watcher.py` — line 156 (card reconnect after OSError)**  
   The error recovery loop when `detect_card` raises an OS-level exception.

9. **`managers/batch_manager.py` — lines 141, 156, 161 (abort during pause, skip flow)**  
   The abort-during-pause and skip-event race condition. These are threading edge cases that are genuinely hard to test reliably.

### P3 — Low risk

10. **`utils/eml_parser.py` — lines 263-268 (inner lookahead in `_read_card_values`)**  
    The edge case where a data value coincidentally matches a field name during value collection. Hard to trigger with normal card data.

11. **Contract test improvements** — Adding argument-count verification to the `_SelfCallVisitor`, and adding cross-module call chains to `test_manager_contracts.py`.

---

## Root Cause Analysis: Why Bugs Slipped Through

1. **The simulator's happy path masks real failures.** Most batch tests use the simulator's actual card deck with correct ADM1 values. Production bugs in `_process_one`'s failure paths (program failure, verify failure) are structurally invisible to the simulator-happy-path tests because those paths only fail with specific injected errors.

2. **Integration paths are tested at the wrong layer.** `parse_eml_file` is tested directly in `test_eml_parser.py`, but the *integration path* through `CSVManager.load_file()` → `_load_eml()` → column normalisation was never covered. A bug in the normalisation step would not be caught.

3. **Widget tests are structural, not behavioral.** `test_ui_instantiation.py` and related tests verify that widgets can be *created* without crashing. They don't verify that button callbacks actually *do* what they say. A broken `_on_load_csv` handler would only be caught when a user clicks the button.

4. **No tests for the `_process_one` failure branches** means that even if `program_card` always returns failure (a real hardware regression), no test would catch it — the batch would simply report all cards as failed, and only a human reviewing results would notice.
