"""Tests for card_worker_process.py — spawns a real subprocess."""

import json
import os
import subprocess
import sys
import time
import uuid

import pytest
from unittest.mock import MagicMock, patch

import card_worker_process

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "card_worker_process.py")


def _spawn():
    return subprocess.Popen(
        [sys.executable, SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _send(proc, verb, params=None):
    req_id = str(uuid.uuid4())
    req = {"id": req_id, "verb": verb}
    if params:
        req["params"] = params
    line = json.dumps(req) + "\n"
    proc.stdin.write(line.encode())
    proc.stdin.flush()
    raw = proc.stdout.readline()
    return json.loads(raw), req_id


def _banner(proc, timeout=3.0):
    """Read ready banner from stderr with a simple thread-based timeout."""
    import threading
    result = []
    done = threading.Event()

    def reader():
        try:
            result.append(proc.stderr.readline().decode())
        except OSError:
            result.append("")
        done.set()

    threading.Thread(target=reader, daemon=True).start()
    done.wait(timeout)
    return json.loads(result[0]) if result and result[0].strip() else None


# --- process starts ---

def test_process_starts_and_emits_ready_banner():
    proc = _spawn()
    try:
        banner = _banner(proc)
        assert banner is not None
        assert banner["event"] == "ready"
        assert isinstance(banner["pid"], int)
    finally:
        proc.terminate()
        proc.wait()


# --- ping ---

def test_ping_returns_pong():
    proc = _spawn()
    try:
        _banner(proc)
        resp, req_id = _send(proc, "ping")
        assert resp["ok"] is True
        assert resp["result"] == "pong"
        assert resp["id"] == req_id
    finally:
        proc.terminate()
        proc.wait()


# --- status ---

def test_status_returns_idle_and_pid():
    proc = _spawn()
    try:
        _banner(proc)
        resp, _ = _send(proc, "status")
        assert resp["ok"] is True
        result = resp["result"]
        assert result["status"] == "idle"
        assert isinstance(result["pid"], int)
        assert result["pid"] == proc.pid
    finally:
        proc.terminate()
        proc.wait()


# --- capabilities ---

def test_capabilities_contains_base_verbs():
    proc = _spawn()
    try:
        _banner(proc)
        resp, _ = _send(proc, "capabilities")
        assert resp["ok"] is True
        caps = set(resp["result"])
        base = {"ping", "status", "capabilities", "shutdown", "probe", "detect", "read_fields", "authenticate"}
        assert base.issubset(caps)
    finally:
        proc.terminate()
        proc.wait()


# --- shutdown ---

def test_shutdown_exits_cleanly():
    proc = _spawn()
    _banner(proc)
    resp, _ = _send(proc, "shutdown")
    assert resp["ok"] is True
    proc.wait(timeout=3)
    assert proc.returncode == 0


# --- unknown verb ---

def test_unknown_verb_returns_error():
    proc = _spawn()
    try:
        _banner(proc)
        resp, req_id = _send(proc, "frobnicate")
        assert resp["ok"] is False
        assert resp["error"] == "unknown_verb"
        assert resp["id"] == req_id
    finally:
        proc.terminate()
        proc.wait()


# --- malformed JSON ---

def test_malformed_json_returns_parse_error():
    proc = _spawn()
    try:
        _banner(proc)
        proc.stdin.write(b"not json at all\n")
        proc.stdin.flush()
        raw = proc.stdout.readline()
        resp = json.loads(raw)
        assert resp["ok"] is False
        assert resp["error"] == "parse_error"
        assert resp["id"] is None
    finally:
        proc.terminate()
        proc.wait()


# --- id echoed ---

def test_response_id_matches_request_id():
    proc = _spawn()
    try:
        _banner(proc)
        resp, req_id = _send(proc, "ping")
        assert resp["id"] == req_id
    finally:
        proc.terminate()
        proc.wait()


# --- multiple requests ---

def test_multiple_requests_use_same_process():
    proc = _spawn()
    try:
        _banner(proc)
        for _ in range(10):
            resp, _ = _send(proc, "ping")
            assert resp["result"] == "pong"
        # Verify pid is still the same (same process).
        resp, _ = _send(proc, "status")
        assert resp["result"]["pid"] == proc.pid
    finally:
        proc.terminate()
        proc.wait()


# ---------------------------------------------------------------------------
# Unit tests for _handle_probe (import card_worker_process as module)
# ---------------------------------------------------------------------------

def _reset_probe_state():
    card_worker_process._card_gen = 0
    card_worker_process._session_id = None
    card_worker_process._last_atr = None
    card_worker_process._card_present = False


def _fake_reader(atr=None, raise_on_connect=False, hang_connect=False):
    conn = MagicMock()
    if raise_on_connect:
        conn.connect.side_effect = Exception("no card")
    elif hang_connect:
        conn.connect.side_effect = lambda: time.sleep(10)
    else:
        conn.connect.return_value = None
        conn.getATR.return_value = atr or [0x3B, 0x9F, 0x94]
    reader = MagicMock()
    reader.createConnection.return_value = conn
    return reader


class TestHandleProbeUnit:

    def setup_method(self):
        _reset_probe_state()

    def test_present_returns_atr_card_gen_session_id(self):
        atr_bytes = [0x3B, 0x9F, 0x94]
        reader = _fake_reader(atr=atr_bytes)
        captured = []
        with patch.object(card_worker_process, "_smartcard_readers", return_value=[reader]):
            with patch.object(card_worker_process, "_write", side_effect=captured.append):
                card_worker_process._handle_probe("req1", {})
        resp = captured[0]
        assert resp["ok"] is True
        assert resp["present"] is True
        assert resp["atr"] == bytes(atr_bytes).hex()
        assert resp["card_gen"] == 1
        assert isinstance(resp["session_id"], str) and len(resp["session_id"]) > 0

    def test_two_present_probes_keep_same_card_gen(self):
        reader = _fake_reader()
        captured = []
        with patch.object(card_worker_process, "_smartcard_readers", return_value=[reader]):
            with patch.object(card_worker_process, "_write", side_effect=captured.append):
                card_worker_process._handle_probe("req1", {})
                card_worker_process._handle_probe("req2", {})
        assert captured[0]["card_gen"] == 1
        assert captured[1]["card_gen"] == 1

    def test_present_absent_present_increments_card_gen(self):
        captured = []
        with patch.object(card_worker_process, "_smartcard_readers", side_effect=[
            [_fake_reader()],
            [_fake_reader(raise_on_connect=True)],
            [_fake_reader()],
        ]):
            with patch.object(card_worker_process, "_write", side_effect=captured.append):
                card_worker_process._handle_probe("req1", {})
                card_worker_process._handle_probe("req2", {})
                card_worker_process._handle_probe("req3", {})
        assert captured[0]["card_gen"] == 1
        assert captured[1]["present"] is False
        assert captured[2]["card_gen"] == 2

    def test_no_reader_returns_present_false(self):
        captured = []
        with patch.object(card_worker_process, "_smartcard_readers", return_value=[]):
            with patch.object(card_worker_process, "_write", side_effect=captured.append):
                card_worker_process._handle_probe("req1", {})
        resp = captured[0]
        assert resp["ok"] is True
        assert resp["present"] is False

    def test_no_card_returns_present_false(self):
        reader = _fake_reader(raise_on_connect=True)
        captured = []
        with patch.object(card_worker_process, "_smartcard_readers", return_value=[reader]):
            with patch.object(card_worker_process, "_write", side_effect=captured.append):
                card_worker_process._handle_probe("req1", {})
        resp = captured[0]
        assert resp["ok"] is True
        assert resp["present"] is False

    def test_timeout_returns_ok_false_probe_timeout(self):
        reader = _fake_reader(hang_connect=True)
        captured = []
        with patch.object(card_worker_process, "_smartcard_readers", return_value=[reader]):
            with patch.object(card_worker_process, "_write", side_effect=captured.append):
                card_worker_process._handle_probe("req1", {"timeout": 0.05})
        resp = captured[0]
        assert resp["ok"] is False
        assert resp["error"] == "PROBE_TIMEOUT"

    def test_capabilities_include_probe(self):
        assert "probe" in card_worker_process._CAPABILITIES


# ---------------------------------------------------------------------------
# Unit tests for _handle_detect / read_fields (Phase 2D-B1)
# ---------------------------------------------------------------------------

SJA5_OUTPUT = (
    "Autodetected card type: sysmoISIM-SJA5\n"
    "ICCID: 8946000000000000001\n"
    "IMSI: 240010000000001\n"
    "ACC: 0001\n"
)

GIALERSIM_OUTPUT = (
    "Autodetected card type: gialersim\n"
    "ACC: ffff\n"
)

_BASE_PARAMS = {
    "pysim_path": "/opt/pysim",
    "reader_index": 0,
    "timeout": 10,
}


def _reset_detect_state(session_id="abc123", card_gen=1):
    card_worker_process._session_id = session_id
    card_worker_process._card_gen = card_gen
    card_worker_process._card_present = True


def _run_detect(params, session_id="abc123", card_gen=1):
    _reset_detect_state(session_id, card_gen)
    captured = []
    with patch.object(card_worker_process, "_write", side_effect=captured.append):
        card_worker_process._handle_detect("req1", params)
    return captured[0]


class TestHandleDetectUnit:

    def setup_method(self):
        _reset_probe_state()

    def test_sja5_output_ok_blank_false_fields_populated(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=SJA5_OUTPUT, stderr="")
        with patch("card_worker_process.subprocess.run", return_value=completed):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                resp = _run_detect(params)
        assert resp["ok"] is True
        assert resp["blank"] is False
        assert resp["fields"]["ICCID"] == "8946000000000000001"
        assert resp["fields"]["IMSI"] == "240010000000001"

    def test_gialersim_output_ok_blank_true(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=GIALERSIM_OUTPUT, stderr="")
        with patch("card_worker_process.subprocess.run", return_value=completed):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                resp = _run_detect(params)
        assert resp["ok"] is True
        assert resp["blank"] is True

    def test_wrong_session_id_returns_stale_session(self):
        params = {**_BASE_PARAMS, "session_id": "wrong", "card_gen": 1}
        with patch("card_worker_process.os.path.isfile", return_value=True):
            resp = _run_detect(params)
        assert resp["ok"] is False
        assert resp["error"] == "STALE_SESSION"

    def test_wrong_card_gen_returns_stale_session(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 99}
        with patch("card_worker_process.os.path.isfile", return_value=True):
            resp = _run_detect(params)
        assert resp["ok"] is False
        assert resp["error"] == "STALE_SESSION"

    def test_missing_pysim_path_returns_cli_not_found(self):
        params = {"session_id": "abc123", "card_gen": 1, "reader_index": 0}
        resp = _run_detect(params)
        assert resp["ok"] is False
        assert resp["error"] == "CLI_NOT_FOUND"

    def test_missing_pysim_read_script_returns_cli_not_found(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        with patch("card_worker_process.os.path.isfile", return_value=False):
            resp = _run_detect(params)
        assert resp["ok"] is False
        assert resp["error"] == "CLI_NOT_FOUND"

    def test_subprocess_timeout_returns_card_unresponsive(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        with patch("card_worker_process.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=10)):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                resp = _run_detect(params)
        assert resp["ok"] is False
        assert resp["error"] == "CARD_UNRESPONSIVE"

    def test_nonzero_no_parseable_output_returns_detect_failed(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        with patch("card_worker_process.subprocess.run", return_value=completed):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                resp = _run_detect(params)
        assert resp["ok"] is False
        assert resp["error"] == "DETECT_FAILED"
        assert resp["worker_error"] is False

    def test_read_fields_mirrors_successful_detect(self):
        _reset_detect_state("abc123", 1)
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=SJA5_OUTPUT, stderr="")
        captured = []
        with patch("card_worker_process.subprocess.run", return_value=completed):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                with patch.object(card_worker_process, "_write", side_effect=captured.append):
                    card_worker_process._handle_detect("req2", params)
        resp = captured[0]
        assert resp["ok"] is True
        assert resp["fields"]["ICCID"] == "8946000000000000001"
        assert resp["card_type"] == "sysmoisim-sja5"
        assert resp["worker_error"] is False
        assert "stdout" in resp
        assert "stderr" in resp

    def test_detect_success_includes_stable_schema_fields(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=SJA5_OUTPUT, stderr="")
        with patch("card_worker_process.subprocess.run", return_value=completed):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                resp = _run_detect(params)
        assert resp["ok"] is True
        assert resp["card_type"] == "sysmoisim-sja5"
        assert resp["blank"] is False
        assert resp["worker_error"] is False
        assert resp["stdout"] == SJA5_OUTPUT
        assert resp["stderr"] == ""

    def test_stale_session_sets_worker_error_true(self):
        params = {**_BASE_PARAMS, "session_id": "wrong", "card_gen": 1}
        with patch("card_worker_process.os.path.isfile", return_value=True):
            resp = _run_detect(params)
        assert resp["ok"] is False
        assert resp["error"] == "STALE_SESSION"
        assert resp["worker_error"] is True

    def test_cli_not_found_sets_worker_error_true(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        with patch("card_worker_process.os.path.isfile", return_value=False):
            resp = _run_detect(params)
        assert resp["ok"] is False
        assert resp["error"] == "CLI_NOT_FOUND"
        assert resp["worker_error"] is True

    def test_protocolerror_retries_once_then_succeeds(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        fail = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="ProtocolError: T=0")
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout=SJA5_OUTPUT, stderr="")
        run_results = [fail, ok]
        with patch("card_worker_process.subprocess.run", side_effect=run_results):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                with patch("card_worker_process.time" if hasattr(card_worker_process, "time") else "time.sleep"):
                    import unittest.mock as _mock
                    with _mock.patch("time.sleep"):
                        resp = _run_detect(params)
        assert resp["ok"] is True
        assert resp["fields"]["ICCID"] == "8946000000000000001"

    def test_protocolerror_retries_once_then_fails(self):
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        fail1 = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="ProtocolError: T=0")
        fail2 = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="still failing")
        run_results = [fail1, fail2]
        with patch("card_worker_process.subprocess.run", side_effect=run_results):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                import unittest.mock as _mock
                with _mock.patch("time.sleep"):
                    resp = _run_detect(params)
        assert resp["ok"] is False
        assert resp["worker_error"] is False

    def test_capabilities_include_detect_and_read_fields(self):
        assert "detect" in card_worker_process._CAPABILITIES
        assert "read_fields" in card_worker_process._CAPABILITIES


# ---------------------------------------------------------------------------
# Unit tests for session profile state (Phase 3A-4)
# ---------------------------------------------------------------------------

def _reset_session_profile():
    card_worker_process._session_profile = None
    card_worker_process._session_pysim_path = ""
    card_worker_process._session_reader_index = 0


class TestSessionProfile:

    def setup_method(self):
        _reset_probe_state()
        _reset_session_profile()

    def test_sja5_detect_stores_sja5_profile(self):
        from card_profiles import SJA5Profile
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=SJA5_OUTPUT, stderr="")
        _reset_detect_state()
        with patch("card_worker_process.subprocess.run", return_value=completed):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                with patch.object(card_worker_process, "_write", side_effect=lambda x: None):
                    card_worker_process._handle_detect("req1", params)
        assert isinstance(card_worker_process._session_profile, SJA5Profile)
        assert card_worker_process._session_pysim_path == "/opt/pysim"
        assert card_worker_process._session_reader_index == 0

    def test_gialersim_detect_stores_gialersimprofile(self):
        from card_profiles import GialerSIMProfile
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=GIALERSIM_OUTPUT, stderr="")
        _reset_detect_state()
        with patch("card_worker_process.subprocess.run", return_value=completed):
            with patch("card_worker_process.os.path.isfile", return_value=True):
                with patch.object(card_worker_process, "_write", side_effect=lambda x: None):
                    card_worker_process._handle_detect("req1", params)
        assert isinstance(card_worker_process._session_profile, GialerSIMProfile)

    def test_profile_creation_failure_leaves_none_but_detect_ok(self):
        import card_profiles
        params = {**_BASE_PARAMS, "session_id": "abc123", "card_gen": 1}
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=SJA5_OUTPUT, stderr="")
        _reset_detect_state()
        card_worker_process._session_profile = object()  # non-None sentinel
        captured = []
        with patch.object(card_profiles.ProfileFactory, "create", side_effect=Exception("boom")):
            with patch("card_worker_process.subprocess.run", return_value=completed):
                with patch("card_worker_process.os.path.isfile", return_value=True):
                    with patch.object(card_worker_process, "_write", side_effect=captured.append):
                        card_worker_process._handle_detect("req1", params)
        assert captured[0]["ok"] is True
        assert card_worker_process._session_profile is None

    def test_probe_new_insertion_clears_stale_session_profile(self):
        card_worker_process._session_profile = object()  # non-None sentinel
        card_worker_process._card_present = False
        atr_bytes = [0x3B, 0x9F, 0x94]
        reader = _fake_reader(atr=atr_bytes)
        captured = []
        with patch.object(card_worker_process, "_smartcard_readers", return_value=[reader]):
            with patch.object(card_worker_process, "_write", side_effect=captured.append):
                card_worker_process._handle_probe("req1", {})
        assert captured[0]["present"] is True
        assert card_worker_process._session_profile is None

    def test_probe_no_card_clears_session_profile(self):
        card_worker_process._session_profile = object()  # non-None sentinel
        card_worker_process._card_present = True  # previously detected
        reader = _fake_reader(raise_on_connect=True)
        captured = []
        with patch.object(card_worker_process, "_smartcard_readers", return_value=[reader]):
            with patch.object(card_worker_process, "_write", side_effect=captured.append):
                card_worker_process._handle_probe("req1", {})
        assert captured[0]["present"] is False
        assert card_worker_process._session_profile is None


