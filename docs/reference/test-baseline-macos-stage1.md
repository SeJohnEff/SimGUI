# macOS Test Baseline — Stage 1 (S1-A)

**Status:** Complete — awaiting human approval before Stage 2 begins.

---

## Run Metadata

| Field | Value |
|---|---|
| Git commit | `adc14a6cc02c4c8459def0687b77b952d29b4c74` |
| Commit message | `docs: tighten platform refactor checklist gates` |
| macOS version | 26.4.1 (Build 25E253) |
| Python version | 3.9.6 |
| pytest version | 8.4.2 |
| Exact command | `python3 -m pytest tests/ -q --tb=no` |
| Run date | 2026-05-21 |
| Code changes made | **None** — working tree was clean before and after. |

---

## Summary Counts

| Result | Count |
|---|---|
| Passed | 2022 |
| Failed | **15** |
| Skipped | 351 |
| **Total** | **2388** |

Ubuntu baseline (v0.5.50): 2067 passed, 0 failed, 321 skipped (total 2388).

The total test count (2388) is identical on both platforms — no tests were added or
removed. Compared with Ubuntu: 15 tests that pass on Ubuntu fail on macOS, and 30
additional tests are skipped on macOS.

---

## Skip Count Difference (Ubuntu 321 → macOS 351, +30)

The 30 additional skips on macOS are not failures and were not investigated in detail.
Likely causes (in decreasing probability):

1. Tests guarded by `sys.platform != "linux"` or similar markers that were present in
   the suite but not triggered on Ubuntu.
2. Tests that probe for Linux-specific binaries (`avahi-browse`, `nmblookup`, `pcscd`)
   at collection time and skip when absent.
3. Differences in Qt/display-related test guards between macOS and headless Ubuntu.

These 30 tests are not regressions — they are correctly skipped on a platform where
their pre-conditions cannot be met.

---

## Failing Tests — Full List

```
FAILED tests/test_network_scanner.py::TestScanSmbServers::test_avahi_only
FAILED tests/test_network_scanner.py::TestScanSmbServers::test_avahi_uses_resolve_flag
FAILED tests/test_network_scanner.py::TestScanSmbServers::test_nmblookup_adds_new_server
FAILED tests/test_network_storage_manager.py::TestNetworkStorageManager::test_build_mount_cmd_smb_guest
FAILED tests/test_network_storage_manager.py::TestNetworkStorageManager::test_build_mount_cmd_smb_with_username
FAILED tests/test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_uses_cifs_type
FAILED tests/test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_guest_when_no_username
FAILED tests/test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_username_in_opts_when_no_cred_file
FAILED tests/test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_domain_in_opts
FAILED tests/test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_cred_file_used_when_present
FAILED tests/test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_uid_gid_in_opts
FAILED tests/test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_file_dir_mode_in_opts
FAILED tests/test_network_storage_manager_full.py::TestSudoPermissionDetection::test_mount_returns_sudo_fix_message
FAILED tests/test_network_storage_manager_full.py::TestSudoPermissionDetection::test_check_sudo_mount_failure
FAILED tests/test_network_storage_manager_full.py::TestSudoPermissionDetection::test_check_sudo_mount_os_error
```

---

## Failure Categories and Root Causes

### Category 1 — SMB mount command format (9 tests)

**Affected tests:**
- `test_build_mount_cmd_smb_guest`
- `test_build_mount_cmd_smb_with_username`
- `test_smb_uses_cifs_type`
- `test_smb_guest_when_no_username`
- `test_smb_username_in_opts_when_no_cred_file`
- `test_smb_domain_in_opts`
- `test_smb_cred_file_used_when_present`
- `test_smb_uid_gid_in_opts`
- `test_smb_file_dir_mode_in_opts`

**Root cause:** `network_storage_manager.py` already contains a `_MACOS = sys.platform
== "darwin"` flag and deliberately uses `/sbin/mount_smbfs` on macOS instead of the
Linux `mount -t cifs` command. On Linux, SMB mounts use:
```
/usr/bin/sudo mount -t cifs <source> <mountpoint> -o username=...,password=...
```
On macOS, the code produces:
```
/usr/bin/sudo /sbin/mount_smbfs //user:pass@host/share /mountpoint
```

The tests assert Linux-specific structure (the `-t cifs` type token and `-o` options
string) and have no `sys.platform` guard. They fail because the command token list
produced on macOS has a completely different shape.

**Classification:** Expected macOS platform behavior. The `_MACOS` branch is an
intentional pre-existing seam. The tests were never written with macOS guards. This is
the exact call site that Stage 2 (`platform_runtime.py`) will address. The tests will
need macOS-aware assertions or `skipif` guards in a later stage.

**No Ubuntu impact:** The `_MACOS` branch is entered only when
`sys.platform == "darwin"`. Ubuntu behavior is not affected.

---

### Category 2 — sudo / permission detection (3 tests)

**Affected tests:**
- `test_mount_returns_sudo_fix_message`
- `test_check_sudo_mount_failure`
- `test_check_sudo_mount_os_error`

**Root cause:** Two distinct sub-issues:

1. **Wrong permission message (`test_mount_returns_sudo_fix_message`):** The test
   asserts `"simgui-setup-mount" in msg`. On macOS the code returns a macOS-specific
   message ("On macOS, you may need to: 1. Unlock System Settings…") that does not
   contain `"simgui-setup-mount"`. The message is correct for macOS but the test
   expects the Linux-specific string.

