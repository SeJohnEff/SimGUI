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

    def test_nonempty_card_routes_to_pysim_shell(self, tmp_path):
        """Non-empty card with a changed field → _program_nonempty_card (pySim-shell)."""
        cm = _auth_manager(tmp_path,
                           original_data={'ICCID': '999', 'IMSI': 'old'})
        with patch.object(cm, '_program_nonempty_card',
                          return_value=(True, 'OK')) as mock_shell:
            ok, msg = cm.program_card(
                {'ICCID': '999', 'IMSI': 'new'},
                original_data={'ICCID': '999', 'IMSI': 'old'})
        mock_shell.assert_called_once()
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
        def capture(card_data, changed):
            captured['fields'] = changed
            return True, 'OK'
        with patch.object(cm, '_program_nonempty_card', side_effect=capture):
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
        def capture(card_data, changed):
            captured['fields'] = changed
            return True, 'OK'
        with patch.object(cm, '_program_nonempty_card', side_effect=capture):
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
        assert 'verification pending' in msg.lower() or 'read the card again' in msg.lower()

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
        """Non-empty card: delta → _program_nonempty_card with only changed fields."""
        orig = {'ICCID': '999', 'IMSI': 'old', 'Ki': 'C' * 32,
                'OPc': 'D' * 32}
        cm = _auth_manager(tmp_path, original_data=orig)
        card_data = dict(orig)
        card_data['IMSI'] = 'new_imsi'

        captured = {}
        def capture(card_data, changed):
            captured['changed'] = dict(changed)
            return True, 'OK'

        with patch.object(cm, 'check_adm1_retry_counter', return_value=3):
            with patch.object(cm, '_program_nonempty_card', side_effect=capture):
                ok, msg = cm.program_card(card_data, original_data=orig)

        assert ok is True
        changed = captured.get('changed', {})
        assert 'ICCID' not in changed  # factory-assigned, excluded
        assert 'IMSI' in changed       # only changed field
        assert 'Ki' not in changed     # unchanged
        assert 'OPc' not in changed    # unchanged

    def test_original_data_empty_dict_treated_as_empty_card(self, tmp_path):
        cm = _auth_manager(tmp_path, original_data={})
        card_data = {'IMSI': '123', 'Ki': 'A' * 32, 'OPc': 'B' * 32}
        with patch.object(cm, '_run_pysim_prog',
                          return_value=(True, 'Done', '')):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {})):
                ok, _ = cm.program_card(card_data, original_data=None)
        assert ok is True


# ---------------------------------------------------------------------------
# SJA5 programming path — must use pySim-shell, never pySim-prog
# ---------------------------------------------------------------------------

def _sja5_auth_manager(tmp_path):
    cm = _make_hw_manager(tmp_path)
    cm.card_type = CardType.SJA5
    cm._original_card_data = {
        'ICCID': '8946001234567890123',
        'IMSI': '240070000000001',
        'Ki': 'C' * 32,
        'OPc': 'D' * 32,
    }
    cm.authenticated = True
    cm._authenticated_adm1_hex = '3838383838383838'
    return cm


