"""Tests for multi-format SIM data file loading (CSV + whitespace-delimited)."""

import csv
import os
import tempfile

import pytest

from managers.csv_manager import CSVManager, _normalize_column


# -- Test data ---------------------------------------------------------------

WHITESPACE_HEADER = "PIN1 PUK1 PIN2 PUK2 ADM ICCID IMSI ACC MSISDN KI OPC"
WHITESPACE_ROWS = [
    "1234 88888888 1234 88888888 3838383838383838 89999880000000000200000 999880000200000 0000 999880000200000 8551958e719c542bb931343c8eb05b49 d290f04588693f6c68591b0ad187fec7",
    "1234 88888888 1234 88888888 3838383838383838 89999880000000000200001 999880000200001 0001 999880000200001 2f412261ae35de0ee15f738a47bf1fb5 20611facb58d04f8d92013bc3f2e9bff",
    "1234 88888888 1234 88888888 3838383838383838 89999880000000000200002 999880000200002 0002 999880000200002 41de287441c1cd1b478202186b99f265 b4160bb42a73cba8a98ab511ddaaa139",
]

COMMA_HEADER = "IMSI,ICCID,ACC,PIN1,PUK1,PIN2,PUK2,Ki,OPC,ADM1"
COMMA_ROWS = [
    "999700000167270,8949440000001672706,0001,0000,88528379,0000,31497382,E049AF7DBE25B0AECD0CE2FEE03FD919,9EB1A95173A8F40281EFBA24D4053A0E,76510072",
    "999700000167271,8949440000001672714,0002,0000,25088500,0000,18493400,8224F445CE586BF9048A8659BC99BD64,3149618671ACB135BFB7668FE8F10AD4,95478281",
]


def _write_tmp(content: str, suffix: str = ".txt") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


# -- Column normalization ----------------------------------------------------

class TestColumnNormalization:
    def test_adm_to_adm1(self):
        assert _normalize_column("ADM") == "ADM1"
        assert _normalize_column("adm") == "ADM1"
        assert _normalize_column("Adm") == "ADM1"

    def test_ki_to_ki(self):
        assert _normalize_column("KI") == "Ki"
        assert _normalize_column("ki") == "Ki"
        assert _normalize_column("Ki") == "Ki"

    def test_opc_to_opc(self):
        assert _normalize_column("OPC") == "OPc"
        assert _normalize_column("opc") == "OPc"
        assert _normalize_column("OPc") == "OPc"

    def test_other_columns_uppercased(self):
        assert _normalize_column("ICCID") == "ICCID"
        assert _normalize_column("imsi") == "IMSI"
        assert _normalize_column("pin1") == "PIN1"
        assert _normalize_column("msisdn") == "MSISDN"

    def test_adm1_stays_adm1(self):
        # ADM1 lowercased is 'adm1', which is not in the special map, so uppercased → ADM1
        assert _normalize_column("ADM1") == "ADM1"


# -- Whitespace format loading -----------------------------------------------

