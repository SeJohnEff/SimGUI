#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Phase 1 bug fixes — dangerous batch programming issues.

Covers:
- Bug 1.1: ATR→ICCID cache cleared on card removal
- Bug 1.2: detect_card() no longer triggers ADM1 VERIFY
- Bug 1.3: Safety override carries from authenticate(force=True) to program_card()
- Bug 1.4: ICCID index updated after programming via add_iccid()
- Integration: batch programming flow doesn't burn retries
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestAtrCacheClearedOnRemoval(unittest.TestCase):
    """Bug 1.1: ATR→ICCID cache must be cleared when a card is removed.

    All blank gialersim cards share the same ATR. Without clearing,
    Card 2 gets misidentified as Card 1.
    """

    def _make_card_watcher(self):
        from managers.card_watcher import CardWatcher
        cm = MagicMock()
        idx = MagicMock()
        idx.lookup.return_value = None
        watcher = CardWatcher.__new__(CardWatcher)
        watcher._card_manager = cm
        watcher._cm = cm
        watcher._iccid_index = idx
        watcher._poll_interval = 1.5
        watcher._running = False
        watcher._thread = None
        watcher._callbacks = []
        watcher._error_callbacks = []
        watcher._atr_iccid_cache = {'AABBCCDD': '8946000000000000001'}
        watcher._last_atr = 'AABBCCDD'
        watcher._last_iccid = None
        watcher._card_present = True
        watcher._programmed_iccids = set()
        watcher.on_card_removed = None
        return watcher

    def test_cache_cleared_on_card_removal_fast_path(self):
        """ATR cache must be empty after _handle_probe_result(False, '')."""
        watcher = self._make_card_watcher()
        watcher._atr_iccid_cache['AABBCCDD'] = '8946000000000000001'
        watcher._card_present = True
        watcher._last_atr = 'AABBCCDD'
        # Simulate card removal via fast probe
        watcher._handle_probe_result(False, '')
        self.assertEqual(len(watcher._atr_iccid_cache), 0,
                         "ATR cache must be cleared on card removal")

    def test_cache_cleared_on_card_removal_slow_path(self):
        """ATR cache must be empty after slow-path card removal."""
        watcher = self._make_card_watcher()
        watcher._atr_iccid_cache['AABBCCDD'] = '8946000000000000001'
        watcher._card_present = True
        # Simulate card removal via the same probe interface
        watcher._handle_probe_result(False, '')
        self.assertEqual(len(watcher._atr_iccid_cache), 0)

    def test_cache_not_cleared_when_card_still_present(self):
        """Cache should NOT be cleared when a card is still there."""
        watcher = self._make_card_watcher()
        watcher._atr_iccid_cache['AABBCCDD'] = '8946000000000000001'
        # Card still present — same ATR, already known
        watcher._handle_probe_result(True, 'AABBCCDD')
        self.assertEqual(len(watcher._atr_iccid_cache), 1,
                         "Cache should persist when card is still present")


class TestDetectCardNoAdm1Verify(unittest.TestCase):
    """Bug 1.2: detect_card() must NOT call check_adm1_retry_counter().

    Calling it on gialersim cards burns ADM1 attempts because they use
    CHV 0x0C, not 0x0A.
    """

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

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._run_cli')
    def test_detect_card_never_calls_retry_check(self, mock_cli, mock_retry):
        """detect_card() must NOT invoke check_adm1_retry_counter()."""
        cm = self._make_card_manager()
        mock_cli.return_value = (True, 'ICCID: 8946000000\nIMSI: 001010000', '')
        cm.detect_card()
        mock_retry.assert_not_called()

    @patch('managers.card_manager.CardManager._run_cli')
    def test_detect_card_success_without_retry_check(self, mock_cli):
        """detect_card() should succeed and return card data."""
        cm = self._make_card_manager()
        mock_cli.return_value = (True, 'ICCID: 8946000000\nIMSI: 001010000', '')
        ok, msg = cm.detect_card()
        self.assertTrue(ok)
        self.assertIn('pySim', msg)

    @patch('managers.card_manager.CardManager._run_cli')
    def test_detect_card_failure_without_retry_check(self, mock_cli):
        """detect_card() failure path should NOT call retry check either."""
        cm = self._make_card_manager()
        mock_cli.return_value = (False, '', 'no card')
        with patch.object(cm, 'check_adm1_retry_counter') as mock_retry:
            ok, msg = cm.detect_card()
            mock_retry.assert_not_called()
        self.assertFalse(ok)


