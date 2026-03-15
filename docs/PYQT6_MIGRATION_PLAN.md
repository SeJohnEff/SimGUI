# SimGUI — PyQt6 Migration Plan

**Version:** 1.0  
**Date:** 2026-03-15  
**Status:** PROPOSAL — awaiting approval

---

## 1. Executive Summary

Migrate the SimGUI desktop application from tkinter to PyQt6, adopting a
`StateManager` + Qt signals architecture as proposed by the project owner.

| Metric | Value |
|--------|-------|
| Source lines to rewrite | 5,602 (16 files) |
| Source lines untouched | 4,663 (25 files — managers, utils, simulator) |
| Test lines to rewrite | 5,756 (11 test files) |
| Test lines untouched | 13,949 (44 test files) |
| Estimated effort | 4 phases, ~6–8 working sessions |
| Risk level | Medium — clean manager/UI separation already exists |

---

## 2. Why Migrate

| Problem (tkinter) | Solution (PyQt6) |
|---|---|
| `root.after(0, ...)` thread dispatch — error-prone, caused 20s timeout bug | Qt signals are thread-safe by design; `signal.emit()` auto-queues to UI thread |
| `StringVar`/`trace_add` boilerplate (36 StringVars counted) | `QProperty` + signal bindings, or direct `setText()` in slots |
| `TclError` crashes from empty/null values (e.g., `foreground=""`) | Qt widgets accept empty strings and None gracefully |
| No built-in async pattern — callback spaghetti (217 callback wires) | Signal/slot decoupling; `QThread` + `Worker` pattern |
| Themed look requires manual `ttk.Style` overrides (171 lines in theme.py) | Qt stylesheets (CSS-like) or QDarkStyle; native look on all platforms |
| `messagebox` / `filedialog` — modal, blocking, non-copyable text | `QMessageBox`, `QFileDialog` — fully copyable, richer controls |
| No tree/table widget (would need for future batch view) | `QTableView` / `QTreeView` with model/view architecture |

---

## 3. Architecture: StateManager + Signals

The new architecture (as proposed) uses a central `StateManager` that owns
all application state as Python properties, emitting Qt signals on change.
UI widgets subscribe to signals — no direct coupling between panels.

```
┌──────────────────────────────────────────────────────────┐
│                     StateManager                         │
│                                                          │
│  Properties (with signal emission):                      │
│    card_state, card_data, iccid, csv_path,               │
│    share_connected, share_label, mode,                   │
│    batch_running, status_text, ...                       │
│                                                          │
│  Signals:                                                │
│    card_state_changed(str)                                │
│    card_data_changed(dict)                                │
│    share_status_changed(bool)                             │
│    csv_loaded(str)                                        │
│    status_changed(str)                                    │
│    ...                                                    │
└───────────┬───────────┬───────────┬──────────────────────┘
            │           │           │
     ┌──────▼──┐  ┌─────▼────┐  ┌──▼───────────┐
     │ CardPanel│  │ProgramTab│  │ BatchTab     │
     │ (reads   │  │(reads +  │  │(reads +      │
     │  signals)│  │ writes)  │  │ writes)      │
     └─────────┘  └──────────┘  └──────────────┘
```

### Signal flow example — card inserted

```
CardWatcher (thread)
  └─→ StateManager.set_card_data(data)      # setter emits signal
        ├─→ CardStatusPanel.on_card_data()   # updates fields
        ├─→ ProgramSimPanel.on_card_data()   # populates form
        └─→ MainWindow.on_card_data()        # updates status bar
```

### What stays the same