class TestSJA5ProgrammingPath:
    """SJA5 cards must use pySim-shell for delta-writes; pySim-prog never called."""

    def test_sja5_program_card_does_not_call_run_pysim_prog(self, tmp_path):
        """program_card for SJA5 must not call _run_pysim_prog."""
        cm = _sja5_auth_manager(tmp_path)
        orig = dict(cm._original_card_data)
        card_data = dict(orig)
        card_data['IMSI'] = '240070000000002'

        prog_called = []
        def fake_prog(*a, **kw):
            prog_called.append(True)
            return True, 'Should not be called', ''

        with patch.object(cm, '_run_pysim_prog', side_effect=fake_prog):
            with patch.object(cm, '_program_nonempty_card',
                              return_value=(True, 'OK')):
                cm.program_card(card_data, original_data=orig)

        assert not prog_called, "_run_pysim_prog must not be called for SJA5"

    def test_sja5_program_card_calls_program_nonempty_card(self, tmp_path):
        """program_card for SJA5 routes to _program_nonempty_card (pySim-shell)."""
        cm = _sja5_auth_manager(tmp_path)
        orig = dict(cm._original_card_data)
        card_data = dict(orig)
        card_data['IMSI'] = '240070000000002'

        with patch.object(cm, '_program_nonempty_card',
                          return_value=(True, 'OK')) as mock_shell:
            cm.program_card(card_data, original_data=orig)

        mock_shell.assert_called_once()

    def test_sja5_delta_excludes_iccid(self, tmp_path):
        """ICCID is never rewritten for SJA5 (factory-assigned)."""
        cm = _sja5_auth_manager(tmp_path)
        orig = dict(cm._original_card_data)
        card_data = dict(orig)
        card_data['IMSI'] = '240070000000002'

        captured = {}
        def capture(card_data_arg, changed):
            captured['changed'] = dict(changed)
            return True, 'OK'

        with patch.object(cm, '_program_nonempty_card', side_effect=capture):
            cm.program_card(card_data, original_data=orig)

        assert 'ICCID' not in captured.get('changed', {})
        assert 'IMSI' in captured.get('changed', {})

    def test_sja5_partial_delta_no_pysim_prog_number_error(self, tmp_path):
        """Partial/delta change for SJA5 does not pass ICCID/IMSI to pySim-prog."""
        cm = _sja5_auth_manager(tmp_path)
        orig = dict(cm._original_card_data)
        card_data = dict(orig)
        card_data['Ki'] = 'A' * 32  # only Ki changed

        prog_args = []
        def fake_prog(fields, adm1, **kw):
            prog_args.append(dict(fields))
            return True, '', ''

        with patch.object(cm, '_run_pysim_prog', side_effect=fake_prog):
            with patch.object(cm, '_program_nonempty_card',
                              return_value=(True, 'OK')):
                cm.program_card(card_data, original_data=orig)

        assert not prog_args, "_run_pysim_prog must not be called for SJA5 delta write"

    def test_sja5_spn_ignored(self, tmp_path):
        """SPN in card_data for SJA5 is silently ignored — not passed to shell."""
        cm = _sja5_auth_manager(tmp_path)
        orig = dict(cm._original_card_data)
        card_data = dict(orig)
        card_data['IMSI'] = '240070000000002'
        card_data['SPN'] = 'TestNetwork'

        captured = {}
        def capture(card_data_arg, changed):
            captured['changed'] = dict(changed)
            return True, 'OK'

        with patch.object(cm, '_program_nonempty_card', side_effect=capture):
            ok, msg = cm.program_card(card_data, original_data=orig)

        assert ok is True
        assert 'SPN' not in captured.get('changed', {})


# ---------------------------------------------------------------------------
# _program_nonempty_card — IMSI/FPLMN only, no Ki/OPc, verification gates artifact
# ---------------------------------------------------------------------------

