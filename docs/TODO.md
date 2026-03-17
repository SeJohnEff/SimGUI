# SimGUI — TODO / Backlog

## Test Quality Audit

- [ ] **Audit tests for "tautological assertions"** — tests that only verify the code
  does what it does, rather than validating it does the *right* thing.
  - Example: `test_safe_shell_includes_noprompt` asserted `--noprompt` was in the
    command — matching the broken implementation. A correct test would have validated
    that piped stdin commands are actually processed by pySim-shell.
  - Example: `test_check_sudo_mount_uses_absolute_paths` asserted the subprocess
    call included `/usr/bin/mount`, but never checked whether the probe command
    (`mount --help`) actually matched the sudoers NOPASSWD rule pattern.
  - **Pattern to watch for**: any test that mocks the exact implementation detail
    and asserts it back, rather than testing observable behavior or contract.
  - Priority: medium — these tests give false confidence and mask real bugs.

## Completed (v0.5.18–0.5.20)

- [x] Detect pySim-shell APDU errors (SwMatchError/6f00) even on exit code 0
- [x] Eliminate double ADM1 authentication during programming
- [x] ADM1 format detection by length (16=hex, ≤8=ASCII)
- [x] Blank card safety — skip VERIFY ADM1 on unpersonalised cards
- [x] Gialersim card type auto-detection and programming support
- [x] `-t gialersim -a` flag routing in `_run_pysim_prog()`

## Future Improvements

- [ ] **SIM standard as Markdown** — Replace `standards.json` with a version-controlled Markdown document (e.g. `sim-standard.md`) defining the Teleaura SIM PLMN Numbering Standard. The top of the document is human-readable prose and tables (site register, IMSI structure, ICCID structure, FPLMN per country). The bottom contains a fenced JSON block (`\`\`\`json ... \`\`\``) with the machine-parseable data — SimGUI parses only that block. This way the document is readable, diffable, and version-controlled, while SimGUI gets structured data without a separate file. Should include: IMSI range allocations per site, ICCID range allocations, SPN canonical values, LI values, FPLMN defaults per country, and site register. Enables richer UI: dropdowns in batch programming for IMSI ranges, ICCID ranges, site codes, and country-based FPLMN defaults.

- [ ] **ICCID mismatch override for blank cards** — Currently, ICCID cross-verification aborts authentication when the card's ICCID doesn't match the CSV row. This blocks blank card programming because blank cards have a factory ICCID (e.g. `8901901557518313028`) that differs from the target ICCID in the CSV (the one to be written). For blank/gialersim cards this check is wrong — the whole point is to *overwrite* the ICCID. Fix: allow an override ("I know what I'm doing") for blank cards. The safety argument is weaker here because all Fiskarheden blank cards share the same default ADM1 (`3838383838383838` / `88888888`), so a mismatch doesn't risk locking the wrong card. Consider: auto-skip the check when `card_type == GIALERSIM`, or show a confirmation dialog instead of a hard abort.

- [ ] **Batch programming: Site Code and SPN not populated** — The Batch Preview table shows Site Code and SPN columns, but they are empty when loading files like `uk1_100_sims.txt` that don't contain these fields. Currently there is no way for an operator to enter or configure them in the batch UI. Two approaches to consider:
  1. **Auto-populate from `sim-standard.json`** — Parse the ICCID's SSSS (site code) field and look up the site in the standard to derive the Site Code label and SPN value automatically. E.g. ICCID `8999988000100000019` → SSSS=`0001` → site `uk1` → SPN `Teleaura UK`.
  2. **Manual entry in batch panel** — Add input fields or dropdowns in the batch panel header (alongside Start Row / Count) for Site Code and SPN that apply to all rows in the batch.
  Approach 1 is preferred (less manual work, uses the standard as source of truth). Ties into the "SIM standard as Markdown" item above — richer standard data enables richer auto-population. Also consider: LI (language) and FPLMN defaults per site/country from the standard.

