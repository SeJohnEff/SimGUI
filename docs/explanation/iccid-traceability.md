# Explanation: Why ICCID is read-only

The ICCID field in SimGUI is always read-only. You cannot type into it, paste a value, or edit it through any UI control. This is a deliberate design decision rooted in how ICCIDs work at the hardware level and why they matter for audit traceability.

---

## What is an ICCID?

ICCID stands for Integrated Circuit Card Identifier. It is a globally unique identifier, up to 19 characters (per ITU-T E.118), printed on the physical SIM card and stored in a dedicated elementary file (EF.ICCID) on the card's chip. It is defined by ITU-T E.118 and 3GPP TS 31.102.

The ICCID is assigned during SIM card manufacturing — it is part of the card's identity before any programming takes place. Unlike IMSI, Ki, OPc, and most other SIM fields, the ICCID is **not intended to be reprogrammed in the field**. Some card types technically allow it, but doing so breaks the traceability chain described below.

---

## Why SimGUI does not allow editing the ICCID

### 1. The ICCID is a physical identifier

When sysmocom (or any SIM manufacturer) ships cards, the ICCID is:

- Laser-etched or printed on the card body
- Included in the order confirmation email
- Embedded in the chip at manufacturing time

These three sources are intended to agree. If SimGUI let you edit the ICCID in a data row and then program it to a different card, you would have a card whose programmed ICCID no longer matches what is printed on it or recorded in the order. Physical inspection and the programming records would diverge — a traceability failure.

### 2. Cross-verification requires a stable reference

SimGUI's ICCID cross-verification safety feature reads the ICCID from the physical card before ADM1 authentication and compares it to the ICCID in the selected data row. This prevents authenticating a card with the wrong ADM1 key, which could lock the card permanently.

This protection only works if the ICCID in the data row is the factory-assigned value, not an operator-modified one. If users could freely edit the ICCID column, they might accidentally put the wrong value there and the cross-check would pass with a mismatch uncaught.

### 3. ICCID is the audit key

The auto-artifact system names every programming record after the ICCID:

```
{ICCID}_{YYYYMMDD_HHMMSS}.csv
```

The ICCID is the primary key that links:

- The physical card (printed label)
- The vendor order data (sysmocom email)
- The programming record (auto-artifact CSV)
- Any future read-back or SIM replacement request

If the ICCID were editable and someone entered a typo, all three links would break. Audit queries like "show me all programming records for ICCID 8988211812345678901" would fail silently.

### 4. Re-reading, not re-entry

SimGUI reads the ICCID directly from the physical card via the CLI tool during card detection. The value in the UI is therefore sourced from hardware — it is what the card says it is, not what an operator typed. There is no benefit to allowing manual override.

---

## The ICCID in the data file

CSV and EML data files contain an ICCID column. This is the **expected** ICCID for each card, sourced from the sysmocom order. SimGUI uses it for:

1. **ICCID cross-verification:** Comparing the data file's ICCID to the card's actual ICCID before ADM1 authentication.
2. **Auto-matching:** When a card is inserted, CardWatcher looks up its ICCID in the data set to find the matching row automatically.

This column is populated from the vendor-supplied data and should never need to be edited manually. If a card's actual ICCID does not match the data file, the most likely explanations are:

- Wrong card in the reader
- Wrong data file loaded
- The data file row was accidentally edited

In all cases, the resolution is to match the correct physical card to the correct data row — not to edit the ICCID field.

---

## SUCI cards and ICCID length

All Teleaura cards use **19-digit ICCIDs**, conforming to ITU-T E.118 (max 19 visible characters). This applies to both SUCI and non-SUCI cards. The ICCID format is:

```
89(2) + CCC(3) + II(2) + SSSS(4) + T(1) + NNNNNN(6) + L(1) = 19 digits
```

The ICCID length is factory-assigned by sysmocom. SimGUI reads the ICCID from the card reader and treats it as an immutable property of that card.

See [SUCI vs non-SUCI cards](suci-vs-non-suci.md) for the full comparison.

---

## Summary

| Reason | Implication |
|---|---|
| ICCID is factory-assigned | Editing it breaks the physical/digital record agreement |
| Used as cross-verification reference | Must be stable to prevent false-positive safety bypasses |
| Primary audit key | Must be reliably sourced from hardware, not user input |
| Read from hardware | Re-entry adds no value; errors become impossible |
