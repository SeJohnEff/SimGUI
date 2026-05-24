# Stale Simulator Reference Audit

**Original audit date:** 2026-05-23
**Refresh date:** 2026-05-24
**Branch:** main
**Head commit:** `2174434` — docs: remove simulator mode from remaining user docs
**Scope:** All references to `simulator`, `simulation`, `virtual card`, `virtual_card`,
`card_deck`, `AppMode`, `simulator_mode`, `hardware mode`, `mode switch`,
`SimulatorBackend` across docs, scripts, tests, and packaging.

---

## Cleanup Progress Summary

| Commit | Description | Files changed |
|--------|-------------|---------------|
| `ed0f184` — Commit 1 | High-risk script messages | `scripts/install.sh`, `scripts/create-release.sh` |
| `01adf97` — Commit 2 | Packaging plan docs | `docs/reference/packaging-configuration-plan.md` |
| `9a27676` — Commit 3 | Live Debian packaging | `debian/rules` |
| `cc4423a` — Commit 4 | Test stale references | `test_card_safety.py`, `test_card_manager_full.py`, `test_e2e_contracts.py`, `test_from_read_card.py` |
| `f4e718c` — Commit 5 | High-visibility user docs | `README.md`, `docs/how-to/install.md`, `docs/explanation/architecture.md`, `docs/index.md` |
| `2174434` — Commit 6 | Remaining lower-traffic user docs | `adm1-security.md`, `suci-vs-non-suci.md`, `auto-read-flow.md`, `network-share-setup.md`, `card-types.md`, `cli-integration.md`, `configuration.md`, `tutorials/batch-programming.md` |

---

## Production Code Status

**Zero simulator references remain in production code.**

Verified with `grep -rn "simulator\|SimulatorBackend\|AppMode\|is_simulator_active\|_simulator\|card_deck\|virtual_card" managers/ main.py` — empty result.

The only non-historical Python hit outside tests is `widgets/program_sim_panel.py:267`
(`# TODO: implement mode switching logic`) which is CSV/manual input mode, not
hardware/simulator mode. Confirmed not simulator-related in the original audit.

---

## User-Facing Docs Status

**One stale section remains** — `docs/how-to/troubleshooting.md` was not included in
Commits 5 or 6. It still contains an entire "Simulator mode" section.

All other user-facing docs cleaned. No current simulator-as-feature claims remain in
README.md, any how-to guide (except troubleshooting), any explanation doc, any tutorial,
any reference doc, or any index page.

---

## Remaining References by File

### docs/how-to/troubleshooting.md — STALE, NOT YET CLEANED

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 211 | `## Simulator mode` heading | **User-facing stale doc — should clean** |
| 213 | `### Simulator shows wrong card type` subheading | **User-facing stale doc — should clean** |
| 215 | "The simulator loads 20 real sysmoISIM-SJA5 profiles …" | **User-facing stale doc — should clean** |
| 217 | `### Simulator mode left enabled accidentally` subheading | **User-facing stale doc — should clean** |
| 219 | "Open Settings → uncheck **Simulator Mode**. The status bar shows "SIMULATOR" …" | **User-facing stale doc — should clean** |
| 251 | "5. Whether the issue reproduces in simulator mode" | **User-facing stale doc — should clean** |

**Action:** Remove lines 211–219 (the full "Simulator mode" section) and remove item 5
on line 251 from the bug-report checklist. This is the last user-facing stale section.

---

### CLAUDE.md — STALE (project control doc)

| Line | Reference | Classification |
|------|-----------|----------------|
| 68 | `simulator/` in architecture tree | **Project control doc stale — should clean** — directory deleted |
| 205–206, 292–303 | "post simulator removal" baseline references | **Historical/internal** — OK to keep |
| 466 | `mode_changed(AppMode) # HARDWARE ↔ SIMULATOR` in signal table | **Project control doc stale — should clean** — signal and enum deleted |

**Action:** Remove `simulator/` from the arch tree (line 68); remove or correct the
`mode_changed(AppMode)` signal entry (line 466). The baseline references (205–206,
292–303) are historically accurate and must remain.

---

### scripts/install-macos.sh — STALE (low risk)

| Line | Reference | Classification |
|------|-----------|----------------|
| 4 | "Casual users should just download SimGUI.app and run it (simulator mode works out of the box)." | **Script stale reference** — `.app` distribution is blocked; simulator mode removed |

**Action:** Update the comment to remove simulator claim. Low risk — comment only,
no behavioral impact.

---

### tests/test_audit_fixes.py — STALE, ACTIVE TEST

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 100, 111, 136, 156, 175, 838 | `cm.is_simulator_active = False` on `MagicMock(spec=CardManager)` | **Test stale reference — should clean** — dead mock attribute write; `CardManager` no longer has `is_simulator_active`. Harmless because MagicMock accepts arbitrary writes even under spec, and `batch_manager.py` no longer reads this attribute. |

---

### tests/test_batch_manager.py — STALE, ACTIVE TEST

| Line | Reference | Classification |
|------|-----------|----------------|
| 23 | `cm.is_simulator_active = False` on plain `MagicMock()` | **Test stale reference — should clean** |

---

