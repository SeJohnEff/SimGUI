# PCSC Parameter Seam Design Note

**Stage:** S3-A (docs-only, no implementation)
**Status:** Draft — awaiting human approval before S3-B begins
**Baseline:** Ubuntu v0.5.50 (authoritative); macOS untested

---

## 1. Current v0.5.50 Behavior

SimGUI always uses **reader index 0** — the first PCSC reader in the system enumeration list.
This assumption is expressed in two ways:

### 1a. CLI flag `-p0`
All three pySim subcommands are invoked with the `-p0` flag, which tells pySim to use the
first PCSC reader (slot index 0):

| Call site | File | Line | Command |
|-----------|------|------|---------|
| `detect_card` (primary read) | `managers/card_manager.py` | 467, 471 | `pySim-read.py -p0` |
| `_run_pysim_shell_safe` (auth) | `managers/card_manager.py` | 616 | `pySim-shell.py -p0` |
| `_run_pysim_prog` (write) | `managers/card_manager.py` | 711 | `pySim-prog.py -p0 -t …` |
| `_verify_write` (post-write read) | `managers/card_manager.py` | 1272 | `pySim-read.py -p0` |

All four pass `-p0` as a positional string literal embedded in the command list.

### 1b. In-process pyscard reader selection
Two methods bypass the pySim CLI entirely and talk to pyscard directly. Both hardcode
`rlist[0]` — the first element of the reader enumeration:

| Method | File | Line | Code |
|--------|------|------|------|
| `probe_card_presence` | `managers/card_manager.py` | 416 | `reader = rlist[0]` |
| `check_adm1_retry_counter` | `managers/card_manager.py` | 801 | `reader = rlist[0]` |

`probe_card_presence` is called by `CardWatcher` every 1.5 s; it is the heartbeat that
drives all state-machine transitions. `check_adm1_retry_counter` is called before every
authentication attempt to guard against card blocking.

---

## 2. Where the Seam Is

There are exactly **two independent seam surfaces**:

### Seam A — CLI flag `-p0`
The pySim flag `-p0` is a string literal assembled inside four call sites in
`card_manager.py`. To make the reader index configurable, this literal must be replaced
by a variable (e.g., `f'-p{self._pcsc_reader_index}'`). The value must come from
construction time, not from `sys.platform` inside the method.

### Seam B — In-process pyscard index `rlist[0]`
The pyscard enumeration subscript `[0]` appears in two methods. To make this configurable,
`rlist[0]` must be replaced by `rlist[self._pcsc_reader_index]` (or the configured index),
with a bounds-check before access.

Both seams resolve to **one shared value**: a reader index (integer, default 0). They must
stay in sync — using index 1 for the CLI but index 0 for the APDU probe would target
different hardware and corrupt the retry-counter read and card-presence signal.

---

## 3. Where the Seam Should Live

The reader index must be **a constructor parameter** on `CardManager`, defaulting to `0`.

**Rationale:**

- `CardManager` is instantiated once at startup and lives for the application session.
  A constructor parameter is the canonical way to inject a single session-scoped value.
- The value is the same for all four call sites inside `CardManager` — one instance variable
  (`self._pcsc_reader_index`) covers Seams A and B uniformly.
- Environment variables and settings files are read before startup. Either could feed the
  constructor argument, but the seam itself is the constructor parameter — not the source of
  the value. This keeps `CardManager` testable without environment manipulation.
- `CardWatcher` does not need to know the reader index; it calls
  `CardManager.probe_card_presence()`, which already encapsulates the selection.

**What does NOT qualify as the seam location:**

- Inside `probe_card_presence` or `check_adm1_retry_counter` — these are leaf methods;
  injecting platform branching there would violate Prohibition 5 and Rule 5a.
- In `card_watcher.py` — that file must remain platform-free (Prohibition 5).
- In `platform_runtime.py` — the reader index is not a platform path or OS convention;
  it is a hardware configuration value. Putting it in `platform_runtime` conflates
  two distinct concerns.

---

## 4. Files and Functions That Would Change in S3-B