- [ ] **Support SPN and FPLMN columns in CSV/TXT import files** — Currently `STANDARD_COLUMNS` in `csv_manager.py` does not include SPN or FPLMN, so these fields are ignored even if present in the source file. The CSV format docs list them as optional columns, but they have no write handlers in `card_manager.py`. To support:
  1. Add `SPN` and `FPLMN` to `STANDARD_COLUMNS` in `csv_manager.py`
  2. Add `spn` and `fplmn` to `_COLUMN_NORMALIZE` if needed (for case-insensitive matching)
  3. Implement write handlers in `card_manager.py` — pySim-shell can write both (`update_spn`, `update_fplmn`)
  4. Show SPN and FPLMN in the Batch Preview table when present in the file
  This is complementary to the auto-populate approach above — if the file contains SPN/FPLMN, use them; if not, fall back to auto-populate from `sim-standard.json`. File values should take precedence over standard defaults.

- [ ] **Remove standalone ADM1 Authenticate button** — The separate "Authenticate" step in the Program SIM panel is unnecessary and confusing for operators. ADM1 authentication happens automatically when programming, so the button adds an extra step with no value. **Exception:** keep an authenticate action if there are protected fields that require ADM1 to *read* (e.g. Ki, OPc read-back). If read-back is the only use case, rename to "Read Protected Fields" or similar. The goal: operators should go from card-detected → program in one click, not card-detected → authenticate → program.

## Critical Bugs (Batch Programming)

- [ ] **CRITICAL: ATR-based ICCID caching breaks batch for blank cards** — All blank gialersim cards share the same ATR (`3B 9F 95 80 1F C7 80 31 A0 73 B6 A1 00 67 CF 32 15 CA 9C D7 09 20`). After Card 1 is programmed (ICCID `8999988000100000019`), its ICCID gets cached against that ATR. When Card 2 is inserted (same ATR, different physical card), `CardWatcher` returns the cached ICCID from Card 1: `"using cached ICCID 8999988000100000019 for ATR ..."`. This means Card 2 is misidentified as Card 1. In batch mode, the ATR→ICCID cache MUST be invalidated between cards — either clear it on card removal, or disable ATR caching entirely during batch operations.

- [ ] **CRITICAL: ADM1 retry counter 1 on fresh blank card** — Card 2 (a fresh blank card) shows `ADM1 retry counter: 1 remaining` at `21:26:26`, moments after insertion. A fresh blank card should have 3 attempts. Root cause likely: the auto-read flow is performing an ADM1 verify/probe on the new card, consuming attempts. Because of the ATR caching bug above, it may be using Card 1's (now-programmed) ADM1 key against Card 2 — or the auto-read flow is doing something that triggers ADM1 attempts. The safety check then correctly aborts (`DANGER: Only 1 ADM1 attempt(s) remaining`), but the real bug is that 2 attempts were already burned during the auto-read. **This is dangerous** — in a 3-card batch, the third card could be locked.
  - Investigate: what in the auto-read/card-detect flow triggers ADM1 verification? This should NEVER happen automatically.
  - Investigate: is the ATR caching bug causing the wrong key to be tried?

- [ ] **Authenticate + Program Card flow broken for gialersim** — On a gialersim card with 1 ADM1 attempt remaining: user clicks Authenticate, gets the "1 attempt remaining" warning, clicks OK to force through. Authenticate "succeeds" — but it only stores the key (`"Gialersim card (uses different auth method) — ADM1 stored"`), it does NOT actually verify against the card. Then when user clicks Program Card, it checks the retry counter again, still sees 1 remaining, and aborts with `DANGER: Only 1 ADM1 attempt(s) remaining`. The user overrode the safety warning for nothing — Authenticate gave a false sense of having passed the check. Two fixes needed:
  1. **Authenticate on gialersim should either actually verify or clearly state it cannot** — don't pretend to authenticate when all it does is store the key.
  2. **If user already forced past the safety warning in Authenticate, Program Card should honour that override** — don't ask twice for the same decision. The override should carry forward to the programming step.
  - Related: the "Remove standalone ADM1 Authenticate button" TODO item above — this is another argument for removing it, since for gialersim cards the Authenticate step is misleading.

