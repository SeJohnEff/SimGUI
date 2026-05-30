"""Tests for CardManager._verify_written_fields internal helper."""

import pytest
from unittest.mock import MagicMock, patch
from managers.card_manager import CardManager, CardType, CLIBackend


def _make_manager():
    mgr = CardManager.__new__(CardManager)
    mgr.cli_backend = CLIBackend.PYSIM
    mgr.card_info = {}
    mgr.card_type = CardType.UNKNOWN
    mgr._pcsc_reader_index = 0
    mgr._VERIFY_RETRIES = 1
    mgr._VERIFY_DELAY_S = 0
    return mgr


class TestVerifyWrittenFields:

    def test_ki_opc_classified_as_unreadable(self):
        mgr = _make_manager()
        mgr.verify_after_program = MagicMock(return_value=(True, "OK", {}))
        report = mgr._verify_written_fields({"Ki": "aabbccdd", "OPc": "11223344"})
        assert "Ki" in report.unreadable_fields
        assert "OPc" in report.unreadable_fields
        assert report.verified_fields == ()
        assert report.failed_fields == ()
        mgr.verify_after_program.assert_not_called()

    def test_readable_matching_field_in_verified(self):
        mgr = _make_manager()
        mgr.verify_after_program = MagicMock(
            return_value=(True, "OK", {"IMSI": "240010123456789"})
        )
        report = mgr._verify_written_fields({"IMSI": "240010123456789"})
        assert "IMSI" in report.verified_fields
        assert report.failed_fields == ()
        assert report.verification_error is None

    def test_readable_mismatch_in_failed(self):
        mgr = _make_manager()
        mgr.verify_after_program = MagicMock(
            return_value=(True, "OK", {"IMSI": "240010000000001"})
        )
        report = mgr._verify_written_fields({"IMSI": "240010123456789"})
        assert "IMSI" in report.failed_fields
        assert report.verified_fields == ()

    def test_readback_failure_sets_verification_error(self):
        mgr = _make_manager()
        mgr.verify_after_program = MagicMock(
            return_value=(False, "pySim-read error: Unknown error", {})
        )
        report = mgr._verify_written_fields({"IMSI": "240010123456789"})
        assert report.verification_error is not None
        assert "error" in report.verification_error.lower()
        assert report.verified_fields == ()
        assert report.failed_fields == ()

    def test_spn_absent_from_intended_not_in_report(self):
        mgr = _make_manager()
        mgr.verify_after_program = MagicMock(
            return_value=(True, "OK", {"IMSI": "240010123456789", "SPN": "TestNet"})
        )
        report = mgr._verify_written_fields({"IMSI": "240010123456789"})
        all_fields = (
            report.verified_fields + report.failed_fields + report.unreadable_fields
        )
        assert "SPN" not in all_fields

    def test_ki_opc_with_readable_field(self):
        mgr = _make_manager()
        mgr.verify_after_program = MagicMock(
            return_value=(True, "OK", {"ICCID": "8924010000000001234"})
        )
        report = mgr._verify_written_fields(
            {"Ki": "aabb", "OPc": "ccdd", "ICCID": "8924010000000001234"}
        )
        assert "Ki" in report.unreadable_fields
        assert "OPc" in report.unreadable_fields
        assert "ICCID" in report.verified_fields
