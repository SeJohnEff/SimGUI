# Post-v0.5.50 Forensic Report

**Produced:** 2026-05-21 — Phase 4 of macOS refactoring preparation

This document is a read-only analysis of the tainted branch
`backup-before-rollback-0.5.50`. It records what classes of changes were
introduced after v0.5.50, why they were dangerous, and what must not be
repeated when macOS support is added correctly in a future phase.

---

## Available refs

| Ref | SHA | Description |
|---|---|---|
| `v0.5.50` | `5e5899a` | Production baseline — Ubuntu clean, 2051 passed, 0 failed |
| `backup-before-rollback-0.5.50` | `075183b` | Tainted tip — 8 commits ahead of v0.5.50 |

The tainted branch covers versions v0.5.51 through v0.5.58.

---

## Commit-by-commit summary

### v0.5.51 — f6ee4fa — Startup mode change

**Files changed:** `main.py`

Removed the conditional `if cli_backend == NONE: mode = SIMULATOR`. The app
now always starts in HARDWARE mode regardless of whether pySim is found.

**Risk:** Behavioral change to startup path. Ubuntu systems where pySim is
not installed at the expected location would have previously auto-entered
Simulator mode; they now start in Hardware mode and fail with "No card
reader". Low severity but a user-visible behavior change on any system with
an unusual pySim installation.

---

### v0.5.52 — 81554c2 — macOS packaging/runtime architecture

**Files changed:** `platform_runtime.py` (NEW), `managers/card_manager.py`,
`managers/network_storage_manager.py`, `managers/settings_manager.py`,
`dialogs/network_storage_dialog_qt.py`, plus new scripts and tests.

This is the highest-risk commit. Three things happened:

**1. New mandatory module introduced.**
`card_manager.py` now imports at the top:
```python
from platform_runtime import pysim_search_dirs, sysmo_search_dirs
```
This is a module-level import. On any Ubuntu system where `platform_runtime.py`
is absent, `import managers.card_manager` raises `ModuleNotFoundError` and
the entire application fails to start. All 2051+ Ubuntu tests that touch
CardManager would fail at collection time.

**2. Mount path made platform-dependent.**
```python
# Before (v0.5.50)
MOUNT_BASE = "/tmp/simgui-mounts"

# After (v0.5.52)
from platform_runtime import mount_base as _platform_mount_base, ...
MOUNT_BASE = _platform_mount_base()
```
The hardcoded Linux mount base `/tmp/simgui-mounts` is replaced by a
platform_runtime call. If `platform_runtime.mount_base()` returns a different
path on Linux (e.g. a macOS Library path), any mounted network share would
become invisible and mount operations would target the wrong directory.

**3. Credentials directory made platform-dependent.**
```python
# Before
self._cred_dir = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "simgui")

# After
self._cred_dir = _platform_cred_dir()
```
If `platform_runtime.credentials_dir()` returns a macOS-specific path, SMB
credential files written on Linux would land in a wrong directory and not be
found by subsequent mount operations.

---

### v0.5.53 — a221941 — Status bar / no-reader state

**Files changed:** `main.py`, `managers/card_watcher.py`,
`managers/card_manager.py`, `managers/settings_manager.py`,
`widgets/card_status_panel.py`, `widgets/program_sim_panel.py`,
`scripts/run-dev.sh`, `scripts/setup_macos_runtime.sh`

Added `on_reader_ready` callback to CardWatcher; added "Insert a SIM card..."
status text when reader becomes available. These are additive changes.

**Risk:** Moderate. `card_watcher.py` received new state-tracking additions.
`card_manager.py` received debug infrastructure (`_dbg()`, `SIMGUI_DEBUG`
env var) that is low risk but adds noise. The `on_reader_ready` callback
path may interact with state machine transitions.

---

### v0.5.54 — 79de1cb — PCSC contention on macOS

**Files changed:** `managers/card_watcher.py`, `managers/card_manager.py`,
`main.py`, `qt_main.py`

Two high-risk changes:

**1. Platform branch in `CardManager._probe_card()`.**
```python
if sys.platform == 'darwin':
    return True, 'MACOS_READER_ONLY'
```
`_probe_card()` now returns the sentinel string `'MACOS_READER_ONLY'` instead
of an ATR hex string on macOS. Downstream code in `card_watcher._check_once()`
uses this return value. While the darwin branch does not fire on Ubuntu,
introducing a sentinel string that masquerades as an ATR value creates a
semantic hole: any code that treats the probe result as "ATR hex" will silently
receive `'MACOS_READER_ONLY'` on macOS instead of failing loudly.

