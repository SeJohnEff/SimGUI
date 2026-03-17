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

- [ ] **SIM standard as Markdown** — Replace `standards.json` with a version-controlled Markdown document defining the Teleaura SIM PLMN Numbering Standard. This would be human-readable, diffable in git, and parseable at runtime. Should include: IMSI range allocations per site, ICCID range allocations, SPN canonical values, LI values, FPLMN defaults per country, and site register. Enables richer UI: dropdowns in batch programming for IMSI ranges, ICCID ranges, site codes, and country-based FPLMN defaults.

- [ ] **Remove standalone ADM1 Authenticate button** — The separate "Authenticate" step in the Program SIM panel is unnecessary and confusing for operators. ADM1 authentication happens automatically when programming, so the button adds an extra step with no value. **Exception:** keep an authenticate action if there are protected fields that require ADM1 to *read* (e.g. Ki, OPc read-back). If read-back is the only use case, rename to "Read Protected Fields" or similar. The goal: operators should go from card-detected → program in one click, not card-detected → authenticate → program.

## Known Issues (Acceptable / Deferred)

- [ ] Share indicator grey on startup (user: "Acceptable, don't look into this right now")
- [ ] App unresponsive after closing Network Storage dialog (user: "Acceptable")
- [ ] Right pane says "Insert SIM" even after blank card detected
- [ ] Card data blanks out when removing/inserting SIM
