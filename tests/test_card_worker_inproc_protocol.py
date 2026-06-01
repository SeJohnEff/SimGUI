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

def test_handler_disabled_when_opted_out(monkeypatch):
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "0")
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


def test_capability_excluded_when_opted_out(monkeypatch):
    monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "0")
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


# ---------------------------------------------------------------------------
# detect_inprocess handler tests
# ---------------------------------------------------------------------------

def _install_fake_pysim_detect(monkeypatch, iccid=None, imsi=None, spn=None,
                                acc=None, fplmn=None, card_name="sysmoisim-sja5",
                                card_detect_returns_none=False):
    """Inject a fake pySim runtime with read methods for detect_inprocess tests."""
    class _FakeCard:
        name = card_name

        def read_iccid(self):
            if iccid is None:
                return (None, "6a82")
            return (iccid, "9000")

        def read_imsi(self):
            if imsi is None:
                return (None, "6a82")
            return (imsi, "9000")

        def read_spn(self):
            if spn is None:
                return (None, "6a82")
            return ((spn, True, False), "9000")

        def read_binary(self, ef):
            if ef == "ACC":
                if acc is None:
                    return (None, "6a82")
                return (acc, "9000")
            return (None, "6a82")

        def read_fplmn(self):
            if fplmn is None:
                return (None, "6a82")
            return (fplmn, "9000")

    class _Runtime:
        @staticmethod
        def init_reader(opts):
            return object()

        @staticmethod
        def SimCardCommands(transport):
            return object()

        @staticmethod
        def card_detect(type_, scc):
            if card_detect_returns_none:
                return None
            return _FakeCard()

    monkeypatch.setattr(card_worker_inproc, "_pysim_runtime", _Runtime(), raising=False)


class TestDetectInprocessHandler:

    def test_handler_disabled_when_opted_out(self, monkeypatch):
        """detect_inprocess verb returns INPROCESS_DISABLED when explicitly disabled."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "0")
        responses = _capture_responses(monkeypatch)
        _send({"id": 99, "verb": "detect_inprocess", "params": {"reader_index": 0}})
        assert len(responses) == 1
        r = responses[0]
        assert r["ok"] is False
        assert r["error"] == "INPROCESS_DISABLED"
        assert r["worker_error"] is True

    def test_handler_success_returns_stable_schema(self, monkeypatch):
        """detect_inprocess success returns all top-level schema keys."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        _install_fake_pysim_detect(
            monkeypatch,
            iccid="8946220000000000001",
            imsi="244220000000001",
            spn="TestNet",
            card_name="sysmoisim-sja5",
        )
        responses = _capture_responses(monkeypatch)
        _send({"id": 10, "verb": "detect_inprocess", "params": {"reader_index": 0}})
        assert len(responses) == 1
        r = responses[0]
        assert r["ok"] is True
        assert r["blank"] is False
        assert r["card_type"] == "sysmoisim-sja5"
        assert r["fields"]["ICCID"] == "8946220000000000001"
        assert r["fields"]["IMSI"] == "244220000000001"
        assert r["fields"]["SPN"] == "TestNet"
        assert "stdout" in r
        assert "stderr" in r
        assert r["worker_error"] is False

    def test_handler_blank_gialersim_returns_blank_true(self, monkeypatch):
        """Blank gialersim card (no ICCID/IMSI) sets blank=True."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        _install_fake_pysim_detect(monkeypatch, card_name="gialersim")
        responses = _capture_responses(monkeypatch)
        _send({"id": 11, "verb": "detect_inprocess", "params": {"reader_index": 0}})
        assert len(responses) == 1
        r = responses[0]
        assert r["ok"] is True
        assert r["blank"] is True
        assert r["card_type"] == "gialersim"

    def test_handler_card_detect_none_returns_no_card(self, monkeypatch):
        """card_detect returning None yields ok=False, error=NO_CARD."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        _install_fake_pysim_detect(monkeypatch, card_detect_returns_none=True)
        responses = _capture_responses(monkeypatch)
        _send({"id": 12, "verb": "detect_inprocess", "params": {"reader_index": 0}})
        assert len(responses) == 1
        r = responses[0]
        assert r["ok"] is False
        assert r["error"] == "NO_CARD"
        assert r["worker_error"] is False

    def test_handler_pysim_import_error_maps_to_import_failed(self, monkeypatch):
        """PysimImportError from detect_inprocess maps to PYSIM_IMPORT_FAILED."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        monkeypatch.setattr(
            card_worker_inproc, "_pysim_runtime",
            None, raising=False
        )
        # Make _load_pysim raise PysimImportError
        monkeypatch.setattr(
            card_worker_inproc, "_load_pysim",
            lambda: (_ for _ in ()).throw(card_worker_inproc.PysimImportError("no pySim")),
        )
        responses = _capture_responses(monkeypatch)
        _send({"id": 13, "verb": "detect_inprocess", "params": {"reader_index": 0}})
        assert len(responses) == 1
        r = responses[0]
        assert r["ok"] is False
        assert r["error"] == "PYSIM_IMPORT_FAILED"
        assert r["worker_error"] is True

    def test_capabilities_include_detect_inprocess_when_enabled(self, monkeypatch):
        """detect_inprocess appears in capabilities only when SIMGUI_WORKER_INPROCESS=1."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        responses = _capture_responses(monkeypatch)
        _send({"id": 20, "verb": "capabilities"})
        caps = responses[0]["result"]
        assert "detect_inprocess" in caps

    def test_capabilities_exclude_detect_inprocess_when_disabled(self, monkeypatch):
        """detect_inprocess absent from capabilities when explicitly disabled."""
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "0")
        responses = _capture_responses(monkeypatch)
        _send({"id": 21, "verb": "capabilities"})
        caps = responses[0]["result"]
        assert "detect_inprocess" not in caps


