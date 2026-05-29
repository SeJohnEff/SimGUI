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

def test_capabilities_contains_four_verbs():
    proc = _spawn()
    try:
        _banner(proc)
        resp, _ = _send(proc, "capabilities")
        assert resp["ok"] is True
        caps = resp["result"]
        assert set(caps) == {"ping", "status", "capabilities", "shutdown", "probe"}
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
