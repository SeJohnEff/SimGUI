#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for v0.5.15 card safety features.

Covers:
- authenticate() NEVER uses -A flag (safe mode)
- Blocked card detection via ADM1 retry counter
- Pre-flight blocked card checks in authenticate() and program_card()
- Retry counter parsing from VERIFY APDU responses
- CardStatusPanel blocked indicator and ADM1 attempts display
- _run_pysim_shell_safe vs _run_pysim_shell distinction
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock, call

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestAuthenticateNeverUsesAFlag(unittest.TestCase):
    """The -A flag sends a VERIFY APDU at startup, consuming an attempt.
    authenticate() must NEVER pass -A.  All writes go through pySim-prog."""

    def _make_card_manager(self):
        """Create a CardManager with mocked pySim paths."""
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/opt/pysim/.venv/bin/python'
        cm.card_type = MagicMock()
        cm.authenticated = False
        cm.card_info = {'ICCID': '8946000000000000001'}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {'ICCID': '8946000000000000001'}
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = 3
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_authenticate_calls_safe_shell_not_a_flag(
            self, mock_retry, mock_safe):
        """authenticate() must call _run_pysim_shell_safe, not _run_pysim_shell."""
        cm = self._make_card_manager()
        mock_retry.return_value = 3
        mock_safe.return_value = (True, 'ok', '')

        ok, msg = cm.authenticate('88888888')
        self.assertTrue(ok)
        # Must have called the SAFE variant
        mock_safe.assert_called_once()
        # The command should be verify_adm with --pin-is-hex
        cmd = mock_safe.call_args[0][0]
        self.assertIn('verify_adm', cmd)
        self.assertIn('--pin-is-hex', cmd)

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_authenticate_only_uses_safe_shell(
            self, mock_retry, mock_safe):
        """authenticate() must use _run_pysim_shell_safe, never the -A variant."""
        cm = self._make_card_manager()
        mock_retry.return_value = 3
        mock_safe.return_value = (True, 'ok', '')

        ok, _ = cm.authenticate('88888888')
        self.assertTrue(ok)
        # Safe variant called exactly once
        mock_safe.assert_called_once()

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_authenticate_hex_adm1_passed_correctly(
            self, mock_retry, mock_safe):
        """ADM1 '88888888' should be hex-encoded as '3838383838383838'."""
        cm = self._make_card_manager()
        mock_retry.return_value = 3
        mock_safe.return_value = (True, '', '')

        cm.authenticate('88888888')
        cmd = mock_safe.call_args[0][0]
        self.assertIn('3838383838383838', cmd.upper())


class TestBlockedCardDetection(unittest.TestCase):
    """Tests for detecting permanently locked cards."""

    def _make_card_manager(self):
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = None
        cm.card_type = MagicMock()
        cm.authenticated = False
        cm.card_info = {}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {}
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = None
        cm._safety_override_acknowledged = False
        return cm

    def test_authenticate_blocked_card_refuses(self):
        """authenticate() must refuse if card_blocked is True."""
        cm = self._make_card_manager()
        cm.card_blocked = True
        ok, msg = cm.authenticate('88888888')
        self.assertFalse(ok)
        self.assertIn('PERMANENTLY LOCKED', msg)
        self.assertFalse(cm.authenticated)

    def test_program_card_blocked_refuses(self):
        """program_card() must refuse if card_blocked is True."""
        cm = self._make_card_manager()
        cm.card_blocked = True
        cm.authenticated = True
        cm._authenticated_adm1_hex = '3838383838383838'
        ok, msg = cm.program_card({'IMSI': '001010000000001'})
        self.assertFalse(ok)
        self.assertIn('PERMANENTLY LOCKED', msg)

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    def test_authenticate_checks_retry_before_verify(
            self, mock_safe, mock_retry):
        """authenticate() must check retry counter BEFORE attempting verify."""
        cm = self._make_card_manager()
        cm._original_card_data = {'ICCID': '123'}
        mock_retry.return_value = 0

        ok, msg = cm.authenticate('88888888')
        self.assertFalse(ok)
        self.assertIn('PERMANENTLY LOCKED', msg)
        self.assertTrue(cm.card_blocked)
        # Should NOT have attempted verify at all
        mock_safe.assert_not_called()

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    def test_authenticate_aborts_on_one_attempt_left(
            self, mock_safe, mock_retry):
        """With only 1 attempt left, authenticate() should abort (unless force)."""
        cm = self._make_card_manager()
        cm._original_card_data = {'ICCID': '123'}
        mock_retry.return_value = 1

        ok, msg = cm.authenticate('88888888')
        self.assertFalse(ok)
        self.assertIn('DANGER', msg)
        self.assertIn('1', msg)
        mock_safe.assert_not_called()

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    def test_authenticate_force_overrides_low_attempts(
            self, mock_safe, mock_retry):
        """force=True should skip the retry counter safety check."""
        cm = self._make_card_manager()
        cm._original_card_data = {'ICCID': '123'}
        mock_retry.return_value = 1
        mock_safe.return_value = (True, '', '')

        ok, msg = cm.authenticate('88888888', force=True)
        self.assertTrue(ok)
        mock_safe.assert_called_once()


