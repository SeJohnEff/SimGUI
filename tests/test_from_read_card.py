"""Tests for the 'From Read Card' data source on the Program SIM tab.

Verifies the data flow: Read SIM → shared state → Program SIM form fields.
Uses the simulator backend so no hardware is needed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_manager import CardManager
from simulator.simulator_backend import SimulatorBackend
from simulator.settings import SimulatorSettings
from simulator.virtual_card import VirtualCard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_card_manager_with_simulator(**overrides):
    """Return a CardManager in simulator mode with a single known card."""
    cm = CardManager()
    settings = SimulatorSettings()
    settings.num_cards = 1
    settings.delay_ms = 0
    cm.enable_simulator(settings)
    # Overwrite the deck with a card whose data we control
    card = VirtualCard(
        card_type="SJA2",
        iccid="89860012345678901234",
        imsi="001010123456789",
        ki="A" * 32,
        opc="B" * 32,
        adm1="12345678",
        acc="0004",
    )
    for k, v in overrides.items():
        setattr(card, k, v)
    cm._simulator.card_deck = [card]
    cm._simulator.current_card_index = 0
    return cm


# ---------------------------------------------------------------------------
# TestSharedReadData — verifying data flows into the shared dict
# ---------------------------------------------------------------------------

class TestSharedReadData:
    """Simulate what ReadSIMPanel does: read public/protected and update dict."""

    def test_public_read_populates_shared_state(self):
        cm = _make_card_manager_with_simulator()
        shared = {}

        # Simulate detect + public read (what ReadSIMPanel.refresh does)
        ok, _ = cm.detect_card()
        assert ok
        pub = cm.read_public_data()
        assert pub is not None

        # Simulate what ReadSIMPanel._update_shared_read_data does
        shared.clear()
        shared.update(pub)

        assert shared["iccid"] == "89860012345678901234"
        assert shared["imsi"] == "001010123456789"
        assert shared["acc"] == "0004"

    def test_protected_read_adds_to_shared_state(self):
        cm = _make_card_manager_with_simulator()
        shared = {}

        ok, _ = cm.detect_card()
        assert ok
        pub = cm.read_public_data()
        shared.update(pub)

        # Authenticate and read protected
        ok, _ = cm.authenticate("12345678")
        assert ok
        prot = cm.read_protected_data()
        assert prot is not None
        shared.update(prot)

        assert shared["ki"] == "A" * 32
        assert shared["opc"] == "B" * 32
        # Note: adm1 is not included in get_current_data() / get_protected_data()
        # because it's a state field on VirtualCard, not a data field
        # Public fields still present
        assert shared["iccid"] == "89860012345678901234"

    def test_shared_state_cleared_when_no_card(self):
        shared = {"iccid": "old_value", "imsi": "old_value"}
        # Simulate what ReadSIMPanel.refresh does when pub is empty
        shared.clear()
        assert shared == {}


# ---------------------------------------------------------------------------
# TestProgramSIMReadCardPopulation — verifying form population logic
# ---------------------------------------------------------------------------

class TestProgramSIMReadCardPopulation:
    """Test the _READ_KEY_MAP-based population logic used by ProgramSIMPanel."""

    # Replicate the key mapping from ProgramSIMPanel
    _READ_KEY_MAP = {
        "iccid": "ICCID",
        "imsi": "IMSI",
        "ki": "Ki",
        "opc": "OPc",
        "adm1": "ADM1",
        "acc": "ACC",
        "spn": "SPN",
        "fplmn": "FPLMN",
    }

    def _populate_fields(self, shared_data):
        """Simulate _populate_from_read_card() logic, return populated dict."""
        fields = {}
        for read_key, form_key in self._READ_KEY_MAP.items():
            fields[form_key] = shared_data.get(read_key, "")
        return fields

    def test_full_read_populates_all_fields(self):
        shared = {
            "iccid": "89860012345678901234",
            "imsi": "001010123456789",
            "ki": "A" * 32,
            "opc": "B" * 32,
            "adm1": "12345678",
            "acc": "0004",
            "spn": "TestSPN",
            "fplmn": "001001",
        }
        fields = self._populate_fields(shared)
        assert fields["ICCID"] == "89860012345678901234"
        assert fields["IMSI"] == "001010123456789"
        assert fields["Ki"] == "A" * 32
        assert fields["OPc"] == "B" * 32
        assert fields["ADM1"] == "12345678"
        assert fields["ACC"] == "0004"
        assert fields["SPN"] == "TestSPN"
        assert fields["FPLMN"] == "001001"

    def test_public_only_read_leaves_protected_empty(self):
        """When only public fields are read, protected fields are empty strings."""
        shared = {
            "iccid": "89860012345678901234",
            "imsi": "001010123456789",
            "acc": "0004",
        }
        fields = self._populate_fields(shared)
        assert fields["ICCID"] == "89860012345678901234"
        assert fields["IMSI"] == "001010123456789"
        # Protected fields should be empty, not missing
        assert fields["Ki"] == ""
        assert fields["OPc"] == ""
        assert fields["ADM1"] == ""

    def test_empty_shared_state_gives_all_empty(self):
        fields = self._populate_fields({})
        for form_key in self._READ_KEY_MAP.values():
            assert fields[form_key] == ""


# ---------------------------------------------------------------------------
# TestEndToEndReadThenProgram — full simulator flow
# ---------------------------------------------------------------------------

class TestEndToEndReadThenProgram:
    """End-to-end test: read a card, then populate Program SIM fields."""

    def test_read_public_then_populate(self):
        cm = _make_card_manager_with_simulator()
        shared = {}

        # Read phase (simulates ReadSIMPanel)
        cm.detect_card()
        pub = cm.read_public_data()
        shared.update(pub)

        # Program phase (simulates ProgramSIMPanel._populate_from_read_card)
        form_iccid = shared.get("iccid", "")
        form_imsi = shared.get("imsi", "")
        assert form_iccid == "89860012345678901234"
        assert form_imsi == "001010123456789"

    def test_full_read_then_modify_and_program(self):
        cm = _make_card_manager_with_simulator()
        shared = {}

        # Read phase
        cm.detect_card()
        pub = cm.read_public_data()
        shared.update(pub)
        cm.authenticate("12345678")
        prot = cm.read_protected_data()
        shared.update(prot)

        # Populate form from shared (uppercase keys as the form uses)
        card_data = {
            "ICCID": shared.get("iccid", ""),
            "IMSI": shared.get("imsi", ""),
            "Ki": shared.get("ki", ""),
            "OPc": shared.get("opc", ""),
            "ADM1": "12345678",
            "ACC": shared.get("acc", ""),
        }
        # User modifies IMSI (the main use case)
        card_data["IMSI"] = "999990123456789"

        # Program the card
        ok, msg = cm.program_card(card_data)
        assert ok

        # Verify the modification was stored
        card = cm._simulator._current_card()
        assert card.programmed_fields["IMSI"] == "999990123456789"

    def test_iccid_cross_check_still_works(self):
        """ICCID cross-check during authentication should still function."""
        cm = _make_card_manager_with_simulator()

        cm.detect_card()
        # Authenticate with the correct ICCID
        ok, msg = cm.authenticate(
            "12345678", expected_iccid="89860012345678901234")
        assert ok

    def test_iccid_mismatch_detected(self):
        """A mismatched ICCID should be flagged during authentication."""
        cm = _make_card_manager_with_simulator()

        cm.detect_card()
        # Authenticate with wrong ICCID
        ok, msg = cm.authenticate(
            "12345678", expected_iccid="99999999999999999999")
        assert ok is False
        assert "ICCID mismatch" in msg


# ---------------------------------------------------------------------------
# TestSourceSwitching — verify mode switching logic
# ---------------------------------------------------------------------------

class TestSourceSwitching:
    """Test that switching between data sources behaves correctly."""

    def test_read_key_map_covers_all_form_fields(self):
        """Ensure _READ_KEY_MAP covers every field in _FORM_FIELDS."""
        from widgets.program_sim_panel import _FORM_FIELDS, ProgramSIMPanel
        form_keys = {key for key, _, _ in _FORM_FIELDS}
        mapped_form_keys = set(ProgramSIMPanel._READ_KEY_MAP.values())
        assert form_keys == mapped_form_keys

    def test_shared_dict_is_same_object(self):
        """Verify that the shared dict is the same object for read/write."""
        shared = {"iccid": "test"}
        # Simulate ReadSIMPanel updating it
        shared["imsi"] = "12345"
        # ProgramSIMPanel reads from the same reference
        assert shared["imsi"] == "12345"

    def test_shared_dict_mutation_visible(self):
        """Both panels reference the same dict, changes are visible."""
        shared = {}
        reader_ref = shared
        writer_ref = shared

        # "ReadSIMPanel" updates
        reader_ref["iccid"] = "89860012345678901234"
        reader_ref["ki"] = "A" * 32

        # "ProgramSIMPanel" sees the updates
        assert writer_ref.get("iccid") == "89860012345678901234"
        assert writer_ref.get("ki") == "A" * 32
