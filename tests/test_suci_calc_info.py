#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for SUCI Calc Info (hnet_pubkey) programming."""

from managers.card_manager import CardManager


class TestSuciCalcInfoWrite:
    """Test _pysim_write_suci_calc_info() returns correct commands."""

    def test_write_suci_calc_info_basic(self):
        """Basic hnet_pubkey write with defaults."""
        hnet_pubkey = "0e6e6e15b5d20b0aa382ef1b5277a780bfd061cd9b94cf7ee1200faaea5da53f"
        cmds = CardManager._pysim_write_suci_calc_info(hnet_pubkey)
        assert 'select MF' in cmds
        assert 'select ADF.USIM' in cmds
        assert 'select DF.5GS' in cmds
        assert 'select EF.SUCI_Calc_Info' in cmds
        assert any('update_binary_decoded' in cmd for cmd in cmds)

    def test_write_suci_calc_info_contains_pubkey(self):
        """Payload includes the hnet_pubkey value."""
        hnet_pubkey = "0e6e6e15b5d20b0aa382ef1b5277a780bfd061cd9b94cf7ee1200faaea5da53f"
        cmds = CardManager._pysim_write_suci_calc_info(hnet_pubkey)
        payload_cmd = [c for c in cmds if 'update_binary_decoded' in c][0]
        assert hnet_pubkey in payload_cmd

    def test_write_suci_calc_info_with_custom_params(self):
        """Write with custom protection scheme, routing indicator, pubkey_id."""
        hnet_pubkey = "0e6e6e15b5d20b0aa382ef1b5277a780bfd061cd9b94cf7ee1200faaea5da53f"
        cmds = CardManager._pysim_write_suci_calc_info(
            hnet_pubkey, prot_scheme=2, routing_ind="01", pubkey_id=2)
        payload_cmd = [c for c in cmds if 'update_binary_decoded' in c][0]
        assert hnet_pubkey in payload_cmd


class TestSuciCalcInfoRead:
    """Test _pysim_read_suci_calc_info() returns correct commands."""

    def test_read_suci_calc_info_basic(self):
        """Read command navigates to DF.5GS and EF.SUCI_Calc_Info."""
        cmds = CardManager._pysim_read_suci_calc_info()
        assert 'select MF' in cmds
        assert 'select ADF.USIM' in cmds
        assert 'select DF.5GS' in cmds
        assert 'select EF.SUCI_Calc_Info' in cmds
        assert 'read_binary_decoded' in cmds


class TestSuciCalcInfoParse:
    """Test _parse_suci_calc_info() parsing."""

    def test_parse_suci_calc_info_valid(self):
        """Parse valid SUCI Calc Info JSON response."""
        output = '''{
            "prot_scheme_id_list": [
                {"priority": 0, "identifier": 1, "key_index": 1}
            ],
            "hnet_pubkey_list": [
                {"hnet_pubkey_identifier": 1, "hnet_pubkey": "0e6e6e15b5d20b0aa382ef1b5277a780bfd061cd9b94cf7ee1200faaea5da53f"}
            ]
        }'''
        result = CardManager._parse_suci_calc_info(output)
        assert result == "0e6e6e15b5d20b0aa382ef1b5277a780bfd061cd9b94cf7ee1200faaea5da53f"

    def test_parse_suci_calc_info_empty_returns_empty_string(self):
        """Parse empty or invalid output returns empty string."""
        assert CardManager._parse_suci_calc_info("") == ""
        assert CardManager._parse_suci_calc_info("invalid json") == ""
        assert CardManager._parse_suci_calc_info("{}") == ""

    def test_parse_suci_calc_info_missing_list(self):
        """Parse JSON missing hnet_pubkey_list returns empty string."""
        output = '{"prot_scheme_id_list": []}'
        result = CardManager._parse_suci_calc_info(output)
        assert result == ""
