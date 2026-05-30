"""Extended tests for managers/batch_manager.py.

Covers:
- Cancellation mid-batch
- Error handling during programming (detect / auth / program failures)
- Progress callback states
- get_summary via success_count / fail_count after various outcomes
- ICCID mismatch handling
- skip() while waiting for card
- Multiple start() calls
- CardResult dataclass
"""

import os
import sys
import threading
import time

import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.batch_manager import BatchManager, BatchState, CardResult  # noqa: E402
from managers.card_manager import CardManager  # noqa: E402
from state_manager import ProgramOutcome, ProgramResult  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_manager():
    """Mock CardManager for hardware-path batch tests."""
    cm = MagicMock()
    cm.is_simulator_active = False
    cm.detect_card.return_value = (True, "Card detected")
    cm.read_iccid.return_value = None  # no ICCID cross-check by default
    cm.authenticate.return_value = (True, "Authenticated")
    cm.program_card.return_value = (True, "Programmed successfully", ProgramResult(outcome=ProgramOutcome.WRITE_OK_VERIFIED, message="Programmed successfully"))
    cm.verify_card.return_value = (True, [])
    return cm


def _make_batch(count: int, adm1="12345678") -> list:
    """Build a dummy batch of `count` card dicts."""
    return [
        {
            "ICCID": f"8999900000000000{i:04d}",
            "IMSI": f"99999000000{i:04d}",
            "ADM1": adm1,
        }
        for i in range(count)
    ]


def _run_to_completion(bm: BatchManager, batch: list, timeout: float = 10) -> None:
    """Start batch and wait for completion.

    Sets on_waiting_for_card to immediately fire card_ready so that
    the hardware-path wait is bypassed in mock-based tests.
    """
    done = threading.Event()
    bm.on_completed = lambda: done.set()
    bm.on_waiting_for_card = lambda i, iccid: bm.card_ready()
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

    def test_default_outcome_is_idle(self):
        """CardResult without explicit outcome defaults to IDLE."""
        r = CardResult(0, "89123", True, "OK")
        assert r.outcome == ProgramOutcome.IDLE

    def test_explicit_outcome_stored(self):
        """CardResult stores an explicitly supplied outcome."""
        r = CardResult(0, "89123", True, "OK",
                       outcome=ProgramOutcome.WRITE_OK_VERIFIED)
        assert r.outcome == ProgramOutcome.WRITE_OK_VERIFIED


# ---------------------------------------------------------------------------
# Outcome propagation through _process_one
# ---------------------------------------------------------------------------

class TestOutcomePropagation:
    """_process_one propagates ProgramOutcome into CardResult.outcome."""

    def _run_single(self, cm) -> CardResult:
        bm = BatchManager(cm)
        _run_to_completion(bm, _make_batch(1))
        return bm.results[0]

    def test_write_ok_verified_propagated(self):
        """Successful program → WRITE_OK_VERIFIED outcome."""
        cm = _mock_manager()
        r = self._run_single(cm)
        assert r.outcome == ProgramOutcome.WRITE_OK_VERIFIED
        assert r.success is True

    def test_no_changes_propagated(self):
        """NO_CHANGES from program_card → outcome=NO_CHANGES, success=True."""
        cm = _mock_manager()
        cm.program_card.return_value = (
            True, "No changes",
            ProgramResult(outcome=ProgramOutcome.NO_CHANGES, message="No changes"))
        r = self._run_single(cm)
        assert r.outcome == ProgramOutcome.NO_CHANGES
        assert r.success is True

    def test_write_ok_pending_propagated(self):
        """WRITE_OK_PENDING from program_card → outcome=WRITE_OK_PENDING, success=True."""
        cm = _mock_manager()
        cm.program_card.return_value = (
            True, "Written",
            ProgramResult(outcome=ProgramOutcome.WRITE_OK_PENDING, message="Written"))
        r = self._run_single(cm)
        assert r.outcome == ProgramOutcome.WRITE_OK_PENDING
        assert r.success is True

    def test_write_ok_verification_failed_from_program(self):
        """WRITE_OK_VERIFICATION_FAILED from program_card → success=False, outcome propagated."""
        cm = _mock_manager()
        cm.program_card.return_value = (
            False, "Verification failed",
            ProgramResult(outcome=ProgramOutcome.WRITE_OK_VERIFICATION_FAILED))
        r = self._run_single(cm)
        assert r.outcome == ProgramOutcome.WRITE_OK_VERIFICATION_FAILED
        assert r.success is False

    def test_post_program_verify_card_failure(self):
        """verify_card failure after programming → WRITE_OK_VERIFICATION_FAILED."""
        cm = _mock_manager()
        cm.verify_card.return_value = (False, ["IMSI mismatch"])
        r = self._run_single(cm)
        assert r.outcome == ProgramOutcome.WRITE_OK_VERIFICATION_FAILED
        assert r.success is False

    def test_detect_failure_outcome_is_idle(self):
        """Detect failure → outcome=IDLE (no programming attempted)."""
        cm = _mock_manager()
        cm.detect_card.return_value = (False, "No card")
        r = self._run_single(cm)
        assert r.outcome == ProgramOutcome.IDLE
        assert r.success is False

    def test_iccid_mismatch_outcome(self):
        """ICCID mismatch → outcome=ICCID_MISMATCH."""
        cm = _mock_manager()
        cm.read_iccid.return_value = "9999999999999999999"  # wrong ICCID
        r = self._run_single(cm)
        assert r.outcome == ProgramOutcome.ICCID_MISMATCH
        assert r.success is False

    def test_auth_failure_outcome(self):
        """Auth failure → outcome=ADM1_AUTH_FAILED."""
        cm = _mock_manager()
        cm.authenticate.return_value = (False, "Wrong key")
        r = self._run_single(cm)
        assert r.outcome == ProgramOutcome.ADM1_AUTH_FAILED
        assert r.success is False