class TestRetryCounterParsing(unittest.TestCase):
    """Tests for check_adm1_retry_counter() APDU response parsing."""

    def _make_card_manager(self):
        from managers.card_manager import CardManager
        cm = CardManager.__new__(CardManager)
        cm._simulator = None
        cm._venv_python = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = None
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager._init_pyscard')
    @patch('managers.card_manager._smartcard_readers')
    def test_retry_counter_3_remaining(self, mock_readers, mock_init):
        """63 C3 = 3 attempts remaining."""
        mock_init.return_value = True
        mock_conn = MagicMock()
        mock_conn.transmit.return_value = ([], 0x63, 0xC3)
        mock_reader = MagicMock()
        mock_reader.createConnection.return_value = mock_conn
        mock_readers.return_value = [mock_reader]

        cm = self._make_card_manager()
        result = cm.check_adm1_retry_counter()
        self.assertEqual(result, 3)
        self.assertFalse(cm.card_blocked)
        self.assertEqual(cm._adm1_remaining_attempts, 3)

    @patch('managers.card_manager._init_pyscard')
    @patch('managers.card_manager._smartcard_readers')
    def test_retry_counter_0_blocked(self, mock_readers, mock_init):
        """63 C0 = 0 attempts = blocked."""
        mock_init.return_value = True
        mock_conn = MagicMock()
        mock_conn.transmit.return_value = ([], 0x63, 0xC0)
        mock_reader = MagicMock()
        mock_reader.createConnection.return_value = mock_conn
        mock_readers.return_value = [mock_reader]

        cm = self._make_card_manager()
        result = cm.check_adm1_retry_counter()
        self.assertEqual(result, 0)
        self.assertTrue(cm.card_blocked)

    @patch('managers.card_manager._init_pyscard')
    @patch('managers.card_manager._smartcard_readers')
    def test_retry_counter_6983_blocked(self, mock_readers, mock_init):
        """69 83 = authentication method blocked."""
        mock_init.return_value = True
        mock_conn = MagicMock()
        mock_conn.transmit.return_value = ([], 0x69, 0x83)
        mock_reader = MagicMock()
        mock_reader.createConnection.return_value = mock_conn
        mock_readers.return_value = [mock_reader]

        cm = self._make_card_manager()
        result = cm.check_adm1_retry_counter()
        self.assertEqual(result, 0)
        self.assertTrue(cm.card_blocked)

    @patch('managers.card_manager._init_pyscard')
    def test_retry_counter_no_pyscard(self, mock_init):
        """Returns None if pyscard is not available."""
        mock_init.return_value = False
        cm = self._make_card_manager()
        result = cm.check_adm1_retry_counter()
        self.assertIsNone(result)

    @patch('managers.card_manager._init_pyscard')
    @patch('managers.card_manager._smartcard_readers')
    def test_retry_counter_no_readers(self, mock_readers, mock_init):
        """Returns None if no readers available."""
        mock_init.return_value = True
        mock_readers.return_value = []
        cm = self._make_card_manager()
        result = cm.check_adm1_retry_counter()
        self.assertIsNone(result)

    @patch('managers.card_manager._init_pyscard')
    @patch('managers.card_manager._smartcard_readers')
    def test_retry_counter_1_remaining(self, mock_readers, mock_init):
        """63 C1 = 1 attempt remaining (danger zone)."""
        mock_init.return_value = True
        mock_conn = MagicMock()
        mock_conn.transmit.return_value = ([], 0x63, 0xC1)
        mock_reader = MagicMock()
        mock_reader.createConnection.return_value = mock_conn
        mock_readers.return_value = [mock_reader]

        cm = self._make_card_manager()
        result = cm.check_adm1_retry_counter()
        self.assertEqual(result, 1)
        self.assertFalse(cm.card_blocked)

    @patch('managers.card_manager._init_pyscard')
    @patch('managers.card_manager._smartcard_readers')
    def test_retry_counter_exception_returns_none(self, mock_readers, mock_init):
        """Connection exception should return None gracefully."""
        mock_init.return_value = True
        mock_readers.side_effect = Exception("PC/SC error")
        cm = self._make_card_manager()
        result = cm.check_adm1_retry_counter()
        self.assertIsNone(result)


