"""
Tests for Program SIM panel binding to shared CardInfo.

Requirement: when a card is read, Program SIM must populate the five public
fields (ICCID, IMSI, ACC, SPN, FPLMN) from StateManager.card_info_changed.
Protected fields (Ki, OPc, ADM1, PIN*, KIC/KID/KIK) must NOT be set from
public read data.

Safe behavior for user edits: CardInfo only fills fields that are currently
empty. Pre-existing content (CSV data or manual typing) is left alone.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from managers.card_manager import CardManager
from state_manager import CardInfo, CardState, StateManager
from widgets.program_sim_panel import ProgramSIMPanel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sm(qapp):
    return StateManager()


@pytest.fixture()
def panel(qapp, sm):
    cm = CardManager()
    p = ProgramSIMPanel(None, cm, state_manager=sm)
    yield p
    p.deleteLater()


def _set_card(sm, iccid="8988601234567890123", imsi="310410123456789",
              acc="ffff", spn="TestNet", fplmn="242010"):
    """Helper: transition to DETECTED with full public card data."""
    sm.card_state = CardState.DETECTED
    sm.update_card_info(
        iccid=iccid, imsi=imsi, acc=acc, spn=spn, fplmn=fplmn, auth_status=False)


# ---------------------------------------------------------------------------
# 1. Public fields populate on card_info_changed
# ---------------------------------------------------------------------------

class TestPublicFieldsPopulateFromCardInfo:
    """Program SIM must fill ICCID/IMSI/ACC/SPN/FPLMN from shared CardInfo."""

    def test_iccid_populated(self, panel, sm):
        _set_card(sm)
        assert panel._field_entries["ICCID"].text() == "8988601234567890123"

    def test_imsi_populated(self, panel, sm):
        _set_card(sm)
        assert panel._field_entries["IMSI"].text() == "310410123456789"

    def test_acc_populated(self, panel, sm):
        _set_card(sm)
        assert panel._field_entries["ACC"].text() == "ffff"

    def test_spn_populated(self, panel, sm):
        _set_card(sm)
        assert panel._field_entries["SPN"].text() == "-- not yet implemented --"

    def test_fplmn_populated(self, panel, sm):
        _set_card(sm)
        assert panel._field_entries["FPLMN"].text() == "242010"

    def test_all_five_fields_at_once(self, panel, sm):
        _set_card(sm, iccid="1111111111111111111", imsi="901700000000001",
                  acc="0001", spn="MySPN", fplmn="24201")
        assert panel._field_entries["ICCID"].text() == "1111111111111111111"
        assert panel._field_entries["IMSI"].text() == "901700000000001"
        assert panel._field_entries["ACC"].text() == "0001"
        assert panel._field_entries["SPN"].text() == "-- not yet implemented --"
        assert panel._field_entries["FPLMN"].text() == "24201"


# ---------------------------------------------------------------------------
# 2. Protected fields must NOT be populated from public read data
# ---------------------------------------------------------------------------

class TestProtectedFieldsNotPopulated:
    """Ki, OPc, ADM1 must remain empty after a public card read."""

    def test_ki_not_set(self, panel, sm):
        _set_card(sm)
        assert panel._field_entries["Ki"].text() == ""

    def test_opc_not_set(self, panel, sm):
        _set_card(sm)
        assert panel._field_entries["OPc"].text() == ""

    def test_adm1_not_set(self, panel, sm):
        _set_card(sm)
        assert panel._field_entries["ADM1"].text() == ""


# ---------------------------------------------------------------------------
# 3. Card removal clears public read fields
# ---------------------------------------------------------------------------

class TestRemovalClearsFields:
    """Fields must be blank after card removal."""

    def test_iccid_cleared_after_removal(self, panel, sm):
        _set_card(sm)
        assert panel._field_entries["ICCID"].text() != ""
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        assert panel._field_entries["ICCID"].text() == ""

    def test_imsi_cleared_after_removal(self, panel, sm):
        _set_card(sm)
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        assert panel._field_entries["IMSI"].text() == ""

    def test_acc_cleared_after_removal(self, panel, sm):
        _set_card(sm)
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        assert panel._field_entries["ACC"].text() == ""

    def test_spn_cleared_after_removal(self, panel, sm):
        _set_card(sm)
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        assert panel._field_entries["SPN"].text() == ""

    def test_fplmn_cleared_after_removal(self, panel, sm):
        _set_card(sm)
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        assert panel._field_entries["FPLMN"].text() == ""

    def test_second_card_shows_new_data(self, panel, sm):
        """After removal and new insertion, new card's data replaces the old."""
        _set_card(sm, iccid="1111111111111111111", imsi="111111111111111")
        sm.card_state = CardState.NO_CARD
        sm.clear_card_info()
        _set_card(sm, iccid="2222222222222222222", imsi="222222222222222")
        assert panel._field_entries["ICCID"].text() == "2222222222222222222"
        assert panel._field_entries["IMSI"].text() == "222222222222222"


