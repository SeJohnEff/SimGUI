"""Tests for card programming — v0.5.32 unified pySim-prog path.

Validates:
- Empty card detection (``_is_empty_card``)
- ``_run_pysim_prog`` builds the correct CLI command
- ``_run_pysim_shell_safe`` detects init failures via output scanning
- ``authenticate`` handles blank-card init failures gracefully
- ``program_card`` routes ALL card types through ``_program_via_pysim_prog``
- Non-empty delta-write: only changed fields forwarded, ICCID excluded
- Ki/OPc pair-write invariant preserved for non-empty cards
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
        assert '-s' in cmd
        assert '-i' in cmd
        assert '-k' in cmd
        assert '-o' in cmd
        assert '-n' in cmd
        assert '--acc' in cmd
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
        assert '-s' not in cmd
        assert '-k' not in cmd
        assert '-o' not in cmd

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

    def test_fplmn_flags_added(self, tmp_path):
        """Each FPLMN entry gets its own -f flag."""
        cm = _make_hw_manager(tmp_path)
        card_data = {'FPLMN': '24007;24001'}
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_prog(card_data, '3838383838383838')

        cmd = mock_run.call_args[0][0]
        assert cmd.count('-f') == 2

    def test_gialersim_uses_ascii_adm1(self, tmp_path):
        """Gialersim cards use -a (ASCII) not -A (hex)."""
        cm = _make_hw_manager(tmp_path)
        cm.card_type = CardType.GIALERSIM
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_prog({'IMSI': '123'}, '3838383838383838')

        cmd = mock_run.call_args[0][0]
        assert '-a' in cmd
        assert '-A' not in cmd
        assert '88888888' in cmd


# ---------------------------------------------------------------------------
# _run_pysim_shell_safe (stdin + init-failure detection)
# ---------------------------------------------------------------------------

class TestRunPysimShellSafeInitDetection:

    def test_noprompt_flag_NOT_present(self, tmp_path):
        """--noprompt must NOT be used — it prevents stdin command processing."""
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_shell_safe('verify_adm')
        cmd = mock_run.call_args[0][0]
        assert '--noprompt' not in cmd
        call_kwargs = mock_run.call_args.kwargs
        assert 'input' in call_kwargs
        assert 'quit' in call_kwargs['input']

    def test_no_A_flag_in_safe_mode(self, tmp_path):
        """-A flag must NOT be present in safe (no-auth) mode."""
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='', stderr='')
            cm._run_pysim_shell_safe('verify_adm')
        cmd = mock_run.call_args[0][0]
        assert '-A' not in cmd

    def test_detects_not_equipped(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='pySim-shell not equipped!',
                stderr='')
            ok, stdout, stderr = cm._run_pysim_shell_safe('verify_adm')
        assert ok is False

    def test_detects_card_error(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='Card error, cannot do ADM verification',
                stderr='')
            ok, _, _ = cm._run_pysim_shell_safe('verify_adm')
        assert ok is False

    def test_detects_autodetection_failed(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='Autodetection failed\nWarning: Could not detect',
                stderr='')
            ok, _, _ = cm._run_pysim_shell_safe('verify_adm')
        assert ok is False

    def test_normal_success_not_affected(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='pySIM-shell (00:MF)> verify_adm\n9000',
                stderr='')
            ok, _, _ = cm._run_pysim_shell_safe('verify_adm')
        assert ok is True


# ---------------------------------------------------------------------------
# authenticate() for blank cards
# ---------------------------------------------------------------------------

class TestAuthenticateBlankCard:

    def test_blank_card_skips_verify_and_stores_adm1(self, tmp_path):
        """Blank card: VERIFY is never sent; ADM1 is stored for pySim-prog."""
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = {}
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe') as mock_shell:
            ok, msg = cm.authenticate('88888888')
        assert ok is True
        assert cm.authenticated is True
        assert cm._authenticated_adm1_hex == '3838383838383838'
        assert 'stored' in msg.lower() or 'blank' in msg.lower()
        mock_shell.assert_not_called()

    def test_blank_card_skips_verify_with_none_original(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = {}
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe') as mock_shell:
            ok, msg = cm.authenticate('88888888')
        assert ok is True
        assert cm.authenticated is True
        mock_shell.assert_not_called()

    def test_nonempty_card_init_failure_is_real_error(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = {'ICCID': '123'}
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe',
                          return_value=(False,
                                        'pySim-shell not equipped!',
                                        '')):
            ok, msg = cm.authenticate('88888888')
        assert ok is False

    def test_nonempty_card_wrong_adm1_fails(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = {'ICCID': '123'}
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe',
                          return_value=(False,
                                        'SW Mismatch 6982',
                                        '')):
            ok, msg = cm.authenticate('12345678')
        assert ok is False
        assert 'wrong adm1' in msg.lower() or 'failed' in msg.lower()

    def test_blank_card_with_acc_but_no_iccid_imsi(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._original_card_data = {'ACC': 'ffff'}
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3), \
             patch.object(cm, '_run_pysim_shell_safe') as mock_shell:
            ok, msg = cm.authenticate('88888888')
        assert ok is True
        assert cm.authenticated is True
        assert 'stored' in msg.lower() or 'blank' in msg.lower()
        mock_shell.assert_not_called()

    def test_gialersim_card_skips_verify(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm.card_type = CardType.GIALERSIM
        cm._original_card_data = {'ACC': 'ffff'}
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
        assert cm.card_info.get('ICCID') is None

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

    def test_detect_card_returns_true_for_gialersim_nonzero_exit(self, tmp_path):
        """detect_card returns True when pySim-read autodetects gialersim even
        if pySim-read exits non-zero (blank gialersim: no EFs to read → error
        exit but card IS detected).  This prevents BLANK→ERROR state flip in
        CardWatcher._read_and_notify which causes 'Insert a SIM card...' in
        Program SIM tab despite a card being present."""
        cm = _make_hw_manager(tmp_path)
        stdout = (
            "Reading ...\n"
            "Autodetected card type: gialersim\n"
            "ACC: ffff\n"
        )
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout=stdout, stderr="Some EF read error")
            ok, msg = cm.detect_card()

        assert ok is True, f"detect_card should succeed for blank gialersim; got: {msg}"
        assert cm.card_type == CardType.GIALERSIM
        assert cm._original_card_data is not None

    def test_detect_card_returns_false_no_card_type_in_stdout(self, tmp_path):
        """detect_card returns False when pySim-read fails and output has no
        recognisable card type (genuine reader error, not blank card)."""
        cm = _make_hw_manager(tmp_path)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="No card detected")
            ok, _msg = cm.detect_card()

        assert ok is False


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
        assert CardManager._hex_to_adm1_ascii('3838383838383838') == '88888888'

    def test_non_printable_returns_hex(self):
        assert CardManager._hex_to_adm1_ascii('0001020304050607') == '0001020304050607'

    def test_arbitrary_ascii(self):
        assert CardManager._hex_to_adm1_ascii('3332363237323431') == '32627241'


# ---------------------------------------------------------------------------
# program_card() routing — all types go through _program_via_pysim_prog
# ---------------------------------------------------------------------------

class TestProgramCardRouting:

    def test_empty_card_routes_to_pysim_prog(self, tmp_path):
        """Empty card (no original data) → _program_via_pysim_prog."""
        cm = _auth_manager(tmp_path, original_data={})
        with patch.object(cm, '_program_via_pysim_prog',
                          return_value=(True, 'OK')) as mock_prog:
            ok, msg = cm.program_card(
                {'IMSI': '123', 'Ki': 'A' * 32, 'OPc': 'B' * 32},
                original_data=None)
        mock_prog.assert_called_once()
        assert ok is True

    def test_nonempty_card_routes_to_pysim_prog(self, tmp_path):
        """Non-empty card with a changed field → _program_via_pysim_prog."""
        cm = _auth_manager(tmp_path,
                           original_data={'ICCID': '999', 'IMSI': 'old'})
        with patch.object(cm, '_program_via_pysim_prog',
                          return_value=(True, 'OK')) as mock_prog:
            ok, msg = cm.program_card(
                {'ICCID': '999', 'IMSI': 'new'},
                original_data={'ICCID': '999', 'IMSI': 'old'})
        mock_prog.assert_called_once()
        assert ok is True

    def test_no_changes_returns_early(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={'IMSI': '123'})
        ok, msg = cm.program_card(
            {'IMSI': '123'},
            original_data={'IMSI': '123'})
        assert ok is True
        assert 'no changes' in msg.lower()

    def test_iccid_excluded_from_nonempty_delta(self, tmp_path):
        """ICCID must never be rewritten on a non-empty card."""
        orig = {'ICCID': '999', 'IMSI': 'old'}
        cm = _auth_manager(tmp_path, original_data=orig)
        captured = {}
        def capture(fields):
            captured['fields'] = fields
            return True, 'OK'
        with patch.object(cm, '_program_via_pysim_prog', side_effect=capture):
            cm.program_card({'ICCID': '999', 'IMSI': 'new'}, original_data=orig)
        assert 'ICCID' not in captured.get('fields', {})
        assert 'IMSI' in captured.get('fields', {})

    def test_ki_opc_pair_completed_for_nonempty(self, tmp_path):
        """If Ki changed but OPc unchanged, OPc is still included (same EF)."""
        orig = {'ICCID': '999', 'IMSI': 'x', 'Ki': 'C' * 32, 'OPc': 'D' * 32}
        cm = _auth_manager(tmp_path, original_data=orig)
        card_data = dict(orig)
        card_data['Ki'] = 'A' * 32  # only Ki changed

        captured = {}
        def capture(fields):
            captured['fields'] = fields
            return True, 'OK'
        with patch.object(cm, '_program_via_pysim_prog', side_effect=capture):
            cm.program_card(card_data, original_data=orig)
        assert 'Ki' in captured.get('fields', {})
        assert 'OPc' in captured.get('fields', {})  # paired with Ki


# ---------------------------------------------------------------------------
# _program_via_pysim_prog
# ---------------------------------------------------------------------------

class TestProgramViaPysimProg:

    def test_success_with_verify(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        fields = {'ICCID': '123', 'IMSI': '456', 'Ki': 'A' * 32, 'OPc': 'B' * 32}
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(True, 'Done', '')):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {'ICCID': '123'})):
                ok, msg = cm._program_via_pysim_prog(fields)
        assert ok is True
        assert 'verified' in msg.lower()

    def test_success_verify_fails_still_ok(self, tmp_path):
        """pySim-prog OK — trust it even if verify can't confirm."""
        cm = _auth_manager(tmp_path, original_data={})
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(True, 'Done', '')):
            with patch.object(cm, 'verify_after_program',
                              return_value=(False, 'read failed', {})):
                ok, msg = cm._program_via_pysim_prog({'IMSI': '456'})
        assert ok is True
        assert 're-insert' in msg.lower() or 'could not confirm' in msg.lower()

    def test_prog_failure_returns_error(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(False, '', 'Card communication error')):
            ok, msg = cm._program_via_pysim_prog({'IMSI': '456'})
        assert ok is False
        assert 'failed' in msg.lower()

    def test_not_found_error(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(False, '', 'pySim-prog.py not found')):
            ok, msg = cm._program_via_pysim_prog({'IMSI': '456'})
        assert ok is False
        assert 'not found' in msg.lower()

    def test_adm1_not_forwarded_to_prog(self, tmp_path):
        """ADM1 must not appear as a field in the pySim-prog command."""
        cm = _auth_manager(tmp_path, original_data={})
        fields_passed = {}
        def capture_fields(fields, adm1_hex, **kw):
            fields_passed.update(fields)
            return True, '', ''
        with patch.object(cm, '_run_pysim_prog', side_effect=capture_fields):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                cm._program_via_pysim_prog({'IMSI': '123', 'ADM1': 'secret'})
        # ADM1 is an auth key, not data — it should appear as adm1_hex arg,
        # not as a field key in the fields dict
        assert 'ADM1' not in fields_passed


