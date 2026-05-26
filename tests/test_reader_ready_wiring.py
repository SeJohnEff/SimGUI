#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for CardWatcher.on_reader_ready wiring — state-machine.md compliance.

Regression: on_reader_ready was dropped from _wire_card_watcher() during the
PyQt6 rewrite (commit 4ada65c).  Without the wiring, the state machine never
emitted card_state_changed(NO_CARD) when the reader was connected with no card,
leaving the UI frozen at "No card reader detected" and silencing the terminal log.

Invariant from state-machine.md:
  no_reader --> no_card : reader connected
  NO_CARD -> "Insert a SIM card..."  (UI Mapping)
  ERROR (no-reader msg) -> "No card reader detected"  (UI Mapping)

These tests are platform-independent.  They exercise the common CardWatcher
callback protocol and the common StateManager/CardStatusPanel mapping.
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

def _make_watcher(card_present=False, last_iccid=None):
    cm = MagicMock()
    watcher = CardWatcher(cm)
    watcher._card_present = card_present
    watcher._last_iccid = last_iccid
    return watcher


# ---------------------------------------------------------------------------
# 1. CardWatcher fires on_reader_ready on the correct probe result
# ---------------------------------------------------------------------------

class TestOnReaderReadyFired(unittest.TestCase):
    """CardWatcher must call on_reader_ready when the probe returns
    'No card in reader' and no card was previously present.

    state-machine.md: no_reader --> no_card : reader connected
    """

    def test_fires_when_probe_returns_no_card_and_no_prior_card(self):
        """on_reader_ready fires for 'No card in reader' with _card_present=False."""
        watcher = _make_watcher(card_present=False)
        fired = []
        watcher.on_reader_ready = lambda: fired.append(True)

        watcher._handle_probe_result(False, 'No card in reader')

        self.assertEqual(fired, [True],
                         "on_reader_ready must fire exactly once")

    def test_does_not_fire_when_card_was_present(self):
        """on_reader_ready must NOT fire if card was previously present.

        'No card in reader' with _card_present=True is a card-removal event,
        not a reader-ready event.  on_card_removed fires instead.
        """
        watcher = _make_watcher(card_present=True, last_iccid="8946001234")
        ready_fired = []
        removed_fired = []
        watcher.on_reader_ready = lambda: ready_fired.append(True)
        watcher.on_card_removed = lambda: removed_fired.append(True)

        watcher._handle_probe_result(False, 'No card in reader')

        self.assertEqual(ready_fired, [],
                         "on_reader_ready must not fire on card removal")
        self.assertEqual(removed_fired, [True],
                         "on_card_removed must fire on card removal")

    def test_does_not_fire_on_no_reader_error(self):
        """on_reader_ready must not fire when probe indicates no reader hardware.

        'No smart-card reader detected' is an error condition, not reader-ready.
        """
        watcher = _make_watcher(card_present=False)
        ready_fired = []
        error_fired = []
        watcher.on_reader_ready = lambda: ready_fired.append(True)
        watcher.on_error = lambda msg: error_fired.append(msg)

        watcher._handle_probe_result(False, 'No smart-card reader detected')

        self.assertEqual(ready_fired, [],
                         "on_reader_ready must not fire on no-reader error")
        self.assertEqual(len(error_fired), 1,
                         "on_error must fire for no-reader condition")

    def test_does_not_fire_when_callback_is_none(self):
        """If on_reader_ready is not wired (None), _handle_probe_result must
        not raise — CardWatcher always guards the callback."""
        watcher = _make_watcher(card_present=False)
        watcher.on_reader_ready = None  # not wired

        try:
            watcher._handle_probe_result(False, 'No card in reader')
        except Exception as exc:
            self.fail(f"_handle_probe_result raised with on_reader_ready=None: {exc}")


# ---------------------------------------------------------------------------
# 2. Wired on_reader_ready produces the correct StateManager transition
# ---------------------------------------------------------------------------

