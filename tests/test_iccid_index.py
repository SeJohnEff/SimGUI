"""Tests for managers.iccid_index — range-based ICCID index."""

import csv
import os
import tempfile
import time

import pytest

from managers.iccid_index import (
    IccidIndex,
    IndexEntry,
    ScanResult,
    _detect_ranges,
    _luhn_strip,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(path: str, rows: list[dict]):
    """Write a simple CSV with the given rows."""
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _make_sysmocom_iccids(prefix: str, start: int, count: int,
                           length: int = 19) -> list[str]:
    """Generate sequential ICCIDs like sysmocom batches.

    For 19-digit ICCIDs, appends a dummy Luhn digit.
    """
    iccids = []
    suffix_len = length - len(prefix) - (1 if length == 19 else 0)
    for i in range(count):
        suffix = str(start + i).zfill(suffix_len)
        iccid = prefix + suffix
        if length == 19:
            iccid += "0"  # dummy Luhn digit
        iccids.append(iccid)
    return iccids


# ---------------------------------------------------------------------------
# Tests for _luhn_strip
# ---------------------------------------------------------------------------

class TestLuhnStrip:
    def test_19_digit(self):
        assert _luhn_strip("8949440000001672706") == "894944000000167270"

    def test_20_digit(self):
        assert _luhn_strip("89494400000016727060") == "8949440000001672706"

    def test_23_digit_unchanged(self):
        iccid = "89461000001000000000001"
        assert _luhn_strip(iccid) == iccid

    def test_empty(self):
        assert _luhn_strip("") == ""

    def test_short(self):
        assert _luhn_strip("12345") == "12345"


# ---------------------------------------------------------------------------
# Tests for _detect_ranges
# ---------------------------------------------------------------------------

class TestDetectRanges:
    def test_empty(self):
        assert _detect_ranges([]) == []

    def test_single_iccid(self):
        ranges = _detect_ranges(["8949440000001672706"])
        assert len(ranges) == 1
        prefix, start, end, slen = ranges[0]
        assert start == end  # single element

    def test_contiguous_range(self):
        iccids = _make_sysmocom_iccids("89494400000016", 100, 20)
        ranges = _detect_ranges(iccids)
        assert len(ranges) == 1
        prefix, start, end, slen = ranges[0]
        assert end - start + 1 == 20

    def test_two_ranges_with_gap(self):
        batch1 = _make_sysmocom_iccids("89494400000016", 100, 10)
        batch2 = _make_sysmocom_iccids("89494400000016", 200, 10)
        iccids = batch1 + batch2
        ranges = _detect_ranges(iccids)
        assert len(ranges) == 2
        assert ranges[0][3] == ranges[1][3]  # same suffix_len

    def test_23_digit_fiskarheden(self):
        iccids = [f"8946100000100000000{i:04d}" for i in range(1, 11)]
        ranges = _detect_ranges(iccids)
        assert len(ranges) == 1
        _, start, end, _ = ranges[0]
        assert end - start + 1 == 10


# ---------------------------------------------------------------------------
# Tests for IndexEntry.contains
# ---------------------------------------------------------------------------

class TestIndexEntryContains:
    def test_match(self):
        entry = IndexEntry(
            file_path="test.csv",
            prefix="89494400000016",
            range_start=100,
            range_end=119,
            suffix_len=4,
            card_count=20,
            iccid_length=19,
        )
        # ICCID: prefix(14) + suffix(4) + luhn(1) = 19
        assert entry.contains("8949440000001601000")  # suffix after strip: "0100"
        assert entry.contains("8949440000001601190")  # suffix: "0119"

    def test_out_of_range(self):
        entry = IndexEntry(
            file_path="test.csv",
            prefix="89494400000016",
            range_start=100,
            range_end=119,
            suffix_len=4,
            card_count=20,
            iccid_length=19,
        )
        assert not entry.contains("8949440000001601200")  # suffix: "0120" > 119

    def test_wrong_length(self):
        entry = IndexEntry(
            file_path="test.csv",
            prefix="89494400000016",
            range_start=100,
            range_end=119,
            suffix_len=4,
            card_count=20,
            iccid_length=19,
        )
        assert not entry.contains("894944000000160100")  # 18 digits

    def test_wrong_prefix(self):
        entry = IndexEntry(
            file_path="test.csv",
            prefix="89494400000016",
            range_start=100,
            range_end=119,
            suffix_len=4,
            card_count=20,
            iccid_length=19,
        )
        assert not entry.contains("8949440000002601000")


# ---------------------------------------------------------------------------
# Tests for IccidIndex
# ---------------------------------------------------------------------------

class TestIccidIndex:
    def test_scan_empty_dir(self, tmp_path):
        idx = IccidIndex()
        result = idx.scan_directory(str(tmp_path))
        assert result.files_scanned == 0
        assert result.total_cards == 0

    def test_scan_nonexistent_dir(self):
        idx = IccidIndex()
        result = idx.scan_directory("/nonexistent/path")
        assert len(result.errors) > 0

    def test_scan_csv_file(self, tmp_path):
        iccids = _make_sysmocom_iccids("89494400000016", 100, 20)
        rows = [{"ICCID": ic, "IMSI": f"999880001{i:05d}",
                 "Ki": "A" * 32, "OPc": "B" * 32, "ADM1": "88888888"}
                for i, ic in enumerate(iccids)]
        _write_csv(str(tmp_path / "batch.csv"), rows)

        idx = IccidIndex()
        result = idx.scan_directory(str(tmp_path))
        assert result.files_scanned == 1
        assert result.total_cards == 20

    def test_lookup_found(self, tmp_path):
        iccids = _make_sysmocom_iccids("89494400000016", 100, 20)
        rows = [{"ICCID": ic, "IMSI": f"999880001{i:05d}"}
                for i, ic in enumerate(iccids)]
        _write_csv(str(tmp_path / "batch.csv"), rows)

        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))
        entry = idx.lookup(iccids[5])
        assert entry is not None
        assert entry.file_path == str(tmp_path / "batch.csv")

    def test_lookup_not_found(self, tmp_path):
        iccids = _make_sysmocom_iccids("89494400000016", 100, 20)
        rows = [{"ICCID": ic} for ic in iccids]
        _write_csv(str(tmp_path / "batch.csv"), rows)

        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))
        assert idx.lookup("0000000000000000000") is None

    def test_load_card(self, tmp_path):
        iccids = _make_sysmocom_iccids("89494400000016", 100, 5)
        rows = [{"ICCID": ic, "IMSI": f"99988000{i:06d}",
                 "Ki": "A" * 32, "ADM1": "88888888"}
                for i, ic in enumerate(iccids)]
        _write_csv(str(tmp_path / "batch.csv"), rows)

        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))
        card = idx.load_card(iccids[2])
        assert card is not None
        assert card["ICCID"] == iccids[2]
        assert card["IMSI"] == "99988000000002"

    def test_load_card_not_found(self, tmp_path):
        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))
        assert idx.load_card("0000000000000000000") is None

    def test_rescan_skips_unchanged(self, tmp_path):
        iccids = _make_sysmocom_iccids("89494400000016", 100, 5)
        rows = [{"ICCID": ic} for ic in iccids]
        _write_csv(str(tmp_path / "batch.csv"), rows)

        idx = IccidIndex()
        result1 = idx.scan_directory(str(tmp_path))
        assert result1.files_scanned == 1

        # Rescan without changes
        result2 = idx.rescan_if_stale(str(tmp_path))
        assert result2 is None  # nothing stale

    def test_rescan_detects_new_file(self, tmp_path):
        iccids1 = _make_sysmocom_iccids("89494400000016", 100, 5)
        _write_csv(str(tmp_path / "batch1.csv"),
                   [{"ICCID": ic} for ic in iccids1])

        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))

        # Add a new file
        iccids2 = _make_sysmocom_iccids("89494400000016", 200, 5)
        _write_csv(str(tmp_path / "batch2.csv"),
                   [{"ICCID": ic} for ic in iccids2])

        result = idx.rescan_if_stale(str(tmp_path))
        assert result is not None
        assert result.files_scanned >= 1

    def test_stats(self, tmp_path):
        iccids = _make_sysmocom_iccids("89494400000016", 100, 10)
        _write_csv(str(tmp_path / "batch.csv"),
                   [{"ICCID": ic} for ic in iccids])

        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))
        s = idx.stats
        assert s["files"] == 1
        assert s["total_cards"] == 10

    def test_clear(self, tmp_path):
        iccids = _make_sysmocom_iccids("89494400000016", 100, 5)
        _write_csv(str(tmp_path / "batch.csv"),
                   [{"ICCID": ic} for ic in iccids])

        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))
        assert idx.stats["files"] == 1
        idx.clear()
        assert idx.stats["files"] == 0

    def test_multiple_files(self, tmp_path):
        iccids1 = _make_sysmocom_iccids("89494400000016", 100, 10)
        iccids2 = _make_sysmocom_iccids("89494400000016", 200, 10)
        _write_csv(str(tmp_path / "batch1.csv"),
                   [{"ICCID": ic, "IMSI": "A"} for ic in iccids1])
        _write_csv(str(tmp_path / "batch2.csv"),
                   [{"ICCID": ic, "IMSI": "B"} for ic in iccids2])

        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))
        assert idx.stats["files"] == 2
        assert idx.stats["total_cards"] == 20

        # Lookup from each file
        e1 = idx.lookup(iccids1[5])
        e2 = idx.lookup(iccids2[5])
        assert e1 is not None
        assert e2 is not None
        assert e1.file_path != e2.file_path

    def test_txt_file_support(self, tmp_path):
        """Test Fiskarheden-style .txt files (23-digit ICCIDs)."""
        path = tmp_path / "simFiskarheden.txt"
        with open(str(path), "w") as fh:
            fh.write("ICCID\tIMSI\tKi\n")
            for i in range(10):
                iccid = f"8946100000100000000{i:04d}"
                fh.write(f"{iccid}\t99988{i:010d}\t{'FF' * 16}\n")

        idx = IccidIndex()
        result = idx.scan_directory(str(tmp_path))
        assert result.files_scanned == 1
        assert result.total_cards == 10

    def test_csv_without_iccid_column_skipped(self, tmp_path):
        """CSV files without ICCID column (like Raketen) are skipped."""
        rows = [{"IMSI": f"99988{i:010d}", "Ki": "A" * 32}
                for i in range(5)]
        _write_csv(str(tmp_path / "no_iccid.csv"), rows)

        idx = IccidIndex()
        result = idx.scan_directory(str(tmp_path))
        assert result.total_cards == 0

    def test_cache_lru_eviction(self, tmp_path):
        """Cache evicts oldest entries when full."""
        iccids = _make_sysmocom_iccids("89494400000016", 100, 10)
        rows = [{"ICCID": ic, "IMSI": f"99988{i:010d}"}
                for i, ic in enumerate(iccids)]
        _write_csv(str(tmp_path / "batch.csv"), rows)

        idx = IccidIndex(cache_size=3)
        idx.scan_directory(str(tmp_path))

        # Load more cards than cache can hold
        for ic in iccids[:5]:
            idx.load_card(ic)

        # Cache should only hold the most recent ones
        assert idx.stats["cached_cards"] <= 3
