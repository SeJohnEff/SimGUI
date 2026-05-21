# Platform Refactor Implementation Checklist

**Derived from:** `docs/reference/platform-boundary-design.md`  
**Authoritative constraint:** `docs/reference/state-machine.md`  
**Ubuntu baseline:** 2067 passed, 321 skipped (recorded in `test-baseline-ubuntu-v0.5.50.md`)  
**Status:** Not started

---

## How to use this checklist

Work through commits in order. Do not start a commit until the previous one is ticked
off. Each commit must:

1. Touch only the files listed under **Allowed files**.
2. Leave every file listed under **Prohibited files** untouched.
3. Pass the **After tests** check on Ubuntu before being pushed.
4. Be reverted immediately if the **Rollback condition** is met.

Items marked **[HUMAN APPROVAL REQUIRED]** must receive explicit written sign-off in
this document (or a linked comment) before work begins. Do not interpret silence as
approval.

Checkbox legend:
- `[ ]` not started
- `[>]` in progress
- `[x]` complete — tests passed, pushed

---

## Stage 0 — Prerequisites

> All items in this stage are already complete. They are listed for traceability only.

- [x] **S0-1** Ubuntu v0.5.50 baseline recorded  
  File: `docs/reference/test-baseline-ubuntu-v0.5.50.md`

- [x] **S0-2** Forensic guardrails written into `CLAUDE.md`  
  Commit: `b0624c6`

- [x] **S0-3** State machine documented in `state-machine.md`  
  File: `docs/reference/state-machine.md`

- [x] **S0-4** Platform boundary design written  
  File: `docs/reference/platform-boundary-design.md`  
  Commit: `f31eecb`

- [x] **S0-5** This checklist written  
  File: `docs/reference/platform-refactor-implementation-checklist.md`

---

## Stage 1 — macOS Development Environment Baseline

**Goal:** Run the existing test suite on macOS unmodified. Record every failure and its
root cause. No application code changes in this stage.

**Entry condition:** Ubuntu baseline is clean (S0-1 complete).  
**Exit condition:** `docs/reference/test-baseline-macos-stage1.md` committed.

---

### Commit S1-A — Run test suite on macOS; record baseline

**Purpose:** Establish which tests fail on macOS before any code change, and why.
Every failure must be categorised by root cause.

**Allowed files:**
- `docs/reference/test-baseline-macos-stage1.md` (new file, docs only)

**Prohibited files (must not be touched):**
- All files under `managers/`
- `card_watcher.py`
- `state_manager.py`
- All files under `tests/`
- All files under `ui/`
- `main.py`, `version.py`
- `docs/reference/state-machine.md`

**Before tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: 2067 passed, 321 skipped — identical to baseline. Any deviation is a
blocker; do not proceed.

**After tests (macOS):**
Run `python3 -m pytest tests/ -q --tb=no` on macOS. Record the count of passed,
failed, skipped in `test-baseline-macos-stage1.md`. Include one-line root-cause
annotation per failing test (e.g. `missing pySim`, `PCSC path assumption`,
`XDG config path`, `Linux-only import`).

**Rollback condition:** If Ubuntu test count changes from 2067/321 after adding the
docs file, the git history has a problem — investigate before proceeding.

**[HUMAN APPROVAL REQUIRED]** Review `test-baseline-macos-stage1.md` and confirm the
root-cause analysis is complete before starting Stage 2. The failure list in that
document defines the scope of all subsequent work.

---

## Stage 2 — Optional Adapter Introduction

**Goal:** Introduce `platform_runtime.py` as an optional module. Wire it into exactly
two call sites: `card_manager._find_cli_tool()` and `network_storage_manager`
`_build_mount_cmd()`. No other call sites. No Ubuntu behaviour change.

**Entry condition:** S1-A complete; `test-baseline-macos-stage1.md` approved.  
**Exit condition:** All commits S2-A through S2-D complete; Ubuntu baseline unchanged.

---

### Commit S2-A — Write `platform_runtime.py` (stub, Linux values only)

**Purpose:** Create the adapter module with all permitted functions returning their
correct Linux/Ubuntu values. No macOS-specific code yet. Establishes that the module
is safe to import on Ubuntu and returns correct values.

