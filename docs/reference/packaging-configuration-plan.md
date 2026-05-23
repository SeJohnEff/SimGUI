# Packaging Configuration Plan

**Phase: S4-B — Audit and Plan only. No implementation.**
**Status: PLANNING — awaiting human approval before any changes.**
**Baseline: Ubuntu v0.5.50 — 2140 passed, 323 skipped.**

---

## 1. Current Ubuntu .deb Packaging Behavior

### Build pipeline

`scripts/install.sh` drives the full Ubuntu install flow:

1. Installs build dependencies: `git`, `dpkg-dev`, `debhelper`, `pcscd`, `pcsc-tools`, `python3-pyscard`.
2. Clones the repo into a `mktemp` directory.
3. Writes the git short-SHA into a `BUILD` file at the repo root.
4. Runs `dpkg-buildpackage -us -uc -b` to produce `simgui_*.deb`.
5. Installs with `dpkg -i`, then `apt-get install -f` to resolve any missing deps.
6. Clones pySim to `/opt/pysim`, sets up a `.venv`, installs pySim deps.
7. Applies the GialerSim SPN patch to `/opt/pysim/pySim/legacy/cards.py`.
8. Installs the sudoers rule for passwordless network-share mount/umount.
9. Installs and enables `smartcard-hotplug-monitor.service`.

### `debian/rules` — what gets installed

`override_dh_auto_install` copies the following into `/opt/simgui/` on the target system:

```
main.py
qt_main.py          ← quarantined stub; installed but never executed
state_manager.py
version.py
theme.py
qt_theme.py
pyproject.toml
requirements.txt
managers/
simulator/          ← DELETED in v0.5.55-hardware-only; must be removed from debian/rules
widgets/
dialogs/
utils/
assets/
etc/
BUILD               (optional, created by install.sh before build)
sim-standard.example.json (optional)
bin/simgui-setup-mount
```

> **Outstanding packaging fix:** `simulator/` was intentionally deleted as part of the
> simulator-mode removal (tag `v0.5.55-hardware-only`). The `cp` command in `debian/rules`
> line 16 still includes `simulator/` and will cause a `.deb` build failure. This must be
> removed in a dedicated packaging fix commit (requires separate approval per §10).

Additional items installed to system paths:
- `/usr/bin/simgui-setup-mount` → symlink to `/opt/simgui/bin/simgui-setup-mount`
- `/usr/bin/simgui` → `debian/simgui-launcher` script
- `/usr/share/applications/simgui.desktop`
- Icon set at 16×16, 32×32, 48×48, 64×64, 128×128, 256×256 from `assets/`

### `debian/simgui-launcher`

The launcher sets `PATH` and `HOME`, `cd`s to `/opt/simgui`, then:

```bash
exec python3 /opt/simgui/main.py "$@"
```

`qt_main.py` is **never invoked** by the launcher or any packaging script.

### `debian/postinst`

- Installs Python pip dependencies from `requirements.txt` (break-system-packages fallback).
- Copies `etc/simgui-mount.sudoers` to `/etc/sudoers.d/simgui-mount` (validated by `visudo -c` first).
- Ensures `cifs-utils` is installed.

### `debian/control` dependencies

```
Depends: python3 (>= 3.8), python3-tk, python3-pip, libpcsclite-dev,
         swig, cifs-utils, nfs-common, smbclient, avahi-utils
Recommends: python3-venv, python3-pyqt6
```

Note: `python3-tk` is listed as a hard `Depends` from a prior tkinter era. The
application now uses PyQt6. This is a known stale dependency but is harmless.
It must not be removed without verifying no code path requires it.

### `debian/compat`

Single-line file; not shown in audit details. No changes needed.

---

## 2. qt_main.py References in Packaging

**COMPLETED — v0.5.53 (2026-05-21, tag `v0.5.53-remove-qt-main`)**

`qt_main.py` has been permanently deleted. All packaging references have
been removed. See `docs/reference/qt_main_audit.md` for the full audit
and completion record.

| File | Line | Nature | Status |
|------|------|--------|--------|
| `debian/rules` | 16 | `cp` argument — file was physically packaged | **Removed** |
| `requirements.txt` | 6 | comment only | **Removed** |
| `CLAUDE.md` | quarantine notice | control document | **Updated to tombstone** |

---

## 3. qt_main.py Deletion — COMPLETED

**Completed in commit `7f572a0`, tag `v0.5.53-remove-qt-main`.**

All three required changes were made:

### 3a. `debian/rules` — `qt_main.py` removed from `cp` command