# ---------------------------------------------------------------------------
# Unit tests for _handle_authenticate (Phase 3B-1)
# ---------------------------------------------------------------------------

def _make_fake_profile(ok, msg):
    profile = MagicMock()
    profile.authenticate.return_value = (ok, msg)
    return profile


def _reset_auth_state(session_id="sess1", card_gen=2):
    card_worker_process._session_id = session_id
    card_worker_process._card_gen = card_gen
    card_worker_process._card_present = True


def _run_authenticate(params, profile, session_id="sess1", card_gen=2):
    _reset_auth_state(session_id, card_gen)
    card_worker_process._session_profile = profile
    captured = []
    with patch.object(card_worker_process, "_write", side_effect=captured.append):
        card_worker_process._handle_authenticate("req1", params)
    return captured[0]


class TestHandleAuthenticate:

    def setup_method(self):
        _reset_probe_state()
        _reset_session_profile()

    def test_authenticate_success_ok_true_deferred_false(self):
        profile = _make_fake_profile(True, "")
        params = {"session_id": "sess1", "card_gen": 2, "adm1_hex": "3838383838383838"}
        resp = _run_authenticate(params, profile)
        assert resp["ok"] is True
        assert resp["result"]["deferred"] is False
        assert resp["result"]["session_id"] == "sess1"
        assert resp["result"]["card_gen"] == 2
        profile.authenticate.assert_called_once_with("3838383838383838")

    def test_authenticate_deferred_ok_true_deferred_true(self):
        profile = _make_fake_profile(True, "DEFERRED: blank card, no VERIFY sent")
        params = {"session_id": "sess1", "card_gen": 2, "adm1_hex": "3838383838383838"}
        resp = _run_authenticate(params, profile)
        assert resp["ok"] is True
        assert resp["result"]["deferred"] is True

    def test_auth_failed_msg_maps_to_auth_failed_error(self):
        profile = _make_fake_profile(False, "AUTH_FAILED: wrong key")
        params = {"session_id": "sess1", "card_gen": 2, "adm1_hex": "3838383838383838"}
        resp = _run_authenticate(params, profile)
        assert resp["ok"] is False
        assert resp["error"] == "AUTH_FAILED"

    def test_card_blocked_msg_maps_to_card_blocked_error(self):
        profile = _make_fake_profile(False, "CARD_BLOCKED: retries exhausted")
        params = {"session_id": "sess1", "card_gen": 2, "adm1_hex": "3838383838383838"}
        resp = _run_authenticate(params, profile)
        assert resp["ok"] is False
        assert resp["error"] == "CARD_BLOCKED"

    def test_transport_error_msg_maps_to_transport_error(self):
        profile = _make_fake_profile(False, "TRANSPORT_ERROR: reader disconnected")
        params = {"session_id": "sess1", "card_gen": 2, "adm1_hex": "3838383838383838"}
        resp = _run_authenticate(params, profile)
        assert resp["ok"] is False
        assert resp["error"] == "TRANSPORT_ERROR"

    def test_stale_session_id_returns_stale_session_and_profile_not_called(self):
        profile = _make_fake_profile(True, "")
        params = {"session_id": "wrong", "card_gen": 2, "adm1_hex": "3838383838383838"}
        resp = _run_authenticate(params, profile)
        assert resp["ok"] is False
        assert resp["error"] == "STALE_SESSION"
        profile.authenticate.assert_not_called()

    def test_no_profile_returns_no_profile(self):
        _reset_auth_state()
        card_worker_process._session_profile = None
        captured = []
        with patch.object(card_worker_process, "_write", side_effect=captured.append):
            card_worker_process._handle_authenticate("req1", {
                "session_id": "sess1", "card_gen": 2, "adm1_hex": "3838383838383838",
            })
        assert captured[0]["ok"] is False
        assert captured[0]["error"] == "NO_PROFILE"

    def test_missing_adm1_hex_returns_invalid_request(self):
        profile = _make_fake_profile(True, "")
        params = {"session_id": "sess1", "card_gen": 2}
        resp = _run_authenticate(params, profile)
        assert resp["ok"] is False
        assert resp["error"] == "INVALID_REQUEST"
        profile.authenticate.assert_not_called()

    def test_capabilities_includes_authenticate(self):
        assert "authenticate" in card_worker_process._CAPABILITIES


