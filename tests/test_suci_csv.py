"""Tests for SUCI CSV field support."""

import tempfile
from managers.csv_manager import CSVManager


class TestSuciCsvLoading:
    """Test SUCI field loading from CSV files."""

    def test_load_csv_with_suci_column(self):
        """CSV with SUCI column loads and normalizes correctly."""
        csv_content = "IMSI,ICCID,SUCI\n240010000000001,8999988000100000019,true\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            f.flush()
            filepath = f.name

        mgr = CSVManager()
        assert mgr.load_csv(filepath)
        assert len(mgr.cards) == 1
        assert 'SUCI' in mgr.cards[0]
        assert mgr.cards[0]['SUCI'] == 'true'

    def test_load_csv_with_suci_enabled_alias(self):
        """CSV with 'suci_enabled' column normalizes to 'SUCI'."""
        csv_content = "IMSI,ICCID,suci_enabled\n240010000000001,8999988000100000019,yes\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            f.flush()
            filepath = f.name

        mgr = CSVManager()
        assert mgr.load_csv(filepath)
        assert len(mgr.cards) == 1
        assert 'SUCI' in mgr.cards[0]
        assert mgr.cards[0]['SUCI'] == 'yes'

    def test_load_csv_suci_in_standard_columns(self):
        """SUCI is in STANDARD_COLUMNS."""
        mgr = CSVManager()
        assert 'SUCI' in mgr.columns
