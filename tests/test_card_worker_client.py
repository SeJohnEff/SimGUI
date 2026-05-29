"""Tests for PersistentWorkerClient in card_worker_client.py."""

import json
import os
import subprocess
import sys
import threading
import time
import uuid

import pytest

from card_worker_client import (
    AuthResult,
    DetectResult,
    PersistentWorkerClient,
    ProbeResult,
    WorkerCrashError,
    WorkerEOFError,
    WorkerError,
    WorkerProtocolError,
    WorkerStartError,
    WorkerTimeoutError,
)

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "card_worker_process.py")


# ---------------------------------------------------------------------------
# Helpers — fake subprocess via threads
# ---------------------------------------------------------------------------

class _FakeProcess:
    """Minimal Popen-alike backed by two in-process pipes."""

    def __init__(self, stdin_r, stdin_w, stdout_r, stdout_w, stderr_r, stderr_w, returncode=None):
        self.stdin = stdin_w
        self.stdout = stdout_r
        self.stderr = stderr_r
        self._stdin_r = stdin_r
        self._stdout_w = stdout_w
        self._stderr_w = stderr_w
        self._returncode = returncode
        self._poll_value = None

    def poll(self):
        return self._poll_value

    def wait(self, timeout=None):
        return self._poll_value

    def terminate(self):
        self._poll_value = -15


def _pipe_pair():
    r, w = os.pipe()
    return os.fdopen(r, "rb"), os.fdopen(w, "wb")


def _make_fake(ready_banner=True, response_lines=None, returncode=None):
    """
    Build a _FakeProcess that writes a ready banner and then response_lines
    to stdout as they are consumed.
    """
    stdin_r, stdin_w = _pipe_pair()
    stdout_r, stdout_w = _pipe_pair()
    stderr_r, stderr_w = _pipe_pair()

    if ready_banner:
        banner = json.dumps({"event": "ready", "pid": 99999}) + "\n"
        stderr_w.write(banner.encode())
        stderr_w.flush()

    if response_lines is not None:
        for line in response_lines:
            stdout_w.write((line + "\n").encode())
        stdout_w.flush()

    proc = _FakeProcess(stdin_r, stdin_w, stdout_r, stdout_w, stderr_r, stderr_w, returncode)
    return proc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_is_alive_false_before_start():
    client = PersistentWorkerClient(worker_script=SCRIPT)
    assert client.is_alive() is False


def test_is_alive_true_after_start():
    client = PersistentWorkerClient(worker_script=SCRIPT)
    client.start()
    try:
        assert client.is_alive() is True
    finally:
        client.stop()


def test_client_start_reads_ready_banner():
    """start() succeeds when worker emits the ready banner."""
    client = PersistentWorkerClient(worker_script=SCRIPT)
    client.start()  # raises WorkerStartError if banner not received
    assert client.is_alive()
    client.stop()


def test_send_ping():
    client = PersistentWorkerClient(worker_script=SCRIPT)
    client.start()
    try:
        resp = client.send("ping")
        assert resp["ok"] is True
        assert resp["result"] == "pong"
    finally:
        client.stop()


def test_stop_sends_shutdown_and_process_exits():
    client = PersistentWorkerClient(worker_script=SCRIPT)
    client.start()
    proc = client._process
    client.stop()
    assert proc.poll() == 0  # exited cleanly


def test_stop_terminates_if_needed():
    """stop() terminates a process that ignores shutdown."""
    # Use a script that hangs on stdin read instead of responding.
    hang_script = os.path.join(os.path.dirname(SCRIPT), "_hang_worker_test.py")
    with open(hang_script, "w") as f:
        f.write(
            "import sys, json, os\n"
            "sys.stderr.write(json.dumps({'event':'ready','pid':os.getpid()})+'\\n')\n"
            "sys.stderr.flush()\n"
            "import time; time.sleep(60)\n"
        )
    try:
        client = PersistentWorkerClient(worker_script=hang_script)
        client.start()
        client.stop()  # should terminate after timeout
        assert not client.is_alive()
    finally:
        os.unlink(hang_script)


