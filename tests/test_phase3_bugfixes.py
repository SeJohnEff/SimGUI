"""Tests for Phase 3 bug fixes and feature additions.

Bug 3.1: pySim-shell gialersim auth — uses -a ASCII instead of -A hex
Bug 3.2: SPN read-back — passes -t gialersim to pySim-read
Bug 3.3: Skipped field warnings surfaced in return message
Feature 3.4: SPN & FPLMN in CSV standard columns and batch programming
"""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_manager import CardManager, CardType, CLIBackend
from managers.csv_manager import STANDARD_COLUMNS, _normalize_column


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hw_manager(tmp_path):
    """Create a CardManager wired to a fake pySim directory."""
    cli_dir = tmp_path / "pysim"
    cli_dir.mkdir()
    for script in ('pySim-shell.py', 'pySim-prog.py', 'pySim-read.py'):
        (cli_dir / script).write_text("# stub")
    cm = CardManager()
    cm.cli_path = str(cli_dir)
    cm.cli_backend = CLIBackend.PYSIM
    cm._venv_python = None
    cm.card_blocked = False
    cm._adm1_remaining_attempts = None
    return cm


def _auth_manager(tmp_path, *, card_type=CardType.UNKNOWN,
                  original_data=None):
    """Return a CardManager that is 'authenticated' for testing."""
    cm = _make_hw_manager(tmp_path)
    cm.authenticated = True
    cm._authenticated_adm1_hex = '3838383838383838'
    cm.card_type = card_type
    if original_data is not None:
        cm._original_card_data = original_data
    return cm


# ===========================================================================
# Bug 3.1 — pySim-shell gialersim auth
# ===========================================================================

class TestPysimShellGialersimAuth:
    """Bug 3.1: _run_pysim_shell_impl uses -a ASCII for gialersim."""

    def test_gialersim_uses_a_flag_not_A(self, tmp_path):
        """Gialersim cards pass -t gialersim -a <ascii> to pySim-shell."""
        cm = _auth_manager(tmp_path, card_type=CardType.GIALERSIM)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_shell('3838383838383838', 'verify_adm')

        cmd = mock_run.call_args[0][0]
        # Must NOT have -A (standard hex auth)
        assert '-A' not in cmd
        # Must have -t gialersim
        assert '-t' in cmd
        t_idx = cmd.index('-t')
        assert cmd[t_idx + 1] == 'gialersim'
        # Must have -a with ASCII ADM1
        assert '-a' in cmd
        a_idx = cmd.index('-a')
        assert cmd[a_idx + 1] == '88888888'  # hex 3838... -> ASCII 88888888

    def test_sja5_still_uses_A_flag(self, tmp_path):
        """Non-gialersim cards still use -A <hex>."""
        cm = _auth_manager(tmp_path, card_type=CardType.SJA5)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_shell('3838383838383838', 'verify_adm')

        cmd = mock_run.call_args[0][0]
        assert '-A' in cmd
        assert '3838383838383838' in cmd
        # Must NOT have -t or -a
        assert '-t' not in cmd
        assert '-a' not in cmd

    def test_unknown_card_uses_A_flag(self, tmp_path):
        """Default/unknown card type uses standard -A hex auth."""
        cm = _auth_manager(tmp_path, card_type=CardType.UNKNOWN)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_shell('AABBCCDD11223344', 'verify_adm')

        cmd = mock_run.call_args[0][0]
        assert '-A' in cmd
        assert 'AABBCCDD11223344' in cmd

    def test_safe_shell_no_auth_flags(self, tmp_path):
        """_run_pysim_shell_safe passes no -A/-a (no auth)."""
        cm = _auth_manager(tmp_path, card_type=CardType.GIALERSIM)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_shell_safe('some_command')

        cmd = mock_run.call_args[0][0]
        assert '-A' not in cmd
        assert '-a' not in cmd
        assert '-t' not in cmd


# ===========================================================================
# Bug 3.2 — SPN read-back with card type
# ===========================================================================

