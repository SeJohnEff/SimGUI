"""Tests for CardManager._verify_written_fields internal helper."""

import pytest
from unittest.mock import MagicMock, patch
from managers.card_manager import CardManager, CardType, CLIBackend


from state_manager import ProgramOutcome, ProgramResult


def _make_manager():
    mgr = CardManager.__new__(CardManager)
    mgr.cli_backend = CLIBackend.PYSIM
    mgr.card_info = {}
    mgr.card_type = CardType.UNKNOWN
    mgr._pcsc_reader_index = 0
    mgr._VERIFY_RETRIES = 1
    mgr._VERIFY_DELAY_S = 0
    mgr._last_program_result = ProgramResult()
    mgr._authenticated_adm1_hex = None
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


class TestProgramViaPysimProg:
    """Tests for _program_via_pysim_prog outcome mapping."""

    def _prog(self, mgr, fields, run_ok=True, run_stderr="",
              readback_ok=True, readback_data=None):
        """Patch _run_pysim_prog and verify_after_program, call the method."""
        readback_data = readback_data or {}
        mgr._run_pysim_prog = MagicMock(return_value=(run_ok, "", run_stderr))
        mgr.verify_after_program = MagicMock(
            return_value=(readback_ok, "OK" if readback_ok else "read error", readback_data)
        )
        return mgr._program_via_pysim_prog(fields)

    def test_verified_outcome_and_ok_true(self):
        mgr = _make_manager()
        ok, msg = self._prog(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "240010123456789"},
        )
        assert ok is True
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_OK_VERIFIED
        assert "verified" in msg

    def test_ki_opc_in_written_only_fields(self):
        mgr = _make_manager()
        ok, msg = self._prog(
            mgr, {"Ki": "aabb", "OPc": "ccdd", "IMSI": "240010123456789"},
            readback_data={"IMSI": "240010123456789"},
        )
        assert ok is True
        r = mgr._last_program_result
        assert "Ki" in r.written_only_fields
        assert "OPc" in r.written_only_fields

    def test_ki_opc_only_maps_to_pending(self):
        mgr = _make_manager()
        ok, msg = self._prog(mgr, {"Ki": "aabb", "OPc": "ccdd"})
        assert ok is True
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_OK_PENDING
        assert "Verification pending" in msg

    def test_mismatch_write_ok_verification_failed_and_ok_false(self):
        mgr = _make_manager()
        ok, msg = self._prog(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "999999999999999"},
        )
        assert ok is False
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_OK_VERIFICATION_FAILED
        assert "verification mismatch" in msg
        assert "IMSI" in msg

    def test_readback_error_maps_to_pending_ok_true(self):
        mgr = _make_manager()
        ok, msg = self._prog(
            mgr, {"IMSI": "240010123456789"},
            readback_ok=False, readback_data={},
        )
        assert ok is True
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_OK_PENDING

    def test_spn_in_skipped_fields(self):
        mgr = _make_manager()
        ok, msg = self._prog(
            mgr, {"IMSI": "240010123456789", "SPN": "TestNet"},
            readback_data={"IMSI": "240010123456789"},
        )
        assert ok is True
        assert "SPN" in mgr._last_program_result.skipped_fields

    def test_write_failure_write_failed_and_ok_false(self):
        mgr = _make_manager()
        ok, msg = self._prog(
            mgr, {"IMSI": "240010123456789"},
            run_ok=False, run_stderr="some error",
        )
        assert ok is False
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_FAILED

    def test_tool_not_found_still_write_failed(self):
        mgr = _make_manager()
        ok, msg = self._prog(
            mgr, {"IMSI": "240010123456789"},
            run_ok=False, run_stderr="pySim-prog.py not found",
        )
        assert ok is False
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_FAILED
        assert "not found" in msg

    def test_card_info_updated_on_verified(self):
        mgr = _make_manager()
        self._prog(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "240010123456789", "ICCID": "8924010000000001234"},
        )
        assert mgr.card_info.get("IMSI") == "240010123456789"
        assert mgr.card_info.get("ICCID") == "8924010000000001234"

    def test_card_info_not_updated_on_mismatch(self):
        mgr = _make_manager()
        mgr.card_info = {"IMSI": "original"}
        self._prog(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "999999999999999"},
        )
        assert mgr.card_info.get("IMSI") == "original"

    def test_no_double_verify_after_program_on_verified(self):
        mgr = _make_manager()
        self._prog(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "240010123456789"},
        )
        # verify_after_program called exactly once (inside _verify_written_fields)
        assert mgr.verify_after_program.call_count == 1


