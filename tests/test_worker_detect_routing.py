"""Phase C.1b: worker detect routing tests for CardManager.detect_card.

Tests verify:
- READY + 'detect' capability -> worker used; _run_cli not called
- not READY -> fallback to _run_cli
- capability missing -> fallback to _run_cli
- worker success maps card_info, card_type, _original_card_data
- blank worker result returns blank message; _read_public_fields_via_shell not called
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_manager import CardManager, CardType, CLIBackend
from card_worker_client import DetectResult


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
    cm._current_session_id = None
    cm._current_card_gen = None
    return cm


def _mock_client(caps=None, detect_result=None, ready=True, raise_exc=None):
    client = MagicMock()
    client.is_alive.return_value = ready
    client.is_ready.return_value = ready
    client.capabilities.return_value = caps if caps is not None else ["detect_inprocess"]
    if raise_exc is not None:
        client.detect_inprocess.side_effect = raise_exc
    elif detect_result is not None:
        client.detect_inprocess.return_value = detect_result
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWorkerDetectRouting:

    def test_detect_inprocess_cap_bypasses_run_cli(self, tmp_path, monkeypatch):
        """READY + 'detect_inprocess' cap -> worker path taken; _run_cli not called."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        result = DetectResult(
            ok=True, card_type="sysmoisim-sja5", blank=False,
            fields={"ICCID": "8946220000000000001", "IMSI": "244220000000001"},
        )
        cm.set_worker_client(_mock_client(caps=["detect_inprocess"], detect_result=result))

        with patch.object(cm, "_run_cli") as mock_cli:
            with patch.object(cm, "_read_public_fields_via_shell"):
                ok, msg = cm.detect_card()

        assert ok is True
        assert msg == "Card detected via pySim"
        mock_cli.assert_not_called()

    def test_detect_only_cap_falls_back_to_run_cli(self, tmp_path, monkeypatch):
        """READY + only 'detect' cap (no detect_inprocess) -> worker skipped; legacy CLI runs."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        cm.set_worker_client(_mock_client(caps=["detect"]))

        with patch.object(cm, "_run_cli", return_value=(0, "output", "")) as mock_cli:
            with patch.object(cm, "_parse_pysim_output", return_value={}):
                cm.detect_card()

        mock_cli.assert_called_once()

    def test_not_ready_falls_back_to_run_cli(self, tmp_path, monkeypatch):
        """Worker not READY -> legacy _run_cli called; worker.detect_inprocess not called."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        client = _mock_client(caps=["detect_inprocess"], ready=False)
        cm.set_worker_client(client)

        with patch.object(cm, "_run_cli", return_value=(False, "", "no card")) as mock_cli:
            cm.detect_card()

        mock_cli.assert_called()
        client.detect_inprocess.assert_not_called()

    def test_capability_missing_falls_back_to_run_cli(self, tmp_path, monkeypatch):
        """No detect_inprocess cap -> legacy path; worker.detect_inprocess not called."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        client = _mock_client(caps=["program_full"])
        cm.set_worker_client(client)

        with patch.object(cm, "_run_cli", return_value=(False, "", "no card")) as mock_cli:
            cm.detect_card()

        mock_cli.assert_called()
        client.detect_inprocess.assert_not_called()

    def test_worker_success_maps_card_info_card_type_original_data(self, tmp_path, monkeypatch):
        """Worker ok=True -> card_info, card_type, _original_card_data correctly populated."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        fields = {"ICCID": "8946220000000000001", "IMSI": "244220000000001", "ACC": "0001"}
        result = DetectResult(ok=True, card_type="sysmoisim-sja5", blank=False, fields=fields)
        cm.set_worker_client(_mock_client(caps=["detect_inprocess"], detect_result=result))

        with patch.object(cm, "_read_public_fields_via_shell"):
            ok, _ = cm.detect_card()

        assert ok is True
        assert cm.card_type == CardType.SJA5
        assert cm.card_info["ICCID"] == "8946220000000000001"
        assert cm.card_info["IMSI"] == "244220000000001"
        assert cm._original_card_data == cm.card_info

    def test_blank_result_returns_blank_message_skips_shell_read(self, tmp_path, monkeypatch):
        """blank=True -> returns blank message; _read_public_fields_via_shell not called."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        result = DetectResult(ok=True, card_type="gialersim", blank=True, fields={})
        cm.set_worker_client(_mock_client(caps=["detect_inprocess"], detect_result=result))

        with patch.object(cm, "_read_public_fields_via_shell") as mock_shell:
            with patch.object(cm, "_run_cli") as mock_cli:
                ok, msg = cm.detect_card()

        assert ok is True
        assert msg == "Card detected via pySim (blank)"
        mock_shell.assert_not_called()
        mock_cli.assert_not_called()

    def test_worker_exception_falls_back_to_run_cli(self, tmp_path, monkeypatch):
        """Transport exception from worker.detect_inprocess -> fallback to legacy _run_cli."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        client = _mock_client(caps=["detect_inprocess"], raise_exc=RuntimeError("transport dead"))
        cm.set_worker_client(client)

        with patch.object(cm, "_run_cli", return_value=(False, "", "no card")) as mock_cli:
            cm.detect_card()

        mock_cli.assert_called()

    def test_env_var_off_falls_back_to_run_cli(self, tmp_path, monkeypatch):
        """SIMGUI_WORKER_INPROCESS=0 -> legacy path even if READY+capable."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "0")
        cm = _make_cm(tmp_path)
        result = DetectResult(ok=True, card_type="gialersim", blank=False, fields={})
        client = _mock_client(caps=["detect_inprocess"], detect_result=result)
        cm.set_worker_client(client)

        with patch.object(cm, "_run_cli", return_value=(False, "", "no card")) as mock_cli:
            cm.detect_card()

        mock_cli.assert_called()
        client.detect_inprocess.assert_not_called()
