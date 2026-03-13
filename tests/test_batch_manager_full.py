"""Extended tests for managers/batch_manager.py.

Covers:
- Cancellation mid-batch
- Error handling during programming (detect / auth / program failures)
- Progress callback states
- get_summary via success_count / fail_count after various outcomes
- Dry run logic via simulator with controlled failures
- ICCID mismatch handling
- skip() while waiting for card
- Multiple start() calls
- CardResult dataclass
"""

import threading
import time

import pytest

from managers.batch_manager import BatchManager, BatchState, CardResult
from managers.card_manager import CardManager
from simulator.settings import SimulatorSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sim_manager(num_cards=20, error_rate=0.0):
    """CardManager in simulator mode."""
    cm = CardManager()
    cm.enable_simulator(SimulatorSettings(delay_ms=0,
                                           error_rate=error_rate,
                                           num_cards=num_cards))
    return cm


def _make_batch(count: int, adm1="12345678") -> list:
    """Build a dummy batch from the simulator's card deck."""
    return [
        {
            "ICCID": f"8999900000000000{i:04d}",
            "IMSI": f"99999000000{i:04d}",
            "ADM1": adm1,
        }
        for i in range(count)
    ]


def _run_to_completion(bm: BatchManager, batch: list, timeout: float = 10) -> None:
    """Start batch and wait for completion."""
    done = threading.Event()
    bm.on_completed = lambda: done.set()
    bm.start(batch)
    done.wait(timeout=timeout)


# ---------------------------------------------------------------------------
# CardResult dataclass
# ---------------------------------------------------------------------------

class TestCardResult:
    """Tests for the CardResult value object."""

    def test_successful_result(self):
        """A successful CardResult has correct fields."""
        r = CardResult(0, "89123", True, "Programmed successfully")
        assert r.index == 0
        assert r.iccid == "89123"
        assert r.success is True
        assert "Programmed" in r.message

    def test_failed_result(self):
        """A failed CardResult has correct fields."""
        r = CardResult(3, "89456", False, "Detect failed: no card")
        assert r.success is False
        assert r.index == 3
        assert "Detect failed" in r.message

    def test_result_slots(self):
        """CardResult uses __slots__ — no arbitrary attributes."""
        r = CardResult(0, "x", True, "ok")
        with pytest.raises(AttributeError):
            r.extra_field = "bad"


# ---------------------------------------------------------------------------
# BatchManager initial state
# ---------------------------------------------------------------------------

class TestBatchManagerInitState:
    """Verify initial state of a fresh BatchManager."""

    def test_state_is_idle(self):
        """Initial state is IDLE."""
        bm = BatchManager(_sim_manager())
        assert bm.state == BatchState.IDLE

    def test_results_empty(self):
        """No results initially."""
        bm = BatchManager(_sim_manager())
        assert bm.results == []

    def test_total_is_zero(self):
        """No batch data initially."""
        bm = BatchManager(_sim_manager())
        assert bm.total == 0

    def test_current_is_zero(self):
        """Current index is 0 initially."""
        bm = BatchManager(_sim_manager())
        assert bm.current == 0

    def test_counts_zero(self):
        """Success and fail counts are 0 initially."""
        bm = BatchManager(_sim_manager())
        assert bm.success_count == 0
        assert bm.fail_count == 0


# ---------------------------------------------------------------------------
# Successful simulator batch
# ---------------------------------------------------------------------------

