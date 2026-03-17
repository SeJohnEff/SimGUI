# Explanation: SUCI vs non-SUCI cards

SimGUI handles two broad categories of sysmocom SIM cards: those with SUCI support (specifically SUCI-capable SJA5 variants) and those without (SJA2, SJS1, and non-SUCI SJA5). This document explains what SUCI is, how the two categories differ, and what the practical differences mean when programming cards with SimGUI.

---

## What is SUCI?

SUCI stands for **Subscription Concealed Identifier**. It is a 5G privacy feature defined in 3GPP TS 33.501.

In 4G and earlier networks, a device identifies itself to the network using the IMSI (International Mobile Subscriber Identity) in plaintext — visible to anyone monitoring the radio interface. This allows for IMSI catchers (fake base stations) to track subscribers.

5G SA (Standalone) networks address this with SUCI: instead of broadcasting the IMSI, the device encrypts the subscriber identity using the home network's public key before transmitting it. Only the home network can decrypt the SUCI to recover the IMSI. An attacker observing the radio interface sees only a one-time, unlinkable encrypted token.

SUCI is implemented on the SIM card itself. The private key computation and the home network public key are both stored in the SIM, not the device.

---

## ICCID length

All Teleaura cards — both SUCI and non-SUCI — use **19-digit ICCIDs**, conforming to ITU-T E.118 (max 19 visible characters).

| Card category | ICCID length | Example |
|---|---|---|
| Non-SUCI (SJA2, SJS1, SJA5 standard) | **19 digits** | `8999988000100000018` |
| SUCI-capable (SJA5 SUCI variant) | **19 digits** | `8999988000110000017` |

The ICCID format follows the Teleaura SIM PLMN Numbering Standard:

```
89(2) + CCC(3) + II(2) + SSSS(4) + T(1) + NNNNNN(6) + L(1) = 19 digits
```

SUCI and non-SUCI cards are distinguished by the **T digit** (SIM type) in the ICCID/IMSI, not by ICCID length. `T=0` is standard USIM, `T=1` is SUCI-capable.

---

## What changes when programming SUCI cards

### Extra fields

SUCI-capable SJA5 cards carry additional EFs (Elementary Files) not present on SJA2/SJS1:

| Field | Purpose |
|---|---|
| Home Network Public Key | The operator's public key used for SUCI encryption; typically 32 or 65 bytes (curve-dependent) |
| Home Network Key Identifier | 1-byte ID matching the key to the network's key management system |
| SUPI Protection Scheme | Identifies the encryption scheme (Profile A = X25519, Profile B = NIST P-256, or null-scheme for testing) |

These are programmed via sysmo-usim-tool's SJA5-specific script. They are **additional** fields on top of the standard IMSI, Ki, OPc, ADM1 set.

### CSV columns for SUCI

When programming SUCI cards from a CSV, additional columns may be present:

| Column | Description |
|---|---|
| `HNPUBKEY` | Home network public key (hex string) |
| `HNKEY_ID` | Home network key identifier (1–2 hex chars) |
| `SUCI_SCHEME` | Protection scheme identifier (`0` = null, `1` = Profile A, `2` = Profile B) |

Standard columns (ICCID, IMSI, Ki, OPc, ADM1, SPN, LI, etc.) are unchanged.

---

## IMSI SIM type digit

The Teleaura SIM PLMN Numbering Standard v2.0 uses the `T` digit (position 10 in the IMSI) to distinguish card types:

| T value | SIM type |
|---|---|
| `0` | USIM (standard, non-SUCI) |
| `1` | USIM + SUCI |
| `2` | eSIM |
| `9` | Test/Dev |

A card with `T=1` in its IMSI is intended for a SUCI deployment. A card with `T=0` is standard USIM. This encoding is assigned during IMSI planning and can be seen in the IMSI column of the CSV.

---

## What stays the same

The programming workflow in SimGUI is identical for both card types:

- ICCID is read from hardware, never entered or edited
- ADM1 authentication uses the same mechanism
- ICCID cross-verification runs before every authentication
- Auto-artifacts are saved per card with the same format
- Batch programming proceeds card-by-card in the same way
- The CLI tool (sysmo-usim-tool) handles both types — only the script differs (`sysmo_isim_sja5.py` for SJA5 regardless of SUCI capability)

---

## Mixed batches

A CSV batch can contain a mix of SUCI and non-SUCI cards. SimGUI identifies the card type from the card reader's response when each card is inserted. The T digit in the ICCID/IMSI distinguishes SUCI from non-SUCI cards.

**Important:** Do not mix SUCI and non-SUCI rows in a batch if the programming tools for each type differ. sysmo-usim-tool's `sysmo_isim_sja5.py` handles both SJA5 variants; `sysmo_isim_sja2.py` handles SJA2 only. CardManager auto-detects the type per card, so mixed batches work correctly in software — but verify that the data file's columns are correct for each card's type.

---

## In the simulator

The built-in simulator uses sysmoISIM-SJA5 profiles (19-digit ICCIDs). The simulator does not currently simulate SUCI-specific EFs. For SUCI field testing, use physical hardware.

---

## Summary

| Property | Non-SUCI | SUCI (SJA5) |
|---|---|---|
| ICCID length | 19 digits | 19 digits |
| Card type | SJA2, SJS1, SJA5 (standard) | SJA5 (SUCI firmware) |
| CLI script | `sysmo_isim_sja2.py` / `sysmo_isim_sja5.py` / `sysmo_isim_sjs1.py` | `sysmo_isim_sja5.py` |
| Extra CSV fields | None | `HNPUBKEY`, `HNKEY_ID`, `SUCI_SCHEME` |
| IMSI T digit | `0` (USIM) | `1` (USIM+SUCI) |
| 5G SUCI privacy | No | Yes |
| Programming workflow | Standard | Standard + extra fields |
| SimGUI simulator | Yes (SJA5 profiles used) | No (SUCI EFs not simulated) |
