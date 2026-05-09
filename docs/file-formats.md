# SimGUI File Formats

## Overview

SimGUI accepts two types of SIM data files:

1. **Programming files** — used to program physical SIM cards
2. **Provisioning files** — used for core network subscriber provisioning (read-only reference in SimGUI)

---

## Programming File (SimGUI Standard CSV)

Used by the ICCID index, batch programmer, and Program SIM tab.

### Format

- Encoding: UTF-8 (with or without BOM)
- Delimiter: comma (`,`)
- First row: header
- No quotes around values
- File extension: `.csv`

### Columns

| Column | Required | Description |
|--------|----------|-------------|
| `ICCID` | ✓ | 18–20 digit card identifier |
| `IMSI` | ✓ | 15 digit subscriber identity |
| `Ki` | ✓ | 32 hex char authentication key |
| `OPc` | ✓ | 32 hex char operator variant algorithm key |
| `ADM1` | ✓ | 16 hex char card administration key |
| `ACC` | ✓ | 4 hex char access control class |
| `PIN1` | | 4–8 digit PIN1 |
| `PUK1` | | 8 digit PUK1 |
| `PIN2` | | 4–8 digit PIN2 |
| `PUK2` | | 8 digit PUK2 |
| `SPN` | | Service Provider Name (max 16 chars) |
| `FPLMN` | | Semicolon-separated forbidden PLMNs e.g. `24001;24007` |

### Example

```csv
ICCID,IMSI,Ki,OPc,ADM1,ACC,PIN1,PUK1,PIN2,PUK2,SPN,FPLMN
8949440000001672706,999700000167270,E049AF7DBE25B0AECD0CE2FEE03FD919,9EB1A95173A8F40281EFBA24D4053A0E,76510072,0001,0000,88528379,0000,31497382,Teleaura UK,24001;24007
```

### Field naming

Column names are normalized case-insensitively on load:
- `ADM` or `adm` → `ADM1`
- `KI` or `ki` → `Ki`
- `OPC` or `opc` → `OPc`
- All others are uppercased (e.g. `imsi` → `IMSI`, `iccid` → `ICCID`)

---

## Provisioning File (Core Network CSV)

Minimal format for subscriber provisioning into Magma/orchestrator. SimGUI accepts this format for ICCID lookup and reference but cannot program cards from it (ADM1 and ACC are missing).

### Format

- Encoding: UTF-8
- Delimiter: comma (`,`)
- First row: header
- File extension: `.csv`

### Columns

| Column | Required | Description |
|--------|----------|-------------|
| `ICCID` | ✓ | 18–20 digit card identifier |
| `IMSI` | ✓ | 15 digit subscriber identity |
| `Ki` | ✓ | 32 hex char authentication key |
| `OPc` | ✓ | 32 hex char operator variant algorithm key |

### Example

```csv
ICCID,IMSI,Ki,OPc
8949440000001691029,999880005000013,2D321C5765F485AADA3C478E04427AC0,843BCF7F353FB9B5FB1503B0DC06E770
```

---

## Auto-Artifact CSV

Generated automatically by SimGUI after programming a card. Stored on the network share.

### Format

```csv
ICCID,IMSI,Ki,OPc,ADM1,ACC,SPN,FPLMN,PIN1,PUK1,PIN2,PUK2,programmed_at
```

This is a superset of the programming file with an additional `programmed_at` timestamp.

---

## Supported File Extensions

| Extension | Format | Notes |
|-----------|--------|-------|
| `.csv` | Comma-delimited | Standard SimGUI format |
| `.txt` | Tab-delimited | Legacy sysmocom format |
| `.eml` | Email | sysmocom order confirmation emails |

---

## Legacy Formats

### sysmocom TXT format (`.txt`)

Tab-delimited with header row. Column names may differ from SimGUI standard:
- `ADM` → SimGUI expects `ADM1`
- `KI` → SimGUI expects `Ki`
- `OPC` → SimGUI expects `OPc`
- May contain extra columns (`MSISDN`, `KIC1`-`KIK3`) which are ignored

### sysmocom EML format (`.eml`)

Parsed via `utils/eml_parser.py`. Field names are normalised during parsing.

---

## Parser behaviour (as of SimGUI 0.5.34)

### Delimiter auto-detection
The parser auto-detects the delimiter from the header line in priority order:
comma → tab → semicolon. If none of these appear, it falls back to
whitespace-delimited parsing. No file extension assumptions are made.

### Field name normalisation
Column names are normalised case-insensitively on load (see Field naming above).
No manual renaming is required.

### Missing required fields
If a file is missing required programming fields (`ICCID`, `Ki`, `OPc`, `ADM1`),
SimGUI shows a warning dialog on load listing the missing fields. The file still
loads (cards can be viewed) but programming will fail without those fields.
Additionally, a toast notification appears when a detected card's data file is
missing `Ki`, `OPc`, or `ADM1`.

### No user-visible parse errors
Fatal parse errors (unreadable file, corrupt content) are shown as an error
dialog. Soft issues (missing columns) appear as warning dialogs.