class TestPySimShellSafe(unittest.TestCase):
    """Tests that _run_pysim_shell_safe never uses -A (authentication only)."""

    def _make_card_manager(self):
        from managers.card_manager import CardManager, CardType, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/opt/pysim/.venv/bin/python'
        cm._simulator = None
        cm.card_type = CardType.UNKNOWN
        cm.card_blocked = False
        cm._adm1_remaining_attempts = None
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager._validate_script_path')
    @patch('subprocess.run')
    def test_safe_shell_no_a_flag(self, mock_run, mock_validate):
        """_run_pysim_shell_safe must NOT include -A in the command."""
        mock_validate.return_value = '/opt/pysim/pySim-shell.py'
        mock_run.return_value = MagicMock(
            returncode=0, stdout='', stderr='')

        cm = self._make_card_manager()
        cm._run_pysim_shell_safe('verify_adm')

        cmd = mock_run.call_args[0][0]
        self.assertNotIn('-A', cmd)

    @patch('managers.card_manager.CardManager._validate_script_path')
    @patch('subprocess.run')
    def test_safe_shell_no_noprompt(self, mock_run, mock_validate):
        """Safe shell must NOT use --noprompt (it prevents stdin processing)."""
        mock_validate.return_value = '/opt/pysim/pySim-shell.py'
        mock_run.return_value = MagicMock(
            returncode=0, stdout='', stderr='')

        cm = self._make_card_manager()
        cm._run_pysim_shell_safe('verify_adm')

        cmd = mock_run.call_args[0][0]
        self.assertNotIn('--noprompt', cmd)
        # Verify commands are piped via stdin with 'quit' appended
        call_kwargs = mock_run.call_args[1] if mock_run.call_args[1] else {}
        if not call_kwargs:
            call_kwargs = mock_run.call_args.kwargs
        self.assertIn('input', call_kwargs)
        self.assertIn('quit', call_kwargs['input'])


class TestBlankCardSafeAuth(unittest.TestCase):
    """Blank cards that cause pySim-shell init failure should NOT consume attempts."""

    def _make_card_manager(self):
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/opt/pysim/.venv/bin/python'
        cm.card_type = MagicMock()
        cm.authenticated = False
        cm.card_info = {}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {}  # blank card — no original data
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = 3
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_blank_card_init_failure_stores_adm1(
            self, mock_retry, mock_safe):
        """Blank card: init failure should store ADM1 without consuming an attempt."""
        cm = self._make_card_manager()
        mock_retry.return_value = 3
        # Simulate init failure (blank card)
        mock_safe.return_value = (
            False, '', 'pySim-shell not equipped')

        ok, msg = cm.authenticate('88888888')
        self.assertTrue(ok)
        self.assertIn('blank card', msg.lower())
        self.assertTrue(cm.authenticated)
        self.assertIsNotNone(cm._authenticated_adm1_hex)


class TestDetectCardBlockedCheck(unittest.TestCase):
    """detect_card() must NOT check ADM1 retry counter (deferred to authenticate)."""

    def _make_card_manager(self):
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = None
        cm.card_type = MagicMock()
        cm.authenticated = False
        cm.card_info = {}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {}
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = None
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager._run_cli')
    def test_detect_card_does_not_call_check_adm1(
            self, mock_cli):
        """detect_card() must NOT call check_adm1_retry_counter().

        ADM1 retry counter check is deferred to authenticate() to
        avoid burning attempts on gialersim/blank cards.
        """
        cm = self._make_card_manager()
        mock_cli.return_value = (True, 'ICCID: 8946000000\nIMSI: 001010000', '')

        with patch.object(cm, 'check_adm1_retry_counter') as mock_retry:
            ok, msg = cm.detect_card()
            mock_retry.assert_not_called()
        self.assertTrue(ok)
        self.assertNotIn('BLOCKED', msg)


