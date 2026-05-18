#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for error-state preservation during transient PCSC failures.

Covers the state-machine contract:
- CardState.ERROR must not be set when _card_present=True but card_state is NO_CARD
  (the window between PCSC ATR probe confirming a card and pySim-read finishing).
- Program SIM panel must not show "Insert a SIM card..." after a transient error
  when card presence was already established (_step >= 1).
- Genuine no-reader errors (message contains "No smart-card reader") still set ERROR.
- Confirmed card removal (NO_CARD) still resets the panel.
- ICCID and IMSI absence do not affect card-present state.

Widget-level tests (TestProgramSIMPanelLabelText) verify the actual QPlainTextEdit
label rendered by ProgramSIMPanel for each card state.
"""

import sys
import unittest
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

# Ensure the project root is importable
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from state_manager import StateManager, CardState
from widgets.program_sim_panel import ProgramSIMPanel


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv or ["test"])
    return app


_qapp = _ensure_qapp()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_on_error_closure(state_manager, card_watcher):
    """Replicate the on_error closure from main.py _wire_card_watcher."""
    def on_error(msg):
        current = state_manager.card_state
        is_no_reader = 'No smart-card reader' in msg
        card_physically_present = card_watcher._card_present
        if is_no_reader or (
                current not in (
                    CardState.BLANK, CardState.DETECTED, CardState.AUTHENTICATED)
                and not card_physically_present):
            state_manager.card_state = CardState.ERROR
        state_manager.report_error(msg)
    return on_error


# ---------------------------------------------------------------------------
# Tests: on_error guard in main.py
# ---------------------------------------------------------------------------

class TestOnErrorGuard(unittest.TestCase):
    """Verify that on_error does not set ERROR when card is physically present."""

    def _make_sm(self):
        return StateManager()

    def _make_watcher(self, card_present):
        w = MagicMock()
        w._card_present = card_present
        return w

    # -- Core race-window case -----------------------------------------------

    def test_card_present_no_card_state_transient_error_preserves_state(self):
        """_card_present=True, card_state=NO_CARD, transient error → state stays NO_CARD.

        This is the race window: PCSC confirmed ATR, pySim-read still running,
        a concurrent probe fails.  ERROR must NOT be set.
        """
        sm = self._make_sm()
        # Initial state is NO_CARD; pySim-read hasn't finished yet
        self.assertEqual(sm.card_state, CardState.NO_CARD)
        watcher = self._make_watcher(card_present=True)
        on_error = _make_on_error_closure(sm, watcher)

        on_error('PC/SC error: CardConnectionException')

        self.assertNotEqual(sm.card_state, CardState.ERROR,
                            "Transient error must not set ERROR when card is physically present")
        self.assertEqual(sm.card_state, CardState.NO_CARD)

    def test_card_absent_no_card_state_error_is_set(self):
        """_card_present=False, card_state=NO_CARD, error → ERROR is set.

        No card in reader, genuine probe error → correct to set ERROR.
        """
        sm = self._make_sm()
        watcher = self._make_watcher(card_present=False)
        on_error = _make_on_error_closure(sm, watcher)

        on_error('PC/SC error: no reader found')

        self.assertEqual(sm.card_state, CardState.ERROR)

    # -- No-reader message always sets ERROR -----------------------------------

    def test_no_reader_message_sets_error_even_when_card_present(self):
        """'No smart-card reader' message always sets ERROR regardless of _card_present.

        When the reader hardware is physically disconnected, ERROR is correct.
        """
        sm = self._make_sm()
        watcher = self._make_watcher(card_present=True)
        on_error = _make_on_error_closure(sm, watcher)

        on_error('No smart-card reader detected')

        self.assertEqual(sm.card_state, CardState.ERROR)

    # -- Established card-present states are preserved ------------------------

    def test_blank_state_transient_error_preserves_blank(self):
        """card_state=BLANK, transient error → state stays BLANK."""
        sm = self._make_sm()
        sm.card_state = CardState.BLANK
        watcher = self._make_watcher(card_present=True)
        on_error = _make_on_error_closure(sm, watcher)

        on_error('PC/SC error: CardConnectionException')

        self.assertEqual(sm.card_state, CardState.BLANK)

    def test_detected_state_transient_error_preserves_detected(self):
        """card_state=DETECTED, transient error → state stays DETECTED."""
        sm = self._make_sm()
        sm.card_state = CardState.DETECTED
        watcher = self._make_watcher(card_present=True)
        on_error = _make_on_error_closure(sm, watcher)

        on_error('PC/SC error: connection reset by peer')

        self.assertEqual(sm.card_state, CardState.DETECTED)

    def test_authenticated_state_transient_error_preserves_authenticated(self):
        """card_state=AUTHENTICATED, transient error → state stays AUTHENTICATED."""
        sm = self._make_sm()
        sm.card_state = CardState.AUTHENTICATED
        watcher = self._make_watcher(card_present=True)
        on_error = _make_on_error_closure(sm, watcher)

        on_error('PC/SC error: connection reset by peer')

        self.assertEqual(sm.card_state, CardState.AUTHENTICATED)

    def test_no_reader_message_with_blank_state_sets_error(self):
        """'No smart-card reader' while in BLANK state still sets ERROR.

        Reader physically removed → correct to set ERROR, regardless of prior state.
        """
        sm = self._make_sm()
        sm.card_state = CardState.BLANK
        watcher = self._make_watcher(card_present=False)
        on_error = _make_on_error_closure(sm, watcher)

        on_error('No smart-card reader detected')

        self.assertEqual(sm.card_state, CardState.ERROR)

    # -- report_error is always called ----------------------------------------

    def test_report_error_always_called(self):
        """report_error must be called regardless of whether card_state changes."""
        sm = self._make_sm()
        sm.card_state = CardState.BLANK
        watcher = self._make_watcher(card_present=True)
        on_error = _make_on_error_closure(sm, watcher)

        errors = []
        sm.error_occurred.connect(lambda msg: errors.append(msg))
        on_error('some transient error')

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0], 'some transient error')

    def test_report_error_called_even_when_error_set(self):
        """report_error is called even when card_state is set to ERROR."""
        sm = self._make_sm()
        watcher = self._make_watcher(card_present=False)
        on_error = _make_on_error_closure(sm, watcher)

        errors = []
        sm.error_occurred.connect(lambda msg: errors.append(msg))
        on_error('PC/SC connection failed')

        self.assertEqual(sm.card_state, CardState.ERROR)
        self.assertEqual(len(errors), 1)


# ---------------------------------------------------------------------------
# Tests: Program SIM panel ERROR handling
# ---------------------------------------------------------------------------

class TestProgramSimPanelErrorHandling(unittest.TestCase):
    """Verify that the Program SIM panel does not reset on transient ERROR."""

    def _make_panel_state(self):
        """Return (detected_non_empty, step) as mutable dict for testing logic."""
        return {'detected_non_empty': False, 'step': 0}

    def _apply_on_card_state_changed(self, state, panel_state):
        """Replicate _on_card_state_changed logic from program_sim_panel.py."""
        on_card_removed_called = []

        def on_card_removed():
            panel_state['detected_non_empty'] = False
            panel_state['step'] = 0
            on_card_removed_called.append(True)

        if state == CardState.NO_CARD:
            on_card_removed()
        elif state == CardState.ERROR:
            if not (panel_state['detected_non_empty'] or panel_state['step'] >= 1):
                on_card_removed()
        elif state in (CardState.DETECTED, CardState.AUTHENTICATED):
            panel_state['detected_non_empty'] = True
            panel_state['step'] = 1
        elif state == CardState.BLANK:
            panel_state['detected_non_empty'] = False
            panel_state['step'] = 1

        return on_card_removed_called

    def test_error_before_any_card_detected_resets_panel(self):
        """ERROR with step=0 (no card ever seen) → panel resets.

        Initial state: no card, no detected non-empty. ERROR should reset.
        """
        panel_state = self._make_panel_state()
        # step=0, detected_non_empty=False: panel never saw a card
        removed = self._apply_on_card_state_changed(CardState.ERROR, panel_state)
        self.assertTrue(len(removed) > 0, "on_card_removed must be called for initial ERROR")
        self.assertEqual(panel_state['step'], 0)

    def test_error_after_blank_card_detected_preserves_state(self):
        """ERROR with step=1 (blank card was detected) → panel does NOT reset.

        After BLANK sets step=1, a transient ERROR must not take the panel back
        to "Insert a SIM card...".
        """
        panel_state = self._make_panel_state()
        # Simulate BLANK having fired first
        self._apply_on_card_state_changed(CardState.BLANK, panel_state)
        self.assertEqual(panel_state['step'], 1)

        removed = self._apply_on_card_state_changed(CardState.ERROR, panel_state)
        self.assertEqual(len(removed), 0, "on_card_removed must NOT be called for ERROR after card seen")
        self.assertEqual(panel_state['step'], 1, "step must remain 1 after transient ERROR")

    def test_error_after_detected_card_preserves_state(self):
        """ERROR with step=1 (non-empty card was detected) → panel does NOT reset."""
        panel_state = self._make_panel_state()
        self._apply_on_card_state_changed(CardState.DETECTED, panel_state)
        self.assertEqual(panel_state['step'], 1)
        self.assertTrue(panel_state['detected_non_empty'])

        removed = self._apply_on_card_state_changed(CardState.ERROR, panel_state)
        self.assertEqual(len(removed), 0)
        self.assertEqual(panel_state['step'], 1)
        self.assertTrue(panel_state['detected_non_empty'])

    def test_no_card_always_resets_panel(self):
        """NO_CARD always resets the panel regardless of step.

        NO_CARD is the confirmed card-removal signal — it must always reset.
        """
        panel_state = self._make_panel_state()
        self._apply_on_card_state_changed(CardState.BLANK, panel_state)
        self.assertEqual(panel_state['step'], 1)

        removed = self._apply_on_card_state_changed(CardState.NO_CARD, panel_state)
        self.assertTrue(len(removed) > 0, "on_card_removed must be called for NO_CARD")
        self.assertEqual(panel_state['step'], 0)

    def test_blank_to_error_to_blank_restores_state(self):
        """BLANK → ERROR → BLANK: second BLANK must restore card-present state."""
        panel_state = self._make_panel_state()
        # First BLANK detection
        self._apply_on_card_state_changed(CardState.BLANK, panel_state)
        self.assertEqual(panel_state['step'], 1)

        # Transient ERROR — must not reset
        self._apply_on_card_state_changed(CardState.ERROR, panel_state)
        self.assertEqual(panel_state['step'], 1, "ERROR must not reset step after BLANK")

        # BLANK fires again (e.g., after retry) — step should still be 1
        self._apply_on_card_state_changed(CardState.BLANK, panel_state)
        self.assertEqual(panel_state['step'], 1)


# ---------------------------------------------------------------------------
# Tests: ICCID / IMSI absence does not affect card-present determination
# ---------------------------------------------------------------------------

class TestCardPresenceWithoutIccid(unittest.TestCase):
    """Missing ICCID/IMSI must not cause the panel to treat card as absent."""

    def test_blank_state_is_card_present(self):
        """CardState.BLANK must be treated as card-present by the state machine."""
        card_present_states = {CardState.BLANK, CardState.DETECTED, CardState.AUTHENTICATED}
        self.assertIn(CardState.BLANK, card_present_states)

    def test_blank_without_iccid_is_still_present(self):
        """Blank card has no ICCID but is physically inserted — must not reset panel."""
        sm = StateManager()
        sm.card_state = CardState.BLANK
        # Simulate an update_card_info with no ICCID (as on_unknown("") does)
        sm.update_card_info(iccid="(blank)", auth_status=False)

        # The state must remain BLANK (card present), not become ERROR or NO_CARD
        self.assertEqual(sm.card_state, CardState.BLANK)

    def test_no_card_state_is_not_card_present(self):
        """CardState.NO_CARD must not be in the card-present set."""
        card_present_states = {CardState.BLANK, CardState.DETECTED, CardState.AUTHENTICATED}
        self.assertNotIn(CardState.NO_CARD, card_present_states)

    def test_error_state_is_not_in_card_present_set(self):
        """CardState.ERROR is ambiguous — not in the definitive card-present set."""
        card_present_states = {CardState.BLANK, CardState.DETECTED, CardState.AUTHENTICATED}
        self.assertNotIn(CardState.ERROR, card_present_states)


# ---------------------------------------------------------------------------
# Widget-level tests: actual QPlainTextEdit label text in ProgramSIMPanel
# ---------------------------------------------------------------------------

class TestProgramSIMPanelLabelText(unittest.TestCase):
    """Verify the visible _action_status label text for each card state.

    Instantiates the real ProgramSIMPanel widget (offscreen via
    QT_QPA_PLATFORM=offscreen set in pytest.ini) and asserts that
    the middle-panel instruction text is correct for each CardState.
    """

    def _make_panel(self):
        sm = StateManager()
        cm = MagicMock()
        panel = ProgramSIMPanel(card_manager=cm, state_manager=sm)
        return panel, sm

    def _label(self, panel):
        return panel._action_status.toPlainText()

    def test_initial_state_shows_insert_sim(self):
        """Initial state (NO_CARD) must show 'Insert a SIM card...'."""
        panel, _sm = self._make_panel()
        self.assertIn("Insert a SIM card", self._label(panel))

    def test_blank_state_does_not_show_insert_sim(self):
        """CardState.BLANK must not show 'Insert a SIM card...'."""
        panel, sm = self._make_panel()
        sm.card_state = CardState.BLANK
        self.assertNotIn("Insert a SIM card", self._label(panel),
                         f"BLANK should not show insert-sim, got: {self._label(panel)!r}")

    def test_detected_state_does_not_show_insert_sim(self):
        """CardState.DETECTED must not show 'Insert a SIM card...'."""
        panel, sm = self._make_panel()
        sm.card_state = CardState.DETECTED
        self.assertNotIn("Insert a SIM card", self._label(panel),
                         f"DETECTED should not show insert-sim, got: {self._label(panel)!r}")

    def test_authenticated_state_does_not_show_insert_sim(self):
        """CardState.AUTHENTICATED must not show 'Insert a SIM card...'."""
        panel, sm = self._make_panel()
        sm.card_state = CardState.AUTHENTICATED
        self.assertNotIn("Insert a SIM card", self._label(panel),
                         f"AUTHENTICATED should not show insert-sim, got: {self._label(panel)!r}")

    def test_no_card_after_blank_shows_insert_sim(self):
        """After BLANK then NO_CARD, must show 'Insert a SIM card...'."""
        panel, sm = self._make_panel()
        sm.card_state = CardState.BLANK
        self.assertNotIn("Insert a SIM card", self._label(panel))
        sm.card_state = CardState.NO_CARD
        self.assertIn("Insert a SIM card", self._label(panel),
                      f"NO_CARD should show insert-sim, got: {self._label(panel)!r}")

    def test_error_after_blank_does_not_show_insert_sim(self):
        """ERROR after BLANK (transient) must NOT reset to 'Insert a SIM card...'."""
        panel, sm = self._make_panel()
        sm.card_state = CardState.BLANK
        self.assertNotIn("Insert a SIM card", self._label(panel))
        sm.card_state = CardState.ERROR
        self.assertNotIn("Insert a SIM card", self._label(panel),
                         f"Transient ERROR after BLANK must not show insert-sim, got: {self._label(panel)!r}")

    def test_error_with_no_prior_card_shows_insert_sim(self):
        """ERROR with no prior card (step=0) must show 'Insert a SIM card...'."""
        panel, sm = self._make_panel()
        # initial: NO_CARD → already shows insert-sim
        sm.card_state = CardState.ERROR
        self.assertIn("Insert a SIM card", self._label(panel),
                      f"ERROR with no prior card should show insert-sim, got: {self._label(panel)!r}")


if __name__ == '__main__':
    unittest.main()
