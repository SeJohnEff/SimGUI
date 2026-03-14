# Reference: CSV format

This document defines the CSV file format used by SimGUI for loading and saving SIM card programming data.

**Source of truth:** `managers/csv_manager.py` — `STANDARD_COLUMNS`, `_COLUMN_NORMALIZE`, and `validate_card_data()` in `utils/validation.py`.

---

## File format

SimGUI accepts two CSV dialects:

| Dialect | Description |
|---|---|
| Comma-separated (`.csv`) | Standard RFC 4180 CSV with header row |
| Whitespace-delimited (`.txt`) | Space- or tab-delimited with header row; auto-detected if comma parsing yields only one column |

Encoding: **UTF-8** (with optional BOM). Files from Excel may have a UTF-8 BOM (`\xef\xbb\xbf`) — SimGUI strips it automatically (`encoding='utf-8-sig'`).

The first row is always the header. Column order is flexible; columns are identified by name, not position.

---

## Column reference

### Mandatory columns

These columns must be present and populated for programming to succeed:

| Column name | Internal name | Type | Format | Example |
|---|---|---|---|---|
| `ICCID` | `ICCID` | String | 10–20 decimal digits | `8988211812345678901` |
| `IMSI` | `IMSI` | String | 6–15 decimal digits | `999880001000001` |
| `Ki` | `Ki` | Hex string | Exactly 32 hex characters | `A1B2C3D4E5F60718293A4B5C6D7E8F90` |
| `OPc` | `OPc` | Hex string | Exactly 32 hex characters | `0102030405060708090A0B0C0D0E0F10` |
| `ADM1` | `ADM1` | String | 8 decimal digits OR 16 hex characters | `12345678` or `4142434445464748` |

> **ICCID is read-only in the UI.** It is always read from the factory-assigned value on the card or from the data file. SimGUI will not write an ICCID to a card. See [Why ICCID is read-only](../explanation/iccid-traceability.md).

### Optional columns

These columns are programmed if present. If absent, the corresponding field is skipped.

| Column name | Type | Format | Description |
|---|---|---|---|
| `MNC_LENGTH` | Integer | `2` or `3` | Length of the MNC portion of the IMSI/HPLMN |
| `ALGO_2G` | String | Enum | Authentication algorithm for 2G (e.g. `COMP128v1`, `MILENAGE`) |
| `ALGO_3G` | String | Enum | Authentication algorithm for 3G |
| `ALGO_4G5G` | String | Enum | Authentication algorithm for 4G/5G |
| `USE_OPC` | Boolean | `1`/`0` or `true`/`false` | Whether OPc (not OP) is used |
| `HPLMN` | String | MCC+MNC | Home PLMN code (e.g. `99988`) |
| `SPN` | String | Up to 16 characters | Service Provider Name displayed on the device |
| `LI` | String | 2-letter ISO 639-1 | Preferred Language Indicator (e.g. `EN`, `SV`) |
| `FPLMN` | String | Semicolon-separated PLMNs | Forbidden PLMN list (e.g. `23415;23410;23420`) |
| `ACC` | String | Hex or decimal | Access Control Class |
| `PIN1` | String | 4–8 digits | PIN1 value |
| `PUK1` | String | 8 digits | PUK1 value |
| `PIN2` | String | 4–8 digits | PIN2 value |
| `PUK2` | String | 8 digits | PUK2 value |

### Auto-artifact extra fields

When SimGUI writes auto-artifact CSVs to the network share, it adds:

| Column | Value |
|---|---|
| `programmed_at` | ISO 8601 timestamp of programming (e.g. `2026-03-14T10:30:45.123456`) |

---

## Column name normalisation

SimGUI normalises common column name variants on load. You do not need to rename columns in your source files:

| Input name (case-insensitive) | Normalised to |
|---|---|
| `adm` | `ADM1` |
| `ki` | `Ki` |
| `opc` | `OPc` |
| Any other name | Uppercased (e.g. `iccid` → `ICCID`) |

---

## Validation rules

SimGUI validates each row before programming. Rows with errors are highlighted but do not block programming of other rows.

| Field | Rule |
|---|---|
| `ICCID` | Digits only; 10–20 characters |
| `IMSI` | Digits only; 6–15 characters |
| `Ki` | Hex characters only; exactly 32 characters (spaces stripped before validation) |
| `OPc` | Hex characters only; exactly 32 characters (spaces stripped before validation) |
| `ADM1` | Either 8 decimal digits or 16 hex characters; empty is accepted (field may be absent) |

Hex validation is case-insensitive (`[0-9a-fA-F]`).

---

## Example CSV

```csv
ICCID,IMSI,Ki,OPc,ADM1,MNC_LENGTH,ALGO_2G,ALGO_3G,ALGO_4G5G,USE_OPC,HPLMN,SPN,LI,FPLMN
8988211812345678901,999880001000001,A1B2C3D4E5F60718293A4B5C6D7E8F90,0102030405060708090A0B0C0D0E0F10,12345678,3,MILENAGE,MILENAGE,MILENAGE,1,99988,ACME_NETWORKS,EN,
8988211812345678902,999880001000002,B2C3D4E5F6071829 ... (32 chars),020304050607080 ... (32 chars),87654321,3,MILENAGE,MILENAGE,MILENAGE,1,99988,ACME_NETWORKS,EN,
```

---

## EML-imported column mapping

When loading a sysmocom `.eml` file, the EML parser extracts the card table and normalises column names using the same rules above. The resulting in-memory representation is identical to loading a CSV — the batch programming workflow treats both sources the same way.

See [Import a sysmocom order email](../how-to/import-order-email.md) for EML import instructions.

---

## SUCI card ICCIDs

Non-SUCI cards have **23-digit ICCIDs**. SUCI-capable cards (sysmoISIM-SJA5 with SUCI firmware) have **19-digit ICCIDs**. Both are valid and accepted by SimGUI. The digit count difference is meaningful — see [SUCI vs non-SUCI](../explanation/suci-vs-non-suci.md).
