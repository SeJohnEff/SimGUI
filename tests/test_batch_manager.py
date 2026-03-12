"""Tests for managers.batch_manager module."""

import threading
import time

import pytest
from managers.batch_manager import BatchManager, BatchState, CardResult
from managers.card_manager import CardManager


@pytest.fixture
def batch_card_manager():
    """CardManager in simulator mode for batch tests."""
    cm = CardManager()
    cm.enable_simulator()
    return cm


@pytest.fixture
def batch_manager(batch_card_manager):
    return BatchManager(batch_card_manager)


def _make_batch(count: int) -> list:
    """Generate a simple batch of card dicts."""
    cards = []
    for i in range(count):
        iccid = f"8999900000000000{i:04d}"
        cards.append({
            "ICCID": iccid,
            "IMSI": f"99999000000{i:04d}",
            "ADM1": "4444444444444444",
            "SPN": "Test",
        })
    return cards


class TestBatchManagerInit:
    def test_initial_state(self, batch_manager):
        assert batch_manager.state == BatchState.IDLE
        assert batch_manager.results == []
        assert batch_manager.total == 0
        assert batch_manager.current == 0

    def test_success_fail_counts_empty(self, batch_manager):
        assert batch_manager.success_count == 0
        assert batch_manager.fail_count == 0


class TestCardResult:
    def test_creation(self):
        r = CardResult(0, "89123", True, "OK")
        assert r.index == 0
        assert r.iccid == "89123"
        assert r.success is True
        assert r.message == "OK"

    def test_failure(self):
        r = CardResult(3, "89456", False, "Auth failed")
        assert r.success is False
        assert "Auth" in r.message


class TestBatchExecution:
    def test_run_batch_simulator(self, batch_manager):
        """Run a small batch in simulator mode and verify completion."""
        batch = _make_batch(3)
        completed = threading.Event()
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        completed.wait(timeout=10)
        assert batch_manager.state == BatchState.COMPLETED
        assert batch_manager.total == 3
        assert len(batch_manager.results) == 3

    def test_results_have_iccid(self, batch_manager):
        batch = _make_batch(2)
        completed = threading.Event()
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        completed.wait(timeout=10)
        for r in batch_manager.results:
            assert r.iccid != ""

    def test_progress_callback(self, batch_manager):
        batch = _make_batch(3)
        progress_calls = []
        completed = threading.Event()
        batch_manager.on_progress = lambda c, t, m: progress_calls.append((c, t, m))
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        completed.wait(timeout=10)
        assert len(progress_calls) == 3
        for cur, total, msg in progress_calls:
            assert total == 3

    def test_card_result_callback(self, batch_manager):
        batch = _make_batch(2)
        results_cb = []
        completed = threading.Event()
        batch_manager.on_card_result = lambda r: results_cb.append(r)
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        completed.wait(timeout=10)
        assert len(results_cb) == 2

    def test_empty_batch(self, batch_manager):
        completed = threading.Event()
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start([])
        completed.wait(timeout=5)
        assert batch_manager.state == BatchState.COMPLETED
        assert batch_manager.results == []


class TestBatchAbort:
    def test_abort_stops_batch(self, batch_manager):
        batch = _make_batch(100)
        completed = threading.Event()
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        time.sleep(0.1)
        batch_manager.abort()
        completed.wait(timeout=10)
        assert batch_manager.state == BatchState.ABORTED
        assert len(batch_manager.results) < 100


class TestBatchPause:
    def test_pause_resume(self, batch_manager):
        batch = _make_batch(5)
        completed = threading.Event()
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        batch_manager.pause()
        assert batch_manager.state == BatchState.PAUSED
        time.sleep(0.1)
        batch_manager.resume()
        completed.wait(timeout=10)
        assert batch_manager.state == BatchState.COMPLETED

    def test_pause_blocks_abort_unblocks(self, batch_manager):
        batch = _make_batch(20)
        completed = threading.Event()
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        time.sleep(0.05)
        batch_manager.pause()
        time.sleep(0.1)
        batch_manager.abort()
        completed.wait(timeout=10)
        assert batch_manager.state == BatchState.ABORTED


class TestBatchProperties:
    def test_total_property(self, batch_manager):
        batch = _make_batch(5)
        completed = threading.Event()
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        completed.wait(timeout=10)
        assert batch_manager.total == 5

    def test_success_fail_count(self, batch_manager):
        batch = _make_batch(3)
        completed = threading.Event()
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        completed.wait(timeout=10)
        assert batch_manager.success_count + batch_manager.fail_count == 3


class TestBatchStateTransitions:
    def test_cannot_start_while_running(self, batch_manager):
        batch = _make_batch(50)
        completed = threading.Event()
        batch_manager.on_completed = lambda: completed.set()
        batch_manager.start(batch)
        # Trying to start again should be a no-op
        batch_manager.start(_make_batch(5))
        # Total should still be 50 from first call
        assert batch_manager.total == 50
        batch_manager.abort()
        completed.wait(timeout=10)
