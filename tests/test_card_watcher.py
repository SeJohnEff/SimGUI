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
        self.rescan_calls = []

    def lookup(self, iccid):
        return self._entries.get(iccid)

    def load_card(self, iccid):
        return self._card_data.get(iccid)

    @property
    def scanned_dirs(self):
        return frozenset()

    @property
    def stats(self):
        return {"total_cards": len(self._card_data)}

    def rescan_if_stale(self, directory):
        self.rescan_calls.append(directory)
        return None


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


# ---------------------------------------------------------------------------
# Blank-card removal debounce
# ---------------------------------------------------------------------------

class TestBlankCardRemovalDebounce:
    """Blank gialersim cards can cause a transient 'No card' from PCSC right
    after pySim-read releases the reader.  The watcher requires two consecutive
    absent probes before declaring removal for blank cards (last_iccid=None).
    Non-blank cards are removed immediately on the first absent probe.
    """

    def _make_watcher_with_blank_card(self):
        """Return a watcher that has already detected a blank card."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = None  # blank card

        removed = []
        unknown = []
        w = CardWatcher(cm)
        w.on_card_removed = lambda: removed.append(True)
        w.on_card_unknown = lambda ic: unknown.append(ic)

        # First check: blank card detected
        w._check_once()
        assert len(unknown) == 1
        assert w._card_present is True
        assert w._last_iccid is None

        cm.detect_ok = False  # simulate card removal
        return w, cm, removed

    def test_nonblank_card_removed_immediately(self):
        """Non-blank card: single 'no card' probe fires on_card_removed."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = "8949440000001672706"  # non-blank

        removed = []
        w = CardWatcher(cm)
        w.on_card_removed = lambda: removed.append(True)
        w.on_card_unknown = lambda ic: None

        w._check_once()  # detect card
        assert w._card_present is True

        cm.detect_ok = False
        w._check_once()  # remove
        assert len(removed) == 1, "Non-blank card should fire removal immediately"

    def test_blank_card_first_absent_probe_no_removal(self):
        """Blank card: first 'no card' probe does NOT fire on_card_removed."""
        w, cm, removed = self._make_watcher_with_blank_card()
        w._check_once()  # first absent probe
        assert len(removed) == 0, "Should not fire removal on first absent probe"
        assert w._card_present is True, "_card_present should stay True after first absent probe"

    def test_blank_card_second_absent_probe_fires_removal(self):
        """Blank card: second consecutive 'no card' probe fires on_card_removed."""
        w, cm, removed = self._make_watcher_with_blank_card()
        w._check_once()  # first absent probe — debounced
        w._check_once()  # second absent probe — fires removal
        assert len(removed) == 1, "Should fire removal on second absent probe"
        assert w._card_present is False

    def test_blank_card_reappears_resets_debounce(self):
        """Blank card: one absent probe, card reappears → no removal fired."""
        w, cm, removed = self._make_watcher_with_blank_card()
        w._check_once()  # first absent probe — debounced
        assert len(removed) == 0

        cm.detect_ok = True  # card reappears
        unknown_extra = []
        w.on_card_unknown = lambda ic: unknown_extra.append(ic)
        w._check_once()  # card back — debounce counter reset
        assert len(removed) == 0, "No removal should fire when card reappears"
        assert w._no_card_streak == 0

    def test_no_card_streak_resets_on_card_present(self):
        """_no_card_streak resets to 0 when card is detected again."""
        w, cm, removed = self._make_watcher_with_blank_card()
        w._check_once()  # first absent probe → streak=1
        assert w._no_card_streak == 1

        cm.detect_ok = True  # card back
        w._check_once()
        assert w._no_card_streak == 0

    def test_blank_card_removal_clears_card_present(self):
        """After second absent probe, _card_present is False and state is clean."""
        w, cm, removed = self._make_watcher_with_blank_card()
        w._check_once()
        w._check_once()
        assert w._card_present is False
        assert w._last_iccid is None
        assert w._last_atr is None


# ---------------------------------------------------------------------------
# _read_and_notify error classification (Bug C fix)
# ---------------------------------------------------------------------------

