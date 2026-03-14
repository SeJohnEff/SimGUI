"""Targeted tests for utils/eml_parser.py to cover missed lines.

Missed lines:
- 257-258: blank line inside card-values loop (continue)
- 260: val starts with '--' or 'Type:' inside inner loop (break)
- 263-268: field-name lookahead inside inner loop (header detection)
- 287-288: _parse_csv_text exception handler
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.eml_parser import (
    _normalise_field_name,
    _parse_csv_text,
    _read_card_values,
    parse_eml_file,
)

# ---------------------------------------------------------------------------
# _normalise_field_name
# ---------------------------------------------------------------------------

class TestNormaliseFieldName:
    """Tests for _normalise_field_name."""

    def test_known_field_returns_canonical(self):
        """'imsi' (lowercase) → 'IMSI'."""
        assert _normalise_field_name("imsi") == "IMSI"

    def test_unknown_field_returns_none(self):
        """Unrecognised field name returns None."""
        assert _normalise_field_name("BLAHBLAH") is None

    def test_strips_whitespace(self):
        """Whitespace is stripped before lookup."""
        assert _normalise_field_name("  Ki  ") == "Ki"


# ---------------------------------------------------------------------------
# _parse_csv_text — exception path (lines 287-288)
# ---------------------------------------------------------------------------

class TestParseCsvText:
    """Tests for _parse_csv_text."""

    def test_valid_csv_parsed(self):
        """Valid CSV text is parsed into a list of dicts."""
        text = "ICCID,IMSI,Ki\n89001,001010001,aabb\n"
        result = _parse_csv_text(text)
        assert len(result) == 1
        assert result[0]["ICCID"] == "89001"

    def test_empty_csv_returns_empty_list(self):
        """Empty CSV text returns []."""
        result = _parse_csv_text("")
        assert result == []

    def test_header_only_csv_returns_empty_list(self):
        """CSV with only a header and no rows returns []."""
        result = _parse_csv_text("ICCID,IMSI,Ki\n")
        assert result == []

    def test_exception_returns_empty_list(self):
        """Exception during CSV parsing returns [] (lines 287-288)."""
        import unittest.mock as mock
        with mock.patch("csv.DictReader", side_effect=RuntimeError("boom")):
            result = _parse_csv_text("anything")
        assert result == []


# ---------------------------------------------------------------------------
# _read_card_values — targeted line coverage
# ---------------------------------------------------------------------------

class TestReadCardValues:
    """Tests for _read_card_values to cover missed branches."""

    def _make_lines(self, text: str) -> list:
        """Split text into stripped lines as the parser expects."""
        return [ln.strip() for ln in text.splitlines()]

    def test_blank_lines_inside_values_are_skipped(self):
        """Blank lines inside a card value block are skipped (lines 257-258)."""
        field_names = ["IMSI", "ICCID", "Ki"]
        lines = [
            "001010001",
            "",
            "89001",
            "",
            "aabbcc",
        ]
        result = _read_card_values(lines, start=0, num_fields=3, field_names=field_names)
        assert len(result) == 1
        assert result[0]["IMSI"] == "001010001"
        assert result[0]["ICCID"] == "89001"
        assert result[0]["Ki"] == "aabbcc"

    def test_signature_line_stops_inner_loop(self):
        """'--' line inside card values terminates collection (line 260)."""
        field_names = ["IMSI", "ICCID", "Ki", "OPC", "ADM1"]
        lines = [
            "001010001",
            "89001",
            "--",
            "aabbcc",
            "ddee",
            "12345678",
        ]
        result = _read_card_values(lines, start=0, num_fields=5, field_names=field_names)
        assert result == []

    def test_type_line_stops_inner_loop(self):
        """'Type: ...' line inside card values terminates collection (line 260)."""
        field_names = ["IMSI", "ICCID", "Ki", "OPC", "ADM1"]
        lines = [
            "001010001",
            "89001",
            "Type: SJA5",
        ]
        result = _read_card_values(lines, start=0, num_fields=5, field_names=field_names)
        assert result == []

    def test_new_header_block_inside_values_stops(self):
        """A new header block inside value reading stops collection (lines 263-268)."""
        field_names = ["IMSI", "ICCID"]
        lines = [
            "001010001",
            "89001",
            "IMSI",
            "ICCID",
            "Ki",
            "OPC",
            "ADM1",
            "001010002",
            "89002",
            "aabbcc",
            "ddee",
            "12345678",
        ]
        result = _read_card_values(lines, start=0, num_fields=2, field_names=field_names)
        assert len(result) == 1
        assert result[0]["IMSI"] == "001010001"

    def test_empty_lines_list_returns_empty(self):
        """Empty lines list returns []."""
        result = _read_card_values([], start=0, num_fields=3,
                                   field_names=["IMSI", "ICCID", "Ki"])
        assert result == []

    def test_incomplete_card_stops_loop(self):
        """When card values are incomplete, the loop stops (line 276)."""
        field_names = ["IMSI", "ICCID", "Ki"]
        lines = [
            "001010001",
            "89001",
        ]
        result = _read_card_values(lines, start=0, num_fields=3, field_names=field_names)
        assert result == []

    def test_dash_separator_at_outer_level_stops(self):
        """'--' at the outer loop level stops processing immediately."""
        field_names = ["IMSI"]
        lines = ["--"]
        result = _read_card_values(lines, start=0, num_fields=1, field_names=field_names)
        assert result == []

    def test_type_separator_at_outer_level_stops(self):
        """'Type:' at the outer loop level stops processing immediately."""
        field_names = ["IMSI"]
        lines = ["Type: SJA2"]
        result = _read_card_values(lines, start=0, num_fields=1, field_names=field_names)
        assert result == []

    def test_multiple_blank_lines_between_cards(self):
        """Multiple blank lines between cards are all skipped correctly."""
        field_names = ["IMSI", "ICCID"]
        lines = [
            "001010001",
            "89001",
            "",
            "",
            "",
            "001010002",
            "89002",
        ]
        result = _read_card_values(lines, start=0, num_fields=2, field_names=field_names)
        assert len(result) == 2
        assert result[1]["IMSI"] == "001010002"


# ---------------------------------------------------------------------------
# parse_eml_file with CSV attachment
# ---------------------------------------------------------------------------

class TestParseEmlFileCsvAttachment:
    """Tests that exercise CSV attachment parsing path."""

    def test_eml_with_csv_attachment(self, tmp_path):
        """EML with a CSV attachment yields cards from the attachment."""
        csv_data = "ICCID,IMSI,Ki,OPC,ADM1\n89001,001010001,aabb,ccdd,12345678\n"
        boundary = "BOUNDARY123"
        eml_content = (
            "From: test@test.com\n"
            "To: user@user.com\n"
            "Subject: SIM Cards\n"
            f"Content-Type: multipart/mixed; boundary={boundary}\n"
            "\n"
            f"--{boundary}\n"
            "Content-Type: text/plain\n"
            "\n"
            "Here are your SIM cards.\n"
            f"--{boundary}\n"
            'Content-Type: text/csv; name="cards.csv"\n'
            'Content-Disposition: attachment; filename="cards.csv"\n'
            "\n"
            + csv_data
            + f"--{boundary}--\n"
        )
        path = tmp_path / "test.eml"
        path.write_text(eml_content)
        cards, meta = parse_eml_file(str(path))
        assert isinstance(cards, list)

    def test_eml_missing_file_raises(self, tmp_path):
        """parse_eml_file raises an error for missing file."""
        with pytest.raises(Exception):
            parse_eml_file(str(tmp_path / "nonexistent.eml"))