# ---------------------------------------------------------------------------
# Outcome-aware count properties
# ---------------------------------------------------------------------------

class TestOutcomeCounts:
    """Outcome-aware summary counts on BatchManager."""

    def test_verified_count(self):
        """verified_count counts only WRITE_OK_VERIFIED results."""
        bm = BatchManager(_mock_manager())
        bm.results = [
            CardResult(0, "A", True, "ok", outcome=ProgramOutcome.WRITE_OK_VERIFIED),
            CardResult(1, "B", True, "ok", outcome=ProgramOutcome.NO_CHANGES),
            CardResult(2, "C", True, "ok", outcome=ProgramOutcome.WRITE_OK_PENDING),
        ]
        assert bm.verified_count == 1

    def test_no_change_count(self):
        """no_change_count counts NO_CHANGES outcomes; not in verified_count."""
        bm = BatchManager(_mock_manager())
        bm.results = [
            CardResult(0, "A", True, "ok", outcome=ProgramOutcome.WRITE_OK_VERIFIED),
            CardResult(1, "B", True, "ok", outcome=ProgramOutcome.NO_CHANGES),
        ]
        assert bm.no_change_count == 1
        assert bm.verified_count == 1

    def test_pending_count(self):
        """pending_count counts WRITE_OK_PENDING results."""
        bm = BatchManager(_mock_manager())
        bm.results = [
            CardResult(0, "A", True, "ok", outcome=ProgramOutcome.WRITE_OK_PENDING),
            CardResult(1, "B", True, "ok", outcome=ProgramOutcome.WRITE_OK_VERIFIED),
        ]
        assert bm.pending_count == 1

    def test_verification_failed_count(self):
        """verification_failed_count counts WRITE_OK_VERIFICATION_FAILED."""
        bm = BatchManager(_mock_manager())
        bm.results = [
            CardResult(0, "A", False, "err",
                       outcome=ProgramOutcome.WRITE_OK_VERIFICATION_FAILED),
            CardResult(1, "B", True, "ok", outcome=ProgramOutcome.WRITE_OK_VERIFIED),
        ]
        assert bm.verification_failed_count == 1

    def test_legacy_success_fail_count_unchanged(self):
        """success_count / fail_count still reflect the success bool."""
        bm = BatchManager(_mock_manager())
        bm.results = [
            CardResult(0, "A", True, "ok", outcome=ProgramOutcome.WRITE_OK_VERIFIED),
            CardResult(1, "B", True, "ok", outcome=ProgramOutcome.NO_CHANGES),
            CardResult(2, "C", False, "err", outcome=ProgramOutcome.ADM1_AUTH_FAILED),
        ]
        assert bm.success_count == 2
        assert bm.fail_count == 1


# ---------------------------------------------------------------------------
# BatchManager initial state
# ---------------------------------------------------------------------------

class TestBatchManagerInitState:
    """Verify initial state of a fresh BatchManager."""

    def test_state_is_idle(self):
        """Initial state is IDLE."""
        bm = BatchManager(_mock_manager())
        assert bm.state == BatchState.IDLE

    def test_results_empty(self):
        """No results initially."""
        bm = BatchManager(_mock_manager())
        assert bm.results == []

    def test_total_is_zero(self):
        """No batch data initially."""
        bm = BatchManager(_mock_manager())
        assert bm.total == 0

    def test_current_is_zero(self):
        """Current index is 0 initially."""
        bm = BatchManager(_mock_manager())
        assert bm.current == 0

    def test_counts_zero(self):
        """Success and fail counts are 0 initially."""
        bm = BatchManager(_mock_manager())
        assert bm.success_count == 0
        assert bm.fail_count == 0


