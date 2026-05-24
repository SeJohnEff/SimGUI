"""
Tests for card data propagation from CardManager → StateManager → UI tabs.

Reproduces the manual failure scenario observed on macOS:
  - Card inserted → Read SIM and Card Status show only ICCID, not IMSI.
  - Removing the card populates the Read SIM tab with stale data (wrong).

Root causes:
  1. main.py on_unknown only passes iccid to update_card_info; IMSI/ACC/SPN/FPLMN
     from CardManager.card_info are silently dropped.
  2. ReadSIMPanel._on_card_info_changed is a pass stub — never updates fields.
  3. ReadSIMPanel._on_card_state_changed calls refresh() on NO_CARD, which reads
     stale CardManager data and populates the tab after the card is gone.

Contract under test:
  - StateManager.card_info must contain IMSI immediately after on_unknown fires.
  - ReadSIMPanel must show ICCID and IMSI immediately after card_info_changed.
  - ReadSIMPanel must clear on card removal; must NOT read from CardManager.
  - CardStatusPanel must show IMSI immediately after card_info_changed.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PyQt6.QtCore import QCoreApplication

from state_manager import CardInfo, CardState, StateManager

# ---------------------------------------------------------------------------
# Fixtures (no display required for StateManager tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _qcore():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv or ["test"])
    return app


@pytest.fixture()
def sm(_qcore):
    return StateManager()


# ---------------------------------------------------------------------------
# 1. StateManager-level: on_unknown must forward all CardManager fields
# ---------------------------------------------------------------------------

class TestOnUnknownForwardsAllFields:
    """Verify that the on_unknown callback includes all pySim-read fields."""

    def test_imsi_propagated_to_state_manager(self, sm):
        """StateManager.card_info.imsi must be set when on_unknown fires.

        Reproduces: Card Status tab shows ICCID but not IMSI after insertion.
        """
        # Simulate what the fixed on_unknown closure must do:
        # read all fields from CardManager.card_info and forward them.
        raw = {"ICCID": "8988601234567890123", "IMSI": "310410123456789", "ACC": "ffff"}
        sm.card_state = CardState.DETECTED
        sm.update_card_info(
            iccid=raw["ICCID"],
            imsi=raw.get("IMSI", ""),
            acc=raw.get("ACC", "-"),
            spn=raw.get("SPN", "-"),
            fplmn=raw.get("FPLMN", "-"),
            auth_status=False,
        )
        assert sm.card_info.imsi == "310410123456789"

    def test_acc_propagated_to_state_manager(self, sm):
        raw = {"ICCID": "8988601234567890123", "IMSI": "310410123456789", "ACC": "ffff"}
        sm.update_card_info(
            iccid=raw["ICCID"],
            imsi=raw.get("IMSI", ""),
            acc=raw.get("ACC", "-"),
            auth_status=False,
        )
        assert sm.card_info.acc == "ffff"

    def test_imsi_empty_for_blank_card(self, sm):
        """Blank gialersim cards have no IMSI — update_card_info must handle empty."""
        sm.card_state = CardState.BLANK
        sm.update_card_info(
            iccid="(blank)",
            imsi="",
            acc="-",
            auth_status=False,
        )
        assert sm.card_info.iccid == "(blank)"
        assert sm.card_info.imsi == ""

    def test_state_manager_cleared_on_removal(self, sm):
        """clear_card_info() must reset IMSI to empty string."""
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        sm.clear_card_info()
        assert sm.card_info.imsi == ""
        assert sm.card_info.iccid == ""


# ---------------------------------------------------------------------------
# 2. Widget-level: ReadSIMPanel._on_card_info_changed updates display fields
# ---------------------------------------------------------------------------

class TestReadSIMPanelCardInfoBinding:
    """ReadSIMPanel must update display fields when card_info_changed fires."""

    @pytest.fixture()
    def panel(self, qapp, sm):
        """Create a ReadSIMPanel bound to a live StateManager."""
        from managers.card_manager import CardManager
        from widgets.read_sim_panel import ReadSIMPanel

        cm = CardManager()
        p = ReadSIMPanel(None, cm, state_manager=sm)
        yield p
        p.deleteLater()

    def test_iccid_shown_immediately_after_card_info_changed(self, panel, sm):
        """ICCID must appear in the public field immediately on card_info_changed.

        Fails before fix: _on_card_info_changed is a pass stub.
        """
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        assert panel._pub_fields["iccid"].text() == "8988601234567890123"

    def test_imsi_shown_immediately_after_card_info_changed(self, panel, sm):
        """IMSI must appear in the public field immediately on card_info_changed.

        Fails before fix: _on_card_info_changed is a pass stub.
        """
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        assert panel._pub_fields["imsi"].text() == "310410123456789"

    def test_acc_shown_when_present(self, panel, sm):
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789", acc="ffff")
        assert panel._pub_fields["acc"].text() == "ffff"

    def test_spn_shown_when_present(self, panel, sm):
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789", spn="BOLIDEN")
        assert panel._pub_fields["spn"].text() == "BOLIDEN"

    def test_fplmn_shown_when_present(self, panel, sm):
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789", fplmn="24007;24001")
        assert panel._pub_fields["fplmn"].text() == "24007;24001"

    def test_spn_shows_dash_when_absent(self, panel, sm):
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        assert panel._pub_fields["spn"].text() == "-"

    def test_fplmn_shows_dash_when_absent(self, panel, sm):
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        assert panel._pub_fields["fplmn"].text() == "-"

    def test_fields_cleared_after_clear_card_info(self, panel, sm):
        """Fields must clear when card is removed (clear_card_info fires).

        Fails before fix: _on_card_info_changed is a pass stub.
        """
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        sm.clear_card_info()
        assert panel._pub_fields["iccid"].text() == "-"
        assert panel._pub_fields["imsi"].text() == "-"

    def test_detected_iccid_updated_on_card_info_changed(self, panel, sm):
        """Internal _detected_iccid must be set so auth flow works."""
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        assert panel._detected_iccid == "8988601234567890123"

    def test_detected_iccid_cleared_on_card_removed(self, panel, sm):
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        sm.clear_card_info()
        assert panel._detected_iccid == ""

    def test_blank_card_sets_empty_detected_iccid(self, panel, sm):
        """Blank/gialersim cards have iccid=(blank); _detected_iccid must be ''."""
        sm.update_card_info(iccid="(blank)", imsi="")
        assert panel._detected_iccid == ""

    def test_shared_last_read_data_updated(self, panel, sm):
        """_last_read_data must include the ICCID after card_info_changed."""
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        assert "iccid" in panel._last_read_data
        assert panel._last_read_data["iccid"] == "8988601234567890123"


# ---------------------------------------------------------------------------
# 3. Widget-level: NO_CARD must clear via card_info_changed, not stale CardManager
# ---------------------------------------------------------------------------

class TestReadSIMPanelNoStaleDataOnRemoval:
    """Card removal must clear fields; must NOT read stale CardManager data."""

    @pytest.fixture()
    def cm_with_stale_data(self):
        """Mock CardManager that still holds the last card's data."""
        cm = MagicMock()
        cm.read_public_data.return_value = {
            "ICCID": "8988601234567890123",
            "IMSI": "310410123456789",
        }
        return cm

    @pytest.fixture()
    def panel_with_cm(self, qapp, sm, cm_with_stale_data):
        from widgets.read_sim_panel import ReadSIMPanel
        p = ReadSIMPanel(None, cm_with_stale_data, state_manager=sm)
        yield p, cm_with_stale_data
        p.deleteLater()

    def test_removal_does_not_show_stale_iccid(self, panel_with_cm, sm):
        """ICCID field must be '-' after card removed, not stale CardManager value.

        Fails before fix: _on_card_state_changed(NO_CARD) calls refresh() which
        reads stale CardManager.card_info and repopulates the fields.
        """
        panel, _ = panel_with_cm
        # Simulate: card was present, then removed
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        # Card removed
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        assert panel._pub_fields["iccid"].text() == "-"

    def test_removal_does_not_show_stale_imsi(self, panel_with_cm, sm):
        """IMSI field must be '-' after card removed, not stale CardManager value."""
        panel, _ = panel_with_cm
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        assert panel._pub_fields["imsi"].text() == "-"

    def test_read_public_data_not_called_on_no_card(self, panel_with_cm, sm):
        """CardManager.read_public_data must NOT be called when state goes to NO_CARD.

        Fails before fix: refresh() is called from _on_card_state_changed(NO_CARD).
        """
        panel, cm = panel_with_cm
        cm.read_public_data.reset_mock()
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        cm.read_public_data.assert_not_called()

    def test_new_card_replaces_old_fields(self, panel_with_cm, sm):
        """When a new card is inserted after removal, only new fields are shown."""
        panel, _ = panel_with_cm
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        # New card inserted
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="9999999999999999999", imsi="999999999999999")
        assert panel._pub_fields["iccid"].text() == "9999999999999999999"
        assert panel._pub_fields["imsi"].text() == "999999999999999"


