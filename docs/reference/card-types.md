# Reference: Card types

SimGUI supports four card types (plus one legacy type), detected automatically by pySim-read. Understanding the differences matters for choosing the right data format and knowing which capabilities are available.

**Source of truth:** `managers/card_manager.py` — `CardType` enum; `managers/csv_manager.py` — `STANDARD_COLUMNS`; `utils/iccid_utils.py` — ICCID generation constants.

---

## Supported card types

| Card type | Enum value | Detection | SUCI support | ICCID length |
|---|---|---|---|---|
| sysmoISIM-SJA2 | `CardType.SJA2` | pySim-read auto-detection | No | 23 digits |
| sysmoISIM-SJA5 | `CardType.SJA5` | pySim-read auto-detection | Yes (firmware option) | 19 digits (SUCI) / 23 digits (non-SUCI) |
| GIALERSIM | `CardType.GIALERSIM` | pySim-read auto-detection (`gialersim`) | No | N/A (blank — written from CSV) |
| magicSIM | `CardType.MAGIC` | pySim-read auto-detection | No | 23 digits |
| sysmoISIM-SJS1 | *(legacy)* | sysmo-usim-tool only | No | 23 digits |

---

## SJA2 — sysmoISIM-SJA2

The SJA2 is a standard ISIM card without SUCI support. It is programmed via `sysmo_isim_sja2.py`.

**Use when:** You need a straightforward ISIM/USIM without 5G SUCI privacy features.

**ICCID:** 23 digits (factory-assigned). Format: `89{MCC_MNC}00{MSIN}{Luhn}` per Teleaura numbering standard.

**Supported fields:**
- IMSI, Ki, OPc, ADM1
- MNC_LENGTH, ALGO_2G, ALGO_3G, ALGO_4G5G
- HPLMN, FPLMN, SPN, LI, ACC

---

## SJA5 — sysmoISIM-SJA5

The SJA5 is the most capable card in the sysmocom range. With appropriate firmware, it supports SUCI (Subscription Concealed Identifier) as defined in 3GPP TS 33.501 for 5G network privacy.

**Use when:** You need 5G SUCI privacy, or you are deploying in a 5G SA network that requires SUCI.

**ICCID lengths:**

- **Non-SUCI SJA5 cards:** 23-digit ICCID (same structure as SJA2/SJS1)
- **SUCI-capable SJA5 cards:** 19-digit ICCID

The ICCID length difference is not a software setting — it is a hardware/firmware distinction. A 19-digit ICCID is a definitive indicator that the card was manufactured with SUCI firmware.

See [SUCI vs non-SUCI](../explanation/suci-vs-non-suci.md) for a full explanation of what SUCI changes.

**Supported fields:**
- All SJA2 fields, plus SUCI-specific keys (SUPI protection scheme, home network public key, home network key ID)

**Simulator:** The built-in SimGUI simulator loads 20 real sysmoISIM-SJA5 profiles, making SJA5 the default simulator card type.

---

## GIALERSIM — Blank/Unpersonalised Cards

GIALERSIM cards are blank (unpersonalised) Fiskarheden SIM cards that have not been programmed at the factory. They differ significantly from pre-programmed cards.

**Use when:** You are programming brand-new blank cards from scratch using data from a CSV file.

**Detection:** pySim-read auto-detects these cards and reports `Autodetected card type: gialersim`.

**Key differences from SJA5:**
- Uses CHV `0x0C` (not `0x0A`) — standard `VERIFY ADM1` fails with `6f00` and **consumes retry attempts**. After 3 failures the card is permanently blocked.
- Has no ICCID or IMSI from factory — these must be written from CSV.
- Default ADM1 is `88888888` (ASCII) / `3838383838383838` (hex).

**Programming:** Blank cards are programmed via `pySim-prog.py -t gialersim -a <ASCII_ADM1>`. Do NOT use `-t auto` for gialersim cards.

**Supported fields:** ICCID, IMSI, Ki, OPc, ADM1, ACC, SPN, FPLMN, MCC, MNC — all written from CSV.

---

## SJS1 — sysmoISIM-SJS1 (legacy)

The SJS1 is a Java Card-based ISIM. It is **not** in the current `CardType` enum — it is supported only via the legacy sysmo-usim-tool backend (`sysmo_isim_sjs1.py`).

**Use when:** Your deployment specifically requires a Java Card ISIM or your existing infrastructure was built around SJS1.

**ICCID:** 23 digits.

**Supported fields:** Similar to SJA2. Check the sysmo-usim-tool documentation for SJS1-specific constraints.

---

## Card type auto-detection

SimGUI does not require you to specify the card type manually. pySim-read (`pySim-read.py -p0`) is the primary detection method. SimGUI parses the `Autodetected card type:` line from pySim-read output to determine the card type.

Detected types include: `sysmoISIM-SJA2`, `sysmoISIM-SJA5`, `gialersim`, and others. The detected type is displayed in the card status panel.

For the legacy sysmo-usim-tool backend, detection tries each script in order: `sysmo_isim_sja2.py` → `sysmo_isim_sja5.py` → `sysmo_isim_sjs1.py`.

---

## Teleaura IMSI/ICCID numbering standard

SimGUI's `generate_imsi()` and `generate_iccid()` functions implement the Teleaura SIM PLMN Numbering Standard v2.0.

### IMSI structure (15 digits)

```
MCC + MNC(5) + SSSS(4) + T(1) + NNNNN(5)
```

| Segment | Length | Description |
|---|---|---|
| MCC + MNC | 5 digits | Mobile Country Code + Mobile Network Code |
| SSSS | 4 digits | Site ID from the Site Register |
| T | 1 digit | SIM type digit |
| NNNNN | 5 digits | Sequential card number within this site/type |

**SIM type digit (T):**

| Value | SIM type |
|---|---|
| `0` | USIM |
| `1` | USIM + SUCI |
| `2` | eSIM |
| `9` | Test/Dev |

### Site Register

| SSSS | Code | Country | Status |
|---|---|---|---|
| `0001` | `uk1` | United Kingdom | Active |
| `0002` | `se1` | Sweden | Active |
| `0003` | `se2` | Sweden (DR) | Active |
| `0004` | `au1` | Australia | Reserved |

### ICCID structure (20 digits)

```
89 + MCC_MNC(5) + 00 + MSIN(10) + Luhn(1)
```

The final digit is a Luhn check digit computed over the preceding 19 digits.

> **Note:** Factory-assigned ICCIDs may follow this numbering or a vendor-specific scheme. The `generate_iccid()` function is provided for **preview and sequence planning only** — it is not used during actual card programming. The physical ICCID is always read from the card itself.

---

## FPLMN defaults by country

The Forbidden PLMN list is set per the card's deployment country (determined by site):

| Country | FPLMN string |
|---|---|
| United Kingdom | `23415;23410;23420;23430` |
| Sweden | `24007;24024;24001;24008;24002` |

These defaults come from `utils/iccid_utils.py` — `FPLMN_BY_COUNTRY`. The FPLMN column in the CSV overrides these defaults when explicitly set.