**Allowed files:**
- `platform_runtime.py` (new file, root of repo)

**Prohibited files:**
- All files under `managers/` (no call sites yet)
- `card_watcher.py`
- `state_manager.py`
- All files under `tests/` (tests come in S2-B)
- `docs/reference/state-machine.md`

**Required content contract (must be met before S2-B tests are written):**

| Function | Linux return value |
|---|---|
| `pysim_search_dirs() -> list[str]` | `["/opt/pysim"]` |
| `sysmo_search_dirs() -> list[str]` | `["/opt/pysim"]` |
| `config_dir() -> str` | `os.path.expanduser("~/.config/simgui")` |
| `mount_cmd_nfs(src, dst) -> list[str]` | `["mount", "-t", "nfs", src, dst]` |
| `mount_cmd_smb(src, dst, opts) -> list[str]` | `["mount", "-t", "cifs", src, dst, *opts]` |

**Prohibited content:** No card detection logic. No ADM1 logic. No `CardState`
references. No signal emissions. No SIM programming logic. Total file size must be
≤ 100 lines.

**Before tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: 2067 passed, 321 skipped.

**After tests (Ubuntu):**
Same command — must still be 2067/321. The new file is not yet imported by anything,
so no change is expected. Confirm with `python3 -c "import platform_runtime; print('ok')"`.

**Rollback condition:** Any Ubuntu test count change; any import error on Ubuntu.

---

### Commit S2-B — Write Ubuntu-correctness tests for `platform_runtime`

**Purpose:** Lock in the contract that `platform_runtime` returns correct Linux values
on Linux. These tests must pass on Ubuntu before the adapter is wired into any manager.

**Allowed files:**
- `tests/test_platform_runtime.py` (new file)

**Prohibited files:**
- `platform_runtime.py` (already written; do not modify in this commit)
- All files under `managers/`
- `card_watcher.py`
- `state_manager.py`
- `docs/reference/state-machine.md`

**Required test cases (all must pass on Ubuntu):**

| Test name | Assertion |
|---|---|
| `test_ubuntu_pysim_dirs` | `pysim_search_dirs()` returns a list containing `"/opt/pysim"` on Linux |
| `test_ubuntu_sysmo_dirs` | `sysmo_search_dirs()` returns a list containing `"/opt/pysim"` on Linux |
| `test_ubuntu_config_dir` | `config_dir()` returns `~/.config/simgui` (expanded) on Linux |
| `test_ubuntu_mount_nfs_tokens` | `mount_cmd_nfs("server:/share", "/mnt")` returns `["mount", "-t", "nfs", "server:/share", "/mnt"]` on Linux |
| `test_ubuntu_mount_smb_tokens` | `mount_cmd_smb("//s/share", "/mnt", ["-o", "ro"])` returns `["mount", "-t", "cifs", "//s/share", "/mnt", "-o", "ro"]` on Linux |
| `test_import_without_platform_runtime_card_manager` | Delete `platform_runtime.py` from `sys.modules`, verify `import managers.card_manager` succeeds |
| `test_import_without_platform_runtime_network_storage` | Same for `managers.network_storage_manager` |

Note: `test_import_without_platform_runtime_*` tests must pass even before S2-C wires
the local imports, because the managers must already be importable without the adapter.

**Before tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: 2067 passed, 321 skipped.

**After tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: 2067 + (number of new tests) passed, 321 skipped. Every new test must pass.

**Rollback condition:** Any pre-existing test that now fails; any new test that cannot
be made to pass without modifying application code.

---

### Commit S2-C — Wire local import into `card_manager._find_cli_tool()`

**Purpose:** Add the optional local `try/except ImportError` import of
`pysim_search_dirs` inside `_find_cli_tool()` only. No other changes to
`card_manager.py`. Ubuntu behaviour must be identical to before this commit.

**Allowed files:**
- `managers/card_manager.py` (one function only: `_find_cli_tool`)