The entire **managers/** layer (card_manager, csv_manager, batch_manager,
network_storage_manager, iccid_index, card_watcher, etc.) is
**framework-independent** and will NOT be modified. The StateManager wraps
these managers, translating their callbacks into Qt signals.

---

## 4. Mapping: tkinter → PyQt6

| tkinter | PyQt6 | Count |
|---------|-------|-------|
| `tk.Tk` / `tk.Toplevel` | `QMainWindow` / `QDialog` | 7 |
| `ttk.Frame` | `QWidget` / `QFrame` | 56 |
| `ttk.Label` | `QLabel` | 67 |
| `ttk.Button` | `QPushButton` | 49 |
| `ttk.Entry` | `QLineEdit` | 23 |
| `ttk.Combobox` | `QComboBox` | 6 |
| `ttk.Checkbutton` | `QCheckBox` | 5 |
| `ttk.Radiobutton` | `QRadioButton` | 7 |
| `ttk.Spinbox` | `QSpinBox` | 5 |
| `ttk.LabelFrame` | `QGroupBox` | 19 |
| `ttk.Scrollbar` | `QScrollBar` (auto in `QScrollArea`) | 11 |
| `tk.Text` | `QTextEdit` / `QPlainTextEdit` | 8 |
| `tk.Menu` | `QMenuBar` / `QMenu` | 5 |
| `tk.StringVar` + `trace_add` | Signal/slot or direct property | 36 |
| `tk.BooleanVar` | Python bool + signal | 7 |
| `.pack()` / `.grid()` | `QVBoxLayout` / `QHBoxLayout` / `QGridLayout` | 169+85 |
| `root.after(ms, fn)` | `QTimer.singleShot(ms, fn)` or signal | 21 |
| `messagebox.showinfo/error/warning` | `QMessageBox.information/critical/warning` | 66 |
| `filedialog.askopenfilename` | `QFileDialog.getOpenFileName` | ~8 |
| `tk.TclError` exception handling | Remove (Qt doesn't throw for empty values) | 17 |
| `theme.py` (ttk.Style) | `app.setStyleSheet(...)` or QDarkStyle | 1 file |

---

## 5. Migration Phases

### Phase 0 — Foundation (smallest, do first)

**Scope:** StateManager, theme, project scaffolding  
**Lines:** ~400 new  
**Files:** 2 new + 1 modified  

- [ ] Create `state_manager.py` with all properties + signals
- [ ] Create `qt_theme.py` (stylesheet replacing ttk theme)
- [ ] Add `PyQt6` to `requirements.txt` / `install.sh`
- [ ] Update `setup.py` / packaging
- [ ] Create `qt_main.py` entry point (parallel to `main.py` during transition)

**Risk:** Low — additive, doesn't break anything  
**Test:** Unit test StateManager signal emissions

---

### Phase 1 — Small Widgets & Dialogs (high count, low complexity)

**Scope:** 10 files — small dialogs + simple widgets  
**Lines to rewrite:** ~1,830  

| File | Lines | Complexity | Notes |
|------|-------|-----------|-------|
| `widgets/tooltip.py` | 156 | Low | → `QToolTip` (mostly delete) |
| `widgets/toast.py` | 106 | Low | → `QLabel` with `QTimer` fade |
| `widgets/info_dialog.py` | 119 | Low | → `QDialog` |
| `widgets/card_status_panel.py` | 137 | Low | 6 labels, 2 buttons |
| `widgets/progress_panel.py` | 131 | Low | `QProgressBar` + `QLabel` |
| `widgets/csv_editor_panel.py` | 178 | Medium | `QTableWidget` |
| `dialogs/adm1_dialog.py` | 203 | Medium | Grid layout |
| `dialogs/simulator_settings_dialog.py` | 138 | Low | 3 fields |
| `dialogs/artifact_export_dialog.py` | 221 | Medium | File browser + options |
| `dialogs/load_card_file_dialog.py` | 250 | Medium | Tree view |

**Risk:** Low — each can be migrated and tested independently  
**Test:** Rewrite 6 test files (~2,700 lines) using `pytest-qt`

---

### Phase 2 — Complex Widgets (core panels)

**Scope:** 4 files — the main working panels  
**Lines to rewrite:** ~2,261  

| File | Lines | Complexity | Notes |
|------|-------|-----------|-------|
| `widgets/read_sim_panel.py` | 397 | Medium | Form + pySim integration |
| `widgets/program_sim_panel.py` | 529 | High | Form + validation + callbacks |
| `widgets/batch_program_panel.py` | 938 | High | Most complex widget; ranges, CSV, generate |

**Risk:** Medium — batch panel is the most complex; needs careful signal wiring  
**Test:** Rewrite 4 test files (~2,400 lines)

---

### Phase 3 — MainWindow + Integration

**Scope:** 2 files — main.py + theme.py  
**Lines to rewrite:** ~1,240  

| File | Lines | Complexity | Notes |
|------|-------|-----------|-------|
| `main.py` | 1,069 | High | Menu, tabs, status bar, startup, card watcher |
| `theme.py` | 171 | Medium | → stylesheet in qt_theme.py |

**Risk:** Medium-High — this is where everything connects  
**Test:** Rewrite `test_main_app.py` (747 lines), `test_ui_instantiation.py` (1,489 lines)

---

### Phase 4 — Network Dialog + Cleanup

**Scope:** 1 large file + final integration  
**Lines to rewrite:** ~859  

| File | Lines | Complexity | Notes |
|------|-------|-----------|-------|
| `dialogs/network_storage_dialog.py` | 859 | High | Threading, scanning, SMB mount, test button |

**Risk:** Medium — complex async patterns, but benefits most from Qt threading  
**Test:** Existing tests are pure-logic (already framework-independent)  
**Cleanup:** Remove all tkinter imports, delete old `main.py`, update `__init__.py` files

---

## 6. Effort Estimate

| Phase | Source Lines | Test Lines | Sessions | Tokens (est.) |
|-------|-------------|-----------|----------|---------------|
| 0 — Foundation | ~400 new | ~200 new | 1 | Low |
| 1 — Small widgets | ~1,830 rewrite | ~2,700 rewrite | 1–2 | Medium |
| 2 — Complex widgets | ~2,261 rewrite | ~2,400 rewrite | 2 | Medium-High |
| 3 — MainWindow | ~1,240 rewrite | ~2,236 rewrite | 1–2 | Medium-High |
| 4 — Network dialog | ~859 rewrite | ~400 new | 1 | Medium |
| **Total** | **~5,602 + 400** | **~5,756 + 600** | **6–8** | |

### Token-saving strategies (per user request)

1. **Use cheaper models for planning/boilerplate:** Phase 0 and Phase 1
   are straightforward widget mapping — ideal for Sonnet-class models.
2. **Use stronger models for complex logic:** Phase 2 (batch panel) and
   Phase 3 (main.py integration) benefit from deeper reasoning.
3. **Migrate source + tests together per file:** Avoids context-switching
   overhead between sessions.
4. **Framework-independent code stays untouched:** 4,663 source lines
   and 13,949 test lines require ZERO changes.

---

## 7. Dependencies & Prerequisites

### New Python packages

```
PyQt6 >= 6.6
pytest-qt >= 4.4      # for testing
```

### Ubuntu install changes (`install.sh`)

```bash
# Replace python3-tk with:
sudo apt-get install -y python3-pyqt6
# Or pip install in venv:
pip install PyQt6
```

### Compatibility

- PyQt6 supports Python 3.9+ ✓
- PyQt6 has ARM/aarch64 wheels (Ubuntu on M4 UTM) ✓
- No tkinter dependency remains after Phase 4

---

## 8. Risk Register

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Batch panel signal complexity | High | Medium | Migrate batch_program_panel first within Phase 2; extensive test coverage |
| Thread dispatch regressions | High | Low | Qt signals handle cross-thread automatically; simpler than `after(0, ...)` |
| PyQt6 licensing (GPL v3) | Medium | Low | SimGUI is already distributed as open source on GitHub |
| ARM/aarch64 PyQt6 wheel availability | Medium | Low | Verified: PyQt6 has aarch64 wheels on PyPI |
| Test migration introduces regressions | Medium | Medium | Migrate tests file-by-file with green CI between each |
| Theme/styling differences | Low | Medium | Create Qt stylesheet early in Phase 0; iterate visually |
| pySim integration unaffected | None | N/A | pySim calls are in managers layer — zero UI coupling |

---

## 9. What Gets Better Immediately

1. **No more `after(0, ...)` hacks** — Qt signals are inherently thread-safe
2. **No more `TclError` crashes** — Qt widgets don't throw on empty values
3. **All text is copyable by default** — `QLabel` supports text selection via flag
4. **Better table support** — `QTableView` for batch/CSV viewing
5. **Native file dialogs** — `QFileDialog` looks native on every platform
6. **Stylesheet theming** — CSS-like syntax, much easier than `ttk.Style`
7. **`QThread` + `Worker` pattern** — cleaner than raw `threading.Thread`

---

## 10. Recommended Approach

**Parallel development:** Keep current tkinter version working (`main.py`)
while building PyQt6 version (`qt_main.py`). Both share the same managers
layer. When PyQt6 version passes all tests, delete tkinter files.

**Phase 0 first, then decide:** Phase 0 is low-risk and low-cost. After
completing it, the StateManager exists and can be unit-tested. This proves
the architecture before committing to the full rewrite.

**One phase per PR/push:** Each phase results in a green test suite and a
pushable version. No "big bang" migration.

---

## 11. File Migration Checklist

### Phase 0 — Foundation
- [ ] `state_manager.py` (NEW)
- [ ] `qt_theme.py` (NEW)
- [ ] `qt_main.py` (NEW — entry point)
- [ ] `requirements.txt` update
- [ ] `tests/test_state_manager.py` (NEW)

### Phase 1 — Small Widgets
- [ ] `widgets/tooltip.py` → `qt_widgets/tooltip.py`
- [ ] `widgets/toast.py` → `qt_widgets/toast.py`
- [ ] `widgets/info_dialog.py` → `qt_dialogs/info_dialog.py`
- [ ] `widgets/card_status_panel.py` → `qt_widgets/card_status_panel.py`
- [ ] `widgets/progress_panel.py` → `qt_widgets/progress_panel.py`
- [ ] `widgets/csv_editor_panel.py` → `qt_widgets/csv_editor_panel.py`
- [ ] `dialogs/adm1_dialog.py` → `qt_dialogs/adm1_dialog.py`
- [ ] `dialogs/simulator_settings_dialog.py` → `qt_dialogs/simulator_settings_dialog.py`
- [ ] `dialogs/artifact_export_dialog.py` → `qt_dialogs/artifact_export_dialog.py`
- [ ] `dialogs/load_card_file_dialog.py` → `qt_dialogs/load_card_file_dialog.py`

### Phase 2 — Complex Widgets
- [ ] `widgets/read_sim_panel.py` → `qt_widgets/read_sim_panel.py`
- [ ] `widgets/program_sim_panel.py` → `qt_widgets/program_sim_panel.py`
- [ ] `widgets/batch_program_panel.py` → `qt_widgets/batch_program_panel.py`

### Phase 3 — MainWindow
- [ ] `main.py` → `qt_main.py` (expand from Phase 0 stub)
- [ ] `theme.py` → delete (replaced by `qt_theme.py`)

### Phase 4 — Network Dialog + Cleanup
- [ ] `dialogs/network_storage_dialog.py` → `qt_dialogs/network_storage_dialog.py`
- [ ] Remove `widgets/`, `dialogs/` (old tkinter dirs)
- [ ] Rename `qt_widgets/` → `widgets/`, `qt_dialogs/` → `dialogs/`
- [ ] Update all imports
- [ ] Final `install.sh` update (remove python3-tk, add PyQt6)

---

## 12. Decision Points for Project Owner

1. **GPL v3 license** — PyQt6 is GPL. Is that acceptable? (Alternative: PySide6 is LGPL, identical API)
2. **Phase 0 approval** — Proceed with StateManager + scaffolding?
3. **Directory strategy** — `qt_widgets/` parallel dirs during migration, or in-place replacement?
4. **Minimum Python version** — PyQt6 requires 3.9+. Currently supporting?
