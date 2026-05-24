# Release Readiness Audit — v0.5.56

**Audit date:** 2026-05-24  
**Branch:** main  
**Head commit:** `dfe953a` — docs: refresh stale simulator reference audit  
**Checkpoint tag:** `v0.5.56-hardware-only-docs-clean`  
**This audit does not modify debian/changelog.**

---

## Executive Summary

| Target | Status | Blockers |
|--------|--------|----------|
| Ubuntu `.deb` build | ⚠️ Buildable but not release-ready | 3 hard blockers in `debian/control`; version drift |
| Ubuntu source install | ✅ Ready | None (caveats noted) |
| macOS source install | ✅ Ready | None (caveats noted) |

**One release-prep commit is required before cutting a `.deb` release.** All three hard
blockers are in `debian/control`. Version numbers must be bumped together with the
changelog entry in that same commit.

---

## File-by-File Findings

### debian/rules — ✅ CLEAN

The `cp` command at line 16 currently reads:

```
cp -r main.py state_manager.py version.py theme.py qt_theme.py pyproject.toml requirements.txt managers/ widgets/ dialogs/ utils/ assets/ etc/ $(CURDIR)/debian/simgui/opt/simgui/
```

- `simulator/` removed (Commit 3 of simulator-cleanup, `9a27676`). ✅
- `qt_main.py` removed (qt_main audit, commit `7f572a0`). ✅
- All remaining paths match files present in the repository. ✅
- Launcher, desktop entry, icons, and `BUILD`/`sim-standard.example.json` install correctly. ✅

No action needed.

---

### debian/control — ⛔ THREE HARD BLOCKERS

**File:** `debian/control`, current content shown below with blockers annotated.

#### Blocker 1 — Description contains stale simulator claim (line 16)

```
 Includes a built-in simulator mode for hardware-free testing with 20 real
 sysmoISIM-SJA5 card profiles.
```

The simulator mode was removed in v0.5.55-hardware-only. This sentence is factually wrong
for every package built from current source.

**Fix:** Replace with a hardware-only description. Suggested replacement:

```
 Hardware-only mode: pySim or sysmo-usim-tool is required for all SIM card
 operations. A USB PCSC-compatible card reader is needed for hardware use.
```

#### Blocker 2 — `python3-tk` in Depends is stale

```
Depends: python3 (>= 3.8), python3-tk, python3-pip, ...
```

The application migrated from tkinter to PyQt6. `python3-tk` is no longer imported or
used. Listing it as a hard dependency installs an unnecessary package on every system.

**Fix:** Remove `python3-tk` from Depends.

#### Blocker 3 — `python3-pyqt6` is Recommends; must be Depends

```
Recommends: python3-venv, python3-pyqt6
```

PyQt6 is the sole UI framework. Without it, `main.py` fails to import on line 1:

```python
from PyQt6.QtWidgets import QApplication
```

A package listed as Recommends is not installed by default on `dpkg -i` without
`apt install -f` — it is optional. This is incorrect for PyQt6.

**Fix:** Move `python3-pyqt6` from Recommends to Depends.

---

#### Advisory — `libpcsclite-dev` and `swig` in Depends (non-blocking)

```
Depends: ..., libpcsclite-dev, swig, ...
```

`libpcsclite-dev` and `swig` are build-time (compilation) dependencies, not runtime
dependencies. They were added because `pyscard` (the PCSC Python binding) compiles a
C extension and needs these headers. However:

- The `.deb` itself does not compile anything — it is a pure Python install.
- `pyscard` is installed via `pip` in `postinst`, where the build headers are needed at
  that moment, not at package install time.
- The correct packaging solution is to either ship `pyscard` as a pre-compiled wheel in
  the package or keep these in Depends with an explicit comment explaining the pip path.

**Current state:** Functional but non-standard. The package installs development headers
(~15 MB) on every end-user system as a runtime dependency.  

**Recommended fix (release-prep commit):** Document the reason inline. Optionally replace
`libpcsclite-dev` with `libpcsclite1` (the runtime library, not headers) and `pcscd`,
and install pyscard from a pre-built wheel. This is a larger change — defer unless the
dev-header bloat becomes an issue.

---

#### Advisory — Qt runtime libraries not declared in Depends (non-blocking for one-liner installs)

`scripts/install.sh` explicitly installs three Qt runtime libraries:

```bash
apt-get install -y -qq libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0
```