**Prohibited files:**
- `card_watcher.py`
- `state_manager.py`
- `managers/network_storage_manager.py` (wired separately in S2-D)
- `managers/csv_manager.py`
- `managers/batch_manager.py`
- `managers/auto_artifact_manager.py`
- `managers/backup_manager.py`
- `tests/` (no test changes in this commit)
- `docs/reference/state-machine.md`

**Required change pattern (no other pattern is permitted):**

```python
def _find_cli_tool() -> ...:
    try:
        from platform_runtime import pysim_search_dirs
        extra_dirs = pysim_search_dirs()
    except ImportError:
        extra_dirs = []
    # existing search logic appends extra_dirs to the base list
```

The base list (`/opt/pysim`, system PATH) must remain unchanged on Linux.
`extra_dirs` is appended after the base list — it does not replace it.

**Before tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: current count (post S2-B).

**After tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: identical count. No test may change from pass to fail or fail to pass.
Additionally run:
```
python3 -c "import sys; sys.modules.pop('platform_runtime', None); \
  import managers.card_manager; print('import ok')"
```
Must print `import ok`.

**Rollback condition:** Any test that changes status; import failure when
`platform_runtime.py` is absent from `sys.modules`.

---

### Commit S2-D — Wire local import into `network_storage_manager._build_mount_cmd()`

**Purpose:** Add the optional local import of `mount_cmd_nfs` / `mount_cmd_smb` inside
`_build_mount_cmd()` only. No other changes to `network_storage_manager.py`. Ubuntu
behaviour must be identical to before this commit.

> Note: `network_storage_manager.py` already contains a module-level `_MACOS` flag
> and a `sys.platform` branch that pre-dates the platform refactor work and is
> considered the existing permitted seam (Section 2.2 of the design). This commit
> must not remove or widen that existing branch — it must only add the local
> `platform_runtime` import as an alternative path inside `_build_mount_cmd()`.

**Allowed files:**
- `managers/network_storage_manager.py` (one method only: `_build_mount_cmd`)

**Prohibited files:**
- `card_watcher.py`
- `state_manager.py`
- `managers/card_manager.py`
- `managers/csv_manager.py`
- `managers/batch_manager.py`
- `managers/auto_artifact_manager.py`
- `managers/backup_manager.py`
- `tests/` (no test changes in this commit)
- `docs/reference/state-machine.md`

**Required change pattern:**

```python
def _build_mount_cmd(self, profile):
    try:
        from platform_runtime import mount_cmd_nfs, mount_cmd_smb
        _have_adapter = True
    except ImportError:
        _have_adapter = False
    # existing _MACOS branch remains; adapter is used only when present
```

The existing `_MACOS` branch must still execute correctly when `platform_runtime` is
absent. The adapter path and the existing path must produce identical results on Linux.

**Before tests (Ubuntu):**
```
python3 -m pytest tests/test_network_storage_manager.py \
  tests/test_network_storage_manager_full.py \
  tests/test_platform_runtime.py -x -q
```
Expected: all pass.

**After tests (Ubuntu):**
Same command — must still all pass. Additionally:
```
python3 -c "import sys; sys.modules.pop('platform_runtime', None); \
  import managers.network_storage_manager; print('import ok')"
```
Must print `import ok`.

**Rollback condition:** Any test status change; any difference in mount command tokens
produced on Linux before vs. after this commit (verify with `test_ubuntu_mount_*`
tests from S2-B).

---

### Commit S2-E — Add macOS-specific values to `platform_runtime.py`

**Purpose:** Now that the Linux contract is locked and wired, extend
`platform_runtime.py` with the macOS-specific return values. This is the first commit
that contains macOS-only logic.

**[HUMAN APPROVAL REQUIRED]** The macOS search paths and mount commands to use must be
confirmed before this commit. Specifically: the pySim search path list for macOS, and
whether `mount_smbfs` is used directly or via `sudo`. Record the decision in Section 7
of `platform-boundary-design.md`.

**Allowed files:**
- `platform_runtime.py`
- `tests/test_platform_runtime.py` (add macOS-only tests, skipped on Linux)

**Prohibited files:**
- All files under `managers/`
- `card_watcher.py`
- `state_manager.py`
- `docs/reference/state-machine.md`

**Required new test cases (skipped on Linux via `pytest.mark.skipif`):**

