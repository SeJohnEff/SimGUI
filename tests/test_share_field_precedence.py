"""Tests for network-share field precedence and passthrough in Program SIM.

Verifies:
- All known fields (incl. non-displayed PIN1/PUK1, KIC/KID/KIK, OLD_IMSI)
  are preserved when share data is loaded.
- Non-displayed fields pass through to card_data at programming time.
- Displayed fields always use the current form values (user edits win).
- Share data is cleared on card removal.
- _normalize_card_data handles common case variants.
"""

import types
from unittest.mock import MagicMock

import pytest

from widgets.program_sim_panel import (
    ProgramSIMPanel,
    _FORM_FIELDS,
    _FORM_FIELD_KEYS,
    _normalize_card_data,
)


# ---------------------------------------------------------------------------
# _normalize_card_data unit tests
# ---------------------------------------------------------------------------

class TestNormalizeCardData:
    def test_canonical_names_unchanged(self):
        data = {"ICCID": "1", "IMSI": "2", "Ki": "3", "OPc": "4",
                "ADM1": "5", "ACC": "6", "SPN": "7", "FPLMN": "8"}
        result = _normalize_card_data(data)
        assert result["ICCID"] == "1"
        assert result["Ki"] == "3"
        assert result["OPc"] == "4"
        assert result["ADM1"] == "5"

    def test_lowercase_keys_normalized(self):
        data = {"iccid": "A", "imsi": "B", "ki": "C", "opc": "D",
                "adm1": "E", "acc": "F", "spn": "G", "fplmn": "H"}
        result = _normalize_card_data(data)
        assert result["ICCID"] == "A"
        assert result["Ki"] == "C"
        assert result["OPc"] == "D"
        assert result["ADM1"] == "E"
        assert result["SPN"] == "G"
        assert result["FPLMN"] == "H"

    def test_opc_uppercase_variant(self):
        data = {"OPC": "DEADBEEF"}
        result = _normalize_card_data(data)
        assert result["OPc"] == "DEADBEEF"

    def test_adm_alias(self):
        data = {"adm": "88888888"}
        result = _normalize_card_data(data)
        assert result["ADM1"] == "88888888"

    def test_extra_known_fields_preserved(self):
        data = {
            "OLD_IMSI": "111", "PIN1": "1234", "PUK1": "12345678",
            "PIN2": "5678", "PUK2": "87654321",
            "KIC1": "AA" * 16, "KID1": "BB" * 16, "KIK1": "CC" * 16,
            "KIC2": "DD" * 16, "KID2": "EE" * 16, "KIK2": "FF" * 16,
            "KIC3": "11" * 16, "KID3": "22" * 16, "KIK3": "33" * 16,
        }
        result = _normalize_card_data(data)
        assert result["OLD_IMSI"] == "111"
        assert result["PIN1"] == "1234"
        assert result["PUK1"] == "12345678"
        assert result["KIC1"] == "AA" * 16
        assert result["KID1"] == "BB" * 16
        assert result["KIK1"] == "CC" * 16
        assert result["KIC3"] == "11" * 16

    def test_unknown_fields_uppercased(self):
        data = {"some_custom_field": "value"}
        result = _normalize_card_data(data)
        assert result["SOME_CUSTOM_FIELD"] == "value"

    def test_extra_fields_not_lost_for_known_lowercase(self):
        data = {"old_imsi": "999", "pin1": "0000", "kic1": "AABB"}
        result = _normalize_card_data(data)
        assert result["OLD_IMSI"] == "999"
        assert result["PIN1"] == "0000"
        assert result["KIC1"] == "AABB"


# ---------------------------------------------------------------------------
# Helpers for stub-based panel tests
# ---------------------------------------------------------------------------

def _make_panel_stub():
    """Bind ProgramSIMPanel methods to a MagicMock stub."""
    stub = MagicMock()
    # Real dict so each key returns its own independent mock
    stub._field_entries = {}
    for key, _, _ in _FORM_FIELDS:
        m = MagicMock()
        m.text.return_value = ""
        stub._field_entries[key] = m
    stub._detected_non_empty = False
    stub._step = 0
    stub._set_action_status = MagicMock()
    stub._fields_have_data = MagicMock(return_value=False)
    stub._original_form_data = {}
    stub._extra_card_data = {}
    stub._update_program_btn_state = MagicMock()
    stub._prog_btn = MagicMock()
    stub.on_card_detected = types.MethodType(ProgramSIMPanel.on_card_detected, stub)
    stub.on_card_removed = types.MethodType(ProgramSIMPanel.on_card_removed, stub)
    stub._reset_step = MagicMock()
    return stub


