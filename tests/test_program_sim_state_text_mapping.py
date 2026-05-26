"""Targeted tests: Program SIM panel must consume the common/global status-text
mapping for reader and card state.  No local divergent wording is allowed.

Illegal mixed state being fixed:
  global status bar → "No smart-card reader detected"
  Program SIM action status → "Insert a SIM card..."

These tests verify:
1. ERROR/no-reader → Program SIM shows "No smart-card reader detected"
2. NO_CARD/reader-present → Program SIM shows the global insert-SIM text
3. Program SIM and global status agree for the no-reader case
4. NO_CARD → ERROR/no-reader transition updates Program SIM text
5. Repeated no-reader events do not revert Program SIM to insert-SIM wording
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import _NOT_POWERED_TEXT, _map_watcher_error
from state_manager import CardState, StateManager
from widgets.program_sim_panel import ProgramSIMPanel


NO_READER_MSG = "No smart-card reader detected"
READER_READY_MSG = "Reader connected — insert a SIM card"


@pytest.fixture()
def sm(qapp):
    return StateManager()


@pytest.fixture()
def panel(qapp, sm):
    cm = MagicMock()
    p = ProgramSIMPanel(None, cm, state_manager=sm)
    yield p
    p.deleteLater()


def _action_text(panel: ProgramSIMPanel) -> str:
    return panel._action_status.toPlainText()


# ---------------------------------------------------------------------------
# 1. ERROR / no-reader → Program SIM shows no-reader text
# ---------------------------------------------------------------------------

class TestProgramSimNoReaderText:
    """Program SIM must show no-reader text (not insert-SIM) when ERROR."""

    def test_no_reader_shows_no_reader_text(self, panel, sm):
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert NO_READER_MSG in _action_text(panel)

    def test_no_reader_does_not_show_insert_sim(self, panel, sm):
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert "Insert a SIM card" not in _action_text(panel)

    def test_no_reader_program_sim_matches_global_status(self, panel, sm):
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert _action_text(panel) == sm.status_text


# ---------------------------------------------------------------------------
# 2. NO_CARD / reader present → Program SIM shows global insert-SIM text
# ---------------------------------------------------------------------------

class TestProgramSimNoCardText:
    """NO_CARD with reader present must show the same text as global status."""

    def test_no_card_reader_present_shows_global_text(self, panel, sm):
        sm.status_text = READER_READY_MSG
        sm.card_state = CardState.NO_CARD
        assert _action_text(panel) == READER_READY_MSG

    def test_no_card_reader_present_does_not_show_no_reader(self, panel, sm):
        sm.status_text = READER_READY_MSG
        sm.card_state = CardState.NO_CARD
        assert "No smart-card reader" not in _action_text(panel)


# ---------------------------------------------------------------------------
# 3. Global status and Program SIM agree for no-reader
# ---------------------------------------------------------------------------

class TestProgramSimGlobalAgreement:
    """Program SIM action status and global status_text must be the same string
    for the no-reader condition."""

    def test_action_status_equals_global_status_on_no_reader(self, panel, sm):
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert _action_text(panel) == sm.status_text

    def test_no_mixed_state_insert_sim_vs_no_reader(self, panel, sm):
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        global_says_no_reader = "No smart-card reader" in sm.status_text
        panel_says_insert_sim = "Insert a SIM card" in _action_text(panel)
        assert not (global_says_no_reader and panel_says_insert_sim), (
            f"Illegal mixed state: global='{sm.status_text}' "
            f"panel='{_action_text(panel)}'"
        )


# ---------------------------------------------------------------------------
# 4. NO_CARD → ERROR transition updates Program SIM
# ---------------------------------------------------------------------------

class TestProgramSimTransition:
    """Going from NO_CARD (reader present) to ERROR (no reader) must update
    Program SIM action status."""

    def test_transition_no_card_to_no_reader_updates_panel(self, panel, sm):
        sm.status_text = READER_READY_MSG
        sm.card_state = CardState.NO_CARD
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert NO_READER_MSG in _action_text(panel)

    def test_transition_clears_insert_sim_text(self, panel, sm):
        sm.status_text = READER_READY_MSG
        sm.card_state = CardState.NO_CARD
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert "Insert a SIM card" not in _action_text(panel)


# ---------------------------------------------------------------------------
# 5. Repeated no-reader events do not revert to insert-SIM
# ---------------------------------------------------------------------------

class TestProgramSimRepeatedNoReader:
    """Repeated no-reader polls (same ERROR state) must not revert to
    'Insert a SIM card...' text."""

    def test_repeated_no_reader_keeps_no_reader_text(self, panel, sm):
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        _map_watcher_error(sm, NO_READER_MSG, CardState.ERROR, False)
        assert NO_READER_MSG in _action_text(panel)

    def test_repeated_no_reader_never_shows_insert_sim(self, panel, sm):
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        _map_watcher_error(sm, NO_READER_MSG, CardState.ERROR, False)
        assert "Insert a SIM card" not in _action_text(panel)


# ---------------------------------------------------------------------------
# 6. NOT_POWERED → Program SIM shows canonical status text, not local wording
# ---------------------------------------------------------------------------

class TestProgramSimNotPoweredText:
    """NOT_POWERED state: Program SIM must display the global canonical status
    text.  No local 'Insert a SIM card...' or other local wording."""

    def test_not_powered_shows_canonical_text(self, panel, sm):
        _map_watcher_error(sm, _NOT_POWERED_TEXT, CardState.NO_CARD, False)
        assert _NOT_POWERED_TEXT in _action_text(panel)

    def test_not_powered_matches_global_status(self, panel, sm):
        _map_watcher_error(sm, _NOT_POWERED_TEXT, CardState.NO_CARD, False)
        assert _action_text(panel) == sm.status_text

    def test_not_powered_does_not_show_insert_sim(self, panel, sm):
        _map_watcher_error(sm, _NOT_POWERED_TEXT, CardState.NO_CARD, False)
        assert "Insert a SIM card" not in _action_text(panel)