class TestSafetyOverrideCarryForward(unittest.TestCase):
    """Bug 1.3: authenticate(force=True) must carry override to program_card().

    When the user forces past the low-retry safety warning during Authenticate,
    program_card() should not independently re-check and block again.
    """

    def _make_card_manager(self):
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
        cm._adm1_remaining_attempts = None
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_force_auth_sets_override_flag(self, mock_retry, mock_safe):
        """authenticate(force=True) must set _safety_override_acknowledged."""
        cm = self._make_card_manager()
        mock_retry.return_value = 1  # low but force overrides
        mock_safe.return_value = (True, '', '')
        ok, _ = cm.authenticate('88888888', force=True)
        self.assertTrue(ok)
        self.assertTrue(cm._safety_override_acknowledged)

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_normal_auth_does_not_set_override(self, mock_retry, mock_safe):
        """authenticate(force=False) must NOT set the override flag."""
        cm = self._make_card_manager()
        mock_retry.return_value = 3
        mock_safe.return_value = (True, '', '')
        ok, _ = cm.authenticate('88888888', force=False)
        self.assertTrue(ok)
        self.assertFalse(cm._safety_override_acknowledged)

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    @patch('managers.card_manager.CardManager._compute_changed_fields')
    def test_program_skips_retry_check_when_override_set(
            self, mock_changed, mock_retry):
        """program_card() must skip retry check when override is acknowledged."""
        cm = self._make_card_manager()
        cm.authenticated = True
        cm._authenticated_adm1_hex = '3838383838383838'
        cm._safety_override_acknowledged = True
        mock_changed.return_value = {}  # no changes
        ok, msg = cm.program_card({'IMSI': '001'})
        self.assertTrue(ok)
        mock_retry.assert_not_called()

    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_program_checks_retry_when_no_override(self, mock_retry):
        """program_card() must check retry counter when override is NOT set."""
        cm = self._make_card_manager()
        cm.authenticated = True
        cm._authenticated_adm1_hex = '3838383838383838'
        cm._safety_override_acknowledged = False
        mock_retry.return_value = 1  # low
        ok, msg = cm.program_card({'IMSI': '001010000000001'})
        self.assertFalse(ok)
        self.assertIn('DANGER', msg)
        mock_retry.assert_called_once()

    def test_disconnect_clears_override(self):
        """disconnect() must clear the safety override flag."""
        cm = self._make_card_manager()
        cm._safety_override_acknowledged = True
        cm.disconnect()
        self.assertFalse(cm._safety_override_acknowledged)

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_force_auth_blank_card_sets_override(self, mock_retry, mock_safe):
        """Blank card authenticate(force=True) must also set override."""
        cm = self._make_card_manager()
        cm._original_card_data = {}  # blank card
        mock_retry.return_value = 1
        # blank card doesn't need pySim-shell, stores ADM1 directly
        ok, _ = cm.authenticate('88888888', force=True)
        self.assertTrue(ok)
        self.assertTrue(cm._safety_override_acknowledged)

    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_force_auth_simulator_sets_override(self, mock_retry, mock_safe):
        """Simulator authenticate(force=True) must also set override."""
        cm = self._make_card_manager()
        cm._simulator = MagicMock()
        cm._simulator.authenticate.return_value = (True, 'ok')
        ok, _ = cm.authenticate('88888888', force=True)
        self.assertTrue(ok)
        self.assertTrue(cm._safety_override_acknowledged)