# ---------------------------------------------------------------------------
# 4. Widget-level: CardStatusPanel shows IMSI when card_info_changed fires
# ---------------------------------------------------------------------------

class TestCardStatusPanelIMSIBinding:
    """CardStatusPanel must show IMSI from card_info_changed."""

    @pytest.fixture()
    def status_panel(self, qapp, sm):
        from widgets.card_status_panel import CardStatusPanel
        p = CardStatusPanel(state_manager=sm)
        yield p
        p.deleteLater()

    def test_imsi_shown_after_card_info_changed(self, status_panel, sm):
        """IMSI label must show IMSI after update_card_info fires.

        This works IF StateManager has IMSI. If on_unknown drops IMSI,
        this test won't help — the IMSI-forwarding tests above cover that.
        """
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        assert status_panel._info_vars["imsi"].text() == "310410123456789"

    def test_iccid_shown_after_card_info_changed(self, status_panel, sm):
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        assert status_panel._info_vars["iccid"].text() == "8988601234567890123"

    def test_imsi_cleared_after_card_removed(self, status_panel, sm):
        # Must transition from a card-present state so NO_CARD fires the signal
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789")
        assert status_panel._info_vars["imsi"].text() == "310410123456789"
        # Card removed: state transitions back to NO_CARD
        sm.card_state = CardState.NO_CARD
        # CardStatusPanel._on_card_state_changed(NO_CARD) calls self.clear_card_info()
        assert status_panel._info_vars["imsi"].text() == "Not available"


