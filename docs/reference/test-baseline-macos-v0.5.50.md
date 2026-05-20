# Test Baseline — macOS — v0.5.50

**IMPORTANT: This is a macOS baseline only.**
It does not substitute for the authoritative Ubuntu v0.5.50 baseline.
The production baseline that must be protected is Ubuntu. This document
records macOS-specific test behaviour for comparison purposes only.

---

## Environment

| Field | Value |
|---|---|
| Platform | macOS |
| OS Version | macOS 26.4.1 (Build 25E253) |
| Python version | 3.9.6 |
| Git commit | `8324482d3640a0ab7880fcea6f50557a174ab99f` |
| Branch | `main` |
| Commit message | `docs: add platform refactoring ground rules to CLAUDE.md` |

## Pytest command

```
python3 -m pytest tests/ -q
```

## Results

| Outcome | Count |
|---|---|
| Passed | 2006 |
| Failed | 15 |
| Skipped | 351 |
| **Total collected** | **2372** |

Run time: ~38 seconds.

---

## Application Code Status

**No application code was changed for this baseline run.**
The only file modified from v0.5.50 is `CLAUDE.md` (documentation only —
ground rules for future refactoring). No Python logic, Qt code, tests,
scripts, or packaging was touched.

---

## Failures (15) — All Platform-Specific, Expected on macOS

All 15 failures are caused by tests written for Linux/Ubuntu behavior that
correctly produce different results on macOS due to the existing platform
branching in `network_storage_manager.py` (`_MACOS = sys.platform == "darwin"`)
and the Linux-specific tools tested in `test_network_scanner.py`.

**These failures are not application regressions.** They would pass on Ubuntu.
They are documented here so that a future Ubuntu baseline run can confirm they
are clean on the intended production platform.

### Group 1 — Linux-only network scanner tools (3 failures)

Tests assert that `avahi-browse` and `nmblookup` are called during SMB server
discovery. These are Linux tools not present on macOS; the scanner does not
invoke them on this platform.

| Test | Assertion | Actual |
|---|---|---|
| `test_network_scanner.py::TestScanSmbServers::test_avahi_only` | `len(servers) == 2` | `len([]) == 0` |
| `test_network_scanner.py::TestScanSmbServers::test_avahi_uses_resolve_flag` | avahi-browse was called | not called on macOS |
| `test_network_scanner.py::TestScanSmbServers::test_nmblookup_adds_new_server` | `len(servers) == 2` | `len([...]) == 1` |

### Group 2 — Linux CIFS mount syntax (9 failures)

Tests assert that `_build_mount_cmd()` produces a `mount -t cifs` command
(Linux/Ubuntu behavior). On macOS the function correctly uses `mount_smbfs`
syntax instead. This is the existing `_MACOS` platform branch in
`network_storage_manager._build_mount_cmd()`.

```
Actual macOS SMB command:
  ['/usr/bin/sudo', '/sbin/mount_smbfs', '//nas.local/simdata', '/tmp/simgui-mounts/smb-test']

Tests expected Linux CIFS command containing 'cifs', '-t', uid/gid/credentials options.
```

Affected tests:
- `test_network_storage_manager.py::TestNetworkStorageManager::test_build_mount_cmd_smb_guest`
- `test_network_storage_manager.py::TestNetworkStorageManager::test_build_mount_cmd_smb_with_username`
- `test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_uses_cifs_type`
- `test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_guest_when_no_username`
- `test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_username_in_opts_when_no_cred_file`
- `test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_domain_in_opts`
- `test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_cred_file_used_when_present`
- `test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_uid_gid_in_opts`
- `test_network_storage_manager_full.py::TestBuildMountCmd::test_smb_file_dir_mode_in_opts`

### Group 3 — Linux sudo permission model (3 failures)

Tests assert Linux-specific sudo/sudoers behavior. On macOS `check_sudo_mount()`
always returns `True` (admin users have sudo by default); the sudoers drop-in
file approach is Linux-only.

