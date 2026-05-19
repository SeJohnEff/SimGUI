"""Tests for network-share autofill wiring in Program SIM and Batch tabs.

Uses AST inspection + unit-level method binding — no display required.
"""

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_SRC = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AST / structural wiring checks
# ---------------------------------------------------------------------------

class TestStructuralWiring:
    def test_on_detected_calls_program_panel_on_card_detected(self):
        """_wire_card_watcher on_detected must forward to program panel."""
        assert "_program_panel.on_card_detected(iccid, card_data, file_path)" in MAIN_SRC

    def test_on_unknown_calls_program_panel_on_card_detected(self):
        """_wire_card_watcher on_unknown must forward to program panel."""
        assert "_program_panel.on_card_detected(iccid, None, None)" in MAIN_SRC

    def test_iccid_index_updated_signal_connected(self):
        """iccid_index_updated signal must be connected to _on_index_updated."""
        assert "iccid_index_updated.connect(self._on_index_updated)" in MAIN_SRC

    def test_on_index_updated_exists(self):
        """_on_index_updated method must exist in main.py."""
        assert "def _on_index_updated" in MAIN_SRC

    def test_rescan_called_after_network_storage_dialog(self):
        """_rescan_shares_background must be called after dialog closes."""
        assert "_rescan_shares_background()" in MAIN_SRC

    def test_rescan_uses_scan_shares_worker(self):
        """_rescan_shares_background must use _ScanSharesWorker."""
        assert "_ScanSharesWorker" in MAIN_SRC

    def test_startup_worker_passes_standards_mgr(self):
        """BackgroundStartupWorker must receive standards_mgr."""
        assert "BackgroundStartupWorker(" in MAIN_SRC
        assert "self._standards_mgr" in MAIN_SRC

    def test_batch_panel_refresh_standards_on_index_update(self):
        """refresh_standards must be called when index is updated."""
        assert "_batch_panel.refresh_standards()" in MAIN_SRC

    def test_on_scan_directory_calls_scan_directory(self):
        """File > Scan Directory must actually scan the iccid_index."""
        assert "_iccid_index.scan_directory(path)" in MAIN_SRC

    def test_on_open_csv_loads_into_program_panel(self):
        """File > Open CSV must load the file into program_panel."""
        assert "_program_panel.load_csv_file(path)" in MAIN_SRC


# ---------------------------------------------------------------------------
# Unit tests for _on_index_updated
# ---------------------------------------------------------------------------

class TestOnIndexUpdated:
    """Test that _on_index_updated autofills Program SIM if card is in reader."""

    def _make_stub(self):
        import main as main_mod
        stub = MagicMock()
        stub._on_index_updated = types.MethodType(
            main_mod.SimGUIApp._on_index_updated, stub)
        return stub

    def test_no_autofill_when_no_card(self):
        """No lookup when card_state is NO_CARD."""
        from state_manager import CardState
        stub = self._make_stub()
        stub.state_manager.card_state = CardState.NO_CARD

        stub._on_index_updated()

        stub._iccid_index.load_card.assert_not_called()
        stub._program_panel.on_card_detected.assert_not_called()

    def test_autofill_when_card_detected_and_in_index(self):
        """Card in reader + index hit → calls on_card_detected with data."""
        from state_manager import CardState
        card_data = {"ICCID": "8946001234567890123", "IMSI": "24001012345",
                     "Ki": "A" * 32, "OPc": "B" * 32}
        entry = MagicMock()
        entry.file_path = "/mnt/share/batch.csv"

        stub = self._make_stub()
        stub.state_manager.card_state = CardState.DETECTED
        stub.state_manager.card_info.iccid = "8946001234567890123"
        stub._iccid_index.load_card.return_value = card_data
        stub._iccid_index.lookup.return_value = entry

        stub._on_index_updated()

        stub._iccid_index.load_card.assert_called_once_with("8946001234567890123")
        stub._program_panel.on_card_detected.assert_called_once_with(
            "8946001234567890123", card_data, "/mnt/share/batch.csv")

    def test_no_autofill_when_iccid_not_in_index(self):
        """Card in reader but ICCID not in index → no autofill."""
        from state_manager import CardState
        stub = self._make_stub()
        stub.state_manager.card_state = CardState.DETECTED
        stub.state_manager.card_info.iccid = "9999000000000000000"
        stub._iccid_index.load_card.return_value = None

        stub._on_index_updated()

        stub._program_panel.on_card_detected.assert_not_called()

    def test_no_autofill_for_blank_card(self):
        """Blank card (iccid == '(blank)') → no index lookup."""
        from state_manager import CardState
        stub = self._make_stub()
        stub.state_manager.card_state = CardState.BLANK
        stub.state_manager.card_info.iccid = "(blank)"

        stub._on_index_updated()

        stub._iccid_index.load_card.assert_not_called()