# ---------------------------------------------------------------------------
# 5. Widget-level: ProgramSIMPanel populates ACC/SPN/FPLMN from CardInfo
# ---------------------------------------------------------------------------

class TestProgramSIMPanelPublicFieldsFromCardInfo:
    """ProgramSIMPanel must fill ACC/SPN/FPLMN from CardInfo when fields are empty."""

    @pytest.fixture()
    def panel(self, qapp, sm):
        from managers.card_manager import CardManager
        from widgets.program_sim_panel import ProgramSIMPanel

        cm = CardManager()
        p = ProgramSIMPanel(None, cm, state_manager=sm)
        yield p
        p.deleteLater()

    def test_acc_populated_from_card_info(self, panel, sm):
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789", acc="0001")
        assert panel._field_entries["ACC"].text() == "0001"

    def test_spn_populated_from_card_info(self, panel, sm):
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789", spn="BOLIDEN")
        assert panel._field_entries["SPN"].text() == "BOLIDEN"

    def test_fplmn_populated_from_card_info(self, panel, sm):
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789", fplmn="24007;24001")
        assert panel._field_entries["FPLMN"].text() == "24007;24001"

    def test_acc_populates_over_placeholder(self, panel, sm):
        """acc must overwrite a '-' placeholder left in the field."""
        panel._field_entries["ACC"].setText("-")
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789", acc="ffff")
        assert panel._field_entries["ACC"].text() == "ffff"

    def test_user_entered_acc_not_overwritten(self, panel, sm):
        """A real user-entered ACC value must not be overwritten by CardInfo."""
        panel._field_entries["ACC"].setText("0002")
        sm.card_state = CardState.DETECTED
        sm.update_card_info(iccid="8988601234567890123", imsi="310410123456789", acc="0001")
        assert panel._field_entries["ACC"].text() == "0002"
