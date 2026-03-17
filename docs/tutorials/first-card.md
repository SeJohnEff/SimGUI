# Tutorial: Program your first SIM card

**Time required:** 10–15 minutes  
**Prerequisites:** SimGUI installed ([Installation guide](../how-to/install.md)), a USB PCSC reader connected, a sysmocom SIM card (pre-programmed or blank), and a card data CSV or `.eml` file. pySim is installed automatically by the install script.

This tutorial walks through a complete single-card programming workflow from loading data to verifying the result. By the end you will have programmed a physical SIM card and understand the key steps SimGUI performs on your behalf.

---

## Step 1: Launch SimGUI

Open a terminal and run:

```bash
simgui
```

Or find SimGUI in your application launcher under the Utilities category.

<!-- screenshot: main-window-on-launch -->

The main window opens with several tabs across the top: **Batch Program**, **Read SIM**, **CSV Editor**, and **Settings**. For this tutorial you will primarily use the **Batch Program** tab (it handles single-card programming too) and **Read SIM**.

---

## Step 2: Connect a card reader

Plug in your USB PCSC reader before inserting any card. SimGUI uses pySim to communicate with the reader — no SimGUI action is needed to register the reader. pySim is installed automatically at `/opt/pysim` by the install script. If a CLI tool warning appears in the status bar, see the [CLI integration guide](../reference/cli-integration.md).

---

## Step 3: Load card data

You have two options for supplying card data:

**Option A — Load a CSV file**

1. In the **Batch Program** tab, select the **Load CSV** radio button.
2. Click **Browse** and navigate to your `.csv` file (or `.txt` whitespace-delimited file).
3. The preview table populates with one row per card.

<!-- screenshot: batch-panel-csv-loaded -->

**Option B — Import a sysmocom order email**

1. Select the **Load CSV** radio button.
2. Click **Browse** and select an `.eml` file exported from your email client.
3. SimGUI's EML parser extracts the card table from the order confirmation email automatically, normalising field names to internal standard (`ADM` → `ADM1`, `KI` → `Ki`, etc.).

See [Import a sysmocom order email](../how-to/import-order-email.md) for export instructions.

**Expected outcome:** The preview table shows your card data. For pre-programmed cards, confirm the ICCID column is populated — this is required for ICCID cross-verification in the next steps.

> **Blank cards:** If you have a blank (unpersonalised/gialersim) card, load your CSV data first — blank cards have no ICCID from factory, so all fields including ICCID are written from the CSV. Blank cards are matched sequentially, not by ICCID.

---

## Step 4: Insert the card

Insert your SIM card into the USB reader now. SimGUI polls the reader automatically every 1.5 seconds via the **CardWatcher** background thread — there is no "Detect" button to click.

Within about two seconds you will see a status change:

- If the card's ICCID matches a row in the loaded CSV, the matching row is highlighted automatically.
- If the card is not in the loaded data, the status bar shows "Unknown card: `<ICCID>`".

<!-- screenshot: card-detected-row-highlighted -->

> **Why is card detection automatic?**  
> See [Architecture overview](../explanation/architecture.md) for how CardWatcher works.

---

## Step 5: Review the card row

With the card detected and a row highlighted, confirm the following in the preview table before proceeding:

| Field | What to check |
|---|---|
| ICCID | Matches what is printed on the physical card |
| IMSI | 15-digit number matching your order |
| Ki | 32 hex characters |
| OPc | 32 hex characters |
| ADM1 | 8 decimal digits or 16 hex characters (from vendor file) |

The ICCID field is always read-only in SimGUI — it is factory-assigned and used for traceability. See [Why ICCID is read-only](../explanation/iccid-traceability.md) for the design rationale.

ADM1 is sourced from your card data file, not typed manually. If ADM1 is missing or malformed, the row will fail validation and programming will be blocked.

---

## Step 6: Program the card

1. Ensure only the card whose row is selected/highlighted is in the reader.
2. Click **Start Batch** (or **Program Selected**).
3. SimGUI performs ICCID cross-verification: it reads the ICCID from the physical card and compares it to the ICCID in the selected data row. If they do not match, programming is aborted immediately to prevent ADM1 authentication against the wrong card.
4. Authentication proceeds automatically using the ADM1 from the data row.
5. The card is programmed field-by-field: IMSI, Ki, OPc, algorithms, HPLMN, SPN, LI, FPLMN, and other available fields.
6. A progress bar and log panel show each step in real time.

<!-- screenshot: programming-in-progress -->

**Expected outcome:** The log shows `Card programmed successfully` and the row is marked green (or a checkmark). If any step fails, a red error appears with a description.

---

## Step 7: Verify the result

After programming, switch to the **Read SIM** tab with the card still in the reader:

1. Click **Read Card**.
2. The read output shows the card's current ICCID, IMSI, and other public fields.
3. After authenticating again with ADM1, protected fields (Ki, OPc) are displayed.

Compare the read-back values against your data row. They should match exactly.

<!-- screenshot: read-sim-result -->

---

## Step 8: Remove the card and check artifacts

Remove the card from the reader. CardWatcher detects the removal and clears the active card state.

If a network share was mounted (see [Configure a network share](../how-to/network-share-setup.md)), SimGUI automatically saved a per-card artifact CSV to the `auto-artifact/` directory on the share immediately after successful programming. Each artifact is named `{ICCID}_{YYYYMMDD_HHMMSS}.csv` and contains ICCID, IMSI, Ki, OPc, ADM1, ACC, SPN, FPLMN, PIN/PUK codes, and a `programmed_at` timestamp.

---

## What's next?

- To program a set of cards back-to-back without restarting, follow [Run a batch programming session](batch-programming.md).
- To understand the CSV column format in detail, see the [CSV format reference](../reference/csv-format.md).
- To set up a shared network drive for your team's card data, see [Configure a network share](../how-to/network-share-setup.md).