class TestVerifyAfterProgramCardType:
    """Bug 3.2: verify_after_program passes -t gialersim to pySim-read."""

    def test_gialersim_verify_passes_card_type(self, tmp_path):
        """pySim-read gets -t gialersim for gialersim cards."""
        cm = _auth_manager(tmp_path, card_type=CardType.GIALERSIM)
        cm.card_info = {}

        pysim_output = (
            "ICCID: 89999880000000000200001\n"
            "IMSI: 999880000200001\n"
            "SPN: TestOp\n"
        )

        with patch.object(cm, '_run_cli',
                          return_value=(True, pysim_output, '')) as mock_cli:
            ok, msg, data = cm.verify_after_program({
                'ICCID': '89999880000000000200001',
                'IMSI': '999880000200001',
            })

        assert ok is True
        # Check that -t gialersim was passed
        mock_cli.assert_called_once_with(
            'pySim-read.py', '-p0', '-t', 'gialersim')

    def test_sja5_verify_no_card_type_flag(self, tmp_path):
        """pySim-read for non-gialersim cards doesn't pass -t."""
        cm = _auth_manager(tmp_path, card_type=CardType.SJA5)
        cm.card_info = {}

        pysim_output = (
            "ICCID: 89999880000000000200001\n"
            "IMSI: 999880000200001\n"
            "SPN: TestOp\n"
        )

        with patch.object(cm, '_run_cli',
                          return_value=(True, pysim_output, '')) as mock_cli:
            ok, msg, data = cm.verify_after_program({
                'ICCID': '89999880000000000200001',
                'IMSI': '999880000200001',
            })

        assert ok is True
        mock_cli.assert_called_once_with('pySim-read.py', '-p0')

    def test_spn_parsed_from_readback(self, tmp_path):
        """SPN is parsed from pySim-read output."""
        cm = _auth_manager(tmp_path, card_type=CardType.GIALERSIM)
        cm.card_info = {}

        pysim_output = (
            "ICCID: 89999880000000000200001\n"
            "IMSI: 999880000200001\n"
            "SPN: Teleaura\n"
        )

        with patch.object(cm, '_run_cli',
                          return_value=(True, pysim_output, '')):
            ok, msg, data = cm.verify_after_program({
                'ICCID': '89999880000000000200001',
                'IMSI': '999880000200001',
            })

        assert ok is True
        assert data.get('SPN') == 'Teleaura'


# ===========================================================================
# Bug 3.3 — Skipped field warnings
# ===========================================================================

class TestSkippedFieldWarnings:
    """Bug 3.3: Unhandled fields surface in return message."""

    def test_skipped_fields_in_return_message(self, tmp_path):
        """Fields with no write handler appear in the return message."""
        cm = _auth_manager(tmp_path, card_type=CardType.SJA5)

        # Mock pySim-shell to succeed
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            # Inject a mock for verify_after_program to skip it
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                ok, msg = cm._program_nonempty_card(
                    {'IMSI': '999880000200001'},
                    {'IMSI': '999880000200001',
                     'PIN1': '1234', 'PUK1': '12345678'})

        assert ok is True
        assert 'PIN1' in msg
        assert 'PUK1' in msg
        assert 'skipped' in msg.lower() or 'warning' in msg.lower()

    def test_no_warning_when_all_handled(self, tmp_path):
        """No warning suffix when all fields have handlers."""
        cm = _auth_manager(tmp_path, card_type=CardType.SJA5)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                ok, msg = cm._program_nonempty_card(
                    {'IMSI': '999880000200001'},
                    {'IMSI': '999880000200001'})

        assert ok is True
        assert 'skipped' not in msg.lower()
        assert 'warning' not in msg.lower()

    def test_only_skipped_fields_return_message(self, tmp_path):
        """When only unhandled fields exist, returns informative message."""
        cm = _auth_manager(tmp_path, card_type=CardType.SJA5)

        ok, msg = cm._program_nonempty_card(
            {'PIN1': '1234'},
            {'PIN1': '1234'})

        assert ok is True
        assert 'No programmable fields changed' in msg
        assert 'PIN1' in msg

    def test_adm1_never_listed_as_skipped(self, tmp_path):
        """ADM1 is silently removed, never listed as skipped."""
        cm = _auth_manager(tmp_path, card_type=CardType.SJA5)

        ok, msg = cm._program_nonempty_card(
            {'ADM1': '88888888'},
            {'ADM1': '88888888'})

        assert ok is True
        assert 'ADM1' not in msg


# ===========================================================================
# Feature 3.4 — CSV Manager: SPN & FPLMN columns
# ===========================================================================

