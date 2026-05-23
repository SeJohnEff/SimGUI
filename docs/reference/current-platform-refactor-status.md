# Current Platform Refactor Status

**Last updated:** 2026-05-23
**Head commit:** `92d8fe4` — chore: delete obsolete simulator package

---

## Active Ubuntu Regression Baseline

| Outcome | Count |
|---|---|
| Passed | 1900 |
| Failed | 0 |
| Skipped | 313 |

Run time: 24.63s. Recorded after simulator-removal Commit 9.

Authoritative document: `docs/reference/test-baseline-ubuntu-post-simulator-removal.md`

**Any future Ubuntu run that drops below 1900 passed without an approved
explanation is a regression and must be reverted.**

---

## Historical Baseline Progression

| Baseline | Passed | Skipped | Document |
|---|---|---|---|
| v0.5.50 | 2051 | 321 | `test-baseline-ubuntu-v0.5.50.md` |
| Post qt_main removal | 2123 | 323 | `test-baseline-ubuntu-post-qt-main-removal.md` |
| Post simulator removal | **1900** | **313** | `test-baseline-ubuntu-post-simulator-removal.md` ← **active** |

The reduction from 2123 to 1900 is entirely intentional: simulator mode
was removed as a product feature. Tests that validated simulator behavior
(~220 tests) were deleted or dropped when the `simulator/` package and
`AppMode` enum were removed. No hardware-path tests were lost. The
behavioral contract for card programming, authentication, card detection,
retry safety, CSV handling, batch sequencing, and state machine behavior
is fully intact.

---

## Completed Work

### 1. Rollback to v0.5.50 Ubuntu baseline
- Post-v0.5.50 commits had accidentally broken Ubuntu application logic.
- All tainted commits rolled back; main restored to v0.5.50.
- Post-v0.5.50 tags deleted from origin.
- Forensic report written: `docs/reference/post-v0.5.50-forensic-report.md`.

### 2. Phase 0–4 platform safety documentation
- Platform refactoring ground rules added to `CLAUDE.md` (Rules 1–10,
  Forensic Guardrails 1–7).
- Platform boundary design: `docs/reference/platform-boundary-design.md`.
- State machine documented as authoritative: `docs/reference/state-machine.md`.
- Forensic prohibitions derived from the tainted-history analysis.

### 3. Optional `platform_runtime` adapter (Stage 2)
- `platform_runtime.py` added as an **optional, locally-imported** module.
- Ubuntu stub returns Linux-correct values; macOS stub returns macOS values.
- All common modules import it with `try/except ImportError` inside the
  one function that needs it — never at module scope.
- Ubuntu test suite passes with or without the module present.

### 4. PCSC reader index seam (Stage 3)
- `PCSC_READER_INDEX` constant extracted in `card_manager.py` and
  `card_watcher.py`.
- Seam allows macOS to override the reader index without branching in
  business logic. Design documented in
  `docs/reference/pcsc-parameter-seam-design.md`.

### 5. macOS hardware-gated tests
- `tests/test_e2e_contracts.py::TestHardwareGated` added.
- Gated behind `SIMGUI_HW_TEST=1`; skipped in normal CI runs.
- Tests cover macOS card detection without asserting ICCID presence
  (blank gialersim cards have none).

### 6. macOS source install documentation
- `docs/how-to/install.md` updated with macOS source-install instructions.
- Covers `~/pysim` path, `PYSIM_PATH` env var, pcscd vs PCSC.framework.
- UTM USB passthrough limitation documented.

### 7. Platform-aware network storage and scanner tests
- Linux CIFS assertions (`-t cifs`, `-o guest`, uid/gid options) skipped
  on macOS with explicit reason; covered in `TestBuildMountCmdMacOS`.
- avahi-browse scanner tests skipped on macOS; dns-sd equivalent added.
- Sudoers check tests skipped on macOS; macOS always-True behavior
  separately asserted.
- Tag: `v0.5.52-platform-aware-tests`.

### 8. qt_main.py removal
- Quarantined Phase 0 stub deleted.
- `debian/rules` `cp` line updated to remove the file from `.deb` builds.
- `CLAUDE.md` quarantine notice replaced with a tombstone.
- `requirements.txt` stale comment removed.
- Tag: `v0.5.53-remove-qt-main`.

