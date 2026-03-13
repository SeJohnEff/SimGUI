"""
EML Parser — Extract SIM card provisioning data from sysmocom emails.

sysmocom sends SIM card credentials in a plain-text email with a
specific structure:

    1. Header block (order info, manual link, card type)
    2. Field names — one per line (IMSI, ICCID, ACC, ...)
    3. Card values — N values per card, repeating for each card
    4. Signature block (``--``)

This module parses that format into a list of dicts suitable for
the CSV editor and batch programming panels.

It handles:
- ``.eml`` files (RFC 5322) — extracts the text/plain MIME part
- Forwarded emails (the data may be in the forwarded body)
- Attached ``.csv`` files inside the email
- **Field order independence** — fields can appear in any order
"""

import csv
import email
import email.policy
import io
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Known sysmocom field names (canonical casing)
_SYSMOCOM_FIELDS = {
    "IMSI", "ICCID", "ACC", "PIN1", "PUK1", "PIN2", "PUK2",
    "Ki", "OPC", "ADM1",
    "KIC1", "KID1", "KIK1",
    "KIC2", "KID2", "KIK2",
    "KIC3", "KID3", "KIK3",
}

# Case-insensitive lookup → canonical name
_FIELD_LOOKUP: dict[str, str] = {f.upper(): f for f in _SYSMOCOM_FIELDS}

# Minimum number of recognised field names to consider a block a header
_MIN_HEADER_FIELDS = 5


def _normalise_field_name(name: str) -> Optional[str]:
    """Return canonical field name or None if not recognised."""
    return _FIELD_LOOKUP.get(name.strip().upper())


def parse_eml_file(path: str) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Parse an ``.eml`` file and return SIM card data.

    Parameters
    ----------
    path : str
        Path to the ``.eml`` file.

    Returns
    -------
    (cards, metadata)
        cards : list of dicts, one per SIM card, keyed by field name.
        metadata : dict with order info (sale_order, delivery_order,
                   webshop_order, card_type, from, date, subject).

    Raises
    ------
    ValueError
        If the file cannot be parsed or no card data is found.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        msg = email.message_from_file(fh, policy=email.policy.default)

    # First, check for CSV attachments
    for part in msg.walk():
        fn = part.get_filename()
        if fn and fn.lower().endswith(".csv"):
            payload = part.get_content()
            cards = _parse_csv_text(payload)
            if cards:
                meta = _extract_metadata_from_headers(msg)
                return cards, meta

    # Otherwise, extract the text/plain body
    body = _get_text_body(msg)
    if not body:
        raise ValueError("No text content found in the email.")

    cards, meta = _parse_sysmocom_body(body)
    # Enrich metadata with email headers
    header_meta = _extract_metadata_from_headers(msg)
    header_meta.update(meta)  # body metadata takes priority
    return cards, header_meta