# ---------------------------------------------------------------------------
# Unit tests for WorkerAuthDelegate.authenticate_adm (Phase 3B-2)
# ---------------------------------------------------------------------------

class TestWorkerAuthDelegateAuthenticateAdm:

    @pytest.fixture(autouse=True)
    def disable_inprocess(self, monkeypatch):
        # These tests cover the CLI subprocess auth path; disable in-process mode.
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "0")

    def _make_delegate(self, pysim_path="/opt/pysim", reader_index=0):
        return card_worker_process.WorkerAuthDelegate(pysim_path, reader_index)

    def test_success_returns_true_empty_msg_and_uses_expected_args(self):
        delegate = self._make_delegate()
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="Welcome\n", stderr="")
        with patch("card_worker_process.os.path.isfile", return_value=True):
            with patch("card_worker_process.subprocess.run", return_value=completed) as mock_run:
                ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is True
        assert msg == ""
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[2] == "-p"
        assert cmd[3] == "0"
        assert cmd[4] == "-A"
        assert cmd[5] == "3838383838383838"
        assert call_args.kwargs["input"] == "quit\n"

    def test_6982_in_output_returns_auth_failed(self):
        delegate = self._make_delegate()
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="SW: 6982\n", stderr="")
        with patch("card_worker_process.os.path.isfile", return_value=True):
            with patch("card_worker_process.subprocess.run", return_value=completed):
                ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is False
        assert msg.startswith("AUTH_FAILED")

    def test_swmatcherror_in_output_returns_auth_failed(self):
        delegate = self._make_delegate()
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="SwMatchError: ...\n", stderr="")
        with patch("card_worker_process.os.path.isfile", return_value=True):
            with patch("card_worker_process.subprocess.run", return_value=completed):
                ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is False
        assert msg.startswith("AUTH_FAILED")

    def test_6983_in_output_returns_card_blocked(self):
        delegate = self._make_delegate()
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="SW: 6983\n", stderr="")
        with patch("card_worker_process.os.path.isfile", return_value=True):
            with patch("card_worker_process.subprocess.run", return_value=completed):
                ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is False
        assert msg.startswith("CARD_BLOCKED")

    def test_missing_script_returns_transport_error_cli_not_found(self):
        delegate = self._make_delegate()
        with patch("card_worker_process.os.path.isfile", return_value=False):
            ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is False
        assert msg == "TRANSPORT_ERROR:CLI_NOT_FOUND"

    def test_timeout_expired_returns_transport_error(self):
        delegate = self._make_delegate()
        with patch("card_worker_process.os.path.isfile", return_value=True):
            with patch("card_worker_process.subprocess.run",
                       side_effect=subprocess.TimeoutExpired(cmd="x", timeout=15)):
                ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is False
        assert msg.startswith("TRANSPORT_ERROR")

    def test_nonzero_returncode_unknown_output_returns_transport_error(self):
        delegate = self._make_delegate()
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="unexpected error\n", stderr="")
        with patch("card_worker_process.os.path.isfile", return_value=True):
            with patch("card_worker_process.subprocess.run", return_value=completed):
                ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is False
        assert msg.startswith("TRANSPORT_ERROR")