# ---------------------------------------------------------------------------
# Integration-style: full flow from program_card
# ---------------------------------------------------------------------------

class TestProgramCardIntegration:

    def test_empty_card_full_flow(self, tmp_path):
        """Empty card: program_card → _run_pysim_prog. ADM1 excluded from fields."""
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
                              return_value=(True, 'OK',
                                            {'ICCID': card_data['ICCID']})):
                ok, msg = cm.program_card(card_data, original_data=None)

        assert ok is True
        mock_prog.assert_called_once()
        prog_fields = mock_prog.call_args[0][0]
        assert 'ADM1' not in prog_fields
        assert 'ICCID' in prog_fields
        assert 'IMSI' in prog_fields

    def test_nonempty_card_full_flow(self, tmp_path):
        """Non-empty card: delta → _run_pysim_prog with only changed fields."""
        orig = {'ICCID': '999', 'IMSI': 'old', 'Ki': 'C' * 32,
                'OPc': 'D' * 32}
        cm = _auth_manager(tmp_path, original_data=orig)
        card_data = dict(orig)
        card_data['IMSI'] = 'new_imsi'
        with patch.object(cm, 'check_adm1_retry_counter', return_value=3):
            with patch.object(cm, '_run_pysim_prog',
                              return_value=(True, 'Done', '')) as mock_prog:
                with patch.object(cm, 'verify_after_program',
                                  return_value=(True, 'OK', {})):
                    ok, msg = cm.program_card(card_data, original_data=orig)

        assert ok is True
        mock_prog.assert_called_once()
        prog_fields = mock_prog.call_args[0][0]
        assert 'ICCID' not in prog_fields  # factory-assigned, not changed
        assert 'IMSI' in prog_fields       # only changed field
        assert 'Ki' not in prog_fields     # unchanged
        assert 'OPc' not in prog_fields    # unchanged

    def test_original_data_empty_dict_treated_as_empty_card(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        card_data = {'IMSI': '123', 'Ki': 'A' * 32, 'OPc': 'B' * 32}
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(True, 'Done', '')):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                ok, _ = cm.program_card(card_data, original_data=None)
        assert ok is True
