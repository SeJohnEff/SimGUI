# Platform Boundary Design

**Status:** Design-only proposal — no implementation yet  
**Prerequisite:** Ubuntu v0.5.50 baseline must remain clean (2067 passed, 321 skipped)  
**Authority:** This document is subordinate to `state-machine.md`. Any conflict with
`state-machine.md` must be resolved in `state-machine.md`'s favour.

---

## Purpose

This document defines the boundaries between platform-specific and shared code for any
future macOS support work. It is a design specification, not an implementation record.
Its goal is to prevent a repetition of the Phase 4 failure pattern, in which macOS
additions broke Ubuntu application logic and required a full rollback.

Read this document in full before writing any platform-related code.

---

## 1. Failure Pattern to Avoid

The tainted history (v0.5.51–v0.5.58, documented in
`docs/reference/post-v0.5.50-forensic-report.md`) broke Ubuntu in three distinct ways:

| Failure category | Mechanism | Impact |
|---|---|---|
| Mandatory top-level runtime import | `from platform_runtime import …` at module scope in `card_manager.py` | `ModuleNotFoundError` kills all 2051+ Ubuntu tests at collection time |
| Mount path made platform-dependent | `base_mount_dir` set from `platform_runtime` instead of hardcoded `/tmp/simgui-mounts` | Ubuntu path changed silently; mounts broke |
| Shadow state machine | `_macos_check_with_pysim()` alongside `CardWatcher`; duplicate removal semantics | Two independent card-detection algorithms with divergent state transitions |

These three patterns are unconditionally prohibited. They are restated as concrete rules
in Section 5.

---

## 2. Permitted Platform Boundaries (Already Exist)

The following seams already exist in v0.5.50 and are the only permitted locations for
platform-specific code.

### 2.1 `card_manager._find_cli_tool()`

**What it does:** Searches a prioritised list of directories for `pySim-shell.py`,
`pySim-prog.py`, and `pySim-read.py`.

**Why it is a legitimate platform seam:** The search path differs by platform:
- Ubuntu: `/opt/pysim`, system PATH
- macOS: `~/pysim`, `PYSIM_PATH` env var, Homebrew-style directories

**How to extend it:** Append macOS search directories to the existing list when
`sys.platform == "darwin"`. The logic that validates the found path and returns it
is shared and must not be duplicated.

**What must not happen:** Do not replace or bypass `_find_cli_tool()` with a new
function. Do not add a macOS-only call site that invokes pySim differently.

### 2.2 `network_storage_manager` mount command handling

**What it does:** Constructs and runs OS-level mount commands for NFS and SMB/CIFS shares.

**Why it is a legitimate platform seam:** The mount binary, flags, and path conventions
differ by OS:
- Ubuntu: `/sbin/mount.nfs`, `mount.cifs`, target at `/tmp/simgui-mounts/<name>`
- macOS: `mount_nfs`, `mount_smbfs`, target at `/tmp/simgui-mounts/<name>` (same)

**How to extend it:** The mount command builder is the only thing that may vary. The
base mount directory (`/tmp/simgui-mounts`) must remain identical on both platforms —
this is a deliberate cross-platform choice that avoids the path-divergence failure seen
in v0.5.52. The share discovery, path validation, status signals, and CSV-loading logic
that follows a successful mount are shared and must not be duplicated.

**What must not happen:** Do not change the base mount path on either platform. Do not
add a platform branch anywhere other than the mount command builder.

### 2.3 Packaging and distribution scripts

**What it does:** `debian/` packaging, `scripts/install.sh`, future `.pkg` or
`.app` bundle scripts.

**Why it is a legitimate platform seam:** Packaging formats are OS-specific by
definition. There is no Ubuntu/macOS conflict risk here as long as the scripts do not
alter application logic.