# ---------------------------------------------------------------------------
# 4. User edits are not overwritten by CardInfo
# ---------------------------------------------------------------------------

class TestUserEditsPreserved:
    """CardInfo only fills empty fields — manual edits must survive."""

    def test_nonempty_imsi_not_overwritten(self, panel, sm):
        """If IMSI already has a value, card_info_changed must not overwrite it."""
        panel._field_entries["IMSI"].setText("999999999999999")
        _set_card(sm, imsi="310410123456789")
        # IMSI was non-empty before the signal — must keep user value
        assert panel._field_entries["IMSI"].text() == "999999999999999"

    def test_nonempty_acc_not_overwritten(self, panel, sm):
        panel._field_entries["ACC"].setText("0001")
        _set_card(sm, acc="ffff")
        assert panel._field_entries["ACC"].text() == "0001"

    def test_empty_fields_still_filled_alongside_nonempty(self, panel, sm):
        """Empty fields are filled even when some fields are pre-populated."""
        panel._field_entries["IMSI"].setText("existing_imsi")
        _set_card(sm, iccid="8988601234567890123", imsi="new_imsi", acc="ffff")
        # IMSI was set → unchanged
        assert panel._field_entries["IMSI"].text() == "existing_imsi"
        # ICCID was empty → filled from CardInfo
        assert panel._field_entries["ICCID"].text() == "8988601234567890123"
        # ACC was empty → filled from CardInfo
        assert panel._field_entries["ACC"].text() == "ffff"

    def test_blank_card_sentinel_not_written_to_iccid(self, panel, sm):
        """Blank gialersim cards have iccid='(blank)' — must not appear in field."""
        sm.card_state = CardState.BLANK
        sm.update_card_info(iccid="(blank)", imsi="", acc="-", auth_status=False)
        assert panel._field_entries["ICCID"].text() == ""

    def test_card_info_dash_sentinel_not_written_to_acc(self, panel, sm):
        """CardInfo default '-' for ACC must not be written to the ACC field."""
        sm.update_card_info(iccid="8988601234567890123", acc="-")
        assert panel._field_entries["ACC"].text() == ""

    def test_card_info_dash_sentinel_not_written_to_spn(self, panel, sm):
        sm.update_card_info(iccid="8988601234567890123", spn="-")
        assert panel._field_entries["SPN"].text() == ""

    def test_card_info_dash_sentinel_not_written_to_fplmn(self, panel, sm):
        sm.update_card_info(iccid="8988601234567890123", fplmn="-")
        assert panel._field_entries["FPLMN"].text() == ""


# ---------------------------------------------------------------------------
# 5. CSV / on_card_detected overwrites CardInfo values (CSV is authoritative)
# ---------------------------------------------------------------------------

