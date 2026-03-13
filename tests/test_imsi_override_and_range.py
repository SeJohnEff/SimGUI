"""Tests for IMSI override and range filter functions in batch_program_panel."""

import pytest

from widgets.batch_program_panel import apply_imsi_override, apply_range_filter


# ---- Sample data --------------------------------------------------------

def _make_cards(n: int = 5) -> list[dict[str, str]]:
    """Create *n* sample card dicts with sequential IMSI and unique ICCID."""
    cards = []
    for i in range(n):
        cards.append({
            "ICCID": f"8999988000440010{i:04d}",
            "IMSI": f"9998804400103{i:02d}",
            "Ki": f"{'A' * 32}",
            "OPc": f"{'B' * 32}",
            "ADM1": "3838383838383838",
        })
    return cards


# ---- apply_range_filter -------------------------------------------------

class TestApplyRangeFilter:
    """Tests for apply_range_filter()."""

    def test_full_range(self):
        cards = _make_cards(5)
        result = apply_range_filter(cards, start=1, count=5)
        assert len(result) == 5
        assert result[0]["IMSI"] == cards[0]["IMSI"]
        assert result[4]["IMSI"] == cards[4]["IMSI"]

    def test_subset_from_start(self):
        cards = _make_cards(10)
        result = apply_range_filter(cards, start=1, count=3)
        assert len(result) == 3
        assert result[0]["IMSI"] == cards[0]["IMSI"]
        assert result[2]["IMSI"] == cards[2]["IMSI"]

    def test_subset_from_middle(self):
        cards = _make_cards(10)
        result = apply_range_filter(cards, start=4, count=3)
        assert len(result) == 3
        # start=4 means index 3
        assert result[0]["IMSI"] == cards[3]["IMSI"]
        assert result[2]["IMSI"] == cards[5]["IMSI"]

    def test_count_exceeds_available(self):
        cards = _make_cards(5)
        result = apply_range_filter(cards, start=3, count=100)
        # Only 3 cards available from row 3 onward (indices 2, 3, 4)
        assert len(result) == 3
        assert result[0]["IMSI"] == cards[2]["IMSI"]

    def test_start_beyond_end(self):
        cards = _make_cards(5)
        result = apply_range_filter(cards, start=10, count=5)
        assert len(result) == 0

    def test_empty_cards(self):
        result = apply_range_filter([], start=1, count=5)
        assert len(result) == 0

    def test_returns_copies(self):
        """Ensure returned dicts are copies, not references to originals."""
        cards = _make_cards(3)
        result = apply_range_filter(cards, start=1, count=3)
        result[0]["IMSI"] = "MODIFIED"
        assert cards[0]["IMSI"] != "MODIFIED"

    def test_start_zero_treated_as_one(self):
        cards = _make_cards(5)
        result = apply_range_filter(cards, start=0, count=2)
        assert len(result) == 2
        assert result[0]["IMSI"] == cards[0]["IMSI"]


# ---- apply_imsi_override ------------------------------------------------

class TestApplyIMSIOverride:
    """Tests for apply_imsi_override()."""

    def test_basic_override(self):
        cards = _make_cards(3)
        result = apply_imsi_override(cards, "9998804600101")
        assert result[0]["IMSI"] == "999880460010101"
        assert result[1]["IMSI"] == "999880460010102"
        assert result[2]["IMSI"] == "999880460010103"

    def test_custom_start_seq(self):
        cards = _make_cards(3)
        result = apply_imsi_override(cards, "9998804600101", start_seq=5)
        assert result[0]["IMSI"] == "999880460010105"
        assert result[1]["IMSI"] == "999880460010106"
        assert result[2]["IMSI"] == "999880460010107"

    def test_iccid_untouched(self):
        """ICCID must NEVER be modified by IMSI override."""
        cards = _make_cards(3)
        original_iccids = [c["ICCID"] for c in cards]
        result = apply_imsi_override(cards, "9998804600101")
        for orig_iccid, new_card in zip(original_iccids, result):
            assert new_card["ICCID"] == orig_iccid

    def test_other_fields_untouched(self):
        cards = _make_cards(2)
        result = apply_imsi_override(cards, "9998804600101")
        assert result[0]["Ki"] == cards[0]["Ki"]
        assert result[0]["ADM1"] == cards[0]["ADM1"]
        assert result[1]["OPc"] == cards[1]["OPc"]

    def test_returns_copies(self):
        cards = _make_cards(2)
        result = apply_imsi_override(cards, "9998804600101")
        result[0]["IMSI"] = "MODIFIED"
        # Original should be unchanged
        assert cards[0]["IMSI"] != "MODIFIED"

    def test_empty_cards(self):
        result = apply_imsi_override([], "9998804600101")
        assert result == []

    def test_two_digit_seq_padding(self):
        """Sequence numbers below 10 should be zero-padded."""
        cards = _make_cards(1)
        result = apply_imsi_override(cards, "9998804600101", start_seq=3)
        assert result[0]["IMSI"].endswith("03")

    def test_seq_above_99(self):
        """Sequence numbers above 99 get 3+ digits — not ideal but shouldn't crash."""
        cards = _make_cards(1)
        result = apply_imsi_override(cards, "9998804600101", start_seq=100)
        assert result[0]["IMSI"] == "9998804600101100"


# ---- Combined workflows ------------------------------------------------

class TestCombinedWorkflows:
    """Test range + IMSI override together."""

    def test_range_then_override(self):
        cards = _make_cards(10)
        # Select rows 3-7 (5 cards)
        filtered = apply_range_filter(cards, start=3, count=5)
        assert len(filtered) == 5
        # Override IMSI with start_seq matching the start row
        result = apply_imsi_override(filtered, "9998804600201", start_seq=3)
        assert result[0]["IMSI"] == "999880460020103"
        assert result[4]["IMSI"] == "999880460020107"
        # ICCID from original row 3 (index 2) should be preserved
        assert result[0]["ICCID"] == cards[2]["ICCID"]

    def test_range_without_override(self):
        cards = _make_cards(10)
        filtered = apply_range_filter(cards, start=5, count=3)
        # Original IMSIs preserved
        assert filtered[0]["IMSI"] == cards[4]["IMSI"]
        assert filtered[2]["IMSI"] == cards[6]["IMSI"]
