"""Phase C.2a: CardManager routing preference for detect_inprocess capability.

Tests verify:
- capabilities include 'detect_inprocess' + 'detect' -> client.detect_inprocess called, not client.detect
- success result mapped correctly; _run_cli not called
- only 'detect' cap (no detect_inprocess) -> client.detect called, not detect_inprocess
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_manager import CardManager, CardType, CLIBackend
from card_worker_client import DetectResult


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


def _make_client(caps, detect_result):
    client = MagicMock()
    client.is_alive.return_value = True
    client.is_ready.return_value = True
    client.capabilities.return_value = caps
    client.detect.return_value = detect_result
    client.detect_inprocess.return_value = detect_result
    return client


class TestDetectInprocessRouting:

    def test_detect_inprocess_preferred_when_both_caps_present(self, tmp_path, monkeypatch):
        """detect_inprocess + detect caps -> client.detect_inprocess used; detect not called."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        result = DetectResult(
            ok=True, card_type="sysmoisim-sja5", blank=False,
            fields={"ICCID": "8946220000000000001", "IMSI": "244220000000001"},
        )
        client = _make_client(caps=["detect", "detect_inprocess"], detect_result=result)
        cm.set_worker_client(client)

        with patch.object(cm, "_run_cli") as mock_cli:
            with patch.object(cm, "_read_public_fields_via_shell"):
                ok, msg = cm.detect_card()

        assert ok is True
        assert msg == "Card detected via pySim"
        client.detect_inprocess.assert_called_once()
        client.detect.assert_not_called()
        mock_cli.assert_not_called()

    def test_detect_inprocess_maps_card_type_and_fields(self, tmp_path, monkeypatch):
        """detect_inprocess success sets card_type, card_info, _original_card_data."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        result = DetectResult(
            ok=True, card_type="sysmoisim-sja5", blank=False,
            fields={"ICCID": "8946220000000000001", "IMSI": "244220000000001"},
        )
        client = _make_client(caps=["detect_inprocess"], detect_result=result)
        cm.set_worker_client(client)

        with patch.object(cm, "_read_public_fields_via_shell"):
            ok, _ = cm.detect_card()

        assert ok is True
        assert cm.card_type == CardType.SJA5
        assert cm.card_info["ICCID"] == "8946220000000000001"
        assert cm._original_card_data == cm.card_info

    def test_detect_used_when_only_detect_cap_present(self, tmp_path, monkeypatch):
        """Only 'detect' cap (no detect_inprocess) -> client.detect called; detect_inprocess not called."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        result = DetectResult(ok=True, card_type="gialersim", blank=True, fields={})
        client = _make_client(caps=["detect"], detect_result=result)
        cm.set_worker_client(client)

        with patch.object(cm, "_run_cli") as mock_cli:
            ok, msg = cm.detect_card()

        assert ok is True
        assert msg == "Card detected via pySim (blank)"
        client.detect.assert_called_once()
        client.detect_inprocess.assert_not_called()
        mock_cli.assert_not_called()

    def test_public_fields_shell_skipped_when_worker_returns_all_three(self, tmp_path, monkeypatch):
        """_read_public_fields_via_shell not called when SPN+ACC+FPLMN all present in worker result."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        result = DetectResult(
            ok=True, card_type="sysmoisim-sja5", blank=False,
            fields={"ICCID": "8946220000000000001", "IMSI": "244220000000001",
                    "SPN": "TestNet", "ACC": "0001", "FPLMN": ""},
        )
        client = _make_client(caps=["detect_inprocess"], detect_result=result)
        cm.set_worker_client(client)

        with patch.object(cm, "_read_public_fields_via_shell") as mock_shell:
            ok, _ = cm.detect_card()

        assert ok is True
        mock_shell.assert_not_called()

    def test_public_fields_shell_called_when_worker_missing_a_field(self, tmp_path, monkeypatch):
        """_read_public_fields_via_shell called when any of SPN/ACC/FPLMN absent in worker result."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        cm = _make_cm(tmp_path)
        result = DetectResult(
            ok=True, card_type="sysmoisim-sja5", blank=False,
            fields={"ICCID": "8946220000000000001", "IMSI": "244220000000001", "SPN": "TestNet"},
        )
        client = _make_client(caps=["detect_inprocess"], detect_result=result)
        cm.set_worker_client(client)

        with patch.object(cm, "_read_public_fields_via_shell") as mock_shell:
            ok, _ = cm.detect_card()

        assert ok is True
        mock_shell.assert_called_once()