| File | Symbol | Change required |
|------|--------|-----------------|
| `managers/card_manager.py` | `CardManager.__init__` | Add `pcsc_reader_index: int = 0` parameter; store as `self._pcsc_reader_index` |
| `managers/card_manager.py` | `probe_card_presence` (line 416) | Replace `rlist[0]` with `rlist[self._pcsc_reader_index]`; add bounds-check |
| `managers/card_manager.py` | `check_adm1_retry_counter` (line 801) | Replace `rlist[0]` with `rlist[self._pcsc_reader_index]`; add bounds-check |
| `managers/card_manager.py` | `_run_pysim_shell_safe` (line 616) | Replace `'-p0'` with `f'-p{self._pcsc_reader_index}'` |
| `managers/card_manager.py` | `_run_pysim_prog` (line 711) | Replace `'-p0'` with `f'-p{self._pcsc_reader_index}'` |
| `managers/card_manager.py` | `detect_card` (lines 467, 471) | Replace `'-p0'` with `f'-p{self._pcsc_reader_index}'` |
| `managers/card_manager.py` | `_verify_write` (line 1272) | Replace `'-p0'` with `f'-p{self._pcsc_reader_index}'` |
| `ui/main_window.py` | `CardManager(…)` instantiation | Pass `pcsc_reader_index` from settings or environment |

Total lines changed: approximately 8–10 lines in `card_manager.py`, 1 line in `main_window.py`.

---

## 5. Files and Functions That Must Not Change

| File | Reason |
|------|--------|
| `managers/card_watcher.py` | Platform-free state machine — Prohibition 5 and Rule 5a |
| `managers/csv_manager.py` | Unrelated to hardware |
| `managers/network_storage_manager.py` | Unrelated to PCSC |
| `managers/batch_manager.py` | Calls `CardManager` methods; no direct PCSC access |
| `platform_runtime.py` | Must not acquire SIM or PCSC logic |
| `docs/reference/state-machine.md` | Authoritative — never modified by implementation tasks |

The state machine is unaffected: `CardState` transitions depend on the *result* of
`probe_card_presence`, not on which reader index was queried. Changing the index value
does not alter any transition condition.

---

## 6. Risks

### 6a. SIM programming
**Risk:** If `self._pcsc_reader_index` is set to a wrong index (e.g., 1 when only one
reader is present), all CLI tools will fail with "reader not found". This will surface
immediately as a `detect_card` failure — no card data, no programming attempted.
**Severity:** Low on Ubuntu (single-reader deployments), medium on macOS (multiple
USB-device entries possible).
**Mitigation:** Default of 0. Bounds-check before pyscard access. Fail fast with a
clear error message if index is out of range.

### 6b. Authentication and retry counters
**Risk:** `probe_card_presence` and `check_adm1_retry_counter` use the in-process pyscard
path. If these use a different index than the CLI tools, they would probe a different
reader than pySim-prog writes to. This is the most critical safety risk — a mismatch
would cause the retry counter to be read from the wrong card, potentially allowing an
ADM1 attempt on a card that has 0 retries remaining.
**Mitigation:** The single `self._pcsc_reader_index` instance variable ensures all four
seam points always use the same value. This is why both Seam A and Seam B must resolve
to the same field.

### 6c. Card detection and state-machine transitions
**Risk:** `CardWatcher` calls `probe_card_presence` every 1.5 s. If the index targets
an empty slot, every poll returns "No card in reader", driving the state machine to
`NO_CARD`. The app would appear to have no reader.
**Mitigation:** Same as 6a — bounds-check + fail-fast at startup before `CardWatcher`
begins polling.

### 6d. Ubuntu baseline regression
**Risk:** Adding a constructor parameter changes the `CardManager` signature. Any test
that constructs `CardManager` directly without keyword arguments could break if the
parameter is positional.
**Mitigation:** The new parameter must be keyword-only with default `0`. All existing
call sites `CardManager(…)` that do not pass `pcsc_reader_index` will silently retain
the current behavior. Zero behavioral change for Ubuntu default deployments.

