"""Tests for managers.auto_artifact_manager — per-card CSV artifact writer."""

import csv
import os
from datetime import datetime
from unittest.mock import patch

import pytest

from managers.auto_artifact_manager import (
    AUTO_ARTIFACT_DIR,
    DEFAULT_ARTIFACT_FIELDS,
    AutoArtifactManager,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeNSManager:
    """Minimal NetworkStorageManager mock."""

    def __init__(self, mounts=None):
        self._mounts = mounts or []

    def get_active_mount_paths(self):
        return self._mounts


def _read_artifact_csv(path):
    """Read a single-row artifact CSV and return (header, row_dict)."""
    with open(path, "r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    return reader.fieldnames, rows[0] if rows else {}


# ---------------------------------------------------------------------------
# Tests for save_card_artifact
# ---------------------------------------------------------------------------

class TestSaveCardArtifact:
    def test_basic_save(self, tmp_path):
        mount = str(tmp_path / "share1")
        os.makedirs(mount)
        ns = FakeNSManager([("Share1", mount)])
        mgr = AutoArtifactManager(ns)

        card_data = {
            "ICCID": "8949440000001672706",
            "IMSI": "99988000301001",
            "Ki": "AA" * 16,
            "OPc": "BB" * 16,
            "ADM1": "88888888",
        }
        paths = mgr.save_card_artifact(card_data)

        assert len(paths) == 1
        assert os.path.isfile(paths[0])
        assert AUTO_ARTIFACT_DIR in paths[0]
        assert "8949440000001672706" in os.path.basename(paths[0])

    def test_csv_content_correct(self, tmp_path):
        mount = str(tmp_path / "share")
        os.makedirs(mount)
        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        card_data = {
            "ICCID": "1234567890123456789",
            "IMSI": "999880001000001",
            "Ki": "CC" * 16,
            "OPc": "DD" * 16,
            "ADM1": "3838383838383838",
            "ACC": "0001",
            "SPN": "BOLIDEN",
            "FPLMN": "24007;24024",
        }
        paths = mgr.save_card_artifact(card_data)
        headers, row = _read_artifact_csv(paths[0])

        assert row["ICCID"] == "1234567890123456789"
        assert row["IMSI"] == "999880001000001"
        assert row["Ki"] == "CC" * 16
        assert row["OPc"] == "DD" * 16
        assert row["ADM1"] == "3838383838383838"
        assert row["SPN"] == "BOLIDEN"
        assert "programmed_at" in row

    def test_creates_auto_artifact_dir(self, tmp_path):
        mount = str(tmp_path / "share")
        os.makedirs(mount)
        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        card_data = {"ICCID": "1111111111111111111"}
        mgr.save_card_artifact(card_data)

        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        assert os.path.isdir(artifact_dir)

    def test_filename_format(self, tmp_path):
        mount = str(tmp_path / "share")
        os.makedirs(mount)
        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        card_data = {"ICCID": "8949440000001672706"}
        paths = mgr.save_card_artifact(card_data)

        fname = os.path.basename(paths[0])
        assert fname.startswith("8949440000001672706_")
        assert fname.endswith(".csv")
        # Should contain a timestamp like 20260314_093000
        parts = fname.replace(".csv", "").split("_", 1)
        assert len(parts[1]) == 15  # YYYYMMDD_HHMMSS

    def test_multiple_shares(self, tmp_path):
        m1 = str(tmp_path / "share1")
        m2 = str(tmp_path / "share2")
        os.makedirs(m1)
        os.makedirs(m2)
        ns = FakeNSManager([("Share1", m1), ("Share2", m2)])
        mgr = AutoArtifactManager(ns)

        card_data = {"ICCID": "2222222222222222222"}
        paths = mgr.save_card_artifact(card_data)

        assert len(paths) == 2
        assert any("share1" in p for p in paths)
        assert any("share2" in p for p in paths)

    def test_no_ns_manager(self):
        mgr = AutoArtifactManager(None)
        paths = mgr.save_card_artifact({"ICCID": "123"})
        assert paths == []

    def test_no_active_mounts(self):
        ns = FakeNSManager([])
        mgr = AutoArtifactManager(ns)
        paths = mgr.save_card_artifact({"ICCID": "123"})
        assert paths == []

    def test_empty_iccid(self, tmp_path):
        mount = str(tmp_path / "share")
        os.makedirs(mount)
        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        paths = mgr.save_card_artifact({"ICCID": ""})
        assert paths == []

    def test_no_iccid_key(self, tmp_path):
        mount = str(tmp_path / "share")
        os.makedirs(mount)
        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        paths = mgr.save_card_artifact({"IMSI": "123"})
        assert paths == []

    def test_custom_fields(self, tmp_path):
        mount = str(tmp_path / "share")
        os.makedirs(mount)
        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        card_data = {"ICCID": "3333333333333333333", "Ki": "FF" * 16}
        paths = mgr.save_card_artifact(
            card_data, fields=["ICCID", "Ki"])

        headers, row = _read_artifact_csv(paths[0])
        assert "ICCID" in headers
        assert "Ki" in headers
        # Default fields like IMSI should NOT be present
        assert "IMSI" not in headers or row.get("IMSI", "") == ""

    def test_extra_meta(self, tmp_path):
        mount = str(tmp_path / "share")
        os.makedirs(mount)
        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        card_data = {"ICCID": "4444444444444444444"}
        paths = mgr.save_card_artifact(
            card_data,
            extra_meta={"source_file": "batch.eml", "operator": "john"},
        )

        _, row = _read_artifact_csv(paths[0])
        assert row["source_file"] == "batch.eml"
        assert row["operator"] == "john"

    def test_default_fields_list(self):
        """Verify the default fields match the expected set."""
        assert "ICCID" in DEFAULT_ARTIFACT_FIELDS
        assert "IMSI" in DEFAULT_ARTIFACT_FIELDS
        assert "Ki" in DEFAULT_ARTIFACT_FIELDS
        assert "OPc" in DEFAULT_ARTIFACT_FIELDS
        assert "ADM1" in DEFAULT_ARTIFACT_FIELDS

    def test_write_failure_does_not_raise(self, tmp_path):
        """If the mount path is read-only, save fails gracefully."""
        mount = str(tmp_path / "readonly_share")
        os.makedirs(mount)
        # Make it read-only
        os.chmod(mount, 0o444)
        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        try:
            paths = mgr.save_card_artifact({"ICCID": "5555555555555555555"})
            assert paths == []  # Fails gracefully
        finally:
            os.chmod(mount, 0o755)  # Restore permissions

    def test_multiple_cards_unique_files(self, tmp_path):
        """Two cards produce two separate files."""
        mount = str(tmp_path / "share")
        os.makedirs(mount)
        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        p1 = mgr.save_card_artifact({"ICCID": "AAAA1111111111111"})
        p2 = mgr.save_card_artifact({"ICCID": "BBBB2222222222222"})

        assert len(p1) == 1
        assert len(p2) == 1
        assert p1[0] != p2[0]

        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        files = os.listdir(artifact_dir)
        assert len(files) == 2


# ---------------------------------------------------------------------------
# Tests for find_existing_artifacts
# ---------------------------------------------------------------------------

class TestFindExistingArtifacts:
    def test_finds_matching_files(self, tmp_path):
        mount = str(tmp_path / "share")
        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        os.makedirs(artifact_dir)

        # Create some artifact files
        for ts in ["20260314_100000", "20260314_110000"]:
            path = os.path.join(artifact_dir, f"ICCID_A_{ts}.csv")
            with open(path, "w") as f:
                f.write("ICCID\nICCID_A\n")

        # Also a different ICCID
        other = os.path.join(artifact_dir, "ICCID_B_20260314_120000.csv")
        with open(other, "w") as f:
            f.write("ICCID\nICCID_B\n")

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        found = mgr.find_existing_artifacts("ICCID_A")
        assert len(found) == 2
        assert all("ICCID_A" in f for f in found)

    def test_no_matches(self, tmp_path):
        mount = str(tmp_path / "share")
        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        os.makedirs(artifact_dir)

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        assert mgr.find_existing_artifacts("NONEXISTENT") == []

    def test_no_artifact_dir(self, tmp_path):
        mount = str(tmp_path / "share")
        os.makedirs(mount)  # No auto-artifact subdir

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        assert mgr.find_existing_artifacts("ICCID_X") == []

    def test_no_ns_manager(self):
        mgr = AutoArtifactManager(None)
        assert mgr.find_existing_artifacts("ICCID_X") == []

    def test_across_multiple_shares(self, tmp_path):
        m1 = str(tmp_path / "share1")
        m2 = str(tmp_path / "share2")
        for m in [m1, m2]:
            d = os.path.join(m, AUTO_ARTIFACT_DIR)
            os.makedirs(d)
            path = os.path.join(d, "ICCID_C_20260314_100000.csv")
            with open(path, "w") as f:
                f.write("ICCID\nICCID_C\n")

        ns = FakeNSManager([("Share1", m1), ("Share2", m2)])
        mgr = AutoArtifactManager(ns)

        found = mgr.find_existing_artifacts("ICCID_C")
        assert len(found) == 2


# ---------------------------------------------------------------------------
# Tests for was_already_programmed
# ---------------------------------------------------------------------------

class TestWasAlreadyProgrammed:
    def test_true_when_artifact_exists(self, tmp_path):
        mount = str(tmp_path / "share")
        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        os.makedirs(artifact_dir)
        path = os.path.join(artifact_dir, "ICCID_D_20260314_100000.csv")
        with open(path, "w") as f:
            f.write("ICCID\nICCID_D\n")

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        assert mgr.was_already_programmed("ICCID_D") is True

    def test_false_when_no_artifact(self, tmp_path):
        mount = str(tmp_path / "share")
        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        os.makedirs(artifact_dir)

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        assert mgr.was_already_programmed("ICCID_MISSING") is False

    def test_false_with_no_manager(self):
        mgr = AutoArtifactManager(None)
        assert mgr.was_already_programmed("ICCID_X") is False


# ---------------------------------------------------------------------------
# Tests for get_previous_programming_info
# ---------------------------------------------------------------------------

class TestGetPreviousProgrammingInfo:
    def _write_artifact(self, artifact_dir, iccid, timestamp, imsi="999880001000001"):
        """Write a minimal artifact CSV and return its path."""
        fname = f"{iccid}_{timestamp}.csv"
        path = os.path.join(artifact_dir, fname)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["ICCID", "IMSI", "ADM1", "programmed_at"])
            writer.writeheader()
            writer.writerow({
                "ICCID": iccid,
                "IMSI": imsi,
                "ADM1": "3838383838383838",
                "programmed_at": f"2026-03-14T{timestamp.split('_')[1][:2]}:00:00",
            })
        return path

    def test_returns_none_when_no_artifact(self, tmp_path):
        mount = str(tmp_path / "share")
        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        os.makedirs(artifact_dir)

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        assert mgr.get_previous_programming_info("ICCID_MISSING") is None

    def test_returns_none_with_no_manager(self):
        mgr = AutoArtifactManager(None)
        assert mgr.get_previous_programming_info("ICCID_X") is None

    def test_returns_data_from_single_artifact(self, tmp_path):
        mount = str(tmp_path / "share")
        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        os.makedirs(artifact_dir)

        self._write_artifact(artifact_dir, "ICCID_E", "20260314_100000", imsi="111222333")

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        info = mgr.get_previous_programming_info("ICCID_E")
        assert info is not None
        assert info["ICCID"] == "ICCID_E"
        assert info["IMSI"] == "111222333"
        assert "programmed_at" in info
        assert "_artifact_path" in info

    def test_returns_most_recent_artifact(self, tmp_path):
        mount = str(tmp_path / "share")
        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        os.makedirs(artifact_dir)

        self._write_artifact(artifact_dir, "ICCID_F", "20260314_090000", imsi="OLD_IMSI")
        self._write_artifact(artifact_dir, "ICCID_F", "20260314_150000", imsi="NEW_IMSI")

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        info = mgr.get_previous_programming_info("ICCID_F")
        assert info is not None
        assert info["IMSI"] == "NEW_IMSI"  # Must be the later one

    def test_returns_none_for_empty_iccid(self, tmp_path):
        mount = str(tmp_path / "share")
        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        os.makedirs(artifact_dir)

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        assert mgr.get_previous_programming_info("") is None

    def test_artifact_path_included(self, tmp_path):
        mount = str(tmp_path / "share")
        artifact_dir = os.path.join(mount, AUTO_ARTIFACT_DIR)
        os.makedirs(artifact_dir)

        written_path = self._write_artifact(
            artifact_dir, "ICCID_G", "20260314_120000")

        ns = FakeNSManager([("Share", mount)])
        mgr = AutoArtifactManager(ns)

        info = mgr.get_previous_programming_info("ICCID_G")
        assert info["_artifact_path"] == written_path