class TestProgramNonemptyCard:
    """Tests for _program_nonempty_card (delta programming path) ProgramResult mapping."""

    def _delta(self, mgr, changed, shell_ok=True, shell_stdout="", shell_stderr="",
               readback_ok=True, readback_data=None):
        readback_data = readback_data or {}
        mgr._run_pysim_shell = MagicMock(return_value=(shell_ok, shell_stdout, shell_stderr))
        mgr._pysim_write_imsi = MagicMock(return_value=["cmd_imsi"])
        mgr._pysim_write_fplmn = MagicMock(return_value=["cmd_fplmn"])
        mgr._clean_pysim_error = MagicMock(return_value="error detail")
        mgr.check_adm1_retry_counter = MagicMock(return_value=3)
        mgr.verify_after_program = MagicMock(
            return_value=(readback_ok, "OK" if readback_ok else "read error", readback_data)
        )
        return mgr._program_nonempty_card({}, changed)

    def test_no_programmable_fields_no_changes(self):
        mgr = _make_manager()
        mgr._run_pysim_shell = MagicMock()
        ok, msg = mgr._program_nonempty_card({}, {})
        assert ok is True
        assert mgr._last_program_result.outcome == ProgramOutcome.NO_CHANGES
        mgr._run_pysim_shell.assert_not_called()

    def test_ki_opc_only_in_changed_is_no_changes(self):
        mgr = _make_manager()
        mgr._run_pysim_shell = MagicMock()
        ok, msg = mgr._program_nonempty_card({}, {"Ki": "aabb", "OPc": "ccdd"})
        assert ok is True
        assert mgr._last_program_result.outcome == ProgramOutcome.NO_CHANGES
        mgr._run_pysim_shell.assert_not_called()

    def test_verified_write_ok_verified_ok_true(self):
        mgr = _make_manager()
        ok, msg = self._delta(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "240010123456789"},
        )
        assert ok is True
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_OK_VERIFIED
        assert "IMSI" in mgr._last_program_result.verified_fields
        assert "verified" in msg

    def test_verification_error_maps_to_pending_ok_true(self):
        mgr = _make_manager()
        ok, msg = self._delta(
            mgr, {"IMSI": "240010123456789"},
            readback_ok=False, readback_data={},
        )
        assert ok is True
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_OK_PENDING

    def test_readback_mismatch_maps_to_verification_failed_ok_false(self):
        mgr = _make_manager()
        ok, msg = self._delta(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "999999999999999"},
        )
        assert ok is False
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_OK_VERIFICATION_FAILED
        assert "verification mismatch" in msg
        assert "IMSI" in msg

    def test_auth_failure_shell_output_maps_to_write_failed(self):
        mgr = _make_manager()
        ok, msg = self._delta(
            mgr, {"IMSI": "240010123456789"},
            shell_ok=False, shell_stdout="failed to verify adm1",
        )
        assert ok is False
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_FAILED
        assert "ABORTED" in msg or "ADM1" in msg

    def test_tries_left_shell_output_maps_to_write_failed(self):
        mgr = _make_manager()
        ok, msg = self._delta(
            mgr, {"IMSI": "240010123456789"},
            shell_ok=False, shell_stdout="3 tries left",
        )
        assert ok is False
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_FAILED

    def test_sw_mismatch_maps_to_write_failed(self):
        mgr = _make_manager()
        ok, msg = self._delta(
            mgr, {"IMSI": "240010123456789"},
            shell_ok=False, shell_stderr="sw mismatch: expected 9000",
        )
        assert ok is False
        assert mgr._last_program_result.outcome == ProgramOutcome.WRITE_FAILED

    def test_ki_opc_not_passed_to_verifier(self):
        mgr = _make_manager()
        self._delta(
            mgr, {"IMSI": "240010123456789", "Ki": "aabb", "OPc": "ccdd"},
            readback_data={"IMSI": "240010123456789"},
        )
        call_args = mgr.verify_after_program.call_args[0][0]
        assert "Ki" not in call_args
        assert "OPc" not in call_args

    def test_ki_opc_absent_from_program_result_tuples(self):
        mgr = _make_manager()
        self._delta(
            mgr, {"IMSI": "240010123456789", "Ki": "aabb", "OPc": "ccdd"},
            readback_data={"IMSI": "240010123456789"},
        )
        r = mgr._last_program_result
        all_fields = r.verified_fields + r.written_only_fields + r.skipped_fields + r.failed_fields
        assert "Ki" not in all_fields
        assert "OPc" not in all_fields

    def test_card_info_updated_on_verified_success(self):
        mgr = _make_manager()
        self._delta(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "240010123456789"},
        )
        assert mgr.card_info.get("IMSI") == "240010123456789"

    def test_card_info_not_updated_on_mismatch(self):
        mgr = _make_manager()
        mgr.card_info = {"IMSI": "original"}
        self._delta(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "999999999999999"},
        )
        assert mgr.card_info.get("IMSI") == "original"

    def test_verify_after_program_not_called_directly(self):
        mgr = _make_manager()
        self._delta(
            mgr, {"IMSI": "240010123456789"},
            readback_data={"IMSI": "240010123456789"},
        )
        assert mgr.verify_after_program.call_count == 1