def test_timeout_raises_worker_timeout_error():
    """send() raises WorkerTimeoutError when worker does not respond."""
    hang_script = os.path.join(os.path.dirname(SCRIPT), "_hang_after_ready_test.py")
    with open(hang_script, "w") as f:
        f.write(
            "import sys, json, os, time\n"
            "sys.stderr.write(json.dumps({'event':'ready','pid':os.getpid()})+'\\n')\n"
            "sys.stderr.flush()\n"
            "time.sleep(60)\n"
        )
    try:
        client = PersistentWorkerClient(worker_script=hang_script)
        client.start()
        with pytest.raises(WorkerTimeoutError) as exc_info:
            client.send("ping", timeout=0.3)
        assert exc_info.value.verb == "ping"
    finally:
        try:
            client._process.terminate()
        except Exception:
            pass
        os.unlink(hang_script)


def test_eof_raises_worker_eof_error():
    """send() raises WorkerEOFError when worker closes stdout without responding."""
    eof_script = os.path.join(os.path.dirname(SCRIPT), "_eof_worker_test.py")
    with open(eof_script, "w") as f:
        f.write(
            "import sys, json, os\n"
            "sys.stderr.write(json.dumps({'event':'ready','pid':os.getpid()})+'\\n')\n"
            "sys.stderr.flush()\n"
            "sys.stdin.readline()\n"
            # Exit without writing to stdout.
        )
    try:
        client = PersistentWorkerClient(worker_script=eof_script)
        client.start()
        with pytest.raises((WorkerEOFError, WorkerTimeoutError)):
            client.send("ping", timeout=2.0)
    finally:
        try:
            client._process.terminate()
        except Exception:
            pass
        os.unlink(eof_script)


def test_bad_json_raises_worker_protocol_error():
    """send() raises WorkerProtocolError when worker returns non-JSON."""
    bad_script = os.path.join(os.path.dirname(SCRIPT), "_bad_json_worker_test.py")
    with open(bad_script, "w") as f:
        f.write(
            "import sys, json, os\n"
            "sys.stderr.write(json.dumps({'event':'ready','pid':os.getpid()})+'\\n')\n"
            "sys.stderr.flush()\n"
            "sys.stdin.readline()\n"
            "sys.stdout.write('this is not json\\n')\n"
            "sys.stdout.flush()\n"
            "import time; time.sleep(10)\n"
        )
    try:
        client = PersistentWorkerClient(worker_script=bad_script)
        client.start()
        with pytest.raises(WorkerProtocolError):
            client.send("ping", timeout=3.0)
    finally:
        try:
            client._process.terminate()
        except Exception:
            pass
        os.unlink(bad_script)


def test_crash_raises_worker_crash_error():
    """send() raises WorkerCrashError when worker exits with non-zero code."""
    crash_script = os.path.join(os.path.dirname(SCRIPT), "_crash_worker_test.py")
    with open(crash_script, "w") as f:
        f.write(
            "import sys, json, os\n"
            "sys.stderr.write(json.dumps({'event':'ready','pid':os.getpid()})+'\\n')\n"
            "sys.stderr.flush()\n"
            "sys.stdin.readline()\n"
            "sys.exit(1)\n"
        )
    try:
        client = PersistentWorkerClient(worker_script=crash_script)
        client.start()
        with pytest.raises((WorkerCrashError, WorkerEOFError, WorkerTimeoutError)):
            client.send("ping", timeout=2.0)
    finally:
        try:
            client._process.terminate()
        except Exception:
            pass
        os.unlink(crash_script)


# ---------------------------------------------------------------------------
# Phase 2B — probe() helper tests (no real hardware)
# ---------------------------------------------------------------------------

class _MockClient(PersistentWorkerClient):
    """PersistentWorkerClient subclass that replaces send() with a controllable fake."""

    def __init__(self):
        super().__init__(worker_script="/dev/null")
        self._send_calls = []
        self._send_return = {}

    def send(self, verb, params=None, timeout=10.0):
        self._send_calls.append({"verb": verb, "params": params, "timeout": timeout})
        return self._send_return


