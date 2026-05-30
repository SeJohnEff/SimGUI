# SimGUI Reader / Card State Machine

This document is the authoritative source of truth for how SimGUI tracks card reader
presence, physical card presence, and card read state. All widgets and managers must
follow these invariants. When in doubt, consult this document.

---

## Principles

1. **StateManager is the single source of truth.** No widget may infer hardware state
   from label text, ICCID presence, IMSI presence, or pySim exit codes.

2. **Reader presence, card presence, and card readability are separate concepts.**
   - The reader can be absent even if a "card info" is still cached in StateManager.
   - A card can be physically inserted even if pySim-read fails or returns no ICCID.
   - "Card content could not be fully read" is not the same as "card not inserted".

3. **Every tab subscribes to `StateManager` signals.** No tab polls, no tab reads
   state from another widget.

4. **Every tab also syncs from current `StateManager` state at construction time**,
   because signals may have fired before the tab existed (e.g., card detected before
   "Program SIM" tab was opened).

5. **`CardState.ERROR` does not mean "no card inserted".** It means "reader or PCSC
   communication error" — which may be transient, may be a no-reader condition, or
   may be a read error while the card is still present. Widgets must not equate ERROR
   with absent card.

6. **Only a confirmed card-removal event (`CardState.NO_CARD`) may demote the UI to
   "Insert a SIM card...".**

---

## State Dimensions

### ReaderState (logical, not yet an explicit enum)

| Value        | Meaning                                    |
|--------------|--------------------------------------------|
| DISCONNECTED | No reader hardware detected                |
| CONNECTED    | Reader hardware present                    |

### CardPresenceState (logical, not yet an explicit enum)

| Value    | Meaning                                               |
|----------|-------------------------------------------------------|
| UNKNOWN  | Reader connected but presence not yet confirmed       |
| ABSENT   | Reader connected, no card ATR detected                |
| INSERTED | PCSC probe returned a valid ATR — card is physically  |
|          | in the reader regardless of whether pySim-read works |

### CardReadState (logical, not yet an explicit enum)

| Value         | Meaning                                               |
|---------------|-------------------------------------------------------|
| NOT_ATTEMPTED | No read attempted yet                                 |
| READABLE      | pySim-read returned ICCID and/or IMSI                 |
| PARTIAL_READ  | pySim-read returned some fields but not ICCID/IMSI    |
|               | (e.g. blank gialersim: may return ACC but no ICCID)  |
| READ_ERROR    | pySim-read failed; card may still be physically present|

### CardType

See `docs/reference/card-types.md` for the full list. The key distinction for state
machine purposes:

| Type       | ICCID present | Uses CHV for auth |
|------------|---------------|-------------------|
| SJA5       | Yes           | 0x0A              |
| GIALERSIM  | No (blank)    | 0x0C (hardcoded)  |
| MAGIC      | Yes           | 0x0A              |
| UNKNOWN    | Unknown       | Unknown           |

---

## Current Implementation Mapping

SimGUI currently uses a single `CardState` enum (in `state_manager.py`) that combines
reader state, card presence, and read state into one dimension. Future work should
split these (see "Desired Future Signals" below), but the current code is documented
here for all maintainers.

```python
class CardState(Enum):
    NO_CARD       # Reader connected, no card inserted (confirmed by PCSC probe)
    DETECTED      # Card inserted, ICCID read successfully, not yet authenticated
    AUTHENTICATED # Card inserted, ADM1 verified
    ERROR         # Reader or PCSC communication error (may be transient)
    BLANK         # Card inserted but no ICCID (factory-blank / gialersim)
    NOT_POWERED   # Card physically inserted but not electrically powered; re-seat required
```

**NOT_POWERED canonical status text:** `"Card not powered - re-seat the SIM in the reader"`

Detected when pySim-read returns an error containing `"card not powered"` or `"re-seat the sim"`
(case-insensitive). The card is physically in the reader (PCSC returned an ATR) but pySim-read
cannot communicate with it electrically. The user must remove and re-seat the SIM.

On the next poll, `CardWatcher._last_read_failed=True` causes `_read_and_notify` to be retried
even when the ATR is unchanged (same-ATR re-seat). If the retry succeeds, the state transitions
to `BLANK` or `DETECTED`.

### Mapping to logical states