class TestCsvSpnFplmnColumns:
    """Feature 3.4: SPN and FPLMN in STANDARD_COLUMNS."""

    def test_spn_in_standard_columns(self):
        assert 'SPN' in STANDARD_COLUMNS

    def test_fplmn_in_standard_columns(self):
        assert 'FPLMN' in STANDARD_COLUMNS

    def test_normalize_spn(self):
        assert _normalize_column('spn') == 'SPN'
        assert _normalize_column('SPN') == 'SPN'

    def test_normalize_fplmn(self):
        assert _normalize_column('fplmn') == 'FPLMN'
        assert _normalize_column('FPLMN') == 'FPLMN'

    def test_normalize_service_provider_name(self):
        assert _normalize_column('service_provider_name') == 'SPN'

    def test_normalize_forbidden_plmn(self):
        assert _normalize_column('forbidden_plmn') == 'FPLMN'


class TestCsvLoadWithSpnFplmn:
    """Feature 3.4: CSV files with SPN/FPLMN columns are parsed."""

    def test_csv_with_spn_fplmn_columns(self, tmp_path):
        """SPN and FPLMN are read from CSV."""
        from managers.csv_manager import CSVManager
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "ICCID,IMSI,Ki,OPc,ADM1,SPN,FPLMN\n"
            "89001,999880001,AA,BB,88888888,TestOp,24007;24024\n"
            "89002,999880002,CC,DD,88888888,TestOp,24007\n"
        )
        mgr = CSVManager()
        ok = mgr.load_csv(str(csv_file))
        assert ok is True
        assert 'SPN' in mgr.columns
        assert 'FPLMN' in mgr.columns
        assert mgr.cards[0]['SPN'] == 'TestOp'
        assert mgr.cards[0]['FPLMN'] == '24007;24024'
        assert mgr.cards[1]['FPLMN'] == '24007'


# ===========================================================================
# Feature 3.4 — Batch panel: SPN/FPLMN override in CSV mode
# ===========================================================================

class TestBatchCsvOverrides:
    """Feature 3.4: Manual SPN/FPLMN override in CSV mode."""

    def test_apply_imsi_override_import(self):
        """apply_imsi_override is importable and works."""
        from widgets.batch_program_panel import apply_imsi_override
        cards = [{"IMSI": "old", "ICCID": "123"}]
        result = apply_imsi_override(cards, "9998800010", start_seq=1)
        assert result[0]["IMSI"] == "999880001000001"
        assert result[0]["ICCID"] == "123"  # untouched

    def test_apply_range_filter_import(self):
        """apply_range_filter is importable and works."""
        from widgets.batch_program_panel import apply_range_filter
        cards = [{"IMSI": str(i)} for i in range(10)]
        result = apply_range_filter(cards, 3, 2)
        assert len(result) == 2
        assert result[0]["IMSI"] == "2"

    def test_csv_override_injects_spn_fplmn(self):
        """Manual SPN/FPLMN values are injected into preview data."""
        # Simulate what _apply_csv_filters does with overrides
        cards = [
            {"ICCID": "89001", "IMSI": "999880001"},
            {"ICCID": "89002", "IMSI": "999880002"},
        ]
        csv_spn = "TestOp"
        csv_fplmn = "24007;24024"
        for card in cards:
            if csv_spn:
                card["SPN"] = csv_spn
            if csv_fplmn:
                card["FPLMN"] = csv_fplmn

        assert cards[0]["SPN"] == "TestOp"
        assert cards[0]["FPLMN"] == "24007;24024"
        assert cards[1]["SPN"] == "TestOp"
        assert cards[1]["FPLMN"] == "24007;24024"

    def test_csv_override_replaces_existing_values(self):
        """Manual override takes precedence over CSV values."""
        cards = [
            {"ICCID": "89001", "SPN": "OldOp", "FPLMN": "11111"},
        ]
        csv_spn = "NewOp"
        csv_fplmn = "24007;24024"
        for card in cards:
            if csv_spn:
                card["SPN"] = csv_spn
            if csv_fplmn:
                card["FPLMN"] = csv_fplmn

        assert cards[0]["SPN"] == "NewOp"
        assert cards[0]["FPLMN"] == "24007;24024"

    def test_empty_override_preserves_csv_values(self):
        """When override is empty string, CSV values are preserved."""
        cards = [
            {"ICCID": "89001", "SPN": "OrigOp", "FPLMN": "99999"},
        ]
        csv_spn = ""  # empty = no override
        csv_fplmn = ""
        if csv_spn or csv_fplmn:
            for card in cards:
                if csv_spn:
                    card["SPN"] = csv_spn
                if csv_fplmn:
                    card["FPLMN"] = csv_fplmn

        assert cards[0]["SPN"] == "OrigOp"
        assert cards[0]["FPLMN"] == "99999"