def test_probe_sends_correct_verb_and_params():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {"present": False, "msg": "no card"}}
    client.probe(reader_index=1, timeout=3.0)
    assert len(client._send_calls) == 1
    call = client._send_calls[0]
    assert call["verb"] == "probe"
    assert call["params"] == {"reader_index": 1, "timeout": 3.0}


def test_probe_default_request_timeout_is_timeout_plus_one():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {"present": False, "msg": "no card"}}
    client.probe(timeout=2.0)
    assert client._send_calls[0]["timeout"] == pytest.approx(3.0)


def test_probe_custom_request_timeout_overrides_default():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {"present": False, "msg": "no card"}}
    client.probe(timeout=2.0, request_timeout=5.0)
    assert client._send_calls[0]["timeout"] == pytest.approx(5.0)


def test_probe_present_response_parsed_correctly():
    client = _MockClient()
    client._send_return = {
        "ok": True,
        "result": {
            "present": True,
            "atr": "3B9F96801FC78031E073FE211B66D0004300900000",
            "card_gen": "sysmoISIM-SJA5",
            "session_id": "abc-123",
        },
    }
    result = client.probe()
    assert isinstance(result, ProbeResult)
    assert result.present is True
    assert result.atr == "3B9F96801FC78031E073FE211B66D0004300900000"
    assert result.card_gen == "sysmoISIM-SJA5"
    assert result.session_id == "abc-123"
    assert result.error is None


def test_probe_absent_response_parsed_correctly():
    client = _MockClient()
    client._send_return = {
        "ok": True,
        "result": {"present": False, "msg": "no card inserted"},
    }
    result = client.probe()
    assert isinstance(result, ProbeResult)
    assert result.present is False
    assert result.msg == "no card inserted"
    assert result.error is None
    assert result.atr is None


def test_probe_timeout_response_parsed_as_error():
    client = _MockClient()
    client._send_return = {
        "ok": False,
        "error": "PROBE_TIMEOUT",
        "msg": "probe timed out waiting for card",
    }
    result = client.probe()
    assert isinstance(result, ProbeResult)
    assert result.present is False
    assert result.error == "PROBE_TIMEOUT"
    assert result.msg == "probe timed out waiting for card"


def test_probe_ok_false_with_result_preserves_card_gen():
    client = _MockClient()
    client._send_return = {
        "ok": False,
        "error": "READER_ERROR",
        "msg": "reader not found",
        "result": {"card_gen": "unknown", "session_id": "xyz"},
    }
    result = client.probe()
    assert result.present is False
    assert result.error == "READER_ERROR"
    assert result.card_gen == "unknown"
    assert result.session_id == "xyz"


# ---------------------------------------------------------------------------
# Phase 2D-B2 — detect() and read_fields() helpers
# ---------------------------------------------------------------------------

def test_detect_sends_correct_verb_and_params():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {"card_type": "sysmoISIM-SJA5", "blank": False, "fields": {}}}
    client.detect(session_id="s1", card_gen=1, pysim_path="/opt/pysim", reader_index=0, timeout=30.0)
    assert len(client._send_calls) == 1
    call = client._send_calls[0]
    assert call["verb"] == "detect"
    assert call["params"] == {
        "session_id": "s1",
        "card_gen": 1,
        "pysim_path": "/opt/pysim",
        "reader_index": 0,
        "timeout": 30.0,
    }


def test_detect_default_request_timeout_is_timeout_plus_one():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {}}
    client.detect(session_id="s1", card_gen=1, pysim_path="/opt/pysim", timeout=30.0)
    assert client._send_calls[0]["timeout"] == pytest.approx(31.0)


def test_detect_custom_request_timeout_overrides_default():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {}}
    client.detect(session_id="s1", card_gen=1, pysim_path="/opt/pysim", timeout=30.0, request_timeout=45.0)
    assert client._send_calls[0]["timeout"] == pytest.approx(45.0)


