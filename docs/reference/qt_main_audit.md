# qt_main.py Reference Audit

**Phase 1 — completed 2026-05-21**

Audit of every reference to `qt_main.py`, `QtSimGUIApp`, and `qt_main`
across the entire repository: Python source, tests, packaging, scripts,
specs, build files, and documentation.

---

## Search terms

- `qt_main.py` (filename as string)
- `QtSimGUIApp` (class name)
- `qt_main` (module name or bare identifier)

---

## References found

### 1. `debian/rules` — line 16 (STRUCTURAL — file is packaged)

```makefile
cp -r main.py qt_main.py state_manager.py version.py ...  $(CURDIR)/debian/simgui/opt/simgui/
```

`qt_main.py` is explicitly named in the `cp` command that assembles the
`.deb` package. It is installed to `/opt/simgui/qt_main.py` on every
Ubuntu installation. The debian launcher (`debian/simgui-launcher`)
invokes only `main.py` — `qt_main.py` is dormant on disk but physically
present. **If `qt_main.py` is deleted, this line in `debian/rules` must
also be updated.**

---

### 2. `docs/PYQT6_MIGRATION_PLAN.md` — lines 129, 284, 301 (planning document)

Line 129:
```
- [ ] Create `qt_main.py` entry point (parallel to `main.py` during transition)
```

Line 284:
```
while building PyQt6 version (`qt_main.py`). Both share the same managers
```

Line 301:
```
- [ ] `qt_main.py` (NEW — entry point)
```

References in a migration planning document only. No build step, test,
or entry point invokes this file based on these references.

---

### 3. `requirements.txt` — line 6 (comment only)

```python
# PyQt6 is required for the upcoming Qt-based UI (qt_main.py).
```

Informational comment. No functional dependency.

---

### 4. `CLAUDE.md` — quarantine notice (our own rule)

The existing quarantine rule in CLAUDE.md references the file by name.
This is a control document entry, not a code dependency.

---

### 5. `qt_main.py` itself — self-references (not external)

The file's own module docstring (line 10) and class definition
(`QtSimGUIApp`, line 85) are self-references. Not counted as external
dependencies.

---

## Files confirmed clean (no references)

| File | Status |
|---|---|
| `SimGUI.spec` | Clean — PyInstaller spec names only `main.py` |
| `pyproject.toml` | Clean |
| `Makefile` | Clean |
| `install-macos-release.sh` | Clean |
| `scripts/install.sh` | Clean |
| `scripts/build-deb.sh` | Clean |
| `scripts/build-macos-app.sh` | Clean |
| `scripts/check.sh` | Clean |
| `scripts/create-release.sh` | Clean |
| `scripts/install-macos.sh` | Clean |
| `debian/control` | Clean |
| `debian/changelog` | Clean |
| `debian/postinst` | Clean |
| `debian/simgui-launcher` | Clean — invokes `main.py` only |
| `debian/simgui.desktop` | Clean |
| `tests/` (all files) | Clean — no test imports or references `qt_main` |
| `README.md` | Clean |
| All other `docs/` files | Clean (except `PYQT6_MIGRATION_PLAN.md` above) |

---

## Note on reported syntax error

CLAUDE.md states that `qt_main.py` "has a Python syntax error." The file
passes `python3 -m py_compile` without error. However, line 72 contains
a suspicious type annotation:

```python
def __init__(self, title: Optional[str, parent: QWidget]= None) -> None:
```

`Optional[str, parent: QWidget]` is not a valid type annotation —
`Optional` accepts a single type argument, and `parent: QWidget` is not
valid syntax inside a subscript. Whether this raises a `TypeError` at
class-definition time or only at instantiation time has not been verified
in this audit. The file should be treated as non-functional regardless.
The CLAUDE.md quarantine status remains correct; the precise description
("syntax error" vs "runtime error") is a secondary detail that does not
affect the quarantine ruling.

---

## Conclusion

`qt_main.py` is **not invoked by any entry point, test, build script,
CI step, or packaging launcher.** Its only structural reference is in
`debian/rules`, where it is copied into the `.deb` package alongside
`main.py` — but it sits dormant there, never executed.

**`qt_main.py` appears safe to delete in a later phase pending human
approval.** If deletion proceeds, the following changes will also be
required:

1. Remove `qt_main.py` from the `cp` command in `debian/rules` (line 16).
2. Update the quarantine entry in `CLAUDE.md`.
3. Optionally update `docs/PYQT6_MIGRATION_PLAN.md` and
   `requirements.txt` comment to reflect removal.

No other files require changes.

---

## Deletion completed — v0.5.53 (2026-05-21)

All actions recommended above have been carried out:

1. `qt_main.py` — deleted from repository (commit `7f572a0`).
2. `debian/rules` line 16 — `qt_main.py` removed from `cp` argument list.
3. `CLAUDE.md` quarantine notice — updated to record permanent removal
   and prohibit reintroduction.
4. `requirements.txt` line 6 — stale comment removed.

Tag: `v0.5.53-remove-qt-main`

This audit is now closed. `qt_main.py` must not be reintroduced.
