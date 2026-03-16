"""Tests for managers.card_watcher — background card polling thread."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from managers.card_watcher import CardWatcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeCardManager:
    """Minimal card manager mock for testing."""

    def __init__(self):
        self.detect_ok = False
        self.iccid = None
        self.detect_call_count = 0
        self.read_iccid_count = 0

    def probe_card_presence(self):
        """Fast probe — mirrors detect_card for testing."""
        self.detect_call_count += 1
        if self.detect_ok:
            return True, "3B 9F 96 80 1F"  # Fake ATR
        return False, "No card in reader"

    def detect_card(self):
        self.detect_call_count += 1
        if self.detect_ok:
            return True, "Card detected"
        return False, "No card"

    def read_iccid(self):
        self.read_iccid_count += 1
        return self.iccid


class FakeIndex:
    """Minimal IccidIndex mock."""

    def __init__(self, entries=None, card_data=None):
        self._entries = entries or {}
        self._card_data = card_data or {}

    def lookup(self, iccid):
        return self._entries.get(iccid)

    def load_card(self, iccid):
        return self._card_data.get(iccid)


class FakeIndexEntry:
    """Minimal IndexEntry-like object."""

    def __init__(self, file_path="test.csv"):
        self.file_path = file_path


# ---------------------------------------------------------------------------
# Tests for CardWatcher initialisation
# ---------------------------------------------------------------------------

class TestCardWatcherInit:
    def test_default_state(self):
        cm = FakeCardManager()
        w = CardWatcher(cm)
        assert not w.is_running
        assert not w.paused
        assert w.index is None

    def test_custom_poll_interval(self):
        cm = FakeCardManager()
        w = CardWatcher(cm, poll_interval=0.5)
        assert w._poll_interval == 0.5

    def test_set_index(self):
        cm = FakeCardManager()
        idx = FakeIndex()
        w = CardWatcher(cm)
        w.index = idx
        assert w.index is idx

    def test_init_with_index(self):
        cm = FakeCardManager()
        idx = FakeIndex()
        w = CardWatcher(cm, idx)
        assert w.index is idx


# ---------------------------------------------------------------------------
# Tests for start / stop
# ---------------------------------------------------------------------------

class TestCardWatcherStartStop:
    def test_start_creates_thread(self):
        cm = FakeCardManager()
        w = CardWatcher(cm, poll_interval=0.1)
        w.start()
        try:
            assert w.is_running
            assert w._thread is not None
            assert w._thread.daemon is True
            assert w._thread.name == "CardWatcher"
        finally:
            w.stop()

    def test_stop_terminates_thread(self):
        cm = FakeCardManager()
        w = CardWatcher(cm, poll_interval=0.1)
        w.start()
        assert w.is_running
        w.stop()
        assert not w.is_running
        assert w._last_iccid is None

    def test_double_start_is_noop(self):
        cm = FakeCardManager()
        w = CardWatcher(cm, poll_interval=0.1)
        w.start()
        thread1 = w._thread
        w.start()  # Should be a no-op
        assert w._thread is thread1
        w.stop()

    def test_stop_without_start(self):
        cm = FakeCardManager()
        w = CardWatcher(cm)
        w.stop()  # Should not raise


# ---------------------------------------------------------------------------
# Tests for pause / resume
# ---------------------------------------------------------------------------

class TestCardWatcherPauseResume:
    def test_pause_stops_polling(self):
        cm = FakeCardManager()
        w = CardWatcher(cm, poll_interval=0.05)
        w.start()
        try:
            time.sleep(0.15)  # Let a few polls run
            count_before = cm.detect_call_count
            w.pause()
            assert w.paused
            time.sleep(0.15)
            count_after = cm.detect_call_count
            # Should have very few (0 or 1) new calls while paused
            assert count_after - count_before <= 1
        finally:
            w.stop()

    def test_resume_restarts_polling(self):
        cm = FakeCardManager()
        w = CardWatcher(cm, poll_interval=0.05)
        w.start()
        try:
            w.pause()
            time.sleep(0.1)
            w.resume()
            assert not w.paused
            count_before = cm.detect_call_count
            time.sleep(0.15)
            count_after = cm.detect_call_count
            assert count_after > count_before
        finally:
            w.stop()


# ---------------------------------------------------------------------------
# Tests for card detection callbacks
# ---------------------------------------------------------------------------

class TestCardWatcherCallbacks:
    def test_on_card_unknown_fired(self):
        """Card inserted but not in index -> on_card_unknown."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "8949440000001672706"

        received = []
        w = CardWatcher(cm, poll_interval=0.05)
        w.on_card_unknown = lambda iccid: received.append(iccid)
        w.start()
        try:
            time.sleep(0.2)
        finally:
            w.stop()

        assert len(received) == 1
        assert received[0] == "8949440000001672706"

    def test_on_card_detected_fired(self):
        """Card inserted and found in index -> on_card_detected."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "8949440000001672706"

        entry = FakeIndexEntry("batch.csv")
        card_data = {"ICCID": "8949440000001672706", "IMSI": "99988000301001"}
        idx = FakeIndex(
            entries={"8949440000001672706": entry},
            card_data={"8949440000001672706": card_data},
        )

        received = []
        w = CardWatcher(cm, idx, poll_interval=0.05)
        w.on_card_detected = lambda ic, data, fp: received.append(
            (ic, data, fp))
        w.start()
        try:
            time.sleep(0.2)
        finally:
            w.stop()

        assert len(received) == 1
        iccid, data, fpath = received[0]
        assert iccid == "8949440000001672706"
        assert data["IMSI"] == "99988000301001"
        assert fpath == "batch.csv"

    def test_on_card_removed_fired(self):
        """Card removed after detection -> on_card_removed."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "8949440000001672706"

        removed = []
        w = CardWatcher(cm, poll_interval=0.05)
        w.on_card_unknown = lambda iccid: None
        w.on_card_removed = lambda: removed.append(True)
        w.start()
        try:
            time.sleep(0.15)  # Card detected
            cm.detect_ok = False  # Remove card
            cm.iccid = None
            time.sleep(0.15)  # Detect removal
        finally:
            w.stop()

        assert len(removed) >= 1

    def test_same_card_no_duplicate_callback(self):
        """Same card staying in reader -> only one callback."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "8949440000001672706"

        received = []
        w = CardWatcher(cm, poll_interval=0.05)
        w.on_card_unknown = lambda iccid: received.append(iccid)
        w.start()
        try:
            time.sleep(0.3)  # Multiple polls with same card
        finally:
            w.stop()

        assert len(received) == 1  # Only fires once

    def test_card_swap_fires_both_callbacks(self):
        """Swapping one card for another fires remove + new detect."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "CARD_A_1234567890123"

        unknown = []
        removed = []
        w = CardWatcher(cm, poll_interval=0.05)
        w.on_card_unknown = lambda iccid: unknown.append(iccid)
        w.on_card_removed = lambda: removed.append(True)
        w.start()
        try:
            time.sleep(0.15)  # Detect CARD_A
            assert len(unknown) == 1

            # Swap: briefly no card, then new card
            cm.detect_ok = False
            cm.iccid = None
            time.sleep(0.15)

            cm.detect_ok = True
            cm.iccid = "CARD_B_9876543210987"
            time.sleep(0.15)
        finally:
            w.stop()

        assert "CARD_A_1234567890123" in unknown
        assert "CARD_B_9876543210987" in unknown
        assert len(removed) >= 1


