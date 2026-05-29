"""Tests for subprocess and thread-based card presence probing.

Test plan:
  1. _probe_with_timeout fast path returns ATR correctly.
  2. _probe_with_timeout returns (False, 'PC/SC probe timed out') within a
     short bounded time when conn.connect() blocks.
  3. probe_card_presence delegates to _probe_with_timeout when subprocess
     is unavailable (fallback path).
  4. CardWatcher continues polling when probe_card_presence returns timeout.
  5. Existing no-reader and card-removed CardWatcher behaviour still passes.
  6. Subprocess probe tests (ATR, no-card, timeout, empty output, bad JSON,
     launch failure, thread guard independence).
"""

import subprocess
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

import managers.card_manager as cm_mod
from managers.card_manager import CardManager, _ProbeResult
from managers.card_watcher import CardWatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reader(*, atr=None, connect_delay=0.0, raises=None):
    """Build a mock pyscard reader whose connect() optionally delays or raises."""
    conn = MagicMock()

    def _connect():
        if connect_delay > 0:
            time.sleep(connect_delay)
        if raises is not None:
            raise raises

    conn.connect.side_effect = _connect
    conn.getATR.return_value = atr if atr is not None else [0x3B, 0x9F]
    conn.disconnect.return_value = None

    reader = MagicMock()
    reader.createConnection.return_value = conn
    return reader


def _patched_cm(monkeypatch):
    """Return a CardManager with pyscard patched as available."""
    monkeypatch.setattr(cm_mod, "_pyscard_available", True)
    return CardManager()


# ---------------------------------------------------------------------------
# 1. _probe_with_timeout fast path
# ---------------------------------------------------------------------------

class TestProbeWithTimeoutFastPath:
    def test_returns_atr_on_fast_connect(self, monkeypatch):
        cm = _patched_cm(monkeypatch)
        reader = _make_reader(atr=[0x3B, 0x9F, 0x96])
        ok, result = cm._probe_with_timeout(reader, timeout=1.0)
        assert ok is True
        assert result == "3B 9F 96"

    def test_no_card_exception_returns_no_card(self, monkeypatch):
        # _NoCardException/_CardConnectionException are None until pyscard is
        # imported.  Monkeypatch them so the except clauses in the thread work.
        class FakeNoCard(Exception):
            pass

        monkeypatch.setattr(cm_mod, "_NoCardException", FakeNoCard)
        monkeypatch.setattr(cm_mod, "_CardConnectionException", FakeNoCard)
        cm = _patched_cm(monkeypatch)
        reader = _make_reader(raises=FakeNoCard())
        ok, result = cm._probe_with_timeout(reader, timeout=1.0)
        assert ok is False
        assert result == "No card in reader"

    def test_connection_exception_returns_error_string(self, monkeypatch):
        class FakeNoCard(Exception):
            pass

        class FakeConnErr(Exception):
            pass

        monkeypatch.setattr(cm_mod, "_NoCardException", FakeNoCard)
        monkeypatch.setattr(cm_mod, "_CardConnectionException", FakeConnErr)
        cm = _patched_cm(monkeypatch)
        reader = _make_reader(raises=FakeConnErr("SCard error"))
        ok, result = cm._probe_with_timeout(reader, timeout=1.0)
        assert ok is False
        assert isinstance(result, str)

    def test_generic_exception_returns_error_string(self, monkeypatch):
        class FakeNoCard(Exception):
            pass

        class FakeConnErr(Exception):
            pass

        monkeypatch.setattr(cm_mod, "_NoCardException", FakeNoCard)
        monkeypatch.setattr(cm_mod, "_CardConnectionException", FakeConnErr)
        cm = _patched_cm(monkeypatch)
        reader = _make_reader(raises=RuntimeError("unexpected"))
        ok, result = cm._probe_with_timeout(reader, timeout=1.0)
        assert ok is False
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 2. _probe_with_timeout returns timeout result within bounded time
# ---------------------------------------------------------------------------