# ---------------------------------------------------------------------------
# Phase C.4a — authenticate_inprocess unit tests
# ---------------------------------------------------------------------------

class TestAuthenticateInprocess:
    """authenticate_inprocess uses the long-lived scc session; no subprocess."""

    def _fake_scc(self):
        scc = mock.MagicMock()
        scc.verify_chv.return_value = ("", "9000")
        return scc

    def _install_session(self, monkeypatch, scc):
        monkeypatch.setitem(card_worker_inproc._session, "sl", object())
        monkeypatch.setitem(card_worker_inproc._session, "scc", scc)
        monkeypatch.setitem(card_worker_inproc._session, "reader_index", 0)

    def _fake_rt(self, monkeypatch, scc):
        rt = mock.MagicMock()
        rt.SimCardCommands.return_value = scc
        rt.init_reader.return_value = mock.MagicMock()
        monkeypatch.setattr(card_worker_inproc, "_pysim_runtime", rt)
        return rt

    def test_success_calls_verify_chv(self, monkeypatch):
        scc = self._fake_scc()
        self._install_session(monkeypatch, scc)
        self._fake_rt(monkeypatch, scc)
        ok, msg = card_worker_inproc.authenticate_inprocess("3838383838383838", 0, False)
        assert ok is True
        assert msg == ""
        scc.verify_chv.assert_called_once_with(0x0A, "3838383838383838")

    def test_wrong_key_maps_to_auth_failed(self, monkeypatch):
        scc = self._fake_scc()
        scc.verify_chv.side_effect = Exception("SW mismatch: 6982 != 9000")
        self._install_session(monkeypatch, scc)
        self._fake_rt(monkeypatch, scc)
        ok, msg = card_worker_inproc.authenticate_inprocess("deadbeefdeadbeef", 0, False)
        assert ok is False
        assert msg.startswith("AUTH_FAILED")

    def test_swmatcherror_maps_to_auth_failed(self, monkeypatch):
        scc = self._fake_scc()
        scc.verify_chv.side_effect = Exception("SwMatchError occurred")
        self._install_session(monkeypatch, scc)
        self._fake_rt(monkeypatch, scc)
        ok, msg = card_worker_inproc.authenticate_inprocess("deadbeefdeadbeef", 0, False)
        assert ok is False
        assert msg.startswith("AUTH_FAILED")

    def test_blocked_maps_to_card_blocked(self, monkeypatch):
        scc = self._fake_scc()
        scc.verify_chv.side_effect = Exception("Authentication blocked: 6983")
        self._install_session(monkeypatch, scc)
        self._fake_rt(monkeypatch, scc)
        ok, msg = card_worker_inproc.authenticate_inprocess("3838383838383838", 0, False)
        assert ok is False
        assert msg.startswith("CARD_BLOCKED")

    def test_gialersim_deferred_does_not_call_verify_chv(self, monkeypatch):
        scc = self._fake_scc()
        self._install_session(monkeypatch, scc)
        self._fake_rt(monkeypatch, scc)
        ok, msg = card_worker_inproc.authenticate_inprocess("3838383838383838", 0, True)
        assert ok is True
        assert msg == "DEFERRED:gialersim"
        scc.verify_chv.assert_not_called()

    def test_transport_error_maps_correctly(self, monkeypatch):
        scc = self._fake_scc()
        scc.verify_chv.side_effect = Exception("PCSC connection lost")
        self._install_session(monkeypatch, scc)
        self._fake_rt(monkeypatch, scc)
        ok, msg = card_worker_inproc.authenticate_inprocess("3838383838383838", 0, False)
        assert ok is False
        assert msg.startswith("TRANSPORT_ERROR")


