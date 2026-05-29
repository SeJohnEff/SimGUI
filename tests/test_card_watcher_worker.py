"""Tests for CardWatcher optional worker-backed probe path (Phase 2C)."""

import pytest
from unittest.mock import MagicMock

from managers.card_watcher import CardWatcher
from card_worker_client import (
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
    def __init__(self, result=None, raises=None):
        self.probe_calls = 0
        self._result = result
        self._raises = raises

    def probe(self, **kwargs):
        self.probe_calls += 1
        if self._raises is not None:
            raise self._raises
        return self._result

    def set_result(self, result):
        self._result = result

    def set_raises(self, exc):
        self._raises = exc
        self._result = None


def make_watcher(worker=None, cm=None):
    if cm is None:
        cm = FakeCardManager()
    return CardWatcher(cm, worker_client=worker), cm


# ---------------------------------------------------------------------------
# Test 1: worker path selected — card_manager.probe_card_presence NOT called
# ---------------------------------------------------------------------------

def test_worker_path_selected():
    worker = FakeWorker(result=ProbeResult(present=False, msg='No card in reader'))
    watcher, cm = make_watcher(worker=worker)
    watcher._check_once()
    assert worker.probe_calls == 1
    assert cm.probe_calls == 0


# ---------------------------------------------------------------------------
# Test 2: same card_gen while already present does not re-read
# ---------------------------------------------------------------------------

def test_same_card_gen_no_reread():
    gen = "gen-abc"
    worker = FakeWorker(result=ProbeResult(present=True, atr="3B 9F", card_gen=gen))
    watcher, cm = make_watcher(worker=worker)

    reads = []
    watcher.on_card_unknown = lambda iccid: reads.append(iccid)

    # First probe — new card
    cm.iccid = None
    cm.detect_ok = True
    watcher._check_once()
    first_count = len(reads)

    # Second probe — same card_gen
    watcher._check_once()
    assert len(reads) == first_count  # no additional read


# ---------------------------------------------------------------------------
# Test 3: new card_gen triggers new read
# ---------------------------------------------------------------------------

def test_new_card_gen_triggers_read():
    worker = FakeWorker(result=ProbeResult(present=True, atr="3B 9F", card_gen="gen-1"))
    watcher, cm = make_watcher(worker=worker)
    cm.iccid = None
    cm.detect_ok = True

    reads = []
    watcher.on_card_unknown = lambda iccid: reads.append(iccid)

    watcher._check_once()
    assert len(reads) == 1

    # Different card_gen
    worker.set_result(ProbeResult(present=True, atr="3B 9F", card_gen="gen-2"))
    watcher._check_once()
    assert len(reads) == 2


# ---------------------------------------------------------------------------
# Test 4: card_gen None falls back to ATR dedupe behavior
# ---------------------------------------------------------------------------

def test_card_gen_none_falls_back_to_atr():
    worker = FakeWorker(result=ProbeResult(present=True, atr="3B 9F 96", card_gen=None))
    watcher, cm = make_watcher(worker=worker)
    cm.iccid = None
    cm.detect_ok = True

    reads = []
    watcher.on_card_unknown = lambda iccid: reads.append(iccid)

    # First probe — triggers read
    watcher._check_once()
    assert len(reads) == 1

    # Same ATR, card_gen=None — existing ATR dedup suppresses re-read
    watcher._check_once()
    assert len(reads) == 1

    # Different ATR with card_gen=None — triggers new read
    worker.set_result(ProbeResult(present=True, atr="00 11 22", card_gen=None))
    watcher._check_once()
    assert len(reads) == 2


# ---------------------------------------------------------------------------
# Test 5: result.error PROBE_TIMEOUT — on_error, _card_present preserved, no removal
# ---------------------------------------------------------------------------

def test_probe_timeout_calls_on_error_preserves_state():
    worker = FakeWorker(result=ProbeResult(present=True, atr="3B", card_gen="g1"))
    watcher, cm = make_watcher(worker=worker)
    cm.iccid = None
    cm.detect_ok = True
    watcher._check_once()  # card becomes present
    assert watcher._card_present

    errors = []
    removals = []
    watcher.on_error = lambda msg: errors.append(msg)
    watcher.on_card_removed = lambda: removals.append(True)

    worker.set_result(ProbeResult(present=False, error='PROBE_TIMEOUT', msg='timed out'))
    watcher._check_once()

    assert len(errors) == 1
    assert len(removals) == 0
    assert watcher._card_present is True


# ---------------------------------------------------------------------------
# Test 6: WorkerTimeoutError — same as PROBE_TIMEOUT
# ---------------------------------------------------------------------------

def test_worker_timeout_error_preserves_state():
    worker = FakeWorker(result=ProbeResult(present=True, atr="3B", card_gen="g1"))
    watcher, cm = make_watcher(worker=worker)
    cm.iccid = None
    cm.detect_ok = True
    watcher._check_once()
    assert watcher._card_present

    errors = []
    removals = []
    watcher.on_error = lambda msg: errors.append(msg)
    watcher.on_card_removed = lambda: removals.append(True)

    worker.set_raises(WorkerTimeoutError("probe", 2.0))
    watcher._check_once()

    assert len(errors) == 1
    assert len(removals) == 0
    assert watcher._card_present is True


# ---------------------------------------------------------------------------
# Test 7: WorkerCrashError — on_error, does NOT fall back to native probe
# ---------------------------------------------------------------------------

def test_worker_crash_calls_on_error_no_native_fallback():
    worker = FakeWorker(raises=WorkerCrashError(1))
    watcher, cm = make_watcher(worker=worker)

    errors = []
    watcher.on_error = lambda msg: errors.append(msg)

    watcher._check_once()

    assert len(errors) == 1
    assert watcher._worker_client is worker  # not cleared
    assert cm.probe_calls == 0              # native path not called


# ---------------------------------------------------------------------------
# Test 8: WorkerEOFError — on_error, does NOT fall back to native probe
# ---------------------------------------------------------------------------

def test_worker_eof_calls_on_error_no_native_fallback():
    worker = FakeWorker(raises=WorkerEOFError())
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
    worker = FakeWorker(result=ProbeResult(present=True, atr="3B", card_gen="g1"))
    watcher, cm = make_watcher(worker=worker)
    cm.iccid = None
    cm.detect_ok = True
    watcher._check_once()
    assert watcher._last_card_gen == "g1"

    ready = []
    watcher.on_reader_ready = lambda: ready.append(True)
    watcher.on_card_removed = lambda: None

    worker.set_result(ProbeResult(present=False, msg='No card in reader'))
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
