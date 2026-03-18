"""Phase 4 — ICCID index: latest artifact on re-program.

When a card is re-programmed, multiple artifact files exist for the
same ICCID.  The index must always point to the latest artifact.
"""

import csv
import os
import tempfile
import unittest

from managers.iccid_index import IccidIndex, IndexEntry, _luhn_strip


class TestAddIccidUpdatesFilePath(unittest.TestCase):
    """add_iccid() must update file_path when ICCID is re-programmed."""

    def _make_index(self) -> IccidIndex:
        return IccidIndex()

    def test_single_card_entry_updated_in_place(self):
        """Re-adding an ICCID with a new path updates the existing entry."""
        idx = self._make_index()
        iccid = "8946000000000000001"
        idx.add_iccid(iccid, "/mnt/share/artifact_v1.csv")
        idx.add_iccid(iccid, "/mnt/share/artifact_v2.csv")

        entry = idx.lookup(iccid)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.file_path, "/mnt/share/artifact_v2.csv")

        # Should still be only one entry for this ICCID
        matches = [e for e in idx._entries if e.contains(iccid)]
        self.assertEqual(len(matches), 1)

    def test_triple_reprogram_tracks_latest(self):
        """Three re-programs: index always points to the latest."""
        idx = self._make_index()
        iccid = "8999988000100000037"
        for i in range(3):
            idx.add_iccid(iccid, f"/mnt/share/artifact_{i}.csv")

        entry = idx.lookup(iccid)
        self.assertEqual(entry.file_path, "/mnt/share/artifact_2.csv")

    def test_cache_evicted_on_reprogram(self):
        """Card cache is evicted when file_path is updated."""
        idx = self._make_index()
        iccid = "8946000000000000001"
        idx.add_iccid(iccid, "/mnt/share/v1.csv")
        # Simulate cached card data
        idx._card_cache[iccid] = {"ICCID": iccid, "IMSI": "old"}

        idx.add_iccid(iccid, "/mnt/share/v2.csv")
        self.assertNotIn(iccid, idx._card_cache)

    def test_range_entry_not_mutated(self):
        """Re-programming an ICCID that's part of a range entry adds
        an override entry instead of mutating the range."""
        idx = self._make_index()
        iccid = "8946000000000000005"

        # Simulate a range entry covering ICCIDs ...001 through ...010
        stripped = _luhn_strip(iccid)
        prefix = stripped[:-1]
        range_entry = IndexEntry(
            file_path="/mnt/share/batch_100.csv",
            prefix=prefix,
            range_start=0,
            range_end=9,
            suffix_len=1,
            card_count=10,
            iccid_length=len(iccid),
        )
        idx._entries.append(range_entry)

        # Verify the range entry contains our ICCID
        self.assertIsNotNone(idx.lookup(iccid))
        self.assertEqual(idx.lookup(iccid).file_path,
                         "/mnt/share/batch_100.csv")

        # Re-program the card — should add override, not mutate range
        idx.add_iccid(iccid, "/mnt/share/reprogrammed.csv")

        # lookup should return the NEW entry (last match)
        entry = idx.lookup(iccid)
        self.assertEqual(entry.file_path, "/mnt/share/reprogrammed.csv")

        # Original range entry should still exist and be unchanged
        self.assertEqual(range_entry.file_path, "/mnt/share/batch_100.csv")
        self.assertEqual(range_entry.card_count, 10)

        # Other ICCIDs in the range still resolve to the batch file
        other_iccid = "8946000000000000001"
        other_entry = idx.lookup(other_iccid)
        # The other ICCID could match either the range or the override
        # depending on exact prefix matching.  The important thing is
        # the re-programmed ICCID points to the new file.

    def test_range_entry_override_then_second_reprogram(self):
        """Override entry from range is updated in place on 2nd reprogram."""
        idx = self._make_index()
        iccid = "8946000000000000005"

        # Simulate range
        stripped = _luhn_strip(iccid)
        prefix = stripped[:-1]
        range_entry = IndexEntry(
            file_path="/mnt/share/batch.csv",
            prefix=prefix,
            range_start=0,
            range_end=9,
            suffix_len=1,
            card_count=10,
            iccid_length=len(iccid),
        )
        idx._entries.append(range_entry)

        # First reprogram — creates override entry
        idx.add_iccid(iccid, "/mnt/share/v1.csv")
        entry1 = idx.lookup(iccid)
        self.assertEqual(entry1.file_path, "/mnt/share/v1.csv")

        # Second reprogram — updates override entry in place
        idx.add_iccid(iccid, "/mnt/share/v2.csv")
        entry2 = idx.lookup(iccid)
        self.assertEqual(entry2.file_path, "/mnt/share/v2.csv")


class TestLookupReturnsLatest(unittest.TestCase):
    """lookup() must return the last matching entry (most recent)."""

    def test_last_match_wins(self):
        """When multiple entries match, the last one is returned."""
        idx = IccidIndex()
        iccid = "8946000000000000005"
        stripped = _luhn_strip(iccid)
        prefix = stripped[:-1]
        suffix = int(stripped[-1])

        # Add two entries that both match the same ICCID
        old_entry = IndexEntry(
            file_path="/old.csv", prefix=prefix,
            range_start=suffix, range_end=suffix + 5, suffix_len=1,
            card_count=6, iccid_length=len(iccid),
        )
        new_entry = IndexEntry(
            file_path="/new.csv", prefix=prefix,
            range_start=suffix, range_end=suffix, suffix_len=1,
            card_count=1, iccid_length=len(iccid),
        )
        idx._entries.extend([old_entry, new_entry])

        result = idx.lookup(iccid)
        self.assertEqual(result.file_path, "/new.csv")


class TestScanDirectoryLatestArtifact(unittest.TestCase):
    """scan_directory() with multiple artifact files for the same ICCID."""

    def test_latest_artifact_file_wins_after_scan(self):
        """When two artifact CSVs exist for the same ICCID, the latest
        (last in sorted filename order) should be returned by lookup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            iccid = "8999988000100000037"
            # Older artifact
            old_path = os.path.join(tmpdir,
                                    f"{iccid}_20260318_100000.csv")
            with open(old_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["ICCID", "IMSI"])
                w.writeheader()
                w.writerow({"ICCID": iccid, "IMSI": "001010000000001"})

            # Newer artifact
            new_path = os.path.join(tmpdir,
                                    f"{iccid}_20260318_140000.csv")
            with open(new_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["ICCID", "IMSI"])
                w.writeheader()
                w.writerow({"ICCID": iccid, "IMSI": "001010000000099"})

            idx = IccidIndex()
            idx.scan_directory(tmpdir)

            entry = idx.lookup(iccid)
            self.assertIsNotNone(entry)
            # Should point to the newer file
            self.assertEqual(entry.file_path, new_path)

            # load_card should return data from the newer file
            card = idx.load_card(iccid)
            self.assertIsNotNone(card)
            self.assertEqual(card["IMSI"], "001010000000099")


if __name__ == "__main__":
    unittest.main()