**Constraint:** Packaging scripts may not patch `card_manager.py`,
`card_watcher.py`, `state_manager.py`, or any shared manager module. If installation
requires a behaviour difference, that difference must be expressed as a configuration
value or environment variable read by shared code — not as a code patch.

### 2.4 Environment and path discovery

**What it does:** Locating pySim, resolving config directories, finding the user's home
directory.

**Why it is a legitimate platform seam:** XDG paths (Linux) vs. `~/Library/Application
Support` (macOS), default pySim install locations, and virtual-environment activation
differ by OS.

**How to express it:** A future `platform_runtime.py` (see Section 4) may return
platform-appropriate values for these lookups. All call sites in shared modules must
treat the adapter as optional (see Section 5, Rule 1).

---

## 3. What Must Remain Common (Non-Negotiable)

The following must never be split by platform, duplicated, or shadowed.

### 3.1 SIM programming logic

`managers/card_manager.py`: `_program_via_pysim_prog()`, `_run_pysim_prog()`,
delta-write vs full-write selection, field encoding, ICCID exclusion for non-empty cards.

All SIM cards behave the same way regardless of which OS the host computer runs.
The platform does not change what commands pySim needs or how card fields are written.

### 3.2 Authentication logic

`managers/card_manager.py`: `authenticate()`, `check_adm1_retry_counter()`, ADM1
format detection (length 16 = hex, ≤ 8 = ASCII), CHV selection per card type.

A wrong ADM1 attempt bricks a card. This logic must be identical on all platforms.
There is no macOS-specific authentication path.

### 3.3 Card detection semantics

`managers/card_manager.py`: `detect_card()`, `probe_card_presence()`,
`_parse_pysim_output()`, `_original_card_data` sentinel semantics (`None` vs `{}`).

pySim-read output format is the same on all platforms. The sentinel contract
(`None` = no card detected, `{}` = blank card detected) is a correctness invariant,
not a platform choice.

### 3.4 `card_watcher.py` state transitions

Every state, every transition, every polling interval, and every invariant defined in
`docs/reference/state-machine.md` applies on all platforms without exception. There is
exactly one card-detection algorithm. macOS-specific PCSC constraints (contention,
no-ATR probe behaviour, settle delays) must be expressed as constructor parameters or
narrowly-scoped adapter calls that feed the existing state machine — not as a second
algorithm.

No `sys.platform` branches, no `if _MACOS` guards, no platform-specific instance
variables may be added to `card_watcher.py`.

### 3.5 `state_manager.py` signal bus

The signal definitions and their semantics are the application contract. No platform
may emit additional signals, suppress existing signals, or change signal payload types.

### 3.6 CSV logic

`managers/csv_manager.py`: parsing, validation, field normalisation, format detection.
SIM CSV files are platform-independent data. There is no macOS-specific CSV path.

### 3.7 Batch logic

`managers/batch_manager.py`: orchestration, progress tracking, error accumulation.
The batch programming workflow is driven by CSV data and card behaviour, not by the OS.

### 3.8 Artifact and backup logic

`managers/auto_artifact_manager.py`, `managers/backup_manager.py`.

These are file I/O operations. The target directory may legitimately differ by platform
(see Section 2.4), but the logic that decides what to write and when to write it is
shared. Do not split these managers unless a genuine OS behavioural difference is
identified and documented.

---

## 4. Future Optional macOS Runtime Adapter

A `platform_runtime.py` module may be introduced in a future phase. The following
rules are unconditional.

### 4.1 It must be optional on all platforms

Ubuntu must start, pass all tests, and run normally whether or not
`platform_runtime.py` is present. The module must never be imported at the top level
of any shared manager. Every import must use one of these two patterns:

```python
# Pattern A — local import inside the one function that needs it
def _find_cli_tool(self):
    try:
        from platform_runtime import pysim_search_dirs
        extra_dirs = pysim_search_dirs()
    except ImportError:
        extra_dirs = []
    # ... rest of function uses shared logic

# Pattern B — conditional import with explicit fallback
try:
    from platform_runtime import sysmo_search_dirs as _sysmo_dirs
except ImportError:
    _sysmo_dirs = lambda: []
```