These are not declared in `debian/control Depends`. A user who installs the `.deb`
directly (without the one-liner) on a minimal Ubuntu system may see the Qt "xcb plugin"
error at launch.

**Fix (release-prep commit):** Add to Depends:
```
libxcb-cursor0, libxcb-xinerama0, libxkbcommon-x11-0
```

---

### debian/changelog — READ-ONLY

Latest entry: `simgui (0.5.50)` — John Fornehed, Mon 19 May 2026.

The following work was done after the `0.5.50` entry without a changelog update:

| Work | Commits |
|------|---------|
| Simulator removal (Commits 1–9) | `edd23af` – `dd90d2b` |
| Simulator reference cleanup (Commits 1–6) | `ed0f184` – `2174434` |
| Audit refresh | `dfe953a` |
| Checkpoint tag | `v0.5.56-hardware-only-docs-clean` |

A changelog entry for `0.5.56` is needed before cutting a release. The entry should
summarise all simulator-removal and docs-cleanup work. **This entry must be written in
the release-prep commit together with the `version.py` bump.** See Recommended Commits
below.

Historical simulator references in `debian/changelog` (lines for `0.5.37`, `0.5.0`) are
correct historical records and must not be modified.

---

### scripts/install.sh — ✅ CLEAN

- Simulator fallback message corrected in Commit 1 (`ed0f184`). ✅
- pySim install path, venv setup, GialerSim SPN patch, pcscd enable, sudoers rule,
  and smartcard hotplug monitor are all correct and current. ✅
- Version number in the final `dpkg-query` line is read dynamically — no hardcoded
  version. ✅

No action needed.

---

### scripts/create-release.sh — ⚠️ STALE (macOS path only, not Ubuntu blocker)

```bash
VERSION="v0.5.37"
ARTIFACT="dist/SimGUI.dmg"
```

The script is hardcoded to `v0.5.37` and uploads a macOS `.dmg` artifact. It is not
used in the Ubuntu `.deb` path. Ubuntu releases go through `install.sh` which calls
`dpkg-buildpackage` directly.

The release notes in this script are v0.5.37-specific (macOS support announcement, May 9
2026 date, commit hash `9066a10`).

**This is not a blocker for Ubuntu .deb builds.** It must be updated before the next
macOS `.dmg` release.

**Fix (macOS release-prep):** Update `VERSION`, release notes body, build date, and
commit hash to match the release being cut. Consider parameterising VERSION instead of
hardcoding it.

---

### scripts/install-macos.sh — ⚠️ STALE COMMENT (known Commit 7 item)

Line 4:
```bash
# Casual users should just download SimGUI.app and run it (simulator mode works out of the box).
```

This is the remaining stale simulator reference flagged in `stale-simulator-reference-audit.md`
as a Commit 7 action. Not a blocker for Ubuntu `.deb` builds. Fix is scoped to Commit 7.

---

### README.md — ✅ CLEAN

- Simulator feature entry removed (Commit 5). ✅
- Requirements section is hardware-only. ✅
- macOS `.pkg` status note is accurate ("in progress"). ✅
- No `qt_main.py` references. ✅

---

### docs/how-to/install.md — ✅ CLEAN

- Simulator claims removed (Commit 5). ✅
- pySim described as required for SIM operations. ✅
- macOS section is accurate. ✅

---

### pyproject.toml — ✅ CLEAN

No packaging issues. No simulator or qt_main references.

---

### requirements.txt — ⚠️ ADVISORY ONLY

**Comment inconsistency (non-blocking):**

```
# tkinter is part of the Python standard library (no pip install needed).
# On Debian/Ubuntu you may need: sudo apt install python3-tk
```

This comment describes tkinter, but the app no longer uses tkinter. The comment above
`Pillow>=10.0` says "required for PNG icons in PyInstaller bundle" — this is a macOS
PyInstaller-specific dependency; Ubuntu runtime does not need Pillow.

Neither of these is a build blocker. The `requirements.txt` is installed by `postinst`
via pip; Pillow on Ubuntu does no harm. However, the tkinter comment is misleading for
anyone reading the file to understand dependencies.

**Fix (release-prep commit, optional):** Remove the tkinter comment block; annotate
Pillow as macOS/PyInstaller-only.

---

### version.py — ⛔ VERSION DRIFT

```python
__version__ = "0.5.50"
```

The checkpoint tag is `v0.5.56-hardware-only-docs-clean`. The version string in code,
the debian/changelog top entry, and the deployed tag are inconsistent:

