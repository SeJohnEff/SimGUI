"""
Targeted tests for SPN placeholder policy.

SPN programming is not yet implemented.  Any SPN present in card data,
CSV rows, or CardInfo must be displayed as SPN_UNSUPPORTED_PLACEHOLDER in
the Program SIM panel and must never reach CardManager.program_card().
CardManager must also defensively drop SPN before building pySim-prog args.
"""
import types
import unittest
from unittest.mock import MagicMock, patch

from widgets.program_sim_panel import (
    ProgramSIMPanel,
    SPN_UNSUPPORTED_PLACEHOLDER,
    _FORM_FIELDS,
)
from managers.card_manager import CardManager, CLIBackend, CardType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_panel():
    """Construct a ProgramSIMPanel without a real Qt application."""
    with patch("widgets.program_sim_panel.QWidget.__init__", return_value=None), \
         patch("widgets.program_sim_panel.ProgramSIMPanel._build_ui"):
        panel = ProgramSIMPanel.__new__(ProgramSIMPanel)
        panel._cm = MagicMock()
        panel.state_manager = None
        panel._ns_manager = None
        panel._card_watcher = None
        panel._last_browse_dir = None
        panel._csv = MagicMock()
        panel._last_read_data = {}
        panel._mode_var = "manual"
        panel._field_vars = {}
        panel._field_entries = {}
        panel._step = 1
        panel._original_form_data = {}
        panel._detected_non_empty = True
        panel._extra_card_data = {}
        panel.on_csv_loaded_callback = None
        panel.on_file_browsed_callback = None
        panel.on_card_programmed_callback = None
        panel._prog_btn = MagicMock()
        panel._action_status = MagicMock()
        # Build lightweight QLineEdit stand-ins
        for key, _, _ in _FORM_FIELDS:
            entry = MagicMock()
            entry._value = ""
            entry.text = lambda e=entry: e._value
            entry.strip = lambda: ""
            entry.setText = lambda v, e=entry: setattr(e, '_value', v)
            panel._field_entries[key] = entry
    return panel


def _make_card_manager(*, authenticated: bool = True,
                        card_type: CardType = CardType.SJA5):
    cm = CardManager.__new__(CardManager)
    cm._pcsc_reader_index = 0
    cm.cli_path = "/fake/pysim"
    cm.cli_backend = CLIBackend.PYSIM
    cm._venv_python = None
    cm.card_type = card_type
    cm.authenticated = authenticated
    cm.card_blocked = False
    cm._authenticated_adm1_hex = "3838383838383838"
    cm._original_card_data = {"ICCID": "8946001234567890123", "IMSI": "240010000000001"}
    cm.card_info = dict(cm._original_card_data)
    cm._adm1_remaining_attempts = 5
    cm._safety_override_acknowledged = True
    return cm


# ---------------------------------------------------------------------------
# Panel display tests
# ---------------------------------------------------------------------------

class TestSPNPlaceholderDisplay(unittest.TestCase):

    def test_on_card_info_changed_real_spn_becomes_placeholder(self):
        """CardInfo with a real SPN value → panel shows placeholder."""
        panel = _make_panel()
        card_info = MagicMock()
        card_info.iccid = "8946001234567890123"
        card_info.imsi = "240010000000001"
        card_info.acc = "0800"
        card_info.spn = "TestOperator"
        card_info.fplmn = ""
        panel._update_program_btn_state = MagicMock()

        panel._on_card_info_changed(card_info)

        self.assertEqual(
            panel._field_entries["SPN"]._value,
            SPN_UNSUPPORTED_PLACEHOLDER,
        )

    def test_on_card_info_changed_empty_spn_stays_empty(self):
        """CardInfo with no SPN → SPN field stays empty (no placeholder injected)."""
        panel = _make_panel()
        card_info = MagicMock()
        card_info.iccid = "8946001234567890123"
        card_info.imsi = "240010000000001"
        card_info.acc = ""
        card_info.spn = ""
        card_info.fplmn = ""
        panel._update_program_btn_state = MagicMock()

        panel._on_card_info_changed(card_info)

        self.assertEqual(panel._field_entries["SPN"]._value, "")

    def test_on_card_detected_with_spn_shows_placeholder(self):
        """on_card_detected with card_data containing SPN → panel shows placeholder."""
        panel = _make_panel()
        card_data = {
            "ICCID": "8946001234567890123",
            "IMSI": "240010000000001",
            "Ki": "A" * 32,
            "OPc": "B" * 32,
            "ADM1": "88888888",
            "ACC": "0800",
            "SPN": "Fiskarheden",
            "FPLMN": "",
        }
        panel._set_action_status = MagicMock()
        panel._update_program_btn_state = MagicMock()

        panel.on_card_detected("8946001234567890123", card_data=card_data)

        self.assertEqual(
            panel._field_entries["SPN"]._value,
            SPN_UNSUPPORTED_PLACEHOLDER,
        )

    def test_on_card_select_with_spn_shows_placeholder(self):
        """Selecting a CSV row with SPN → panel shows placeholder, not the real value."""
        panel = _make_panel()
        panel._csv = MagicMock()
        panel._csv.get_card.return_value = {
            "ICCID": "8946001234567890123",
            "IMSI": "240010000000001",
            "SPN": "RealOperatorName",
            "ADM1": "88888888",
        }
        panel._card_table = MagicMock()
        panel._card_table.currentRow.return_value = 0
        panel._update_program_btn_state = MagicMock()
        panel._set_action_status = MagicMock()

        panel._on_card_select()

        self.assertEqual(
            panel._field_entries["SPN"]._value,
            SPN_UNSUPPORTED_PLACEHOLDER,
        )

    def test_on_card_select_no_spn_field_stays_empty(self):
        """Selecting a CSV row with no SPN → SPN field stays empty."""
        panel = _make_panel()
        panel._csv = MagicMock()
        panel._csv.get_card.return_value = {
            "ICCID": "8946001234567890123",
            "IMSI": "240010000000001",
            "ADM1": "88888888",
        }
        panel._card_table = MagicMock()
        panel._card_table.currentRow.return_value = 0
        panel._update_program_btn_state = MagicMock()
        panel._set_action_status = MagicMock()

        panel._on_card_select()

        self.assertEqual(panel._field_entries["SPN"]._value, "")


