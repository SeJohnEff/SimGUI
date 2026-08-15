# Explanation: Architecture overview

SimGUI is structured as a thin GUI layer over a set of independent manager components. The managers handle all business logic; the widgets handle display and user input. Neither layer imports the other's concerns, and the CLI card tools sit completely outside the Python process.

---

## High-level structure

```
┌─────────────────────────────────────────────────────────┐
│  SimGUI process                                         │
│                                                         │
│  ┌─────────────────────┐  ┌─────────────────────────┐  │
│  │   Widgets (UI)      │  │   Managers (logic)      │  │
│  │                     │  │                         │  │
│  │  BatchProgramPanel  │  │  CardManager            │  │
│  │  ReadSimPanel       │  │  BatchManager           │  │
│  │  CSVEditorPanel     │  │  CSVManager             │  │
│  │  CardStatusPanel    │  │  StandardsManager       │  │
│  │  ProgressPanel      │  │  NetworkStorageManager  │  │
│  │                     │  │  AutoArtifactManager    │  │
│  │  Dialogs:           │  │  CardWatcher            │  │
│  │  ADM1Dialog         │  │  IccidIndex             │  │
│  │  ArtifactExport     │  │  SettingsManager        │  │
│  │  NetworkStorage     │  │  BackupManager          │  │
│  │                     │  │  StateManager           │  │
│  └──────────▲──────────┘  └────────────┬────────────┘  │
│             │ signals                  │               │
│  ┌──────────┴──────────────────────────┴────────────┐  │
│  │  StateManager (QObject) — signal hub             │  │
│  │  Widgets subscribe to signals, never import      │  │
│  │  each other. Only MainWindow writes state.       │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────┬───────────────────────┘
                                  │ subprocess
               ┌──────────────────▼──────────────────┐
               │  External CLI (separate process)    │
               │                                     │
               │  pySim (primary):                   │
               │    pySim-read.py                    │
               │    pySim-shell.py                   │
               │    pySim-prog.py                    │
               │                                     │
               │  sysmo-usim-tool (optional):        │
               │    sysmo_isim_sja2.py               │
               │    sysmo_isim_sja5.py               │
               │    sysmo_isim_sjs1.py               │
               └─────────────────────────────────────┘
```

---

## The subprocess boundary

The most important architectural decision in SimGUI is that **card tools are never imported as Python modules**. `CardManager` calls them via `subprocess.run()`, capturing stdout and stderr.

This choice was made deliberately:

1. **Independence:** sysmo-usim-tool and pySim have their own release cycles, dependencies, and Python version requirements. Importing them would create tight coupling. Shelling out keeps SimGUI independent.
2. **Safety:** A crashing CLI tool does not crash the GUI process. SimGUI catches timeouts and exceptions from subprocess invocations and surfaces them as error messages.
3. **Versioning:** Users can update the CLI tools without reinstalling SimGUI, and vice versa.

See [CLI integration](../reference/cli-integration.md) for the full subprocess call design.

---

## Manager components

### CardManager

The central card interface. Manages:
- CLI backend auto-detection (pySim at `/opt/pysim` is primary; sysmo-usim-tool is optional fallback)
- Card detection and type identification (SJA2, SJA5, GIALERSIM, MAGIC via pySim-read)
- ADM1 authentication (skipped for blank/gialersim cards to avoid CHV 0x0C failures)
- Programming, routed by **card type** in `program_card()`:
  - **gialersim → native** (`managers/gialersim.py`, pyscard directly, no pySim)
  - **non-gialersim empty/blank → pySim-prog** (full write)
  - **non-empty (SJA5/SJA2) → pySim-shell** (delta-write)
- ICCID cross-verification before every authentication

> **Why gialersim bypasses the subprocess boundary.** Every other flow shells
> out to a CLI tool (see below). gialersim is the one exception: pySim's
> `GialerSim` class writes Ki/OPc in the wrong (UICC) class and omits the
> algorithm configuration, so its writes return `9000` but never commit — a
> silent, card-bricking failure. The correct GSM-class sequence is small,
> verified, and security-critical, so it lives in-process in
> `managers/gialersim.py` (a framework-free module using pyscard, like the ADM1
> retry-counter probe already does). This is a card-type branch, not a platform
> branch — sysmocom cards are untouched and still use pySim. See
> [GIALERSIM_PROGRAMMING.md](../GIALERSIM_PROGRAMMING.md).

