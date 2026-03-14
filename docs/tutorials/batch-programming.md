# Tutorial: Run a batch programming session

**Time required:** 20–40 minutes for a typical batch of 10–20 cards  
**Prerequisites:** You have completed [Program your first SIM card](first-card.md), have a CSV or `.eml` file with all card data, and have a set of physical SIM cards matching the data.

A batch session programs multiple cards sequentially. SimGUI waits for each card insertion, verifies it, programs it, saves its artifact, then waits for the next. You do not restart the session between cards.

---

## Step 1: Prepare your data file

Load the full card set before starting. Your CSV (or EML) must contain one row per card, with the ICCID column populated for every row — ICCID is used for automatic card matching as you insert each card.

1. In the **Batch Program** tab, select **Load CSV**.
2. Click **Browse** and select your data file.
3. Inspect the preview table. Every row should show a valid ICCID, IMSI, Ki, OPc, and ADM1.

To validate all rows before starting:

- Click **Validate All** (if present) or check the CSV Editor tab for any red-highlighted cells.
- Rows with missing or malformed Ki, OPc, or ADM1 will fail during programming. Fix them now.

<!-- screenshot: batch-panel-full-dataset-loaded -->

> **Tip:** If your order email had a different column ordering than expected, the EML parser is field-order independent. See [Import a sysmocom order email](../how-to/import-order-email.md).

---

## Step 2: Configure the batch range (optional)

If you do not want to program all rows — for example, you are picking up partway through an order, or you only received a subset of cards — use the **Range** controls:

- **Start row:** 1-based row number of the first card to program (default: 1).
- **Count:** number of cards to include.

These controls slice the data without modifying the file. For example, to program rows 6–10 of a 20-row file, set Start = 6, Count = 5.

---

## Step 3: Configure IMSI override (optional)

If your data file contains placeholder IMSIs and you need to apply a sequential IMSI assignment at programming time:

1. Check **Override IMSI**.
2. Enter the **IMSI base** — the first 10 digits (MCC + MNC + SSSS + T in the Teleaura numbering standard).
3. Set **Start sequence** — the 5-digit sequence number for the first card (default: 1).

SimGUI generates `{base}{seq:05d}` for each card in order. ICCIDs and all other fields remain untouched.

> **When to use this:** IMSI override is useful when ICCIDs are vendor-assigned (factory values) but IMSI assignment is managed internally per the [Teleaura SIM PLMN Numbering Standard](../reference/card-types.md).

---

## Step 4: Mount the network share (recommended)

Mounting a network share before starting ensures that:

1. SimGUI can read `standards.json` for canonical SPN and LI validation.
2. Auto-artifact CSVs are written to `auto-artifact/` on the share after each card.

See [Configure a network share](../how-to/network-share-setup.md) if you have not set this up yet. If no share is mounted, artifacts are not saved automatically and SPN/LI values are accepted without canonical validation.

---

## Step 5: Start the batch session

Click **Start Batch**. The panel transitions to the programming workflow:

1. The status shows **"Waiting for card..."**.
2. The progress bar reflects how many cards have been completed out of the total.
3. The log panel at the bottom records each operation with a timestamp.

<!-- screenshot: batch-waiting-for-card -->

---

## Step 6: Insert cards one at a time

For each card in your set:

1. **Insert the card** into the USB reader. Do not click anything — SimGUI detects the card automatically.
2. SimGUI reads the ICCID (no authentication needed for ICCID).
3. **ICCID cross-verification:** SimGUI matches the card's ICCID against the rows in your data. If no match is found, it logs "Unknown card: `<ICCID>`" and waits — do not insert a different card yet; remove the unknown card first.
4. When a match is found, SimGUI automatically:
   - Authenticates using the ADM1 from the matched data row.
   - Programs all fields from the row.
   - Saves a per-card artifact CSV to the network share.
   - Marks the row as complete.
5. The log shows `Card programmed successfully` and the row turns green.
6. **Remove the card** and insert the next one.

<!-- screenshot: batch-card-complete-row-green -->

> **Important:** Never insert a card whose ICCID is not in the loaded data while a batch is running. SimGUI will pause and wait rather than program an unknown card.

---

## Step 7: Handle errors mid-batch

If a card fails:

| Error | What happened | Action |
|---|---|---|
| ICCID mismatch | Card in reader doesn't match any data row | Remove card, check physical label vs. data |
| ADM1 authentication failed | ADM1 in data row is wrong or card locked | Do not retry — see [ADM1 security](../explanation/adm1-security.md) |
| Programming timeout | CLI tool did not respond in time | Re-insert card and retry |
| Artifact save failed | Network share unavailable | Check share mount, re-save from log |

Failed rows are marked red in the table. SimGUI continues to the next card — it does not abort the entire batch on a single card failure.

---

## Step 8: Complete the batch

When all cards are programmed, the status shows **"Batch complete"** and the summary panel shows total success and failure counts.

<!-- screenshot: batch-complete-summary -->

Check the `auto-artifact/` directory on your network share. You should find one CSV per successfully programmed card, named `{ICCID}_{YYYYMMDD_HHMMSS}.csv`. Each file contains:

- ICCID, IMSI, Ki, OPc, ADM1
- ACC, SPN, FPLMN
- PIN1, PUK1, PIN2, PUK2
- `programmed_at` ISO timestamp

These artifacts are immutable records. Keep them; they are your audit trail.

---

## Using the simulator for a dry run

Before running a batch against real hardware for the first time, use the built-in simulator:

1. Open **Settings** → enable **Simulator Mode**.
2. The simulator loads 20 real sysmoISIM-SJA5 profiles as virtual cards.
3. Run through the complete batch workflow — card detection, ICCID matching, programming, artifacts — without touching physical hardware.
4. Disable Simulator Mode before switching to real cards.

<!-- screenshot: simulator-mode-enabled -->

See [Architecture overview](../explanation/architecture.md) for how the simulator backend works.

---

## What's next?

- Review the [CSV format reference](../reference/csv-format.md) for every supported column.
- Set up [canonical SPN/LI values via standards.json](../how-to/standards-file.md) to prevent spelling inconsistencies across batches.
- For large deployments, read about [Auto-artifact storage](../explanation/architecture.md#auto-artifact-storage) to understand the audit trail design.