Pattern A is preferred because the import scope is narrower.

### 4.2 It must return correct Ubuntu values on Ubuntu

Every function in `platform_runtime.py` must return the same value on Ubuntu as
the hardcoded constant it replaces — verified by the Ubuntu test suite. This is not
optional. If a function cannot return the correct Ubuntu value, the function must not
replace the hardcoded constant; the constant must remain.

### 4.3 It must be thin

An adapter function wraps one call, translates one path, or handles one import
difference. It must not contain SIM card logic, state machine logic, ADM1 handling,
card type detection, or any business rule. Maximum acceptable size: a few lines per
function, no more than ~100 lines total for the initial adapter. If it grows beyond
this, the abstraction is leaking and must be redesigned.

### 4.4 Permitted adapter surface

| Function | Returns | Ubuntu value |
|---|---|---|
| `pysim_search_dirs() -> list[str]` | Platform-appropriate pySim search paths | `["/opt/pysim"]` |
| `sysmo_search_dirs() -> list[str]` | Platform-appropriate sysmocom tool search paths | `["/opt/pysim"]` |
| `config_dir() -> str` | User config directory | `~/.config/simgui` |
| `mount_cmd_nfs(src, dst) -> list[str]` | NFS mount command tokens | `["mount", "-t", "nfs", src, dst]` |
| `mount_cmd_smb(src, dst, opts) -> list[str]` | SMB mount command tokens | `["mount", "-t", "cifs", src, dst, *opts]` |

This table is illustrative. The actual surface must be no larger than what is
demonstrably needed for a concrete failing test case.

### 4.5 Prohibited adapter surface

The adapter must not contain, return, or influence:

- Card detection logic or card presence semantics
- ADM1 key format conversion
- Card type selection (`-t gialersim` vs `-t sysmoISIM-SJA5`)
- pySim command construction (beyond search path resolution)
- State machine transitions or `CardState` values
- Signal emissions
- Any logic that currently lives in `card_watcher.py`, `card_manager.py`'s core
  programming/auth methods, `csv_manager.py`, or `batch_manager.py`

---

## 5. Concrete Prohibitions (Forensic Guardrails Restated)

These rules are derived from the Phase 4 forensic report. They are listed here in
condensed form for quick reference during code review.

**Rule F1 — No mandatory top-level runtime imports in shared modules.**  
`from platform_runtime import …` at module scope in any file under `managers/` is
unconditionally prohibited.

**Rule F2 — No shadow state machines.**  
There is exactly one card-detection algorithm. Any new detection helper must feed the
existing `CardWatcher` state machine, not run alongside it.

**Rule F3 — No card detection outside `CardWatcher` / `detect_card()`.**  
Detection loops, cooldown counters, and fail-streak trackers outside these two locations
are prohibited.

**Rule F4 — No bypass of `state-machine.md`.**  
If a proposed change contradicts any invariant in `state-machine.md`, stop and report
the conflict. Do not code around it.

**Rule F5 — No platform branches inside `card_watcher.py`.**  
`sys.platform`, `_MACOS`, `darwin`, and equivalent guards are prohibited in this file.

**Rule F6 — Do not partially fix known state-machine violations.**  
A commit that introduces a violation must not be pushed. A discovered violation in a
pushed commit requires stopping all work on that branch and reporting the exact
file/line/invariant conflict.

**Rule F7 — Any macOS runtime abstraction must be optional, thin, and Ubuntu-safe.**  
Verified by the Ubuntu test suite before any macOS-facing work is considered complete.

---

## 6. Staged Future Implementation Plan

The plan below is a proposal only. Each stage requires an explicit decision before work
begins. No stage may be started until the previous stage's tests pass on Ubuntu.