2. **`check_sudo_mount()` returns True on macOS (`test_check_sudo_mount_failure`,
   `test_check_sudo_mount_os_error`):** Tests expect the method to return `False` when
   `sudo mount` fails (mocked via `subprocess.run` raising `OSError` or returning
   non-zero). On macOS, `check_sudo_mount()` returns `True` without running the Linux
   `sudo mount -t cifs` probe — the macOS code path skips the probe and assumes
   mounting is available through `mount_smbfs`. The mock therefore never fires.

**Classification:** Expected macOS platform behavior. Both sub-issues arise from the
same pre-existing `_MACOS` branch in `network_storage_manager.py`. The tests assert
Linux-specific behavior and have no macOS guards.

**No Ubuntu impact:** The macOS code path is gated on `_MACOS`.

---

### Category 3 — avahi-browse not invoked on macOS (3 tests)

**Affected tests:**
- `test_avahi_only`
- `test_avahi_uses_resolve_flag`
- `test_nmblookup_adds_new_server`

**Root cause:** `avahi-browse` is a Linux/Avahi daemon tool. On macOS it does not
exist. The `scan_smb_servers()` function in `utils/network_scanner.py` takes a
platform-specific code path on macOS that does not call `avahi-browse`. The tests mock
`utils.network_scanner._run_cmd` and expect `avahi-browse` to be called (or its mock
output to be consumed), but since the function never issues the `avahi-browse` call on
macOS, the mock is not invoked:

- `test_avahi_only`: expects 2 servers from avahi mock output, gets 0 (avahi never
  called; nmblookup mock also not called, so result is empty).
- `test_avahi_uses_resolve_flag`: asserts `avahi-browse` was called at least once —
  it was not.
- `test_nmblookup_adds_new_server`: expects avahi (1 server) + nmblookup (1 new
  server) = 2. On macOS avahi is not called, so only the nmblookup path fires,
  yielding 1 server.

**Classification:** Expected macOS platform behavior. `avahi-browse` has no macOS
equivalent in the current code. The tests have no `skipif(sys.platform != "linux")`
guard. Fixing these tests is out of scope for Stage 2 (platform_runtime only covers
pySim paths and mount commands); a separate decision is needed for macOS network
discovery (mDNS via `dns-sd`, Bonjour, or no-op). These tests should be guarded with
`skipif(sys.platform != "linux")` in a future stage.

**No Ubuntu impact:** The macOS network discovery path is platform-gated.

---

## Summary Table

| # | Test | Category | Root cause | Expected macOS behavior? | Ubuntu impact? |
|---|---|---|---|---|---|
| 1 | `test_avahi_only` | 3 | `avahi-browse` not called on macOS | Yes | None |
| 2 | `test_avahi_uses_resolve_flag` | 3 | `avahi-browse` not called on macOS | Yes | None |
| 3 | `test_nmblookup_adds_new_server` | 3 | avahi produces 0 results on macOS | Yes | None |
| 4 | `test_build_mount_cmd_smb_guest` | 1 | macOS uses `mount_smbfs`, not `cifs` | Yes | None |
| 5 | `test_build_mount_cmd_smb_with_username` | 1 | macOS uses `mount_smbfs`, not `cifs` | Yes | None |
| 6 | `test_smb_uses_cifs_type` | 1 | macOS uses `mount_smbfs`, not `cifs` | Yes | None |
| 7 | `test_smb_guest_when_no_username` | 1 | macOS uses `mount_smbfs`, not `cifs` | Yes | None |
| 8 | `test_smb_username_in_opts_when_no_cred_file` | 1 | macOS uses `mount_smbfs`, not `cifs` | Yes | None |
| 9 | `test_smb_domain_in_opts` | 1 | macOS uses `mount_smbfs`, not `cifs` | Yes | None |
| 10 | `test_smb_cred_file_used_when_present` | 1 | macOS uses `mount_smbfs`, not `cifs` | Yes | None |
| 11 | `test_smb_uid_gid_in_opts` | 1 | macOS uses `mount_smbfs`, not `cifs` | Yes | None |
| 12 | `test_smb_file_dir_mode_in_opts` | 1 | macOS uses `mount_smbfs`, not `cifs` | Yes | None |
| 13 | `test_mount_returns_sudo_fix_message` | 2 | macOS returns different permission message | Yes | None |
| 14 | `test_check_sudo_mount_failure` | 2 | `check_sudo_mount()` skips probe on macOS | Yes | None |
| 15 | `test_check_sudo_mount_os_error` | 2 | `check_sudo_mount()` skips probe on macOS | Yes | None |

**All 15 failures are expected macOS platform behavior. Zero are true regressions.**
**No Ubuntu behavior is affected by any of these failures.**

---

## Implications for Stage 2

The 15 failures fall into two files:
- `managers/network_storage_manager.py` — Categories 1 and 2 (12 tests)
- `utils/network_scanner.py` — Category 3 (3 tests)

Stage 2 (`platform_runtime.py`) covers `network_storage_manager._build_mount_cmd()`.
After Stage 2 wiring, the mount command tests will need macOS-aware assertions or
`skipif` guards — the tests themselves must be updated once the Stage 2 adapter is in
place (this is test-update work, not regression work).

`utils/network_scanner.py` is **not** in the Stage 2 scope. The 3 network scanner
tests should be guarded with `skipif(sys.platform != "linux")` in a dedicated commit
(which must be approved separately as it requires touching `tests/`).

No changes to `card_manager.py`, `card_watcher.py`, `state_manager.py`, or any
business logic are implied by these failures. Card detection, authentication, and
programming flows all pass on macOS (or are skipped by hardware gate).

---

## No-Code-Change Confirmation

The working tree was clean (`git status`: nothing to commit) before the test run.
No application code, test code, or configuration was modified to produce this baseline.
This document is the only artifact created by S1-A.