# ---------------------------------------------------------------------------
# on_card_detected: extra field storage
# ---------------------------------------------------------------------------

class TestOnCardDetectedExtraFields:
    def test_extra_fields_stored_in_extra_card_data(self):
        """Non-displayed fields are stored in _extra_card_data."""
        stub = _make_panel_stub()
        card_data = {
            "ICCID": "8946001234567890123",
            "IMSI": "24001012345",
            "Ki": "A" * 32,
            "OPc": "B" * 32,
            "ADM1": "88888888",
            "ACC": "0001",
            "SPN": "TEST",
            "FPLMN": "24007",
            "OLD_IMSI": "24001000000",
            "PIN1": "1234",
            "PUK1": "12345678",
            "PIN2": "5678",
            "PUK2": "87654321",
            "KIC1": "AA" * 16,
            "KID1": "BB" * 16,
            "KIK1": "CC" * 16,
        }

        stub.on_card_detected("8946001234567890123", card_data, "/share/batch.csv")

        assert stub._extra_card_data["OLD_IMSI"] == "24001000000"
        assert stub._extra_card_data["PIN1"] == "1234"
        assert stub._extra_card_data["PUK1"] == "12345678"
        assert stub._extra_card_data["KIC1"] == "AA" * 16
        assert stub._extra_card_data["KID1"] == "BB" * 16
        assert stub._extra_card_data["KIK1"] == "CC" * 16

    def test_displayed_fields_also_in_extra_card_data(self):
        """Displayed fields are present in _extra_card_data with canonical names."""
        stub = _make_panel_stub()
        card_data = {"ICCID": "123", "Ki": "A" * 32, "OPc": "B" * 32,
                     "ADM1": "88888888"}
        stub.on_card_detected("123", card_data, "/share/batch.csv")

        assert stub._extra_card_data["ICCID"] == "123"
        assert stub._extra_card_data["Ki"] == "A" * 32
        assert stub._extra_card_data["OPc"] == "B" * 32

    def test_no_card_data_clears_extra(self):
        """When card_data is None, _extra_card_data is cleared."""
        stub = _make_panel_stub()
        stub._extra_card_data = {"OLD_IMSI": "stale"}

        stub.on_card_detected("8946001234567890123", None, None)

        assert stub._extra_card_data == {}

    def test_blank_card_clears_extra(self):
        """Blank card (empty iccid, no data) clears _extra_card_data."""
        stub = _make_panel_stub()
        stub._extra_card_data = {"PIN1": "stale"}

        stub.on_card_detected("", None, None)

        assert stub._extra_card_data == {}

    def test_lowercase_keys_normalized_on_store(self):
        """Lowercase field names from raw file are normalized when stored."""
        stub = _make_panel_stub()
        card_data = {"iccid": "111", "ki": "A" * 32, "opc": "B" * 32,
                     "old_imsi": "222", "pin1": "0000"}
        stub.on_card_detected("111", card_data, "/share/f.csv")

        assert "Ki" in stub._extra_card_data
        assert "OPc" in stub._extra_card_data
        assert stub._extra_card_data["OLD_IMSI"] == "222"
        assert stub._extra_card_data["PIN1"] == "0000"


# ---------------------------------------------------------------------------
# on_card_removed: clears extra data
# ---------------------------------------------------------------------------

class TestOnCardRemovedClearsExtra:
    def test_extra_data_cleared_on_removal(self):
        stub = _make_panel_stub()
        stub._extra_card_data = {"OLD_IMSI": "999", "PIN1": "1234"}

        stub.on_card_removed()

        assert stub._extra_card_data == {}


# ---------------------------------------------------------------------------
# _on_program: extra fields passed through to card_data
# ---------------------------------------------------------------------------

