"""Targeted tests: Program SIM no-op and sticky-result behavior.

Covers:
1. No-op status text shown exactly
2. No artifact created on no-op
3. Watcher poll (card-state signal) does NOT overwrite sticky no-op for same ICCID
4. Card removal clears sticky — status can be overwritten afterward
5. Different ICCID (rapid card swap) clears sticky
6. Successful programming result is also sticky for same ICCID
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from state_manager import CardState, CardInfo, StateManager, ProgramOutcome, ProgramResult
from widgets.program_sim_panel import ProgramSIMPanel

NOOP_MSG_FROM_MANAGER = "No changes to program — card data already matches"
EXPECTED_NOOP_DISPLAY = "No changes to program — card already matches CSV data"


def _make_panel(sm):
    cm = MagicMock()
    return ProgramSIMPanel(None, cm, state_manager=sm), cm


def _action_text(panel: ProgramSIMPanel) -> str:
    return panel._action_status.toPlainText()


def _put_card_in_panel(panel: ProgramSIMPanel, sm: StateManager, iccid: str = "8946020123456789012"):
    """Drive panel into a card-detected state with a given ICCID."""
    panel._field_entries["ICCID"].setText(iccid)
    panel._field_entries["ADM1"].setText("88888888")
    sm.card_state = CardState.DETECTED


def _simulate_noop(panel: ProgramSIMPanel, cm: MagicMock, iccid: str):
    """Wire card manager to return no-op and call _on_program."""
    cm.authenticate.return_value = (True, "OK")
    cm.program_card.return_value = (True, NOOP_MSG_FROM_MANAGER, ProgramResult(outcome=ProgramOutcome.NO_CHANGES, message=NOOP_MSG_FROM_MANAGER))
    panel._step = 1
    panel._field_entries["ICCID"].setText(iccid)
    panel._field_entries["ADM1"].setText("88888888")
    panel._on_program()


# ---------------------------------------------------------------------------
# 1. No-op status text shown correctly
# ---------------------------------------------------------------------------

class TestNoopStatusText:
    def test_noop_shows_expected_text(self, qapp, sm=None):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        _put_card_in_panel(panel, sm)
        _simulate_noop(panel, cm, "8946020123456789012")
        assert _action_text(panel) == EXPECTED_NOOP_DISPLAY
        panel.deleteLater()

    def test_noop_does_not_show_manager_raw_message(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        _put_card_in_panel(panel, sm)
        _simulate_noop(panel, cm, "8946020123456789012")
        assert "card data already matches" not in _action_text(panel)
        panel.deleteLater()

    def test_noop_not_shown_as_error(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        _put_card_in_panel(panel, sm)
        _simulate_noop(panel, cm, "8946020123456789012")
        # error style uses error color; normal style has no override — just check
        # the stylesheet is NOT the error stylesheet
        style = panel._action_status.styleSheet()
        from qt_theme import QtTheme
        error_color = QtTheme.get_color("error")
        assert error_color not in style
        panel.deleteLater()


# ---------------------------------------------------------------------------
# 2. No artifact created on no-op
# ---------------------------------------------------------------------------

class TestNoopNoArtifact:
    def test_no_artifact_callback_on_noop(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        artifact_cb = MagicMock(return_value=["/path/to/artifact.json"])
        panel.on_card_programmed_callback = artifact_cb
        _put_card_in_panel(panel, sm)
        _simulate_noop(panel, cm, "8946020123456789012")
        artifact_cb.assert_not_called()
        panel.deleteLater()

    def test_artifact_message_not_in_status_on_noop(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        panel.on_card_programmed_callback = MagicMock(return_value=["/a/b.json"])
        _put_card_in_panel(panel, sm)
        _simulate_noop(panel, cm, "8946020123456789012")
        assert "Artifact" not in _action_text(panel)
        panel.deleteLater()


# ---------------------------------------------------------------------------
# 3. Watcher refresh (card-state signal) does NOT overwrite sticky no-op
# ---------------------------------------------------------------------------

class TestNoopStickyAgainstWatcher:
    def test_card_state_signal_does_not_overwrite_noop(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        _put_card_in_panel(panel, sm, "8946020123456789012")
        _simulate_noop(panel, cm, "8946020123456789012")
        assert _action_text(panel) == EXPECTED_NOOP_DISPLAY
        # Simulate card-watcher poll: re-emit DETECTED state (same card still in)
        sm.card_state = CardState.DETECTED
        assert _action_text(panel) == EXPECTED_NOOP_DISPLAY

    def test_authenticated_state_does_not_overwrite_noop(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        _put_card_in_panel(panel, sm, "8946020123456789012")
        _simulate_noop(panel, cm, "8946020123456789012")
        sm.card_state = CardState.AUTHENTICATED
        assert _action_text(panel) == EXPECTED_NOOP_DISPLAY

    def test_card_info_signal_does_not_overwrite_noop(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        iccid = "8946020123456789012"
        _put_card_in_panel(panel, sm, iccid)
        _simulate_noop(panel, cm, iccid)
        # Same card info re-emitted by watcher
        sm.update_card_info(iccid=iccid, imsi="242010000000001")
        assert _action_text(panel) == EXPECTED_NOOP_DISPLAY

    def test_repeated_state_polls_do_not_overwrite_noop(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        _put_card_in_panel(panel, sm, "8946020123456789012")
        _simulate_noop(panel, cm, "8946020123456789012")
        # Three successive watcher polls
        for _ in range(3):
            sm.card_state = CardState.DETECTED
        assert _action_text(panel) == EXPECTED_NOOP_DISPLAY


# ---------------------------------------------------------------------------
# 4. Card removal clears sticky
# ---------------------------------------------------------------------------

class TestStickyCleared_CardRemoval:
    def test_card_removed_clears_sticky(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        iccid = "8946020123456789012"
        _put_card_in_panel(panel, sm, iccid)
        _simulate_noop(panel, cm, iccid)
        assert panel._sticky_result_iccid is not None
        # Remove card
        sm.card_state = CardState.NO_CARD
        assert panel._sticky_result_iccid is None

    def test_after_removal_watcher_can_overwrite_status(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        iccid = "8946020123456789012"
        _put_card_in_panel(panel, sm, iccid)
        _simulate_noop(panel, cm, iccid)
        sm.card_state = CardState.NO_CARD
        # Status should now reflect no-card state, not the old no-op text
        assert _action_text(panel) != EXPECTED_NOOP_DISPLAY


# ---------------------------------------------------------------------------
# 5. Different ICCID (rapid card swap) clears sticky
# ---------------------------------------------------------------------------

class TestStickyCleared_DifferentIccid:
    def test_different_iccid_card_info_clears_sticky(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        iccid_a = "8946020123456789012"
        _put_card_in_panel(panel, sm, iccid_a)
        _simulate_noop(panel, cm, iccid_a)
        assert panel._sticky_result_iccid == iccid_a
        # Different card inserted without going through NO_CARD
        iccid_b = "8946020987654321098"
        sm.update_card_info(iccid=iccid_b, imsi="242010000000099")
        assert panel._sticky_result_iccid is None

    def test_same_iccid_card_info_preserves_sticky(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        iccid = "8946020123456789012"
        _put_card_in_panel(panel, sm, iccid)
        _simulate_noop(panel, cm, iccid)
        sm.update_card_info(iccid=iccid, imsi="242010000000001")
        assert panel._sticky_result_iccid == iccid


# ---------------------------------------------------------------------------
# 6. Successful programming result is also sticky for same ICCID
# ---------------------------------------------------------------------------

class TestSuccessSticky:
    def _simulate_success(self, panel, cm, iccid):
        cm.authenticate.return_value = (True, "OK")
        cm.program_card.return_value = (True, "Programming complete", ProgramResult(outcome=ProgramOutcome.WRITE_OK_VERIFIED, message="Programming complete"))
        panel._step = 1
        panel._field_entries["ICCID"].setText(iccid)
        panel._field_entries["ADM1"].setText("88888888")
        panel._on_program()

    def test_success_result_is_sticky(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        iccid = "8946020123456789012"
        _put_card_in_panel(panel, sm, iccid)
        self._simulate_success(panel, cm, iccid)
        success_text = _action_text(panel)
        # Watcher poll
        sm.card_state = CardState.AUTHENTICATED
        assert _action_text(panel) == success_text

    def test_success_sticky_cleared_on_removal(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        iccid = "8946020123456789012"
        _put_card_in_panel(panel, sm, iccid)
        self._simulate_success(panel, cm, iccid)
        assert panel._sticky_result_iccid == iccid
        sm.card_state = CardState.NO_CARD
        assert panel._sticky_result_iccid is None


# ---------------------------------------------------------------------------
# 7. on_card_detected (index update) does NOT overwrite sticky for same ICCID
# ---------------------------------------------------------------------------

class TestOnCardDetectedStickyGuard:
    """on_card_detected must not overwrite sticky result for the same ICCID."""

    _CARD_DATA = {"ICCID": "8946020123456789012", "IMSI": "242010000000001", "ADM1": "88888888"}
    _ICCID = "8946020123456789012"

    def test_same_iccid_card_data_does_not_overwrite_success_sticky(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        _put_card_in_panel(panel, sm, self._ICCID)
        cm.authenticate.return_value = (True, "OK")
        cm.program_card.return_value = (True, "Programming complete", ProgramResult(outcome=ProgramOutcome.WRITE_OK_VERIFIED, message="Programming complete"))
        panel._step = 1
        panel._on_program()
        success_text = _action_text(panel)
        panel.on_card_detected(self._ICCID, card_data=self._CARD_DATA)
        assert _action_text(panel) == success_text
        panel.deleteLater()

    def test_same_iccid_card_data_does_not_overwrite_noop_sticky(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        _put_card_in_panel(panel, sm, self._ICCID)
        _simulate_noop(panel, cm, self._ICCID)
        assert _action_text(panel) == EXPECTED_NOOP_DISPLAY
        panel.on_card_detected(self._ICCID, card_data=self._CARD_DATA)
        assert _action_text(panel) == EXPECTED_NOOP_DISPLAY
        panel.deleteLater()

    def test_no_sticky_card_data_shows_loaded_from_index(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        # No sticky — fresh detection
        panel.on_card_detected(self._ICCID, card_data=self._CARD_DATA)
        assert "data loaded from" in _action_text(panel)
        panel.deleteLater()

    def test_different_iccid_card_data_shows_normal_status(self, qapp):
        sm = StateManager()
        panel, cm = _make_panel(sm)
        _put_card_in_panel(panel, sm, self._ICCID)
        _simulate_noop(panel, cm, self._ICCID)
        assert panel._sticky_result_iccid == self._ICCID
        iccid_b = "8946020987654321098"
        panel.on_card_detected(iccid_b, card_data={"ICCID": iccid_b, "IMSI": "242010000000099", "ADM1": "88888888"})
        assert "data loaded from" in _action_text(panel)
        panel.deleteLater()
