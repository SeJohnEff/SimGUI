"""Tests for pysim_parser.parse_pysim_output()."""

import pytest
from pysim_parser import parse_pysim_output


# ---------------------------------------------------------------------------
# SJA5-like output
# ---------------------------------------------------------------------------

SJA5_OUTPUT = (
    "Autodetected card type: sysmoISIM-SJA5\n"
    "ICCID: 8946001900000123456\n"
    "IMSI: 240010123456789\n"
    "ACC: 0004\n"
    "SPN: BOLIDEN\n"
    "FPLMN:\n"
    "\t42f010 # MCC: 240 MNC: 01\n"
    "\t42f007 # MCC: 240 MNC: 07\n"
)


def test_sja5_card_type_str():
    result = parse_pysim_output(SJA5_OUTPUT)
    assert result["card_type_str"] == "sysmoisim-sja5"


def test_sja5_iccid():
    result = parse_pysim_output(SJA5_OUTPUT)
    assert result["ICCID"] == "8946001900000123456"


def test_sja5_imsi():
    result = parse_pysim_output(SJA5_OUTPUT)
    assert result["IMSI"] == "240010123456789"


def test_sja5_acc():
    result = parse_pysim_output(SJA5_OUTPUT)
    assert result["ACC"] == "0004"


def test_sja5_spn():
    result = parse_pysim_output(SJA5_OUTPUT)
    assert result["SPN"] == "BOLIDEN"


def test_sja5_fplmn():
    result = parse_pysim_output(SJA5_OUTPUT)
    assert result["FPLMN"] == "24001;24007"


# ---------------------------------------------------------------------------
# GialerSIM / blank card output
# ---------------------------------------------------------------------------

GIALERSIM_OUTPUT = (
    "Autodetected card type: gialersim\n"
    "ACC: ffff\n"
)


def test_gialersim_card_type_str():
    result = parse_pysim_output(GIALERSIM_OUTPUT)
    assert result["card_type_str"] == "gialersim"


def test_gialersim_no_iccid():
    result = parse_pysim_output(GIALERSIM_OUTPUT)
    assert "ICCID" not in result


def test_gialersim_no_imsi():
    result = parse_pysim_output(GIALERSIM_OUTPUT)
    assert "IMSI" not in result


def test_gialersim_acc_present():
    result = parse_pysim_output(GIALERSIM_OUTPUT)
    assert result["ACC"] == "ffff"


# ---------------------------------------------------------------------------
# FPLMN edge cases
# ---------------------------------------------------------------------------

def test_fplmn_single_entry():
    out = "FPLMN:\n\t42f007 # MCC: 240 MNC: 07\n"
    result = parse_pysim_output(out)
    assert result["FPLMN"] == "24007"


def test_fplmn_empty_block_not_in_result():
    result = parse_pysim_output("FPLMN:\n")
    assert "FPLMN" not in result


def test_fplmn_mnc_zero_padded():
    out = "FPLMN:\n\t42f001 # MCC: 240 MNC: 1\n"
    result = parse_pysim_output(out)
    assert result["FPLMN"] == "24001"


# ---------------------------------------------------------------------------
# Traceback / noise skipped
# ---------------------------------------------------------------------------

def test_traceback_lines_skipped():
    out = (
        "Traceback (most recent call last):\n"
        '  File "pySim-read.py", line 42, in <module>\n'
        "raise RuntimeError('fail')\n"
        "IMSI: 240010000000001\n"
    )
    result = parse_pysim_output(out)
    assert result["IMSI"] == "240010000000001"
    assert "card_type_str" in result


# ---------------------------------------------------------------------------
# Empty / degenerate input
# ---------------------------------------------------------------------------

def test_empty_string_returns_safe_dict():
    result = parse_pysim_output("")
    assert isinstance(result, dict)
    assert result.get("card_type_str") == ""
    assert "IMSI" not in result
    assert "ICCID" not in result


def test_no_colon_lines_ignored():
    result = parse_pysim_output("No colon here\nAnother line\n")
    assert result == {"card_type_str": ""}


def test_case_insensitive_imsi():
    result = parse_pysim_output("  imsi: 123456789012345")
    assert result["IMSI"] == "123456789012345"


def test_whitespace_trimmed():
    result = parse_pysim_output("IMSI:   001010123456789   ")
    assert result["IMSI"] == "001010123456789"


def test_value_with_colon_uses_first_partition():
    result = parse_pysim_output("ICCID: 89860012345678901234:extra")
    assert result["ICCID"] == "89860012345678901234:extra"
