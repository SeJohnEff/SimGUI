"""Tests for CardWatcher optional worker-backed probe path (Phase 2C)."""

import pytest
from unittest.mock import MagicMock

from managers.card_watcher import CardWatcher
from card_worker_client import (
    DetectResult,
    ProbeResult,
    WorkerCrashError,
    WorkerEOFError,
    WorkerTimeoutError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeCardManager:
    def __init__(self):
        self.probe_calls = 0
        self.detect_ok = True
        self.iccid = "1234567890123456789"

    def probe_card_presence(self):
        self.probe_calls += 1
        return True, "3B 9F 96 80 1F"

    def detect_card(self):
        return self.detect_ok, "ok"

    def read_iccid(self):
        return self.iccid

    def reset_pyscard(self):
        pass


class FakeWorker:
    def __init__(self, result=None, raises=None, detect_result=None, ready=True):
        self.probe_calls = 0
        self.detect_calls = 0           # legacy; kept for tests that still check it
        self.detect_inprocess_calls = 0
        self._result = result
        self._raises = raises
        self._detect_result = detect_result
        self._detect_raises = None
        self._ready = ready

    def is_ready(self):
        return self._ready

    def capabilities(self):
        return ["detect_inprocess"]

    def probe(self, **kwargs):
        self.probe_calls += 1
        if self._raises is not None:
            raise self._raises
        return self._result

    def detect_inprocess(self, **kwargs):
        self.detect_inprocess_calls += 1
        if self._detect_raises is not None:
            raise self._detect_raises
        if self._detect_result is not None:
            return self._detect_result
        return DetectResult(ok=True, blank=True)

    def detect(self, **kwargs):
        self.detect_calls += 1
        if self._detect_raises is not None:
            raise self._detect_raises
        if self._detect_result is not None:
            return self._detect_result
        return DetectResult(ok=True, blank=True)

    def set_result(self, result):
        self._result = result

    def set_raises(self, exc):
        self._raises = exc
        self._result = None

    def set_detect_result(self, result):
        self._detect_result = result

    def set_detect_raises(self, exc):
        self._detect_raises = exc


def make_watcher(worker=None, cm=None, pysim_path=None):
    if cm is None:
        cm = FakeCardManager()
    return CardWatcher(cm, worker_client=worker, pysim_path=pysim_path), cm


# ---------------------------------------------------------------------------
# Test 1: worker path selected — card_manager.probe_card_presence NOT called
# ---------------------------------------------------------------------------

def test_worker_path_selected():
    # New architecture: detect_inprocess is called directly; probe() is never used.
    worker = FakeWorker()
    worker._detect_result = DetectResult(ok=False, error='NO_CARD', msg='No card in reader')
    watcher, cm = make_watcher(worker=worker)
    watcher._check_once()
    assert worker.probe_calls == 0
    assert worker.detect_inprocess_calls == 1
    assert cm.probe_calls == 0


# ---------------------------------------------------------------------------
# Test 2: same card_gen while already present does not re-read
# ---------------------------------------------------------------------------

def test_same_card_gen_no_reread():
    gen = "gen-abc"
    worker = FakeWorker(detect_result=DetectResult(ok=True, blank=True, card_gen=gen))
    watcher, cm = make_watcher(worker=worker)

    reads = []
    watcher.on_card_unknown = lambda iccid: reads.append(iccid)

    # First call — new card
    watcher._check_once()
    first_count = len(reads)

    # Second call — same card_gen, card already present
    watcher._check_once()
    assert len(reads) == first_count  # no additional read


# ---------------------------------------------------------------------------
# Test 3: new card_gen triggers new read
# ---------------------------------------------------------------------------

def test_new_card_gen_triggers_read():
    worker = FakeWorker(detect_result=DetectResult(ok=True, blank=True, card_gen="gen-1"))
    watcher, cm = make_watcher(worker=worker)

    reads = []
    watcher.on_card_unknown = lambda iccid: reads.append(iccid)

    watcher._check_once()
    assert len(reads) == 1

    # Different card_gen — triggers new read
    worker.set_detect_result(DetectResult(ok=True, blank=True, card_gen="gen-2"))
    watcher._check_once()
    assert len(reads) == 2


# ---------------------------------------------------------------------------
# Test 4: card_gen None falls back to ATR dedupe behavior
# ---------------------------------------------------------------------------

def test_card_gen_none_falls_back_to_atr():
    # card_gen=None: after first read, same result suppressed because
    # _card_present=True and new_gen==old_gen==None and not _last_read_failed.
    worker = FakeWorker(detect_result=DetectResult(ok=True, blank=True, card_gen=None))
    watcher, cm = make_watcher(worker=worker)

    reads = []
    watcher.on_card_unknown = lambda iccid: reads.append(iccid)

    # First call — triggers read
    watcher._check_once()
    assert len(reads) == 1

    # Second call — card_gen=None, already present, not failed — suppressed
    watcher._check_once()
    assert len(reads) == 1

    # _last_read_failed=True forces re-read even with same card_gen=None
    watcher._last_read_failed = True
    watcher._check_once()
    assert len(reads) == 2


# ---------------------------------------------------------------------------
# Test 5: WorkerTimeoutError during detect — on_error, _card_present preserved, no removal
# ---------------------------------------------------------------------------

def test_probe_timeout_calls_on_error_preserves_state():
    worker = FakeWorker(detect_result=DetectResult(ok=True, blank=True))
    watcher, cm = make_watcher(worker=worker)
    watcher._check_once()  # card becomes present
    assert watcher._card_present

    errors = []
    removals = []
    watcher.on_error = lambda msg: errors.append(msg)
    watcher.on_card_removed = lambda: removals.append(True)

    worker.set_detect_raises(WorkerTimeoutError("detect_inprocess", 30.0))
    watcher._check_once()

    assert len(errors) == 1
    assert len(removals) == 0
    assert watcher._card_present is True


# ---------------------------------------------------------------------------
# Test 6: WorkerEOFError during detect — on_error, _card_present preserved, no removal
# ---------------------------------------------------------------------------

def test_worker_timeout_error_preserves_state():
    worker = FakeWorker(detect_result=DetectResult(ok=True, blank=True))
    watcher, cm = make_watcher(worker=worker)
    watcher._check_once()
    assert watcher._card_present

    errors = []
    removals = []
    watcher.on_error = lambda msg: errors.append(msg)
    watcher.on_card_removed = lambda: removals.append(True)

    worker.set_detect_raises(WorkerEOFError())
    watcher._check_once()

    assert len(errors) == 1
    assert len(removals) == 0
    assert watcher._card_present is True


# ---------------------------------------------------------------------------
# Test 7: WorkerCrashError in detect_inprocess — on_error, no native fallback
# ---------------------------------------------------------------------------

def test_worker_crash_calls_on_error_no_native_fallback():
    worker = FakeWorker()
    worker.set_detect_raises(WorkerCrashError(1))
    watcher, cm = make_watcher(worker=worker)

    errors = []
    watcher.on_error = lambda msg: errors.append(msg)

    watcher._check_once()

    assert len(errors) == 1
    assert watcher._worker_client is worker  # not cleared
    assert cm.probe_calls == 0              # native path not called


# ---------------------------------------------------------------------------
# Test 8: WorkerEOFError in detect_inprocess — on_error, no native fallback
# ---------------------------------------------------------------------------

def test_worker_eof_calls_on_error_no_native_fallback():
    worker = FakeWorker()
    worker.set_detect_raises(WorkerEOFError())
    watcher, cm = make_watcher(worker=worker)

    errors = []
    watcher.on_error = lambda msg: errors.append(msg)

    watcher._check_once()

    assert len(errors) == 1
    assert watcher._worker_client is worker  # not cleared
    assert cm.probe_calls == 0


# ---------------------------------------------------------------------------
# Test 9: present=False "No card in reader" clears _last_card_gen, existing handling
# ---------------------------------------------------------------------------

def test_no_card_clears_last_card_gen():
    worker = FakeWorker(detect_result=DetectResult(ok=True, blank=True, card_gen="g1"))
    watcher, cm = make_watcher(worker=worker)
    watcher._check_once()
    assert watcher._last_card_gen == "g1"

    ready = []
    watcher.on_reader_ready = lambda: ready.append(True)
    watcher.on_card_removed = lambda: None

    worker.set_detect_result(DetectResult(ok=False, error='NO_CARD', msg='No card in reader'))
    # blank card debounce requires two consecutive absent probes
    watcher._check_once()
    watcher._check_once()

    assert watcher._last_card_gen is None


# ---------------------------------------------------------------------------
# Test 10: worker_client=None uses native card_manager.probe_card_presence
# ---------------------------------------------------------------------------

def test_no_worker_uses_native_path():
    cm = FakeCardManager()
    watcher = CardWatcher(cm)  # no worker_client

    watcher._check_once()

    assert cm.probe_calls == 1


# ---------------------------------------------------------------------------
# Test 11: pysim_path forwarded to worker detect
# ---------------------------------------------------------------------------

def test_pysim_path_forwarded_to_detect_inprocess():
    calls = []

    class TrackingWorker(FakeWorker):
        def detect_inprocess(self, **kwargs):
            calls.append(kwargs.copy())
            return DetectResult(ok=True, blank=True)

    worker = TrackingWorker()
    watcher, _ = make_watcher(worker=worker, pysim_path="/opt/pysim")
    watcher._check_once()

    assert len(calls) == 1
    assert calls[0]["pysim_path"] == "/opt/pysim"
    # session_id is always None in the new probe-free path
    assert calls[0]["session_id"] is None
    # card_gen reflects _last_card_gen (None on first call)
    assert calls[0]["card_gen"] is None


# ---------------------------------------------------------------------------
# Test 12: detect returns ok=True, non-blank with ICCID → on_card_unknown (no index)
# ---------------------------------------------------------------------------

def test_worker_detect_iccid_fires_handle_new_card():
    iccid = "8946101234567890001"
    worker = FakeWorker(
        result=ProbeResult(present=True, atr="3B", card_gen="g1"),
        detect_result=DetectResult(ok=True, blank=False, fields={"ICCID": iccid}),
    )
    watcher, _ = make_watcher(worker=worker)

    unknown = []
    watcher.on_card_unknown = lambda x: unknown.append(x)

    watcher._check_once()

    assert len(unknown) == 1
    assert unknown[0] == iccid
    assert watcher._last_iccid == iccid
    assert watcher._last_read_failed is False


# ---------------------------------------------------------------------------
# Test 13: detect returns ok=True, blank → on_card_unknown("")
# ---------------------------------------------------------------------------

def test_worker_detect_blank_fires_on_card_unknown_empty():
    worker = FakeWorker(
        result=ProbeResult(present=True, atr="3B", card_gen="g1"),
        detect_result=DetectResult(ok=True, blank=True),
    )
    watcher, _ = make_watcher(worker=worker)

    unknown = []
    watcher.on_card_unknown = lambda x: unknown.append(x)

    watcher._check_once()

    assert unknown == [""]
    assert watcher._last_iccid is None
    assert watcher._last_read_failed is False


# ---------------------------------------------------------------------------
# Test 14: detect returns ok=True, non-blank, no ICCID → on_error, _last_read_failed
# ---------------------------------------------------------------------------

def test_worker_detect_no_iccid_calls_on_error():
    worker = FakeWorker(
        result=ProbeResult(present=True, atr="3B", card_gen="g1"),
        detect_result=DetectResult(ok=True, blank=False, fields={}),
    )
    watcher, _ = make_watcher(worker=worker)

    errors = []
    watcher.on_error = lambda msg: errors.append(msg)

    watcher._check_once()

    assert len(errors) == 1
    assert watcher._last_read_failed is True


# ---------------------------------------------------------------------------
# Test 15: detect returns ok=False (non-STALE) → on_error, _last_read_failed
# ---------------------------------------------------------------------------

def test_worker_detect_failure_calls_on_error():
    worker = FakeWorker(
        result=ProbeResult(present=True, atr="3B", card_gen="g1"),
        detect_result=DetectResult(ok=False, msg="pySim-read crashed"),
    )
    watcher, _ = make_watcher(worker=worker)

    errors = []
    watcher.on_error = lambda msg: errors.append(msg)

    watcher._check_once()

    assert len(errors) == 1
    assert "pySim-read crashed" in errors[0]
    assert watcher._last_read_failed is True


# ---------------------------------------------------------------------------
# Test 16: detect returns STALE_SESSION → _last_card_gen=None, on_error
# ---------------------------------------------------------------------------

def test_worker_detect_stale_session_clears_card_gen():
    worker = FakeWorker(
        result=ProbeResult(present=True, atr="3B", card_gen="g1"),
        detect_result=DetectResult(ok=False, error="STALE_SESSION", msg="stale"),
    )
    watcher, _ = make_watcher(worker=worker)

    errors = []
    watcher.on_error = lambda msg: errors.append(msg)

    watcher._check_once()

    assert watcher._last_card_gen is None
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# Test 17: WorkerTimeoutError in detect → _last_read_failed, on_error, no clear
# ---------------------------------------------------------------------------

def test_worker_detect_timeout_sets_read_failed():
    worker = FakeWorker(result=ProbeResult(present=True, atr="3B", card_gen="g1"))
    worker.set_detect_raises(WorkerTimeoutError("detect", 30.0))
    watcher, cm = make_watcher(worker=worker)

    errors = []
    watcher.on_error = lambda msg: errors.append(msg)

    watcher._check_once()

    assert len(errors) == 1
    assert watcher._last_read_failed is True
    assert watcher._worker_client is worker  # not cleared
    assert cm.probe_calls == 0


# ---------------------------------------------------------------------------
# Test 18: WorkerCrashError in detect → _last_read_failed, no native fallback
# ---------------------------------------------------------------------------

def test_worker_detect_crash_no_native_fallback():
    worker = FakeWorker(result=ProbeResult(present=True, atr="3B", card_gen="g1"))
    worker.set_detect_raises(WorkerCrashError(1))
    watcher, cm = make_watcher(worker=worker)

    errors = []
    watcher.on_error = lambda msg: errors.append(msg)

    watcher._check_once()

    assert len(errors) == 1
    assert watcher._last_read_failed is True
    assert watcher._worker_client is worker  # not cleared
    assert cm.probe_calls == 0              # native path not called


# ---------------------------------------------------------------------------
# Test 22: _worker_read_and_notify uses detect_inprocess when capability present
# ---------------------------------------------------------------------------

def test_worker_read_uses_detect_inprocess_when_available():
    worker = FakeWorker(
        result=ProbeResult(present=True, atr="3B", card_gen="g1", session_id="sid1"),
        detect_result=DetectResult(ok=True, blank=True),
    )
    worker.detect_inprocess_calls = 0

    def fake_detect_inprocess(**kwargs):
        worker.detect_inprocess_calls += 1
        return DetectResult(ok=True, blank=True)

    worker.detect_inprocess = fake_detect_inprocess
    worker.capabilities = lambda: ["detect", "detect_inprocess", "read_fields"]

    watcher, _ = make_watcher(worker=worker)
    watcher.on_card_unknown = lambda x: None
    watcher._check_once()

    assert worker.detect_inprocess_calls == 1
    assert worker.detect_calls == 0


# ---------------------------------------------------------------------------
# Test 23: _worker_read_and_notify fires on_error when detect_inprocess absent
# ---------------------------------------------------------------------------

def test_worker_read_fires_error_when_detect_inprocess_absent():
    worker = FakeWorker(
        result=ProbeResult(present=True, atr="3B", card_gen="g1", session_id="sid1"),
        detect_result=DetectResult(ok=True, blank=True),
    )
    worker.capabilities = lambda: []  # detect_inprocess not advertised

    errors = []
    watcher, _ = make_watcher(worker=worker)
    watcher.on_error = errors.append
    watcher._check_once()

    assert worker.detect_calls == 0
    assert worker.detect_inprocess_calls == 0
    assert watcher._last_read_failed is True
    assert any("not available" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 24: _worker_read_and_notify skips detect when worker not ready
# ---------------------------------------------------------------------------

def test_worker_read_skips_detect_when_not_ready():
    worker = FakeWorker(
        result=ProbeResult(present=True, atr="3B", card_gen="g1", session_id="sid1"),
        detect_result=DetectResult(ok=True, blank=True),
        ready=False,
    )
    watcher, _ = make_watcher(worker=worker)

    errors = []
    watcher.on_error = errors.append
    watcher._check_once()

    assert worker.detect_calls == 0
    assert watcher._last_read_failed is True
    assert len(errors) == 1
    assert "not ready" in errors[0].lower()