Updated line 16 (after `qt_main.py` removal, commit `7f572a0`) read:
```makefile
cp -r main.py state_manager.py version.py theme.py qt_theme.py pyproject.toml requirements.txt managers/ simulator/ widgets/ dialogs/ utils/ assets/ etc/ $(CURDIR)/debian/simgui/opt/simgui/
```

> **Note:** The `simulator/` directory shown above has since been deleted
> (`v0.5.55-hardware-only`). The target state of `debian/rules` line 16 is:
> ```makefile
> cp -r main.py state_manager.py version.py theme.py qt_theme.py pyproject.toml requirements.txt managers/ widgets/ dialogs/ utils/ assets/ etc/ $(CURDIR)/debian/simgui/opt/simgui/
> ```
> This change to `debian/rules` has not yet been made and requires explicit approval
> per §10 before implementation.

### 3b. `CLAUDE.md` — quarantine notice replaced with tombstone

The quarantine notice now states that `qt_main.py` has been permanently
removed and must not be reintroduced.

### 3c. Documentation cleanup completed

- `requirements.txt` line 6: stale comment removed.

`qt_main.py` must not be reintroduced.

---

## 4. macOS Packaging Options

### 4a. Current supported mode: source-based install

macOS users run SimGUI directly from source:

```bash
cd /path/to/SimGUI
python3 main.py
```

This is documented in `docs/how-to/install.md` and is the **only currently supported
macOS mode**. It requires:
- Python 3.10+ (Homebrew recommended)
- PyQt6 (`pip3 install PyQt6`)
- pySim at `~/pysim` or `PYSIM_PATH` env var
- pyscard for hardware card access

The developer install script `scripts/install-macos.sh` automates pySim setup.

### 4b. PyInstaller `.app` bundle — exists but blocked

`SimGUI.spec` (repo root) is a working PyInstaller spec file targeting `main.py`.
`scripts/build-macos-app.sh` runs `pyinstaller SimGUI.spec --clean` and produces
`dist/SimGUI.app`.

**Known blocker (documented in `docs/TODO.md`):** The app bundle crashes on GUI init
due to asset loading from a temp directory during PyInstaller bootstrap. The root cause
is PNG asset resolution at runtime, not a logic error. This is not investigated further
in S4-B.

`SimGUI.spec` lists the following `hiddenimports`:
```python
'smartcard', 'smartcard.scard', '_smartcard',
'tkinter', 'PIL', 'PIL.ImageTk'
```

`tkinter` and `PIL`/`Pillow` are legacy imports from the tkinter era. These should be
removed before any `.app` distribution is attempted, after verifying no code path
requires them.

### 4c. `.pkg` installer — not yet implemented

No macOS `.pkg` packaging exists. This would require a `pkgbuild`/`productbuild`
workflow, a `postinstall` script (analogous to `debian/postinst`), and code-signing.
This is a future consideration only.

### 4d. Homebrew formula — not applicable at this stage

The codebase targets internal operator use, not general distribution. A Homebrew
formula is not required. It would require a stable release cadence and a public
download URL. Deferred indefinitely.

---

## 5. Recommendation: Defer PyInstaller/.app/.pkg

**Recommendation: defer all macOS binary packaging until after the Ubuntu baseline
is re-verified on Ubuntu hardware (not UTM), the PyInstaller asset-loading blocker
is diagnosed, and `qt_main.py` is formally retired.**

The asset-loading crash (see `docs/TODO.md`) means the `.app` bundle cannot be
distributed today without silently crashing at startup. Shipping a broken `.app`
is worse than source-only, because it gives users a false confidence that a
binary distribution exists.

Source-based install on macOS is stable, tested, and documented. It is the correct
current mode.

---

## 6. Files Allowed in a Future Packaging Implementation

A future packaging implementation (either Ubuntu cleanup or macOS bundle) may only
touch the files listed below. Any file not on this list requires a new explicit
approval before it is modified.

### Ubuntu .deb cleanup (permitted scope)

| File | Permitted change |
|------|-----------------|
| `debian/rules` | Remove `qt_main.py` from `cp` line after qt_main deletion approval |
| `debian/rules` | Remove `state_manager.py`, `theme.py`, `qt_theme.py` if they are also deleted/renamed |
| `debian/control` | Remove stale `python3-tk` from `Depends` (verify first) |
| `debian/postinst` | Add GialerSim SPN patch application (mirrors `scripts/install.sh`) |
| `scripts/install.sh` | Minor fixes; no logic changes |
| `debian/simgui-launcher` | Path or env changes only |

### macOS PyInstaller (permitted scope, only after blocker resolved)

| File | Permitted change |
|------|-----------------|
| `SimGUI.spec` | Remove legacy `tkinter`/`PIL` hidden imports; update `datas` |
| `scripts/build-macos-app.sh` | Minor fixes to the build script |

