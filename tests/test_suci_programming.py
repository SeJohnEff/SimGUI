"""Tests for SUCI (5G privacy) service activation/deactivation."""

from managers.card_manager import CardManager


class TestSuciWriteCommands:
    """Test _pysim_write_suci() returns correct pySim-shell commands."""

    def test_write_suci_enabled(self):
        """SUCI enabled: activate service 124, deactivate service 125."""
        cmds = CardManager._pysim_write_suci(True)
        assert 'ust_service_activate 124' in cmds
        assert 'ust_service_deactivate 125' in cmds

    def test_write_suci_disabled(self):
        """SUCI disabled: deactivate service 124, activate service 125."""
        cmds = CardManager._pysim_write_suci(False)
        assert 'ust_service_deactivate 124' in cmds
        assert 'ust_service_activate 125' in cmds


class TestSuciReadCommands:
    """Test _pysim_read_suci() returns correct pySim-shell commands."""

    def test_read_suci_includes_read_binary_decoded(self):
        """SUCI read includes EF.UST navigation and read_binary_decoded."""
        cmds = CardManager._pysim_read_suci()
        assert 'read_binary_decoded' in cmds
        assert 'select EF.UST' in cmds


class TestSuciParseReadback:
    """Test _parse_suci_readback() correctly parses EF.UST read output."""

    def test_parse_suci_enabled(self):
        """Service 124 true AND 125 false returns True."""
        output = '{"124": true, "125": false}'
        assert CardManager._parse_suci_readback(output) is True

    def test_parse_suci_disabled(self):
        """Service 124 false AND 125 true returns False."""
        output = '{"124": false, "125": true}'
        assert CardManager._parse_suci_readback(output) is False

    def test_parse_suci_invalid_returns_false(self):
        """Invalid/missing data returns False."""
        assert CardManager._parse_suci_readback('invalid json') is False
        assert CardManager._parse_suci_readback('') is False