**2. `_CardWatcherBridge` introduced in `main.py`.**
`_wire_card_watcher()` was rewritten to use a new `_CardWatcherBridge` QObject
with Qt signals, replacing the direct callback assignments. This is an
architecturally sound change (thread-safe signal delivery) but it is a
complete rewrite of the wiring layer and introduces new QObject lifetime
management requirements (`self._card_bridge = bridge` to prevent GC).

---

### v0.5.55 — 17b4f18 — pySim-read partial-read detection

**Files changed:** `managers/card_manager.py`

Changed `detect_card()` fallback logic for non-zero exit codes:
```python
# Before: only ICCID was checked
if self.card_info.get('ICCID'):
    self._original_card_data = dict(self.card_info)
    return True, "Card detected via pySim"

# After: ICCID or IMSI triggers success
iccid = self.card_info.get('ICCID')
imsi = self.card_info.get('IMSI')
if iccid or imsi:
    self._original_card_data = dict(self.card_info)
    return True, "Card detected via pySim (partial read)"
```

**Risk:** Logic change to detection flow. Legitimate fix for macOS UnicodeDecodeError
partial reads, but changes the state machine entry condition. A card with IMSI
but no ICCID would now be considered successfully detected; previously it would
have fallen through to the error path. On gialersim blank cards, this could
silently change which branch is taken.

---

### v0.5.56 — e0a50d3 — Signal propagation fix

**Files changed:** `main.py`, `qt_main.py`, `widgets/program_sim_panel.py`

Complete rewrite of `_wire_card_watcher()`. Direct callback lambdas replaced
with `@pyqtSlot` methods. One violation introduced:

**Cross-component coupling in `_on_bridge_unknown`:**
```python
@pyqtSlot(str)
def _on_bridge_unknown(self, iccid):
    cm_info = self._card_manager.card_info or {}  # ← direct manager access
    self.state_manager.update_card_info(
        imsi=cm_info.get("IMSI", ""), ...)
```
This slot reads `self._card_manager.card_info` directly, bypassing the
StateManager signal bus. CLAUDE.md Rule: "Managers are framework-free — managers
have zero Qt imports. StateManager bridges them to the UI via signals. Widgets
never import each other — they subscribe to StateManager signals."

This wiring change also modifies how `_on_bridge_unknown` populates card info
for the "not in index" case: it now exposes all pySim-read fields (IMSI, ACC,
SPN, FPLMN) even when the card is not found in the ICCID index. Previously
these fields were only populated in the `on_detected` path.

---

### v0.5.57 — 0129e8f — macOS PCSC contention via no-ATR probe

**Files changed:** `managers/card_watcher.py`, `managers/card_manager.py`

Added `_macos_check_with_pysim()` — a parallel card detection method (~100
lines) exclusive to macOS. This is the most structurally dangerous change.

**Structure of the parallel path:**
- 5 new macOS-specific instance variables in `CardWatcher.__init__`:
  `_macos_pcsc_settle_s`, `_macos_last_read_s`, `_macos_read_cooldown_s`,
  `_macos_read_fail_streak`, `_macos_removal_threshold`
- These are initialised unconditionally in `__init__` (on Ubuntu too)
- New `MACOS_READER_ONLY` branch in `_check_once()` dispatches to
  `_macos_check_with_pysim()` instead of the standard ATR-driven path
- `_macos_check_with_pysim()` implements its own cooldown, removal-threshold,
  and fail-streak logic — entirely separate state machine from the standard
  two-probe debounce

**Why this is dangerous:** The standard state machine is documented in
`docs/reference/state-machine.md`. The macOS path is a shadow implementation
that does not reference that document. Any future refactoring of the standard
path would need to maintain parity with the macOS shadow path or risk
divergence. The two-probe debounce is a deliberate safety mechanism for blank
card removal detection — the macOS removal threshold algorithm replaces it with
a configurable counter that is not equivalent.

---

### v0.5.58 — 075183b — Fix state-machine violations

**Files changed:** `main.py`, `managers/card_watcher.py`, plus new tests

**The commit message itself is the most important finding:** "fix two
state-machine violations in macOS no-ATR path." This confirms that the previous
commit (v0.5.57) introduced state machine violations and that v0.5.58 is a
partial fix. The rollback to v0.5.50 occurred because the violations were not
fully resolved before the taint propagated to Ubuntu.

---

## Files changed summary

| File | Status | Risk |
|---|---|---|
| `platform_runtime.py` | NEW (not in v0.5.50) | CRITICAL — mandatory new import |
| `managers/card_manager.py` | Modified | HIGH — new platform import, new branch in _probe_card(), partial-read logic |
| `managers/card_watcher.py` | Modified | CRITICAL — parallel macOS detection path, state machine violations |
| `managers/network_storage_manager.py` | Modified | MEDIUM — mount path and credentials dir now platform-dependent |
| `managers/settings_manager.py` | Modified | MEDIUM — platform-specific settings path |
| `managers/state_manager.py` | **Unchanged** | Clean — signal bus was not the source of regressions |
| `main.py` | Modified | HIGH — startup mode change, signal bridge rewrite, cross-component coupling |
| `qt_main.py` | Modified | Quarantined — not analysed further |