def _get_text_body(msg) -> str:
    """Extract the plain-text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_content()
    else:
        if msg.get_content_type() == "text/plain":
            return msg.get_content()
    return ""


def _extract_metadata_from_headers(msg) -> dict[str, str]:
    """Pull useful metadata from the email headers."""
    meta = {}
    for key, field in [("from", "From"), ("date", "Date"),
                        ("subject", "Subject")]:
        val = msg.get(field, "")
        if val:
            meta[key] = str(val)
    return meta


def _parse_sysmocom_body(body: str) -> tuple[list[dict[str, str]],
                                               dict[str, str]]:
    """Parse the sysmocom provisioning email body format.

    The body may contain **multiple batches** (e.g. two 10-packs in
    one order).  Each batch has its own ``Type:`` line, field-name
    header block, and card values.  We find every header block and
    parse the cards that follow it.

    Field order is NOT assumed — the parser reads whatever field names
    appear in each batch's header block and maps values accordingly.
    """
    lines = [ln.strip() for ln in body.replace("\r", "").split("\n")]
    meta: dict[str, str] = {}

    # Extract order metadata (from the first occurrence)
    for i, line in enumerate(lines):
        if line.startswith("Sale Order:") or line == "Sale Order:":
            if i + 1 < len(lines) and "sale_order" not in meta:
                meta["sale_order"] = lines[i + 1].strip()
        elif line.startswith("Delivery Order:") or line == "Delivery Order:":
            if i + 1 < len(lines) and "delivery_order" not in meta:
                meta["delivery_order"] = lines[i + 1].strip()
        elif line.startswith("Webshop Order ID:") or line == "Webshop Order ID:":
            if i + 1 < len(lines) and "webshop_order" not in meta:
                meta["webshop_order"] = lines[i + 1].strip()
        elif line.startswith("Type:") and "card_type" not in meta:
            meta["card_type"] = line.split(":", 1)[1].strip()

    # Find ALL field header blocks in the email
    header_blocks = _find_all_field_headers(lines)
    if not header_blocks:
        raise ValueError(
            "Could not find SIM card field headers in the email.\n"
            "Expected a block containing field names like: IMSI, ICCID, ACC, ...")

    cards: list[dict[str, str]] = []

    for header_start, field_names in header_blocks:
        num_fields = len(field_names)
        # Values start right after the header block
        values_start = header_start + num_fields
        batch_cards = _read_card_values(lines, values_start,
                                        num_fields, field_names)
        cards.extend(batch_cards)

    if not cards:
        raise ValueError("No card data found after the field headers.")

    logger.info("Parsed %d card(s) from sysmocom email", len(cards))
    return cards, meta


def _find_all_field_headers(
        lines: list[str]) -> list[tuple[int, list[str]]]:
    """Find ALL field header blocks in the email body.

    Returns a list of ``(start_index, field_names)`` tuples.
    Each ``field_names`` list preserves the order from the email so that
    subsequent card values are mapped to the correct field.

    Detection is **order-independent**: any consecutive run of lines
    where at least ``_MIN_HEADER_FIELDS`` match known sysmocom field
    names is considered a header block.
    """
    results: list[tuple[int, list[str]]] = []
    n = len(lines)
    i = 0

    while i < n:
        canonical = _normalise_field_name(lines[i])
        if canonical is None:
            i += 1
            continue

        # Potential header block — collect consecutive recognised names
        block_start = i
        field_names: list[str] = []
        while i < n:
            canon = _normalise_field_name(lines[i])
            if canon is not None:
                field_names.append(canon)
                i += 1
            elif not lines[i]:
                # skip blank lines inside header block
                i += 1
            else:
                break

        if len(field_names) >= _MIN_HEADER_FIELDS:
            results.append((block_start, field_names))
        # else: too few matches — not a header block, continue scanning

    return results


def _read_card_values(lines: list[str], start: int,
                      num_fields: int,
                      field_names: list[str]) -> list[dict[str, str]]:
    """Read card value blocks starting at *start*.

    Stops when it hits a signature (``--``), a new ``Type:`` line,
    a new field header block, or runs out of data.
    """
    cards: list[dict[str, str]] = []
    pos = start

    while pos < len(lines):
        # Skip empty lines between cards
        while pos < len(lines) and not lines[pos]:
            pos += 1
        if pos >= len(lines):
            break

        # Stop conditions
        if lines[pos].startswith("--"):
            break
        if lines[pos].startswith("Type:"):
            break
        # New header block (next batch) — check if this line is a field name
        if _normalise_field_name(lines[pos]) is not None:
            # Look ahead: if several consecutive lines are field names,
            # this is a new header block
            lookahead_count = 0
            for j in range(pos, min(pos + _MIN_HEADER_FIELDS + 1, len(lines))):
                if _normalise_field_name(lines[j]) is not None:
                    lookahead_count += 1
            if lookahead_count >= _MIN_HEADER_FIELDS:
                break

        # Try to read one card (num_fields non-empty values)
        values: list[str] = []
        j = pos
        while j < len(lines) and len(values) < num_fields:
            val = lines[j].strip()
            if not val:
                j += 1
                continue
            if val.startswith("--") or val.startswith("Type:"):
                break
            # Check if we've hit a new header block
            if _normalise_field_name(val) is not None:
                lookahead_count = 0
                for k in range(j, min(j + _MIN_HEADER_FIELDS + 1, len(lines))):
                    if _normalise_field_name(lines[k]) is not None:
                        lookahead_count += 1
                if lookahead_count >= _MIN_HEADER_FIELDS:
                    break
            values.append(val)
            j += 1

        if len(values) == num_fields:
            cards.append(dict(zip(field_names, values)))
            pos = j
        else:
            break  # incomplete card — stop

    return cards


def _parse_csv_text(text: str) -> list[dict[str, str]]:
    """Parse CSV text (from an attachment) into card dicts."""
    try:
        reader = csv.DictReader(io.StringIO(text))
        cards = [dict(row) for row in reader]
        return cards if cards else []
    except Exception:
        return []
