# Reference: standards.json schema

`standards.json` is a JSON configuration file placed at the root of a network share. It provides canonical, authoritative values for enumerable SIM fields (currently SPN and LI). SimGUI reads it when a share is mounted and uses it to validate and auto-suggest field values.

**Source of truth:** `managers/standards_manager.py` — `StandardsManager`, `STANDARDS_FILENAME`, `SUPPORTED_VERSION`.

---

## File location

The file must be named exactly `standards.json` (case-sensitive on Linux filesystems) and placed at the **root** of the network share mount point:

```
/mnt/simgui-share/
  standards.json         ← SimGUI reads this
  auto-artifact/
    8988211812345678901_20260314_103045.csv
  card-data.csv
```

SimGUI does **not** search subdirectories.

---

## Schema

```json
{
  "version": 1,
  "spn": ["STRING", "STRING", ...],
  "li": ["STRING", "STRING", ...]
}
```

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | Integer | No (defaults to `1`) | Schema version. Currently only version `1` is defined. |
| `spn` | Array of strings | No (defaults to empty) | Canonical SPN (Service Provider Name) values |
| `li` | Array of strings | No (defaults to empty) | Canonical LI (Language Indicator) values |

Additional keys at the top level are silently ignored. This makes forward compatibility safe — a future version can add keys without breaking older SimGUI versions.

### `version`

| Value | Meaning |
|---|---|
| `1` | Current version. Defines `spn` and `li` arrays. |
| `> 1` | Loaded with a warning; unknown keys ignored. SimGUI continues to read `spn` and `li`. |

### `spn` array

Each element is a string representing a canonical Service Provider Name. Values are:

- **Case-exact**: stored and compared with the exact casing in the file.
- **Trimmed**: leading and trailing whitespace is stripped on load.
- **No length limit** in the schema, but SIM cards typically support SPN up to 16 characters (enforced by the CLI tool, not SimGUI).

SimGUI provides `suggest_spn(value)` which performs a case-insensitive lookup, returning the canonical form. For example: `suggest_spn("boliden")` returns `"BOLIDEN"` if `"BOLIDEN"` is in the list.

### `li` array

Each element is a canonical Language Indicator value. Typically ISO 639-1 two-letter codes (`"EN"`, `"SV"`, `"FI"`, `"DE"`, etc.), but the schema does not enforce a specific format — any non-empty string is accepted.

---

## Full example

```json
{
  "version": 1,
  "spn": [
    "BOLIDEN",
    "FISKARHEDEN",
    "TELEAURA",
    "NORTHNET",
    "ACME_NETWORKS"
  ],
  "li": [
    "EN",
    "SV",
    "FI",
    "NO",
    "DE"
  ]
}
```

---

## Template generation

The `StandardsManager.create_template()` static method writes a starter file:

```python
from managers.standards_manager import StandardsManager

StandardsManager.create_template(
    "/mnt/simgui-share/standards.json",
    spn=["YOUR_PROVIDER"],
    li=["EN"]
)
```

The generated file uses 2-space indentation, UTF-8 encoding, and a trailing newline.

---

## Merging from multiple shares

When multiple network shares are mounted and each has a `standards.json`, SimGUI merges them:

1. Values are merged in the order shares are loaded.
2. De-duplication is **case-exact**: `"BOLIDEN"` and `"boliden"` are treated as distinct values and both appear if they come from different files.
3. `spn` and `li` lists are merged independently.

**Recommendation:** Keep values consistent (same casing) across all shares to avoid unwanted duplicates in dropdowns.

---

## Validation behaviour

| Scenario | SimGUI behaviour |
|---|---|
| File absent from share root | Standards not loaded; SPN/LI fields accept free text |
| File present but invalid JSON | Warning logged; file skipped; other shares still loaded |
| File present but not a JSON object | Warning logged; file skipped |
| `spn` is not an array | `spn` treated as empty; `li` loaded normally |
| `li` is not an array | `li` treated as empty; `spn` loaded normally |
| String value in array is empty or whitespace | Silently skipped |
| Unknown top-level key | Silently ignored |

---

## Programmatic access

The `StandardsManager` API:

| Method / Property | Description |
|---|---|
| `spn_values` | `list[str]` — current canonical SPN list |
| `li_values` | `list[str]` — current canonical LI list |
| `has_standards` | `bool` — `True` if at least one file loaded |
| `loaded_paths` | `list[str]` — paths of all successfully loaded files |
| `load_from_directory(dir)` | Load (and merge) from a directory; returns `bool` |
| `reload_from_directories(dirs)` | Clear and reload from a list of directories; returns count |
| `is_valid_spn(value)` | Case-exact membership check |
| `is_valid_li(value)` | Case-exact membership check |
| `suggest_spn(value)` | Case-insensitive lookup; returns canonical form or `None` |
| `suggest_li(value)` | Case-insensitive lookup; returns canonical form or `None` |
| `clear()` | Remove all loaded values |

---

## How-to

For step-by-step instructions on creating and maintaining this file, see [Create and maintain standards.json](../how-to/standards-file.md).
