"""Phase 2 production-spike: opt-in worker routing for _program_via_pysim_prog.

Tests verify:
- Worker success path bypasses subprocess and produces WRITE_OK_VERIFIED
- SIMGUI_WORKER_INPROCESS=0 (or absent) routes to subprocess
- Missing capability falls back to subprocess
- Transport error (exception) falls back to subprocess
- worker_error=True in response falls back to subprocess
- Card failure (ok=False, worker_error=False) does NOT fall back
- ProgramResult/ProgramOutcome mapping is preserved through the worker path
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_manager import CardManager, CardType, CLIBackend
from managers import card_manager as cm_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cm(tmp_path):
    cli_dir = tmp_path / "pysim"
    cli_dir.mkdir()
    for script in ('pySim-shell.py', 'pySim-prog.py', 'pySim-read.py'):
        (cli_dir / script).write_text("# stub")
    cm = CardManager()
    cm.cli_path = str(cli_dir)
    cm.cli_backend = CLIBackend.PYSIM
    cm._venv_python = None
    cm.card_blocked = False
    cm._adm1_remaining_attempts = None
    cm.authenticated = True
    cm._authenticated_adm1_hex = "3838383838383838"
    cm._original_card_data = {}
    cm.card_type = CardType.GIALERSIM
    return cm


def _mock_client(caps=None, program_full_resp=None, alive=True, raise_exc=None):
    client = MagicMock()
    client.is_alive.return_value = alive
    client.capabilities.return_value = caps if caps is not None else ["program_full"]
    if raise_exc is not None:
        client.program_full.side_effect = raise_exc
    elif program_full_resp is not None:
        client.program_full.return_value = program_full_resp
    return client


def _good_verify_report():
    from managers.card_manager import _VerificationReport
    return _VerificationReport(
        verified_fields=("IMSI",),
        failed_fields=(),
        unreadable_fields=(),
        verification_error=None,
        readback_data={"IMSI": "001010123456789"},
    )


def _failed_verify_report():
    from managers.card_manager import _VerificationReport
    return _VerificationReport(
        verified_fields=(),
        failed_fields=("IMSI",),
        unreadable_fields=(),
        verification_error=None,
        readback_data={},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWorkerRouting:

    def test_worker_success_path_bypasses_subprocess(self, tmp_path, monkeypatch):
        """Worker returns ok=True, worker_error=False -> subprocess not called -> WRITE_OK_VERIFIED."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        client = _mock_client(
            caps=["program_full"],
            program_full_resp={"ok": True, "stdout": "Done", "stderr": "", "worker_error": False},
        )
        cm.set_worker_client(client)

        with patch.object(cm, "_run_pysim_prog") as mock_proc:
            with patch.object(cm, "_verify_written_fields", return_value=_good_verify_report()):
                ok, msg = cm._program_via_pysim_prog({"IMSI": "001010123456789"})

        mock_proc.assert_not_called()
        assert ok is True
        from state_manager import ProgramOutcome
        assert cm.get_last_program_result().outcome == ProgramOutcome.WRITE_OK_VERIFIED

    def test_env_var_off_skips_worker(self, tmp_path, monkeypatch):
        """SIMGUI_WORKER_INPROCESS unset -> worker not consulted -> subprocess called."""
        monkeypatch.delenv("SIMGUI_WORKER_INPROCESS", raising=False)
        cm = _make_cm(tmp_path)
        client = _mock_client(caps=["program_full"])
        cm.set_worker_client(client)

        with patch.object(cm, "_run_pysim_prog", return_value=(True, "Done", "")) as mock_proc:
            with patch.object(cm, "_verify_written_fields", return_value=_good_verify_report()):
                ok, _ = cm._program_via_pysim_prog({"IMSI": "001010123456789"})

        mock_proc.assert_called_once()
        client.program_full.assert_not_called()

    def test_capability_missing_falls_back_to_subprocess(self, tmp_path, monkeypatch):
        """Worker does not advertise program_full -> subprocess called."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        client = _mock_client(caps=["ping", "detect"])
        cm.set_worker_client(client)

        with patch.object(cm, "_run_pysim_prog", return_value=(True, "Done", "")) as mock_proc:
            with patch.object(cm, "_verify_written_fields", return_value=_good_verify_report()):
                ok, _ = cm._program_via_pysim_prog({"IMSI": "001010123456789"})

        mock_proc.assert_called_once()
        client.program_full.assert_not_called()

    def test_worker_transport_error_falls_back_once(self, tmp_path, monkeypatch):
        """Worker raises exception -> fallback to subprocess."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        from card_worker_client import WorkerTimeoutError
        client = _mock_client(caps=["program_full"], raise_exc=WorkerTimeoutError("program_full", 60.0))
        cm.set_worker_client(client)

        with patch.object(cm, "_run_pysim_prog", return_value=(True, "Done", "")) as mock_proc:
            with patch.object(cm, "_verify_written_fields", return_value=_good_verify_report()):
                ok, _ = cm._program_via_pysim_prog({"IMSI": "001010123456789"})

        mock_proc.assert_called_once()

    def test_worker_error_flag_falls_back_once(self, tmp_path, monkeypatch):
        """Worker returns worker_error=True -> fallback to subprocess."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        client = _mock_client(
            caps=["program_full"],
            program_full_resp={"ok": False, "error": "PYSIM_IMPORT_FAILED", "worker_error": True},
        )
        cm.set_worker_client(client)

        with patch.object(cm, "_run_pysim_prog", return_value=(True, "Done", "")) as mock_proc:
            with patch.object(cm, "_verify_written_fields", return_value=_good_verify_report()):
                ok, _ = cm._program_via_pysim_prog({"IMSI": "001010123456789"})

        mock_proc.assert_called_once()

    def test_worker_card_failure_does_not_fallback(self, tmp_path, monkeypatch):
        """Worker returns ok=False, worker_error=False -> no subprocess fallback -> WRITE_FAILED."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        client = _mock_client(
            caps=["program_full"],
            program_full_resp={"ok": False, "stdout": "", "stderr": "Card error", "worker_error": False},
        )
        cm.set_worker_client(client)

        with patch.object(cm, "_run_pysim_prog") as mock_proc:
            ok, msg = cm._program_via_pysim_prog({"IMSI": "001010123456789"})

        mock_proc.assert_not_called()
        assert ok is False
        from state_manager import ProgramOutcome
        assert cm.get_last_program_result().outcome == ProgramOutcome.WRITE_FAILED

    def test_program_result_mapping_preserved_via_worker(self, tmp_path, monkeypatch):
        """Worker success + verification mismatch -> WRITE_OK_VERIFICATION_FAILED."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        client = _mock_client(
            caps=["program_full"],
            program_full_resp={"ok": True, "stdout": "Done", "stderr": "", "worker_error": False},
        )
        cm.set_worker_client(client)

        with patch.object(cm, "_run_pysim_prog"):
            with patch.object(cm, "_verify_written_fields", return_value=_failed_verify_report()):
                ok, msg = cm._program_via_pysim_prog({"IMSI": "001010123456789"})

        assert ok is False
        from state_manager import ProgramOutcome
        assert cm.get_last_program_result().outcome == ProgramOutcome.WRITE_OK_VERIFICATION_FAILED