| Source | Value |
|--------|-------|
| `version.py` | `0.5.50` |
| `debian/changelog` top | `0.5.50` |
| Latest git tag | `v0.5.56-hardware-only-docs-clean` |

`version.py` and `debian/changelog` must be bumped together. They are currently
consistent with each other (`0.5.50`) but both lag the tag by six version steps.

---

## Readiness Verdict

### Ubuntu `.deb` build

**Buildable but not release-ready.** `dpkg-buildpackage` will succeed — the package
will compile and install. However, the resulting package has three user-visible defects:

1. The package description advertises a removed feature (simulator mode).
2. `python3-tk` is listed as required and will be installed unnecessarily.
3. `python3-pyqt6` is optional (Recommends) but the application cannot run without it.

A `.deb` cut from current source would work for an operator who already has PyQt6
installed, but the package metadata would mislead any packaging tool or future maintainer.

### Ubuntu source install

**Ready.** `git clone` + `pip install -r requirements.txt` + `python3 main.py` works.
pySim must be separately installed (documented in README and install.md).

### macOS source install

**Ready.** Same as Ubuntu source path with `PYSIM_PATH` set.

---

## Recommended Release-Prep Commits

### Commit A — `debian/control` corrections (hard blockers)

Scope: `debian/control` only.

1. Remove stale simulator claim from Description (last two lines of Description field).
2. Remove `python3-tk` from Depends.
3. Move `python3-pyqt6` from Recommends to Depends.
4. Add `libxcb-cursor0, libxcb-xinerama0, libxkbcommon-x11-0` to Depends (Qt runtime).

Suggested commit message: `fix: correct debian/control — remove stale deps, promote PyQt6 to Depends`

### Commit B — Version bump + debian/changelog entry

Scope: `version.py` + `debian/changelog` only.

Bump `version.py` to `0.5.56`. Add `debian/changelog` entry for `simgui (0.5.56)`:

```
simgui (0.5.56) unstable; urgency=medium

  * chore: remove simulator mode and all simulator package files
    (SimulatorBackend, VirtualCard, CardDeck, SimulatorSettings, simulator/)
  * chore: remove all user-facing simulator-as-feature references from docs,
    scripts, and packaging; hardware-only mode is now the sole operational mode
  * fix: debian/control — remove python3-tk stale dep, promote python3-pyqt6
    to Depends, add Qt runtime libraries, remove simulator description claim
```

Suggested commit message: `chore: bump version to 0.5.56 and record changelog`

### Commit C — requirements.txt comment cleanup (optional, low priority)

Scope: `requirements.txt` only.

Remove stale tkinter comment; annotate Pillow as macOS/PyInstaller-specific.

Suggested commit message: `chore: remove stale tkinter comment from requirements.txt`

---

## What Is Explicitly Excluded From This Audit's Scope

- `tests/test_main_app.py` — globally skipped; delete with PyQt6 migration cleanup.
- Commit 7 items (`troubleshooting.md`, `CLAUDE.md`, test files) — scoped separately in
  `stale-simulator-reference-audit.md`.
- `scripts/create-release.sh` version update — macOS release path only; update when
  cutting the macOS release.

---

## Appendix — debian/control As-Found vs Recommended

### As-found (current)

```
Depends: python3 (>= 3.8), python3-tk, python3-pip, libpcsclite-dev, swig, cifs-utils, nfs-common, smbclient, avahi-utils
Recommends: python3-venv, python3-pyqt6
Description: GUI wrapper for SIM card programming tools
 SimGUI is a lightweight GUI wrapper for sysmo-usim-tool and pySim.
 It provides a desktop interface for SIM card detection, ADM1
 authentication, CSV batch editing, and card programming. Includes
 a built-in simulator mode for hardware-free testing with 20 real
 sysmoISIM-SJA5 card profiles.
```

### Recommended (after Commit A)

```
Depends: python3 (>= 3.8), python3-pyqt6, python3-pip, libpcsclite-dev, swig, cifs-utils, nfs-common, smbclient, avahi-utils, libxcb-cursor0, libxcb-xinerama0, libxkbcommon-x11-0
Recommends: python3-venv
Description: GUI wrapper for SIM card programming tools
 SimGUI is a lightweight GUI wrapper for sysmo-usim-tool and pySim.
 It provides a desktop interface for SIM card detection, ADM1
 authentication, CSV batch editing, and card programming.
 Hardware-only mode: pySim or sysmo-usim-tool is required for all
 SIM card operations. A USB PCSC-compatible card reader is needed.
```