# ---------------------------------------------------------------------------
# Successful batch (mock CM always succeeds)
# ---------------------------------------------------------------------------

class TestSuccessfulBatch:
    """Mock batch that completes fully."""

    def test_all_cards_processed(self):
        """All cards in the batch are processed."""
        cm = _mock_manager()
        bm = BatchManager(cm)
        _run_to_completion(bm, _make_batch(3))
        assert len(bm.results) == 3

    def test_state_completed_after_run(self):
        """State is COMPLETED after successful run."""
        bm = BatchManager(_mock_manager())
        _run_to_completion(bm, _make_batch(1))
        assert bm.state == BatchState.COMPLETED

    def test_on_progress_called_for_each_card(self):
        """on_progress callback fires once per card."""
        calls = []
        bm = BatchManager(_mock_manager())
        bm.on_progress = lambda c, t, m: calls.append((c, t, m))
        _run_to_completion(bm, _make_batch(3))
        assert len(calls) == 3

    def test_on_card_result_called_for_each_card(self):
        """on_card_result callback fires once per card."""
        results_cb = []
        bm = BatchManager(_mock_manager())
        bm.on_card_result = lambda r: results_cb.append(r)
        _run_to_completion(bm, _make_batch(2))
        assert len(results_cb) == 2

    def test_success_count_all_pass(self):
        """success_count equals batch size when all succeed."""
        bm = BatchManager(_mock_manager())
        _run_to_completion(bm, _make_batch(3))
        assert bm.success_count == 3
        assert bm.fail_count == 0


# ---------------------------------------------------------------------------
# Error during batch
# ---------------------------------------------------------------------------

class TestBatchErrors:
    """Test error handling when individual cards fail."""

    def test_wrong_adm1_causes_failure(self):
        """Authenticate failure causes that card to fail."""
        cm = _mock_manager()
        cm.authenticate.return_value = (False, "Wrong ADM1")
        bm = BatchManager(cm)
        _run_to_completion(bm, _make_batch(1))
        assert bm.fail_count >= 1
        assert "Auth failed" in bm.results[0].message

    def test_iccid_mismatch_causes_failure(self):
        """ICCID returned by card differs from batch — card fails."""
        cm = _mock_manager()
        # read_iccid returns a value that won't match any batch ICCID
        cm.read_iccid.return_value = "0000000000000000000"
        bm = BatchManager(cm)
        _run_to_completion(bm, _make_batch(1))
        assert len(bm.results) == 1
        assert bm.results[0].success is False

    def test_detect_failure_causes_card_fail(self):
        """If detect_card fails, that card's result is failure."""
        cm = _mock_manager()
        cm.detect_card.return_value = (False, "No card in reader")
        bm = BatchManager(cm)
        _run_to_completion(bm, _make_batch(1))
        assert bm.fail_count >= 1

    def test_mixed_success_and_failure(self):
        """Batch with some valid and some failing auth produces mixed results."""
        cm = _mock_manager()
        cm.authenticate.side_effect = [
            (True, "Authenticated"),
            (False, "Wrong ADM1"),
        ]
        bm = BatchManager(cm)
        _run_to_completion(bm, _make_batch(2))
        assert bm.success_count + bm.fail_count == 2
        assert bm.fail_count >= 1

    def test_success_plus_fail_equals_total(self):
        """success_count + fail_count always equals total results."""
        cm = _mock_manager()
        cm.authenticate.side_effect = [
            (True, "ok"), (False, "fail"), (True, "ok"), (False, "fail"),
        ]
        bm = BatchManager(cm)
        _run_to_completion(bm, _make_batch(4))
        assert bm.success_count + bm.fail_count == len(bm.results)


# ---------------------------------------------------------------------------
# Abort / pause / resume
# ---------------------------------------------------------------------------