class TestProbeWithTimeoutBounded:
    def test_returns_timeout_message_when_connect_blocks(self, monkeypatch):
        cm = _patched_cm(monkeypatch)
        # connect sleeps 10 s; timeout is 0.15 s — must resolve within ~0.5 s
        reader = _make_reader(connect_delay=10.0)
        deadline = time.monotonic() + 0.5
        ok, result = cm._probe_with_timeout(reader, timeout=0.15)
        assert time.monotonic() < deadline, "probe_with_timeout took too long"
        assert ok is False
        assert result == "PC/SC probe timed out"

    def test_timeout_duration_is_respected(self, monkeypatch):
        """Wall-clock time is at least timeout and less than 3× timeout."""
        cm = _patched_cm(monkeypatch)
        reader = _make_reader(connect_delay=10.0)
        t0 = time.monotonic()
        ok, result = cm._probe_with_timeout(reader, timeout=0.1)
        elapsed = time.monotonic() - t0
        assert ok is False
        assert result == "PC/SC probe timed out"
        assert elapsed >= 0.1, "returned before timeout elapsed"
        assert elapsed < 0.4, f"took too long: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# 3. probe_card_presence uses _probe_with_timeout for the selected reader
# ---------------------------------------------------------------------------

class TestProbeCardPresenceDelegates:
    def test_probe_card_presence_calls_probe_with_timeout(self, monkeypatch):
        """When subprocess is unavailable, probe_card_presence falls back to
        _probe_with_timeout.  Subprocess unavailability is forced explicitly."""
        monkeypatch.setattr(cm_mod, "_pyscard_available", True)
        fake_reader = MagicMock()
        monkeypatch.setattr(cm_mod, "_smartcard_readers", lambda: [fake_reader])
        cm = CardManager(pcsc_reader_index=0)

        # Force subprocess path to return unavailable so fallback is exercised.
        cm._probe_via_subprocess = lambda idx, timeout: _ProbeResult.unavailable("no interpreter")

        called_with = []

        def fake_probe(reader, timeout=None):
            called_with.append(reader)
            return True, "3B 9F 96"

        cm._probe_with_timeout = fake_probe
        ok, result = cm.probe_card_presence()
        assert ok is True
        assert called_with == [fake_reader]

    def test_probe_card_presence_returns_timeout_from_helper(self, monkeypatch):
        monkeypatch.setattr(cm_mod, "_pyscard_available", True)
        monkeypatch.setattr(cm_mod, "_smartcard_readers", lambda: [MagicMock()])
        cm = CardManager(pcsc_reader_index=0)
        # Force subprocess unavailable so the thread path runs and returns timeout.
        cm._probe_via_subprocess = lambda idx, timeout: _ProbeResult.unavailable("no interpreter")
        cm._probe_with_timeout = lambda reader, timeout=None: (False, "PC/SC probe timed out")
        ok, result = cm.probe_card_presence()
        assert ok is False
        assert result == "PC/SC probe timed out"


# ---------------------------------------------------------------------------
# 4. CardWatcher continues polling when probe returns "PC/SC probe timed out"
# ---------------------------------------------------------------------------

class FakeCardManagerForWatcher:
    """Scriptable fake CardManager for watcher tests."""

    def __init__(self, probe_sequence):
        self._seq = iter(probe_sequence)
        self._exhausted_result = probe_sequence[-1]
        self.detect_call_count = 0

    def probe_card_presence(self):
        try:
            return next(self._seq)
        except StopIteration:
            return self._exhausted_result

    def detect_card(self):
        self.detect_call_count += 1
        return False, "No card"

    def read_iccid(self):
        return None

    def reset_pyscard(self):
        pass