# ---------------------------------------------------------------------------
# Tests for error handling
# ---------------------------------------------------------------------------

class TestCardWatcherErrors:
    def test_on_error_fired(self):
        """Error in probe -> on_error callback."""
        cm = FakeCardManager()
        cm.probe_card_presence = MagicMock(side_effect=RuntimeError("Reader fail"))

        errors = []
        w = CardWatcher(cm, poll_interval=0.05)
        w.on_error = lambda msg: errors.append(msg)
        w.start()
        try:
            time.sleep(0.2)
        finally:
            w.stop()

        assert len(errors) >= 1
        assert "Reader fail" in errors[0]

    def test_callback_exception_does_not_crash(self):
        """Exception in callback should not kill the watcher thread."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "1234567890123456789"

        def bad_callback(iccid):
            raise ValueError("Callback exploded")

        w = CardWatcher(cm, poll_interval=0.05)
        w.on_card_unknown = bad_callback
        w.start()
        try:
            time.sleep(0.2)
            assert w.is_running  # Thread should survive
        finally:
            w.stop()

    def test_on_error_callback_exception_does_not_crash(self):
        """Exception in on_error callback should not kill the thread."""
        cm = FakeCardManager()
        cm.detect_card = MagicMock(side_effect=RuntimeError("fail"))

        def bad_error_handler(msg):
            raise ValueError("Error handler exploded")

        w = CardWatcher(cm, poll_interval=0.05)
        w.on_error = bad_error_handler
        w.start()
        try:
            time.sleep(0.2)
            assert w.is_running
        finally:
            w.stop()

    def test_on_card_removed_callback_exception_does_not_crash(self):
        """Exception in on_card_removed should not kill the thread."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "1234567890123456789"

        def bad_removed():
            raise ValueError("Remove handler exploded")

        w = CardWatcher(cm, poll_interval=0.05)
        w.on_card_unknown = lambda ic: None
        w.on_card_removed = bad_removed
        w.start()
        try:
            time.sleep(0.15)
            cm.detect_ok = False
            cm.iccid = None
            time.sleep(0.15)
            assert w.is_running
        finally:
            w.stop()


