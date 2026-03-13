"""Tests for the sysmocom EML parser.

Covers:
- Real email parsing (20 cards, 2×10 batches)
- Field order independence
- Single-batch and multi-batch emails
- Malformed / empty / non-sysmocom emails
- CSV attachment handling
- Field name normalisation through CSVManager.load_file()
- Public API smoke test (the test that would have caught _find_all_field_headers)
"""

import os
import sys
import tempfile
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.eml_parser import (
    _SYSMOCOM_FIELDS,
    _find_all_field_headers,
    _normalise_field_name,
    _parse_sysmocom_body,
    parse_eml_file,
)

# Path to the real sysmocom email (if available)
_REAL_EML = os.path.join(
    os.path.dirname(__file__), '..', '..',
    'FW-sysmocom-SIM-Card-Details-AM93OUT10305-WEBON_1885944321-1.eml')
_HAS_REAL_EML = os.path.exists(_REAL_EML)


# ---------------------------------------------------------------------------
# Helpers — synthetic email builders
# ---------------------------------------------------------------------------

_STANDARD_FIELDS = [
    "IMSI", "ICCID", "ACC", "PIN1", "PUK1", "PIN2", "PUK2",
    "Ki", "OPC", "ADM1",
    "KIC1", "KID1", "KIK1",
    "KIC2", "KID2", "KIK2",
    "KIC3", "KID3", "KIK3",
]


# Value generators keyed by field name
_FIELD_VALUE_GENERATORS = {
    "IMSI": lambda n: f"99970000016{n:04d}",
    "ICCID": lambda n: f"894944000000167{n:04d}",
    "ADM1": lambda n: f"ADM{n:05d}",
    "Ki": lambda n: f"KI{'A' * 28}{n:04d}",
    "OPC": lambda n: f"OP{'B' * 28}{n:04d}",
}


def _make_card_values(card_num: int, field_order: list[str]) -> list[str]:
    """Generate dummy values for a single card, matching the given field order."""
    vals = []
    for field_name in field_order:
        gen = _FIELD_VALUE_GENERATORS.get(field_name)
        if gen:
            vals.append(gen(card_num))
        else:
            vals.append(f"{field_name}_{card_num:04d}")
    return vals


def _build_eml(body: str, subject: str = "SIM Card Details") -> str:
    """Wrap a body in a minimal RFC 5322 email."""
    return textwrap.dedent(f"""\
        From: test@sysmocom.de
        To: user@example.com
        Subject: {subject}
        MIME-Version: 1.0
        Content-Type: text/plain; charset="utf-8"

        {body}
    """)


def _build_batch_body(field_order: list[str], num_cards: int,
                      card_type: str = "sysmoISIM-SJA5",
                      start_num: int = 1) -> str:
    """Build one batch block with given field order."""
    lines = [f"Type: {card_type}", ""]
    for f in field_order:
        lines.append(f)
    lines.append("")
    for i in range(num_cards):
        vals = _make_card_values(start_num + i, field_order)
        for v in vals:
            lines.append(v)
        lines.append("")
    return "\n".join(lines)