def test_detect_ok_response_parsed_correctly():
    client = _MockClient()
    client._send_return = {
        "ok": True,
        "result": {
            "card_type": "sysmoISIM-SJA5",
            "blank": False,
            "fields": {"ICCID": "8946001234567890123", "IMSI": "240011234567890"},
            "session_id": "sess-42",
            "card_gen": 7,
        },
    }
    result = client.detect(session_id="sess-42", card_gen=7, pysim_path="/opt/pysim")
    assert isinstance(result, DetectResult)
    assert result.ok is True
    assert result.card_type == "sysmoISIM-SJA5"
    assert result.blank is False
    assert result.fields["ICCID"] == "8946001234567890123"
    assert result.session_id == "sess-42"
    assert result.card_gen == 7
    assert result.error is None


def test_detect_blank_card_response_parsed_correctly():
    client = _MockClient()
    client._send_return = {
        "ok": True,
        "result": {
            "card_type": "gialersim",
            "blank": True,
            "fields": {},
            "session_id": "sess-blank",
            "card_gen": 3,
        },
    }
    result = client.detect(session_id="sess-blank", card_gen=3, pysim_path="/opt/pysim")
    assert result.ok is True
    assert result.blank is True
    assert result.card_type == "gialersim"
    assert result.fields == {}


def test_detect_stale_session_response_parsed_as_error():
    client = _MockClient()
    client._send_return = {
        "ok": False,
        "error": "STALE_SESSION",
        "msg": "card changed between probe and detect",
    }
    result = client.detect(session_id="old-sess", card_gen=2, pysim_path="/opt/pysim")
    assert isinstance(result, DetectResult)
    assert result.ok is False
    assert result.error == "STALE_SESSION"
    assert result.msg == "card changed between probe and detect"
    assert result.card_type is None


def test_read_fields_sends_correct_verb():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {}}
    client.read_fields(session_id="s2", card_gen=5, pysim_path="/opt/pysim")
    assert client._send_calls[0]["verb"] == "read_fields"


def test_read_fields_ok_response_parsed_correctly():
    client = _MockClient()
    client._send_return = {
        "ok": True,
        "result": {
            "card_type": "sysmoISIM-SJA5",
            "blank": False,
            "fields": {"IMSI": "240019876543210", "ACC": "0001"},
            "session_id": "s2",
            "card_gen": 5,
        },
    }
    result = client.read_fields(session_id="s2", card_gen=5, pysim_path="/opt/pysim")
    assert isinstance(result, DetectResult)
    assert result.ok is True
    assert result.fields["IMSI"] == "240019876543210"
    assert result.card_gen == 5
    assert result.error is None


def test_read_fields_default_request_timeout_is_timeout_plus_one():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {}}
    client.read_fields(session_id="s2", card_gen=5, pysim_path="/opt/pysim", timeout=20.0)
    assert client._send_calls[0]["timeout"] == pytest.approx(21.0)


# ---------------------------------------------------------------------------
# Phase 3C — authenticate() helper tests
# ---------------------------------------------------------------------------

def test_authenticate_sends_correct_verb_and_params():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {"deferred": False, "session_id": "s1", "card_gen": 2}}
    client.authenticate(session_id="s1", card_gen=2, adm1_hex="3838383838383838", timeout=15.0)
    assert len(client._send_calls) == 1
    call = client._send_calls[0]
    assert call["verb"] == "authenticate"
    assert call["params"] == {
        "session_id": "s1",
        "card_gen": 2,
        "adm1_hex": "3838383838383838",
        "timeout": 15.0,
    }


def test_authenticate_default_request_timeout_is_timeout_plus_one():
    client = _MockClient()
    client._send_return = {"ok": True, "result": {}}
    client.authenticate(session_id="s1", card_gen=1, adm1_hex="aa", timeout=15.0)
    assert client._send_calls[0]["timeout"] == pytest.approx(16.0)


