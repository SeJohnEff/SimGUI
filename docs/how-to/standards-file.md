# How to: Create and maintain standards.json

`standards.json` is a small JSON file placed at the root of a network share. It defines the canonical, authoritative values for SPN (Service Provider Name) and LI (Language Indicator) fields. SimGUI reads this file when a share is mounted and uses the values to validate and auto-suggest entries during card programming.

Without `standards.json`, SimGUI falls back to free-text entry for these fields — acceptable for one-off work, but error-prone for teams programming cards across multiple sessions.

**Source of truth:** `managers/standards_manager.py` — `StandardsManager.create_template()`

---

## Prerequisites

- An SMB network share mounted (see [Configure a network share](network-share-setup.md))
- Write access to the root of the share
- A text editor

---

## Step 1: Create the file

Place `standards.json` at the **root** of your network share (not in a subdirectory). SimGUI looks for it at `{mount_point}/standards.json`.

Minimum valid content:

```json
{
  "version": 1,
  "spn": ["ACME_NETWORKS"],
  "li": ["EN"]
}
```

A more complete example for a multi-operator environment:

```json
{
  "version": 1,
  "spn": [
    "BOLIDEN",
    "FISKARHEDEN",
    "TELEAURA",
    "NORTHNET"
  ],
  "li": [
    "EN",
    "SV",
    "FI",
    "NO"
  ]
}
```

---

## Step 2: Use the template generator

SimGUI includes a Python helper to generate a starter file:

```python
from managers.standards_manager import StandardsManager

StandardsManager.create_template(
    "/mnt/simgui-share/standards.json",
    spn=["ACME_NETWORKS", "NORTHNET"],
    li=["EN", "SV"]
)
```

Run this from a Python 3 environment where SimGUI is installed, or copy the output manually.

---

## Step 3: Verify SimGUI loads it

1. Mount the share in SimGUI (Settings → Network Storage).
2. Check the log or status bar. You should see:

   ```
   Loaded standards from /mnt/simgui-share/standards.json: 4 SPN, 3 LI values
   ```

3. In the **Batch Program** tab, the SPN and LI input fields now show dropdown menus with your canonical values instead of plain text boxes.

<!-- screenshot: spn-dropdown-with-canonical-values -->

---

## Adding new values

Edit `standards.json` directly in a text editor:

```bash
nano /mnt/simgui-share/standards.json
```

Add new entries to the `spn` or `li` arrays. SimGUI re-reads the file each time a share is mounted or remounted. There is no live reload — unmount and remount the share in SimGUI to pick up changes, or restart SimGUI.

---

## Case sensitivity

Values are **case-exact** as written in the file. SimGUI stores and compares them without normalisation. This is by design — SPN values are embedded in the SIM and must match operator requirements exactly.

The `suggest_spn()` function performs a case-insensitive lookup for auto-correction (e.g. "boliden" → "BOLIDEN"), but canonical validation is always case-exact.

Always use the exact casing your operator or standards body requires.

---

## Multiple shares with overlapping values

If you have multiple shares mounted, each with their own `standards.json`, SimGUI merges the lists. De-duplication is case-exact: `"BOLIDEN"` and `"boliden"` would both appear if they came from different files. Keep values consistent across shares to avoid duplicates.

---

## File format rules

| Rule | Detail |
|---|---|
| Must be valid JSON | UTF-8 encoding, no trailing commas |
| `version` field | Currently `1`; future versions may add fields |
| `spn` array | Array of strings; empty array is valid (no SPN validation) |
| `li` array | Array of strings; empty array is valid (no LI validation) |
| Unknown keys | Ignored by SimGUI; safe to add comments via a `_comment` key |
| Values with whitespace | Stripped of leading/trailing whitespace on load |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Standards not loaded | File not at share root, or malformed JSON | Check path; validate JSON with `python3 -m json.tool standards.json` |
| Dropdowns empty | Share not mounted in SimGUI | Mount share in Settings → Network Storage |
| Values appear twice | Duplicate across two shares | Audit both files; remove duplicates |
| SPN validation fails for known value | Case mismatch | Match exact case in `standards.json`; check for invisible characters |

For the full schema specification, see [standards.json reference](../reference/standards-json.md).
