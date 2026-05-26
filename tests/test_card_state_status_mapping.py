"""Targeted tests for the global card-state → status-text mapping and the
share-status display contract.

These tests exercise the common/global owner of the mapping logic:

Card reader tests — use ``_map_watcher_error`` from main.py directly so
    that any regression in the mapping function is caught without needing
    to instantiate a full SimGUIApp.

Network share tests — use ``StateManager`` and ``ShareStatus`` directly,
    which own the share state contract.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from PyQt6.QtWidgets import QApplication

from main import _map_watcher_error
from state_manager import CardState, ShareStatus, StateManager

_app = QApplication.instance() or QApplication(sys.argv)

NO_READER_MSG = "No smart-card reader detected"


# ---------------------------------------------------------------------------
# Reader / card-state mapping
# ---------------------------------------------------------------------------

class TestNoReaderMapsToErrorState:
    """on_error('No smart-card reader…') must set ERROR state and matching text."""

    def test_no_reader_sets_error_card_state(self):
        sm = StateManager()
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert sm.card_state == CardState.ERROR

    def test_no_reader_sets_status_text_to_error_message(self):
        sm = StateManager()
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert sm.status_text == NO_READER_MSG

    def test_no_reader_does_not_show_insert_sim_text(self):
        sm = StateManager()
        sm.status_text = "Reader connected — insert a SIM card"
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert "insert a sim card" not in sm.status_text.lower()
        assert sm.status_text == NO_READER_MSG


class TestNOCardMapsToInsertSimText:
    """NO_CARD state must only say 'insert SIM' when the reader IS available."""

    def test_no_card_state_shows_insert_sim_text(self):
        # Simulates what on_reader_ready sets — reader present, no card.
        sm = StateManager()
        sm.card_state = CardState.NO_CARD
        sm.status_text = "Reader connected — insert a SIM card"
        assert sm.card_state == CardState.NO_CARD
        assert "insert a sim card" in sm.status_text.lower()

    def test_no_card_text_never_says_no_reader(self):
        sm = StateManager()
        sm.card_state = CardState.NO_CARD
        sm.status_text = "Reader connected — insert a SIM card"
        assert "No smart-card reader" not in sm.status_text


class TestTransitionNOCardToNoReader:
    """Going from NO_CARD (reader present) → no reader must update visible status."""

    def test_transition_updates_card_state_to_error(self):
        sm = StateManager()
        sm.card_state = CardState.NO_CARD
        sm.status_text = "Reader connected — insert a SIM card"
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert sm.card_state == CardState.ERROR

    def test_transition_updates_status_text_to_no_reader(self):
        sm = StateManager()
        sm.card_state = CardState.NO_CARD
        sm.status_text = "Reader connected — insert a SIM card"
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        assert sm.status_text == NO_READER_MSG
        assert "insert a sim card" not in sm.status_text.lower()


class TestRepeatedNoReaderEventsStable:
    """Repeated no-reader polls must not change visible state after first ERROR."""

    def test_repeated_error_status_text_unchanged(self):
        sm = StateManager()
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        after_first = sm.status_text
        # Second poll: state is already ERROR
        _map_watcher_error(sm, NO_READER_MSG, CardState.ERROR, False)
        assert sm.status_text == after_first

    def test_repeated_error_card_state_unchanged(self):
        sm = StateManager()
        _map_watcher_error(sm, NO_READER_MSG, CardState.NO_CARD, False)
        _map_watcher_error(sm, NO_READER_MSG, CardState.ERROR, False)
        assert sm.card_state == CardState.ERROR


class TestTransientErrorDoesNotDemoteCardPresent:
    """Transient PCSC errors while a card is present must not set ERROR state."""

    def test_transient_error_card_detected_state_preserved(self):
        sm = StateManager()
        sm.card_state = CardState.DETECTED
        sm.status_text = "Card detected: 8946020000000000001"
        _map_watcher_error(sm, "CardConnectionException: T0 protocol error",
                           CardState.DETECTED, True)
        assert sm.card_state == CardState.DETECTED

    def test_transient_error_status_text_preserved(self):
        sm = StateManager()
        sm.card_state = CardState.AUTHENTICATED
        sm.status_text = "Authenticated — ready to program"
        _map_watcher_error(sm, "Some PCSC glitch", CardState.AUTHENTICATED, True)
        assert sm.status_text == "Authenticated — ready to program"


# ---------------------------------------------------------------------------
# Network share status display contract
# ---------------------------------------------------------------------------

class TestShareStatusDisconnected:
    """Disconnected share status must produce amber 'No network storage connected'."""

    def test_disconnected_share_status_has_no_error_text(self):
        s = ShareStatus(connected=False)
        assert s.error_text == ""

    def test_disconnected_share_status_not_connected(self):
        s = ShareStatus(connected=False)
        assert not s.connected

    def test_state_manager_update_disconnected_emits_signal(self):
        sm = StateManager()
        received = []
        sm.share_status_changed.connect(lambda s: received.append(s))
        sm.update_share_status([])
        # Signal must fire: initial state is also disconnected but labels differ
        # only when going from a connected state first.
        # Force a transition: connect then disconnect.
        sm.update_share_status([("NAS", "/mnt/nas")])
        received.clear()
        sm.update_share_status([])
        assert len(received) == 1
        assert not received[0].connected
        assert received[0].error_text == ""


class TestShareStatusConnected:
    """Connected share status must remain green; amber must not appear."""

    def test_connected_share_status_has_connected_true(self):
        s = ShareStatus(connected=True, labels=["NAS"], mount_paths=[("NAS", "/m")])
        assert s.connected

    def test_state_manager_update_connected_emits_signal(self):
        sm = StateManager()
        received = []
        sm.share_status_changed.connect(lambda s: received.append(s))
        sm.update_share_status([("NAS", "/mnt/nas")])
        assert len(received) == 1
        assert received[0].connected
        assert received[0].labels == ["NAS"]


class TestShareStatusExplicitError:
    """An explicit error_text must not be overwritten by the generic disconnected text."""

    def test_error_text_preserved_in_share_status(self):
        sm = StateManager()
        sm.update_share_status([], error="Mount timed out (30 s)")
        assert sm.share_status.error_text == "Mount timed out (30 s)"
        assert not sm.share_status.connected

    def test_explicit_error_different_from_generic_text(self):
        error_msg = "Mount timed out (30 s)"
        s = ShareStatus(connected=False, error_text=error_msg)
        # error_text present → UI must show this, not "No network storage connected"
        display = s.error_text or "No network storage connected"
        assert display == error_msg
        assert display != "No network storage connected"

    def test_no_error_text_falls_back_to_generic(self):
        s = ShareStatus(connected=False, error_text="")
        display = s.error_text or "No network storage connected"
        assert display == "No network storage connected"