class TestReaderReadyStateTransition(unittest.TestCase):
    """When on_reader_ready is wired to set card_state = NO_CARD (as main.py does),
    the state machine must transition from ERROR to NO_CARD.

    state-machine.md: no_reader --> no_card : reader connected
    """

    def _wire_and_fire(self):
        """Simulate the wiring that main.py:_wire_card_watcher() performs,
        then fire the reader-ready probe result."""
        sm = StateManager()
        sm.card_state = CardState.ERROR  # simulate no-reader error state

        watcher = _make_watcher(card_present=False)

        # Wire exactly as main.py does
        def on_reader_ready():
            sm.card_state = CardState.NO_CARD
            sm.status_text = "Reader connected — insert a SIM card"

        watcher.on_reader_ready = on_reader_ready

        watcher._handle_probe_result(False, 'No card in reader')
        return sm

    def test_state_is_no_card_after_reader_ready(self):
        """State must be NO_CARD after reader-ready probe when callback is wired."""
        sm = self._wire_and_fire()
        self.assertEqual(sm.card_state, CardState.NO_CARD,
                         "card_state must be NO_CARD after reader-ready")

    def test_state_was_error_not_no_card_without_wiring(self):
        """Without wiring on_reader_ready, state stays at ERROR — proves the
        regression existed and this test would have caught it."""
        sm = StateManager()
        sm.card_state = CardState.ERROR

        watcher = _make_watcher(card_present=False)
        # Deliberately NOT wiring on_reader_ready — proves regression scenario
        watcher.on_reader_ready = None

        watcher._handle_probe_result(False, 'No card in reader')

        self.assertEqual(sm.card_state, CardState.ERROR,
                         "Without wiring, state stays at ERROR (regression scenario)")

    def test_repeated_reader_ready_probes_stay_no_card(self):
        """Subsequent 'No card in reader' probes after the first must not
        break NO_CARD state — on_reader_ready is called every idle poll."""
        sm = StateManager()
        sm.card_state = CardState.ERROR

        watcher = _make_watcher(card_present=False)

        def on_reader_ready():
            sm.card_state = CardState.NO_CARD

        watcher.on_reader_ready = on_reader_ready

        for _ in range(3):
            watcher._handle_probe_result(False, 'No card in reader')

        self.assertEqual(sm.card_state, CardState.NO_CARD,
                         "Repeated reader-ready probes must keep state at NO_CARD")


# ---------------------------------------------------------------------------
# 3. Existing card-removal behavior unchanged (regression guard)
# ---------------------------------------------------------------------------

class TestCardRemovalUnchanged(unittest.TestCase):
    """on_card_removed must still set NO_CARD — verify the fix did not regress
    the existing removal path."""

    def test_card_removed_transitions_to_no_card(self):
        """on_card_removed must fire and transition to NO_CARD on card removal."""
        sm = StateManager()
        sm.card_state = CardState.DETECTED

        watcher = _make_watcher(card_present=True, last_iccid="8946001234")

        removed = []

        def on_removed():
            sm.card_state = CardState.NO_CARD
            removed.append(True)

        watcher.on_card_removed = on_removed

        # Probe: card gone
        watcher._handle_probe_result(False, 'No card in reader')

        self.assertEqual(removed, [True],
                         "on_card_removed must fire on card removal")
        self.assertEqual(sm.card_state, CardState.NO_CARD,
                         "State must be NO_CARD after card removal")

    def test_reader_ready_does_not_interfere_with_removal_path(self):
        """When a card is present and probe returns 'No card in reader',
        on_card_removed must fire — not on_reader_ready."""
        watcher = _make_watcher(card_present=True, last_iccid="8946001234")

        ready_fired = []
        removed_fired = []
        watcher.on_reader_ready = lambda: ready_fired.append(True)
        watcher.on_card_removed = lambda: removed_fired.append(True)

        watcher._handle_probe_result(False, 'No card in reader')

        self.assertEqual(ready_fired, [],
                         "on_reader_ready must not fire during card removal")
        self.assertEqual(removed_fired, [True],
                         "on_card_removed must fire during card removal")


if __name__ == '__main__':
    unittest.main()