class TestWatcherContinuesAfterTimeout:
    def _run_watcher(self, probe_sequence, *, n_cycles, poll_interval=0.05):
        """Run CardWatcher for n_cycles polls, return collected callback events."""
        events = []
        barrier = threading.Barrier(2, timeout=5)

        cm = FakeCardManagerForWatcher(probe_sequence)
        w = CardWatcher(cm, poll_interval=poll_interval)
        w.on_error = lambda msg: events.append(("error", msg))
        w.on_card_removed = lambda: events.append(("removed",))
        w.on_reader_ready = lambda: events.append(("ready",))
        w.on_card_unknown = lambda iccid: events.append(("unknown", iccid))

        poll_count = [0]
        original_check = w._check_once

        def counting_check():
            original_check()
            poll_count[0] += 1
            if poll_count[0] >= n_cycles:
                try:
                    barrier.wait(timeout=0)
                except Exception:
                    pass

        w._check_once = counting_check
        w.start()
        barrier.wait(timeout=3)
        w.stop()
        return events, poll_count[0]

    def test_watcher_keeps_polling_after_timeout_result(self):
        """After a timeout probe result, CardWatcher must continue polling."""
        probe_seq = [
            (False, "PC/SC probe timed out"),  # cycle 1 — timeout
            (False, "PC/SC probe timed out"),  # cycle 2
            (False, "No smart-card reader detected"),  # cycle 3 — normal error
        ]
        events, count = self._run_watcher(probe_seq, n_cycles=3)
        assert count >= 3, f"Expected ≥3 polls, got {count}"

    def test_card_removed_fires_after_timeout_then_no_card(self):
        """Sequence: card present → timeout probe → no card → on_card_removed."""
        cm = FakeCardManagerForWatcher([
            (False, "PC/SC probe timed out"),
            (False, "No card in reader"),
        ])
        w = CardWatcher(cm, poll_interval=0.05)
        w._card_present = True
        w._last_iccid = "8949440000001672706"  # non-blank → skip debounce

        removed = threading.Event()
        w.on_card_removed = lambda: removed.set()
        w.on_error = lambda msg: None

        # Manually run two poll cycles (no thread needed)
        w._check_once()  # timeout — card_present stays True
        assert not removed.is_set(), "on_card_removed fired prematurely on timeout"
        w._check_once()  # no card — should fire removal
        assert removed.is_set(), "on_card_removed did not fire after no-card probe"

    def test_timeout_probe_does_not_change_card_present_flag(self):
        """A timeout result is a transient error; _card_present must not be cleared."""
        cm = FakeCardManagerForWatcher([(False, "PC/SC probe timed out")])
        w = CardWatcher(cm, poll_interval=0.05)
        w._card_present = True
        w._last_iccid = "8949440000001672706"
        w.on_error = lambda msg: None
        w._check_once()
        assert w._card_present is True


# ---------------------------------------------------------------------------
# 5. Existing no-reader and card-removed behaviour unchanged
# ---------------------------------------------------------------------------

class TestExistingWatcherBehaviourUnchanged:
    def _watcher_with_probe(self, probe_result, *, card_present=False, last_iccid=None):
        cm = FakeCardManagerForWatcher([probe_result])
        w = CardWatcher(cm, poll_interval=0.05)
        w._card_present = card_present
        w._last_iccid = last_iccid
        events = []
        w.on_error = lambda msg: events.append(("error", msg))
        w.on_card_removed = lambda: events.append(("removed",))
        w.on_reader_ready = lambda: events.append(("ready",))
        w.on_card_unknown = lambda iccid: events.append(("unknown", iccid))
        w._check_once()
        return events

    def test_no_reader_fires_on_error(self):
        events = self._watcher_with_probe((False, "No smart-card reader detected"))
        assert any(e[0] == "error" for e in events)

    def test_card_removed_fires_on_removal(self):
        events = self._watcher_with_probe(
            (False, "No card in reader"),
            card_present=True,
            last_iccid="8949440000001672706",
        )
        assert ("removed",) in events

    def test_reader_idle_fires_reader_ready(self):
        events = self._watcher_with_probe((False, "No card in reader"), card_present=False)
        assert ("ready",) in events


# ---------------------------------------------------------------------------
# In-flight guard: no unbounded thread accumulation
# ---------------------------------------------------------------------------