# ---------------------------------------------------------------------------
# _inprocess_enabled default-on semantics
# ---------------------------------------------------------------------------

def test_inprocess_enabled_default_on(monkeypatch):
    import card_worker_process as cwp
    monkeypatch.delenv("SIMGUI_WORKER_INPROCESS", raising=False)
    assert cwp._inprocess_enabled() is True


def test_inprocess_enabled_opt_out(monkeypatch):
    import card_worker_process as cwp
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "0")
    assert cwp._inprocess_enabled() is False


def test_inprocess_enabled_explicit_on(monkeypatch):
    import card_worker_process as cwp
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
    assert cwp._inprocess_enabled() is True


def test_capabilities_include_detect_inprocess_by_default(monkeypatch):
    """_capabilities() includes detect_inprocess when inprocess is enabled and inproc loads."""
    import card_worker_process as cwp
    import types
    monkeypatch.delenv("SIMGUI_WORKER_INPROCESS", raising=False)
    fake_inproc = type("FakeInproc", (), {"delta_supported_fields": staticmethod(lambda: ["IMSI"])})()
    monkeypatch.setitem(__import__("sys").modules, "card_worker_inproc", fake_inproc)
    # pySim must also appear importable — _capabilities() imports it as a guard
    monkeypatch.setitem(__import__("sys").modules, "pySim", types.ModuleType("pySim"))
    caps = cwp._capabilities()
    assert "detect_inprocess" in caps
    assert "program_full" in caps
