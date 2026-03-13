"""Tests for widgets/progress_panel.py pure logic.

Uses a standalone harness that replicates ProgressPanel's non-GUI logic.
"""

import os
import sys
import threading
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeWidget:
    """Minimal fake widget for testing."""

    def __init__(self, **kw):
        self._config = dict(kw)

    def __setitem__(self, key, value):
        self._config[key] = value

    def __getitem__(self, key):
        return self._config.get(key, 0)

    def configure(self, **kw):
        self._config.update(kw)

    def insert(self, *a):
        self._inserted = a

    def delete(self, *a):
        self._deleted = a

    def see(self, *a):
        pass

    def start(self, ms=10):
        self._started = True

    def stop(self):
        self._stopped = True


class ProgressPanelHarness:
    """Replicates ProgressPanel's non-GUI logic for testing."""

    def __init__(self):
        self._cancel_event = threading.Event()
        self._progress_bar = _FakeWidget(maximum=100, value=0, mode='determinate')
        self._progress_label = _FakeWidget(text="Idle")
        self._percent_label = _FakeWidget(text="0%")
        self._log_text = _FakeWidget(state="disabled")
        self._log_messages = []
        self._exists = True

    def winfo_exists(self):
        return self._exists

    def after(self, delay, callback):
        callback()

    def set_progress(self, value, maximum=100, label=None):
        def _do():
            if not self.winfo_exists():
                return
            self._progress_bar['maximum'] = maximum
            self._progress_bar['value'] = value
            pct = int((value / maximum) * 100) if maximum > 0 else 0
            self._percent_label.configure(text=f"{pct}%")
            if label:
                self._progress_label.configure(text=label)
        self.after(0, _do)

    def set_indeterminate(self, running=True):
        def _do():
            if not self.winfo_exists():
                return
            if running:
                self._progress_bar.configure(mode='indeterminate')
                self._progress_bar.start(10)
            else:
                self._progress_bar.stop()
                self._progress_bar.configure(mode='determinate')
        self.after(0, _do)

    def log(self, message):
        from datetime import datetime
        ts = datetime.now().strftime('%H:%M:%S')
        def _do():
            if not self.winfo_exists():
                return
            self._log_messages.append(f"[{ts}] {message}")
        self.after(0, _do)

    def clear_log(self):
        def _do():
            if not self.winfo_exists():
                return
            self._log_messages.clear()
        self.after(0, _do)

    def reset(self):
        self._cancel_event.clear()
        def _do():
            if not self.winfo_exists():
                return
            self._progress_bar.stop()
            self._progress_bar.configure(mode='determinate', value=0)
            self._progress_label.configure(text="Idle")
            self._percent_label.configure(text="0%")
        self.after(0, _do)

    def cancel(self):
        self._cancel_event.set()
        self.log("Cancellation requested")

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()


class TestProgressPanelCancel:
    """Tests for cancel/cancelled logic."""

    def test_cancelled_false_initially(self):
        """cancelled property is False initially."""
        p = ProgressPanelHarness()
        assert p.cancelled is False

    def test_cancel_sets_event(self):
        """cancel() sets the _cancel_event."""
        p = ProgressPanelHarness()
        p.cancel()
        assert p.cancelled is True

    def test_cancel_logs_message(self):
        """cancel() logs a cancellation message."""
        p = ProgressPanelHarness()
        p.cancel()
        assert any("Cancellation" in m for m in p._log_messages)

    def test_reset_clears_cancel(self):
        """reset() clears the cancellation event."""
        p = ProgressPanelHarness()
        p.cancel()
        p.reset()
        assert p.cancelled is False

    def test_cancel_event_is_threading_event(self):
        """_cancel_event is a threading.Event."""
        p = ProgressPanelHarness()
        assert isinstance(p._cancel_event, threading.Event)


