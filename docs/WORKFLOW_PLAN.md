# SimGUI — Workflow Plan v0.5.2

This document defines the four SIM card programming workflows and the
expected software behaviour at each step.  All bug fixes must be
validated against these workflows.

---

## State Machine

Every card in the Program SIM panel moves through:

```
STEP 0  → "Insert a SIM card…"       (no card, buttons disabled)
STEP 1  → "Card detected"            (Authenticate enabled)
STEP 2  → "Authenticated"            (Program Card enabled)
STEP 3  → "Programmed"               (done)
```

Card removal at any point → back to STEP 0 + clear all fields.

---

## Workflow 1 — Single Non-Empty Card (factory ICCID)

**Preconditions**: Network share mounted OR data file available locally.

| # | User action | Software behaviour |
|---|-------------|--------------------|
| 1 | (optional) Mount network share | Share icon turns green, ICCID index scanned |
| 2 | Insert non-empty card | CardWatcher reads ICCID → IccidIndex lookup |
| 2a| — Card IS in index | `on_card_detected(iccid, card_data, file_path)` → all fields populated, ICCID read-only, STEP 1 |
| 2b| — Card NOT in index | `on_card_unknown(iccid)` → ICCID field set, rest blank, "not in index" warning, file-picker dialog opens, STEP 1 |
| 3 | Click Authenticate | ADM1 verified with card. STEP 2 on success |
| 4 | Click Program Card | pySim writes changed fields. Auto-artifact saved. STEP 3 |
| 5 | Remove card | Clear all, STEP 0, ready for next |

**Key invariant**: ICCID is ALWAYS read-only for non-empty cards.

---

## Workflow 2 — Single Empty (Blank) Card from CSV

**Preconditions**: CSV/EML file with card data available.

| # | User action | Software behaviour |
|---|-------------|--------------------|
| 1 | Switch to "From CSV" mode | CSV pane visible |
| 2 | Browse and load CSV/EML file | Tree populated with rows. Fields still empty. STEP 0 |
| 3 | Select a CSV row | Form fields populated from that row (ICCID editable for blank cards) |
| 4 | Insert blank card | CardWatcher fires `on_card_unknown("")` |
|   | **CRITICAL**: Software detects fields are already populated from CSV → does NOT overwrite them. Moves to STEP 1. Status: "Blank card detected — ready to authenticate" |
| 5 | Click Authenticate | ADM1 verified. STEP 2 |
| 6 | Click Program Card | All fields written (including ICCID from CSV). Auto-artifact saved. STEP 3 |
| 7 | Remove card | Clear all, STEP 0 |
| 8 | Select next CSV row, insert next blank card | Repeat from step 3 |

**Key invariant**: Card detection MUST NOT overwrite CSV-populated fields.

**ALTERNATE ORDER** (insert card first, then select CSV row):

| # | User action | Software behaviour |
|---|-------------|--------------------|
| 1 | Load CSV file | Tree populated |
| 2 | Insert blank card | `on_card_unknown("")` → STEP 1, fields empty, status shows "Blank card — select a CSV row or enter data manually" |
| 3 | Select CSV row | Fields populated. Step stays at 1 (card present). Auth button enabled |
| 4 | Authenticate → Program | As above |

**Key invariant**: Order of CSV-select vs card-insert doesn't matter.

---

## Workflow 3 — Batch Non-Empty Cards

**Preconditions**: Network share or directory with data files scanned into ICCID index.

| # | User action | Software behaviour |
|---|-------------|--------------------|
| 1 | Mount share, scan directory | ICCID index populated |
| 2 | Switch to Batch tab | Batch settings visible |
| 3 | Insert non-empty card | Auto-detected, matched by ICCID, auto-authenticated, auto-programmed |
| 4 | Remove card, insert next | Repeat. Progress tracked per card |

---

## Workflow 4 — Batch Empty Cards from CSV

| # | User action | Software behaviour |
|---|-------------|--------------------|
| 1 | Load CSV file in batch panel | Rows loaded |
| 2 | Insert blank card | Auto-matched to next unprocessed CSV row by sequence |
| 3 | Auto-authenticate, auto-program | ICCID + all fields written from CSV row |
| 4 | Remove card, insert next | Next CSV row used. Repeat |

---

## Bug Analysis (v0.5.2)

### Bug 1: Blank card overwrites CSV data

**Symptom**: User loads CSV, selects row (fields populate), inserts blank
card → `on_card_detected("")` clears all fields and shows "not in index".

**Root cause**: `on_card_detected(iccid="")` in `program_sim_panel.py` line
370-377 ALWAYS overwrites fields when `card_data` is None.  It doesn't
check whether fields were already populated by CSV selection.

**Fix**: In `on_card_detected()`, when `iccid` is empty (blank card) AND
fields are already populated (CSV data), preserve the existing field
values.  Only set ICCID and show "not in index" when fields are actually
empty.  The key signal is: if `_mode_var == "csv"` and fields have
values, the user pre-loaded data — honour it.

Additionally, in `_on_auto_card_unknown` in `main.py` line 628, the call
`self._program_panel.on_card_detected(iccid)` passes no `card_data`,
which triggers the "no data" branch.  We need a new method or parameter
to handle blank-card-with-preloaded-data differently.

### Bug 2: Action status text not selectable

**Symptom**: The "not in index, enter data manually" message (and all
other action status messages) cannot be selected or copied.

**Root cause**: `self._action_status = ttk.Label(act, ...)` (line 136).
tkinter Labels are not selectable.

**Fix**: Replace the `ttk.Label` with a `tk.Text` widget configured as
read-only (state=DISABLED), matching the pattern in `info_dialog.py`.
The Text widget must:
- Be read-only but selectable
- Auto-size to single line height
- Support style changes (Success/Warning/Error colours)
- Right-click copy support

### Bug 3: Share icon shows disconnected after file browse

**Symptom**: Share was connected, user uses Browse button in Program SIM
panel, share icon flips to disconnected.

**Root cause**: `_refresh_share_indicator()` is only called at:
- Startup (line 158)
- After LoadCardFileDialog closes (line 657)
- After NetworkStorageDialog closes (line 940)

It is NOT called after the Program SIM panel's own Browse button
(`_on_browse_csv` in program_sim_panel.py line 253).  The Browse button
uses `filedialog.askopenfilename()` which is a system file dialog.

However, the actual issue is likely that the `is_mounted()` check uses
`os.path.ismount()`, and on some systems, opening a file dialog that
navigates into the CIFS/NFS mount point can cause a stale check.

More likely: the indicator was never refreshed after the initial auto-
reconnect.  If auto-reconnect didn't fully mount, the icon stays grey.
The user sees the CSV file from the share, assumes share is connected,
but the `_active_mounts` dict or the `os.path.ismount()` check says
otherwise.

**Fix**: Call `_refresh_share_indicator()` periodically or at key
state transitions:
1. After any file browse dialog closes
2. After any CSV file is loaded (the file path reveals the share)
3. Add a periodic refresh (every 30 seconds) to catch external
   mount/unmount events

---

## Implementation Order

1. Bug 2 (simplest, isolated change to UI widget)
2. Bug 1 (core workflow fix, needs careful state management)
3. Bug 3 (indicator refresh, needs hook points)
4. Tests for all three
5. Version bump → v0.5.2