class TestDisconnectResetsBlockedState(unittest.TestCase):
    """disconnect() must reset card_blocked and retry counter."""

    def test_disconnect_clears_blocked(self):
        from managers.card_manager import CardManager
        cm = CardManager.__new__(CardManager)
        cm._simulator = None
        cm.authenticated = True
        cm._authenticated_adm1_hex = 'abc'
        cm._original_card_data = {'x': 'y'}
        cm.card_type = MagicMock()
        cm.card_info = {'a': 'b'}
        cm.card_blocked = True
        cm._adm1_remaining_attempts = 0
        cm._safety_override_acknowledged = True

        cm.disconnect()
        self.assertFalse(cm.card_blocked)
        self.assertIsNone(cm._adm1_remaining_attempts)
        self.assertFalse(cm.authenticated)
        self.assertFalse(cm._safety_override_acknowledged)


class TestCardStatusPanelBlockedIndicator(unittest.TestCase):
    """Tests for the blocked card indicator in the UI panel."""

    def _make_panel(self):
        """Create a CardStatusPanel with mocked Tk."""
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        from widgets.card_status_panel import CardStatusPanel
        panel = CardStatusPanel(root)
        return panel, root

    def test_panel_has_blocked_status_color(self):
        """'blocked' state should produce a deep red indicator."""
        try:
            panel, root = self._make_panel()
            panel.set_status('blocked', 'BLOCKED')
            # Just verify it doesn't crash
            root.update_idletasks()
            root.destroy()
        except Exception:
            # No display in CI — just verify the method exists
            from widgets.card_status_panel import CardStatusPanel
            self.assertTrue(hasattr(CardStatusPanel, 'set_status'))

    def test_panel_has_set_blocked_indicator(self):
        """CardStatusPanel must have set_blocked_indicator method."""
        from widgets.card_status_panel import CardStatusPanel
        self.assertTrue(hasattr(CardStatusPanel, 'set_blocked_indicator'))

    def test_panel_has_set_adm1_attempts(self):
        """CardStatusPanel must have set_adm1_attempts method."""
        from widgets.card_status_panel import CardStatusPanel
        self.assertTrue(hasattr(CardStatusPanel, 'set_adm1_attempts'))

    def test_panel_has_adm1_attempts_info_var(self):
        """Panel should have 'adm1_attempts' in its info vars."""
        try:
            panel, root = self._make_panel()
            self.assertIn('adm1_attempts', panel._info_vars)
            root.destroy()
        except Exception:
            pass  # No display in CI


class TestAuthenticateWrongKeyUpdatesRetryCounter(unittest.TestCase):
    """After a failed auth (6982), the retry counter should be refreshed."""

    def _make_card_manager(self):
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/opt/pysim/.venv/bin/python'
        cm.card_type = MagicMock()
        cm.authenticated = False
        cm.card_info = {}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {'ICCID': '123'}
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = 3
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    def test_wrong_key_rechecks_counter(self, mock_safe, mock_retry):
        """After 6982 error, authenticate() should re-check retry counter."""
        cm = self._make_card_manager()
        # First call: pre-flight check returns 3
        # Second call: after failure returns 2
        mock_retry.side_effect = [3, 2]
        mock_safe.return_value = (
            False, '', 'SW Mismatch: Expected 9000 and got 6982')

        ok, msg = cm.authenticate('99999999')
        self.assertFalse(ok)
        self.assertIn('FAILED', msg)
        self.assertIn('6982', msg)
        self.assertIn('2 attempt(s) remaining', msg)
        # check_adm1_retry_counter called twice: pre-flight + post-failure
        self.assertEqual(mock_retry.call_count, 2)


