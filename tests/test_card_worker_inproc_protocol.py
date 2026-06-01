"""Phase 1 spike protocol tests for the in-process program_full handler.

These tests never touch real pySim or hardware. They drive ``_handle`` directly,
capture responses through a monkey-patched ``_write``, and inject a fake pySim
runtime via ``card_worker_inproc._pysim_runtime``.
"""

import json
import os
from typing import Any, Dict, List
from unittest import mock

import pytest

import card_worker_inproc
import card_worker_process


@pytest.fixture(autouse=True)
def _reset_inproc_state(monkeypatch):
    """Each test starts with a clean session and no real pySim import."""
    card_worker_inproc.reset_session()
    monkeypatch.setattr(card_worker_inproc, "_pysim_runtime", None, raising=False)
    yield
    card_worker_inproc.reset_session()
    monkeypatch.setattr(card_worker_inproc, "_pysim_runtime", None, raising=False)


def _capture_responses(monkeypatch) -> List[Dict[str, Any]]:
    captured: List[Dict[str, Any]] = []
    monkeypatch.setattr(card_worker_process, "_write",
                        lambda obj: captured.append(obj))
    return captured


def _send(line: dict) -> None:
    card_worker_process._handle(json.dumps(line))


def _install_fake_pysim(monkeypatch, program_spy=None, raise_on_program=None):
    """Inject a fake pySim runtime that records program calls."""
    calls = {"detect": [], "program": []}

    class _FakeCard:
        def program(self, cp):
            calls["program"].append(cp)
            if raise_on_program is not None:
                raise raise_on_program
            if program_spy is not None:
                program_spy(cp)

    class _FakeScc:
        pass

    class _Runtime:
        @staticmethod
        def init_reader(opts):
            return object()

        @staticmethod
        def SimCardCommands(transport):
            return _FakeScc()

        @staticmethod
        def card_detect(type_, scc):
            calls["detect"].append(type_)
            return _FakeCard()

    monkeypatch.setattr(card_worker_inproc, "_pysim_runtime", _Runtime(), raising=False)
    return calls


# --- Tests ---

def test_handler_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SIMGUI_WORKER_INPROCESS", raising=False)
    responses = _capture_responses(monkeypatch)

    _send({"id": 1, "verb": "program_full",
           "params": {"fields": {"IMSI": "001010000000001"}, "adm1_hex": "3838383838383838"}})

    assert responses == [{"id": 1, "ok": False, "error": "INPROCESS_DISABLED", "worker_error": True}]


def test_handler_routes_when_flag_set(monkeypatch):
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
    responses = _capture_responses(monkeypatch)
    calls = _install_fake_pysim(monkeypatch)

    _send({"id": 2, "verb": "program_full",
           "params": {"fields": {"IMSI": "001010000000001",
                                 "Ki": "00112233445566778899aabbccddeeff",
                                 "OPc": "00112233445566778899aabbccddeeff"},
                      "adm1_hex": "3838383838383838",
                      "reader_index": 0}})

    assert len(responses) == 1
    r = responses[0]
    assert r["id"] == 2
    assert r["ok"] is True
    assert "programmed fields=" in r["stdout"]
    assert r["stderr"] == ""
    assert calls["detect"] == ["gialersim"]
    assert len(calls["program"]) == 1
    cp = calls["program"][0]
    assert cp["imsi"] == "001010000000001"
    assert cp["adm1"] == "3838383838383838"


def test_handler_strips_pin_puk(monkeypatch):
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
    responses = _capture_responses(monkeypatch)
    calls = _install_fake_pysim(monkeypatch)

    _send({"id": 3, "verb": "program_full",
           "params": {"fields": {"IMSI": "001010000000001",
                                 "PIN1": "0000", "PUK1": "12345678"},
                      "adm1_hex": "3838383838383838"}})

    assert responses[0]["ok"] is True
    cp = calls["program"][0]
    assert "PIN1" not in cp and "PUK1" not in cp
    # mapping target keys are pin1/puk1 if ever added; they must not appear either.
    assert "pin1" not in cp and "puk1" not in cp


def test_handler_pysim_exception_to_stderr(monkeypatch):
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
    responses = _capture_responses(monkeypatch)
    _install_fake_pysim(monkeypatch, raise_on_program=RuntimeError("APDU 6f00"))

    _send({"id": 4, "verb": "program_full",
           "params": {"fields": {"IMSI": "001010000000001"},
                      "adm1_hex": "3838383838383838"}})

    r = responses[0]
    assert r["ok"] is False
    assert "RuntimeError" in r["stderr"]
    assert "APDU 6f00" in r["stderr"]