| Test name | Assertion |
|---|---|
| `test_macos_pysim_dirs` | `pysim_search_dirs()` returns list containing `~/pysim` (expanded) on macOS |
| `test_macos_mount_nfs_tokens` | `mount_cmd_nfs()` returns macOS-appropriate tokens on macOS |
| `test_macos_mount_smb_tokens` | `mount_cmd_smb()` returns `mount_smbfs`-based tokens on macOS |

**Ubuntu correctness check:** All `test_ubuntu_*` tests from S2-B must still pass
unchanged. The macOS-only tests must be skipped (not failed) on Ubuntu.

**Before tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: identical to post-S2-D count.

**After tests (Ubuntu):**
Same command — count must not change (macOS tests are skipped, not added to pass count
without the marker).

**Rollback condition:** Any `test_ubuntu_*` test that changes status; any macOS test
that does not have a proper `skipif(sys.platform != "darwin")` guard.

---

## Stage 3 — macOS PCSC Integration

**Goal:** Make card detection work on macOS by resolving PCSC.framework differences.
`card_watcher.py` must not change. Any accommodation is expressed as a constructor
parameter or adapter call that feeds the existing state machine.

**Entry condition:** All Stage 2 commits complete; Ubuntu baseline unchanged.  
**Exit condition:** Hardware-gated test passes on macOS; Ubuntu baseline still unchanged.

**[HUMAN APPROVAL REQUIRED]** Before starting Stage 3, the exact PCSC difference to
accommodate must be identified from the Stage 1 failure analysis. This stage cannot be
planned in full until that analysis exists. The commit plan below is therefore
tentative and must be revised once S1-A is complete.

---

### Commit S3-A — Identify PCSC parameter seam (design only, no code)

**Purpose:** Document the specific PCSC.framework constraint identified in Stage 1 and
how it will be expressed as a constructor parameter (not a platform branch in
`card_watcher.py`). Update this checklist with the concrete S3-B commit plan.

**Allowed files:**
- `docs/reference/platform-refactor-implementation-checklist.md` (this file)
- `docs/reference/platform-boundary-design.md` (Section 7 decision log only)

**Prohibited files:**
- All application code files
- `docs/reference/state-machine.md`

**Before/after tests:** Ubuntu baseline must be unchanged. Docs-only commit.

**Rollback condition:** Not applicable (docs only).

**[HUMAN APPROVAL REQUIRED]** The updated S3-B plan in this checklist must be reviewed
and approved before S3-B work begins.

---

### Commit S3-B — (Tentative) Express PCSC constraint as constructor parameter

> This commit plan is a placeholder. Replace with the concrete plan after S3-A is
> approved.

**Tentative purpose:** Add a constructor parameter to `CardWatcher` (e.g.
`pcsc_settle_ms: int = 0`) that accommodates the macOS PCSC settle delay without
adding a platform branch inside the class. The parameter default must leave Ubuntu
behaviour unchanged.

**Tentative allowed files:**
- `managers/card_watcher.py` (constructor and one call site only)
- `main.py` (pass the parameter at construction time on macOS)
- `tests/test_card_watcher.py` (add test for new parameter default)

**Prohibited files under all circumstances:**
- `card_watcher.py` state transition logic (transitions themselves must not change)
- `state_manager.py`
- All other files under `managers/`
- `docs/reference/state-machine.md`

**Before tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: identical to post-Stage-2 count.

**After tests (Ubuntu):**
Same command — identical count. The new parameter must have a default that leaves all
existing `CardWatcher` tests passing without modification.

**Rollback condition:** Any `test_card_watcher.py` test that changes from pass to fail;
any state-machine invariant violation identified in the diff.

---

### Commit S3-C — Add hardware-gated macOS card detection test

**Purpose:** Add a test that exercises the full detect → authenticate path on real
macOS hardware. Skipped unless `SIMGUI_HW_TEST=1` and `sys.platform == "darwin"`.

**Allowed files:**
- `tests/test_e2e_contracts.py` (add one new test class `TestMacOSHardwareGated`)

**Prohibited files:**
- All files under `managers/`
- `card_watcher.py`
- `state_manager.py`
- `docs/reference/state-machine.md`