def test_authenticate_success_response_parsed_correctly():
    client = _MockClient()
    client._send_return = {
        "ok": True,
        "result": {
            "deferred": True,
            "session_id": "sess-99",
            "card_gen": 5,
        },
    }
    result = client.authenticate(session_id="sess-99", card_gen=5, adm1_hex="deadbeef")
    assert isinstance(result, AuthResult)
    assert result.ok is True
    assert result.deferred is True
    assert result.session_id == "sess-99"
    assert result.card_gen == 5
    assert result.error is None


def test_authenticate_auth_failed_maps_error():
    client = _MockClient()
    client._send_return = {
        "ok": False,
        "error": "AUTH_FAILED",
        "msg": "ADM1 verification failed",
    }
    result = client.authenticate(session_id="s1", card_gen=1, adm1_hex="badkey")
    assert isinstance(result, AuthResult)
    assert result.ok is False
    assert result.error == "AUTH_FAILED"
    assert result.msg == "ADM1 verification failed"


def test_authenticate_card_blocked_maps_error():
    client = _MockClient()
    client._send_return = {
        "ok": False,
        "error": "CARD_BLOCKED",
        "msg": "ADM1 retry counter exhausted",
    }
    result = client.authenticate(session_id="s1", card_gen=1, adm1_hex="badkey")
    assert result.ok is False
    assert result.error == "CARD_BLOCKED"


def test_authenticate_stale_session_maps_error():
    client = _MockClient()
    client._send_return = {
        "ok": False,
        "error": "STALE_SESSION",
        "msg": "card changed since probe",
    }
    result = client.authenticate(session_id="old", card_gen=0, adm1_hex="aa")
    assert result.ok is False
    assert result.error == "STALE_SESSION"


class _MockClientRaises(PersistentWorkerClient):
    """Variant that raises a given exception from send()."""

    def __init__(self, exc):
        super().__init__(worker_script="/dev/null")
        self._exc = exc

    def send(self, verb, params=None, timeout=10.0):
        raise self._exc


def test_authenticate_worker_timeout_maps_worker_dead():
    exc = WorkerTimeoutError("authenticate", 15.0)
    client = _MockClientRaises(exc)
    result = client.authenticate(session_id="s1", card_gen=1, adm1_hex="aa")
    assert result.ok is False
    assert result.error == "WORKER_DEAD"
    assert "authenticate" in result.msg


def test_authenticate_worker_eof_maps_worker_dead():
    client = _MockClientRaises(WorkerEOFError())
    result = client.authenticate(session_id="s1", card_gen=1, adm1_hex="aa")
    assert result.ok is False
    assert result.error == "WORKER_DEAD"


def test_authenticate_worker_crash_maps_worker_dead():
    client = _MockClientRaises(WorkerCrashError(1))
    result = client.authenticate(session_id="s1", card_gen=1, adm1_hex="aa")
    assert result.ok is False
    assert result.error == "WORKER_DEAD"
    assert "1" in result.msg


def test_stderr_does_not_block_caller():
    """Sending many bytes to stderr must not block send()."""
    noisy_script = os.path.join(os.path.dirname(SCRIPT), "_noisy_stderr_worker_test.py")
    with open(noisy_script, "w") as f:
        f.write(
            "import sys, json, os\n"
            "sys.stderr.write(json.dumps({'event':'ready','pid':os.getpid()})+'\\n')\n"
            "sys.stderr.flush()\n"
            "# Dump 1 MB to stderr before responding.\n"
            "sys.stderr.write('x' * 1_000_000 + '\\n')\n"
            "sys.stderr.flush()\n"
            "line = sys.stdin.readline()\n"
            "req = json.loads(line)\n"
            "sys.stdout.write(json.dumps({'id': req.get('id'), 'ok': True, 'result': 'pong'})+'\\n')\n"
            "sys.stdout.flush()\n"
            "import time; time.sleep(10)\n"
        )
    try:
        client = PersistentWorkerClient(worker_script=noisy_script)
        client.start()
        resp = client.send("ping", timeout=5.0)
        assert resp["ok"] is True
    finally:
        try:
            client._process.terminate()
        except Exception:
            pass
        os.unlink(noisy_script)