def test_handler_invalid_request(monkeypatch):
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
    responses = _capture_responses(monkeypatch)

    _send({"id": 5, "verb": "program_full", "params": {"fields": {"IMSI": "x"}}})

    assert responses[0] == {"id": 5, "ok": False, "error": "INVALID_REQUEST", "worker_error": True}


def test_handler_pysim_import_failed(monkeypatch):
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
    responses = _capture_responses(monkeypatch)

    def _boom():
        raise card_worker_inproc.PysimImportError("no module named pySim")

    monkeypatch.setattr(card_worker_inproc, "_load_pysim", _boom)

    _send({"id": 6, "verb": "program_full",
           "params": {"fields": {"IMSI": "001010000000001"},
                      "adm1_hex": "3838383838383838"}})

    r = responses[0]
    assert r["ok"] is False
    assert r["error"] == "PYSIM_IMPORT_FAILED"


def test_capability_excluded_when_flag_off(monkeypatch):
    monkeypatch.delenv("SIMGUI_WORKER_INPROCESS", raising=False)
    responses = _capture_responses(monkeypatch)
    _send({"id": 7, "verb": "capabilities"})
    assert "program_full" not in responses[0]["result"]


def test_capability_advertised_when_flag_on(monkeypatch):
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
    responses = _capture_responses(monkeypatch)
    _send({"id": 8, "verb": "capabilities"})
    assert "program_full" in responses[0]["result"]


# ---------------------------------------------------------------------------
# Phase B.1 — in-process session lifecycle reset tests
# ---------------------------------------------------------------------------

def _make_probe_readers(monkeypatch, present: bool, atr_hex: str = "3b9f96"):
    """Patch _smartcard_readers and threading so probe behaves synchronously."""
    import threading as _threading

    class _FakeConn:
        def connect(self):
            if not present:
                raise Exception("no card")
        def getATR(self):
            return bytes.fromhex(atr_hex)

    class _FakeReader:
        def createConnection(self):
            return _FakeConn()

    monkeypatch.setattr(card_worker_process, "_smartcard_readers", lambda: [_FakeReader()])

    # Patch threading.Thread so the inner _connect() runs synchronously.
    original_thread = _threading.Thread
    class _SyncThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target
        def start(self):
            self._target()
        def join(self, timeout=None):
            pass
        def is_alive(self):
            return False

    monkeypatch.setattr(card_worker_process, "__builtins__", card_worker_process.__builtins__)
    # Patch threading inside the module namespace via sys.modules trick
    import sys
    fake_threading = type(sys)("threading")
    fake_threading.Thread = _SyncThread
    monkeypatch.setitem(sys.modules, "threading", fake_threading)


def test_reset_called_on_card_removal(monkeypatch):
    """reset_session() is called when probe transitions present→absent."""
    reset_calls = []
    monkeypatch.setattr(card_worker_inproc, "reset_session", lambda: reset_calls.append("reset"))

    responses = _capture_responses(monkeypatch)
    _make_probe_readers(monkeypatch, present=False)

    # Pre-seed _card_present=True so removal transition fires.
    card_worker_process._card_present = True
    _send({"id": 10, "verb": "probe", "params": {"reader_index": 0, "timeout": 1.0}})

    assert reset_calls == ["reset"], "reset_session must be called on card removal"
    assert responses[0]["present"] is False


def test_reset_called_on_new_card_generation(monkeypatch):
    """reset_session() is called on absent→present (new card inserted)."""
    reset_calls = []
    monkeypatch.setattr(card_worker_inproc, "reset_session", lambda: reset_calls.append("reset"))

    responses = _capture_responses(monkeypatch)
    _make_probe_readers(monkeypatch, present=True)

    # Pre-seed absent state so absent→present transition fires.
    card_worker_process._card_present = False
    _send({"id": 11, "verb": "probe", "params": {"reader_index": 0, "timeout": 1.0}})

    assert reset_calls == ["reset"], "reset_session must be called on new card generation"
    assert responses[0]["present"] is True


def test_reset_not_called_for_stable_same_card(monkeypatch):
    """reset_session() is NOT called when card was already present (same generation)."""
    reset_calls = []
    monkeypatch.setattr(card_worker_inproc, "reset_session", lambda: reset_calls.append("reset"))

    responses = _capture_responses(monkeypatch)
    _make_probe_readers(monkeypatch, present=True)

    # Pre-seed present state — no transition, same card.
    card_worker_process._card_present = True
    _send({"id": 12, "verb": "probe", "params": {"reader_index": 0, "timeout": 1.0}})

    assert reset_calls == [], "reset_session must NOT be called for stable same-card probe"
    assert responses[0]["present"] is True