# ---------------------------------------------------------------------------
# Tests for _check_once (unit-level)
# ---------------------------------------------------------------------------

class TestCheckOnce:
    def test_no_card_no_previous(self):
        """No card detected, no previous card -> nothing happens."""
        cm = FakeCardManager()
        w = CardWatcher(cm)
        w._check_once()
        assert w._last_iccid is None

    def test_card_detected_no_index(self):
        """Card detected without index -> on_card_unknown."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "TEST_ICCID_12345"

        received = []
        w = CardWatcher(cm)
        w.on_card_unknown = lambda ic: received.append(ic)
        w._check_once()

        assert w._last_iccid == "TEST_ICCID_12345"
        assert received == ["TEST_ICCID_12345"]

    def test_card_detected_with_index_match(self):
        """Card in index -> on_card_detected."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "ICCID_KNOWN"

        entry = FakeIndexEntry("data.csv")
        card = {"ICCID": "ICCID_KNOWN", "Ki": "AA" * 16}
        idx = FakeIndex(
            entries={"ICCID_KNOWN": entry},
            card_data={"ICCID_KNOWN": card},
        )

        detected = []
        w = CardWatcher(cm, idx)
        w.on_card_detected = lambda ic, d, fp: detected.append((ic, d, fp))
        w._check_once()

        assert len(detected) == 1
        assert detected[0][0] == "ICCID_KNOWN"

    def test_card_detected_with_index_no_match(self):
        """Card not in index -> on_card_unknown."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "ICCID_UNKNOWN"

        idx = FakeIndex()  # Empty index

        unknown = []
        w = CardWatcher(cm, idx)
        w.on_card_unknown = lambda ic: unknown.append(ic)
        w._check_once()

        assert unknown == ["ICCID_UNKNOWN"]

    def test_card_removed(self):
        """Card was present, then removed."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "ICCID_123"

        removed = []
        w = CardWatcher(cm)
        w.on_card_unknown = lambda ic: None
        w.on_card_removed = lambda: removed.append(True)

        # First detect
        w._check_once()
        assert w._last_iccid == "ICCID_123"

        # Card removed
        cm.detect_ok = False
        cm.iccid = None
        w._check_once()

        assert w._last_iccid is None
        assert removed == [True]

    def test_same_card_second_check_noop(self):
        """Same card on second check -> no callback."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "ICCID_SAME"

        count = []
        w = CardWatcher(cm)
        w.on_card_unknown = lambda ic: count.append(1)

        w._check_once()
        w._check_once()

        assert len(count) == 1  # Only once

    def test_detect_ok_but_no_iccid(self):
        """detect_card ok but read_iccid returns None -> on_card_unknown("").

        This covers blank cards that are detected by the reader but have
        no ICCID programmed yet.
        """
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = None  # No ICCID available (blank card)

        received = []
        w = CardWatcher(cm)
        w.on_card_unknown = lambda ic: received.append(ic)
        w._check_once()

        # Blank card should fire on_card_unknown with empty string
        assert len(received) == 1
        assert received[0] == ""

    def test_index_lookup_match_but_load_card_fails(self):
        """Index finds entry but load_card returns None -> no on_card_detected."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "ICCID_PARTIAL"

        entry = FakeIndexEntry("data.csv")
        idx = FakeIndex(
            entries={"ICCID_PARTIAL": entry},
            card_data={},  # load_card returns None
        )

        detected = []
        unknown = []
        w = CardWatcher(cm, idx)
        w.on_card_detected = lambda ic, d, fp: detected.append(1)
        w.on_card_unknown = lambda ic: unknown.append(ic)
        w._check_once()

        # load_card failed, should NOT fire on_card_detected
        assert len(detected) == 0
        # Falls through to on_card_unknown? No — current code returns after
        # entering the index path. Let's verify the actual behavior:
        # In the current implementation, if entry exists but load_card fails,
        # it skips both callbacks (just returns from _handle_new_card).
        # This is acceptable — the card was found in index but data couldn't load.

    def test_no_callbacks_set(self):
        """No callbacks configured -> no crash."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "ICCID_NO_CB"

        w = CardWatcher(cm)
        w._check_once()  # Should not raise
        assert w._last_iccid == "ICCID_NO_CB"

        cm.detect_ok = False
        cm.iccid = None
        w._check_once()  # Should not raise
        assert w._last_iccid is None


# ---------------------------------------------------------------------------
# paused_context — nestable context manager
# ---------------------------------------------------------------------------

class TestPausedContext:
    """Tests for CardWatcher.paused_context() nestable context manager."""

    def test_basic_pause_resume(self):
        """Context manager pauses on enter, resumes on exit."""
        cm = FakeCardManager()
        w = CardWatcher(cm)
        assert not w.paused

        with w.paused_context():
            assert w.paused
        assert not w.paused

    def test_nested_pause_only_outermost_resumes(self):
        """Nested paused_context blocks don't prematurely resume."""
        cm = FakeCardManager()
        w = CardWatcher(cm)

        with w.paused_context():
            assert w.paused
            with w.paused_context():
                assert w.paused
            # Inner exited — should still be paused
            assert w.paused
        # Outer exited — now should be resumed
        assert not w.paused

    def test_triple_nesting(self):
        """Triple nesting works correctly."""
        cm = FakeCardManager()
        w = CardWatcher(cm)

        with w.paused_context():
            with w.paused_context():
                with w.paused_context():
                    assert w.paused
                assert w.paused
            assert w.paused
        assert not w.paused

    def test_exception_in_block_still_resumes(self):
        """Watcher is resumed even if exception occurs inside block."""
        cm = FakeCardManager()
        w = CardWatcher(cm)

        with pytest.raises(ValueError):
            with w.paused_context():
                assert w.paused
                raise ValueError("test error")
        assert not w.paused

    def test_exception_in_nested_block_still_resumes(self):
        """Exception in nested block resumes correctly."""
        cm = FakeCardManager()
        w = CardWatcher(cm)

        with pytest.raises(ValueError):
            with w.paused_context():
                with w.paused_context():
                    raise ValueError("inner error")
        # Both exited due to exception — should be resumed
        assert not w.paused

    def test_already_paused_watcher(self):
        """Context manager works even if watcher was already paused."""
        cm = FakeCardManager()
        w = CardWatcher(cm)
        w.pause()  # Manually paused before context
        assert w.paused

        with w.paused_context():
            assert w.paused
        # Context manager resumes because depth went 0→1→0
        assert not w.paused

    def test_paused_context_returns_watcher(self):
        """The 'as' variable in 'with ... as w' is the watcher."""
        cm = FakeCardManager()
        w = CardWatcher(cm)
        with w.paused_context() as ctx:
            assert ctx is w

    def test_poll_loop_respects_paused_context(self):
        """Polling loop skips checks while paused via context manager."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "89000000000000000001"
        w = CardWatcher(cm, poll_interval=0.1)
        detected = []
        w.on_card_detected = lambda *a: detected.append(a)

        w.start()
        # Let it detect the card
        time.sleep(0.3)
        initial_count = cm.detect_call_count
        assert initial_count > 0

        # Pause via context manager — poll count should freeze
        with w.paused_context():
            count_at_pause = cm.detect_call_count
            time.sleep(0.3)
            assert cm.detect_call_count == count_at_pause

        # After resume, polling should continue
        time.sleep(0.3)
        assert cm.detect_call_count > count_at_pause
        w.stop()