---

## 7. Files That Must Not Change

These files are frozen for S4-B and any future packaging implementation unless
explicitly approved in writing:

| File | Reason |
|------|--------|
| `debian/rules` | Frozen except for the single `qt_main.py` removal described in §3 |
| `docs/reference/state-machine.md` | Behavioral authority — never modified by packaging work |
| `managers/card_manager.py` | Business logic — no packaging changes touch this |
| `managers/card_watcher.py` | Business logic — same |
| `managers/csv_manager.py` | Business logic — same |
| `main.py` | Entry point — no changes during packaging work |
| `version.py` | Only bumped as part of a release, not packaging cleanup |
| `debian/changelog` | Only bumped together with `version.py` for a release |
| Any `tests/` file | Test suite must pass before and after every packaging change |

---

## 8. Required Checks Before and After Any Packaging Implementation

### Before starting

1. Run full test suite on Ubuntu and confirm baseline: `python3 -m pytest tests/ -x -q`
2. Confirm the baseline matches the recorded Ubuntu v0.5.50 baseline
   (`docs/reference/test-baseline-ubuntu-v0.5.50.md`).
3. Record exact pass/skip/fail counts as the pre-implementation snapshot.
4. Confirm `debian/rules` builds a working `.deb` from a clean clone:
   `dpkg-buildpackage -us -uc -b` and `dpkg -i simgui_*.deb`.
5. Confirm `simgui` (launcher) starts without error after the `.deb` install.

### After each change

1. Run full test suite: `python3 -m pytest tests/ -x -q`
2. Pass/skip counts must match the pre-implementation snapshot exactly.
3. For `debian/rules` changes: rebuild `.deb` from a clean clone and verify launch.
4. For `scripts/install.sh` changes: run on a fresh Ubuntu 22.04 VM and verify
   the full install flow from clone to `simgui` launch.

### macOS-specific (if PyInstaller work proceeds)

1. Run full test suite on macOS: `python3 -m pytest tests/ -x -q`
2. Confirm pass/skip counts match `docs/reference/test-baseline-macos-stage1.md`.
3. Build the `.app`: `./scripts/build-macos-app.sh`
4. Launch `dist/SimGUI.app` and confirm it reaches the main window without crashing.
5. Confirm the app starts in hardware mode and displays the expected "No card reader" or
   "Insert a SIM card" status. Simulator mode no longer exists.

---

## 9. Rollback Conditions

Any of the following conditions require an immediate stop and rollback to the
last known-good commit:

- Test suite pass count drops below the pre-implementation baseline (any regression).
- The `.deb` build fails (`dpkg-buildpackage` exits non-zero).
- The installed `simgui` launcher fails to start `main.py`.
- The Ubuntu `simgui` binary produces different behavior on any observable operation
  compared to the v0.5.50 baseline.
- A state-machine invariant from `docs/reference/state-machine.md` is violated
  (even if tests still pass — state-machine compliance is a separate check).
- The macOS `.app` crashes at startup (if PyInstaller work is in scope).
- Any common module (`card_manager.py`, `card_watcher.py`, `csv_manager.py`)
  fails to import cleanly on Ubuntu after a change.

Rollback procedure: `git revert HEAD` or `git reset --hard <last-good-SHA>`.
Never use `--force` push to `main` without explicit human approval.

---

## 10. Human Approval Gate

**No implementation may start without explicit written approval from the human.**

The following decisions each require separate approval:

| Decision | Requires approval before |
|----------|--------------------------|
| Delete `qt_main.py` | Any commit that removes the file |
| Modify `debian/rules` | Any commit that changes the file |
| Start macOS PyInstaller work | Any build-script or spec change |
| Change `debian/control` dependencies | Any `Depends`/`Recommends` edit |
| Bump `version.py` + `debian/changelog` for a release | Version increment commit |

**The existence of this plan document is not approval for implementation.**
This document is audit output only. Approval must be given explicitly in conversation.

---

## Summary

| Area | Current state | Required before implementation |
|------|--------------|-------------------------------|
| Ubuntu .deb | Working; builds and installs cleanly | Human approval; Ubuntu baseline re-verified |
| qt_main.py in packaging | Installed to `/opt/simgui/`; never executed | Human approval for deletion; then remove from `debian/rules` line 16 |
| macOS source install | Supported and documented | No changes needed |
| macOS PyInstaller `.app` | Spec exists; blocker: asset-load crash at startup | Blocker diagnosed and fixed; human approval |
| macOS `.pkg` | Not implemented | Not recommended at this stage |