| CardState     | ReaderState | CardPresenceState | CardReadState  |
|---------------|-------------|-------------------|----------------|
| NO_CARD       | CONNECTED   | ABSENT            | NOT_ATTEMPTED  |
| DETECTED      | CONNECTED   | INSERTED          | READABLE       |
| AUTHENTICATED | CONNECTED   | INSERTED          | READABLE       |
| BLANK         | CONNECTED   | INSERTED          | PARTIAL_READ   |
| ERROR         | UNKNOWN*    | UNKNOWN*          | READ_ERROR*    |
| NOT_POWERED   | CONNECTED   | INSERTED          | READ_ERROR     |

\* ERROR is ambiguous — it conflates no-reader, reader hardware error, and transient
PCSC failure. Use the error message content to distinguish:
- Message contains `"No smart-card reader"` → reader physically absent
- Other messages → transient PCSC error; card may still be physically present

NOT_POWERED is unambiguous: the card is physically inserted (PCSC returned an ATR) but
pySim-read failed with a "not powered" error. It is distinct from ERROR because the card
presence is confirmed and the corrective action is known (re-seat).

---

## Invariants

These rules are non-negotiable. Violating them causes incorrect UI behaviour.

### Reader and card presence

- If `CardState in (BLANK, DETECTED, AUTHENTICATED, NOT_POWERED)` → card is physically
  inserted. Do NOT show "Insert a SIM card...".
- If `CardState == NO_CARD` → reader is connected but no card; show "Insert a SIM card...".
- If `CardState == ERROR` → unknown; preserve the last known card-present state if
  any was established in this session.
- If `CardState == NOT_POWERED` → card is physically inserted but not readable. Show the
  canonical status text `"Card not powered - re-seat the SIM in the reader"` from
  `StateManager.status_text`. Never show "Insert a SIM card..." for this state.

### ERROR handling

- `ERROR` must not automatically mean "no card inserted".
- A transient PCSC error while the watcher's `_card_present = True` (PCSC confirmed
  ATR before pySim-read finished) must NOT demote the UI to "Insert a SIM card...".
- `ERROR` may be set only if:
  1. The error message contains `"No smart-card reader"` (reader physically absent), OR
  2. No card has ever been physically confirmed present in this session
     (`_card_present == False` AND
     `card_state not in (BLANK, DETECTED, AUTHENTICATED, NOT_POWERED)`)
- When a widget receives `card_state_changed(ERROR)` and has previously established
  card-present state (`_step >= 1` or equivalent), it must preserve the card-present
  display rather than resetting to "Insert a SIM card...".
- A `"card not powered"` error always sets `NOT_POWERED`, never `ERROR`, regardless of
  prior state. `NOT_POWERED` is in the card-present guard so a subsequent generic PCSC
  error will not demote it to `ERROR`.

### Missing ICCID / IMSI

- Missing ICCID does NOT imply card absent. Blank gialersim cards have no ICCID.
- Missing IMSI does NOT imply card absent. Blank gialersim cards have no IMSI.
- ICCID and IMSI are not required for card-present state.
- `CardState.BLANK` represents card-inserted-but-unreadable-ICCID — it is a
  card-present state, not an absent state.

### Card removal

- Only a confirmed `CardState.NO_CARD` transition (from `on_card_removed()` callback,
  which requires two consecutive "No card in reader" PCSC probes for blank cards)
  may transition the UI to "Insert a SIM card...".
- A read error (`READ_ERROR`) is NOT a card removal.
- A transient PCSC error is NOT a card removal.

### Consistency across tabs

- All tabs subscribe to the same `card_state_changed` signal on the same StateManager.
- A transition to BLANK in one tab is a transition to BLANK in all tabs.
- No tab may locally track "has a card" state that diverges from StateManager.

---

## Signals

### Current signals

| Signal                    | Type        | Meaning                                      |
|---------------------------|-------------|----------------------------------------------|
| `card_state_changed`      | `CardState` | Card reader state changed                    |
| `card_info_changed`       | `CardInfo`  | ICCID, IMSI, card_type, or other info changed|
| `status_changed`          | `str`       | Status bar text update                       |
| `error_occurred`          | `str`       | Non-fatal error for toast/log display        |
| `share_status_changed`    | `ShareStatus`| Network share mount/unmount                 |

### Desired future signals (not yet implemented)

These would remove the ambiguity in `CardState.ERROR` and allow finer-grained UI
reactions. They should be added in a future refactor — the current fix must not
require them.

| Signal                    | Type                  | Meaning                              |
|---------------------------|-----------------------|--------------------------------------|
| `reader_state_changed`    | `ReaderState`         | Reader connected / disconnected      |
| `card_presence_changed`   | `CardPresenceState`   | Physical card inserted / removed     |
| `card_read_state_changed` | `CardReadState`       | pySim-read result (readable/partial/error)|

Until these signals exist, widgets must apply the invariants documented above when
handling `CardState.ERROR`.