A single `CardManager` instance is created in `main.py` and passed to every component that needs card access.

### CSVManager

Purely data-handling; no card or UI dependencies. Manages:
- Loading CSV, TXT (whitespace-delimited), and EML files
- Column name normalisation (`ADM` → `ADM1`, etc.)
- Row-level validation via `utils/validation.py`
- Save to CSV

### StandardsManager

Loads and caches `standards.json` from network share mount points. Provides:
- `spn_values` and `li_values` lists for UI dropdowns
- Case-exact and case-insensitive lookup/suggestion
- Merging from multiple shares

### NetworkStorageManager

Manages share mount points — both discovery and connection. Provides:
- `get_active_mount_paths()` → list of `(label, path)` for all mounted shares
- mDNS and NetBIOS discovery of SMB servers on the LAN

### AutoArtifactManager

Writes per-card programming records to network shares. After each `program_card()` with outcome `ProgramOutcome.WRITE_OK_VERIFIED` (clean success with full verification):
- Builds a CSV row from the card data (ICCID, IMSI, Ki, OPc, ADM1, ACC, SPN, FPLMN, PIN/PUK, timestamp)
- Writes `{ICCID}_{YYYYMMDD_HHMMSS}.csv` to `auto-artifact/` on every connected share
- `was_already_programmed(iccid)` checks for existing artifacts (duplicate detection)

No artifacts are produced for `WRITE_OK_PENDING`, `WRITE_OK_VERIFICATION_FAILED`, `WRITE_FAILED`, or any other non-verified outcome.

### CardWatcher

A background daemon thread that polls the card reader every 1.5 seconds:

```
poll loop:
    detect_card()
    if ok and iccid changed:
        lookup(iccid) in IccidIndex
        if found: on_card_detected(iccid, card_data, file_path)
        else: on_card_unknown(iccid)
    if not ok and was_ok:
        on_card_removed()
```

CardWatcher eliminates the "Detect Card" button. The UI reacts to events rather than polling. During programming, the watcher is paused to avoid interfering with ongoing card operations.

**Thread safety:** All callbacks are invoked on the watcher thread. Qt signals auto-marshal to the UI thread, so widgets react safely without manual dispatching.

### IccidIndex

An in-memory index built from all loaded CSV files. Maps ICCID → (file path, row data). Used by CardWatcher to resolve a detected ICCID to its full card profile without re-reading the file.

### BatchManager

Orchestrates multi-card programming sessions:
- Iterates through the card list
- Waits for card insertion events from CardWatcher
- Calls CardManager authenticate → program_card → AutoArtifactManager for each card
- Emits progress callbacks (`on_progress`, `on_card_result`, `on_waiting_for_card`, `on_completed`)
- Runs on a background thread to keep the UI responsive

### SettingsManager

Persists user preferences to `~/.config/simgui/settings.json`. Simple JSON read/write with defaults. Used to restore the last-used MCC/MNC, SPN, CSV path, window geometry, etc.

---

## Signal-based architecture (StateManager)

SimGUI uses a signal-based architecture for cross-component communication. `StateManager` (a `QObject`) owns all mutable UI state and emits Qt signals when state changes.

**Key signals:**
- `card_state_changed(CardState)` — NO_CARD → DETECTED → AUTHENTICATED
- `card_info_changed(CardInfo)` — ICCID, IMSI, card_type, etc.
- `csv_path_changed(str)` — active CSV file
- `batch_running_changed(bool)` — batch lock
- `card_programmed(dict)` — triggers auto-artifact

**Pattern:** Manager does work → MainWindow updates StateManager → Signal fires → Widgets react. Widgets NEVER call managers directly. They read StateManager properties and react to signals. Widgets never import each other — they subscribe to StateManager signals.

