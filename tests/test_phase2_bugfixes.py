"""Tests for Phase 2 batch programming bug fixes.

Bug 1: ICCID-already-programmed check in batch flow
Bug 2: Per-card artifact saving for 2nd+ card
Bug 3: Batch summary artifact auto-save
"""

import csv
import os
import tempfile
from dataclasses import dataclass
from unittest.mock import MagicMock, call, patch

import pytest

from managers.auto_artifact_manager import AutoArtifactManager
from managers.batch_manager import CardResult
from managers.iccid_index import IccidIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_share(tmp_path):
    """Create a fake network share mount point with auto-artifact dir."""
    share = tmp_path / "share"
    share.mkdir()
    return share


@pytest.fixture
def ns_manager(tmp_share):
    """Mock NetworkStorageManager with one active mount."""
    ns = MagicMock()
    ns.get_active_mount_paths.return_value = [("TestShare", str(tmp_share))]
    return ns


@pytest.fixture
def auto_artifact(ns_manager):
    return AutoArtifactManager(ns_manager)


@pytest.fixture
def iccid_index():
    return IccidIndex()


# ---------------------------------------------------------------------------
# Bug 1: ICCID duplicate detection
# ---------------------------------------------------------------------------

class TestIccidDuplicateCheck:
    """Bug 1: Batch should detect ICCIDs already in the index."""

    def test_lookup_returns_entry_for_known_iccid(self, iccid_index):
        """add_iccid registers the ICCID so lookup finds it."""
        iccid_index.add_iccid("8999988000100000037", "/fake/file.eml")
        entry = iccid_index.lookup("8999988000100000037")
        assert entry is not None

    def test_lookup_returns_none_for_unknown_iccid(self, iccid_index):
        """Unknown ICCID returns None."""
        entry = iccid_index.lookup("8999988000100000099")
        assert entry is None

    def test_batch_panel_warns_for_duplicate_iccids(self):
        """_check_iccid_index_duplicates logs warnings for known ICCIDs."""
        idx = IccidIndex()
        idx.add_iccid("8999988000100000037", "/fake/file.eml")

        # Create a minimal mock panel to test the method
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        panel._iccid_index = idx
        panel._preview_data = [
            {"ICCID": "8999988000100000037", "IMSI": "111"},
            {"ICCID": "8999988000100000099", "IMSI": "222"},
        ]
        log_calls = []
        panel._log = lambda msg: log_calls.append(msg)

        # Call the actual method
        BatchProgramPanel._check_iccid_index_duplicates(panel)

        assert len(log_calls) == 1
        assert "8999988000100000037" in log_calls[0]
        assert "already programmed" in log_calls[0]

    def test_no_warning_when_no_index(self):
        """No warnings when iccid_index is None."""
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        panel._iccid_index = None
        panel._preview_data = [{"ICCID": "123"}]
        log_calls = []
        panel._log = lambda msg: log_calls.append(msg)

        BatchProgramPanel._check_iccid_index_duplicates(panel)
        assert len(log_calls) == 0

    def test_no_warning_for_fresh_batch(self):
        """No warnings when none of the ICCIDs are in the index."""
        idx = IccidIndex()
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        panel._iccid_index = idx
        panel._preview_data = [
            {"ICCID": "8999988000100000037"},
            {"ICCID": "8999988000100000038"},
        ]
        log_calls = []
        panel._log = lambda msg: log_calls.append(msg)

        BatchProgramPanel._check_iccid_index_duplicates(panel)
        assert len(log_calls) == 0


# ---------------------------------------------------------------------------
# Bug 2: Per-card artifact saving
# ---------------------------------------------------------------------------