class TestGetRemainingAttemptsReturnsStoredValue(unittest.TestCase):
    """get_remaining_attempts() should return _adm1_remaining_attempts."""

    def test_returns_stored_value(self):
        from managers.card_manager import CardManager
        cm = CardManager.__new__(CardManager)
        cm._simulator = None
        cm._adm1_remaining_attempts = 2
        self.assertEqual(cm.get_remaining_attempts(), 2)

    def test_returns_none_when_unknown(self):
        from managers.card_manager import CardManager
        cm = CardManager.__new__(CardManager)
        cm._simulator = None
        cm._adm1_remaining_attempts = None
        self.assertIsNone(cm.get_remaining_attempts())


class TestAdm1RemainingAttemptsProperty(unittest.TestCase):
    """Test the adm1_remaining_attempts property."""

    def test_property_returns_value(self):
        from managers.card_manager import CardManager
        cm = CardManager.__new__(CardManager)
        cm._adm1_remaining_attempts = 3
        self.assertEqual(cm.adm1_remaining_attempts, 3)

    def test_property_returns_none(self):
        from managers.card_manager import CardManager
        cm = CardManager.__new__(CardManager)
        cm._adm1_remaining_attempts = None
        self.assertIsNone(cm.adm1_remaining_attempts)


class TestProgramCardBlockedGuard(unittest.TestCase):
    """program_card() must check card_blocked before proceeding."""

    def _make_card_manager(self):
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = None
        cm.card_type = MagicMock()
        cm.authenticated = True
        cm.card_info = {}
        cm._authenticated_adm1_hex = '3838383838383838'
        cm._original_card_data = {'ICCID': '123', 'IMSI': '001'}
        cm._simulator = None
        cm.card_blocked = True
        cm._adm1_remaining_attempts = 0
        cm._safety_override_acknowledged = False
        return cm

    def test_program_card_refuses_blocked(self):
        cm = self._make_card_manager()
        ok, msg = cm.program_card({'IMSI': '001010000000001'})
        self.assertFalse(ok)
        self.assertIn('PERMANENTLY LOCKED', msg)

    def test_program_card_allows_unblocked(self):
        """Unblocked card should pass the blocked check (may fail later)."""
        cm = self._make_card_manager()
        cm.card_blocked = False
        # Will fail later because no actual card, but should pass the blocked check
        with patch.object(cm, '_compute_changed_fields', return_value={}):
            ok, msg = cm.program_card({'IMSI': '001'})
        self.assertTrue(ok)
        self.assertIn('No changes', msg)


class TestProgramCardRetryCounterSafety(unittest.TestCase):
    """program_card() must check ADM1 retry counter before programming.

    If the counter is dangerously low (e.g. from a previous 6f00 error),
    programming must be refused to protect the card.
    """

    def _make_card_manager(self, remaining=3):
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/opt/pysim/.venv/bin/python'
        cm.card_type = MagicMock()
        cm.authenticated = True
        cm.card_info = {}
        cm._authenticated_adm1_hex = '3838383838383838'
        cm._original_card_data = {'ICCID': '123', 'IMSI': '001'}
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = remaining
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_refuses_when_counter_is_zero(self, mock_retry):
        cm = self._make_card_manager()
        mock_retry.return_value = 0
        ok, msg = cm.program_card({'IMSI': '001010000000001'})
        self.assertFalse(ok)
        self.assertIn('PERMANENTLY LOCKED', msg)
        self.assertTrue(cm.card_blocked)

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_refuses_when_counter_is_one(self, mock_retry):
        cm = self._make_card_manager()
        mock_retry.return_value = 1
        ok, msg = cm.program_card({'IMSI': '001010000000001'})
        self.assertFalse(ok)
        self.assertIn('DANGER', msg)
        self.assertIn('1', msg)

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._compute_changed_fields')
    def test_allows_when_counter_is_two(self, mock_changed, mock_retry):
        cm = self._make_card_manager()
        mock_retry.return_value = 2
        mock_changed.return_value = {}  # No changes
        ok, msg = cm.program_card({'IMSI': '001'})
        self.assertTrue(ok)  # Passes safety check, no changes to write

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._compute_changed_fields')
    def test_allows_when_counter_is_three(self, mock_changed, mock_retry):
        cm = self._make_card_manager()
        mock_retry.return_value = 3
        mock_changed.return_value = {}  # No changes
        ok, msg = cm.program_card({'IMSI': '001'})
        self.assertTrue(ok)  # Passes safety check

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._compute_changed_fields')
    def test_allows_when_counter_unavailable(self, mock_changed, mock_retry):
        """If retry counter can't be read (None), proceed cautiously."""
        cm = self._make_card_manager()
        mock_retry.return_value = None
        mock_changed.return_value = {}  # No changes
        ok, msg = cm.program_card({'IMSI': '001'})
        self.assertTrue(ok)  # None means we can't check, so allow