class TestOnProgramMergesExtras:
    def _make_program_stub(self, share_extras: dict, form_values: dict):
        """Stub with _extra_card_data set and form fields returning form_values."""
        stub = MagicMock()
        stub._step = 1
        stub._extra_card_data = share_extras
        stub._original_form_data = {}
        stub._card_watcher = None

        # Use a real dict so each key returns its own mock (not MagicMock.__getitem__)
        stub._field_entries = {}
        for key, _, _ in _FORM_FIELDS:
            m = MagicMock()
            m.text.return_value = form_values.get(key, "")
            stub._field_entries[key] = m

        # Capture what card_data is passed to program_card
        captured = {}

        def fake_program_card(card_data, original_data=None):
            captured.update(card_data)
            return True, "OK"

        stub._cm.authenticate.return_value = (True, "OK")
        stub._cm.program_card.side_effect = fake_program_card
        stub._set_action_status = MagicMock()
        stub.on_card_programmed_callback = None

        stub._on_program = types.MethodType(ProgramSIMPanel._on_program, stub)
        return stub, captured

    def test_extra_fields_included_in_card_data(self):
        """Non-displayed share fields pass through to program_card()."""
        share_extras = {
            "ICCID": "111", "Ki": "A" * 32, "OPc": "B" * 32,
            "ADM1": "88888888", "IMSI": "240010", "ACC": "", "SPN": "", "FPLMN": "",
            "OLD_IMSI": "240009", "PIN1": "1234", "PUK1": "12345678",
            "KIC1": "AA" * 16, "KID1": "BB" * 16, "KIK1": "CC" * 16,
        }
        form_values = {
            "ICCID": "111", "IMSI": "240010", "Ki": "A" * 32,
            "OPc": "B" * 32, "ADM1": "88888888", "ACC": "", "SPN": "", "FPLMN": "",
        }
        stub, captured = self._make_program_stub(share_extras, form_values)

        stub._on_program()

        assert captured["OLD_IMSI"] == "240009"
        assert captured["PIN1"] == "1234"
        assert captured["PUK1"] == "12345678"
        assert captured["KIC1"] == "AA" * 16

    def test_displayed_fields_override_share_values(self):
        """User-edited displayed fields override the share values in card_data."""
        share_extras = {
            "ICCID": "111", "IMSI": "OLD_IMSI_VAL", "Ki": "AA" * 16,
            "OPc": "BB" * 16, "ADM1": "88888888",
            "ACC": "", "SPN": "", "FPLMN": "",
            "PIN1": "1234",
        }
        form_values = {
            "ICCID": "111", "IMSI": "NEW_IMSI_VAL", "Ki": "CC" * 16,
            "OPc": "DD" * 16, "ADM1": "88888888",
            "ACC": "", "SPN": "MyNetwork", "FPLMN": "",
        }
        stub, captured = self._make_program_stub(share_extras, form_values)

        stub._on_program()

        # Form values win for displayed fields
        assert captured["IMSI"] == "NEW_IMSI_VAL"
        assert captured["Ki"] == "CC" * 16
        assert captured["SPN"] == "MyNetwork"
        # Non-displayed share fields still present
        assert captured["PIN1"] == "1234"

    def test_no_share_data_behaves_as_before(self):
        """Empty _extra_card_data: card_data contains only displayed fields."""
        share_extras = {}
        form_values = {
            "ICCID": "222", "IMSI": "240010", "Ki": "A" * 32,
            "OPc": "B" * 32, "ADM1": "88888888", "ACC": "0001",
            "SPN": "Test", "FPLMN": "24007",
        }
        stub, captured = self._make_program_stub(share_extras, form_values)

        stub._on_program()

        assert captured["ICCID"] == "222"
        assert captured["IMSI"] == "240010"
        assert captured["ADM1"] == "88888888"
        # No extra keys
        assert "OLD_IMSI" not in captured
        assert "PIN1" not in captured

    def test_missing_adm1_aborts_before_program(self):
        """Missing ADM1 aborts early — program_card is not called."""
        stub = MagicMock()
        stub._step = 1
        stub._extra_card_data = {}
        stub._field_entries = {}
        for key, _, _ in _FORM_FIELDS:
            m = MagicMock()
            m.text.return_value = ""
            stub._field_entries[key] = m
        stub._set_action_status = MagicMock()
        stub._card_watcher = None
        stub._on_program = types.MethodType(ProgramSIMPanel._on_program, stub)

        stub._on_program()

        stub._cm.program_card.assert_not_called()
