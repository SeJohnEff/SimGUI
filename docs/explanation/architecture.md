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
│  │  BatchProgramPanel  │◄─┤  CardManager            │  │
│  │  ReadSimPanel       │  │  BatchManager           │  │
│  │  CSVEditorPanel     │  │  CSVManager             │  │
│  │  CardStatusPanel    │  │  StandardsManager       │  │
│  │  ProgressPanel      │  │  NetworkStorageManager  │  │
│  │                     │  │  AutoArtifactManager    │  │
│  │  Dialogs:           │  │  CardWatcher            │  │
│  │  ADM1Dialog         │  │  IccidIndex             │  │
│  │  ArtifactExport     │  │  SettingsManager        │  │
│  │  NetworkStorage     │  │  BackupManager          │  │
│  │  SimulatorSettings  │  │  BatchManager           │  │
│  └─────────────────────┘  └────────────┬────────────┘  │
│                                        │               │
│                           ┌────────────▼────────────┐  │
│                           │  SimulatorBackend (opt) │  │
│                           │  virtual_card.py        │  │
│                           │  card_deck.py           │  │
│                           └─────────────────────────┘  │
└─────────────────────────────────┬───────────────────────┘
                                  │ subprocess
               ┌──────────────────▼──────────────────┐
               │  External CLI (separate process)    │
               │                                     │
               │  sysmo-usim-tool:                   │
               │    sysmo_isim_sja2.py               │
               │    sysmo_isim_sja5.py               │
               │    sysmo_isim_sjs1.py               │
               │                                     │
               │  pySim:                             │
               │    pySim-read.py                    │
               │    pySim-prog.py                    │
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
- CLI backend auto-detection (`SYSMO_USIM_TOOL_PATH`, `PYSIM_PATH`, fallback paths)
- Card detection, ICCID reading, ADM1 authentication
- ICCID cross-verification before every authentication
- Simulator delegation (when `_simulator` is set, all operations route there)

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

Writes per-card programming records to network shares. After each successful `program_card()` in a batch:
- Builds a CSV row from the card data (ICCID, IMSI, Ki, OPc, ADM1, ACC, SPN, FPLMN, PIN/PUK, timestamp)
- Writes `{ICCID}_{YYYYMMDD_HHMMSS}.csv` to `auto-artifact/` on every connected share
- `was_already_programmed(iccid)` checks for existing artifacts (duplicate detection)

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

**Thread safety:** All callbacks are invoked on the watcher thread. The UI must dispatch to the main thread via `root.after(0, ...)` (Tkinter's thread-safe scheduling mechanism).

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

## The simulator backend

The simulator provides a complete card-operations API without requiring hardware. It is activated by setting `CardManager._simulator` to a `SimulatorBackend` instance.

`SimulatorBackend` holds a `card_deck` — a list of 20 `VirtualCard` objects pre-populated with real sysmoISIM-SJA5 profiles. Each virtual card:

- Has a unique ICCID and IMSI
- Tracks authentication state
- Tracks remaining ADM1 attempts (starts at 3)
- Can be programmed (fields updated in memory)
- Can be verified (programmed fields compared to expected)

`CardManager.next_virtual_card()` / `previous_virtual_card()` advance through the deck, simulating card insertions and removals. CardWatcher detects virtual card changes the same way it detects physical ones.

The simulator is intentionally opaque to the rest of the system — `BatchProgramPanel`, `AutoArtifactManager`, and all other components interact with `CardManager`'s public API and cannot tell whether the backend is hardware or simulator.

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
2. Instantiates the main window and all tab panels
3. Passes manager instances to panels that need them
4. Starts CardWatcher
5. Runs the Tkinter event loop

There is no dependency injection framework — wiring is explicit in `main.py`. This keeps the code easy to follow for a desktop application of this size.