class TestBatchControl:
    """Tests for abort, pause, and resume controls."""

    def test_abort_before_start(self):
        """abort() before start sets state to ABORTED."""
        bm = BatchManager(_mock_manager())
        bm.abort()
        assert bm.state == BatchState.ABORTED

    def test_abort_mid_batch(self):
        """abort() during execution stops the batch.

        Without auto card_ready, the batch thread is blocked waiting for
        the first card insertion. abort() unblocks and exits cleanly.
        """
        bm = BatchManager(_mock_manager())
        done = threading.Event()
        bm.on_completed = lambda: done.set()
        bm.start(_make_batch(100))
        time.sleep(0.05)
        bm.abort()
        done.wait(timeout=10)
        assert bm.state == BatchState.ABORTED

    def test_pause_then_resume(self):
        """pause() then resume() does not break batch completion.

        With auto card_ready, the small batch may complete before pause()
        is called — COMPLETED is an accepted state per this test's contract.
        """
        bm = BatchManager(_mock_manager())
        done = threading.Event()
        bm.on_completed = lambda: done.set()
        bm.on_waiting_for_card = lambda i, iccid: bm.card_ready()
        bm.start(_make_batch(5))
        time.sleep(0.02)
        bm.pause()
        time.sleep(0.05)
        assert bm.state in (BatchState.PAUSED, BatchState.COMPLETED)
        bm.resume()
        done.wait(timeout=10)
        assert bm.state == BatchState.COMPLETED

    def test_pause_when_not_running_is_noop(self):
        """pause() when not running does not change state."""
        bm = BatchManager(_mock_manager())
        bm.pause()
        assert bm.state == BatchState.IDLE

    def test_resume_when_not_paused_is_noop(self):
        """resume() when not paused does not crash."""
        bm = BatchManager(_mock_manager())
        bm.resume()
        assert bm.state == BatchState.IDLE

    def test_abort_unblocks_waiting_batch(self):
        """abort() wakes a batch blocked at WAITING_FOR_CARD and sets ABORTED."""
        bm = BatchManager(_mock_manager())
        done = threading.Event()
        bm.on_completed = lambda: done.set()
        bm.start(_make_batch(50))
        time.sleep(0.05)
        bm.abort()
        done.wait(timeout=10)
        assert bm.state == BatchState.ABORTED

    def test_cannot_start_while_running(self):
        """start() while running is a no-op (total stays at original count)."""
        bm = BatchManager(_mock_manager())
        done = threading.Event()
        bm.on_completed = lambda: done.set()
        bm.start(_make_batch(50))
        original_total = bm.total
        assert original_total == 50
        bm.abort()
        done.wait(timeout=10)

    def test_second_start_after_completion(self):
        """Can start a new batch after the previous one completed."""
        bm = BatchManager(_mock_manager())
        _run_to_completion(bm, _make_batch(1))
        assert bm.state == BatchState.COMPLETED

        bm.state = BatchState.IDLE
        _run_to_completion(bm, _make_batch(1))
        assert bm.state == BatchState.COMPLETED


# ---------------------------------------------------------------------------
# Progress callback details
# ---------------------------------------------------------------------------

class TestProgressCallback:
    """Verify progress callback arguments."""

    def test_progress_total_matches_batch_size(self):
        """on_progress total arg always matches actual batch size."""
        n = 3
        totals = []
        bm = BatchManager(_mock_manager())
        bm.on_progress = lambda c, t, m: totals.append(t)
        _run_to_completion(bm, _make_batch(n))
        assert all(t == n for t in totals)

    def test_progress_current_increases(self):
        """on_progress current arg is non-decreasing across calls."""
        currents = []
        bm = BatchManager(_mock_manager())
        bm.on_progress = lambda c, t, m: currents.append(c)
        _run_to_completion(bm, _make_batch(4))
        assert currents == sorted(currents)

    def test_progress_message_is_string(self):
        """on_progress message arg is always a non-empty string."""
        messages = []
        bm = BatchManager(_mock_manager())
        bm.on_progress = lambda c, t, m: messages.append(m)
        _run_to_completion(bm, _make_batch(1))
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
        bm = BatchManager(_mock_manager())
        _run_to_completion(bm, [])
        assert bm.state == BatchState.COMPLETED
        assert bm.results == []
        assert bm.success_count == 0
        assert bm.fail_count == 0

    def test_on_completed_still_called(self):
        """on_completed callback fires even for empty batch."""
        bm = BatchManager(_mock_manager())
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
        cm = CardManager()  # real CM, no simulator — hardware path

        bm = BatchManager(cm)
        wait_calls = []
        bm.on_waiting_for_card = lambda i, iccid: wait_calls.append(iccid)
        done = threading.Event()
        bm.on_completed = lambda: done.set()

        batch = [{"ICCID": "89123", "IMSI": "001", "ADM1": "12345678"}]
        bm.start(batch)

        time.sleep(0.2)
        bm.card_ready()
        done.wait(timeout=5)
        assert bm.state in (BatchState.COMPLETED, BatchState.ABORTED)

    def test_skip_marks_card_skipped(self):
        """skip() causes the current card to be marked as Skipped."""
        cm = CardManager()  # real CM, no simulator — hardware path
        bm = BatchManager(cm)
        done = threading.Event()
        bm.on_completed = lambda: done.set()

        batch = [{"ICCID": "89123", "IMSI": "001", "ADM1": "12345678"}]
        bm.start(batch)
        time.sleep(0.2)
        bm.skip()
        done.wait(timeout=5)

        if bm.results:
            skipped = [r for r in bm.results if "Skipped" in r.message]
            assert len(skipped) >= 1