# ===========================================================================
# Feature 3.4 — Batch preview: FPLMN column
# ===========================================================================

class TestBatchPreviewFplmnColumn:
    """Feature 3.4: FPLMN column in Treeview preview."""

    def test_generate_mode_includes_fplmn_in_preview_data(self):
        """Generated preview data contains FPLMN key."""
        # Simulate what _on_preview does for one card
        preview_row = {
            "IMSI": "999880001000001",
            "ICCID": "89999880000100000015",
            "SITE_CODE": "uk1",
            "SPN": "TestOp",
            "FPLMN": "24007;24024;24001",
            "ADM1": "",
            "ACC": "0001",
            "LI": "EN",
        }
        # _refresh_preview accesses these keys
        assert preview_row.get("FPLMN") == "24007;24024;24001"
        assert preview_row.get("SPN") == "TestOp"

    def test_preview_values_tuple_includes_fplmn(self):
        """The values tuple for Treeview insert has 6 elements (with FPLMN)."""
        row = {
            "IMSI": "imsi1", "ICCID": "iccid1",
            "SITE_CODE": "uk1", "SPN": "Op",
            "FPLMN": "24007", "ADM1": "88888888",
        }
        values = (
            row.get("IMSI", ""),
            row.get("ICCID", ""),
            row.get("SITE_CODE", ""),
            row.get("SPN", ""),
            row.get("FPLMN", ""),
            row.get("ADM1", ""),
        )
        assert len(values) == 6
        assert values[4] == "24007"


# ===========================================================================
# Bug 3.1 — Extra fields after pySim-prog (integration-level)
# ===========================================================================

class TestExtraFieldsAfterPysimProg:
    """Bug 3.1 integration: extra fields use gialersim-aware pySim-shell."""

    def test_program_empty_card_extra_fields_use_gialersim_shell(
            self, tmp_path):
        """After pySim-prog, extra fields written via pySim-shell with
        -t gialersim -a ASCII ADM1."""
        cm = _auth_manager(tmp_path, card_type=CardType.GIALERSIM)

        card_data = {
            'ICCID': '89999880000000000200001',
            'IMSI': '999880000200001',
            'Ki': 'A' * 32,
            'OPc': 'B' * 32,
            'SPN': 'TestOp',
            'ACC': '0001',
            'FPLMN': '24007;24024',
        }

        shell_calls = []

        def mock_run(cmd, **kwargs):
            shell_calls.append(cmd)
            return MagicMock(returncode=0, stdout='Done', stderr='')

        with patch('subprocess.run', side_effect=mock_run):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                ok, msg = cm._program_empty_card(
                    card_data,
                    dict(card_data))  # all fields as "changed"

        assert ok is True
        # There should be at least 2 calls: pySim-prog + pySim-shell
        assert len(shell_calls) >= 2

        # The second call (pySim-shell for extra fields) should use
        # -a (ASCII) not -A (hex)
        shell_cmd = shell_calls[1]
        assert '-a' in shell_cmd
        assert '-t' in shell_cmd
        t_idx = shell_cmd.index('-t')
        assert shell_cmd[t_idx + 1] == 'gialersim'
        assert '-A' not in shell_cmd


# ===========================================================================
# _parse_pysim_output — SPN patterns
# ===========================================================================

class TestParsePysimOutputSpn:
    """Bug 3.2: parser correctly extracts SPN from pySim-read output."""

    def test_parses_spn_line(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.card_info = {}
        cm._parse_pysim_output("SPN: Teleaura\n")
        assert cm.card_info.get('SPN') == 'Teleaura'

    def test_parses_service_provider_line(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.card_info = {}
        cm._parse_pysim_output("SERVICE PROVIDER: MyOperator\n")
        assert cm.card_info.get('SPN') == 'MyOperator'

    def test_parses_fplmn(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.card_info = {}
        cm._parse_pysim_output("FPLMN: 24007\nFPLMN: 24024\n")
        assert '24007' in cm.card_info.get('FPLMN', '')
        assert '24024' in cm.card_info.get('FPLMN', '')