class TestInFlightGuard:
    def _make_cm(self, monkeypatch):
        class FakeNoCard(Exception):
            pass

        class FakeConnErr(Exception):
            pass

        monkeypatch.setattr(cm_mod, "_pyscard_available", True)
        monkeypatch.setattr(cm_mod, "_NoCardException", FakeNoCard)
        monkeypatch.setattr(cm_mod, "_CardConnectionException", FakeConnErr)
        return CardManager(), FakeNoCard, FakeConnErr

    def test_repeated_calls_while_blocked_do_not_create_new_threads(self, monkeypatch):
        """Calls while a probe is in-flight must not spawn additional threads."""
        cm, _, _ = self._make_cm(monkeypatch)
        gate = threading.Event()
        reader = _make_reader(connect_delay=0)

        # Patch connect to block until gate is set
        def _blocking_connect():
            gate.wait()

        reader.createConnection().connect.side_effect = _blocking_connect

        # Start first probe in a background thread (it will block)
        first_result = []

        def _first():
            first_result.append(cm._probe_with_timeout(reader, timeout=5.0))

        t = threading.Thread(target=_first, daemon=True)
        t.start()
        # Give the probe thread a moment to start and block inside connect
        time.sleep(0.05)
        assert cm._probe_thread is not None and cm._probe_thread.is_alive()

        # Second and third calls should return immediately without new threads
        before = threading.active_count()
        r2 = cm._probe_with_timeout(reader, timeout=0.1)
        r3 = cm._probe_with_timeout(reader, timeout=0.1)
        after = threading.active_count()

        assert r2 == (False, 'PC/SC probe timed out')
        assert r3 == (False, 'PC/SC probe timed out')
        # Thread count must not have grown (guard prevented new spawns)
        assert after <= before, f"Thread count grew from {before} to {after}"

        # Unblock and clean up
        gate.set()
        t.join(timeout=2)

    def test_new_probe_allowed_after_blocked_thread_exits(self, monkeypatch):
        """Once the stalled probe thread completes, the next call can probe again."""
        cm, _, _ = self._make_cm(monkeypatch)
        gate = threading.Event()

        # First reader: blocks until gate is set, then raises NoCardException
        blocking_reader = _make_reader(connect_delay=0)

        def _block_then_raise():
            gate.wait()
            raise Exception("card gone")

        blocking_reader.createConnection().connect.side_effect = _block_then_raise

        # Start probe that will block
        def _blocked_call():
            cm._probe_with_timeout(blocking_reader, timeout=5.0)

        bt = threading.Thread(target=_blocked_call, daemon=True)
        bt.start()
        time.sleep(0.05)
        assert cm._probe_thread.is_alive()

        # Unblock — thread exits
        gate.set()
        bt.join(timeout=2)
        assert not cm._probe_thread.is_alive()

        # New reader that returns ATR normally
        good_reader = _make_reader(atr=[0x3B, 0x9F])
        ok, result = cm._probe_with_timeout(good_reader, timeout=1.0)
        assert ok is True
        assert result == "3B 9F"

    def test_fast_path_unaffected_by_guard(self, monkeypatch):
        """Normal fast probes always succeed regardless of guard state."""
        cm, _, _ = self._make_cm(monkeypatch)
        # _probe_thread is None (initial state) — fast path must work
        reader = _make_reader(atr=[0x3B, 0x6F, 0x00])
        ok, result = cm._probe_with_timeout(reader, timeout=1.0)
        assert ok is True
        assert result == "3B 6F 00"
        # Subsequent fast call also works (thread completed synchronously)
        ok2, result2 = cm._probe_with_timeout(reader, timeout=1.0)
        assert ok2 is True


# ---------------------------------------------------------------------------
# Subprocess probe tests (new in v0.5.60)
# ---------------------------------------------------------------------------

def _make_subprocess_result(stdout="", stderr="", returncode=0):
    """Build a fake subprocess.CompletedProcess."""
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def _patched_probe_cm(monkeypatch):
    """CardManager with pyscard patched as available and one fake reader."""
    monkeypatch.setattr(cm_mod, "_pyscard_available", True)
    monkeypatch.setattr(cm_mod, "_smartcard_readers", lambda: [MagicMock()])
    return CardManager(pcsc_reader_index=0)


