# Test Baseline — Ubuntu — Post Simulator Removal

This document records the authoritative Ubuntu expected result after the
intentional removal of simulator mode across Commits 1–9 of the
simulator-removal refactor sequence.

**Future regressions must be judged against this baseline.**

---

## Environment

| Field | Value |
|---|---|
| Platform | Ubuntu (ARM/aarch64, UTM VM) |
| Branch | `main` |
| Head commit | `92d8fe4` — chore: delete obsolete simulator package |

## Test command

```
python3 -m pytest tests/ -x -q
```

## Results

| Outcome | Count |
|---|---|
| Passed | 1900 |
| Failed | 0 |
| Skipped | 313 |

Run time: 24.63 seconds.

**Zero failures. All application tests pass.**

---

## Why the count differs from the post-qt_main baseline (2123/323)

The previous active baseline was **2123 passed, 323 skipped** (recorded in
`docs/reference/test-baseline-ubuntu-post-qt-main-removal.md`).

The count decreased because simulator mode was intentionally removed as a
product feature. All decreases are accounted for and approved:

| Change | Δ passed | Δ skipped | Commits |
|---|---|---|---|
| Rewrite test-double tests (mock-based) | 0 | 0 | Commit 1 |
| Delete simulator-feature tests | −179 | −1 | Commit 2 |
| Remove simulator routing (card_manager) | 0 | 0 | Commit 3 |
| Remove simulator routing (batch_manager) | 0 | 0 | Commit 4 |
| Remove AppMode / SimulatorInfo / signals | 0 | 0 | Commit 5 |
| Remove simulator UI and mode handlers | 0 | 0 | Commit 6 |
| Clean stale simulator settings references | −2 | 0 | Commit 7 |
| state-machine.md standalone edit | 0 | 0 | Commit 8 |
| Delete simulator/ package | −42 | −9 | Commit 9 |

The −179 in Commit 2 is caused by deleting tests that validated simulator
mode as a product feature (`test_simulator.py`, `test_simulator_full.py`,
`test_simulator_settings_logic.py`, and AppMode/simulator-startup cases).
These tests have no hardware equivalent — the feature is gone.

The −42 in Commit 9 comes from removing `TestSimulatorBackendDeckLoading`
and related tests in `test_audit_fixes.py` that imported from the deleted
`simulator/` package, plus 24 parametrized `test_interface_contracts.py`
entries that auto-generated from the deleted source files. Neither is a
regression.

None of these changes affect card programming, authentication, card
detection, retry safety, CSV handling, batch sequencing, or state machine
behavior. The hardware behavioral contract is fully intact.

---

## What changed about the product

- **Simulator mode is no longer a product feature.** The application has
  exactly one operational mode: hardware mode.
- **No simulator fallback.** When pySim is missing at startup, the
  application shows a clear install-guidance message and does not fall
  back to any simulated operation.
- **`simulator/` package deleted.** The `SimulatorBackend`, `VirtualCard`,
  `CardDeck`, and `SimulatorSettings` classes no longer exist.
- **`AppMode` enum deleted.** There is one operational mode; the enum,
  its signal (`mode_changed`), and all connected handlers are gone.

---

## Relationship to previous baselines

`docs/reference/test-baseline-ubuntu-post-qt-main-removal.md` records
the 2123/323 baseline after qt_main removal. It is now historical.

`docs/reference/test-baseline-ubuntu-v0.5.50.md` records the original
v0.5.50 contract (2051/321). It remains the historical record.

**This document supersedes both as the active regression guard for
Ubuntu correctness.**

Any future Ubuntu run that drops below **1900 passed** without an
approved explanation is a regression and must be reverted.
