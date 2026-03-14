# Auto-Read Flow — Design Document v2

## Overview

When a SIM card is inserted, SimGUI automatically reads the ICCID (no
authentication required), looks it up in a lightweight index, and loads
the full profile on demand from the source file.  The index stores only
ICCID ranges — not full profiles — so 10,000+ cards cost just a few KB.

---

## Current Flow (today) — 7 operator actions

```
Operator                           SimGUI
   ├── Opens file browser ──────────► │
   ├── Navigates to SMB share ──────► │
   ├── Selects .eml / .csv file ────► │  ← loads & parses file
   ├── Selects row in table ────────► │  ← populates fields
   ├── Inserts SIM card ──────────► │
   ├── Clicks "Detect Card" ────────► │  ← reads ICCID
   ├── Clicks "Authenticate" ──────► │  ← ADM1 dialog
   ├── Edits IMSI / FPLMN ────────► │
   └── Clicks "Program" ──────────► │
```

## Proposed Flow (auto-read) — 1–3 operator actions

```
Operator                           SimGUI
   │  ┌─ on SMB connect ───────────► │  ← quick-scans files, builds
   │  │                               │    range index (lightweight)
   │                                  │
   ├── Inserts SIM card ──────────► │  ← auto-detect, read ICCID
   │                                  │  ← range lookup → find file
   │                                  │  ← lazy-load ONLY that card
   │                                  │  ← pre-fill all fields
   │                                  │
   ├── [optional] Adjusts IMSI ────► │
   ├── [optional] Adjusts FPLMN ───► │
   └── Clicks "Program" ──────────► │  ← ADM1 from file data
```

---

## Index Architecture — Range-Based

### The key insight

Sysmocom delivers SIMs in sequential batches.  A file with 500 cards
has ICCIDs that share a common prefix with only the last digits varying:

```
File: batch_se2_2026Q1.eml (500 cards)
  ICCIDs: 8949440000001672607
          8949440000001672615
          ...
          8949440000001672797

  → prefix:  894944000000167
  → range:   2607 .. 2797
  → 1 index entry instead of 500
```

### Index structure

```python
@dataclass
class IndexEntry:
    """One contiguous ICCID range within a single file."""
    file_path: str          # source .eml or .csv on SMB share
    prefix: str             # common ICCID prefix (e.g. "894944000000167")
    range_start: int        # first suffix as integer (e.g. 2607)
    range_end: int          # last suffix as integer  (e.g. 2797)
    suffix_len: int         # number of digits in suffix (e.g. 4)
    card_count: int         # cards in this range
    iccid_length: int       # 19 (SUCI) or 23 (non-SUCI)
```

### Memory footprint

| Cards | Files (500/file) | Index entries | RAM |
|-------|-------------------|---------------|-----|
| 500 | 1 | 1 | ~200 bytes |
| 5,000 | 10 | ~10 | ~2 KB |
| 10,000 | 20 | ~20 | ~4 KB |
| 100,000 | 200 | ~200 | ~40 KB |

Even at 100,000 cards the index is negligible.  Full card profiles
(Ki, OPc, ADM1, etc.) are never stored in RAM until needed.

### Scanning — fast header-only parse

During index build, we do NOT parse every card's full data.  Instead:

1. Open file
2. Find field headers (reuse existing `_find_all_field_headers`)
3. Locate the ICCID column position
4. Read only the ICCID values (skip Ki, OPc, ADM1, etc.)
5. Detect prefix + range
6. Store one `IndexEntry`

For a 500-card .eml file, this reads ~500 short lines instead of
~10,000 lines of crypto keys.  The file `mtime` is cached so
unchanged files are skipped on re-scan.

### Lookup — O(n) on entries, not cards

```python
def lookup(self, iccid: str) -> IndexEntry | None:
    """Find which file contains this ICCID.

    For each index entry, check if:
      1. iccid starts with entry.prefix
      2. suffix (remaining digits) falls within range_start..range_end

    With ~20 entries for 10,000 cards this is instant.
    """
```

### On-demand card load

Once lookup finds the file, we parse ONLY that file (using the existing
`eml_parser` or `CSVManager`) and find the exact row by ICCID.  This
result is cached in a small LRU so repeated lookups are free.

```python
class IccidIndex:
    def __init__(self):
        self._entries: list[IndexEntry] = []
        self._file_mtimes: dict[str, float] = {}
        self._card_cache: OrderedDict[str, dict] = OrderedDict()  # LRU, max ~50

    def scan_directory(self, directory: str) -> ScanResult:
        """Quick-scan all .eml/.csv files.  Build range entries."""

    def lookup(self, iccid: str) -> IndexEntry | None:
        """Find the index entry containing this ICCID."""

    def load_card(self, iccid: str) -> dict[str, str] | None:
        """Lookup + parse source file + return full card profile.
        Caches the parsed file briefly for consecutive lookups."""

    def rescan_if_stale(self, directory: str, max_age_s: float = 30.0):
        """Re-scan only files whose mtime changed."""

    @property
    def stats(self) -> dict:
        """Returns {files, entries, total_cards, ram_bytes}."""
```

### Handling non-contiguous ICCIDs

If a file contains ICCIDs that aren't a single contiguous range
(e.g. two batches in one email, or gaps), the scanner creates
multiple `IndexEntry` objects for that file — one per contiguous run.
Still far fewer entries than individual ICCIDs.