class TestIccidIndexAddIccid(unittest.TestCase):
    """Bug 1.4: IccidIndex.add_iccid() must register a single ICCID.

    After programming, re-inserting the card should be recognised
    without a full directory rescan.
    """

    def _make_index(self):
        from managers.iccid_index import IccidIndex
        return IccidIndex()

    def test_add_iccid_creates_entry(self):
        """add_iccid() must create a lookup-able entry."""
        idx = self._make_index()
        idx.add_iccid('8946000000000000001', '/tmp/test.csv')
        entry = idx.lookup('8946000000000000001')
        self.assertIsNotNone(entry)
        self.assertEqual(entry.file_path, '/tmp/test.csv')

    def test_add_iccid_empty_string_ignored(self):
        """Empty ICCID string should be silently ignored."""
        idx = self._make_index()
        idx.add_iccid('', '/tmp/test.csv')
        self.assertEqual(len(idx._entries), 0)

    def test_add_iccid_already_indexed_no_duplicate(self):
        """Adding an already-indexed ICCID should not create a duplicate."""
        idx = self._make_index()
        idx.add_iccid('8946000000000000001', '/tmp/test.csv')
        idx.add_iccid('8946000000000000001', '/tmp/test.csv')
        # Count entries that match this ICCID
        matches = [e for e in idx._entries
                   if e.contains('8946000000000000001')]
        self.assertEqual(len(matches), 1)

    def test_add_iccid_evicts_stale_cache(self):
        """add_iccid() must evict stale card cache for re-reads."""
        idx = self._make_index()
        # Pre-populate cache
        idx._card_cache['8946000000000000001'] = {'ICCID': '8946000000000000001'}
        idx.add_iccid('8946000000000000001', '/tmp/test.csv')
        self.assertNotIn('8946000000000000001', idx._card_cache)

    def test_add_iccid_19_digit_iccid(self):
        """19-digit ICCIDs (standard) should work correctly."""
        idx = self._make_index()
        iccid = '8946000000001672706'
        idx.add_iccid(iccid, '/tmp/batch.csv')
        entry = idx.lookup(iccid)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.iccid_length, 19)


class TestBatchFlowNoRetryBurn(unittest.TestCase):
    """Integration: batch programming flow must not burn ADM1 retries.

    This test simulates the full batch flow:
    1. detect_card() — should NOT call check_adm1_retry_counter
    2. authenticate(force=True) — sets safety override
    3. program_card() — should skip retry check due to override
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
        cm._original_card_data = {}
        cm._simulator = None
        cm.card_blocked = False
        cm._adm1_remaining_attempts = None
        cm._safety_override_acknowledged = False
        return cm

    @patch('managers.card_manager.CardManager._compute_changed_fields')
    @patch('managers.card_manager.CardManager._run_pysim_shell_safe')
    @patch('managers.card_manager.CardManager._run_cli')
    @patch('managers.card_manager.CardManager.check_adm1_retry_counter')
    def test_batch_flow_minimal_retry_checks(
            self, mock_retry, mock_cli, mock_safe, mock_changed):
        """Full batch flow should call check_adm1_retry_counter at most once.

        - detect_card: 0 calls (removed)
        - authenticate(force=True): 0 calls (force skips pre-flight)
        - program_card: 0 calls (override acknowledged)
        Total: 0 calls to check_adm1_retry_counter
        """
        cm = self._make_card_manager()
        mock_retry.return_value = 3
        mock_cli.return_value = (
            True, 'ICCID: 8946000000\nIMSI: 001010000', '')
        mock_safe.return_value = (True, '', '')
        mock_changed.return_value = {}

        # Step 1: detect_card
        ok, _ = cm.detect_card()
        self.assertTrue(ok)

        # Step 2: authenticate with force
        ok, _ = cm.authenticate('88888888', force=True)
        self.assertTrue(ok)
        self.assertTrue(cm._safety_override_acknowledged)

        # Step 3: program_card (no changes, but exercises the path)
        ok, _ = cm.program_card({'IMSI': '001'})
        self.assertTrue(ok)

        # check_adm1_retry_counter should NOT have been called
        # (detect_card removed it, force skips it, override skips it)
        mock_retry.assert_not_called()


if __name__ == '__main__':
    unittest.main()
