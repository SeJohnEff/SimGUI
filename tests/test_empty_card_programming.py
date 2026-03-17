"""Tests for empty (blank) card programming — v0.5.14.

Validates:
- Empty card detection (``_is_empty_card``)
- ``_run_pysim_prog`` builds the correct CLI command
- ``_program_empty_card`` uses pySim-prog, falls back to pySim-shell
- ``_program_nonempty_card`` still works as before (pySim-shell delta)
- ``program_card`` routes empty vs non-empty correctly
- ``authenticate`` handles blank-card init failures gracefully
- ``_run_pysim_shell`` without ``--noprompt`` detects init failures via output scanning
- FPLMN (extra field) follow-up after pySim-prog succeeds
"""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_manager import CardManager, CardType, CLIBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hw_manager(tmp_path):
    """Create a CardManager wired to a fake pySim directory."""
    cli_dir = tmp_path / "pysim"
    cli_dir.mkdir()
    # Create dummy scripts so _validate_script_path accepts them
    for script in ('pySim-shell.py', 'pySim-prog.py', 'pySim-read.py'):
        (cli_dir / script).write_text("# stub")
    cm = CardManager()
    cm.cli_path = str(cli_dir)
    cm.cli_backend = CLIBackend.PYSIM
    cm._venv_python = None
    cm.card_blocked = False
    cm._adm1_remaining_attempts = None
    return cm


def _auth_manager(tmp_path, *, original_data=None):
    """Return a CardManager that is 'authenticated' for testing."""
    cm = _make_hw_manager(tmp_path)
    cm.authenticated = True
    cm._authenticated_adm1_hex = '3838383838383838'
    if original_data is not None:
        cm._original_card_data = original_data
    return cm


# ---------------------------------------------------------------------------
# _is_empty_card
# ---------------------------------------------------------------------------