def _write_eml(content: str) -> str:
    """Write EML content to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".eml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


# ---------------------------------------------------------------------------
# Test: Public API smoke test — THE test that catches _find_all_field_headers
# ---------------------------------------------------------------------------

class TestPublicAPISmoke:
    """Calling parse_eml_file with valid data must not crash."""

    def test_parse_eml_file_is_callable(self):
        assert callable(parse_eml_file)

    def test_parse_single_batch_eml(self):
        """parse_eml_file() must work end-to-end with a simple synthetic email."""
        body = _build_batch_body(_STANDARD_FIELDS, 3)
        eml = _build_eml(body)
        path = _write_eml(eml)
        try:
            cards, meta = parse_eml_file(path)
            assert len(cards) == 3
            assert "IMSI" in cards[0]
            assert "ICCID" in cards[0]
        finally:
            os.unlink(path)

    def test_internal_functions_exist(self):
        """All functions called by the parser must actually exist in the module."""
        import utils.eml_parser as mod
        # These are the key internal functions called by the parser
        assert hasattr(mod, '_find_all_field_headers'), \
            "_find_all_field_headers is called but missing!"
        assert hasattr(mod, '_read_card_values')
        assert hasattr(mod, '_parse_sysmocom_body')
        assert hasattr(mod, '_get_text_body')
        assert hasattr(mod, '_extract_metadata_from_headers')
        assert hasattr(mod, '_parse_csv_text')
        assert hasattr(mod, '_normalise_field_name')


# ---------------------------------------------------------------------------
# Test: Real email (2×10 = 20 cards)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_REAL_EML, reason="Real .eml file not available")
class TestRealEmail:

    def test_card_count(self):
        cards, _ = parse_eml_file(_REAL_EML)
        assert len(cards) == 20, f"Expected 20 cards, got {len(cards)}"

    def test_all_19_fields_populated(self):
        cards, _ = parse_eml_file(_REAL_EML)
        for i, card in enumerate(cards):
            assert len(card) == 19, (
                f"Card {i}: expected 19 fields, got {len(card)}: {sorted(card.keys())}")
            for key, val in card.items():
                assert val, f"Card {i}: field '{key}' is empty"

    def test_field_names_correct(self):
        cards, _ = parse_eml_file(_REAL_EML)
        expected = set(_STANDARD_FIELDS)
        actual = set(cards[0].keys())
        assert actual == expected, f"Field mismatch: {actual.symmetric_difference(expected)}"

    def test_iccid_lengths(self):
        cards, _ = parse_eml_file(_REAL_EML)
        for i, card in enumerate(cards):
            iccid = card["ICCID"]
            assert len(iccid) >= 19, f"Card {i}: ICCID too short: {iccid}"

    def test_imsi_15_digits(self):
        cards, _ = parse_eml_file(_REAL_EML)
        for i, card in enumerate(cards):
            imsi = card["IMSI"]
            assert len(imsi) == 15 and imsi.isdigit(), (
                f"Card {i}: IMSI not 15 digits: {imsi}")

    def test_metadata_extracted(self):
        _, meta = parse_eml_file(_REAL_EML)
        assert "sale_order" in meta
        assert "delivery_order" in meta
        assert "card_type" in meta
        assert "from" in meta
        assert "subject" in meta

    def test_two_distinct_batches(self):
        """The 20 cards should come from 2 batches of 10 with different ICCIDs."""
        cards, _ = parse_eml_file(_REAL_EML)
        iccids = [c["ICCID"] for c in cards]
        assert len(set(iccids)) == 20, "Expected 20 unique ICCIDs"


# ---------------------------------------------------------------------------
# Test: Field order independence
# ---------------------------------------------------------------------------

class TestFieldOrderIndependence:

    def test_reversed_field_order(self):
        """Parser must work when fields appear in reversed order."""
        reversed_fields = list(reversed(_STANDARD_FIELDS))
        body = _build_batch_body(reversed_fields, 2)
        eml = _build_eml(body)
        path = _write_eml(eml)
        try:
            cards, _ = parse_eml_file(path)
            assert len(cards) == 2
            # Values must map to correct field names despite reversed order
            assert cards[0]["IMSI"].startswith("999700")
            assert cards[0]["ICCID"].startswith("894944")
        finally:
            os.unlink(path)

    def test_shuffled_field_order(self):
        """Parser must work with an arbitrary field ordering."""
        import random
        rng = random.Random(42)  # deterministic
        shuffled = list(_STANDARD_FIELDS)
        rng.shuffle(shuffled)
        body = _build_batch_body(shuffled, 5)
        eml = _build_eml(body)
        path = _write_eml(eml)
        try:
            cards, _ = parse_eml_file(path)
            assert len(cards) == 5
            for card in cards:
                assert set(card.keys()) == set(_STANDARD_FIELDS)
                assert card["IMSI"].startswith("999700")
                assert card["ICCID"].startswith("894944")
        finally:
            os.unlink(path)

    def test_subset_of_fields(self):
        """Parser must work with fewer than 19 fields (as long as >= 5)."""
        subset = ["ICCID", "IMSI", "Ki", "OPC", "ADM1", "ACC"]
        body = _build_batch_body(subset, 3)
        eml = _build_eml(body)
        path = _write_eml(eml)
        try:
            cards, _ = parse_eml_file(path)
            assert len(cards) == 3
            assert set(cards[0].keys()) == set(subset)
        finally:
            os.unlink(path)

    def test_case_insensitive_field_names(self):
        """Field names like 'imsi', 'Iccid', 'opc' must be normalised."""
        assert _normalise_field_name("imsi") == "IMSI"
        assert _normalise_field_name("ICCID") == "ICCID"
        assert _normalise_field_name("opc") == "OPC"
        assert _normalise_field_name("ki") == "Ki"
        assert _normalise_field_name("adm1") == "ADM1"
        assert _normalise_field_name("unknown") is None


# ---------------------------------------------------------------------------
# Test: Multi-batch parsing
# ---------------------------------------------------------------------------

class TestMultiBatch:

    def test_two_batches(self):
        batch1 = _build_batch_body(_STANDARD_FIELDS, 5, start_num=1)
        batch2 = _build_batch_body(_STANDARD_FIELDS, 3, start_num=100)
        body = batch1 + "\n" + batch2
        eml = _build_eml(body)
        path = _write_eml(eml)
        try:
            cards, _ = parse_eml_file(path)
            assert len(cards) == 8
        finally:
            os.unlink(path)

    def test_three_batches(self):
        body = ""
        for i in range(3):
            body += _build_batch_body(
                _STANDARD_FIELDS, 4, start_num=i * 100) + "\n"
        eml = _build_eml(body)
        path = _write_eml(eml)
        try:
            cards, _ = parse_eml_file(path)
            assert len(cards) == 12
        finally:
            os.unlink(path)

    def test_batches_with_different_field_orders(self):
        """Each batch can have a different field order."""
        reversed_fields = list(reversed(_STANDARD_FIELDS))
        batch1 = _build_batch_body(_STANDARD_FIELDS, 2, start_num=1)
        batch2 = _build_batch_body(reversed_fields, 2, start_num=100)
        body = batch1 + "\n" + batch2
        eml = _build_eml(body)
        path = _write_eml(eml)
        try:
            cards, _ = parse_eml_file(path)
            assert len(cards) == 4
            for card in cards:
                assert card["IMSI"].startswith("999700")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:

    def test_empty_email_raises(self):
        eml = _build_eml("")
        path = _write_eml(eml)
        try:
            with pytest.raises(ValueError, match="field headers"):
                parse_eml_file(path)
        finally:
            os.unlink(path)

    def test_no_text_body_raises(self):
        # Build an email with only HTML part
        content = textwrap.dedent("""\
            From: test@example.com
            Subject: Test
            MIME-Version: 1.0
            Content-Type: text/html; charset="utf-8"

            <html><body>No data here</body></html>
        """)
        path = _write_eml(content)
        try:
            with pytest.raises(ValueError, match="No text content"):
                parse_eml_file(path)
        finally:
            os.unlink(path)

    def test_non_sysmocom_email_raises(self):
        body = "Hello John,\n\nPlease find attached the invoice.\n\nRegards,\nBob"
        eml = _build_eml(body, subject="Invoice")
        path = _write_eml(eml)
        try:
            with pytest.raises(ValueError, match="field headers"):
                parse_eml_file(path)
        finally:
            os.unlink(path)

    def test_too_few_fields_raises(self):
        """A block with only 3 recognised field names should not parse."""
        body = "Type: test\n\nIMSI\nICCID\nACC\n\n12345\n67890\n0001\n"
        eml = _build_eml(body)
        path = _write_eml(eml)
        try:
            with pytest.raises(ValueError, match="field headers"):
                parse_eml_file(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: CSV attachment in EML
# ---------------------------------------------------------------------------

class TestCSVAttachment:

    def test_eml_with_csv_attachment(self):
        import email as email_mod
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart()
        msg["From"] = "test@example.com"
        msg["Subject"] = "SIM Data"
        msg.attach(MIMEText("See attached CSV.", "plain"))

        csv_data = "IMSI,ICCID,Ki,OPC,ADM1\n" \
                   "123456789012345,89860012345678901234,AA,BB,CC\n"
        csv_part = MIMEText(csv_data, "csv")
        csv_part.add_header("Content-Disposition", "attachment",
                            filename="cards.csv")
        msg.attach(csv_part)

        path = _write_eml(msg.as_string())
        try:
            cards, meta = parse_eml_file(path)
            assert len(cards) == 1
            assert cards[0]["IMSI"] == "123456789012345"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: _find_all_field_headers internals
# ---------------------------------------------------------------------------

class TestFindAllFieldHeaders:

    def test_single_block(self):
        lines = ["some text", "IMSI", "ICCID", "ACC", "PIN1", "PUK1",
                 "PIN2", "PUK2", "Ki", "OPC", "ADM1", "", "value1"]
        result = _find_all_field_headers(lines)
        assert len(result) == 1
        start, fields = result[0]
        assert start == 1
        assert fields[0] == "IMSI"

    def test_two_blocks(self):
        lines = (["Type: batch1", ""]
                 + _STANDARD_FIELDS + ["val1"] * 19
                 + ["", "Type: batch2", ""]
                 + _STANDARD_FIELDS + ["val2"] * 19)
        # Flatten the field list since _STANDARD_FIELDS is a list
        result = _find_all_field_headers(lines)
        assert len(result) == 2

    def test_order_independent_detection(self):
        """Detection must not depend on which field comes first."""
        fields = ["ADM1", "Ki", "OPC", "ICCID", "IMSI", "ACC"]
        lines = ["some header"] + fields + ["value1"]
        result = _find_all_field_headers(lines)
        assert len(result) == 1
        _, detected_fields = result[0]
        assert detected_fields == fields  # preserve original order

    def test_empty_lines_returns_empty(self):
        result = _find_all_field_headers(["", "", ""])
        assert result == []


# ---------------------------------------------------------------------------
# Test: CSVManager.load_file() integration with EML
# ---------------------------------------------------------------------------

class TestCSVManagerEMLIntegration:

    def test_load_file_with_eml(self):
        """CSVManager.load_file() must correctly load an .eml file."""
        from managers.csv_manager import CSVManager
        body = _build_batch_body(_STANDARD_FIELDS, 2)
        eml = _build_eml(body)
        path = _write_eml(eml)
        try:
            mgr = CSVManager()
            assert mgr.load_file(path) is True
            assert mgr.get_card_count() == 2
            card = mgr.get_card(0)
            assert card is not None
            assert "IMSI" in card
        finally:
            os.unlink(path)

    def test_load_file_eml_error_raises_valueerror(self):
        """CSVManager.load_file() must let ValueError propagate for bad EML."""
        from managers.csv_manager import CSVManager
        eml = _build_eml("This is not SIM data.")
        path = _write_eml(eml)
        try:
            mgr = CSVManager()
            with pytest.raises(ValueError):
                mgr.load_file(path)
        finally:
            os.unlink(path)

    @pytest.mark.skipif(not _HAS_REAL_EML, reason="Real .eml file not available")
    def test_load_real_eml_via_csv_manager(self):
        """CSVManager.load_file() with real email → 20 cards."""
        from managers.csv_manager import CSVManager
        mgr = CSVManager()
        assert mgr.load_file(_REAL_EML) is True
        assert mgr.get_card_count() == 20