class TestWorkerAuthDelegateRouting:
    """WorkerAuthDelegate routes to inproc or subprocess depending on env var."""

    def test_inprocess_enabled_calls_authenticate_inprocess(self, monkeypatch):
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        called = {}

        def fake_auth_inprocess(adm1_hex, reader_index, is_gialersim):
            called["adm1"] = adm1_hex
            called["reader"] = reader_index
            called["gialersim"] = is_gialersim
            return (True, "")

        monkeypatch.setattr(
            card_worker_inproc, "authenticate_inprocess", fake_auth_inprocess
        )

        delegate = card_worker_process.WorkerAuthDelegate("/fake/pysim", 0, False)
        ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is True
        assert called["adm1"] == "3838383838383838"
        assert called["gialersim"] is False

    def test_inprocess_enabled_gialersim_passes_flag(self, monkeypatch):
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "1")
        called = {}

        def fake_auth_inprocess(adm1_hex, reader_index, is_gialersim):
            called["gialersim"] = is_gialersim
            return (True, "DEFERRED:gialersim")

        monkeypatch.setattr(
            card_worker_inproc, "authenticate_inprocess", fake_auth_inprocess
        )

        delegate = card_worker_process.WorkerAuthDelegate("/fake/pysim", 0, True)
        ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is True
        assert called["gialersim"] is True

    def test_inprocess_disabled_uses_subprocess(self, monkeypatch):
        monkeypatch.setenv("SIMGUI_WORKER_INPROCESS", "0")
        subprocess_calls = []

        def fake_run(*args, **kwargs):
            subprocess_calls.append(args)
            result = mock.MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0
            return result

        monkeypatch.setattr(card_worker_process.subprocess, "run", fake_run)
        monkeypatch.setattr(os.path, "isfile", lambda p: True)

        delegate = card_worker_process.WorkerAuthDelegate("/fake/pysim", 0, False)
        ok, msg = delegate.authenticate_adm("3838383838383838")
        assert ok is True
        assert len(subprocess_calls) == 1


# ---------------------------------------------------------------------------
# Tests: program_delta
# ---------------------------------------------------------------------------

class TestProgramDeltaInproc:
    """Tests for card_worker_inproc.program_delta and writer registry."""

    def _fake_rt(self, monkeypatch):
        rt = mock.MagicMock()
        rt.init_reader.return_value = mock.MagicMock()
        monkeypatch.setattr(card_worker_inproc, "_pysim_runtime", rt)
        return rt

    def _install_session(self, monkeypatch, scc):
        monkeypatch.setitem(card_worker_inproc._session, "sl", object())
        monkeypatch.setitem(card_worker_inproc._session, "scc", scc)
        monkeypatch.setitem(card_worker_inproc._session, "reader_index", 0)

    def test_delta_supported_fields_returns_imsi_and_fplmn(self):
        fields = card_worker_inproc.delta_supported_fields()
        assert "IMSI" in fields
        assert "FPLMN" in fields

    def test_unsupported_field_rejected_write_started_false(self, monkeypatch):
        rt = self._fake_rt(monkeypatch)
        scc = mock.MagicMock()
        self._install_session(monkeypatch, scc)
        rt.card_detect.return_value = mock.MagicMock()
        res = card_worker_inproc.program_delta(
            {"Ki": "aabbcc"}, "3838383838383838", 0, "sysmoISIM-SJA5")
        assert res["write_started"] is False
        assert res["ok"] is False
        assert res["error"] == "UNSUPPORTED_FIELDS"
        assert "Ki" in res["unsupported_fields"]
        scc.verify_chv.assert_not_called()

    def test_fplmn_semicolon_string_parsed_to_list(self, monkeypatch):
        rt = self._fake_rt(monkeypatch)
        scc = mock.MagicMock()
        self._install_session(monkeypatch, scc)
        card = mock.MagicMock()
        card.update_fplmn.return_value = "9000"
        rt.card_detect.return_value = card
        res = card_worker_inproc.program_delta(
            {"FPLMN": "24001;24201"}, "3838383838383838", 0, "auto")
        assert res["ok"] is True
        card.update_fplmn.assert_called_once_with(["24001", "24201"])

    def test_successful_delta_writes_only_changed_fields(self, monkeypatch):
        rt = self._fake_rt(monkeypatch)
        scc = mock.MagicMock()
        self._install_session(monkeypatch, scc)
        card = mock.MagicMock()
        card.update_imsi.return_value = "9000"
        rt.card_detect.return_value = card
        res = card_worker_inproc.program_delta(
            {"IMSI": "001010123456789"}, "3838383838383838", 0, "sysmoISIM-SJA5")
        assert res["ok"] is True
        assert res["write_started"] is True
        assert "IMSI" in res["written_fields"]
        assert res["failed_fields"] == []
        card.update_imsi.assert_called_once_with("001010123456789")
        card.update_fplmn.assert_not_called()

    def test_writer_non9000_sets_failed_fields(self, monkeypatch):
        rt = self._fake_rt(monkeypatch)
        scc = mock.MagicMock()
        self._install_session(monkeypatch, scc)
        card = mock.MagicMock()
        card.update_imsi.return_value = "6982"
        rt.card_detect.return_value = card
        res = card_worker_inproc.program_delta(
            {"IMSI": "001010123456789"}, "3838383838383838", 0, "sysmoISIM-SJA5")
        assert res["ok"] is False
        assert res["write_started"] is True
        assert "IMSI" in res["failed_fields"]
        assert "IMSI" not in res["written_fields"]