class TestPerCardArtifact:
    """Bug 2: Each successful card in batch gets an artifact."""

    def test_save_card_artifact_creates_file(self, auto_artifact, tmp_share):
        """save_card_artifact writes a CSV to the share."""
        card_data = {
            "ICCID": "8999988000100000037",
            "IMSI": "999880001000001",
            "Ki": "aabbccdd",
            "OPc": "11223344",
            "ADM1": "3838383838383838",
        }
        paths = auto_artifact.save_card_artifact(card_data)
        assert len(paths) == 1
        assert os.path.exists(paths[0])
        # Check file content
        with open(paths[0], newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["ICCID"] == "8999988000100000037"
        assert rows[0]["IMSI"] == "999880001000001"

    def test_save_per_card_artifact_calls_manager(self):
        """_save_per_card_artifact calls auto_artifact_manager and iccid_index."""
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        mock_artifact = MagicMock()
        mock_artifact.save_card_artifact.return_value = ["/fake/artifact.csv"]
        panel._auto_artifact = mock_artifact

        mock_idx = MagicMock()
        panel._iccid_index = mock_idx

        card_data = {"ICCID": "8999988000100000037", "IMSI": "111"}

        BatchProgramPanel._save_per_card_artifact(panel, card_data)

        mock_artifact.save_card_artifact.assert_called_once_with(card_data)
        mock_idx.add_iccid.assert_called_once_with(
            "8999988000100000037", "/fake/artifact.csv")

    def test_save_per_card_artifact_skips_when_no_manager(self):
        """No error when auto_artifact_manager is None."""
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        panel._auto_artifact = None
        panel._iccid_index = None

        # Should not raise
        BatchProgramPanel._save_per_card_artifact(
            panel, {"ICCID": "123", "IMSI": "456"})

    def test_on_card_result_saves_artifact_on_success(self):
        """_on_card_result triggers artifact save when card succeeds."""
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        panel._preview_data = [
            {"ICCID": "AAA", "IMSI": "111"},
            {"ICCID": "BBB", "IMSI": "222"},
        ]
        panel.winfo_exists.return_value = True
        panel.after = MagicMock()

        result = CardResult(index=1, iccid="BBB", success=True,
                            message="Programmed successfully")

        BatchProgramPanel._on_card_result(panel, result)

        panel._save_per_card_artifact.assert_called_once_with(
            {"ICCID": "BBB", "IMSI": "222"})

    def test_on_card_result_no_artifact_on_failure(self):
        """_on_card_result does not save artifact when card fails."""
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        panel._preview_data = [{"ICCID": "AAA", "IMSI": "111"}]
        panel.winfo_exists.return_value = True
        panel.after = MagicMock()

        result = CardResult(index=0, iccid="AAA", success=False,
                            message="Auth failed")

        BatchProgramPanel._on_card_result(panel, result)

        panel._save_per_card_artifact.assert_not_called()

    def test_multiple_cards_each_get_artifact(self, auto_artifact, tmp_share):
        """Multiple calls to save_card_artifact create separate files."""
        cards = [
            {"ICCID": "8999988000100000037", "IMSI": "001"},
            {"ICCID": "8999988000100000038", "IMSI": "002"},
            {"ICCID": "8999988000100000039", "IMSI": "003"},
        ]
        all_paths = []
        for card in cards:
            paths = auto_artifact.save_card_artifact(card)
            all_paths.extend(paths)
        assert len(all_paths) == 3
        # All files exist and are distinct
        assert len(set(all_paths)) == 3
        for p in all_paths:
            assert os.path.exists(p)


# ---------------------------------------------------------------------------
# Bug 3: Batch summary artifact
# ---------------------------------------------------------------------------

class TestBatchSummaryArtifact:
    """Bug 3: Auto-save batch summary CSV after batch completes."""

    def test_save_batch_summary_creates_file(self, auto_artifact, tmp_share):
        """save_batch_summary writes a summary CSV with key card fields."""
        records = [
            {
                "ICCID": "8999988000100000037",
                "ADM1": "3838383838383838",
                "IMSI": "001010000000001",
                "Ki": "AABBCCDD" * 4,
                "OPc": "11223344" * 4,
            },
            {
                "ICCID": "8999988000100000038",
                "ADM1": "3838383838383838",
                "IMSI": "001010000000002",
                "Ki": "EEFF0011" * 4,
                "OPc": "55667788" * 4,
            },
        ]
        results = [
            CardResult(0, "8999988000100000037", True, "Programmed successfully"),
            CardResult(1, "8999988000100000038", True, "Programmed successfully"),
        ]
        paths = auto_artifact.save_batch_summary(records, results)
        assert len(paths) == 1
        assert os.path.exists(paths[0])
        assert "batch_summary_" in os.path.basename(paths[0])

        # Check content — fields: ICCID, ADM1, IMSI, Ki, OPc
        with open(paths[0], newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert len(rows) == 2
        assert list(rows[0].keys()) == ["ICCID", "ADM1", "IMSI", "Ki", "OPc"]
        assert rows[0]["ICCID"] == "8999988000100000037"
        assert rows[0]["ADM1"] == "3838383838383838"
        assert rows[0]["IMSI"] == "001010000000001"
        assert rows[0]["Ki"] == "AABBCCDD" * 4
        assert rows[0]["OPc"] == "11223344" * 4
        assert rows[1]["ICCID"] == "8999988000100000038"

    def test_save_batch_summary_no_ns_manager(self):
        """Returns empty list when no network storage manager."""
        mgr = AutoArtifactManager(ns_manager=None)
        paths = mgr.save_batch_summary([], [])
        assert paths == []

    def test_save_batch_summary_empty_results(self, auto_artifact, tmp_share):
        """Empty results produce an empty (header-only) CSV."""
        paths = auto_artifact.save_batch_summary([], [])
        assert len(paths) == 1
        with open(paths[0], newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert len(rows) == 0

    def test_batch_panel_saves_summary_on_completion(self):
        """_save_batch_summary calls auto_artifact_manager.save_batch_summary."""
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        mock_artifact = MagicMock()
        mock_artifact.save_batch_summary.return_value = ["/fake/summary.csv"]
        panel._auto_artifact = mock_artifact

        mock_batch_mgr = MagicMock()
        mock_batch_mgr.results = [
            CardResult(0, "AAA", True, "OK"),
            CardResult(1, "BBB", False, "FAIL"),
        ]
        panel._batch_mgr = mock_batch_mgr

        records = [{"ICCID": "AAA", "IMSI": "111"}]
        panel.get_programmed_records = MagicMock(return_value=records)

        BatchProgramPanel._save_batch_summary(panel)

        mock_artifact.save_batch_summary.assert_called_once_with(
            records, mock_batch_mgr.results)

    def test_batch_panel_skips_summary_when_no_manager(self):
        """No error when auto_artifact_manager is None."""
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        panel._auto_artifact = None

        # Should not raise
        BatchProgramPanel._save_batch_summary(panel)

    def test_batch_panel_skips_summary_when_no_results(self):
        """No summary saved when batch has no results."""
        from widgets.batch_program_panel import BatchProgramPanel

        panel = MagicMock(spec=BatchProgramPanel)
        mock_artifact = MagicMock()
        panel._auto_artifact = mock_artifact
        panel._batch_mgr = MagicMock()
        panel._batch_mgr.results = []
        panel.get_programmed_records = MagicMock(return_value=[])

        BatchProgramPanel._save_batch_summary(panel)

        mock_artifact.save_batch_summary.assert_not_called()