### Handling Luhn check digits

Sysmocom ICCIDs include a Luhn check digit as the last character.
The "sequential" part is the digits before the check digit.  The
range detection strips the Luhn digit, finds the sequential range
on the remaining digits, and lookup does the same strip before
range comparison.

```
ICCID:           8949440000001672706
                 ├─ prefix ──────┤├┤├─ Luhn
                 894944000000167  270  6

Stored as:  prefix="894944000000167", range 260..279, suffix_len=3
Lookup:     strip Luhn → "894944000000167270" → prefix match → suffix 270 in range
```

---

## Card Watcher

Same as v1 — background thread polling every 1.5s.  No changes to this
component.  Uses existing `CardManager.detect_card()` + `read_iccid()`.

```
every 1.5s:
    detect_card()
    if card present:
        iccid = read_iccid()
        if iccid != last_iccid:       # new card
            entry = index.lookup(iccid)
            if entry:
                profile = index.load_card(iccid)
                emit on_card_matched(iccid, profile, entry.file_path)
            else:
                emit on_card_unknown(iccid)
            last_iccid = iccid
    else:
        if last_iccid:                 # card removed
            emit on_card_removed()
            last_iccid = None
```

---

## UI Integration

### Card Status Panel

| State | Indicator | Message |
|-------|-----------|---------|
| Auto-read waiting | Blue pulsing dot | "Auto-read: waiting for card..." |
| Card matched | Green dot | "Matched — batch_se2_2026Q1.eml (card 47/500)" |
| Card not found | Amber dot | "ICCID 8946... not in index (1,247 cards indexed)" |
| Card removed | Blue pulsing dot | Returns to waiting state |

### Program SIM Panel

- New data source: **"Auto (from reader)"** radio button
- On match: all fields populate, IMSI + FPLMN highlighted as editable
- Source file shown: "Loaded from: batch_se2_2026Q1.eml"
- ICCID: read-only (as always)
- ADM1: from file data, used automatically on Program click

### Toolbar

- **Auto-Read** toggle (checkbox in Card menu or toolbar)
- Index status in status bar: "Index: 1,247 cards in 3 files"

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| **ICCID not in index** | Amber warning. Operator can load file manually. No auth attempted. |
| **Duplicate ICCID across files** | Log warning during scan. Keep first occurrence. Show warning on lookup. |
| **Card removed mid-program** | program_card() returns error. Watcher resets to waiting. |
| **SMB disconnected** | Index stays valid. Status shows "stale". Re-scan on reconnect. |
| **New files on SMB** | Periodic rescan (30s) or manual refresh. "+24 cards indexed" notification. |
| **Mixed ICCID lengths** | 19-digit (SUCI) and 23-digit (non-SUCI) handled as separate entries with different prefix/suffix splits. |
| **Non-sequential ICCIDs** | Multiple index entries per file. Falls back gracefully. |
| **Simulator mode** | CardWatcher pauses. Index still usable for CSV-loaded simulator data. |

---

## Data Flow

```
SMB Share                     IccidIndex                  CardWatcher          UI
┌──────────┐   quick-scan    ┌────────────────┐                              
│ .eml     │ ──────────────► │ Range entries:  │                              
│ .csv     │   (ICCIDs only) │  prefix+range   │                              
│ files    │                 │  → file path    │                              
└──────────┘                 └───────┬────────┘                              
                                     │                                        
                              lookup │         ┌──────────────┐              
                                     │◄────────│ poll reader  │◄── card insert
                                     │         │ read ICCID   │              
                                     │         └──────┬───────┘              
                              match? │                │                      
                                     ▼                │                      
                             ┌───────────────┐        │    ┌──────────────┐  
                             │ parse ONLY    │        │    │ Program SIM  │  
                             │ matched file  │────────┼───►│ Panel        │  
                             │ find card row │        │    │ (pre-filled) │  
                             └───────────────┘        │    └──────────────┘  
                                                      │                      
                                                      │    ┌──────────────┐  
                                                      └───►│ Card Status  │  
                                                           │ (green/amber)│  
                                                           └──────────────┘  
```

---

## Implementation Phases

| Phase | What | Effort |
|---|---|---|
| **1** | `IccidIndex` with range detection, scan, lookup, load_card + tests | 1 day |
| **2** | `CardWatcher` polling thread + tests | 0.5 day |
| **3** | Wire into UI: auto-populate, toggle, status bar | 1 day |
| **4** | SMB auto-scan on mount, periodic rescan, stale detection | 0.5 day |
| **5** | Polish: LRU cache tuning, batch-mode integration, settings | 0.5 day |

---

## Files to Create/Modify

**New files:**
- `managers/iccid_index.py` — range-based index
- `managers/card_watcher.py` — polling thread
- `tests/test_iccid_index.py`
- `tests/test_card_watcher.py`

**Modified files:**
- `main.py` — wire watcher + index, add Auto-Read toggle
- `widgets/program_sim_panel.py` — add "Auto" source, accept pre-fill
- `widgets/card_status_panel.py` — add "auto" indicator states
- `managers/settings_manager.py` — persist auto-read + index prefs
- `managers/network_storage_manager.py` — trigger index scan on mount