### Stage 0 — Prerequisites (already done)

- Ubuntu v0.5.50 baseline established: 2067 passed, 321 skipped.
- Forensic guardrails documented in `CLAUDE.md`.
- State machine documented in `state-machine.md`.
- This design document written and committed.

### Stage 1 — macOS development environment baseline

**Goal:** Run the test suite on macOS and document which tests fail and why, without
making any application code changes.

**Output:** `docs/reference/test-baseline-macos-stage1.md` listing all failures with
root cause per failure (missing pySim, PCSC framework difference, path assumption, etc.).

**Constraint:** No application code changes in this stage.

### Stage 2 — Optional adapter introduction

**Goal:** Introduce `platform_runtime.py` as an optional module. Add local imports in
`_find_cli_tool()` and `network_storage_manager` mount command builder only.

**Constraint:** Every existing Ubuntu test must still pass unchanged after this stage.
The adapter must not change any Ubuntu behaviour. New tests must assert Ubuntu return
values from every adapter function.

**Required tests (Ubuntu):**
- `test_platform_runtime_ubuntu_pysim_dirs` — asserts `pysim_search_dirs()` returns
  `["/opt/pysim"]` on Linux.
- `test_platform_runtime_ubuntu_config_dir` — asserts `config_dir()` returns
  `~/.config/simgui` on Linux.
- `test_platform_runtime_ubuntu_mount_nfs` — asserts `mount_cmd_nfs()` returns the
  same tokens as the pre-adapter hardcoded command.
- `test_platform_runtime_ubuntu_mount_smb` — same for SMB.
- `test_card_manager_import_without_platform_runtime` — confirms
  `import managers.card_manager` succeeds on a Python path where
  `platform_runtime.py` does not exist.
- `test_network_storage_manager_import_without_platform_runtime` — same for
  `network_storage_manager`.

**Required tests (macOS-only, skipped on Ubuntu):**
- `test_platform_runtime_macos_pysim_dirs` — asserts macOS paths are returned.
- `test_platform_runtime_macos_mount_nfs` — asserts `mount_nfs` command tokens.
- `test_platform_runtime_macos_mount_smb` — asserts `mount_smbfs` command tokens.

### Stage 3 — macOS PCSC integration

**Goal:** Resolve PCSC.framework differences so that card detection works on macOS
without modifying `card_watcher.py` or `card_manager.py`.

**Approach:** `_find_cli_tool()` and pySim invocation may need to handle the absence
of `pcscd` (macOS uses the built-in PCSC framework). This is expressed as a search-path
or invocation-flag difference, not a new detection algorithm.

**Constraint:** `card_watcher.py` must not change. Any macOS PCSC accommodation must
be a parameter passed to the existing polling logic, not a new polling loop.

**Required tests:** Hardware-gated (`SIMGUI_HW_TEST=1`) tests that exercise the full
detect → authenticate → program flow on macOS hardware. These are additive to, not
replacements for, the Ubuntu hardware tests.

### Stage 4 — Distribution

**Goal:** `.app` bundle or `.pkg` installer for macOS.

**Constraint:** Packaging scripts must not patch shared manager modules. Any runtime
configuration needed by the macOS package must be expressed as an environment variable
or config file read by shared code.

---

## 7. Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-21 | Base mount directory `/tmp/simgui-mounts` kept identical on both platforms | Eliminates the path-divergence failure class seen in v0.5.52; `/tmp` exists on both Linux and macOS |
| 2026-05-21 | `platform_runtime.py` must be optional, not mandatory | Prevents the `ModuleNotFoundError` failure class seen in v0.5.52 |
| 2026-05-21 | No platform branches in `card_watcher.py` | File is the state machine implementation; platform branches introduce divergent detection semantics |
| 2026-05-21 | macOS baseline established separately from Ubuntu baseline | A test run on macOS is macOS evidence only; Ubuntu baseline is authoritative for production correctness |