### tests/test_batch_manager_full.py — STALE, ACTIVE TEST

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 30 | `cm.is_simulator_active = False` on plain `MagicMock()` | **Test stale reference — should clean** |
| 389, 407 | Comments `# real CM, no simulator — hardware path` | **Test stale reference** — comment is harmless but no longer meaningful; hardware is the only path |

---

### tests/test_phase1_bugfixes.py — STALE, ACTIVE TEST (newly found)

| Lines | Reference | Classification |
|-------|-----------|----------------|
| 139, 192, 340 | `cm._simulator = None` on live `CardManager.__new__(CardManager)` instances | **Test stale reference — should clean** — `_simulator` no longer exists on `CardManager`; identical in nature to the 18 occurrences removed from `test_card_safety.py` in Commit 4. Not in the original audit because the original grep focused on `test_card_safety.py` for this pattern. |

---

### tests/test_widget_methods_comprehensive.py — STALE, ACTIVE TEST (newly found)

| Line | Reference | Classification |
|------|-----------|----------------|
| 383 | `"dialogs.simulator_settings_dialog": _mock.MagicMock()` in sys.modules patch dict | **Test stale reference — should clean** — `dialogs/simulator_settings_dialog.py` was deleted in v0.5.55-hardware-only. Patching a deleted module has no effect and misleads readers. Not in original audit. |

---

### tests/test_main_app.py — GLOBALLY SKIPPED (unchanged from original audit)

All tests in this file carry `pytestmark = pytest.mark.skip(reason="tkinter mocking
incompatible with PyQt6 migration")`. All simulator references are inert — the tests
never execute. **Do not clean individual references; delete the whole file as part of
the PyQt6 migration cleanup.**

---

### Historical/internal docs — DO NOT TOUCH

These files contain simulator references that are permanently correct historical records.
They must not be edited.

| File | Classification |
|------|----------------|
| `docs/reference/remove-simulator-mode-plan.md` | **Historical record** — the removal decision and commit plan |
| `docs/reference/test-baseline-ubuntu-post-simulator-removal.md` | **Authoritative baseline** — must not change |
| `docs/reference/test-baseline-macos-v0.5.50.md` | **Frozen snapshot** |
| `docs/reference/post-v0.5.50-forensic-report.md` | **Forensic record** |
| `docs/reference/current-platform-refactor-status.md` | **Status history** |
| `docs/reference/packaging-configuration-plan.md` | **Planning doc** — already annotated in Commit 2 |
| `test_audit_report.md` (root) | **Pre-removal audit snapshot** |
| `docs/TODO.md:174,176` | **Internal planning notes** — future testing strategy, still valid context |
| `docs/PYQT6_MIGRATION_PLAN.md:17,150,313` | **Internal planning doc** — historical line counts, deleted-dialog entries |

---

## Key Confirmations

**Production code:** ✅ Zero simulator references. Hardware path is unconditional.

**User-facing docs:** ⚠️ One remaining section — `docs/how-to/troubleshooting.md` lines
211–219 and line 251 (missed in Commits 5–6). All other user-facing simulator claims
removed.

**CLAUDE.md:** ⚠️ Two stale entries (arch tree `simulator/` entry at line 68; signal
table `mode_changed(AppMode)` entry at line 466).

**Scripts:** ⚠️ `scripts/install-macos.sh:4` — stale comment only.

**Tests (active):** ⚠️ Three active test files still have dead mock attributes:
- `test_audit_fixes.py` — 6× `cm.is_simulator_active = False`
- `test_batch_manager.py` — 1× `cm.is_simulator_active = False`
- `test_batch_manager_full.py` — 1× `cm.is_simulator_active = False`, 2× comments
- `test_phase1_bugfixes.py` — 3× `cm._simulator = None` (newly found)
- `test_widget_methods_comprehensive.py` — 1× deleted-dialog in sys.modules patch (newly found)

---

## Recommendation

**One final cleanup commit is needed.** Suggested scope:

**Commit 7 — final simulator reference cleanup:**

*Docs (user-facing):*
- `docs/how-to/troubleshooting.md` — remove lines 211–219 (simulator section); remove item 5 on line 251

*Project control doc:*
- `CLAUDE.md` — remove `simulator/` from arch tree (line 68); remove `mode_changed(AppMode)` signal entry (line 466)

*Script:*
- `scripts/install-macos.sh` — update line 4 comment

*Active tests:*
- `tests/test_audit_fixes.py` — remove 6× `cm.is_simulator_active = False`
- `tests/test_batch_manager.py` — remove 1× `cm.is_simulator_active = False`
- `tests/test_batch_manager_full.py` — remove 1× `cm.is_simulator_active = False`, update 2× comments
- `tests/test_phase1_bugfixes.py` — remove 3× `cm._simulator = None`
- `tests/test_widget_methods_comprehensive.py` — remove the `simulator_settings_dialog` entry from the sys.modules patch dict

*Not included (leave for PyQt6 migration cleanup):*
- `tests/test_main_app.py` — globally skipped; delete entire file when PyQt6 migration is complete

After Commit 7, the only remaining simulator references in the repository will be
in permanent historical/internal records (baselines, decision docs, forensic reports).
No further cleanup will be required.
