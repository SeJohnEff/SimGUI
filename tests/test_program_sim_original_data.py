"""
Tests for ProgramSIMPanel original_data / delta-baseline correctness.

Bug: on_card_detected(card_data=target_row) was setting _original_form_data
equal to the target fields, so program_card saw zero delta and wrote nothing.

Fix: _original_form_data must stay empty when target data is loaded; the
delta baseline must come from CardManager._original_card_data (physical read).
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from managers.card_manager import CardManager, CardType
from state_manager import CardInfo, CardState, StateManager
from widgets.program_sim_panel import ProgramSIMPanel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sm(qapp):
    return StateManager()


@pytest.fixture()
def cm():
    return CardManager()


@pytest.fixture()
def panel(qapp, sm, cm):
    p = ProgramSIMPanel(None, cm, state_manager=sm)
    yield p
    p.deleteLater()


# ---------------------------------------------------------------------------
# Bug 2 — on_card_detected must not bake target fields into _original_form_data
# ---------------------------------------------------------------------------

class TestOriginalFormDataNotSetFromTargetData:
    """Loading target CSV/index data must NOT set _original_form_data."""

    def test_original_form_data_empty_after_on_card_detected_with_card_data(self, panel):
        """_original_form_data stays {} when target row is loaded."""
        target = {
            "ICCID": "8949440000001775004",
            "IMSI": "999880001000001",
            "Ki": "aabbccddeeff00112233445566778899",
            "OPc": "00112233445566778899aabbccddeeff",
            "ADM1": "3838383838383838",
        }
        panel.on_card_detected("8949440000001775004", card_data=target)
        assert panel._original_form_data == {}, (
            "_original_form_data must be empty so program_card falls back to "
            "CardManager._original_card_data (physical read), not the target row"
        )

    def test_original_form_data_empty_after_no_card_data(self, panel):
        """_original_form_data stays {} when card is not in index (no card_data)."""
        panel.on_card_detected("8949440000001775004")
        assert panel._original_form_data == {}

    def test_program_card_called_with_none_original_data_when_target_loaded(
            self, panel, sm, cm):
        """program_card receives original_data=None so CardManager uses its own baseline."""
        # Arrange: physical card state in CardManager
        cm._original_card_data = {
            "ICCID": "8949440000001775004",
            "IMSI": "999700000177500",   # old IMSI on physical card
        }
        cm.card_type = CardType.SJA5
        cm.card_info = {"ICCID": "8949440000001775004", "IMSI": "999700000177500"}

        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8949440000001775004", imsi="999700000177500",
                            auth_status=False)

        target = {
            "ICCID": "8949440000001775004",
            "IMSI": "999880001000001",   # new IMSI to write
            "ADM1": "3838383838383838",
        }
        panel.on_card_detected("8949440000001775004", card_data=target)

        # program_card must be called with original_data=None
        calls = []

        def _fake_program(card_data, original_data=None):
            from state_manager import ProgramOutcome, ProgramResult
            calls.append(original_data)
            return True, "ok", ProgramResult(outcome=ProgramOutcome.WRITE_OK_VERIFIED, message="ok")

        cm.program_card = _fake_program
        cm.authenticate = MagicMock(return_value=(True, "ok"))

        panel._on_program()

        assert calls, "program_card must be called"
        assert calls[0] is None, (
            f"program_card must receive original_data=None, got {calls[0]!r}"
        )


# ---------------------------------------------------------------------------
# SJA5 delta: old IMSI vs new IMSI reaches _program_nonempty_card with change
# ---------------------------------------------------------------------------

class TestSJA5DeltaWithImsiChange:
    """CardManager.program_card must detect IMSI change for SJA5 cards."""

    def _make_sja5_cm(self, old_imsi: str) -> CardManager:
        cm = CardManager()
        cm.card_type = CardType.SJA5
        cm._original_card_data = {
            "ICCID": "8949440000001775004",
            "IMSI": old_imsi,
            "ACC": "ffff",
            "FPLMN": "",
        }
        cm.card_info = dict(cm._original_card_data)
        # Set up authenticated state so program_card passes pre-flight checks
        cm.authenticated = True
        cm._authenticated_adm1_hex = "3838383838383838"
        cm._safety_override_acknowledged = True  # skip retry-counter pySim call
        from managers.card_manager import CLIBackend
        cm.cli_backend = CLIBackend.PYSIM
        return cm

    def test_imsi_change_detected_in_program_nonempty_card(self):
        """When IMSI changes, _program_nonempty_card receives a non-empty changed dict."""
        cm = self._make_sja5_cm("999700000177500")

        card_data = {
            "ICCID": "8949440000001775004",
            "IMSI": "999880001000001",
            "ADM1": "3838383838383838",
        }

        captured = {}

        def _fake_program_nonempty(target, changed):
            captured["changed"] = dict(changed)
            return True, "ok"

        cm._program_nonempty_card = _fake_program_nonempty

        # original_data=None → CardManager uses _original_card_data
        ok, msg, _result = cm.program_card(card_data, original_data=None)

        assert "changed" in captured, "_program_nonempty_card was not called"
        assert "IMSI" in captured["changed"], (
            f"IMSI must appear in changed fields; got {captured['changed']}"
        )
        assert captured["changed"]["IMSI"] == "999880001000001"

    def test_no_change_when_original_data_equals_target(self):
        """When physical card already matches target, no fields change."""
        cm = self._make_sja5_cm("999880001000001")

        card_data = {
            "ICCID": "8949440000001775004",
            "IMSI": "999880001000001",
            "ADM1": "3838383838383838",
        }

        captured = {}

        def _fake_program_nonempty(target, changed):
            captured["changed"] = dict(changed)
            return True, "ok"

        cm._program_nonempty_card = _fake_program_nonempty
        cm.program_card(card_data, original_data=None)

        # Either not called (early-exit "no changes") or called with empty IMSI
        if "changed" in captured:
            assert "IMSI" not in captured["changed"], (
                "IMSI must not appear in changed fields when physical card matches target"
            )
