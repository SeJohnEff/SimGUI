# Troubleshooting

Common problems, their causes, and how to resolve them.

---

## Card detection

### Card not detected

**Symptom:** SimGUI shows no card activity after inserting the card. Status stays "Waiting for card..." indefinitely.

**Check in order:**

1. **PCSC daemon running?**
   ```bash
   systemctl status pcscd
   ```
   If inactive: `sudo systemctl start pcscd`

2. **Reader visible to the OS?**
   ```bash
   pcsc_scan
   ```
   If the reader does not appear, try a different USB port or cable. Check `lsusb` to confirm the reader is enumerated.

3. **CLI tool found?**  
   The status bar should show which backend is active (sysmo-usim-tool or pySim). If it shows "No CLI tool found", see [CLI integration](../reference/cli-integration.md) and [Configuration](../reference/configuration.md).

4. **User permissions?**
   ```bash
   groups $USER
   ```
   If `pcscd` is not in the list: `sudo usermod -aG pcscd $USER` then log out and back in.

5. **Card orientation?**  
   Ensure the gold contacts face down (toward the reader contacts) and the card is fully seated.

---

### Card detected but ICCID not read

**Symptom:** Card watcher fires, but the ICCID field is empty or shows an error.

- Some card types require a specific CLI script. SimGUI tries `sysmo_isim_sja2.py`, `sysmo_isim_sja5.py`, and `sysmo_isim_sjs1.py` in sequence for sysmo-usim-tool. If none work, the ICCID cannot be read.
- For pySim backend, verify `pySim-read.py -p0` works from the command line independently.

---

### Wrong card detected (unexpected ICCID)

**Symptom:** SimGUI reports an ICCID that does not match the physical label on the card.

- Verify the physical label. SUCI cards have 19-digit ICCIDs; non-SUCI have 23-digit ICCIDs. See [SUCI vs non-SUCI](../explanation/suci-vs-non-suci.md).
- The ICCID is always read-only and sourced directly from the card — SimGUI does not modify or override it.

---

## ADM1 and authentication

### ADM1 authentication failed

**Symptom:** Programming aborts with "Authentication failed" or "Wrong ADM1".

**Critical:** Do **not** retry authentication repeatedly. sysmocom cards have a limited number of ADM1 authentication attempts (typically 3 or 10, card-dependent). Exhausting these permanently locks the card.

Steps:
1. Verify the ADM1 value in your CSV/EML matches the vendor-supplied data exactly — no extra spaces, correct digit count (8 decimal or 16 hex).
2. Check you are using the correct data row for the inserted card — the ICCID must match.
3. If you suspect the data file is wrong, contact sysmocom with the card's ICCID to retrieve the correct ADM1.

See [ADM1 security](../explanation/adm1-security.md) for why this design exists.

---

### ICCID mismatch error

**Symptom:** SimGUI aborts with "ICCID mismatch! Card ICCID: ... does not match expected: ..."

This is intentional safety behaviour. The card in the reader has a different ICCID than the data row SimGUI was about to use. Proceeding would authenticate with the wrong ADM1 and risk locking the card.

Resolution:
1. Remove the card.
2. Find the card whose ICCID matches the data row, or find the data row that matches the physical card's ICCID.
3. Re-insert the correct card, or select the correct data row.

Do **not** disable ICCID cross-verification.

---

### ADM1 validation error (before authentication)

**Symptom:** "ADM1 must be 8 decimal digits or 16 hex characters"

This is a format check performed before any card communication. Fix the ADM1 value in your data file:

- Valid formats: `12345678` (8 decimal digits) or `4142434445464748` (16 hex characters)
- Common mistakes: 7 or 9 digits, non-hex letters in a hex key, extra spaces

---

## CSV and data loading

### CSV loads but table is empty

- The file may contain only a header row with no data rows.
- Encoding issue: SimGUI expects UTF-8 (with optional BOM). If the file was saved in Windows-1252 or Latin-1, convert it: `iconv -f WINDOWS-1252 -t UTF-8 input.csv > output.csv`

### Column names not recognised

SimGUI normalises common variants: `ADM` → `ADM1`, `KI` → `Ki`, `OPC` → `OPc`. If your file uses non-standard names, the columns load under their original names and may not participate in validation. Rename them to the [standard column names](../reference/csv-format.md) before loading.

### EML file fails to parse

- Ensure the file is the original sysmocom order confirmation, not a forwarded copy (forwarding can corrupt the MIME structure).
- Try opening the `.eml` in a text editor and checking for the card data table manually.
- If the email is HTML-only with images, the text table may not be present — request a plain-text version from sysmocom.

---

## Network share

### Share mounts but standards not loaded

1. Confirm `standards.json` is at the **root** of the mounted share, not in a subdirectory.
2. Validate the file: `python3 -m json.tool /mnt/simgui-share/standards.json`
3. Unmount and remount the share in SimGUI (Settings → Network Storage).

### Artifacts not saved after programming

1. Verify the share is still mounted: `ls /mnt/simgui-share/`
2. Check write permissions: `touch /mnt/simgui-share/test.tmp && rm /mnt/simgui-share/test.tmp`
3. If the share was temporarily unavailable during programming, re-export from the session log.

### SMB authentication error on mount

```
mount error(13): Permission denied
```

- Double-check credentials (case-sensitive on many SMB servers).
- If using a domain account: `username=DOMAIN\username`.
- Check SMB version compatibility: add `vers=3.0` to mount options if the server requires SMB3.

---

## Simulator mode

### Simulator shows wrong card type

The simulator loads 20 real sysmoISIM-SJA5 profiles. If you are testing SJA2 or SJS1 specific behaviour, use hardware. The simulator covers the common programming workflow but does not emulate every card-type-specific feature.

### Simulator mode left enabled accidentally

Open Settings → uncheck **Simulator Mode**. The status bar shows "SIMULATOR" when active — always verify this indicator before connecting real hardware.

---

## General

### SimGUI window does not open

Try launching from the terminal to see error output:
```bash
simgui
```

Common causes:
- Missing Python dependencies: `pip3 install -r /usr/share/simgui/requirements.txt`
- Display server issue on Wayland: `GDK_BACKEND=x11 simgui`
- Corrupted settings file: `rm ~/.config/simgui/settings.json` (settings will reset to defaults)

### Settings not persisted

Settings are saved to `~/.config/simgui/settings.json`. If the directory is not writable, settings revert on each launch. Check: `ls -la ~/.config/simgui/`

---

## Getting help

If none of the above resolves your issue, collect the following and open a bug report:

1. SimGUI version (`simgui --version`)
2. Ubuntu version (`lsb_release -a`)
3. CLI tool in use and version
4. The full error message from the log panel
5. Whether the issue reproduces in simulator mode

File issues at the [SimGUI GitHub repository](https://github.com/SeJohnEff/SimGUI).
