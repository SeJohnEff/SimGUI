# How to: Import a sysmocom order confirmation email

sysmocom order confirmation emails contain a table of SIM card data (ICCID, IMSI, Ki, OPc, ADM1, and related fields). SimGUI can parse these emails directly from `.eml` files, eliminating manual copy-paste and reducing transcription errors.

**Supported format:** sysmocom order confirmation emails exported as `.eml` from an email client. The parser is field-order independent — column positions in the email table do not matter.

**Source of truth:** `utils/eml_parser.py` — `parse_eml_file()`

---

## Prerequisites

- A sysmocom order confirmation email in your inbox
- An email client capable of exporting `.eml` format (Thunderbird, Outlook, Apple Mail, Gmail via browser)
- SimGUI installed

---

## Step 1: Export the email as .eml

### Thunderbird

1. Open the order confirmation email.
2. **File → Save As** (or right-click the message → **Save As**).
3. Choose format **EML (*.eml)**.
4. Save to a known location (e.g. `~/Downloads/sysmocom-order-12345.eml`).

### Outlook (Windows)

1. Open the email.
2. **File → Save As**.
3. Set file type to **Outlook Message Format - Unicode (.msg)** — note that `.msg` is **not** the same as `.eml`.
4. Alternatively: drag the email from Outlook to a Windows Explorer folder, which saves it as `.msg`. You may need to convert `.msg` to `.eml` using a tool such as `msgconvert` (Linux) or an online converter.

For Outlook, the most reliable method is to forward the email to a Thunderbird account and export from there.

### Gmail (browser)

1. Open the email.
2. Click the three-dot menu (⋮) at the top right of the message.
3. Select **Download message**.
4. Gmail saves as a `.eml` file directly.

### Apple Mail

1. Select the email.
2. **File → Save As** → format: **Raw Message Source**.
3. Rename the saved file to have a `.eml` extension if needed.

---

## Step 2: Load the .eml file in SimGUI

1. In the **Batch Program** tab, select **Load CSV**.
2. Click **Browse**.
3. In the file dialog, change the filter to **Email Files (*.eml)** or **SIM Data Files (*.csv *.eml *.txt)**.
4. Navigate to your `.eml` file and click **Open**.

SimGUI passes the file to `eml_parser.parse_eml_file()`, which:

1. Decodes the email's MIME structure (handles Base64 and quoted-printable encoding).
2. Locates the card data table in the email body — typically an HTML or plain-text table.
3. Extracts rows and normalises column names to SimGUI's internal standard:

   | Email column | Internal name |
   |---|---|
   | `ADM` | `ADM1` |
   | `KI` | `Ki` |
   | `OPC` | `OPc` |
   | Others | Uppercased |

4. Populates the preview table with one row per card.

<!-- screenshot: eml-import-preview-table -->

---

## Step 3: Verify the loaded data

After import, check:

- **Row count** matches the number of cards in your order.
- **ICCID** column is fully populated (all card types: 19 digits per ITU-T E.118).
- **ADM1** is present (8 decimal digits or 16 hex characters). ADM1 is critical — without it authentication cannot proceed.
- **Ki** and **OPc** are 32 hex characters each.

If any columns are empty or malformed, there may be a formatting issue in the email. See [Troubleshooting](#troubleshooting) below.

---

## Step 4: Proceed with programming

Once the data looks correct, follow either:

- [Program your first SIM card](../tutorials/first-card.md) for a single card
- [Run a batch programming session](../tutorials/batch-programming.md) for the full set

---

## What metadata does the parser extract?

In addition to the card table, `eml_parser.parse_eml_file()` returns a `meta` dict with:

- `subject` — email subject line (typically the order number)
- `date` — email date header
- `from` — sender address
- `order_id` — extracted order number if present in subject or body

This metadata is available to SimGUI for logging but is not programmed onto the card.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| File dialog shows no `.eml` files | Filter set to CSV only | Change filter to "Email Files" or "All files" |
| `ValueError: Could not parse EML file` | Email format not recognised | Try re-exporting; check the email is the sysmocom card delivery format |
| Row count is wrong | Parser picked up a secondary table | Open the `.eml` in a text editor and check for multiple tables; report as a bug |
| ADM1 column missing | sysmocom email did not include ADM1 (separate delivery) | Load the ADM1-containing file separately, then merge via CSV Editor |
| Ki/OPc shows garbled characters | Email encoding issue | Try re-exporting with UTF-8 encoding; avoid forwarding the email before export (can corrupt encoding) |
| ICCID is not 19 digits | Legacy or non-standard batch | All ICCIDs must be 19 digits per ITU-T E.118; check [card types reference](../reference/card-types.md) |

---

## Supported email formats

The EML parser handles sysmocom's standard order confirmation format. Other SIM vendors' emails are not guaranteed to parse correctly. If you receive card data in a different format, convert it to CSV manually and use the standard CSV import instead (see [CSV format reference](../reference/csv-format.md)).