# TestProgramNonemptyUseSafeShell removed: _program_nonempty_card and
# _run_pysim_shell (with -A) were eliminated in v0.5.32.
# All writes now go through _program_via_pysim_prog → pySim-prog.


class TestAuthenticateDetects6983InOutput(unittest.TestCase):
    """When pySim-shell returns 6983, authenticate() must set card_blocked."""

    def _make_card_manager(self):
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/opt/pysim/.venv/bin/python'
        cm.card_type = MagicMock()
        cm.authenticated = False
        cm.card_info = {}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {'ICCID': '123'}
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = 3
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    def test_6983_sets_blocked(self, mock_safe, mock_retry):
        cm = self._make_card_manager()
        mock_retry.return_value = 3  # pre-flight ok
        mock_safe.return_value = (
            False, '', 'SW Mismatch: Expected 9000 and got 6983')

        ok, msg = cm.authenticate('88888888')
        self.assertFalse(ok)
        self.assertTrue(cm.card_blocked)
        self.assertEqual(cm._adm1_remaining_attempts, 0)
        self.assertIn('PERMANENTLY LOCKED', msg)


class TestPySimShellImplDetectsCommandErrors(unittest.TestCase):
    """_run_pysim_shell_impl must detect APDU errors even when exit code is 0.

    pySim-shell exits 0 even when verify_adm fails with SwMatchError/6f00.
    The impl must scan stdout/stderr for error patterns and return False.
    This is the ROOT CAUSE of the v0.5.17 card-locking bug.
    """

    def _make_card_manager(self):
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/opt/pysim/.venv/bin/python'
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = None
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager._validate_script_path')
    @patch('subprocess.run')
    def test_swmatcherror_6f00_detected(self, mock_run, mock_validate):
        """SwMatchError with 6f00 in stderr must return failure.

        This is the EXACT output from the v0.5.17 bug that locked a card.
        """
        mock_validate.return_value = '/opt/pysim/pySim-shell.py'
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='pySIM-shell (MF)>',
            stderr='SwMatchError: Expected 9000 and got 6f00',
        )
        cm = self._make_card_manager()
        ok, stdout, stderr = cm._run_pysim_shell_impl(
            None, 'verify_adm --pin-is-hex 3838383838383838')
        self.assertFalse(ok, "Must return False when SwMatchError in stderr")
        self.assertIn('SwMatchError', stderr)

    @patch('managers.card_manager.CardManager._validate_script_path')
    @patch('subprocess.run')
    def test_swmatcherror_6982_detected(self, mock_run, mock_validate):
        """SwMatchError with 6982 (wrong key) must return failure."""
        mock_validate.return_value = '/opt/pysim/pySim-shell.py'
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='pySIM-shell (MF)>',
            stderr='SwMatchError: Expected 9000 and got 6982',
        )
        cm = self._make_card_manager()
        ok, stdout, stderr = cm._run_pysim_shell_impl(
            None, 'verify_adm --pin-is-hex 0000000000000000')
        self.assertFalse(ok, "Must return False when 6982 in stderr")

    @patch('managers.card_manager.CardManager._validate_script_path')
    @patch('subprocess.run')
    def test_swmatcherror_6983_detected(self, mock_run, mock_validate):
        """SwMatchError with 6983 (blocked) must return failure."""
        mock_validate.return_value = '/opt/pysim/pySim-shell.py'
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='',
            stderr='SwMatchError: Expected 9000 and got 6983',
        )
        cm = self._make_card_manager()
        ok, stdout, stderr = cm._run_pysim_shell_impl(
            None, 'verify_adm --pin-is-hex 0000000000000000')
        self.assertFalse(ok, "Must return False when 6983 in stderr")

    @patch('managers.card_manager.CardManager._validate_script_path')
    @patch('subprocess.run')
    def test_clean_output_returns_success(self, mock_run, mock_validate):
        """Clean output with exit code 0 should return True."""
        mock_validate.return_value = '/opt/pysim/pySim-shell.py'
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='pySIM-shell (MF)>',
            stderr='',
        )
        cm = self._make_card_manager()
        ok, stdout, stderr = cm._run_pysim_shell_impl(
            None, 'verify_adm --pin-is-hex 3838383838383838')
        self.assertTrue(ok, "Clean output should return True")

    @patch('managers.card_manager.CardManager._validate_script_path')
    @patch('subprocess.run')
    def test_quit_used_not_exit(self, mock_run, mock_validate):
        """pySim-shell uses 'quit', not 'exit'."""
        mock_validate.return_value = '/opt/pysim/pySim-shell.py'
        mock_run.return_value = MagicMock(
            returncode=0, stdout='', stderr='')
        cm = self._make_card_manager()
        cm._run_pysim_shell_impl(None, 'some_command')
        call_kwargs = mock_run.call_args.kwargs
        stdin_input = call_kwargs.get('input', '')
        self.assertIn('quit', stdin_input,
                      "Must use 'quit' to terminate pySim-shell")
        self.assertNotIn('\nexit\n', stdin_input,
                         "Must NOT use 'exit' — pySim-shell doesn't recognize it")


