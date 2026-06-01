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

import pytest

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


def _mock_client(caps=None, program_full_resp=None, ready=True, raise_exc=None):
    client = MagicMock()
    client.is_alive.return_value = ready
    client.is_ready.return_value = ready
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

    def test_worker_not_ready_skips_worker(self, tmp_path, monkeypatch):
        """Client is_ready()=False -> falls back to subprocess even with env+capability."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        client = _mock_client(caps=["program_full"], ready=False)
        cm.set_worker_client(client)

        with patch.object(cm, "_run_pysim_prog", return_value=(True, "Done", "")) as mock_proc:
            with patch.object(cm, "_verify_written_fields", return_value=_good_verify_report()):
                ok, _ = cm._program_via_pysim_prog({"IMSI": "001010123456789"})

        mock_proc.assert_called_once()
        client.program_full.assert_not_called()


class TestWorkerStateTransitions:
    """Unit tests for WorkerState enum and PersistentWorkerClient state tracking."""

    def test_initial_state_is_not_started(self):
        from card_worker_client import PersistentWorkerClient, WorkerState
        client = PersistentWorkerClient(worker_script="/nonexistent")
        assert client.state == WorkerState.NOT_STARTED
        assert client.last_error is None
        assert client.is_ready() is False

    def test_state_ready_after_successful_start(self, tmp_path):
        from card_worker_client import PersistentWorkerClient, WorkerState
        import json, threading

        ready_banner = json.dumps({"event": "ready"}) + "\n"
        client = PersistentWorkerClient.__new__(PersistentWorkerClient)
        client._script = "/fake"
        client._start_timeout = 2.0
        client._process = None
        client._stderr_thread = None
        client._lock = threading.Lock()
        client._state = WorkerState.NOT_STARTED
        client._last_error = None

        fake_proc = MagicMock()
        fake_proc.stderr.readline.return_value = ready_banner.encode()
        fake_proc.stdout = MagicMock()
        fake_proc.stdin = MagicMock()

        with patch("card_worker_client.subprocess.Popen", return_value=fake_proc):
            with patch.object(
                PersistentWorkerClient,
                "_readline_with_timeout",
                return_value=ready_banner,
            ):
                client.start()

        assert client.state == WorkerState.READY
        assert client.last_error is None
        assert client.is_ready() is True

    def test_state_error_on_bad_banner(self, tmp_path):
        from card_worker_client import PersistentWorkerClient, WorkerState, WorkerStartError
        import threading

        client = PersistentWorkerClient.__new__(PersistentWorkerClient)
        client._script = "/fake"
        client._start_timeout = 2.0
        client._process = None
        client._stderr_thread = None
        client._lock = threading.Lock()
        client._state = WorkerState.NOT_STARTED
        client._last_error = None

        fake_proc = MagicMock()
        fake_proc.stdin = MagicMock()

        with patch("card_worker_client.subprocess.Popen", return_value=fake_proc):
            with patch.object(
                PersistentWorkerClient,
                "_readline_with_timeout",
                return_value=None,  # timeout
            ):
                with pytest.raises(WorkerStartError):
                    client.start()

        assert client.state == WorkerState.ERROR
        assert client.last_error is not None
        assert client.is_ready() is False

    def test_state_stopped_after_stop(self):
        from card_worker_client import PersistentWorkerClient, WorkerState
        import threading

        client = PersistentWorkerClient.__new__(PersistentWorkerClient)
        client._script = "/fake"
        client._start_timeout = 2.0
        client._process = None
        client._stderr_thread = None
        client._lock = threading.Lock()
        client._state = WorkerState.NOT_STARTED
        client._last_error = None

        client.stop()  # stop with no process
        assert client.state == WorkerState.STOPPED

    def test_cardmanager_skips_worker_when_not_ready(self, tmp_path, monkeypatch):
        """CardManager checks is_ready(), not is_alive() — NOT_STARTED client skips worker."""
        import pytest
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        from card_worker_client import PersistentWorkerClient, WorkerState
        import threading

        # Build a real client stuck in NOT_STARTED (never started)
        real_client = PersistentWorkerClient.__new__(PersistentWorkerClient)
        real_client._script = "/fake"
        real_client._start_timeout = 2.0
        real_client._process = None
        real_client._stderr_thread = None
        real_client._lock = threading.Lock()
        real_client._state = WorkerState.NOT_STARTED
        real_client._last_error = None

        cm.set_worker_client(real_client)
        assert real_client.is_ready() is False

        with patch.object(cm, "_run_pysim_prog", return_value=(True, "Done", "")) as mock_proc:
            with patch.object(cm, "_verify_written_fields", return_value=_good_verify_report()):
                ok, _ = cm._program_via_pysim_prog({"IMSI": "001010123456789"})

        mock_proc.assert_called_once()
        assert ok is True


# ---------------------------------------------------------------------------
# Tests: program_delta routing through CardManager
# ---------------------------------------------------------------------------

def _make_cm_nonempty(tmp_path):
    """CardManager configured for a non-empty SJA5 card."""
    cm = _make_cm(tmp_path)
    cm.card_type = CardType.SJA5
    cm._original_card_data = {"ICCID": "8946080000000000001", "IMSI": "001010000000001"}
    cm._current_session_id = "sess-abc"
    cm._current_card_gen = 1
    return cm


def _mock_delta_client(supported_fields=None, delta_resp=None, ready=True):
    client = MagicMock()
    client.is_ready.return_value = ready
    if supported_fields is None:
        supported_fields = ["FPLMN", "IMSI"]
    client.capabilities.return_value = ["program_delta", "program_delta_capabilities"]
    client.program_delta_capabilities.return_value = supported_fields
    if delta_resp is not None:
        client.program_delta.return_value = delta_resp
    return client


class TestDeltaWorkerRouting:

    def _changed(self):
        return {"IMSI": "001010000000002"}

    def test_routes_to_worker_when_env_caps_session_valid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm_nonempty(tmp_path)
        client = _mock_delta_client(delta_resp={
            "ok": True, "write_started": True,
            "written_fields": ["IMSI"], "failed_fields": [], "error": None,
            "worker_error": False,
        })
        cm.set_worker_client(client)
        with patch.object(cm, "_run_pysim_shell") as mock_shell:
            result = cm._try_worker_program_delta(self._changed())
        assert result is not None
        assert result[0] is True
        # result[1] is the written_fields list, not a message string
        assert "IMSI" in result[1]
        mock_shell.assert_not_called()
        client.program_delta.assert_called_once()

    def test_worker_delta_success_calls_verify_not_pysim_shell(self, tmp_path, monkeypatch):
        """Worker write success routes to readback verification, not pySim-shell."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm_nonempty(tmp_path)
        client = _mock_delta_client(delta_resp={
            "ok": True, "write_started": True,
            "written_fields": ["IMSI"], "failed_fields": [], "error": None,
            "worker_error": False,
        })
        cm.set_worker_client(client)
        with patch.object(cm, "_run_pysim_shell") as mock_shell, \
             patch.object(cm, "_verify_written_fields",
                          return_value=_good_verify_report()) as mock_verify:
            ok, _ = cm._program_nonempty_card({}, {"IMSI": "001010000000002"})
        mock_shell.assert_not_called()
        mock_verify.assert_called_once()
        assert ok is True

    def test_worker_delta_success_produces_write_ok_verified_after_verify(self, tmp_path, monkeypatch):
        """Outcome is WRITE_OK_VERIFIED only after successful readback."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm_nonempty(tmp_path)
        client = _mock_delta_client(delta_resp={
            "ok": True, "write_started": True,
            "written_fields": ["IMSI"], "failed_fields": [], "error": None,
            "worker_error": False,
        })
        cm.set_worker_client(client)
        with patch.object(cm, "_verify_written_fields",
                          return_value=_good_verify_report()):
            ok, _ = cm._program_nonempty_card({}, {"IMSI": "001010000000002"})
        from state_manager import ProgramOutcome
        assert ok is True
        assert cm.get_last_program_result().outcome == ProgramOutcome.WRITE_OK_VERIFIED

    def test_worker_delta_success_verify_fail_produces_verification_failed(self, tmp_path, monkeypatch):
        """Verification failure after worker write produces WRITE_OK_VERIFICATION_FAILED."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm_nonempty(tmp_path)
        client = _mock_delta_client(delta_resp={
            "ok": True, "write_started": True,
            "written_fields": ["IMSI"], "failed_fields": [], "error": None,
            "worker_error": False,
        })
        cm.set_worker_client(client)
        with patch.object(cm, "_verify_written_fields",
                          return_value=_failed_verify_report()):
            ok, _ = cm._program_nonempty_card({}, {"IMSI": "001010000000002"})
        from state_manager import ProgramOutcome
        assert ok is False
        assert cm.get_last_program_result().outcome == ProgramOutcome.WRITE_OK_VERIFICATION_FAILED

    def test_falls_back_env_off(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SIMGUI_WORKER_INPROCESS", raising=False)
        cm = _make_cm_nonempty(tmp_path)
        cm.set_worker_client(_mock_delta_client())
        assert cm._try_worker_program_delta(self._changed()) is None

    def test_falls_back_cap_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm_nonempty(tmp_path)
        client = MagicMock()
        client.is_ready.return_value = True
        client.capabilities.return_value = []
        cm.set_worker_client(client)
        assert cm._try_worker_program_delta(self._changed()) is None

    def test_falls_back_unsupported_field(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm_nonempty(tmp_path)
        client = _mock_delta_client(supported_fields=["FPLMN"])  # no IMSI
        cm.set_worker_client(client)
        assert cm._try_worker_program_delta({"IMSI": "001010000000002"}) is None

    def test_falls_back_pre_write_failure_write_started_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm_nonempty(tmp_path)
        client = _mock_delta_client(delta_resp={
            "ok": False, "write_started": False,
            "written_fields": [], "failed_fields": [], "error": "STALE_SESSION",
            "worker_error": False,
        })
        cm.set_worker_client(client)
        assert cm._try_worker_program_delta(self._changed()) is None

    def test_no_fallback_write_started_true_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm_nonempty(tmp_path)
        client = _mock_delta_client(delta_resp={
            "ok": False, "write_started": True,
            "written_fields": [], "failed_fields": ["IMSI"], "error": "SW_IMSI=6982",
            "worker_error": False,
        })
        cm.set_worker_client(client)
        result = cm._try_worker_program_delta(self._changed())
        assert result is not None   # definitive failure returned, not None
        assert result[0] is False   # ok=False

    def test_falls_back_no_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm_nonempty(tmp_path)
        cm._current_session_id = None
        cm.set_worker_client(_mock_delta_client())
        assert cm._try_worker_program_delta(self._changed()) is None