# ---------------------------------------------------------------------------
# Unit tests for ProgramSIMPanel.on_card_detected field population
# ---------------------------------------------------------------------------

class TestProgramSIMPanelOnCardDetected:
    """Test that on_card_detected populates fields from card_data."""

    def _make_panel(self):
        """Bind on_card_detected to a stub panel for unit testing."""
        from widgets.program_sim_panel import ProgramSIMPanel, _FORM_FIELDS
        import types

        stub = MagicMock()
        stub._field_entries = {
            key: MagicMock() for key, _, _ in _FORM_FIELDS}
        stub._detected_non_empty = False
        stub._step = 0
        stub._set_action_status = MagicMock()
        stub._fields_have_data = MagicMock(return_value=False)
        stub._original_form_data = {}
        stub._update_program_btn_state = MagicMock()

        stub.on_card_detected = types.MethodType(
            ProgramSIMPanel.on_card_detected, stub)
        return stub

    def test_fields_populated_from_card_data(self):
        """All card_data fields are set in the form entries."""
        stub = self._make_panel()
        card_data = {
            "ICCID": "8946001234567890123",
            "IMSI": "24001012345",
            "Ki": "A" * 32,
            "OPc": "B" * 32,
            "ADM1": "88888888",
            "ACC": "0001",
            "SPN": "BOLIDEN",
            "FPLMN": "24007",
        }

        stub.on_card_detected("8946001234567890123", card_data, "/mnt/batch.csv")

        stub._field_entries["ICCID"].setText.assert_called_with("8946001234567890123")
        stub._field_entries["IMSI"].setText.assert_called_with("24001012345")
        stub._field_entries["Ki"].setText.assert_called_with("A" * 32)
        stub._field_entries["ADM1"].setText.assert_called_with("88888888")

    def test_status_shows_source_file(self):
        """Status includes the source filename when data is loaded."""
        stub = self._make_panel()
        card_data = {"ICCID": "8946001234567890123", "IMSI": "24001"}

        stub.on_card_detected("8946001234567890123", card_data, "/mnt/share/batch.csv")

        status_text = stub._set_action_status.call_args[0][0]
        assert "batch.csv" in status_text

    def test_not_in_index_shows_warning(self):
        """card_data=None shows 'not in index' warning status."""
        stub = self._make_panel()

        stub.on_card_detected("8946001234567890123", None, None)

        call_args = stub._set_action_status.call_args
        assert call_args[0][1] == "warning"

    def test_blank_card_no_data_shows_manual_entry_prompt(self):
        """Empty ICCID + no card_data shows blank-card prompt."""
        stub = self._make_panel()

        stub.on_card_detected("", None, None)

        call_args = stub._set_action_status.call_args
        assert call_args[0][1] == "warning"


# ---------------------------------------------------------------------------
# Integration: IccidIndex.load_card returns dict usable by on_card_detected
# ---------------------------------------------------------------------------

class TestIccidIndexLoadCard:
    """Verify that load_card returns the expected structure."""

    def test_load_card_from_csv(self, tmp_path):
        """load_card on a CSV file returns a dict with ICCID and IMSI."""
        import csv
        from managers.iccid_index import IccidIndex

        csv_file = tmp_path / "batch.csv"
        with open(csv_file, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["ICCID", "IMSI", "Ki", "OPc", "ADM1"])
            writer.writeheader()
            writer.writerow({
                "ICCID": "8946001234567890123",
                "IMSI": "24001012345678",
                "Ki": "A" * 32,
                "OPc": "B" * 32,
                "ADM1": "88888888",
            })

        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))
        card = idx.load_card("8946001234567890123")

        assert card is not None
        assert card["ICCID"] == "8946001234567890123"
        assert card["IMSI"] == "24001012345678"
        assert card["ADM1"] == "88888888"