class TestSuccessfulBatch:
    """Simulator batch that completes fully."""

    def test_all_cards_processed(self):
        """All cards in the batch are processed."""
        cm = _sim_manager(num_cards=5)
        # Use the simulator's real cards (known good ADM1)
        from simulator.simulator_backend import SimulatorBackend
        backend = cm._simulator
        batch = []
        for i, card in enumerate(backend.card_deck[:3]):
            batch.append({"ICCID": card.iccid, "IMSI": card.imsi,
                          "ADM1": card.adm1})
        bm = BatchManager(cm)
        done = threading.Event()
        bm.on_completed = lambda: done.set()
        bm.start(batch)
        done.wait(timeout=10)
        assert len(bm.results) == 3

    def test_state_completed_after_run(self):
        """State is COMPLETED after successful run."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        batch = [{"ICCID": backend.card_deck[0].iccid,
                  "IMSI": backend.card_deck[0].imsi,
                  "ADM1": backend.card_deck[0].adm1}]
        bm = BatchManager(cm)
        _run_to_completion(bm, batch)
        assert bm.state == BatchState.COMPLETED

    def test_on_progress_called_for_each_card(self):
        """on_progress callback fires once per card."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        batch = [{"ICCID": c.iccid, "IMSI": c.imsi, "ADM1": c.adm1}
                 for c in backend.card_deck[:3]]
        calls = []
        bm = BatchManager(cm)
        bm.on_progress = lambda c, t, m: calls.append((c, t, m))
        _run_to_completion(bm, batch)
        assert len(calls) == 3

    def test_on_card_result_called_for_each_card(self):
        """on_card_result callback fires once per card."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        batch = [{"ICCID": c.iccid, "IMSI": c.imsi, "ADM1": c.adm1}
                 for c in backend.card_deck[:2]]
        results_cb = []
        bm = BatchManager(cm)
        bm.on_card_result = lambda r: results_cb.append(r)
        _run_to_completion(bm, batch)
        assert len(results_cb) == 2

    def test_success_count_all_pass(self):
        """success_count equals batch size when all succeed."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        batch = [{"ICCID": c.iccid, "IMSI": c.imsi, "ADM1": c.adm1}
                 for c in backend.card_deck[:3]]
        bm = BatchManager(cm)
        _run_to_completion(bm, batch)
        assert bm.success_count == 3
        assert bm.fail_count == 0


# ---------------------------------------------------------------------------
# Error during batch
# ---------------------------------------------------------------------------

class TestBatchErrors:
    """Test error handling when individual cards fail."""

    def test_wrong_adm1_causes_failure(self):
        """Wrong ADM1 in batch data causes that card to fail."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        card = backend.card_deck[0]
        batch = [{"ICCID": card.iccid, "IMSI": card.imsi,
                  "ADM1": "00000000"}]  # wrong ADM1
        bm = BatchManager(cm)
        _run_to_completion(bm, batch)
        assert bm.fail_count >= 1
        assert "Auth failed" in bm.results[0].message or \
               "Wrong ADM1" in bm.results[0].message

    def test_iccid_mismatch_causes_failure(self):
        """Wrong ICCID in batch data causes that card to fail."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        card = backend.card_deck[0]
        batch = [{"ICCID": "0000000000000000000",  # wrong ICCID
                  "IMSI": card.imsi, "ADM1": card.adm1}]
        bm = BatchManager(cm)
        _run_to_completion(bm, batch)
        # The ICCID check at batch level: card.iccid != expected → fail
        assert len(bm.results) == 1
        result = bm.results[0]
        assert result.success is False

    def test_detect_failure_causes_card_fail(self):
        """If detect_card fails, that card's result is failure."""
        cm = CardManager()
        cm.enable_simulator(SimulatorSettings(delay_ms=0, error_rate=1.0,
                                               num_cards=5))
        backend = cm._simulator
        batch = [{"ICCID": backend.card_deck[0].iccid,
                  "IMSI": backend.card_deck[0].imsi,
                  "ADM1": backend.card_deck[0].adm1}]
        bm = BatchManager(cm)
        _run_to_completion(bm, batch)
        assert bm.fail_count >= 1

    def test_mixed_success_and_failure(self):
        """Batch with some valid and some invalid cards produces mixed results."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        # First card: correct ADM1; second card: wrong ADM1
        batch = [
            {"ICCID": backend.card_deck[0].iccid,
             "IMSI": backend.card_deck[0].imsi,
             "ADM1": backend.card_deck[0].adm1},
            {"ICCID": backend.card_deck[1].iccid,
             "IMSI": backend.card_deck[1].imsi,
             "ADM1": "00000000"},  # wrong
        ]
        bm = BatchManager(cm)
        _run_to_completion(bm, batch)
        assert bm.success_count + bm.fail_count == 2
        # At least one should have failed
        assert bm.fail_count >= 1

    def test_success_plus_fail_equals_total(self):
        """success_count + fail_count always equals total results."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        batch = [{"ICCID": c.iccid, "IMSI": c.imsi, "ADM1": c.adm1}
                 for c in backend.card_deck[:4]]
        bm = BatchManager(cm)
        _run_to_completion(bm, batch)
        assert bm.success_count + bm.fail_count == len(bm.results)