class TestIsEmptyCard:

    def test_none_original_and_empty_stored(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        assert cm._is_empty_card(None) is True

    def test_empty_dict_original(self, tmp_path):
        cm = _auth_manager(tmp_path)
        # Empty dict is falsy -> empty card
        assert cm._is_empty_card({}) is True

    def test_nonempty_original(self, tmp_path):
        cm = _auth_manager(tmp_path)
        assert cm._is_empty_card({'ICCID': '123'}) is False

    def test_none_with_stored_data(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={'ICCID': '123'})
        assert cm._is_empty_card(None) is False


# ---------------------------------------------------------------------------
# _run_pysim_prog
# ---------------------------------------------------------------------------

class TestRunPysimProg:

    def test_builds_correct_command(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        card_data = {
            'ICCID': '8946200000000000001',
            'IMSI': '240077000000001',
            'Ki': 'A' * 32,
            'OPc': 'B' * 32,
            'SPN': 'TestOP',
            'ACC': '0001',
        }
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='Done', stderr='')
            ok, stdout, stderr = cm._run_pysim_prog(
                card_data, '3838383838383838')

        assert ok is True
        cmd = mock_run.call_args[0][0]
        assert 'pySim-prog.py' in cmd[1]
        assert '-p0' in cmd
        assert '-A' in cmd
        assert '3838383838383838' in cmd
        assert '-s' in cmd  # ICCID
        assert '-i' in cmd  # IMSI
        assert '-k' in cmd  # Ki
        assert '-o' in cmd  # OPc
        assert '-n' in cmd  # SPN
        assert '--acc' in cmd  # ACC
        # MCC/MNC from IMSI
        assert '-x' in cmd
        idx_x = cmd.index('-x')
        assert cmd[idx_x + 1] == '240'
        idx_y = cmd.index('-y')
        assert cmd[idx_y + 1] == '07'

    def test_missing_fields_not_added(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        card_data = {'IMSI': '240077000000001'}
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_prog(card_data, '3838383838383838')

        cmd = mock_run.call_args[0][0]
        assert '-s' not in cmd  # no ICCID
        assert '-k' not in cmd  # no Ki
        assert '-o' not in cmd  # no OPc

    def test_returns_failure_on_nonzero_exit(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout='', stderr='Card error')
            ok, stdout, stderr = cm._run_pysim_prog(
                {'IMSI': '123'}, '3838383838383838')
        assert ok is False
        assert 'Card error' in stderr

    def test_returns_failure_when_no_cli_path(self):
        cm = CardManager()
        cm.cli_path = None
        ok, _, stderr = cm._run_pysim_prog({}, 'DEADBEEF')
        assert ok is False
        assert 'not found' in stderr

    def test_timeout_returns_failure(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run',
                   side_effect=subprocess.TimeoutExpired(cmd='x', timeout=60)):
            ok, _, stderr = cm._run_pysim_prog(
                {'IMSI': '123'}, '3838383838383838')
        assert ok is False
        assert 'timed out' in stderr


# ---------------------------------------------------------------------------
# _run_pysim_shell (interactive stdin + init-failure detection)
# ---------------------------------------------------------------------------

class TestRunPysimShellInitDetection:

    def test_noprompt_flag_NOT_present(self, tmp_path):
        """--noprompt must NOT be used — it prevents stdin command processing."""
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_shell('DEADBEEF', 'verify_adm')
        cmd = mock_run.call_args[0][0]
        assert '--noprompt' not in cmd
        # -A flag should still be present when using _run_pysim_shell
        assert '-A' in cmd
        assert 'DEADBEEF' in cmd
        # stdin must pipe commands with 'quit' appended
        call_kwargs = mock_run.call_args.kwargs
        assert 'input' in call_kwargs
        assert 'quit' in call_kwargs['input']

    def test_detects_not_equipped(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='pySim-shell not equipped!',
                stderr='')
            ok, stdout, stderr = cm._run_pysim_shell(
                'DEADBEEF', 'verify_adm')
        # Must report failure even though exit code was 0
        assert ok is False

    def test_detects_card_error(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='Card error, cannot do ADM verification',
                stderr='')
            ok, _, _ = cm._run_pysim_shell('DEADBEEF', 'verify_adm')
        assert ok is False

    def test_detects_autodetection_failed(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='Autodetection failed\nWarning: Could not detect',
                stderr='')
            ok, _, _ = cm._run_pysim_shell('DEADBEEF', 'verify_adm')
        assert ok is False

    def test_normal_success_not_affected(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='pySIM-shell (00:MF)> verify_adm\n9000',
                stderr='')
            ok, _, _ = cm._run_pysim_shell('DEADBEEF', 'verify_adm')
        assert ok is True


# ---------------------------------------------------------------------------
# authenticate() for blank cards
# ---------------------------------------------------------------------------

class TestAuthenticateBlankCard:

    def test_blank_card_skips_verify_and_stores_adm1(self, tmp_path):
        """Blank card: VERIFY is never sent; ADM1 is stored for pySim-prog."""
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = {}  # empty card
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe') as mock_shell:
            ok, msg = cm.authenticate('88888888')
        assert ok is True
        assert cm.authenticated is True
        assert cm._authenticated_adm1_hex == '3838383838383838'
        assert 'stored' in msg.lower() or 'blank' in msg.lower()
        # VERIFY must never be called on blank cards
        mock_shell.assert_not_called()

    def test_blank_card_skips_verify_with_none_original(self, tmp_path):
        """Blank card (None original data): same early-return path."""
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = None  # type: ignore[assignment]
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe') as mock_shell:
            ok, msg = cm.authenticate('88888888')
        assert ok is True
        assert cm.authenticated is True
        mock_shell.assert_not_called()

    def test_nonempty_card_init_failure_is_real_error(self, tmp_path):
        """Non-empty card: init failure is a genuine auth problem."""
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = {'ICCID': '123'}  # non-empty
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe',
                          return_value=(False,
                                        'pySim-shell not equipped!',
                                        '')):
            ok, msg = cm.authenticate('88888888')
        assert ok is False

    def test_nonempty_card_wrong_adm1_fails(self, tmp_path):
        """Non-empty card with wrong ADM1 (6982) returns failure."""
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = {'ICCID': '123'}  # non-empty
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe',
                          return_value=(False,
                                        'SW Mismatch 6982',
                                        '')):
            ok, msg = cm.authenticate('12345678')
        assert ok is False
        assert 'wrong adm1' in msg.lower() or 'failed' in msg.lower()

    def test_blank_card_with_acc_but_no_iccid_imsi(self, tmp_path):
        """Blank gialersim card: has ACC from pySim-read but no ICCID/IMSI."""
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = {'ACC': 'ffff'}  # partial read, no ICCID/IMSI
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe') as mock_shell:
            ok, msg = cm.authenticate('88888888')
        assert ok is True
        assert cm.authenticated is True
        assert 'stored' in msg.lower() or 'blank' in msg.lower()
        mock_shell.assert_not_called()

    def test_gialersim_card_skips_verify(self, tmp_path):
        """Gialersim card type always skips VERIFY (uses CHV 0x0C internally)."""
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm.card_type = CardType.GIALERSIM
        cm._original_card_data = {'ACC': 'ffff'}  # has some data
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe') as mock_shell:
            ok, msg = cm.authenticate('88888888')
        assert ok is True
        assert cm.authenticated is True
        assert 'gialersim' in msg.lower()
        mock_shell.assert_not_called()