class TestProgramNonemptyCard:
    """_program_nonempty_card writes IMSI and FPLMN only; verification gates artifact save."""

    def _cm(self, tmp_path, shell_result=(True, '', '')):
        cm = _sja5_auth_manager(tmp_path)
        return cm

    def test_imsi_written_when_changed(self, tmp_path):
        """Changed IMSI generates IMSI write commands via pySim-shell."""
        cm = self._cm(tmp_path)
        orig = dict(cm._original_card_data)
        changed = {'IMSI': '240070000000099'}

        shell_calls = []
        def fake_shell(adm1, cmds, timeout=30):
            shell_calls.append(cmds)
            return True, '', ''

        with patch.object(cm, '_run_pysim_shell', side_effect=fake_shell):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {'IMSI': '240070000000099'})):
                ok, msg = cm._program_nonempty_card(orig, changed)

        assert ok is True
        assert shell_calls, "pySim-shell was not called"
        assert 'EF.IMSI' in shell_calls[0] or 'IMSI' in shell_calls[0]
        assert 'update_binary_decoded' in shell_calls[0]

    def test_fplmn_written_via_adf_usim(self, tmp_path):
        """Changed FPLMN generates commands navigating through ADF.USIM."""
        cm = self._cm(tmp_path)
        orig = dict(cm._original_card_data)
        changed = {'FPLMN': '24001;24007'}

        shell_calls = []
        def fake_shell(adm1, cmds, timeout=30):
            shell_calls.append(cmds)
            return True, '', ''

        with patch.object(cm, '_run_pysim_shell', side_effect=fake_shell):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {'FPLMN': '24001;24007'})):
                ok, msg = cm._program_nonempty_card(orig, changed)

        assert ok is True
        cmds = shell_calls[0]
        assert 'select MF' in cmds
        assert 'select ADF.USIM' in cmds
        assert 'select EF.FPLMN' in cmds
        assert 'update_binary_decoded' in cmds

    def test_ki_opc_not_written(self, tmp_path):
        """Ki and OPc in changed are silently skipped — no write command generated."""
        cm = self._cm(tmp_path)
        orig = dict(cm._original_card_data)
        changed = {'Ki': 'A' * 32, 'OPc': 'B' * 32, 'IMSI': '240070000000099'}

        shell_calls = []
        def fake_shell(adm1, cmds, timeout=30):
            shell_calls.append(cmds)
            return True, '', ''

        with patch.object(cm, '_run_pysim_shell', side_effect=fake_shell):
            with patch.object(cm, 'verify_after_program',
                              return_value=(True, 'OK', {'IMSI': '240070000000099'})):
                ok, msg = cm._program_nonempty_card(orig, changed)

        assert ok is True
        cmds = shell_calls[0]
        assert 'USIM_AUTH_KEY' not in cmds, "Ki/OPc EF must not be selected"

    def test_pysim_prog_never_called(self, tmp_path):
        """_program_nonempty_card never calls _run_pysim_prog."""
        cm = self._cm(tmp_path)
        orig = dict(cm._original_card_data)
        changed = {'IMSI': '240070000000099'}

        prog_calls = []
        with patch.object(cm, '_run_pysim_prog',
                          side_effect=lambda *a, **kw: prog_calls.append(True) or (True, '', '')):
            with patch.object(cm, '_run_pysim_shell', return_value=(True, '', '')):
                with patch.object(cm, 'verify_after_program',
                                  return_value=(True, 'OK', {})):
                    cm._program_nonempty_card(orig, changed)

        assert not prog_calls, "_run_pysim_prog must never be called for non-empty card"

    def test_verification_passes_only_written_fields(self, tmp_path):
        """verify_after_program is called with only the fields that were written."""
        cm = self._cm(tmp_path)
        orig = dict(cm._original_card_data)
        changed = {'IMSI': '240070000000099'}

        verify_calls = []
        def fake_verify(data):
            verify_calls.append(dict(data))
            return True, 'OK', {'IMSI': '240070000000099'}

        with patch.object(cm, '_run_pysim_shell', return_value=(True, '', '')):
            with patch.object(cm, 'verify_after_program', side_effect=fake_verify):
                cm._program_nonempty_card(orig, changed)

        assert verify_calls, "verify_after_program must be called"
        verify_arg = verify_calls[0]
        assert 'IMSI' in verify_arg
        assert 'Ki' not in verify_arg
        assert 'OPc' not in verify_arg

    def test_failed_verification_blocks_clean_success(self, tmp_path):
        """Verification failure returns ok=True with pending wording — not a clean success."""
        from widgets.program_sim_panel import ProgramSIMPanel
        cm = self._cm(tmp_path)
        orig = dict(cm._original_card_data)
        changed = {'IMSI': '240070000000099'}

        with patch.object(cm, '_run_pysim_shell', return_value=(True, '', '')):
            with patch.object(cm, 'verify_after_program',
                              return_value=(False, 'IMSI mismatch', {})):
                ok, msg = cm._program_nonempty_card(orig, changed)

        assert ok is True
        assert 'verification pending' in msg.lower() or 'read the card again' in msg.lower()
        assert ProgramSIMPanel._is_clean_success(ok, msg) is False

    def test_no_change_when_imsi_and_fplmn_equal(self, tmp_path):
        """No commands generated when IMSI and FPLMN equal target — no-op."""
        cm = self._cm(tmp_path)
        orig = dict(cm._original_card_data)
        # Only Ki changed — not a supported field for this path
        changed = {'Ki': 'A' * 32}

        ok, msg = cm._program_nonempty_card(orig, changed)

        assert ok is True
        assert 'no programmable fields' in msg.lower()

    def test_gialersim_path_unchanged(self, tmp_path):
        """Gialersim cards still use _program_via_pysim_prog — not _program_nonempty_card."""
        cm = _make_hw_manager(tmp_path)
        cm.card_type = CardType.GIALERSIM
        cm._original_card_data = {}
        cm.authenticated = True
        cm._authenticated_adm1_hex = '3838383838383838'

        prog_called = []
        with patch.object(cm, '_program_via_pysim_prog',
                          side_effect=lambda *a: prog_called.append(True) or (True, 'OK')) as mock_prog:
            cm.program_card(
                {'IMSI': '240070000000001', 'Ki': 'A' * 32, 'OPc': 'B' * 32},
                original_data=None)

        assert prog_called, "_program_via_pysim_prog must be called for gialersim"