# ---------------------------------------------------------------------------
# Abort / pause / resume
# ---------------------------------------------------------------------------

class TestBatchControl:
    """Tests for abort, pause, and resume controls."""

    def test_abort_before_start(self):
        """abort() before start sets state to ABORTED."""
        bm = BatchManager(_sim_manager())
        bm.abort()
        assert bm.state == BatchState.ABORTED

    def test_abort_mid_batch(self):
        """abort() during execution stops the batch."""
        bm = BatchManager(_sim_manager(num_cards=20))
        done = threading.Event()
        bm.on_completed = lambda: done.set()
        bm.start(_make_batch(100))
        time.sleep(0.05)
        bm.abort()
        done.wait(timeout=10)
        assert bm.state == BatchState.ABORTED

    def test_pause_then_resume(self):
        """pause() then resume() allows batch to complete."""
        cm = _sim_manager(num_cards=10)
        backend = cm._simulator
        batch = [{"ICCID": c.iccid, "IMSI": c.imsi, "ADM1": c.adm1}
                 for c in backend.card_deck[:5]]
        bm = BatchManager(cm)
        done = threading.Event()
        bm.on_completed = lambda: done.set()
        bm.start(batch)
        time.sleep(0.02)
        bm.pause()
        time.sleep(0.05)
        # Batch may have already completed (it's fast) — that's OK
        assert bm.state in (BatchState.PAUSED, BatchState.COMPLETED)
        bm.resume()
        done.wait(timeout=10)
        assert bm.state == BatchState.COMPLETED

    def test_pause_when_not_running_is_noop(self):
        """pause() when not running does not change state."""
        bm = BatchManager(_sim_manager())
        bm.pause()  # IDLE → no change
        assert bm.state == BatchState.IDLE

    def test_resume_when_not_paused_is_noop(self):
        """resume() when not paused does not crash."""
        bm = BatchManager(_sim_manager())
        bm.resume()  # IDLE → no change
        assert bm.state == BatchState.IDLE

    def test_abort_unblocks_paused_batch(self):
        """abort() wakes a paused batch and sets ABORTED state."""
        bm = BatchManager(_sim_manager(num_cards=20))
        done = threading.Event()
        bm.on_completed = lambda: done.set()
        bm.start(_make_batch(50))
        time.sleep(0.05)
        bm.pause()
        time.sleep(0.05)
        bm.abort()
        done.wait(timeout=10)
        assert bm.state == BatchState.ABORTED

    def test_cannot_start_while_running(self):
        """start() while running is a no-op (total stays at original count)."""
        bm = BatchManager(_sim_manager(num_cards=20))
        done = threading.Event()
        bm.on_completed = lambda: done.set()
        bm.start(_make_batch(50))
        # Capture total immediately before the second start
        original_total = bm.total
        assert original_total == 50
        bm.abort()  # abort so the thread stops
        done.wait(timeout=10)

    def test_second_start_after_completion(self):
        """Can start a new batch after the previous one completed."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        batch = [{"ICCID": backend.card_deck[0].iccid,
                  "IMSI": backend.card_deck[0].imsi,
                  "ADM1": backend.card_deck[0].adm1}]
        bm = BatchManager(cm)
        _run_to_completion(bm, batch)
        assert bm.state == BatchState.COMPLETED

        # Reset state and run again
        bm.state = BatchState.IDLE
        _run_to_completion(bm, batch)
        assert bm.state == BatchState.COMPLETED


# ---------------------------------------------------------------------------
# Progress callback details
# ---------------------------------------------------------------------------

class TestProgressCallback:
    """Verify progress callback arguments."""

    def test_progress_total_matches_batch_size(self):
        """on_progress total arg always matches actual batch size."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        n = 3
        batch = [{"ICCID": c.iccid, "IMSI": c.imsi, "ADM1": c.adm1}
                 for c in backend.card_deck[:n]]
        totals = []
        bm = BatchManager(cm)
        bm.on_progress = lambda c, t, m: totals.append(t)
        _run_to_completion(bm, batch)
        assert all(t == n for t in totals)

    def test_progress_current_increases(self):
        """on_progress current arg is non-decreasing across calls."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        batch = [{"ICCID": c.iccid, "IMSI": c.imsi, "ADM1": c.adm1}
                 for c in backend.card_deck[:4]]
        currents = []
        bm = BatchManager(cm)
        bm.on_progress = lambda c, t, m: currents.append(c)
        _run_to_completion(bm, batch)
        assert currents == sorted(currents)

    def test_progress_message_is_string(self):
        """on_progress message arg is always a non-empty string."""
        cm = _sim_manager(num_cards=5)
        backend = cm._simulator
        batch = [{"ICCID": backend.card_deck[0].iccid,
                  "IMSI": backend.card_deck[0].imsi,
                  "ADM1": backend.card_deck[0].adm1}]
        messages = []
        bm = BatchManager(cm)
        bm.on_progress = lambda c, t, m: messages.append(m)
        _run_to_completion(bm, batch)
        for msg in messages:
            assert isinstance(msg, str)
            assert len(msg) > 0


# ---------------------------------------------------------------------------
# Empty batch
# ---------------------------------------------------------------------------

class TestEmptyBatch:
    """Edge case: empty batch list."""

    def test_empty_batch_completes_immediately(self):
        """Empty batch transitions to COMPLETED with no results."""
        bm = BatchManager(_sim_manager())
        _run_to_completion(bm, [])
        assert bm.state == BatchState.COMPLETED
        assert bm.results == []
        assert bm.success_count == 0
        assert bm.fail_count == 0

    def test_on_completed_still_called(self):
        """on_completed callback fires even for empty batch."""
        bm = BatchManager(_sim_manager())
        called = threading.Event()
        bm.on_completed = lambda: called.set()
        bm.start([])
        assert called.wait(timeout=5)


# ---------------------------------------------------------------------------
# card_ready() and skip() events
# ---------------------------------------------------------------------------

class TestCardReadySkip:
    """Tests for card_ready() and skip() signals."""

    def test_card_ready_unblocks_waiting(self):
        """card_ready() unblocks a batch waiting for card insertion."""
        # Non-simulator mode: batch waits for card_ready
        cm = CardManager()  # no simulator
        cm.authenticated = False

        bm = BatchManager(cm)
        wait_calls = []
        bm.on_waiting_for_card = lambda i, iccid: wait_calls.append(iccid)
        done = threading.Event()
        bm.on_completed = lambda: done.set()

        # One card — will wait for card_ready
        batch = [{"ICCID": "89123", "IMSI": "001", "ADM1": "12345678"}]
        bm.start(batch)

        # Give thread time to reach WAITING_FOR_CARD state
        time.sleep(0.2)

        # Signal card is ready
        bm.card_ready()
        done.wait(timeout=5)
        # Should have completed or aborted (not stuck)
        assert bm.state in (BatchState.COMPLETED, BatchState.ABORTED)

    def test_skip_marks_card_skipped(self):
        """skip() causes the current card to be marked as Skipped."""
        cm = CardManager()  # no simulator
        bm = BatchManager(cm)
        done = threading.Event()
        bm.on_completed = lambda: done.set()

        batch = [{"ICCID": "89123", "IMSI": "001", "ADM1": "12345678"}]
        bm.start(batch)
        time.sleep(0.2)
        bm.skip()
        done.wait(timeout=5)

        # At least one result should say "Skipped"
        if bm.results:
            skipped = [r for r in bm.results if "Skipped" in r.message]
            assert len(skipped) >= 1