class TestWhitespaceFormat:
    def test_load_whitespace_txt(self):
        content = WHITESPACE_HEADER + "\n" + "\n".join(WHITESPACE_ROWS) + "\n"
        path = _write_tmp(content, suffix=".txt")
        try:
            mgr = CSVManager()
            assert mgr.load_csv(path) is True
            assert mgr.get_card_count() == 3
        finally:
            os.unlink(path)

    def test_column_names_normalized(self):
        content = WHITESPACE_HEADER + "\n" + WHITESPACE_ROWS[0] + "\n"
        path = _write_tmp(content, suffix=".txt")
        try:
            mgr = CSVManager()
            mgr.load_csv(path)
            # ADM → ADM1, KI → Ki, OPC → OPc
            assert "ADM1" in mgr.columns
            assert "Ki" in mgr.columns
            assert "OPc" in mgr.columns
            assert "ADM" not in mgr.columns
            assert "KI" not in mgr.columns
            assert "OPC" not in mgr.columns
        finally:
            os.unlink(path)

    def test_adm_value_preserved(self):
        content = WHITESPACE_HEADER + "\n" + WHITESPACE_ROWS[0] + "\n"
        path = _write_tmp(content, suffix=".txt")
        try:
            mgr = CSVManager()
            mgr.load_csv(path)
            card = mgr.get_card(0)
            assert card["ADM1"] == "3838383838383838"
        finally:
            os.unlink(path)

    def test_msisdn_preserved(self):
        content = WHITESPACE_HEADER + "\n" + WHITESPACE_ROWS[0] + "\n"
        path = _write_tmp(content, suffix=".txt")
        try:
            mgr = CSVManager()
            mgr.load_csv(path)
            card = mgr.get_card(0)
            assert card["MSISDN"] == "999880000200000"
        finally:
            os.unlink(path)

    def test_ki_opc_values(self):
        content = WHITESPACE_HEADER + "\n" + WHITESPACE_ROWS[0] + "\n"
        path = _write_tmp(content, suffix=".txt")
        try:
            mgr = CSVManager()
            mgr.load_csv(path)
            card = mgr.get_card(0)
            assert card["Ki"] == "8551958e719c542bb931343c8eb05b49"
            assert card["OPc"] == "d290f04588693f6c68591b0ad187fec7"
        finally:
            os.unlink(path)

    def test_windows_line_endings(self):
        content = WHITESPACE_HEADER + "\r\n" + WHITESPACE_ROWS[0] + "\r\n"
        path = _write_tmp(content, suffix=".txt")
        try:
            mgr = CSVManager()
            assert mgr.load_csv(path) is True
            assert mgr.get_card_count() == 1
        finally:
            os.unlink(path)


# -- Comma CSV format (existing) ---------------------------------------------

class TestCommaFormat:
    def test_load_comma_csv(self):
        content = COMMA_HEADER + "\n" + "\n".join(COMMA_ROWS) + "\n"
        path = _write_tmp(content, suffix=".csv")
        try:
            mgr = CSVManager()
            assert mgr.load_csv(path) is True
            assert mgr.get_card_count() == 2
        finally:
            os.unlink(path)

    def test_comma_columns_normalized(self):
        content = COMMA_HEADER + "\n" + COMMA_ROWS[0] + "\n"
        path = _write_tmp(content, suffix=".csv")
        try:
            mgr = CSVManager()
            mgr.load_csv(path)
            # Ki in header stays Ki; OPC normalizes to OPc
            assert "Ki" in mgr.columns
            assert "OPc" in mgr.columns
            assert "OPC" not in mgr.columns
            # ADM1 stays ADM1
            assert "ADM1" in mgr.columns
        finally:
            os.unlink(path)

    def test_existing_sysmocom_csv(self):
        """Test the real sysmocom CSV file loads correctly."""
        csv_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "sysmocom_sim_data.csv")
        if not os.path.exists(csv_path):
            pytest.skip("sysmocom_sim_data.csv not found")
        mgr = CSVManager()
        assert mgr.load_csv(csv_path) is True
        assert mgr.get_card_count() > 0
        card = mgr.get_card(0)
        assert card["IMSI"] is not None

    def test_existing_fiskarheden_txt(self):
        """Test the real Fiskarheden TXT file loads correctly."""
        txt_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "simFiskarheden_876549639.txt")
        if not os.path.exists(txt_path):
            pytest.skip("simFiskarheden_876549639.txt not found")
        mgr = CSVManager()
        assert mgr.load_csv(txt_path) is True
        assert mgr.get_card_count() == 100
        card = mgr.get_card(0)
        assert card["ADM1"] == "3838383838383838"
        assert "MSISDN" in mgr.columns


# -- Auto-detection ----------------------------------------------------------