---

## 7. Proposed Minimal Implementation for S3-B

> **This is a design sketch only. No implementation until S3-B is explicitly approved.**

```python
# managers/card_manager.py — __init__ signature change
class CardManager:
    def __init__(
        self,
        cli_path: Optional[str] = None,
        venv_python: Optional[str] = None,
        *,
        pcsc_reader_index: int = 0,   # <-- new, keyword-only, default 0
    ):
        self._pcsc_reader_index = pcsc_reader_index
        # ... rest unchanged ...

# probe_card_presence — in-process pyscard
reader = rlist[self._pcsc_reader_index]   # was: rlist[0]

# check_adm1_retry_counter — in-process pyscard
reader = rlist[self._pcsc_reader_index]   # was: rlist[0]

# All four CLI sites — replace literal
f'-p{self._pcsc_reader_index}'            # was: '-p0'
```

Caller site in `ui/main_window.py`:
```python
reader_index = int(os.environ.get('SIMGUI_PCSC_READER', '0'))
card_manager = CardManager(cli_path=…, venv_python=…, pcsc_reader_index=reader_index)
```

Using an environment variable keeps the default path zero-change and avoids a
settings-file format change for this initial step.

---

## 8. Required Tests for S3-B

All tests must pass on Ubuntu without modification before S3-B begins (Rule 9).

| Test | Assertion |
|------|-----------|
| `CardManager(pcsc_reader_index=0)` invokes `pySim-read.py -p0` | Baseline unchanged |
| `CardManager(pcsc_reader_index=1)` invokes `pySim-read.py -p1` | Seam is wired |
| `CardManager(pcsc_reader_index=1)` invokes `pySim-shell.py -p1` | Seam is wired (auth) |
| `CardManager(pcsc_reader_index=1)` invokes `pySim-prog.py -p1 …` | Seam is wired (write) |
| `CardManager()` (no argument) invokes `pySim-read.py -p0` | Default preserved |
| `probe_card_presence` uses `rlist[self._pcsc_reader_index]` | In-process seam is wired |
| `check_adm1_retry_counter` uses `rlist[self._pcsc_reader_index]` | In-process seam is wired |
| `CardManager(pcsc_reader_index=99)` with a 1-reader list returns error | Bounds-check works |
| Existing `test_detect_card_pysim_invokes_read_with_p0_flag` passes unchanged | Ubuntu baseline |

The existing contract test `test_detect_card_pysim_invokes_read_with_p0_flag`
(`tests/test_e2e_contracts.py`, lines 245–268) must continue to pass as-is because
`CardManager()` with no `pcsc_reader_index` must default to index 0.

---

## 9. Rollback Condition

Revert S3-B if any of the following occur:

1. Any Ubuntu test that passed on the v0.5.50 baseline now fails.
2. `CardManager()` with no `pcsc_reader_index` argument produces a `-p` value other than `0`.
3. The `probe_card_presence` and CLI tools use different reader indices in any code path.
4. The constructor change is positional (not keyword-only), breaking existing call sites.
5. Any platform branch (`if sys.platform`, `if _MACOS`) is introduced in `card_manager.py`
   or `card_watcher.py` as part of implementing this seam.

---

## 10. Human Approval Gate

**S3-B must not begin until a human explicitly approves this design note in writing.**

Questions requiring human decision before S3-B:

1. **Value source:** Environment variable (`SIMGUI_PCSC_READER`) or a settings key in
   `settings_manager.py`? The env-var approach is simpler and avoids a settings migration,
   but a settings key integrates with the existing configuration panel.
2. **Bounds-check behavior:** On out-of-range index, should SimGUI (a) fail fast at startup
   with an error dialog, or (b) fall back silently to index 0 and log a warning?
3. **macOS scope:** Is this seam intended only for macOS multi-reader disambiguation, or
   should Ubuntu users also be able to configure a non-zero reader index (e.g., for
   multi-reader batch stations)?

No implementation work on `card_manager.py`, `card_watcher.py`, or any test file may
begin until these questions are answered and this note is approved.