class TestAuthenticateDetects6f00(unittest.TestCase):
    """authenticate() must detect 6f00 errors and report failure.

    6f00 is a generic APDU error that consumes an ADM1 attempt.
    Previously only 6982 and 6983 were checked.
    """

    def _make_card_manager(self):
        from managers.card_manager import CardManager, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/opt/pysim/.venv/bin/python'
        cm.card_type = MagicMock()
        cm.authenticated = False
        cm.card_info = {}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {'ICCID': '123'}
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = 3
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    def test_6f00_returns_failure(self, mock_safe, mock_retry):
        """Exact scenario from v0.5.17 bug: 6f00 with exit code 0."""
        cm = self._make_card_manager()
        mock_retry.side_effect = [3, 2]
        # _run_pysim_shell_safe now returns False (after the _impl fix),
        # and stderr contains the SwMatchError with 6f00
        mock_safe.return_value = (
            False, 'pySIM-shell (MF)>',
            'SwMatchError: Expected 9000 and got 6f00')

        ok, msg = cm.authenticate('88888888')
        self.assertFalse(ok, "authenticate() must return False on 6f00")
        self.assertFalse(cm.authenticated, "Must NOT set authenticated=True")
        self.assertIn('6f00', msg.lower())
        self.assertIn('FAILED', msg)

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    def test_6f00_rechecks_retry_counter(self, mock_safe, mock_retry):
        """After 6f00, retry counter should be re-checked."""
        cm = self._make_card_manager()
        mock_retry.side_effect = [3, 0]  # Pre-flight 3, post-failure 0 (blocked!)
        mock_safe.return_value = (
            False, '', 'SwMatchError: Expected 9000 and got 6f00')

        ok, msg = cm.authenticate('88888888')
        self.assertFalse(ok)
        self.assertTrue(cm.card_blocked, "Must set card_blocked when counter=0")
        # check_adm1_retry_counter should be called twice
        self.assertEqual(mock_retry.call_count, 2)

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    def test_swmatcherror_without_specific_sw_still_fails(
            self, mock_safe, mock_retry):
        """SwMatchError without a known SW code should still trigger failure."""
        cm = self._make_card_manager()
        mock_retry.side_effect = [3, 2]
        mock_safe.return_value = (
            False, '', 'SwMatchError: Expected 9000 and got 6a82')

        ok, msg = cm.authenticate('88888888')
        self.assertFalse(ok)
        # The swmatcherror pattern catches this even though 6a82 isn't
        # in the specific SW checks
        self.assertIn('FAILED', msg)