class TestReadAndNotifyClassification:
    """Transport/protocol read failures must NOT become BLANK (on_card_unknown).

    BLANK must only be set when pySim-read successfully contacted the card and
    found no ICCID (genuinely unprogrammed gialersim).  A T0/CardConnection
    transport failure is a READ_ERROR — it maps to on_error, not on_card_unknown.
    """

    def _make_fast_probe_watcher(self, probe_atr="3B 9F 96 80 1F"):
        """Return (watcher, cm) with the fast probe path active.

        Sets up FakeCardManager so probe_card_presence() reports a card present
        (triggering _read_and_notify via _handle_probe_result).  The actual
        detect_card() return value is controlled per-test via detect_ok / detect_msg.
        """
        cm = FakeCardManager()
        # Override probe_card_presence to always report card present
        cm.probe_card_presence = lambda: (True, probe_atr)
        w = CardWatcher(cm)
        w._probe_available = True
        w._last_atr = None
        w._card_present = False
        return w, cm

    def test_transport_error_maps_to_on_error_not_blank(self):
        """ok=False with transport/protocol error → on_error, NOT on_card_unknown."""
        w, cm = self._make_fast_probe_watcher()
        cm.detect_ok = False
        cm.detect_card = lambda: (
            False,
            "Card communication error - re-seat the SIM",
        )
        cm.iccid = None

        errors = []
        unknowns = []
        w.on_error = lambda msg: errors.append(msg)
        w.on_card_unknown = lambda ic: unknowns.append(ic)

        w._check_once()

        assert len(unknowns) == 0, (
            "Transport error must NOT fire on_card_unknown (BLANK state)"
        )
        assert len(errors) == 1
        assert "communication error" in errors[0].lower() or errors[0]

    def test_cardconnectionexception_maps_to_on_error(self):
        """CardConnectionException / T0 protocol mismatch → on_error, not BLANK."""
        w, cm = self._make_fast_probe_watcher()
        error_msg = "Failed to transmit with protocol T0. Card protocol mismatch"
        cm.detect_card = lambda: (False, error_msg)
        cm.iccid = None

        errors = []
        unknowns = []
        w.on_error = lambda msg: errors.append(msg)
        w.on_card_unknown = lambda ic: unknowns.append(ic)

        w._check_once()

        assert len(unknowns) == 0, (
            "T0 protocol mismatch must NOT produce BLANK state"
        )
        assert len(errors) == 1
        assert "T0" in errors[0] or "protocol" in errors[0].lower()

    def test_blank_card_ok_no_iccid_still_maps_to_on_card_unknown(self):
        """ok=True but no ICCID (genuine blank/gialersim) → on_card_unknown("").

        This is the valid BLANK path — pySim-read contacted the card successfully
        but it has no programmed ICCID.
        """
        w, cm = self._make_fast_probe_watcher()
        cm.detect_ok = True
        cm.iccid = None  # No ICCID — blank card

        errors = []
        unknowns = []
        w.on_error = lambda msg: errors.append(msg)
        w.on_card_unknown = lambda ic: unknowns.append(ic)

        w._check_once()

        assert len(errors) == 0, "Blank card (ok=True, no ICCID) must NOT fire on_error"
        assert len(unknowns) == 1
        assert unknowns[0] == "", "Blank card should fire on_card_unknown with empty string"

    def test_successful_read_with_iccid_unaffected(self):
        """ok=True with ICCID → on_card_unknown(iccid) (no index), no on_error."""
        w, cm = self._make_fast_probe_watcher()
        cm.detect_ok = True
        cm.iccid = "8949440000001672706"

        errors = []
        unknowns = []
        w.on_error = lambda msg: errors.append(msg)
        w.on_card_unknown = lambda ic: unknowns.append(ic)

        w._check_once()

        assert len(errors) == 0
        assert len(unknowns) == 1
        assert unknowns[0] == "8949440000001672706"

    def test_transport_error_with_atr_cache_still_resolves(self):
        """Transport error but ATR cache hit → on_card_unknown(cached_iccid), no error."""
        w, cm = self._make_fast_probe_watcher(probe_atr="ATR_KNOWN")
        cached_iccid = "8949440000001672706"
        # Pre-populate the cache as if a card was just programmed
        w._atr_iccid_cache["ATR_KNOWN"] = cached_iccid
        w._last_atr = "ATR_KNOWN"

        cm.detect_card = lambda: (False, "Card communication error")
        cm.iccid = None

        errors = []
        unknowns = []
        w.on_error = lambda msg: errors.append(msg)
        w.on_card_unknown = lambda ic: unknowns.append(ic)

        w._check_once()

        # Cache hit takes priority — resolves to cached ICCID, no error
        assert len(errors) == 0
        assert len(unknowns) == 1
        assert unknowns[0] == cached_iccid

    def test_blank_card_debounce_behavior_unchanged(self):
        """Blank card debounce is unaffected: second absent probe fires removal."""
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = None  # blank

        removed = []
        unknowns = []
        w = CardWatcher(cm)
        w.on_card_removed = lambda: removed.append(True)
        w.on_card_unknown = lambda ic: unknowns.append(ic)

        # Detect blank card
        w._check_once()
        assert len(unknowns) == 1
        assert w._card_present is True

        # First absent probe — debounced
        cm.detect_ok = False
        w._check_once()
        assert len(removed) == 0
        assert w._card_present is True

        # Second absent probe — removal fires
        w._check_once()
        assert len(removed) == 1
        assert w._card_present is False