class TestCSVDataOverridesCardInfo:
    """CSV-loaded data from on_card_detected takes precedence over CardInfo."""

    def test_csv_imsi_overwrites_card_info_imsi(self, panel, sm):
        """on_card_detected with card_data always wins over CardInfo values."""
        _set_card(sm, imsi="read_imsi")
        # CardInfo set imsi = "read_imsi"; now on_card_detected arrives with CSV data
        panel.on_card_detected(
            "8988601234567890123",
            {"ICCID": "8988601234567890123", "IMSI": "csv_imsi", "ADM1": "12345678"},
            "/data/test.csv"
        )
        assert panel._field_entries["IMSI"].text() == "csv_imsi"

    def test_csv_data_fills_protected_fields_card_info_cannot(self, panel, sm):
        """CSV provides Ki/OPc/ADM1 which CardInfo cannot."""
        _set_card(sm)
        panel.on_card_detected(
            "8988601234567890123",
            {"ICCID": "8988601234567890123", "IMSI": "310410123456789",
             "Ki": "AA" * 16, "OPc": "BB" * 16, "ADM1": "12345678"},
            "/data/test.csv"
        )
        assert panel._field_entries["Ki"].text() == "AA" * 16
        assert panel._field_entries["OPc"].text() == "BB" * 16
        assert panel._field_entries["ADM1"].text() == "12345678"


# ---------------------------------------------------------------------------
# 6. on_card_detected with partial CSV must not clear CardInfo public fields
# ---------------------------------------------------------------------------

class TestCSVDoesNotClearCardInfoPublicFields:
    """CSV absent fields must preserve CardInfo (pySim-read) values in the form.

    Typical Fiskarheden CSV has ICCID/IMSI/Ki/OPc/ADM1 but NOT ACC/SPN/FPLMN.
    pySim-read populates those via CardInfo.  on_card_detected must not clear them.
    """

    _CSV_PARTIAL = {
        "ICCID": "8988601234567890123",
        "IMSI": "310410123456789",
        "Ki": "AA" * 16,
        "OPc": "BB" * 16,
        "ADM1": "12345678",
    }

    def test_acc_from_card_info_preserved_after_csv_load(self, panel, sm):
        _set_card(sm, acc="ffff")
        panel.on_card_detected("8988601234567890123", self._CSV_PARTIAL, "/data/test.csv")
        assert panel._field_entries["ACC"].text() == "ffff"

    def test_spn_from_card_info_preserved_after_csv_load(self, panel, sm):
        _set_card(sm, spn="TestNet")
        panel.on_card_detected("8988601234567890123", self._CSV_PARTIAL, "/data/test.csv")
        assert panel._field_entries["SPN"].text() == "-- not yet implemented --"

    def test_fplmn_from_card_info_preserved_after_csv_load(self, panel, sm):
        _set_card(sm, fplmn="242010")
        panel.on_card_detected("8988601234567890123", self._CSV_PARTIAL, "/data/test.csv")
        assert panel._field_entries["FPLMN"].text() == "242010"

    def test_csv_imsi_still_wins_over_card_info_imsi(self, panel, sm):
        """CSV IMSI takes priority when CSV has a value."""
        _set_card(sm, imsi="read_imsi")
        panel.on_card_detected("8988601234567890123", self._CSV_PARTIAL, "/data/test.csv")
        assert panel._field_entries["IMSI"].text() == "310410123456789"

    def test_protected_fields_cleared_by_csv_when_absent(self, panel, sm):
        """Ki/OPc/ADM1 absent from CSV should be cleared (they are NOT pySim-read fields)."""
        _set_card(sm)
        panel.on_card_detected(
            "8988601234567890123",
            {"ICCID": "8988601234567890123", "IMSI": "310410123456789"},
            "/data/test.csv"
        )
        assert panel._field_entries["Ki"].text() == ""
        assert panel._field_entries["OPc"].text() == ""
        assert panel._field_entries["ADM1"].text() == ""

    def test_all_public_fields_preserved_when_csv_has_none(self, panel, sm):
        """CSV with only protected fields keeps all five public CardInfo values."""
        _set_card(sm, iccid="8988601234567890123", imsi="310410123456789",
                  acc="ffff", spn="TestNet", fplmn="242010")
        panel.on_card_detected(
            "8988601234567890123",
            {"Ki": "AA" * 16, "OPc": "BB" * 16, "ADM1": "12345678"},
            "/data/test.csv"
        )
        assert panel._field_entries["ICCID"].text() == "8988601234567890123"
        assert panel._field_entries["IMSI"].text() == "310410123456789"
        assert panel._field_entries["ACC"].text() == "ffff"
        assert panel._field_entries["SPN"].text() == "-- not yet implemented --"
        assert panel._field_entries["FPLMN"].text() == "242010"
