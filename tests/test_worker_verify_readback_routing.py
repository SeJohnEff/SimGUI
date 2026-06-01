"""Tests for Phase C.3a: in-process worker readback routing in verify_after_program."""

import os
import pytest
from unittest.mock import MagicMock, patch

from managers.card_manager import CardManager, CLIBackend, CardType


def _make_manager(worker_inprocess_env="1"):
    """Build a minimal CardManager wired with a mock worker client."""
    with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": worker_inprocess_env}):
        mgr = CardManager.__new__(CardManager)
        mgr.cli_backend = CLIBackend.PYSIM
        mgr.cli_path = "/opt/pysim"
        mgr._pcsc_reader_index = 0
        mgr._VERIFY_RETRIES = 2
        mgr._VERIFY_DELAY_S = 0.0
        mgr.card_info = {"ICCID": "1234", "IMSI": "5678"}
        mgr._current_session_id = "sess-1"
        mgr._current_card_gen = 1
        mgr._cached_worker_capabilities = ["detect_inprocess", "program_full"]
        return mgr


def _ready_client(fields):
    """Return a mock client whose detect_inprocess returns the given fields."""
    client = MagicMock()
    client.is_ready.return_value = True
    result = MagicMock()
    result.ok = True
    result.fields = fields
    client.detect_inprocess.return_value = result
    return client


# ---------------------------------------------------------------------------
# _try_worker_readback_fields
# ---------------------------------------------------------------------------

class TestTryWorkerReadbackFields:
    def test_returns_fields_on_success(self):
        mgr = _make_manager()
        fields = {"ICCID": "891460000000000001", "IMSI": "240010000000001"}
        mgr._worker_client = _ready_client(fields)
        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "1"}):
            result = mgr._try_worker_readback_fields()
        assert result == fields

    def test_returns_none_when_env_unset(self):
        mgr = _make_manager(worker_inprocess_env="0")
        mgr._worker_client = _ready_client({"ICCID": "x"})
        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "0"}):
            result = mgr._try_worker_readback_fields()
        assert result is None

    def test_returns_none_when_no_client(self):
        mgr = _make_manager()
        mgr._worker_client = None
        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "1"}):
            result = mgr._try_worker_readback_fields()
        assert result is None

    def test_returns_none_when_not_ready(self):
        mgr = _make_manager()
        client = MagicMock()
        client.is_ready.return_value = False
        mgr._worker_client = client
        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "1"}):
            result = mgr._try_worker_readback_fields()
        assert result is None

    def test_returns_none_when_capability_missing(self):
        mgr = _make_manager()
        mgr._cached_worker_capabilities = ["program_full"]  # no detect_inprocess
        mgr._worker_client = _ready_client({"ICCID": "x"})
        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "1"}):
            result = mgr._try_worker_readback_fields()
        assert result is None

    def test_returns_none_when_result_ok_false(self):
        mgr = _make_manager()
        client = MagicMock()
        client.is_ready.return_value = True
        result = MagicMock()
        result.ok = False
        client.detect_inprocess.return_value = result
        mgr._worker_client = client
        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "1"}):
            r = mgr._try_worker_readback_fields()
        assert r is None

    def test_returns_none_on_exception(self):
        mgr = _make_manager()
        client = MagicMock()
        client.is_ready.return_value = True
        client.detect_inprocess.side_effect = RuntimeError("boom")
        mgr._worker_client = client
        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "1"}):
            r = mgr._try_worker_readback_fields()
        assert r is None

    def test_returns_none_when_session_id_none(self):
        mgr = _make_manager()
        mgr._current_session_id = None
        mgr._worker_client = _ready_client({"ICCID": "x"})
        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "1"}):
            r = mgr._try_worker_readback_fields()
        assert r is None


# ---------------------------------------------------------------------------
# verify_after_program routing
# ---------------------------------------------------------------------------

class TestVerifyAfterProgramRouting:
    def test_worker_success_skips_run_cli(self):
        """When worker returns fields, _run_cli must not be called."""
        mgr = _make_manager()
        fields = {"ICCID": "891460000000000001", "IMSI": "240010000000001"}
        mgr._worker_client = _ready_client(fields)

        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "1"}):
            with patch.object(mgr, "_run_cli") as mock_cli:
                ok, msg, rb = mgr.verify_after_program(
                    {"ICCID": "891460000000000001", "IMSI": "240010000000001"}
                )

        mock_cli.assert_not_called()
        assert ok is True
        assert rb["ICCID"] == "891460000000000001"

    def test_worker_unavailable_falls_back_to_run_cli(self):
        """When worker returns None, _run_cli is called for subprocess readback."""
        mgr = _make_manager(worker_inprocess_env="0")
        mgr._worker_client = None

        fake_stdout = (
            "ICCID: 891460000000000001\n"
            "IMSI: 240010000000001\n"
        )

        def fake_parse(stdout):
            mgr.card_info["ICCID"] = "891460000000000001"
            mgr.card_info["IMSI"] = "240010000000001"

        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "0"}):
            with patch.object(mgr, "_run_cli", return_value=(True, fake_stdout, "")) as mock_cli:
                with patch.object(mgr, "_parse_pysim_output", side_effect=fake_parse):
                    ok, msg, rb = mgr.verify_after_program(
                        {"ICCID": "891460000000000001", "IMSI": "240010000000001"}
                    )

        mock_cli.assert_called()
        assert ok is True

    def test_card_info_unchanged_after_worker_readback(self):
        """card_info must not be mutated when worker readback path is taken."""
        mgr = _make_manager()
        original_info = {"ICCID": "original", "IMSI": "original_imsi"}
        mgr.card_info = dict(original_info)

        fields = {"ICCID": "891460000000000001", "IMSI": "240010000000001"}
        mgr._worker_client = _ready_client(fields)

        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "1"}):
            mgr.verify_after_program({"ICCID": "891460000000000001"})

        assert mgr.card_info == original_info

    def test_card_info_unchanged_after_subprocess_readback(self):
        """card_info swap-and-restore must leave card_info intact on subprocess path."""
        mgr = _make_manager(worker_inprocess_env="0")
        mgr._worker_client = None
        original_info = {"ICCID": "before", "IMSI": "before_imsi"}
        mgr.card_info = dict(original_info)

        def fake_parse(stdout):
            mgr.card_info["ICCID"] = "891460000000000001"

        with patch.dict(os.environ, {"SIMGUI_WORKER_INPROCESS": "0"}):
            with patch.object(mgr, "_run_cli", return_value=(True, "stdout", "")):
                with patch.object(mgr, "_parse_pysim_output", side_effect=fake_parse):
                    mgr.verify_after_program({"ICCID": "891460000000000001"})

        assert mgr.card_info == original_info