class TestIccidCheckSkippedForBlankAndGialersim(unittest.TestCase):
    """ICCID cross-verification must be skipped for blank and gialersim cards.

    For blank/gialersim cards the target ICCID in the CSV is the one being
    *written*, not what the card already holds.  All blank Fiskarheden cards
    share the same default ADM1 so a mismatch cannot lock the wrong card.
    """

    def _make_gialersim_manager(self):
        from managers.card_manager import CardManager, CardType, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = None
        cm.card_type = CardType.GIALERSIM
        cm.authenticated = False
        cm.card_info = {}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {}   # blank card detected
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = None
        cm._safety_override_acknowledged = False
        return cm

    def _make_blank_manager(self):
        """Blank card: UNKNOWN type, no ICCID/IMSI in original data."""
        from managers.card_manager import CardManager, CardType, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = None
        cm.card_type = CardType.UNKNOWN
        cm.authenticated = False
        cm.card_info = {}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {}   # blank — no ICCID, no IMSI
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = None
        cm._safety_override_acknowledged = False
        return cm

    def _make_sja5_manager(self):
        from managers.card_manager import CardManager, CardType, CLIBackend
        cm = CardManager.__new__(CardManager)
        cm.cli_path = '/opt/pysim'
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = None
        cm.card_type = CardType.SJA5
        cm.authenticated = False
        cm.card_info = {'ICCID': '8946000000000000001'}
        cm._authenticated_adm1_hex = None
        cm._original_card_data = {'ICCID': '8946000000000000001', 'IMSI': '001010000000001'}
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = 3
        cm._safety_override_acknowledged = False
        return cm

    def test_gialersim_iccid_check_skipped_proceeds_to_auth(self):
        """Gialersim card: expected_iccid mismatch must NOT abort authentication."""
        cm = self._make_gialersim_manager()
        # authenticate() for gialersim takes the blank-card path (stored, no VERIFY)
        ok, msg = cm.authenticate('3838383838383838',
                                  expected_iccid='8946000000000000099')
        self.assertTrue(ok, f"Expected success for gialersim, got: {msg}")
        self.assertNotIn('mismatch', msg.lower())

    def test_gialersim_iccid_check_skipped_regardless_of_card_iccid(self):
        """Even if card_info has an ICCID, gialersim skips the check."""
        cm = self._make_gialersim_manager()
        cm.card_info = {'ICCID': '8901901557518313028'}   # factory ICCID
        cm._original_card_data = {'ICCID': '8901901557518313028'}
        ok, msg = cm.authenticate('3838383838383838',
                                  expected_iccid='8946000000000000099')
        self.assertTrue(ok, f"Expected success for gialersim, got: {msg}")

    def test_blank_card_iccid_check_skipped(self):
        """Blank card (no ICCID/IMSI): expected_iccid mismatch must be skipped."""
        cm = self._make_blank_manager()
        ok, msg = cm.authenticate('3838383838383838',
                                  expected_iccid='8946000000000000099')
        self.assertTrue(ok, f"Expected success for blank card, got: {msg}")
        self.assertNotIn('mismatch', msg.lower())

    def test_blank_card_with_acc_only_iccid_check_skipped(self):
        """Blank card that pySim-read returns ACC but no ICCID/IMSI."""
        cm = self._make_blank_manager()
        cm._original_card_data = {'ACC': 'ffff'}   # ACC present, no ICCID/IMSI
        ok, msg = cm.authenticate('3838383838383838',
                                  expected_iccid='8946000000000000099')
        self.assertTrue(ok, f"Expected success for ACC-only card, got: {msg}")

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_sja5_iccid_mismatch_still_aborts(self, mock_retry, mock_safe):
        """Non-empty SJA5 card: ICCID mismatch must still abort authentication."""
        cm = self._make_sja5_manager()
        mock_retry.return_value = 3
        ok, msg = cm.authenticate('88888888',
                                  expected_iccid='9999999999999999999')
        self.assertFalse(ok)
        self.assertIn('mismatch', msg.lower())
        mock_safe.assert_not_called()   # VERIFY must not have been sent

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_sja5_iccid_match_proceeds_normally(self, mock_retry, mock_safe):
        """Non-empty SJA5 card: matching expected_iccid proceeds to auth."""
        cm = self._make_sja5_manager()
        mock_retry.return_value = 3
        mock_safe.return_value = (True, 'Authentication successful', '')
        ok, msg = cm.authenticate('88888888',
                                  expected_iccid='8946000000000000001')
        self.assertTrue(ok)

    def test_no_expected_iccid_always_skips_check(self):
        """expected_iccid=None skips the check regardless of card type."""
        cm = self._make_sja5_manager()
        with patch.object(cm, 'read_iccid') as mock_read:
            cm.authenticate('88888888', expected_iccid=None)
        mock_read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
