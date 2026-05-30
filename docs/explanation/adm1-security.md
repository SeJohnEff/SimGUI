# Explanation: ADM1 security and ICCID cross-verification

ADM1 (Administrative Code 1) is the master authentication key for a SIM card. It grants full read/write access to all card fields — IMSI, Ki, OPc, algorithms, SPN, and everything else. This document explains what ADM1 is, why it is handled the way it is in SimGUI, and why ICCID cross-verification exists as a guard against one of the most costly mistakes possible in SIM card operations.

---

## What is ADM1?

ADM1 is a PIN-like secret stored in the SIM card's file system under access conditions that restrict write access to critical files. Only a party that presents the correct ADM1 to the card is permitted to reprogram those files.

For sysmocom cards:
- The ADM1 is set at manufacturing time by sysmocom.
- It is delivered to the card buyer as part of the order confirmation data.
- It is a **one-per-card value** — every card in a batch has a unique ADM1.
- It is either 8 decimal digits (`12345678`) or 16 hex characters (`4142434445464748`), depending on the card model.

---

## ADM1 sources and session binding

ADM1 may come from the loaded CSV or EML data file, manual UI entry, or other supported sources. Regardless of source, ADM1 use in SimGUI is session-bound and always guarded by ICCID cross-verification before any VERIFY attempt that could consume authentication retries. This design prevents one of the most costly mistakes possible in SIM card operations: presenting the wrong ADM1 to a card.

---

## Authentication attempt limits

SIM cards track ADM1 authentication attempts. Most sysmocom cards allow between 3 and 10 wrong attempts before permanently locking. A locked card cannot be reprogrammed.

There is no way to reset the attempt counter without the original manufacturer's assistance, and even then it may not be possible. A locked card is effectively scrap.

This makes ADM1 authentication one of the few genuinely irreversible operations in SIM card management. It is not like a file that can be overwritten — once the attempt counter reaches zero, nothing can be done.

---

## ICCID cross-verification

### The problem it solves

Imagine a batch programming session with 20 cards and 20 data rows. The operator programs card 1 (ICCID ending in ...001) successfully. They remove it and pick up the next card. Without looking carefully at the physical label, they insert a card from a different batch — say, one ending in ...015.

SimGUI selects data row 2 (ICCID ...002) and attempts authentication with ADM1 from row 2. The card in the reader is ...015, which has a completely different ADM1. Authentication fails, consuming one attempt on card ...015.

If this happens three times in sequence, card ...015 is permanently locked.

### How cross-verification prevents this

Before presenting ADM1 to the card, SimGUI reads the ICCID from the physical card (ICCID can be read without authentication) and compares it to the ICCID in the data row being used:

```python
# From managers/card_manager.py
if expected_iccid is not None:
    card_iccid = self.read_iccid()
    if card_iccid and card_iccid != expected_iccid:
        return False, (
            f"ICCID mismatch! Card ICCID: {card_iccid} does not match "
            f"expected: {expected_iccid}. Wrong card or wrong data row. "
            f"Authentication aborted to prevent card lockout."
        )
```

If the ICCIDs disagree, authentication is **aborted immediately** — no ADM1 is presented to the card. The wrong card suffers no attempt count decrement. The operator is shown a clear error identifying both the expected and actual ICCIDs.

### When cross-verification fires

Cross-verification runs:

- Before every ADM1 authentication in the batch programming flow.
- Before authentication in single-card programming.
- Always, unless no expected ICCID is available (e.g. programming without a loaded data file — which SimGUI prevents anyway).

### Why this cannot be "just a warning"

Some systems implement checks like this as warnings that can be bypassed with a confirmation click. SimGUI does not. The cost of a wrong authentication is too high (permanent lock) and the bypass is never the right action — if the ICCIDs disagree, the correct response is always to fix the situation (insert the right card), not to proceed.

---

## Remaining attempt tracking

SimGUI reads the remaining ADM1 authentication attempts from the card after each authentication attempt (via `get_remaining_attempts()` when available from the CLI tool). The attempt count is an active safety gate: when the count reaches or falls below the safe threshold, SimGUI may hard-abort a programming attempt to prevent permanent card lockout.

The ICCID cross-check is the primary guard — it prevents wrong-card authentication, which is the dominant cause of accidental lockout. The remaining attempt count is a secondary but active safety layer that halts operations before the card can be permanently locked.

---

## Summary

| Design decision | Reason |
|---|---|
| ADM1 comes from data file, not manual entry | Eliminates transcription errors; keeps audit trail complete |
| ICCID cross-check is non-bypassable | Wrong-card auth is the top lockout risk; bypassing is never correct |
| Abort, not warn, on mismatch | Card lock is permanent; the cost of a false negative vastly exceeds the cost of a false positive |
| Attempt count displayed | Operational awareness; secondary indicator after cross-check |