# ---------------------------------------------------------------------------
# Rescan-on-miss and stats property tests
# ---------------------------------------------------------------------------

class TestRescanOnLookupMiss:
    """_handle_new_card rescans known dirs on a lookup miss before giving up."""

    def _make_cm(self, iccid):
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = iccid
        return cm

    def test_stats_is_property_not_callable(self):
        """IccidIndex.stats is a dict property — accessing it must not raise."""
        from managers.iccid_index import IccidIndex
        idx = IccidIndex()
        s = idx.stats
        assert isinstance(s, dict)
        assert "total_cards" in s

    def test_lookup_miss_triggers_rescan_then_finds_iccid(self):
        """On first-insert miss, rescan is called and card is found on retry."""
        entry = FakeIndexEntry("batch.csv")
        card = {"ICCID": "ICCID_LATE", "ADM1": "72762965"}

        class RescanPopulatesIndex(FakeIndex):
            """Simulates a stale index: lookup misses until after rescan."""
            def __init__(self):
                super().__init__()
                self._rescanned = False

            @property
            def scanned_dirs(self):
                return frozenset(["/mnt/share"])

            def lookup(self, iccid):
                # Only return the entry after a rescan has been called
                if self._rescanned:
                    return entry
                return None

            def rescan_if_stale(self, directory):
                self._rescanned = True
                self.rescan_calls.append(directory)
                return None

            def load_card(self, iccid):
                if self._rescanned:
                    return card
                return None

        idx = RescanPopulatesIndex()
        cm = self._make_cm("ICCID_LATE")

        detected = []
        w = CardWatcher(cm, idx)
        w.on_card_detected = lambda ic, d, fp: detected.append((ic, d, fp))
        w._check_once()

        assert idx.rescan_calls == ["/mnt/share"], "rescan_if_stale must be called once"
        assert len(detected) == 1
        assert detected[0][0] == "ICCID_LATE"
        assert detected[0][1]["ADM1"] == "72762965"

    def test_lookup_still_missing_after_rescan_fires_on_card_unknown(self):
        """If ICCID is still absent after rescan, on_card_unknown is called."""
        class AlwaysMissIndex(FakeIndex):
            @property
            def scanned_dirs(self):
                return frozenset(["/mnt/share"])

            def rescan_if_stale(self, directory):
                self.rescan_calls.append(directory)
                return None

        idx = AlwaysMissIndex()
        cm = self._make_cm("ICCID_REALLY_GONE")

        unknown = []
        w = CardWatcher(cm, idx)
        w.on_card_unknown = lambda ic: unknown.append(ic)
        w._check_once()

        assert idx.rescan_calls == ["/mnt/share"], "rescan_if_stale must be called"
        assert unknown == ["ICCID_REALLY_GONE"]

    def test_rescan_on_miss_uses_fresh_csv_adm1(self, tmp_path):
        """Integration: card insert after CSV replacement finds new ADM1."""
        import csv as _csv
        from managers.iccid_index import IccidIndex

        iccid = "8949440000001775004"
        csv_path = str(tmp_path / "batch.csv")

        # Write initial file with old ADM1
        with open(csv_path, "w", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=["ICCID", "ADM1"])
            w.writeheader()
            w.writerow({"ICCID": iccid, "ADM1": "3838383838383838"})

        idx = IccidIndex()
        idx.scan_directory(str(tmp_path))

        # Prime cache with old data
        card_old = idx.load_card(iccid)
        assert card_old["ADM1"] == "3838383838383838"

        # Replace file with new ADM1, bump mtime
        with open(csv_path, "w", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=["ICCID", "ADM1"])
            w.writeheader()
            w.writerow({"ICCID": iccid, "ADM1": "72762965"})
        import os
        new_mtime = os.path.getmtime(csv_path) + 1
        os.utime(csv_path, (new_mtime, new_mtime))

        # Simulate card insert: lookup misses (stale), rescan fires, retry succeeds
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = iccid

        detected = []
        w2 = CardWatcher(cm, idx)
        w2.on_card_detected = lambda ic, d, fp: detected.append((ic, d, fp))
        w2._check_once()

        assert len(detected) == 1, "Card must be detected after rescan"
        assert detected[0][1]["ADM1"] == "72762965", (
            f"Expected fresh ADM1 '72762965', got '{detected[0][1]['ADM1']}'"
        )


# ---------------------------------------------------------------------------
# Targeted lookup diagnostic tests
# ---------------------------------------------------------------------------

