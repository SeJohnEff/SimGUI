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
from widgets.card_status_panel import CardStatusPanel


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv or ["test"])
    return app


_qapp = _ensure_qapp()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_panel(sm=None):
    if sm is None:
        sm = StateManager()
    panel = CardStatusPanel(state_manager=sm)
    return panel, sm


def _status_text(panel):
    return panel.status_label.text()


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


# ---------------------------------------------------------------------------
# 2. CardStatusPanel status mapping per state-machine.md UI Mapping table
# ---------------------------------------------------------------------------

class TestCardStatusPanelStateMapping(unittest.TestCase):
    """CardStatusPanel must map card states and error messages to the correct
    status text per the state-machine.md UI Mapping table.

    These tests are platform-independent: they exercise common signal/slot
    wiring and state mapping, not device-specific detection logic.
    """

    def test_reader_missing_error_shows_no_reader_not_insert_sim(self):
        """state-machine.md: ERROR (no-reader msg) -> 'No card reader detected'.

        'Insert a SIM card...' must never be shown when no reader is detected.
        """
        panel, sm = _make_panel()

        sm.report_error("No smart-card reader detected")

        text = _status_text(panel)
        self.assertNotIn(
            "Insert a SIM card", text,
            f"reader-missing error must not show insert-sim; got: {text!r}")
        self.assertIn(
            "reader", text.lower(),
            f"reader-missing error must mention reader; got: {text!r}")

    def test_tool_missing_error_shows_error_not_insert_sim(self):
        """state-machine.md: ERROR (tool-missing msg) -> error state.

        'pySim not found' must produce an error status, not 'Insert a SIM card...'.
        """
        panel, sm = _make_panel()

        sm.report_error("No CLI tool found. Install pySim and restart.")

        text = _status_text(panel)
        self.assertNotIn(
            "Insert a SIM card", text,
            f"tool-missing error must not show insert-sim; got: {text!r}")

    def test_no_card_state_shows_insert_sim(self):
        """state-machine.md: NO_CARD -> 'Insert a SIM card...'.

        Reader is present but no card — correct to show 'Insert a SIM card...'.
        Transition via BLANK -> NO_CARD to force signal emission (StateManager
        deduplicates same-value assignments).
        """
        panel, sm = _make_panel()
        sm.card_state = CardState.BLANK
        sm.card_state = CardState.NO_CARD

        text = _status_text(panel)
        self.assertIn(
            "Insert a SIM card", text,
            f"NO_CARD must show insert-sim; got: {text!r}")

    def test_blank_state_does_not_show_insert_sim(self):
        """state-machine.md: BLANK -> card-present (not 'Insert a SIM card...')."""
        panel, sm = _make_panel()
        sm.card_state = CardState.BLANK

        text = _status_text(panel)
        self.assertNotIn(
            "Insert a SIM card", text,
            f"BLANK must not show insert-sim; got: {text!r}")

    def test_detected_state_does_not_show_insert_sim(self):
        """state-machine.md: DETECTED -> card-present (not 'Insert a SIM card...')."""
        panel, sm = _make_panel()
        sm.card_state = CardState.DETECTED

        text = _status_text(panel)
        self.assertNotIn(
            "Insert a SIM card", text,
            f"DETECTED must not show insert-sim; got: {text!r}")

    def test_authenticated_state_does_not_show_insert_sim(self):
        """state-machine.md: AUTHENTICATED -> card-present."""
        panel, sm = _make_panel()
        sm.card_state = CardState.AUTHENTICATED

        text = _status_text(panel)
        self.assertNotIn(
            "Insert a SIM card", text,
            f"AUTHENTICATED must not show insert-sim; got: {text!r}")

    def test_transient_error_after_blank_does_not_show_insert_sim(self):
        """state-machine.md ERROR-handling: ERROR after BLANK is transient.

        _on_card_state_changed(ERROR) does nothing for card_status_panel
        (it delegates to _on_error_occurred).  Without a report_error call,
        the label must stay at the BLANK display, not reset to insert-sim.
        """
        panel, sm = _make_panel()
        sm.card_state = CardState.BLANK
        sm.card_state = CardState.ERROR

        text = _status_text(panel)
        self.assertNotIn(
            "Insert a SIM card", text,
            f"transient ERROR after BLANK must not show insert-sim; got: {text!r}")

    def test_reader_missing_then_card_detected_shows_detected(self):
        """After a no-reader error, DETECTED must show card-present status."""
        panel, sm = _make_panel()

        sm.report_error("No smart-card reader detected")
        self.assertNotIn("Insert a SIM card", _status_text(panel))

        sm.card_state = CardState.DETECTED
        text = _status_text(panel)
        self.assertNotIn(
            "Insert a SIM card", text,
            f"DETECTED after no-reader must not show insert-sim; got: {text!r}")
        self.assertIn(
            "detect", text.lower(),
            f"DETECTED after no-reader must show detected status; got: {text!r}")


if __name__ == '__main__':
    unittest.main()