# ---------------------------------------------------------------------------
# Card type detection from pySim-read output
# ---------------------------------------------------------------------------

class TestCardTypeDetection:

    def test_gialersim_detected(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        output = (
            "Reading ...\n"
            "Autodetected card type: gialersim\n"
            "ICCID: \n"
            "IMSI: None\n"
            "ACC: ffff\n"
        )
        cm._parse_pysim_output(output)
        assert cm.card_type == CardType.GIALERSIM
        assert cm.card_info.get('ICCID') is None  # empty = not stored

    def test_sja5_detected(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        output = (
            "Autodetected card type: sysmoISIM-SJA5\n"
            "ICCID: 8988211000000001234\n"
            "IMSI: 999700000001234\n"
        )
        cm._parse_pysim_output(output)
        assert cm.card_type == CardType.SJA5
        assert cm.card_info.get('ICCID') == '8988211000000001234'

    def test_unknown_type_stays_unknown(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        output = "Autodetected card type: somethingNew\n"
        cm._parse_pysim_output(output)
        assert cm.card_type == CardType.UNKNOWN


# ---------------------------------------------------------------------------
# _is_empty_card routing (gialersim-aware)
# ---------------------------------------------------------------------------

class TestIsEmptyCardGialersim:

    def test_no_original_data(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm._original_card_data = {}
        assert cm._is_empty_card(None) is True

    def test_original_with_iccid_is_not_empty(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm._original_card_data = {'ICCID': '123', 'IMSI': '456'}
        assert cm._is_empty_card(None) is False

    def test_acc_only_no_iccid_imsi_is_empty(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm._original_card_data = {'ACC': 'ffff'}
        assert cm._is_empty_card(None) is True

    def test_gialersim_always_empty(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.card_type = CardType.GIALERSIM
        cm._original_card_data = {'ICCID': '123', 'IMSI': '456'}
        assert cm._is_empty_card(None) is True


# ---------------------------------------------------------------------------
# Hex-to-ASCII conversion
# ---------------------------------------------------------------------------

class TestHexToAdm1Ascii:

    def test_standard_conversion(self):
        from managers.card_manager import CardManager
        assert CardManager._hex_to_adm1_ascii('3838383838383838') == '88888888'

    def test_non_printable_returns_hex(self):
        from managers.card_manager import CardManager
        assert CardManager._hex_to_adm1_ascii('0001020304050607') == '0001020304050607'

    def test_arbitrary_ascii(self):
        from managers.card_manager import CardManager
        assert CardManager._hex_to_adm1_ascii('3332363237323431') == '32627241'


# ---------------------------------------------------------------------------
# program_card() routing
# ---------------------------------------------------------------------------

class TestProgramCardRouting:

    def test_empty_card_routes_to_pysim_prog(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        with patch.object(cm, '_program_empty_card',
                          return_value=(True, 'OK')) as mock_empty:
            with patch.object(cm, '_program_nonempty_card') as mock_non:
                ok, msg = cm.program_card(
                    {'IMSI': '123', 'Ki': 'A' * 32, 'OPc': 'B' * 32},
                    original_data=None)
        mock_empty.assert_called_once()
        mock_non.assert_not_called()
        assert ok is True

    def test_nonempty_card_routes_to_pysim_shell(self, tmp_path):
        cm = _auth_manager(tmp_path,
                           original_data={'ICCID': '999', 'IMSI': 'old'})
        with patch.object(cm, '_program_empty_card') as mock_empty:
            with patch.object(cm, '_program_nonempty_card',
                              return_value=(True, 'OK')) as mock_non:
                ok, msg = cm.program_card(
                    {'ICCID': '999', 'IMSI': 'new'},
                    original_data={'ICCID': '999', 'IMSI': 'old'})
        mock_empty.assert_not_called()
        mock_non.assert_called_once()
        assert ok is True

    def test_no_changes_returns_early(self, tmp_path):
        cm = _auth_manager(tmp_path,
                           original_data={'IMSI': '123'})
        ok, msg = cm.program_card(
            {'IMSI': '123'},
            original_data={'IMSI': '123'})
        assert ok is True
        assert 'no changes' in msg.lower()


# ---------------------------------------------------------------------------
# _program_empty_card
# ---------------------------------------------------------------------------

class TestProgramEmptyCard:

    def test_pysim_prog_success_with_verify(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        changed = {
            'ICCID': '123', 'IMSI': '456',
            'Ki': 'A' * 32, 'OPc': 'B' * 32,
        }
        card_data = dict(changed)
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(True, 'Done', '')):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {'ICCID': '123'})):
                ok, msg = cm._program_empty_card(card_data, changed)
        assert ok is True
        assert 'verified' in msg.lower()

    def test_pysim_prog_success_verify_fails_still_ok(self, tmp_path):
        """pySim-prog succeeded — trust it even if verify can't confirm."""
        cm = _auth_manager(tmp_path, original_data={})
        changed = {'IMSI': '456'}
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(True, 'Done', '')):
            with patch.object(cm, 'verify_after_program',
                              return_value=(False, 'read failed', {})):
                ok, msg = cm._program_empty_card({'IMSI': '456'}, changed)
        assert ok is True
        assert 're-insert' in msg.lower() or 'could not confirm' in msg.lower()

    def test_pysim_prog_missing_falls_back_to_shell(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        changed = {'IMSI': '456', 'Ki': 'A' * 32, 'OPc': 'B' * 32}
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(False, '', 'pySim-prog.py not found')):
            with patch.object(cm, '_program_nonempty_card',
                              return_value=(True, 'Shell OK')) as mock_shell:
                ok, msg = cm._program_empty_card(
                    {'IMSI': '456', 'Ki': 'A' * 32, 'OPc': 'B' * 32},
                    changed)
        mock_shell.assert_called_once()
        assert ok is True

    def test_pysim_prog_genuine_failure(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        changed = {'IMSI': '456'}
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(False, '', 'Card communication error')):
            ok, msg = cm._program_empty_card({'IMSI': '456'}, changed)
        assert ok is False
        assert 'failed' in msg.lower()

    def test_extra_fields_written_via_shell_after_prog(self, tmp_path):
        """FPLMN is not supported by pySim-prog -> follow-up shell call."""
        cm = _auth_manager(tmp_path, original_data={})
        changed = {
            'IMSI': '456', 'Ki': 'A' * 32, 'OPc': 'B' * 32,
            'FPLMN': '24007;24024',
        }
        card_data = dict(changed)

        with patch.object(cm, '_run_pysim_prog',
                          return_value=(True, 'Done', '')):
            with patch.object(cm, '_program_nonempty_card',
                              return_value=(True, 'Shell OK')) as mock_shell:
                with patch.object(cm, 'verify_after_program',
                                  return_value=(True, 'OK', {})):
                    ok, msg = cm._program_empty_card(card_data, changed)

        # _program_nonempty_card should have been called with FPLMN
        mock_shell.assert_called_once()
        extra_changed = mock_shell.call_args[0][1]
        assert 'FPLMN' in extra_changed
        assert 'IMSI' not in extra_changed  # prog fields handled by prog
        assert ok is True


# ---------------------------------------------------------------------------
# _program_nonempty_card (preserved from v0.5.8)
# ---------------------------------------------------------------------------

class TestProgramNonemptyCard:

    def test_delta_write_only_changed(self, tmp_path):
        cm = _auth_manager(tmp_path)
        changed = {'IMSI': 'new_imsi'}
        card_data = {'ICCID': '999', 'IMSI': 'new_imsi'}
        with patch.object(cm, '_run_pysim_shell',
                          return_value=(True, '', '')) as mock_shell:
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                ok, msg = cm._program_nonempty_card(card_data, changed)
        assert ok is True
        # First arg is ADM1 hex, second is commands
        adm1_hex = mock_shell.call_args[0][0]
        commands = mock_shell.call_args[0][1]
        assert adm1_hex  # ADM1 hex key passed via -A flag
        assert 'verify_adm' not in commands  # No double-auth
        assert 'EF.IMSI' in commands
        assert 'EF.ICCID' not in commands  # ICCID not changed

    def test_shell_failure_returns_error(self, tmp_path):
        cm = _auth_manager(tmp_path)
        changed = {'IMSI': '123'}
        with patch.object(cm, '_run_pysim_shell',
                          return_value=(False, '', 'SW mismatch')):
            ok, msg = cm._program_nonempty_card(
                {'IMSI': '123'}, changed)
        assert ok is False

    def test_ki_opc_written_together(self, tmp_path):
        cm = _auth_manager(tmp_path)
        changed = {'Ki': 'A' * 32, 'OPc': 'B' * 32}
        with patch.object(cm, '_run_pysim_shell',
                          return_value=(True, '', '')) as mock_shell:
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                cm._program_nonempty_card(
                    {'Ki': 'A' * 32, 'OPc': 'B' * 32}, changed)
        commands = mock_shell.call_args[0][1]
        assert 'USIM_AUTH_KEY' in commands

    def test_adm1_never_written(self, tmp_path):
        """ADM1 field value is not written as data (auth is via -A flag)."""
        cm = _auth_manager(tmp_path)
        changed = {'ADM1': '88888888', 'IMSI': '123'}
        with patch.object(cm, '_run_pysim_shell',
                          return_value=(True, '', '')) as mock_shell:
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                cm._program_nonempty_card(
                    {'ADM1': '88888888', 'IMSI': '123'}, changed)
        commands = mock_shell.call_args[0][1]
        # ADM1 as a field name should never appear in write commands
        assert 'ADM1' not in commands


# ---------------------------------------------------------------------------
# Integration-style test: full flow from program_card
# ---------------------------------------------------------------------------

class TestProgramCardIntegration:

    def test_empty_card_full_flow(self, tmp_path):
        """Empty card: program_card -> _program_empty_card -> pySim-prog."""
        cm = _auth_manager(tmp_path, original_data={})
        card_data = {
            'ICCID': '8946200000000000001',
            'IMSI': '240077000000001',
            'Ki': 'A' * 32,
            'OPc': 'B' * 32,
            'ADM1': '88888888',
            'SPN': 'TestOP',
        }
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(True, 'Done', '')) as mock_prog:
            with patch.object(cm, 'verify_after_program',
                              return_value=(
                                  True, 'OK',
                                  {'ICCID': card_data['ICCID']})):
                ok, msg = cm.program_card(card_data, original_data=None)

        assert ok is True
        mock_prog.assert_called_once()
        # ADM1 should NOT be in the prog_fields
        prog_fields = mock_prog.call_args[0][0]
        assert 'ADM1' not in prog_fields

    def test_nonempty_card_full_flow(self, tmp_path):
        """Non-empty card: program_card -> _program_nonempty_card."""
        orig = {'ICCID': '999', 'IMSI': 'old', 'Ki': 'C' * 32,
                'OPc': 'D' * 32}
        cm = _auth_manager(tmp_path, original_data=orig)
        card_data = dict(orig)
        card_data['IMSI'] = 'new_imsi'
        with patch.object(cm, 'check_adm1_retry_counter',
                          return_value=3):
            with patch.object(cm, '_run_pysim_shell',
                              return_value=(True, '', '')) as mock_shell:
                with patch.object(cm, 'verify_after_program',
                                  return_value=(True, 'OK', {})):
                    ok, msg = cm.program_card(card_data, original_data=orig)

        assert ok is True
        mock_shell.assert_called_once()
        # First arg is ADM1 hex (-A flag), second is write commands
        adm1_hex = mock_shell.call_args[0][0]
        commands = mock_shell.call_args[0][1]
        assert adm1_hex  # -A flag auth
        assert 'verify_adm' not in commands  # No double-auth
        assert 'EF.IMSI' in commands
        assert 'USIM_AUTH_KEY' not in commands

    def test_original_data_empty_dict_treated_as_empty_card(self, tmp_path):
        """Empty dict passed via `or None` pattern is treated as empty card."""
        cm = _auth_manager(tmp_path, original_data={})
        card_data = {'IMSI': '123', 'Ki': 'A' * 32, 'OPc': 'B' * 32}
        # Simulates: program_card(card_data, original_data={} or None)
        # {} or None == None, so original_data=None
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(True, 'Done', '')):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                ok, _ = cm.program_card(card_data, original_data=None)
        assert ok is True