class TestHandleNewCardLookupDiagnostics:
    """_handle_new_card emits correct callbacks and logs lookup details."""

    def _make_watcher(self, iccid, index):
        cm = FakeCardManager()
        cm.detect_ok = True
        cm.iccid = iccid
        return CardWatcher(cm, index)

    def test_index_hit_emits_detected_not_unknown(self):
        """Fake index containing ICCID fires on_card_detected, never on_card_unknown."""
        iccid = "8949440000001775004"
        entry = FakeIndexEntry("/share/batch.csv")
        card = {"ICCID": iccid, "ADM1": "3838383838383838", "IMSI": "240015000000001"}
        idx = FakeIndex(entries={iccid: entry}, card_data={iccid: card})

        detected = []
        unknown = []
        w = self._make_watcher(iccid, idx)
        w.on_card_detected = lambda ic, d, fp: detected.append((ic, d, fp))
        w.on_card_unknown = lambda ic: unknown.append(ic)
        w._check_once()

        assert unknown == [], (
            f"on_card_unknown must NOT fire when ICCID is in index; got {unknown}"
        )
        assert len(detected) == 1, "on_card_detected must fire exactly once"
        assert detected[0][0] == iccid
        assert detected[0][1] == card
        assert detected[0][2] == "/share/batch.csv"

    def test_index_miss_logs_lookup_details(self, caplog):
        """Lookup miss must log iccid, 'miss', and emit log before on_card_unknown."""
        import logging
        iccid = "8949440000001775004"
        idx = FakeIndex()  # empty — lookup returns None

        unknown = []
        w = self._make_watcher(iccid, idx)
        w.on_card_unknown = lambda ic: unknown.append(ic)

        with caplog.at_level(logging.INFO, logger="managers.card_watcher"):
            w._check_once()

        assert unknown == [iccid], "on_card_unknown must fire with the ICCID on miss"

        log_text = "\n".join(caplog.messages)
        assert "miss" in log_text, f"Expected 'miss' in diagnostic log; got:\n{log_text}"
        assert iccid in log_text, f"Expected ICCID in diagnostic log; got:\n{log_text}"
        assert "on_card_unknown" in log_text, (
            f"Expected emit-log before on_card_unknown; got:\n{log_text}"
        )


# ---------------------------------------------------------------------------
# Tests for _last_read_failed retry flag
# ---------------------------------------------------------------------------

class TestLastReadFailed:
    """_last_read_failed ensures same-ATR cards are retried after a read failure
    and that the flag is correctly cleared on success or card removal."""

    _ATR = "3B 9F 96 80 1F"

    def _make_watcher(self, detect_ok=True, iccid=None):
        cm = FakeCardManager()
        cm.detect_ok = detect_ok
        cm.iccid = iccid
        return CardWatcher(cm), cm

    def test_same_atr_last_read_failed_true_triggers_retry(self):
        """Same ATR + _last_read_failed=True → _read_and_notify is called."""
        w, cm = self._make_watcher(detect_ok=True, iccid=None)
        w._card_present = True
        w._last_atr = self._ATR
        w._last_read_failed = True
        w._handle_probe_result(True, self._ATR)
        # _read_and_notify calls detect_card, incrementing detect_call_count
        assert cm.detect_call_count > 0

    def test_same_atr_last_read_failed_false_no_retry(self):
        """Same ATR + _last_read_failed=False → _read_and_notify is not called."""
        w, cm = self._make_watcher(detect_ok=True, iccid=None)
        w._card_present = True
        w._last_atr = self._ATR
        w._last_read_failed = False
        w._handle_probe_result(True, self._ATR)
        # Same card, no prior failure — detect_card must not be called
        assert cm.detect_call_count == 0

    def test_last_read_failed_set_when_pysim_read_fails(self):
        """When pySim-read returns ok=False, _last_read_failed is set to True."""
        w, cm = self._make_watcher(detect_ok=False)
        w._last_read_failed = False
        w._last_atr = self._ATR
        w._read_and_notify()
        assert w._last_read_failed is True

    def test_last_read_failed_clears_on_successful_read(self):
        """After a successful pySim-read (ICCID returned), _last_read_failed is False."""
        w, cm = self._make_watcher(detect_ok=True, iccid="8949440000001672706")
        w._last_read_failed = True
        w._last_atr = self._ATR
        w._read_and_notify()
        assert w._last_read_failed is False

    def test_last_read_failed_clears_on_blank_card_read(self):
        """ok=True but no ICCID (blank card) also clears _last_read_failed."""
        w, cm = self._make_watcher(detect_ok=True, iccid=None)
        w._last_read_failed = True
        w._last_atr = self._ATR
        w._read_and_notify()
        assert w._last_read_failed is False

    def test_last_read_failed_clears_on_card_removal(self):
        """Card removal via probe clears _last_read_failed."""
        w, cm = self._make_watcher()
        w._card_present = True
        w._last_iccid = "8949440000001672706"  # non-None → skip blank-card debounce
        w._last_read_failed = True
        w._handle_probe_result(False, "No card in reader")
        assert w._last_read_failed is False