**Before tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: unchanged count (new test is skipped on Ubuntu).

**After tests (macOS hardware):**
```
SIMGUI_HW_TEST=1 python3 -m pytest \
  tests/test_e2e_contracts.py::TestMacOSHardwareGated -v
```
Must pass. Record result in `docs/reference/test-baseline-macos-stage3.md`.

**Rollback condition:** Ubuntu count changes; new test does not have both
`SIMGUI_HW_TEST` and `sys.platform == "darwin"` guards.

---

## Stage 4 — Distribution

**Goal:** `.app` bundle or `.pkg` installer for macOS. No changes to shared application
code.

**Entry condition:** Stage 3 complete; macOS hardware test passing.

**[HUMAN APPROVAL REQUIRED]** Distribution toolchain (PyInstaller, `py2app`, Xcode,
Homebrew formula) must be decided before work begins. Record the decision in
`platform-boundary-design.md` Section 7.

---

### Commit S4-A — macOS build script (docs/scripts only)

**Purpose:** Add `scripts/build-macos.sh` (or equivalent). No changes to application
code.

**Allowed files:**
- `scripts/build-macos.sh` (new file)
- `docs/how-to/install.md` (macOS section)

**Prohibited files:**
- All files under `managers/`
- `card_watcher.py`
- `state_manager.py`
- `main.py`
- `version.py`
- `docs/reference/state-machine.md`

**Before/after tests (Ubuntu):**
```
python3 -m pytest tests/ -x -q
```
Expected: unchanged count. Scripts are not imported by the test suite.

**Rollback condition:** Ubuntu test count changes.

---

### Commit S4-B — Packaging configuration for macOS bundle

**Purpose:** Add `platform_runtime.spec`, `setup-macos.cfg`, or equivalent packaging
configuration. Must not patch shared manager modules.

**Allowed files:**
- Packaging configuration files (`.spec`, `.cfg`, `Info.plist`, etc.)
- `scripts/` (macOS-specific scripts only)

**Prohibited files:**
- All files under `managers/`
- `card_watcher.py`
- `state_manager.py`
- `main.py` (unless adding a single `if getattr(sys, "frozen", False):` guard at the
  entry point — requires separate human approval)
- `docs/reference/state-machine.md`

**Before/after tests (Ubuntu):**
Unchanged count.

**Rollback condition:** Any shared manager file touched; Ubuntu count changes.

---

## Invariant Checklist (Run Before Every Commit)

Before pushing any commit in Stages 2–4, verify these invariants manually:

```
[ ] python3 -m pytest tests/ -x -q  →  2067+ passed, 321 skipped (Ubuntu)
[ ] grep -rn "from platform_runtime import" managers/  →  zero results at module scope
[ ] grep -rn "sys.platform\|_MACOS\|darwin" managers/card_watcher.py  →  zero results
[ ] grep -rn "sys.platform\|_MACOS\|darwin" managers/card_manager.py  →  zero results
    (except comments and the existing _find_cli_tool docstring)
[ ] python3 -c "import sys; [sys.modules.pop(k,None) for k in list(sys.modules) \
    if 'platform_runtime' in k]; import managers.card_manager; \
    import managers.network_storage_manager; print('ok')"  →  prints ok
[ ] Diff of card_watcher.py against v0.5.50 tag shows no logic changes
[ ] state-machine.md is unmodified (git diff HEAD -- docs/reference/state-machine.md)
```

---

## Rollback Protocol

If a rollback condition is triggered:

1. Do not push the offending commit.
2. If already pushed: `git revert <sha>` immediately — do not amend or force-push.
3. Record the failure in a new row in `platform-boundary-design.md` Section 7.
4. Stop all Stage work until the root cause is understood and a revised plan is
   approved (human approval gate).

---

## Approval Log

Record human approvals here with date and initials.

| Item | Approved by | Date | Notes |
|---|---|---|---|
| S1-A complete — baseline analysis approved | | | |
| S2-E macOS paths confirmed | | | |
| S3-A PCSC constraint plan approved | | | |
| S3-B revised plan approved | | | |
| S4 distribution toolchain decision | | | |