# ---------------------------------------------------------------------------
# _normalize_fplmn
# ---------------------------------------------------------------------------

class TestNormalizeFplmn:
    """_normalize_fplmn returns order-independent frozenset."""

    def test_same_order(self):
        assert CardManager._normalize_fplmn('24001;24007') == frozenset({'24001', '24007'})

    def test_different_order(self):
        assert (CardManager._normalize_fplmn('24007;24001') ==
                CardManager._normalize_fplmn('24001;24007'))

    def test_empty_string(self):
        assert CardManager._normalize_fplmn('') == frozenset()

    def test_comma_separated(self):
        assert CardManager._normalize_fplmn('24001,24007') == frozenset({'24001', '24007'})


# ---------------------------------------------------------------------------
# verify_after_program — FPLMN field verification
# ---------------------------------------------------------------------------

class TestVerifyAfterProgramFplmn:
    """verify_after_program reports mismatch when FPLMN does not match written value."""

    def _cm(self, tmp_path):
        cm = _make_hw_manager(tmp_path)
        cm.authenticated = True
        cm._authenticated_adm1_hex = '3838383838383838'
        return cm

    def _make_pysim_read_output(self, imsi='240070000000001',
                                 iccid='8949440000001775004',
                                 fplmn_lines=None):
        lines = [
            f'ICCID: {iccid}',
            f'IMSI: {imsi}',
        ]
        if fplmn_lines:
            lines.append('FPLMN:')
            lines.extend(fplmn_lines)
        return '\n'.join(lines)

    def test_fplmn_match_returns_ok(self, tmp_path):
        """When read-back FPLMN matches target, verification passes."""
        cm = self._cm(tmp_path)
        stdout = self._make_pysim_read_output(
            fplmn_lines=['\t24f010 # MCC: 240 MNC: 01',
                         '\t24f070 # MCC: 240 MNC: 07'])

        with patch.object(cm, '_run_cli', return_value=(True, stdout, '')):
            ok, msg, data = cm.verify_after_program({'FPLMN': '24001;24007'})

        assert ok is True

    def test_fplmn_mismatch_returns_fail(self, tmp_path):
        """When read-back FPLMN differs from target, verification fails."""
        cm = self._cm(tmp_path)
        stdout = self._make_pysim_read_output(
            fplmn_lines=['\t24f010 # MCC: 240 MNC: 01'])

        with patch.object(cm, '_run_cli', return_value=(True, stdout, '')):
            ok, msg, data = cm.verify_after_program({'FPLMN': '24001;24007'})

        assert ok is False
        assert 'FPLMN' in msg

    def test_fplmn_order_independent(self, tmp_path):
        """FPLMN verification is order-independent."""
        cm = self._cm(tmp_path)
        stdout = self._make_pysim_read_output(
            fplmn_lines=['\t24f070 # MCC: 240 MNC: 07',
                         '\t24f010 # MCC: 240 MNC: 01'])

        with patch.object(cm, '_run_cli', return_value=(True, stdout, '')):
            ok, msg, data = cm.verify_after_program({'FPLMN': '24001;24007'})

        assert ok is True

    def test_imsi_mismatch_still_fails(self, tmp_path):
        """IMSI mismatch returns failure even when FPLMN is not being verified."""
        cm = self._cm(tmp_path)
        stdout = self._make_pysim_read_output(imsi='240070000000001')

        with patch.object(cm, '_run_cli', return_value=(True, stdout, '')):
            ok, msg, data = cm.verify_after_program(
                {'IMSI': '240070000000099'})  # target differs from read-back

        assert ok is False
        assert 'IMSI' in msg