# ---------------------------------------------------------------------------
# Panel → CardManager call test
# ---------------------------------------------------------------------------

class TestSPNStrippedBeforeProgramCall(unittest.TestCase):

    def test_on_program_strips_spn_before_calling_program_card(self):
        """_on_program must remove SPN from card_data before program_card()."""
        panel = _make_panel()

        # Populate fields including SPN with placeholder
        field_values = {
            "ICCID": "8946001234567890123",
            "IMSI": "240010000000001",
            "Ki": "A" * 32,
            "OPc": "B" * 32,
            "ADM1": "88888888",
            "ACC": "0800",
            "SPN": SPN_UNSUPPORTED_PLACEHOLDER,
            "FPLMN": "",
        }
        for key, val in field_values.items():
            panel._field_entries[key]._value = val

        panel._card_watcher = None

        # Capture the card_data passed to program_card
        received_card_data = {}

        def fake_authenticate(adm1, **kwargs):
            return True, "ok"

        def fake_program_card(card_data, original_data=None):
            received_card_data.update(card_data)
            return True, "Card programmed — verified: IMSI"

        panel._cm.authenticate = fake_authenticate
        panel._cm.program_card = fake_program_card
        panel._set_action_status = MagicMock()
        panel.on_card_programmed_callback = None

        panel._on_program()

        self.assertNotIn("SPN", received_card_data,
                         "SPN must not be passed to program_card()")


# ---------------------------------------------------------------------------
# CardManager defensive drop tests
# ---------------------------------------------------------------------------

class TestCardManagerDropsSPN(unittest.TestCase):

    def test_program_card_drops_spn_from_changed_fields(self):
        """program_card() must silently drop SPN before calling _program_via_pysim_prog."""
        cm = _make_card_manager()
        card_data = {
            "IMSI": "240010000000002",
            "SPN": "ShouldBeDropped",
            "ACC": "0800",
        }
        passed_fields = {}

        def fake_program_via(fields):
            passed_fields.update(fields)
            return True, "Card programmed — verified: IMSI, ACC"

        cm._program_via_pysim_prog = fake_program_via
        cm.check_adm1_retry_counter = MagicMock(return_value=5)

        ok, msg = cm.program_card(card_data)

        self.assertTrue(ok)
        self.assertNotIn("SPN", passed_fields,
                         "SPN must be dropped before _program_via_pysim_prog")

    def test_program_via_pysim_prog_drops_spn_defensively(self):
        """_program_via_pysim_prog() must pop SPN before passing fields to _run_pysim_prog."""
        cm = _make_card_manager()
        passed_card_data = {}

        def fake_run_pysim_prog(card_data, adm1_hex, timeout=60):
            passed_card_data.update(card_data)
            return True, "OK", ""

        cm._run_pysim_prog = fake_run_pysim_prog
        cm.verify_after_program = MagicMock(return_value=(
            True, "OK", {"IMSI": "240010000000002", "ICCID": "8946001234567890123"}))

        fields = {"IMSI": "240010000000002", "SPN": "ShouldNotReach", "ACC": "0800"}
        ok, msg = cm._program_via_pysim_prog(fields)

        self.assertTrue(ok)
        self.assertNotIn("SPN", passed_card_data,
                         "SPN must be dropped before _run_pysim_prog")

    def test_program_card_with_only_spn_change_returns_no_changes(self):
        """If SPN is the only changed field, program_card returns 'no changes' cleanly."""
        cm = _make_card_manager()
        cm._original_card_data = {
            "ICCID": "8946001234567890123",
            "IMSI": "240010000000001",
        }
        cm.check_adm1_retry_counter = MagicMock(return_value=5)

        card_data = {
            "ICCID": "8946001234567890123",
            "IMSI": "240010000000001",
            "SPN": "NewOperatorName",
        }
        ok, msg = cm.program_card(card_data)

        self.assertTrue(ok)
        self.assertIn("No changes", msg)

    def test_program_via_pysim_prog_message_never_contains_spn_warning(self):
        """Result message from _program_via_pysim_prog must not contain SPN warning text."""
        cm = _make_card_manager()

        def fake_run_pysim_prog(card_data, adm1_hex, timeout=60):
            return True, "OK", ""

        cm._run_pysim_prog = fake_run_pysim_prog
        cm.verify_after_program = MagicMock(return_value=(
            True, "OK", {"IMSI": "240010000000002"}))

        fields = {"IMSI": "240010000000002", "SPN": "Operator"}
        ok, msg = cm._program_via_pysim_prog(fields)

        self.assertTrue(ok)
        self.assertNotIn("not verified", msg)
        self.assertNotIn("not written", msg)
        self.assertNotIn("SPN", msg)


if __name__ == "__main__":
    unittest.main()