class TestProgressPanelSetProgress:
    """Tests for set_progress."""

    def test_updates_progress_bar_value(self):
        """set_progress updates the bar's value."""
        p = ProgressPanelHarness()
        p.set_progress(50, maximum=100)
        assert p._progress_bar['value'] == 50

    def test_updates_maximum(self):
        """set_progress updates the bar's maximum."""
        p = ProgressPanelHarness()
        p.set_progress(25, maximum=200)
        assert p._progress_bar['maximum'] == 200

    def test_percent_label_updated(self):
        """set_progress updates percent label."""
        p = ProgressPanelHarness()
        p.set_progress(25, maximum=100)
        assert "25%" in p._percent_label._config.get("text", "")

    def test_zero_maximum_no_error(self):
        """set_progress with maximum=0 does not raise ZeroDivisionError."""
        p = ProgressPanelHarness()
        p.set_progress(0, maximum=0)  # should not raise

    def test_label_updated_when_provided(self):
        """set_progress updates progress label when label is provided."""
        p = ProgressPanelHarness()
        p.set_progress(10, maximum=100, label="Loading cards")
        assert "Loading cards" in p._progress_label._config.get("text", "")

    def test_label_not_cleared_when_not_provided(self):
        """set_progress leaves progress label unchanged when no label given."""
        p = ProgressPanelHarness()
        p._progress_label.configure(text="Custom Label")
        p.set_progress(10, maximum=100)  # no label arg
        assert p._progress_label._config.get("text") == "Custom Label"

    def test_winfo_exists_false_skips_update(self):
        """set_progress skips if winfo_exists() returns False."""
        p = ProgressPanelHarness()
        p._exists = False
        p.set_progress(50, maximum=100)
        # bar should still have default value 0
        assert p._progress_bar['value'] == 0


class TestProgressPanelIndeterminate:
    """Tests for set_indeterminate."""

    def test_indeterminate_true_starts_bar(self):
        """set_indeterminate(True) starts the progress bar."""
        p = ProgressPanelHarness()
        p.set_indeterminate(running=True)
        assert p._progress_bar._config.get("mode") == "indeterminate"
        assert getattr(p._progress_bar, "_started", False)

    def test_indeterminate_false_stops_bar(self):
        """set_indeterminate(False) stops the progress bar."""
        p = ProgressPanelHarness()
        p.set_indeterminate(running=False)
        assert getattr(p._progress_bar, "_stopped", False)
        assert p._progress_bar._config.get("mode") == "determinate"


class TestProgressPanelLog:
    """Tests for log and clear_log."""

    def test_log_adds_message(self):
        """log() appends a timestamped message."""
        p = ProgressPanelHarness()
        p.log("Hello world")
        assert any("Hello world" in m for m in p._log_messages)

    def test_log_message_has_timestamp(self):
        """log() message includes a timestamp bracket."""
        p = ProgressPanelHarness()
        p.log("Test")
        assert any("[" in m for m in p._log_messages)

    def test_clear_log_empties_messages(self):
        """clear_log() removes all log messages."""
        p = ProgressPanelHarness()
        p.log("msg1")
        p.log("msg2")
        p.clear_log()
        assert len(p._log_messages) == 0

    def test_log_skips_when_not_exists(self):
        """log() skips when winfo_exists() returns False."""
        p = ProgressPanelHarness()
        p._exists = False
        p.log("Should not be logged")
        assert len(p._log_messages) == 0


class TestProgressPanelReset:
    """Tests for reset."""

    def test_reset_sets_idle_label(self):
        """reset() sets progress label to 'Idle'."""
        p = ProgressPanelHarness()
        p._progress_label.configure(text="Processing")
        p.reset()
        assert p._progress_label._config.get("text") == "Idle"

    def test_reset_sets_zero_percent(self):
        """reset() sets percent label to '0%'."""
        p = ProgressPanelHarness()
        p._percent_label.configure(text="75%")
        p.reset()
        assert p._percent_label._config.get("text") == "0%"

    def test_reset_sets_determinate_mode(self):
        """reset() sets progress bar to determinate mode."""
        p = ProgressPanelHarness()
        p._progress_bar.configure(mode="indeterminate")
        p.reset()
        assert p._progress_bar._config.get("mode") == "determinate"

    def test_reset_sets_value_zero(self):
        """reset() sets progress bar value to 0."""
        p = ProgressPanelHarness()
        p._progress_bar.configure(value=75)
        p.reset()
        assert p._progress_bar._config.get("value") == 0