---

## Dangerous change categories

### Category A — New mandatory module with Ubuntu-impacting platform logic

`platform_runtime.py` is a new module imported at the top level of
`card_manager.py` and `network_storage_manager.py`. Any future implementation
must ensure:
- `platform_runtime.py` returns correct Linux values on Ubuntu (not macOS paths)
- The module is present before any test or application import runs
- Ubuntu mount base `/tmp/simgui-mounts` and credentials dir `~/.config/simgui`
  are the correct values returned by the Linux path in `platform_runtime`
- No macOS-conditional imports or initialisation side effects run on Linux

### Category B — Platform branches inside non-adapter modules

`card_manager._probe_card()` received `if sys.platform == 'darwin'`.
`card_watcher._check_once()` received `MACOS_READER_ONLY` dispatch.

Per the agreed ground rules (CLAUDE.md Rule 5a), the only permitted
platform-specific code in `card_manager.py` is `_find_cli_tool()`.
`_probe_card()` is SIM detection logic — it must remain platform-free.
The macOS PCSC-contention problem must be solved without a `sys.platform`
branch in `_probe_card()`.

### Category C — Parallel state machine implementation

`_macos_check_with_pysim()` is a shadow of the standard card-detection state
machine. Two detection algorithms with different removal semantics cannot
coexist without tight coupling between them. The correct approach is to make
the standard algorithm handle the macOS probe constraints (e.g. by accepting
an ATR-less "reader present" probe result and driving the existing state
machine from there).

### Category D — Cross-component coupling in UI wiring

`_on_bridge_unknown` reads `self._card_manager.card_info` directly inside a
signal slot. This bypasses the StateManager signal bus and violates the
architecture principle that the UI layer never calls managers directly.
CardManager must push its data to StateManager; the signal handler must read
from StateManager only.

### Category E — State machine violations acknowledged before rollback

The commit history shows that v0.5.57 introduced state machine violations and
v0.5.58 attempted partial fixes, with rollback before they were resolved. Any
future implementation of the macOS no-ATR path must be validated against the
full Ubuntu test suite (2051 passed, 0 failed) before merging.

---

## "Do not repeat" list

The following patterns from the tainted history must not be used in future
macOS refactoring:

1. **Do not add `sys.platform == 'darwin'` or `if _MACOS` branches inside
   `card_manager.py` except in `_find_cli_tool()`.**
   All other card_manager code is SIM logic and must remain platform-free.

2. **Do not add `sys.platform` branches inside `card_watcher.py`.**
   CardWatcher implements the state machine. Platform differences must be
   expressed as constructor parameters or injected dependencies, not inline
   branches.

3. **Do not write a parallel detection algorithm for macOS.**
   There must be one detection algorithm. macOS-specific constraints (e.g.
   PCSC contention, no-ATR probe) must be expressed as configuration or
   narrowly-scoped adapter calls, not a shadow `_macos_check_with_pysim()`
   method.

4. **Do not change `MOUNT_BASE` from a literal to a platform call without
   verifying that the Linux return value is identical to the original literal.**
   The mount base is used in stored paths. Changing it silently migrates all
   existing mounts to a new location.

5. **Do not read `self._card_manager.card_info` from a signal slot.**
   All card data flows through StateManager signals. If a slot needs data
   that is not in StateManager, the fix is to put it in StateManager — not
   to reach into CardManager.

6. **Do not introduce a new mandatory module-level import in any manager
   without verifying Ubuntu test suite passes.**
   A new import that fails on Ubuntu kills every test that touches the
   importing module — a catastrophic regression that is easy to miss if only
   macOS is tested.

7. **Do not commit macOS-specific code without a passing Ubuntu test run.**
   The Ubuntu baseline (2051 passed, 0 failed) is the gate. The tainted
   branch advanced through 8 commits without a confirmed Ubuntu run.

---

## Conclusion

The Ubuntu regression was caused primarily by introducing `platform_runtime.py`
as a mandatory import (Category A), adding a parallel detection algorithm in
`card_watcher.py` (Category C), and allowing state machine violations to
accumulate across multiple commits without Ubuntu validation (Category E).
The state bus (`state_manager.py`) was not modified and was not the source of
any regression.

The ground rules added to CLAUDE.md (Rules 1–10 and 5a) directly address every
category identified here. No new implementation should begin until a developer
has read both this report and the state-machine document
(`docs/reference/state-machine.md`).