---

## UI Mapping — Program SIM Tab

| Condition                                            | Status message                                          | Program Card |
|------------------------------------------------------|---------------------------------------------------------|--------------|
| No reader connected (`ERROR` from no-reader message) | "No card reader detected"                               | Disabled     |
| Reader connected, no card (`NO_CARD`)                | "Insert a SIM card..."                                  | Disabled     |
| Card inserted, no form data (`BLANK`/`DETECTED`)     | "Blank/Card detected — select data..."                  | Disabled     |
| Card inserted, form data present                     | "Card detected — ready to program"                      | **Enabled**  |
| `ERROR` with prior card presence (`_step >= 1`)      | Preserve last card-present message                      | Preserved    |
| `NOT_POWERED`                                        | "Card not powered - re-seat the SIM in the reader"      | Disabled     |

### Program Card enablement rule

Program Card is enabled when ALL of the following are true:
1. `card_state in (BLANK, DETECTED, AUTHENTICATED)` — card is physically inserted, OR
   `_step >= 1` — card presence was established before a transient error
2. At least one form field has data (IMSI, Ki, OPc, ADM1, etc.)

`NOT_POWERED` keeps the panel idle (`_step` does not advance). The status text comes
exclusively from `StateManager.status_text` via the `status_changed` signal — the panel
sets no local wording for this state.

ICCID and IMSI are NOT required. Blank cards have neither.

---

## State Transition Diagram

```mermaid
stateDiagram-v2
    [*] --> no_reader : app start, no reader

    no_reader : No Reader\n(ERROR / no-reader msg)
    no_card : No Card\n(NO_CARD)
    reading : Reading Card\n(PCSC ATR confirmed,\npySim-read running)
    blank : Blank Card\n(BLANK — no ICCID)
    detected : Card Detected\n(DETECTED — has ICCID)
    authenticated : Authenticated\n(AUTHENTICATED)
    transient_err : Transient Error\n(ERROR — card still present)
    not_powered : Not Powered\n(NOT_POWERED — card present\nbut not electrically powered)

    no_reader --> no_card : reader connected
    no_card --> no_reader : reader removed

    no_card --> reading : PCSC ATR detected
    reading --> blank : pySim-read: no ICCID\n(blank/gialersim)
    reading --> detected : pySim-read: ICCID found
    reading --> not_powered : pySim-read failed\n("not powered" error)
    reading --> transient_err : probe error during read\n(_card_present=True)

    transient_err --> reading : next probe succeeds\n(same ATR → skip re-read)
    transient_err --> no_card : two consecutive\n"No card" probes

    not_powered --> blank : re-seat + retry succeeds\n(no ICCID)
    not_powered --> detected : re-seat + retry succeeds\n(ICCID found)
    not_powered --> not_powered : retry still fails\n(still not powered)
    not_powered --> no_card : card removed

    blank --> authenticated : ADM1 provided\n(no VERIFY for blank)
    detected --> authenticated : ADM1 VERIFY success
    authenticated --> blank : session reset
    authenticated --> detected : session reset

    blank --> no_card : card removed\n(2× "No card" probe)
    detected --> no_card : card removed
    authenticated --> no_card : card removed

    no_card --> no_reader : reader disconnected
    blank --> no_reader : reader disconnected
    detected --> no_reader : reader disconnected
    authenticated --> no_reader : reader disconnected
    not_powered --> no_reader : reader disconnected
```

---

## Implementation Notes

### Why `_card_present` matters in `on_error`

`CardWatcher._card_present` is set to `True` synchronously when the PCSC probe
returns a valid ATR — before `_read_and_notify()` (pySim-read) starts. The StateManager
`card_state` is not updated to `BLANK` or `DETECTED` until pySim-read finishes and
`on_card_unknown()` or `on_card_detected()` fires.

During this window (ATR confirmed, pySim-read running), a concurrent PCSC probe
failure (e.g., from `_startup_detect_card` on the main thread) can fire `on_error`
with `current = NO_CARD`. The guard in `on_error` must check BOTH `card_state` AND
`_card_present` to prevent setting `CardState.ERROR` during this window.

### Why the panel guard matters

Even with the `on_error` guard, a race between the main thread's startup probe and
the background CardWatcher thread can still occasionally set `CardState.ERROR` before
`CardState.BLANK` is established. The panel-level guard (`_step >= 1`) ensures that
even if `ERROR` fires unexpectedly, the panel does not reset to "Insert a SIM card..."
if it has already established card-present state.

### Debounce for blank cards

