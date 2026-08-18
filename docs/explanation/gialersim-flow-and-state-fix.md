# Gialersim flow correctness + card-lifecycle state single-sourcing

> **Status: IMPLEMENTED in v0.8.1.** This is the design/decision record for the
> gialersim SUCI/verification/state fixes. It is retained as the rationale
> ("why") behind the change; the authoritative "what" lives in
> `docs/reference/state-machine.md`, `docs/GIALERSIM_PROGRAMMING.md`, and the
> code. The three decisions in §8 were resolved as: SPN/FPLMN hidden for
> gialersim; `ProgramOutcome.VERIFY_UNAVAILABLE` added; startup crypto-check
> failure pre-gates gialersim programming with an explicit override.

Original planning note (Rev 2 — folds in
fail-closed verification, pycryptodome as a hard prerequisite, and an explicit
"trust the code over the task framing" principle.)

---

## Guiding principle: the code is the source of truth

Where my reading of the code contradicts the task description, the plan follows
the code and states the contradiction explicitly. Each such contradiction is
flagged **[CONTRADICTS TASK]** below so nothing is resolved silently. This is
the same failure mode that made these cards look programmed for a week: a status
(`9000`) was trusted without being checked. The plan does not repeat that — it
verifies claims (including the task's) against what the code actually does.

---

## 0. Findings that change the shape of the work

### 0.1 [CONTRADICTS TASK] Defect #4 "missing verification" — already implemented, but inert
Task says verification is missing. The code says otherwise:
- `managers/gialersim_selfcheck.py` — full Milenage + USIM `AUTHENTICATE`
  (INS `88`, P2 `81`), TS 35.208 Set-1 self-test, `DB`/`DC` → keys correct,
  `9862`/`6300` → keys wrong.
- `managers/card_manager.py:2089` — `_selfcheck_gialersim_keys(fields)` runs on
  every successful native program (commit `131fce0`).

**Real bug:** the crypto backend is neither installed nor declared —

```
.venv/bin/python -c "import Cryptodome" → ModuleNotFoundError
.venv/bin/python -c "import Crypto"     → ModuleNotFoundError
requirements*.txt / pyproject.toml / SimGUI.spec / debian/control → no crypto dep
```

So `selftest()` returns `False` → `verify_keys()` returns `(None, …)` → **every**
program lands in the "could not verify" branch. The feature is complete but can
never run. Work item is *"make it a hard, self-testing prerequisite and treat
its absence as a verification failure"*, not *"add verification."*

### 0.2 [CONTRADICTS TASK] Defect #3 "red on success" — it is the (correct) NOT-verified path
The message the task quotes is verbatim the `verified is None` branch
(`card_manager.py:2115`), rendered amber (`program_sim_panel.py:779`). Given
§0.1, that branch fires on *every* card, so it reads as "red on every success."
It is not a mis-coloured success — it is an accurately-signalled **unverified**
card. Making verification actually run reaches the green `WRITE_OK_VERIFIED`
message. Under fail-closed (§2.1) the unverified branch becomes an explicit
**failure**, not an amber near-success.

### 0.3 [PARTIALLY CONTRADICTS TASK] Defect #2 delta — only bites on re-programming an already-written card
`program_card` (`card_manager.py:1823-1864`):
- blank gialersim (`empty_card=True`) → `changed = all non-empty fields` (full
  write — already correct);
- **non-empty gialersim** (already personalised) → `changed =
  _compute_changed_fields(delta)` **and `ICCID` is popped** (l.1830) → the
  partial dict fails `_program_gialersim_native`'s `required=(ICCID,IMSI,Ki,OPc)`
  check → `WRITE_FAILED` / under-write.

"Delta must not exist for gialersim" is correct; the fix targets the **non-empty
routing branch** specifically.

### 0.4 [CONTRADICTS TASK] A new monolithic lifecycle enum would violate the "holy" rules
Task proposes one enum `NO_CARD→…→VERIFIED/FAILED`. The repo already has two
documented, non-negotiable dimensions — `CardState` (presence/read) and
`ProgramOutcome` (result) — governed by `docs/reference/state-machine.md`
(Rules 6-8, Prohibition 4). A third combined enum duplicates and contradicts
both. **Recommendation: no new enum.** Compose the two existing dimensions and
add the one missing first-class concept — **card identity (`card_type`) as
single-sourced state with a `card_identified` event** (= the task's
"IDENTIFIED"). Programming/VERIFIED/FAILED already map onto `ProgramOutcome`.

### 0.5 [TENSION] SPN/FPLMN "shown must be written" vs. "don't change the APDU recipe"
Defect #2 wants everything shown written; the verified recipe writes no
SPN/FPLMN and the constraints forbid recipe changes. Resolved by the canonical
schema (§4): gialersim's schema excludes SPN/FPLMN/HNET_PUBKEY, so the GUI does
not show them for a gialersim card → "shown = written" holds with zero APDU
change. One decision to confirm (§8).

---

## 1. Where card-presence and card-type state live today

### Presence — 5 places, but already has a documented SSOT
| # | Location | Holds | Reset on removal? |
|---|----------|-------|-------------------|
| 1 | `StateManager.card_state` (`CardState`) | **documented SSOT** | yes → `NO_CARD` (main.py:639) |
| 2 | `CardWatcher._card_present` | PCSC ATR seen | yes |
| 3 | `CardManager._original_card_data` (`None`/`{}`/data) | detect sentinel | `None` only in `disconnect()` |
| 4 | `CardManager.card_info` (dict) | last read fields | on next detect |
| 5 | Panel `_step` / `_detected_non_empty` | local mirror | via `on_card_removed()` |

Presence is not the problem; identity is.

### Type/identity — 2 conflicting places (root of defect #1)
| Location | Type | Reset on removal? |
|----------|------|-------------------|
| `CardManager.card_type` (`CardType` enum) | authoritative today | **NO** — set `UNKNOWN` only at start of `detect_card` (l.942) and in `disconnect` (l.2939); `on_removed()` never touches it |
| `CardInfo.card_type` (display *string*, never `==` enum) | UI mirror | yes (`clear_card_info`) |

`_handle_suci_for_card_type` reads the **stale, not-reset-on-removal** enum via
`self._cm.card_type`, and is triggered by `card_info_changed`, which
`clear_card_info()` fires **on removal** — so a removed gialersim still reads as
`GIALERSIM`, and `on_card_removed()` re-checks the SUCI box, re-firing the
dialog. Exactly the "state derived in more than one place" the task describes.

### Named SSOT going forward
- **Presence/read:** `StateManager.card_state` (unchanged).
- **Identity:** promote to `StateManager.card_type: CardType` + `card_identified`
  signal, set/cleared in the one MainWindow watcher bridge. `CardManager.card_type`
  stays internal; **the UI stops reading it** and takes capabilities from
  StateManager only.
- **Programming result:** `ProgramOutcome` / `ProgramResult` (unchanged enum;
  gialersim handling amended per §2.1).

---

## 2. Card lifecycle as composition (no new enum)

Presence (`CardState`, unchanged): `NO_CARD → BLANK|DETECTED|NOT_POWERED|ERROR →
AUTHENTICATED → NO_CARD`.

Identity (new, additive): `card_type ∈ CardType`, driven by the same detect
events, cleared to `UNKNOWN` on removal. `UNKNOWN → <known>` fires
`card_identified(CardType)` once per insertion (= "IDENTIFIED").

Programming (`ProgramOutcome`, unchanged vocabulary): `IDLE → …`.

### 2.1 Verification is FAIL-CLOSED (new invariant)
There are exactly **three** terminal verification results for gialersim keys,
and only one is a success:

| Self-check | Meaning | Terminal state | Success? | Artifact | Colour |
|---|---|---|---|---|---|
| `True` (DB/DC) | MAC verified — keys committed | `WRITE_OK_VERIFIED` | **yes** | yes | green |
| `False` (9862) | keys wrong / did not commit | `WRITE_OK_VERIFICATION_FAILED` | no | no | red |
| `None` (no crypto / exception / skipped / self-test fail) | **could not verify** | **NOT-verified failure** (see §2.2) | **no** | no | red |

Rules:
- **"Could not verify" and "verification failed" are BOTH failure states, both
  distinct from VERIFIED.** Neither returns `ok=True`; neither is green; neither
  emits an artifact; neither shows a warning that could read as success.
- A missing crypto backend, any exception in the check, a failed Milenage
  self-test, or an un-runnable check all collapse to the **could-not-verify
  failure** — never a silent pass, never `WRITE_OK_PENDING`-as-success.
- `9000` on a key write is explicitly **not** evidence of anything.

### 2.2 [STATE-MACHINE.MD CONFLICT — must be resolved before coding]
`state-machine.md` currently classifies `WRITE_OK_PENDING` as a **success
state**: *"A success state (`WRITE_OK_VERIFIED` or `WRITE_OK_PENDING`) means all
intended writes completed without error."* Fail-closed (§2.1) says the
could-not-verify case is a **failure**. These conflict (Rule 8: stop and report
rather than silently pick one).

Reported and resolved deliberately, as a documented amendment (not a silent
override):

- **Keep `WRITE_OK_PENDING` meaning unchanged for the sysmocom/SJA5 paths**
  (e.g. SPN-only writes with no read-back) — it stays a non-failure amber there.
  Touching that would violate Rule 1 (Ubuntu baseline) — out of scope.
- **For gialersim key verification, introduce a dedicated terminal failure
  outcome** so "could not verify" is neither conflated with "keys wrong" nor
  with the SJA5 pending case. Proposed: add `ProgramOutcome.VERIFY_UNAVAILABLE`
  (name TBD) — writes completed, verification could not run, **treated as a
  failure** (no artifact, red, `ok=False`), with a message distinct from
  `WRITE_OK_VERIFICATION_FAILED`.
- **Amend `state-machine.md`** in the same commit: (a) add
  `VERIFY_UNAVAILABLE` to Programming Outcome States as a failure; (b) reword the
  "success state" sentence so `WRITE_OK_PENDING` is described as *unverified /
  not a clean success* rather than "success"; (c) update the UI/Artifact rules
  table (red, no artifact). This keeps the doc authoritative and consistent
  with fail-closed instead of contradicting it.

> If you prefer **not** to add an enum value, the fallback is to reuse
> `WRITE_OK_VERIFICATION_FAILED` for the could-not-verify case with a
> distinguishing message — simpler, but it loses the "distinct from failed"
> distinction you asked for. I recommend the new value. Flagged as a decision
> in §8.

---

## 3. pycryptodome is a hard prerequisite (not optional)

Verification cannot run without it, and per §2.1 its absence is a failure — so
it is treated as a required dependency with three enforcement points:

1. **Declared** — add `pycryptodome` to `requirements.txt` (and
   `requirements-dev.txt` for the test env); add to `debian/control` and both
   install scripts (`scripts/install.sh`, `scripts/install-macos.sh`).
2. **Bundled** — add `Cryptodome` (and its needed submodules) to
   `SimGUI.spec` `hiddenimports` so the PyInstaller build ships it; without this
   the source venv could pass while the packaged app silently loses the backend
   and every gialersim program becomes could-not-verify. A build-time smoke
   check (import in the frozen app) is added to catch regressions.
3. **Surfaced at startup, immediately** — a startup capability check calls
   `gialersim_selfcheck.selftest()` (which both imports the backend *and*
   validates the Milenage vectors). If it fails, the app surfaces a persistent,
   high-severity banner/dialog at launch — *"USIM AUTHENTICATE verification is
   unavailable (crypto backend missing/broken). Gialersim key programming
   cannot be verified."* — not deferred to first programming. Runs via the
   existing `QThread` startup-worker pattern (CLAUDE.md lesson: no blocking work
   on the event loop), emitting a signal the UI renders.
   - **Recommended hardening (decision in §8):** when the startup check fails,
     pre-gate gialersim programming (disable Program with a clear reason) so the
     app never writes keys it structurally cannot verify. Defence in depth on
     top of the per-program fail-closed outcome.

---

## 4. Canonical gialersim field schema (single definition)

New `card_profiles/field_schema.py`, beside `capabilities.py`, same
schema-driven pattern the panel already trusts:

```python
GIALERSIM_FIELDS = FieldSchema(
    written             = ("ICCID", "IMSI", "Ki", "OPc", "ACC"),
    hardcoded           = ("ADM1",),                       # fixed 84796153, greyed
    verify_readback     = ("ICCID", "IMSI"),
    verify_authenticate = ("Ki", "OPc"),
    excluded            = ("SPN", "FPLMN", "HNET_PUBKEY", "SUCI"),
)
fields_for(card_type) -> FieldSchema
```

Read by GUI (render/enable `written`, grey `hardcoded`, hide `excluded`),
programming (`_program_gialersim_native` write set = `written`, no delta), and
verification (read-back = `verify_readback`, AUTHENTICATE = `verify_authenticate`)
— one object, cannot drift. Non-gialersim types return today's behaviour;
**sysmocom/pySim paths unchanged.**

---

## 5. Modules: changed / new / untouched

**New**
- `card_profiles/field_schema.py` (§4).
- Session one-shot notice registry inside `state_manager.py` (§6).
- Tests: `test_gialersim_field_schema.py`, `test_gialersim_selfcheck.py`
  (True→VERIFIED, False→VERIFICATION_FAILED, None→VERIFY_UNAVAILABLE — assert
  **fail-closed**: none of False/None ever returns `ok=True` or green),
  `test_startup_crypto_check.py`, `test_suci_notice_once.py`.

**Changed**
- `requirements.txt`, `requirements-dev.txt`, `SimGUI.spec` (hiddenimports),
  `debian/control`, `scripts/install*.sh` — pycryptodome prerequisite (§3).
- `managers/card_manager.py` — (a) gialersim field set from schema, no delta,
  keep ICCID (§0.3); (b) fail-closed verification mapping incl. new
  `VERIFY_UNAVAILABLE` (§2.1-2.2); (c) tighten the three result messages
  (§0.2); (d) remove stale `TODO(gialersim-selfcheck)` comments.
- `state_manager.py` — `card_type: CardType` + `card_identified` signal; notice
  registry; add `ProgramOutcome.VERIFY_UNAVAILABLE`.
- `main.py` — startup crypto check via startup worker (§3.3); set/clear
  `state_manager.card_type` and emit `card_identified` in the watcher bridge.
- `widgets/program_sim_panel.py` — read caps/schema from StateManager not
  `cm.card_type`; SUCI-unsupported trigger → identity edge + registry; remove
  `HNET_PUBKEY` row from `_FORM_FIELDS`; hide `excluded` for gialersim;
  render VERIFY_UNAVAILABLE / VERIFICATION_FAILED as red failures (never amber
  near-success).
- Docs (same commit as the code): `state-machine.md` (identity dimension +
  `card_identified`; **fail-closed amendment + `VERIFY_UNAVAILABLE`** per §2.2),
  `GIALERSIM_PROGRAMMING.md` (self-check is implemented; crypto prerequisite;
  field schema; drop the TODO framing), `docs/reference/card-types.md`,
  `docs/TODO.md` (close selfcheck TODO), `version.py` + `debian/changelog`.

**Explicitly untouched (constraints)**
- `managers/gialersim.py` APDU recipe — not one byte.
- pySim-prog / pySim-shell paths, `_program_nonempty_card`,
  `_program_via_pysim_prog`, `card_watcher.py`, and the SJA5 meaning of
  `WRITE_OK_PENDING` — unchanged (Rules 1-5a, Prohibitions 1-7).

---

## 6. Migration order (small, reviewable commits; full pytest + Ubuntu 1900/0/313 after each)

1. **Crypto prerequisite + startup check.** requirements + `SimGUI.spec`
   hiddenimports + install scripts + build smoke check + startup `selftest()`
   banner (and optional pre-gate). No card-logic change yet. → makes
   verification *able* to run and its absence *loud*. Tests: startup check
   surfaces missing backend.
2. **Fail-closed verification + `VERIFY_UNAVAILABLE` + state-machine.md
   amendment.** Map True/False/None → VERIFIED / VERIFICATION_FAILED /
   VERIFY_UNAVAILABLE; None and False both `ok=False`, red, no artifact; tighten
   the three messages; amend the holy doc in the same commit. → resolves **#4**
   and **#3**. Tests assert no failure path is green/`ok=True`.
3. **Canonical field schema + no-delta gialersim.** `field_schema.py`; gialersim
   uses full `written` set, keeps ICCID, never `_compute_changed_fields`. →
   resolves **#2**. Tests: re-program of an already-personalised gialersim writes
   the full set incl. ICCID.
4. **GUI field set.** Remove `HNET_PUBKEY` row (→ **#5**, remains only under
   File → SUCI configuration); hide `excluded` fields for gialersim so
   "shown = written" holds. Tests: gialersim renders only schema fields.
5. **State single-sourcing + SUCI one-shot.** `StateManager.card_type` +
   `card_identified` + notice registry; panel reads caps from StateManager;
   SUCI-unsupported fires once per session on the identify edge, never on
   removal. → resolves **#1**. Tests: insert→remove→reinsert fires at most once;
   removal never fires.

Rationale: crypto/fail-closed first (highest-stakes correctness, the exact
"9000 meant nothing" bug), state single-sourcing last on a green baseline
(Rules 9-10).

---

## 7. How each defect is resolved

| Defect | Resolution |
|---|---|
| **#1 SUCI popup every insert + on removal** | Identity single-sourced in StateManager, cleared to `UNKNOWN` on removal (kills the stale-`GIALERSIM` read). Trigger moves off `card_info_changed` onto the `card_identified` edge, guarded by the session notice registry → at most once per session, insertion-only, never on removal. |
| **#2 Delta for gialersim** | Field set from the canonical schema (full `written`, ICCID kept), never `_compute_changed_fields`. Everything shown for a gialersim card is written every time. |
| **#3 Verbose red "success"** | It was the unverified path forced by #4. Verification running reaches the concise green VERIFIED message; under fail-closed the unverified/failed paths are unambiguously red failures, not amber near-successes. |
| **#4 Missing verification** | Already implemented; made a hard prerequisite (declared + bundled + startup-checked). **Fail-closed:** could-not-verify and verification-failed are both terminal failures distinct from VERIFIED — no silent pass, no artifact, `9000` proves nothing. |
| **#5 HNET_PUBKEY in main GUI** | Row removed from `_FORM_FIELDS`; editable only in File → SUCI configuration (its `settings_manager` source unchanged). |

---

## 8. Decisions to confirm before coding

1. **SPN/FPLMN (§0.5):** confirm gialersim does **not** show SPN/FPLMN (they are
   not in the verified recipe; writing them needs a forbidden APDU change). The
   alternative is a separate recipe-extension task.
2. **Could-not-verify outcome (§2.2):** confirm adding
   `ProgramOutcome.VERIFY_UNAVAILABLE` (recommended — keeps it distinct from
   "keys wrong") vs. reusing `WRITE_OK_VERIFICATION_FAILED` with a distinct
   message. Either way it is a red, no-artifact, `ok=False` failure.
3. **Pre-gate (§3.3):** confirm whether a failed startup crypto check should
   **disable gialersim programming** (recommended, strongest fail-closed) or
   only cause each attempt to terminate in `VERIFY_UNAVAILABLE`.
