# Test Baseline — Ubuntu — Post qt_main.py Removal (v0.5.53)

This document records the current authoritative Ubuntu expected result
after the intentional removal of `qt_main.py` in v0.5.53.

**Future regressions must be judged against this baseline, not the
pre-removal v0.5.50 count.**

---

## Environment

| Field | Value |
|---|---|
| Platform | Ubuntu (ARM/aarch64, UTM VM) |
| Git tag | `v0.5.53-remove-qt-main` |
| Branch | `main` |

## Test command

```
python3 -m pytest tests/ -x -q
```

## Results

| Outcome | Count |
|---|---|
| Passed | 2123 |
| Failed | 0 |
| Skipped | 323 |

Run time: 43.89 seconds.

**Zero failures. All application tests pass.**

---

## Why the count differs from v0.5.50

The v0.5.50 Ubuntu baseline recorded **2051 passed, 321 skipped**.
Subsequent commits added tests (platform-aware network storage and
scanner tests, PCSC seam tests, macOS hardware-gated tests) and removed
`qt_main.py`. The count changes are all intentional:

| Change | Δ passed | Δ skipped | Commit |
|---|---|---|---|
| Platform-aware test cleanup (v0.5.52) | +72 | +45 | `26efc29` |
| qt_main.py removal (v0.5.53) | −17 | 0 | `7f572a0` |

The −17 in passed count from v0.5.52 → v0.5.53 is caused by deleting
`qt_main.py`. That file contained a class (`QtSimGUIApp`) which was
instantiated in one or more tests. Once the file was removed, those
tests were dropped along with it. This is expected and is **not a
regression** — the quarantined stub had no application behavior.

---

## Relationship to v0.5.50 baseline

`docs/reference/test-baseline-ubuntu-v0.5.50.md` remains the historical
record of the v0.5.50 contract. It must not be altered. That document's
protected count (2051 passed) applied to the pre-cleanup codebase.

The count protected by **this** document is **2123 passed, 0 failed**.
Any future Ubuntu run that drops below this count and cannot be explained
by an intentional, approved change is a regression and must be reverted.

---

**This document supersedes `test-baseline-ubuntu-v0.5.50.md` as the
active regression guard for Ubuntu correctness.**
