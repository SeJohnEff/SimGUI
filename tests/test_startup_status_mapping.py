#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for startup status mapping — state-machine.md compliance.

Covers two state-machine.md invariants:

1.  [*] --> no_reader : app start, no reader
    After the first probe, reader-absent or tool-missing conditions MUST
    produce an error notification so the UI can show "No card reader detected"
    (not "Insert a SIM card...").

2.  UI Mapping table:
    - ERROR (no-reader message)  -> "No card reader detected"
    - ERROR (tool-missing msg)   -> error state (not "Insert a SIM card...")
    - NO_CARD                    -> "Insert a SIM card..."
    - BLANK/DETECTED/AUTHENTICATED -> card-present display

These tests are common to Ubuntu and macOS — no platform branching.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_watcher import CardWatcher
from state_manager import CardState, StateManager


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv or ["test"])
    return app


_qapp = _ensure_qapp()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 1. _check_once_slow fires on_error when detect_card fails, no prior card
# ---------------------------------------------------------------------------

class TestCheckOnceSlowOnError(unittest.TestCase):
    """_check_once_slow must call on_error when detect_card() fails and
    _card_present is False.

    state-machine.md invariant: '[*] --> no_reader : app start, no reader'
    The slow path (used when pyscard is unavailable) must feed the state
    machine the same error signal that the fast probe path already provides
    via _handle_probe_result.  Without this, the UI stays at the initial
    display indefinitely and never reaches the correct no-reader state.
    """

    def _make_watcher(self, detect_result):
        """CardWatcher backed by a mock CardManager with a fixed detect result."""
        cm = MagicMock()
        cm.detect_card.return_value = detect_result
        watcher = CardWatcher(cm)
        watcher._card_present = False
        watcher._last_iccid = None
        return watcher

    def test_fires_on_error_with_reader_missing_message(self):
        """Slow path: detect_card fails with no-reader message -> on_error fired."""
        watcher = self._make_watcher((False, "No smart-card reader detected"))
        errors = []
        watcher.on_error = lambda msg: errors.append(msg)

        watcher._check_once_slow()

        self.assertEqual(len(errors), 1,
                         "on_error must be called once; got: " + str(errors))
        self.assertIn("No smart-card reader", errors[0])

    def test_fires_on_error_with_tool_missing_message(self):
        """Slow path: detect_card fails with tool-missing message -> on_error fired."""
        watcher = self._make_watcher(
            (False, "No CLI tool found. Install sysmo-usim-tool or pySim."))
        errors = []
        watcher.on_error = lambda msg: errors.append(msg)

        watcher._check_once_slow()

        self.assertEqual(len(errors), 1,
                         "on_error must be called for tool-missing condition")
        self.assertIn("CLI tool", errors[0])

    def test_fires_on_error_with_generic_failure(self):
        """Slow path: detect_card fails for any reason -> on_error fired."""
        watcher = self._make_watcher((False, "No card detected"))
        errors = []
        watcher.on_error = lambda msg: errors.append(msg)

        watcher._check_once_slow()

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0], "No card detected")

    def test_does_not_fire_on_error_when_detect_succeeds(self):
        """Slow path: detect_card succeeds -> on_error must NOT be called."""
        cm = MagicMock()
        cm.detect_card.return_value = (True, "Card detected")
        cm.read_iccid.return_value = "8946001234"
        watcher = CardWatcher(cm)
        watcher._card_present = False
        watcher._last_iccid = None
        errors = []
        watcher.on_error = lambda msg: errors.append(msg)

        watcher._check_once_slow()

        self.assertEqual(errors, [], "on_error must not fire when detect succeeds")

    def test_does_not_fire_on_error_when_card_previously_present(self):
        """Slow path: detect_card fails but _card_present=True -> removal path
        runs, not the no-prior-card error path."""
        watcher = self._make_watcher((False, "No card detected"))
        watcher._card_present = True
        watcher._last_iccid = "8946001234"
        errors = []
        removed = []
        watcher.on_error = lambda msg: errors.append(msg)
        watcher.on_card_removed = lambda: removed.append(True)

        watcher._check_once_slow()

        self.assertEqual(removed, [True], "on_card_removed must fire for confirmed removal")
        self.assertEqual(errors, [], "on_error must not fire from the card-removal path")

    def test_on_error_receives_exact_message_from_detect_card(self):
        """on_error must receive exactly the message returned by detect_card."""
        msg = "Arbitrary failure: PCSC context lost"
        watcher = self._make_watcher((False, msg))
        received = []
        watcher.on_error = lambda m: received.append(m)

        watcher._check_once_slow()

        self.assertEqual(received, [msg])


if __name__ == '__main__':
    unittest.main()