Blank gialersim cards can cause a transient "No card in reader" PCSC response
immediately after pySim-read releases the reader. `CardWatcher` requires two
consecutive "No card in reader" probes before firing `on_card_removed()`. This
prevents spurious card-removal events for blank cards.

---

## Programming Outcome States (ProgramOutcome)

`ProgramOutcome` is a separate, independent dimension from `CardState`. It tracks the
result of a single programming attempt. It is set by `CardManager` at the end of each
programming operation and is exposed via `StateManager`. It does NOT drive card presence
or reader state.

### State Table

| State | Trigger / Meaning |
| --- | --- |
| `IDLE` | No programming attempt has been made this session, or the state was explicitly reset. |
| `NO_CHANGES` | All fields in the CSV row matched the card's current values. No writes were performed. |
| `ICCID_MISMATCH` | The ICCID read from the physical card does not match the ICCID in the CSV row. Operation was aborted before any write or ADM1 attempt. |
| `ADM1_LOCKED` | The ADM1 retry counter on the card reached zero before this session. No VERIFY attempted. |
| `ADM1_AUTH_FAILED` | A VERIFY command was sent and the card rejected it (wrong key). Counter decremented. |
| `WRITE_FAILED` | ADM1 auth succeeded (or was skipped for blank) but at least one field write failed. |
| `WRITE_OK_VERIFIED` | All written fields were read back and confirmed to match the intended values. |
| `WRITE_OK_PENDING` | Writes completed without error, but read-back verification was not performed or was inconclusive (e.g., SPN-only change where SPN read-back is not supported). |

### Required Distinctions

**`ICCID_MISMATCH` vs `ADM1_AUTH_FAILED`**

- `ICCID_MISMATCH`: the operation was aborted before any VERIFY or write. The ADM1 key was never used. The retry counter is unchanged.
- `ADM1_AUTH_FAILED`: the ICCID matched (or the card is blank), a VERIFY was attempted, and the card rejected it. The retry counter was decremented.

**`ADM1_AUTH_FAILED` vs `ADM1_LOCKED`**

- `ADM1_LOCKED`: the retry counter was already zero when the operation was attempted. No VERIFY was sent. The card is already in a permanently blocked state.
- `ADM1_AUTH_FAILED`: the retry counter was >0; a VERIFY was sent; the card rejected the key. The counter is now decremented by one.

**`WRITE_OK_VERIFIED` vs `WRITE_OK_PENDING`**

- `WRITE_OK_VERIFIED`: each written field was read back from the card and the value confirmed equal to the intended value. This is the only "clean success" state.
- `WRITE_OK_PENDING`: writes completed without a pySim-prog error, but at least one field could not be verified by read-back (e.g., SPN write on a card type that does not support SPN read-back via pySim-read). The programmer must treat this as unverified.

**No `WRITE_OK_PARTIAL`**

Any partial write failure (some fields written, some not) is `WRITE_FAILED`. There is no `WRITE_OK_PARTIAL` state. A success state (`WRITE_OK_VERIFIED` or `WRITE_OK_PENDING`) means all intended writes completed without error; a failure state means at least one did not.

### Outcome Metadata

Each `ProgramOutcome` may carry a metadata dict with four field-set lists:

| Key | Type | Meaning |
| --- | --- | --- |
| `verified_fields` | `list[str]` | Fields written and confirmed by read-back (contributes to WRITE_OK_VERIFIED) |
| `written_only_fields` | `list[str]` | Fields written but not verified (contributes to WRITE_OK_PENDING) |
| `skipped_fields` | `list[str]` | Fields where CSV value matched the card — no write needed |
| `failed_fields` | `list[str]` | Fields where the write was attempted but failed |

For non-write outcomes (`IDLE`, `NO_CHANGES`, `ICCID_MISMATCH`, `ADM1_LOCKED`,
`ADM1_AUTH_FAILED`) all four lists are empty.

### UI and Artifact Rules

| Outcome | UI colour | Artifact export allowed |
| --- | --- | --- |
| `WRITE_OK_VERIFIED` | Green | Yes |
| `WRITE_OK_PENDING` | Amber | No |
| `NO_CHANGES` | Neutral | No |
| `WRITE_FAILED` | Red | No |
| `ADM1_AUTH_FAILED` | Red | No |
| `ADM1_LOCKED` | Red | No |
| `ICCID_MISMATCH` | Red | No |
| `IDLE` | — (hidden) | No |

Artifacts (per-card export files) may only be produced when `WRITE_OK_VERIFIED` is the
final outcome. Any other outcome, including `WRITE_OK_PENDING`, must suppress artifact
generation.
