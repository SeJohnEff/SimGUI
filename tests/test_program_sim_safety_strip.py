"""Tests: safety strip in ProgramSIMPanel shows card_type, source, already_programmed.

These fields were previously visible only in Card Status. After this change they
are also shown in Program SIM so the Card Status tab is no longer the sole
location for safety-critical card info.

Note: isHidden() is used instead of isVisible() because the panel is not
attached to a visible window in tests — show()/hide() set the explicit hidden
flag, which isHidden() reflects correctly regardless of parent visibility.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

from state_manager import StateManager, CardInfo, CardState
from widgets.program_sim_panel import ProgramSIMPanel

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def sm():
    return StateManager()


@pytest.fixture
def panel(sm):
    return ProgramSIMPanel(
        card_manager=MagicMock(),
        state_manager=sm,
    )


# ---------------------------------------------------------------------------
# Strip widget existence
# ---------------------------------------------------------------------------

class TestSafetyStripExists:

    def test_card_type_label_exists(self, panel):
        assert hasattr(panel, "_card_type_lbl")

    def test_source_label_exists(self, panel):
        assert hasattr(panel, "_source_lbl")

    def test_already_programmed_banner_exists(self, panel):
        assert hasattr(panel, "_already_programmed_banner")

    def test_already_programmed_banner_hidden_by_default(self, panel):
        assert panel._already_programmed_banner.isHidden()


# ---------------------------------------------------------------------------
# card_info_changed drives the strip
# ---------------------------------------------------------------------------

class TestSafetyStripUpdatesOnCardInfoChanged:

    def test_card_type_shown(self, panel, sm):
        sm.update_card_info(iccid="89000000000000000001", card_type="SJA5")
        assert panel._card_type_lbl.text() == "SJA5"

    def test_gialersim_card_type_shown(self, panel, sm):
        sm.update_card_info(iccid="89000000000000000001", card_type="GIALERSIM")
        assert panel._card_type_lbl.text() == "GIALERSIM"

    def test_source_file_shown_as_basename(self, panel, sm):
        sm.update_card_info(
            iccid="89000000000000000001",
            source_file="/mnt/nas/simdata/batch001.csv",
        )
        assert panel._source_lbl.text() == "batch001.csv"

    def test_source_file_empty_shows_dash(self, panel, sm):
        sm.update_card_info(iccid="89000000000000000001", source_file="")
        assert panel._source_lbl.text() == "—"

    def test_already_programmed_banner_shown(self, panel, sm):
        sm.update_card_info(
            iccid="89000000000000000001",
            already_programmed=True,
        )
        assert not panel._already_programmed_banner.isHidden()

    def test_already_programmed_banner_hidden_when_false(self, panel, sm):
        sm.update_card_info(iccid="89000000000000000001", already_programmed=True)
        sm.update_card_info(already_programmed=False)
        assert panel._already_programmed_banner.isHidden()

    def test_card_type_unknown_shows_dash(self, panel, sm):
        sm.update_card_info(iccid="89000000000000000001", card_type="")
        assert panel._card_type_lbl.text() == "—"


# ---------------------------------------------------------------------------
# Strip resets on card removed (clear_card_info fires card_info_changed)
# ---------------------------------------------------------------------------

class TestSafetyStripClearsOnRemoval:

    def test_card_type_reset_on_remove(self, panel, sm):
        sm.update_card_info(iccid="89000000000000000001", card_type="SJA5")
        sm.clear_card_info()
        assert panel._card_type_lbl.text() == "—"

    def test_source_reset_on_remove(self, panel, sm):
        sm.update_card_info(
            iccid="89000000000000000001",
            source_file="/data/file.csv",
        )
        sm.clear_card_info()
        assert panel._source_lbl.text() == "—"

    def test_already_programmed_banner_hidden_on_remove(self, panel, sm):
        sm.update_card_info(iccid="89000000000000000001", already_programmed=True)
        assert not panel._already_programmed_banner.isHidden()
        sm.clear_card_info()
        assert panel._already_programmed_banner.isHidden()


# ---------------------------------------------------------------------------
# StateManager CardInfo carries card_type and already_programmed
# ---------------------------------------------------------------------------

class TestCardInfoFieldsPopulated:

    def test_card_type_field_settable(self, sm):
        sm.update_card_info(iccid="89000000000000000001", card_type="SJA5")
        assert sm.card_info.card_type == "SJA5"

    def test_already_programmed_field_settable(self, sm):
        sm.update_card_info(
            iccid="89000000000000000001",
            already_programmed=True,
        )
        assert sm.card_info.already_programmed is True

    def test_card_type_cleared_on_remove(self, sm):
        sm.update_card_info(iccid="89000000000000000001", card_type="SJA5")
        sm.clear_card_info()
        assert sm.card_info.card_type == ""

    def test_already_programmed_cleared_on_remove(self, sm):
        sm.update_card_info(iccid="89000000000000000001", already_programmed=True)
        sm.clear_card_info()
        assert sm.card_info.already_programmed is False