| Test | Expected | Actual |
|---|---|---|
| `TestSudoPermissionDetection::test_mount_returns_sudo_fix_message` | message contains `simgui-setup-mount` | macOS message contains Finder instructions instead |
| `TestSudoPermissionDetection::test_check_sudo_mount_failure` | `check_sudo_mount()` returns False | returns True (macOS always-True branch) |
| `TestSudoPermissionDetection::test_check_sudo_mount_os_error` | `check_sudo_mount()` returns False on OSError | returns True (macOS branch never reaches isfile check) |

---

## Skips (351) — Categorised

### Category 1 — Qt GUI tests requiring a display (~316 tests)

These tests instantiate Qt widgets or panels, which require a running `QApplication`
and a display. They are skipped on macOS without a display (CI-equivalent environment)
and on Ubuntu headless environments.

Affected test files:
- `test_batch_program_panel.py` (17 tests)
- `test_main_app.py` (~80 tests)
- `test_ui_instantiation.py` (~50 tests)
- `test_widgets_actual.py` (~30 tests)
- `test_widgets_fixed.py` (~30 tests)
- `test_widget_methods_comprehensive.py` (~15 tests)
- `test_gui_integration.py` (5 tests)
- Various others requiring widget instantiation

### Category 2 — Hardware-gated tests (2 tests)

Require `SIMGUI_HW_TEST=1` and a physical SIM card reader with an inserted card.

- `test_e2e_contracts.py::TestHardwareGated::test_detect_real_card`
- `test_e2e_contracts.py::TestHardwareGated::test_authenticate_real_card`

### Category 3 — Missing real test data files (11 tests)

Require actual EML email files or specific CSV files not present in this environment.

- `test_eml_parser.py::TestRealEmail` (7 tests) — requires a real EML file
- `test_eml_parser.py::TestCSVManagerEMLIntegration::test_load_real_eml_via_csv_manager`
- `test_csv_multi_format.py::TestCommaFormat::test_existing_sysmocom_csv`
- `test_csv_multi_format.py::TestCommaFormat::test_existing_fiskarheden_txt`
- `test_csv_multi_format.py::TestEmptyColumnWhitespace::test_actual_uk1_file`

### Category 4 — pyscard/smartcard imports (4 tests)

Tests that check `from smartcard.System import readers` and related imports
at specific line numbers in `card_manager.py`. Skipped because pyscard is not
installed in the current Python environment (only available inside the pySim venv).

- `test_interface_contracts.py::test_from_import_resolves[...:smartcard.System:56]`
- `test_interface_contracts.py::test_from_import_resolves[...:smartcard.Exceptions:57]`
- `test_interface_contracts.py::test_from_import_resolves[...:smartcard.System:85]`
- `test_interface_contracts.py::test_from_import_resolves[...:smartcard.Exceptions:86]`

### Category 5 — Simulator deck loading (1 test)

- `test_audit_fixes.py::TestSimulatorBackendDeckLoading::test_load_from_settings_path`

---

## Key Observations for Ubuntu Baseline

When the Ubuntu baseline is run, the following differences are expected:

1. **All 15 failures above should pass on Ubuntu.** They test Linux-specific
   behavior (`mount -t cifs`, sudoers model, avahi-browse, nmblookup) that is
   correct on Ubuntu.

2. **The macOS-branch of `_build_mount_cmd()` will not be exercised** unless
   tests explicitly patch `_MACOS = True`. The Ubuntu run should confirm the
   Linux path is green.

3. **Skip counts may differ.** Some tests skipped here due to missing test data
   files may pass on Ubuntu if those files are present in the Ubuntu environment.

4. **Qt GUI skips** are environment-dependent; they require a display server.
   On Ubuntu with a running desktop session or Xvfb they may un-skip.

---

## What This Baseline Does NOT Tell Us

- Whether Ubuntu v0.5.50 passes all 2006 tests cleanly — this must be verified
  on Ubuntu directly.
- Whether the 15 platform-specific failures are the complete set of macOS
  divergences, or whether there are others masked by the skip list.
- The behaviour of hardware-gated tests with a real card reader.

**The authoritative Ubuntu v0.5.50 baseline must be recorded separately
on an Ubuntu machine before any refactoring begins.**