class TestSubprocessProbe:
    """Tests for _probe_via_subprocess and its integration into probe_card_presence."""

    # --- 3. ATR JSON response parses correctly ---

    def test_atr_json_response(self, monkeypatch):
        cm = _patched_probe_cm(monkeypatch)
        monkeypatch.setattr(
            cm_mod.subprocess, "run",
            lambda *a, **kw: _make_subprocess_result('{"ok": true, "atr": "3B 9F 96"}'),
        )
        result = cm._probe_via_subprocess(0, 2.0)
        assert result.available is True
        assert result.present is True
        assert result.message == "3B 9F 96"

    # --- 4. no-card JSON response parses correctly ---

    def test_no_card_json_response(self, monkeypatch):
        cm = _patched_probe_cm(monkeypatch)
        monkeypatch.setattr(
            cm_mod.subprocess, "run",
            lambda *a, **kw: _make_subprocess_result('{"ok": false, "msg": "No card in reader"}'),
        )
        result = cm._probe_via_subprocess(0, 2.0)
        assert result.available is True
        assert result.present is False
        assert result.message == "No card in reader"

    # --- 5. empty stdout returns a clean error ---

    def test_empty_stdout_returns_unavailable(self, monkeypatch):
        cm = _patched_probe_cm(monkeypatch)
        monkeypatch.setattr(
            cm_mod.subprocess, "run",
            lambda *a, **kw: _make_subprocess_result("", "some stderr"),
        )
        result = cm._probe_via_subprocess(0, 2.0)
        assert result.available is False
        assert isinstance(result.message, str) and result.message

    # --- 6. malformed JSON returns a clean error ---

    def test_malformed_json_returns_unavailable(self, monkeypatch):
        cm = _patched_probe_cm(monkeypatch)
        monkeypatch.setattr(
            cm_mod.subprocess, "run",
            lambda *a, **kw: _make_subprocess_result("not json at all"),
        )
        result = cm._probe_via_subprocess(0, 2.0)
        assert result.available is False
        assert isinstance(result.message, str) and result.message

    # --- 7. interpreter launch failure returns unavailable; fallback fires ---

    def test_launch_failure_returns_unavailable(self, monkeypatch):
        cm = _patched_probe_cm(monkeypatch)

        def _raise(*a, **kw):
            raise FileNotFoundError("python not found")

        monkeypatch.setattr(cm_mod.subprocess, "run", _raise)
        result = cm._probe_via_subprocess(0, 2.0)
        assert result.available is False

    def test_launch_failure_triggers_thread_fallback(self, monkeypatch):
        """When subprocess cannot launch, probe_card_presence uses _probe_with_timeout."""
        cm = _patched_probe_cm(monkeypatch)

        def _raise(*a, **kw):
            raise FileNotFoundError("python not found")

        monkeypatch.setattr(cm_mod.subprocess, "run", _raise)

        fallback_called = []

        def _fake_thread_probe(reader, timeout=None):
            fallback_called.append(True)
            return True, "3B AB CD"

        cm._probe_with_timeout = _fake_thread_probe
        ok, msg = cm.probe_card_presence()
        assert fallback_called, "_probe_with_timeout was not called as fallback"
        assert ok is True
        assert msg == "3B AB CD"

    # --- 1. subprocess timeout returns 'PC/SC probe timed out'; _probe_thread is None ---

    def test_subprocess_timeout_result_and_no_thread(self, monkeypatch):
        cm = _patched_probe_cm(monkeypatch)

        def _raise_timeout(*a, **kw):
            raise subprocess.TimeoutExpired(cmd=["python"], timeout=2.0)

        monkeypatch.setattr(cm_mod.subprocess, "run", _raise_timeout)
        ok, msg = cm.probe_card_presence()
        assert ok is False
        assert msg == "PC/SC probe timed out"
        assert cm._probe_thread is None

    # --- env: frozen mode passes PYTHONPATH including sys._MEIPASS ---

    def test_subprocess_receives_probe_env_in_frozen_mode(self, monkeypatch):
        """_probe_via_subprocess passes env with sys._MEIPASS in PYTHONPATH (frozen)."""
        import sys as _sys
        cm = _patched_probe_cm(monkeypatch)
        monkeypatch.setattr(_sys, 'frozen', True, raising=False)
        monkeypatch.setattr(_sys, '_MEIPASS', '/fake/meipass', raising=False)
        # _bundled_python is None in dev mode; simulate a frozen bundled interpreter
        cm._bundled_python = '/fake/python3'

        captured = {}

        def _capture(*a, **kw):
            captured.update(kw)
            return _make_subprocess_result('{"ok": false, "msg": "No card in reader"}')

        monkeypatch.setattr(cm_mod.subprocess, "run", _capture)
        cm._probe_via_subprocess(0, 2.0)

        env = captured.get('env')
        assert env is not None, "env not passed to subprocess.run in frozen mode"
        assert '/fake/meipass' in env.get('PYTHONPATH', ''), (
            f"sys._MEIPASS not in PYTHONPATH: {env.get('PYTHONPATH')}"
        )

    # --- pyscard ImportError in msg key returns unavailable ---

    def test_pyscard_import_error_msg_key_returns_unavailable(self, monkeypatch):
        """'pyscard import failed' in 'msg' must return unavailable, not card_absent."""
        cm = _patched_probe_cm(monkeypatch)
        monkeypatch.setattr(
            cm_mod.subprocess, "run",
            lambda *a, **kw: _make_subprocess_result(
                '{"ok": false, "msg": "pyscard import failed: No module named \'smartcard\'"}'
            ),
        )
        result = cm._probe_via_subprocess(0, 2.0)
        assert result.available is False, "ImportError via 'msg' must return unavailable"
        assert "pyscard import failed" in result.message

    # --- pyscard ImportError in error key returns unavailable ---

    def test_pyscard_import_error_error_key_returns_unavailable(self, monkeypatch):
        """'pyscard import failed' in 'error' must return unavailable, not card_absent."""
        cm = _patched_probe_cm(monkeypatch)
        monkeypatch.setattr(
            cm_mod.subprocess, "run",
            lambda *a, **kw: _make_subprocess_result(
                '{"ok": false, "error": "pyscard import failed: No module named \'smartcard\'"}'
            ),
        )
        result = cm._probe_via_subprocess(0, 2.0)
        assert result.available is False, "ImportError via 'error' must return unavailable"
        assert "pyscard import failed" in result.message

    # --- ImportError triggers _probe_with_timeout fallback ---

    def test_import_error_triggers_thread_fallback(self, monkeypatch):
        """probe_card_presence falls back to _probe_with_timeout on pyscard import failure."""
        cm = _patched_probe_cm(monkeypatch)
        monkeypatch.setattr(
            cm_mod.subprocess, "run",
            lambda *a, **kw: _make_subprocess_result(
                '{"ok": false, "msg": "pyscard import failed: No module named \'smartcard\'"}'
            ),
        )
        fallback_called = []

        def _fake_thread_probe(reader, timeout=None):
            fallback_called.append(True)
            return True, "3B AB CD"

        cm._probe_with_timeout = _fake_thread_probe
        ok, msg = cm.probe_card_presence()
        assert fallback_called, "_probe_with_timeout not called on pyscard import failure"
        assert ok is True
        assert msg == "3B AB CD"

    # --- 2. next poll succeeds after subprocess timeout (no in-flight guard blocks it) ---

    def test_next_poll_unblocked_after_subprocess_timeout(self, monkeypatch):
        call_count = [0]

        def _run(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                raise subprocess.TimeoutExpired(cmd=["python"], timeout=2.0)
            return _make_subprocess_result('{"ok": true, "atr": "3B 9F"}')

        monkeypatch.setattr(cm_mod, "_pyscard_available", True)
        monkeypatch.setattr(cm_mod, "_smartcard_readers", lambda: [MagicMock()])
        monkeypatch.setattr(cm_mod.subprocess, "run", _run)
        cm = CardManager(pcsc_reader_index=0)

        ok1, msg1 = cm.probe_card_presence()
        assert ok1 is False
        assert msg1 == "PC/SC probe timed out"
        assert cm._probe_thread is None  # no orphaned thread

        ok2, msg2 = cm.probe_card_presence()
        assert ok2 is True
        assert msg2 == "3B 9F"