- [ ] **FPLMN not programmed on gialersim — pySim-shell ADM1 auth fails after pySim-prog** — FPLMN is handled as an "extra field" via pySim-shell after pySim-prog completes the core programming. But pySim-shell's VERIFY ADM1 fails with `SW 6f00` on the just-programmed gialersim card (`ADM verification (3838383838383838) failed`). Despite the auth failure, pySim-shell partially writes FPLMN data (`"42f010"` = PLMN 24001, only 3 bytes into a 60-byte EF_FPLMN), then the overall operation is flagged as failed. The success message only lists `ICCID, IMSI, Ki, OPc, ACC` — FPLMN is missing. Root cause: gialersim cards use a different auth method than standard VERIFY ADM1. pySim-prog handles this with `-t gialersim -a`, but pySim-shell uses standard VERIFY which doesn't work. Fix options:
  1. Use pySim-shell's gialersim-aware auth method (if it exists)
  2. Write FPLMN within the pySim-prog session before it exits (if pySim-prog supports it)
  3. Use pySim-shell with `-t gialersim` flag or equivalent to use the correct auth path
  - Also: the partial write (`WARNING: Data length (3) less than file size (60)`) means only one PLMN was encoded. If multiple FPLMNs are needed (e.g. `24001;24002`), the encoding logic must pad/fill correctly.

- [ ] **SPN shows "Not available" after programming even though it was written** — pySim-prog successfully writes SPN (log: `> Name : Teleaura UK`, `Programming successful`, `pySim-prog succeeded: ICCID, IMSI, Ki, OPc, ACC, SPN`). But the immediate post-program verify read-back already reports `'SPN': 'Not available'`. On re-insert, Card Status also shows `SPN: Not available`. The SPN is on the card (pySim-prog confirmed it), but the pySim-shell read-back in `card_manager` can't read it. Likely cause: the SPN read function doesn't know how to read the EF_SPN file on gialersim cards, or the pySim-shell command used for read-back doesn't extract SPN. Investigate: what pySim-shell command is used to read SPN, and does it work on gialersim cards?

- [ ] **PIN1/PUK1/PIN2/PUK2 write handlers missing** — Log shows `program_card: field 'PIN1' has no write handler, skipped` (same for PUK1, PIN2, PUK2). These fields are present in the CSV but silently dropped. Either implement write handlers (pySim-shell can set PINs/PUKs) or warn the operator in the batch log that these fields were not programmed.

- [ ] **Batch artifact file — verify it is saved** — After batch programming (1 success, 1 fail), confirm the auto-artifact CSV is written to the network share. Need to check: does the artifact include only the successful card, or is the failed card also recorded (with failure status)? The artifact should log both outcomes for traceability.

## Known Issues (Acceptable / Deferred)

- [ ] Share indicator grey on startup (user: "Acceptable, don't look into this right now")
- [ ] App unresponsive after closing Network Storage dialog (user: "Acceptable")
- [ ] Right pane says "Insert SIM" even after blank card detected
- [ ] Card data blanks out when removing/inserting SIM
- [ ] **"Card not in index" after just programming** — After programming a SIM (ICCID `8999988000100000019`), removing and re-inserting shows the correct "this sim has been programmed before" pop-up, but then immediately shows the "Load Card Data File" dialog saying "Card not in index". The ICCID index is either not updated after programming completes, or the auto-read flow triggers a second lookup that doesn't find the card in the index. Expected: after programming, the card's ICCID should be in the index and re-insert should go straight to showing card data without prompting for a file.