class TestAutoDetection:
    def test_autodetect_comma(self):
        content = COMMA_HEADER + "\n" + COMMA_ROWS[0] + "\n"
        path = _write_tmp(content, suffix=".csv")
        try:
            mgr = CSVManager()
            mgr.load_csv(path)
            assert mgr.get_card_count() == 1
            assert mgr.get_card(0)["IMSI"] == "999700000167270"
        finally:
            os.unlink(path)

    def test_autodetect_whitespace(self):
        content = WHITESPACE_HEADER + "\n" + WHITESPACE_ROWS[0] + "\n"
        path = _write_tmp(content, suffix=".txt")
        try:
            mgr = CSVManager()
            mgr.load_csv(path)
            assert mgr.get_card_count() == 1
            assert mgr.get_card(0)["IMSI"] == "999880000200000"
        finally:
            os.unlink(path)

    def test_whitespace_file_with_csv_extension(self):
        """Whitespace-delimited content in a .csv file should still work."""
        content = WHITESPACE_HEADER + "\n" + WHITESPACE_ROWS[0] + "\n"
        path = _write_tmp(content, suffix=".csv")
        try:
            mgr = CSVManager()
            assert mgr.load_csv(path) is True
            assert mgr.get_card_count() == 1
        finally:
            os.unlink(path)


# -- Save after load ---------------------------------------------------------

class TestSaveAfterLoad:
    def test_save_whitespace_as_csv(self):
        """Loading a .txt whitespace file then saving produces valid CSV."""
        content = WHITESPACE_HEADER + "\n" + "\n".join(WHITESPACE_ROWS) + "\n"
        txt_path = _write_tmp(content, suffix=".txt")
        csv_path = _write_tmp("", suffix=".csv")
        try:
            mgr = CSVManager()
            mgr.load_csv(txt_path)
            assert mgr.save_csv(csv_path) is True

            # Re-load the saved CSV
            mgr2 = CSVManager()
            assert mgr2.load_csv(csv_path) is True
            assert mgr2.get_card_count() == 3

            # Verify it was saved as comma-separated
            with open(csv_path, "r") as f:
                first_line = f.readline()
            assert "," in first_line

            # Verify normalized columns are in the saved output
            assert "ADM1" in mgr2.columns
            assert "Ki" in mgr2.columns
            assert "OPc" in mgr2.columns

            # Verify data integrity
            card = mgr2.get_card(0)
            assert card["ADM1"] == "3838383838383838"
            assert card["MSISDN"] == "999880000200000"
        finally:
            os.unlink(txt_path)
            os.unlink(csv_path)


# -- Edge cases --------------------------------------------------------------

class TestEdgeCases:
    def test_empty_file(self):
        path = _write_tmp("", suffix=".txt")
        try:
            mgr = CSVManager()
            assert mgr.load_csv(path) is False
        finally:
            os.unlink(path)

    def test_header_only_file(self):
        path = _write_tmp(WHITESPACE_HEADER + "\n", suffix=".txt")
        try:
            mgr = CSVManager()
            assert mgr.load_csv(path) is True
            assert mgr.get_card_count() == 0
        finally:
            os.unlink(path)

    def test_header_only_csv(self):
        path = _write_tmp(COMMA_HEADER + "\n", suffix=".csv")
        try:
            mgr = CSVManager()
            assert mgr.load_csv(path) is True
            assert mgr.get_card_count() == 0
        finally:
            os.unlink(path)

    def test_blank_lines_ignored(self):
        content = WHITESPACE_HEADER + "\n\n" + WHITESPACE_ROWS[0] + "\n\n"
        path = _write_tmp(content, suffix=".txt")
        try:
            mgr = CSVManager()
            assert mgr.load_csv(path) is True
            assert mgr.get_card_count() == 1
        finally:
            os.unlink(path)

    def test_whitespace_only_file(self):
        path = _write_tmp("   \n\n  \n", suffix=".txt")
        try:
            mgr = CSVManager()
            assert mgr.load_csv(path) is False
        finally:
            os.unlink(path)
