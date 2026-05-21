# Test Baseline — Ubuntu — v0.5.50

This is the authoritative production baseline for SimGUI v0.5.50.
It confirms that Ubuntu application behavior is intact and protected.

---

## Environment

| Field | Value |
|---|---|
| Platform | Ubuntu (ARM/aarch64, UTM VM) |
| Git commit | `ce49aa24e12b781cc231d7b72b57c980ab36093a` |
| Branch | `main` |

## Test command

```
make test
```

This runs `.venv/bin/python -m pytest -x -q --cov=. --cov-report=term`
after installing both `requirements.txt` and `requirements-dev.txt` into
the virtualenv.

## Results

| Outcome | Count |
|---|---|
| Passed | 2051 |
| Failed | 0 |
| Skipped | 321 |
| **Total** | **2372** |

Run time: 39.28 seconds.

**Zero failures. All application tests pass.**

---

## Notes

### Makefile dependency fix

This baseline was recorded after a one-line fix to the `test` target in
`Makefile` (commit `ce49aa2`). A fresh Ubuntu clone previously failed
because `make test` installed only `requirements-dev.txt`, omitting
`requirements.txt` (which declares PyQt6 and other runtime dependencies).
The fix adds `pip install -r requirements.txt` before the dev install.
No application code was changed.

### Application code status

No application code was changed from v0.5.50. The only changes since the
v0.5.50 tag are:

- `CLAUDE.md` — platform refactoring ground rules (documentation)
- `docs/reference/test-baseline-macos-v0.5.50.md` — macOS baseline (documentation)
- `Makefile` — one-line dependency setup fix in `test` target

### What this baseline protects

Ubuntu v0.5.50 application behavior is now documented and protected by
this result. Any future commit that causes the Ubuntu suite to regress
below **2051 passed, 0 failed** is invalid and must be reverted before
proceeding.

The 321 skipped tests are environment-dependent (Qt GUI tests requiring a
display, hardware-gated tests requiring `SIMGUI_HW_TEST=1`, and tests
requiring test data files not present in a clean clone). They are not
failures.

---

## Relationship to macOS Baseline

The macOS baseline (`test-baseline-macos-v0.5.50.md`) recorded
2006 passed, 15 failed, 351 skipped. The 15 macOS failures are
platform-specific tests for Linux mount commands and Linux-only network
tools — consistent with expected Linux/Ubuntu behavior. The Ubuntu run
confirms those tests pass here with 0 failures.

The difference in skip counts (321 Ubuntu vs 351 macOS) reflects
environment differences, not regressions.

---

**This document must not be deleted or altered retroactively.**
It is the contract for Ubuntu v0.5.50 correctness.