Only `MainWindow` (the controller) writes to StateManager. This ensures a single point of state mutation and prevents tangled dependencies between UI components.

---

## Programming result contract (CardManager.program_card)

`CardManager.program_card()` returns a 3-tuple:

```python
(ok: bool, msg: str, result: ProgramResult) = cm.program_card(card_data)
```

The **`ProgramResult` object is the canonical source of truth** for programming outcomes. Do not infer state from the message text or the `ok` boolean.

**Key rules:**

1. **`ok` boolean** — High-level success flag (`True` = write phase completed without CLI error; `False` = write or ADM1 failure). Do not use this to determine artifact eligibility or clean success.

2. **`msg` string** — Human-readable status message for UI display. Do **not** parse this string to infer state (e.g., checking for "verified", "written", "pending"). Use only for display.

3. **`result.outcome`** — `ProgramOutcome` enum (IDLE, NO_CHANGES, ICCID_MISMATCH, ADM1_LOCKED, ADM1_AUTH_FAILED, WRITE_FAILED, WRITE_OK_VERIFIED, WRITE_OK_PENDING, WRITE_OK_VERIFICATION_FAILED). This is the **authoritative result state**.

**Artifact eligibility:**

Only `ProgramOutcome.WRITE_OK_VERIFIED` is eligible for artifact generation. `WRITE_OK_PENDING` (incomplete verification) and all failure outcomes produce no artifacts.

**StateManager emission:**

- `program_result_changed` signal emits the `ProgramResult` for all outcomes
- `card_programmed` signal emits only when outcome is `WRITE_OK_VERIFIED`

See `docs/reference/state-machine.md` (ProgramOutcome section) for the full outcome glossary.

---

## Async patterns (QThread workers)

Long-running tasks (e.g., network share reconnect, ICCID index scanning) must not block the event loop. SimGUI uses `QThread` workers for any blocking I/O or CPU work:

**Worker pattern:**

1. Create a `QObject` subclass (e.g., `BackgroundStartupWorker`) that emits signals for each result
2. Worker does all blocking work in a `run()` method, emitting signals when done
3. Create a `QThread`, move the worker to it, and connect thread lifecycle signals
4. Connect worker signals to main window slots (`_on_worker_*`)
5. Slots update `StateManager` via normal methods (never direct state mutation)

**Example (v0.5.38):**
- `BackgroundStartupWorker.run()` does blocking I/O (network share reconnect, dir scan)
- Emits: `toast_requested`, `status_requested`, `mounts_updated`, `index_updated`
- `_on_worker_*` slots update `StateManager` or call its methods
- No lambdas with `setattr()` or direct state manipulation — all updates go through proper slots

**Benefits:**
- Event loop never blocks (UI stays responsive)
- No threading race conditions (Qt handles thread-safe signal dispatch)
- Clean separation: worker emits signals, slots react
- Easy to test: disconnect signals, verify emissions; separately verify slot behavior

---

## Auto-artifact storage

Each successful programming event writes one file. This design choice — one file per card rather than one log file per session — was deliberate:

1. **Idempotent writes:** Two programming events for the same ICCID produce two timestamped files. Neither overwrites the other. The full history is preserved.
2. **Easy querying:** `ls auto-artifact/ | grep 8988211812345678901` returns all records for a card.
3. **No transaction risk:** If the system crashes mid-session, partial sessions don't corrupt a master log.
4. **Duplicate detection:** `was_already_programmed(iccid)` checks for any file with the ICCID prefix, alerting operators to re-programming of a card.

---

## Entry point and wiring

`main.py` is the application entry point. It:
1. Creates all managers (CardManager, CSVManager, StandardsManager, etc.)
2. Creates the `StateManager` and wires it to `MainWindow`
3. Instantiates the main window and all tab panels
4. Passes manager instances to panels that need them
5. Starts CardWatcher
6. Runs the PyQt6 event loop

There is no dependency injection framework — wiring is explicit in `main.py`. This keeps the code easy to follow for a desktop application of this size.
