#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for state_manager.py — Phase 0 of the PyQt6 migration.

Covers:
  - Every property setter emits its signal exactly once on change.
  - No signal emitted when value is unchanged (idempotency).
  - update_card_info partial updates.
  - clear_card_info resets all fields.
  - ShareStatus convenience properties.
  - SimulatorInfo partial updates.
  - Toast/error/card_programmed/index_updated convenience signals.
  - Enum correctness (CardState, AppMode).
  - CardInfo.to_dict() round-trip.
  - Thread safety of signal emission (basic verification).

Does NOT require a display server — uses QCoreApplication (no widgets).
"""

import sys
import threading

import pytest

# QCoreApplication is sufficient for signal/slot testing (no GUI needed)
from PyQt6.QtCore import QCoreApplication

from state_manager import (
    AppMode,
    CardInfo,
    CardState,
    ShareStatus,
    SimulatorInfo,
    StateManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Create a single QCoreApplication for the entire test session."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv or ["test"])
    return app


@pytest.fixture()
def sm(qapp):
    """Fresh StateManager for each test."""
    return StateManager()


class SignalSpy:
    """Lightweight spy that records signal emissions."""

    def __init__(self):
        self.calls: list[tuple] = []

    def slot(self, *args):
        self.calls.append(args)

    @property
    def count(self) -> int:
        return len(self.calls)

    @property
    def last(self):
        return self.calls[-1] if self.calls else None

    def reset(self):
        self.calls.clear()


# ---------------------------------------------------------------------------
# CardState property
# ---------------------------------------------------------------------------

class TestCardState:

    def test_initial_state(self, sm):
        assert sm.card_state is CardState.NO_CARD

    def test_set_emits_signal(self, sm):
        spy = SignalSpy()
        sm.card_state_changed.connect(spy.slot)
        sm.card_state = CardState.DETECTED
        assert spy.count == 1
        assert spy.last == (CardState.DETECTED,)

    def test_idempotent_no_signal(self, sm):
        """Setting to the same value should not emit."""
        sm.card_state = CardState.DETECTED
        spy = SignalSpy()
        sm.card_state_changed.connect(spy.slot)
        sm.card_state = CardState.DETECTED
        assert spy.count == 0

    def test_all_states(self, sm):
        spy = SignalSpy()
        sm.card_state_changed.connect(spy.slot)
        for state in CardState:
            sm.card_state = state
        # NO_CARD is the default — skipped; rest should fire
        assert spy.count == len(CardState) - 1

    def test_transition_sequence(self, sm):
        spy = SignalSpy()
        sm.card_state_changed.connect(spy.slot)
        sm.card_state = CardState.DETECTED
        sm.card_state = CardState.AUTHENTICATED
        sm.card_state = CardState.NO_CARD
        assert spy.count == 3
        assert [c[0] for c in spy.calls] == [
            CardState.DETECTED, CardState.AUTHENTICATED, CardState.NO_CARD]


# ---------------------------------------------------------------------------
# CardInfo
# ---------------------------------------------------------------------------

class TestCardInfo:

    def test_initial_card_info(self, sm):
        info = sm.card_info
        assert info.iccid == ""
        assert info.imsi == ""
        assert info.auth_status is False

    def test_update_card_info_emits(self, sm):
        spy = SignalSpy()
        sm.card_info_changed.connect(spy.slot)
        sm.update_card_info(iccid="89460000")
        assert spy.count == 1
        assert sm.card_info.iccid == "89460000"

    def test_update_card_info_partial(self, sm):
        sm.update_card_info(iccid="89460000", imsi="24001")
        spy = SignalSpy()
        sm.card_info_changed.connect(spy.slot)
        sm.update_card_info(imsi="24002")
        assert spy.count == 1
        assert sm.card_info.iccid == "89460000"  # unchanged
        assert sm.card_info.imsi == "24002"

    def test_update_card_info_no_change(self, sm):
        sm.update_card_info(iccid="89460000")
        spy = SignalSpy()
        sm.card_info_changed.connect(spy.slot)
        sm.update_card_info(iccid="89460000")
        assert spy.count == 0

    def test_update_card_info_bad_field(self, sm):
        with pytest.raises(AttributeError, match="no field 'bogus'"):
            sm.update_card_info(bogus="value")

    def test_clear_card_info(self, sm):
        sm.update_card_info(iccid="89460000", imsi="24001",
                            auth_status=True)
        spy = SignalSpy()
        sm.card_info_changed.connect(spy.slot)
        sm.clear_card_info()
        assert spy.count == 1
        assert sm.card_info.iccid == ""
        assert sm.card_info.imsi == ""
        assert sm.card_info.auth_status is False

    def test_to_dict(self):
        info = CardInfo(iccid="89460000", imsi="24001", acc="0004")
        d = info.to_dict()
        assert d["ICCID"] == "89460000"
        assert d["IMSI"] == "24001"
        assert d["ACC"] == "0004"

    def test_clear_resets_all_fields(self):
        info = CardInfo(
            iccid="89460000", imsi="24001", acc="0004",
            spn="Test", fplmn="DEADBEEF", card_type="sysmoISIM",
            source_file="/data/cards.csv", auth_status=True,
            already_programmed=True)
        info.clear()
        assert info.iccid == ""
        assert info.imsi == ""
        assert info.acc == "-"
        assert info.spn == "-"
        assert info.fplmn == "-"
        assert info.card_type == ""
        assert info.source_file == ""
        assert info.auth_status is False
        assert info.already_programmed is False

    def test_update_multiple_fields_single_signal(self, sm):
        spy = SignalSpy()
        sm.card_info_changed.connect(spy.slot)
        sm.update_card_info(
            iccid="89460000", imsi="24001", acc="0004",
            spn="Operator", auth_status=True)
        assert spy.count == 1
        assert sm.card_info.iccid == "89460000"
        assert sm.card_info.imsi == "24001"
        assert sm.card_info.acc == "0004"
        assert sm.card_info.spn == "Operator"
        assert sm.card_info.auth_status is True


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------

class TestMode:

    def test_initial_mode(self, sm):
        assert sm.mode is AppMode.HARDWARE

    def test_set_mode_emits(self, sm):
        spy = SignalSpy()
        sm.mode_changed.connect(spy.slot)
        sm.mode = AppMode.SIMULATOR
        assert spy.count == 1
        assert spy.last == (AppMode.SIMULATOR,)
        assert sm.mode is AppMode.SIMULATOR

    def test_idempotent(self, sm):
        spy = SignalSpy()
        sm.mode_changed.connect(spy.slot)
        sm.mode = AppMode.HARDWARE  # same as default
        assert spy.count == 0

    def test_toggle(self, sm):
        spy = SignalSpy()
        sm.mode_changed.connect(spy.slot)
        sm.mode = AppMode.SIMULATOR
        sm.mode = AppMode.HARDWARE
        sm.mode = AppMode.SIMULATOR
        assert spy.count == 3

    def test_enum_values(self):
        assert AppMode.HARDWARE.value == "hardware"
        assert AppMode.SIMULATOR.value == "simulator"


# ---------------------------------------------------------------------------
# Status text
# ---------------------------------------------------------------------------

class TestStatusText:

    def test_initial(self, sm):
        assert sm.status_text == "Ready"

    def test_set_emits(self, sm):
        spy = SignalSpy()
        sm.status_changed.connect(spy.slot)
        sm.status_text = "Card detected"
        assert spy.count == 1
        assert spy.last == ("Card detected",)

    def test_idempotent(self, sm):
        sm.status_text = "Card detected"
        spy = SignalSpy()
        sm.status_changed.connect(spy.slot)
        sm.status_text = "Card detected"
        assert spy.count == 0

    def test_empty_string(self, sm):
        sm.status_text = "something"
        spy = SignalSpy()
        sm.status_changed.connect(spy.slot)
        sm.status_text = ""
        assert spy.count == 1
        assert spy.last == ("",)


# ---------------------------------------------------------------------------
# Share status
# ---------------------------------------------------------------------------

class TestShareStatus:

    def test_initial(self, sm):
        assert sm.share_status.connected is False
        assert sm.share_status.labels == []

    def test_update_connected(self, sm):
        spy = SignalSpy()
        sm.share_status_changed.connect(spy.slot)
        sm.update_share_status([("NAS1", "/mnt/nas1")])
        assert spy.count == 1
        assert sm.share_status.connected is True
        assert sm.share_status.labels == ["NAS1"]

    def test_update_disconnected(self, sm):
        sm.update_share_status([("NAS1", "/mnt/nas1")])
        spy = SignalSpy()
        sm.share_status_changed.connect(spy.slot)
        sm.update_share_status([])
        assert spy.count == 1
        assert sm.share_status.connected is False

    def test_update_none(self, sm):
        spy = SignalSpy()
        sm.share_status_changed.connect(spy.slot)
        sm.update_share_status(None)
        assert spy.count == 0  # was already disconnected

    def test_idempotent(self, sm):
        sm.update_share_status([("NAS1", "/mnt/nas1")])
        spy = SignalSpy()
        sm.share_status_changed.connect(spy.slot)
        sm.update_share_status([("NAS1", "/mnt/nas1")])
        assert spy.count == 0

    def test_display_text(self):
        s = ShareStatus(connected=True, labels=["NAS1", "NAS2"],
                        mount_paths=[("NAS1", "/mnt/1"), ("NAS2", "/mnt/2")])
        assert "NAS1" in s.display_text
        assert "NAS2" in s.display_text

    def test_display_text_empty(self):
        s = ShareStatus()
        assert s.display_text == ""

    def test_tooltip_text(self):
        s = ShareStatus(connected=True, labels=["NAS1"],
                        mount_paths=[("NAS1", "/mnt/nas1")])
        assert "NAS1: /mnt/nas1" in s.tooltip_text

    def test_tooltip_text_disconnected(self):
        s = ShareStatus()
        assert "No network share" in s.tooltip_text

    def test_multiple_mounts(self, sm):
        spy = SignalSpy()
        sm.share_status_changed.connect(spy.slot)
        sm.update_share_status([
            ("NAS1", "/mnt/nas1"),
            ("NAS2", "/mnt/nas2"),
        ])
        assert spy.count == 1
        assert sm.share_status.labels == ["NAS1", "NAS2"]
        assert len(sm.share_status.mount_paths) == 2


# ---------------------------------------------------------------------------
# CSV path
# ---------------------------------------------------------------------------

class TestCSVPath:

    def test_initial(self, sm):
        assert sm.csv_path == ""

    def test_set_emits(self, sm):
        spy = SignalSpy()
        sm.csv_path_changed.connect(spy.slot)
        sm.csv_path = "/data/cards.csv"
        assert spy.count == 1
        assert spy.last == ("/data/cards.csv",)

    def test_idempotent(self, sm):
        sm.csv_path = "/data/cards.csv"
        spy = SignalSpy()
        sm.csv_path_changed.connect(spy.slot)
        sm.csv_path = "/data/cards.csv"
        assert spy.count == 0


# ---------------------------------------------------------------------------
# Simulator info
# ---------------------------------------------------------------------------

class TestSimulatorInfo:

    def test_initial(self, sm):
        info = sm.simulator_info
        assert info.current_index == 0
        assert info.total_cards == 0
        assert info.active is False

    def test_update_emits(self, sm):
        spy = SignalSpy()
        sm.simulator_info_changed.connect(spy.slot)
        sm.update_simulator_info(current_index=3, total_cards=20, active=True)
        assert spy.count == 1
        assert sm.simulator_info.current_index == 3
        assert sm.simulator_info.total_cards == 20
        assert sm.simulator_info.active is True

    def test_partial_update(self, sm):
        sm.update_simulator_info(current_index=3, total_cards=20)
        spy = SignalSpy()
        sm.simulator_info_changed.connect(spy.slot)
        sm.update_simulator_info(current_index=4)
        assert spy.count == 1
        assert sm.simulator_info.current_index == 4
        assert sm.simulator_info.total_cards == 20  # unchanged

    def test_idempotent(self, sm):
        sm.update_simulator_info(current_index=3)
        spy = SignalSpy()
        sm.simulator_info_changed.connect(spy.slot)
        sm.update_simulator_info(current_index=3)
        assert spy.count == 0


# ---------------------------------------------------------------------------
# Batch running
# ---------------------------------------------------------------------------

class TestBatchRunning:

    def test_initial(self, sm):
        assert sm.batch_running is False

    def test_set_emits(self, sm):
        spy = SignalSpy()
        sm.batch_running_changed.connect(spy.slot)
        sm.batch_running = True
        assert spy.count == 1
        assert spy.last == (True,)

    def test_idempotent(self, sm):
        spy = SignalSpy()
        sm.batch_running_changed.connect(spy.slot)
        sm.batch_running = False  # same as default
        assert spy.count == 0


# ---------------------------------------------------------------------------
# Convenience signals
# ---------------------------------------------------------------------------

class TestConvenienceSignals:

    def test_request_toast(self, sm):
        spy = SignalSpy()
        sm.toast_requested.connect(spy.slot)
        sm.request_toast("Hello", "success", 3000)
        assert spy.count == 1
        assert spy.last == ("Hello", "success", 3000)

    def test_report_error(self, sm):
        spy = SignalSpy()
        sm.error_occurred.connect(spy.slot)
        sm.report_error("Something went wrong")
        assert spy.count == 1
        assert spy.last == ("Something went wrong",)

    def test_notify_card_programmed(self, sm):
        spy = SignalSpy()
        sm.card_programmed.connect(spy.slot)
        data = {"ICCID": "89460000", "IMSI": "24001"}
        sm.notify_card_programmed(data)
        assert spy.count == 1
        assert spy.last == (data,)

    def test_notify_index_updated(self, sm):
        spy = SignalSpy()
        sm.iccid_index_updated.connect(spy.slot)
        sm.notify_index_updated()
        assert spy.count == 1


# ---------------------------------------------------------------------------
# CardState enum
# ---------------------------------------------------------------------------

class TestCardStateEnum:

    def test_all_members(self):
        names = {s.name for s in CardState}
        assert names == {"NO_CARD", "DETECTED", "AUTHENTICATED", "ERROR", "BLANK"}

    def test_is_enum(self):
        assert CardState.NO_CARD is not CardState.DETECTED


# ---------------------------------------------------------------------------
# Thread safety (basic)
# ---------------------------------------------------------------------------

class TestThreadSafety:
    """Verify that signals can be emitted from a background thread
    without crashing.  Full cross-thread delivery requires an event
    loop, but at minimum the emission must not segfault.
    """

    def test_emit_from_thread(self, sm):
        spy = SignalSpy()
        sm.status_changed.connect(spy.slot)
        errors = []

        def worker():
            try:
                sm.status_text = "from thread"
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=2.0)
        assert not errors, f"Thread emission raised: {errors}"

    def test_card_state_from_thread(self, sm):
        errors = []

        def worker():
            try:
                sm.card_state = CardState.DETECTED
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=2.0)
        assert not errors

    def test_update_card_info_from_thread(self, sm):
        errors = []

        def worker():
            try:
                sm.update_card_info(iccid="89460000", imsi="24001")
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=2.0)
        assert not errors


# ---------------------------------------------------------------------------
# Multiple subscribers
# ---------------------------------------------------------------------------

class TestMultipleSubscribers:
    """Verify that multiple slots connected to the same signal all fire."""

    def test_two_subscribers(self, sm):
        spy1 = SignalSpy()
        spy2 = SignalSpy()
        sm.status_changed.connect(spy1.slot)
        sm.status_changed.connect(spy2.slot)
        sm.status_text = "both see this"
        assert spy1.count == 1
        assert spy2.count == 1

    def test_disconnect(self, sm):
        spy = SignalSpy()
        sm.status_changed.connect(spy.slot)
        sm.status_text = "first"
        sm.status_changed.disconnect(spy.slot)
        sm.status_text = "second"
        assert spy.count == 1  # only "first"


# ---------------------------------------------------------------------------
# Integration: typical workflow sequence
# ---------------------------------------------------------------------------

class TestWorkflowSequence:
    """Simulate a typical card insertion → authentication → programming
    sequence and verify the signal chain.
    """

    def test_full_card_lifecycle(self, sm):
        state_spy = SignalSpy()
        info_spy = SignalSpy()
        status_spy = SignalSpy()
        sm.card_state_changed.connect(state_spy.slot)
        sm.card_info_changed.connect(info_spy.slot)
        sm.status_changed.connect(status_spy.slot)

        # 1. Card inserted, detected by watcher
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8946000001", imsi="240010001")
        sm.status_text = "Card detected: 8946000001"

        # 2. User authenticates
        sm.card_state = CardState.AUTHENTICATED
        sm.update_card_info(auth_status=True)
        sm.status_text = "Authenticated"

        # 3. Card programmed
        sm.status_text = "Programming..."
        data = {"ICCID": "8946000001", "IMSI": "240010001"}
        sm.notify_card_programmed(data)
        sm.status_text = "Done"

        # 4. Card removed
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        sm.status_text = "Card removed"

        assert state_spy.count == 3  # DETECTED → AUTHENTICATED → NO_CARD
        assert info_spy.count == 3   # insert, auth, clear
        assert status_spy.count == 5  # detected, auth, programming, done, removed

    def test_share_connect_then_card(self, sm):
        """Share connected before card insertion."""
        share_spy = SignalSpy()
        sm.share_status_changed.connect(share_spy.slot)

        sm.update_share_status([("Fiskarheden", "/mnt/nas/fiskarheden")])
        assert share_spy.count == 1
        assert sm.share_status.connected is True

        # Card inserted while share is active
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="89460000", source_file="/mnt/nas/fiskarheden/cards.csv")
        assert sm.card_info.source_file == "/mnt/nas/fiskarheden/cards.csv"