class TestGetLastProgramResult:
    """Tests for CardManager.get_last_program_result() accessor."""

    def test_new_manager_returns_idle(self):
        mgr = _make_manager()
        result = mgr.get_last_program_result()
        assert result.outcome == ProgramOutcome.IDLE
        assert result.message == ""

    def test_accessor_returns_latest_after_pysim_prog_verified(self):
        mgr = _make_manager()
        mgr._run_pysim_prog = MagicMock(return_value=(True, "", ""))
        mgr.verify_after_program = MagicMock(
            return_value=(True, "OK", {"IMSI": "240010123456789"})
        )
        mgr._program_via_pysim_prog({"IMSI": "240010123456789"})
        result = mgr.get_last_program_result()
        assert result.outcome == ProgramOutcome.WRITE_OK_VERIFIED
        assert "IMSI" in result.verified_fields

    def test_accessor_returns_latest_after_pysim_prog_failure(self):
        mgr = _make_manager()
        mgr._run_pysim_prog = MagicMock(return_value=(False, "", "some error"))
        mgr._program_via_pysim_prog({"IMSI": "240010123456789"})
        result = mgr.get_last_program_result()
        assert result.outcome == ProgramOutcome.WRITE_FAILED

    def test_accessor_returns_latest_after_delta_write_verified(self):
        mgr = _make_manager()
        mgr._run_pysim_shell = MagicMock(return_value=(True, "", ""))
        mgr._pysim_write_imsi = MagicMock(return_value=["cmd"])
        mgr._pysim_write_fplmn = MagicMock(return_value=[])
        mgr.verify_after_program = MagicMock(
            return_value=(True, "OK", {"IMSI": "240010123456789"})
        )
        mgr._program_nonempty_card({}, {"IMSI": "240010123456789"})
        result = mgr.get_last_program_result()
        assert result.outcome == ProgramOutcome.WRITE_OK_VERIFIED

    def test_accessor_returns_latest_after_delta_no_changes(self):
        mgr = _make_manager()
        mgr._program_nonempty_card({}, {})
        result = mgr.get_last_program_result()
        assert result.outcome == ProgramOutcome.NO_CHANGES

    def test_returned_result_is_immutable(self):
        mgr = _make_manager()
        result = mgr.get_last_program_result()
        with pytest.raises(Exception):
            result.outcome = ProgramOutcome.WRITE_FAILED
