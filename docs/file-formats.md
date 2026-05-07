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

Field names are case-sensitive. Use exactly:
- `ADM1` not `ADM`
- `OPc` not `OPC` or `opc`
- `Ki` not `KI` or `ki`
- `ICCID`, `IMSI`, `ACC`, `SPN`, `FPLMN` in uppercase

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

## Known Parser Limitations (as of SimGUI 0.5.26)

### Delimiter auto-detection
- `.csv` files are assumed to be comma-delimited. Files using semicolon or other
  delimiters will parse silently with wrong column alignment.
- `.txt` files are assumed to be tab-delimited. Comma-delimited `.txt` files will
  parse silently with wrong column alignment.
- **Workaround:** Convert files to comma-delimited `.csv` before use.

### Field name case sensitivity
- Field names are case-sensitive. `ADM` instead of `ADM1`, `OPC` instead of `OPc`,
  or `KI` instead of `Ki` will cause fields to be silently missing.
- **Workaround:** Rename columns to match SimGUI standard before use.

### Missing required fields
- If a file is missing required fields (e.g. `OPc`, `ADM1`), SimGUI will find the
  card by ICCID but silently fail to populate programming data. The UI shows
  "ICCID not found" or empty fields with no explanation.
- **Workaround:** Ensure all required columns are present.

### No user-visible parse errors
- File parse failures are logged to the terminal only (`logger.warning`). No
  error is shown in the UI.
- **Workaround:** Run SimGUI from terminal to see parse warnings.

### Planned improvements
- Auto-detect delimiter (comma, tab, semicolon)
- Validate required fields after parsing and surface errors in UI
- Case-insensitive field name matching
- Clear error message when card is found but programming data is incomplete