### 9. Baseline documentation and CLAUDE.md updates
- `docs/reference/test-baseline-ubuntu-post-qt-main-removal.md` created
  as the active regression guard (2123/323).
- `docs/reference/qt_main_audit.md` marked complete.
- `docs/reference/packaging-configuration-plan.md` §2 and §3 updated to
  "COMPLETED".
- `CLAUDE.md` Testing section and Rule 1 updated to reflect current count.
- Tag: `v0.5.54-post-qt-main-baseline`.

### 10. Simulator mode removal (Commits 1–10)
- All simulator runtime branches removed from `card_manager.py` and
  `batch_manager.py`.
- `AppMode`, `SimulatorInfo`, `mode_changed` signal, and
  `simulator_info_changed` signal removed from `state_manager.py`.
- Simulator UI (Card menu hardware/simulator toggle, mode status display)
  removed from `main.py`.
- `simulator/` package deleted: `SimulatorBackend`, `VirtualCard`,
  `CardDeck`, `SimulatorSettings` no longer exist.
- `dialogs/simulator_settings_dialog.py` deleted.
- `"simulator_mode"` settings key removed from `SettingsManager`.
- `state-machine.md` `mode_changed` / `AppMode` signal row removed
  (standalone commit, human-approved).
- Simulator-feature tests deleted; test-double tests rewritten with
  `unittest.mock` to preserve hardware-path coverage.
- New Ubuntu baseline: **1900 passed, 313 skipped**.
- Authoritative document: `test-baseline-ubuntu-post-simulator-removal.md`.

---

## Current macOS Status

macOS support is **source-install only**. No packaged distribution exists.

| Item | Status |
|---|---|
| Source install (`python3 main.py`) | Works on macOS M4 with `~/pysim` |
| `platform_runtime.py` adapter | Present; optional; locally imported |
| PCSC reader index seam | In place |
| Hardware card tests | Gated behind `SIMGUI_HW_TEST=1` |
| `.app` / `.pkg` bundle | Blocked — asset-load issue unresolved |
| PyInstaller bundle | Blocked — same asset-load issue |
| macOS business-logic changes | Not permitted |

macOS-specific code is limited to thin platform adapter values.
No SIM card logic, authentication logic, or state machine behavior
differs by platform.

---

## What Remains Safe to Do Next

- **No urgent code refactor is required.** The codebase is stable and the
  Ubuntu baseline is protected.
- **Optional:** Investigate the macOS `.app`/`.pkg` asset-load blocker
  (PNG loading from temp directory at GUI init). See `docs/TODO.md`.
- **Optional:** Design macOS packaging approach (`.pkg`, notarization,
  Homebrew formula) once the asset-load issue is diagnosed. Requires
  separate written approval before implementation.
- **Optional:** Add more macOS-specific thin adapter coverage (e.g.,
  NFS mount path differences) if needed for real-world macOS usage.

---

## What Remains Blocked

The following actions require **explicit separate written approval** before
any implementation begins:

- PyInstaller bundle, `.app`, or `.pkg` packaging — blocked until
  asset-load issue is diagnosed and a packaging approach is approved.
- Any split of the state machine (`CardState`, `CardWatcher`,
  `StateManager`) across platforms.
- Any macOS-specific business logic (card detection algorithms, ADM1
  handling, programming flows, auth decisions).
- Amending `state-machine.md` without explicit approval.
- Using post-v0.5.50 tainted-history commits as a source of logic.

---

## Required Guardrails (Summary)

1. Ubuntu behavior is the only behavioral authority.
2. Common logic must remain common — no duplication across platforms.
3. No platform branches in `card_manager.py` or `card_watcher.py` except
   the existing `_find_cli_tool()` path adapter.
4. `platform_runtime.py` must remain optional and locally imported only.
5. `state-machine.md` is authoritative. If code and doc disagree, stop
   and report — do not guess.
6. One concern per commit; run tests after every behavioral change.
7. macOS-specific code may only provide thin platform adapter values.
   It must never define or change SIM/card/auth/state behavior.

Full rules: see `CLAUDE.md` Platform Refactoring Ground Rules (Rules 1–10)
and Forensic Guardrails (Prohibitions 1–7).
