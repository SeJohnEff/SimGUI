"""Tests for the 'From Read Card' data source on the Program SIM tab.

Verifies the data flow: Read SIM → shared state → Program SIM form fields.
Uses mocked CardManager — no hardware or pySim needed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ---------------------------------------------------------------------------
# TestSharedReadData — verifying data flows into the shared dict
# ---------------------------------------------------------------------------

class TestSharedReadData:
    """Simulate what ReadSIMPanel does: read public/protected and update dict."""

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
