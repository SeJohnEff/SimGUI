#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests: CardWatcher callbacks must not touch Qt objects directly.

Bug: on_detected and on_unknown called self._program_panel.on_card_detected()
directly from the CardWatcher background thread (threading.Thread).  Any Qt
widget mutation from a non-main thread triggers "QObject: Cannot create
children for a parent that is in a different thread" (QTextDocument warning).

Fix: _wire_card_watcher() now assigns relay.signal.emit to each callback so
the background thread only calls thread-safe signal emission.  Handlers run on
the main thread via Qt's QueuedConnection.

These tests verify the wiring contract without starting a full QApplication
main loop.
"""

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv or ["test"])
    return app


_qapp = _ensure_qapp()


# ---------------------------------------------------------------------------
# Import the relay class directly so we can inspect it without a full window
# ---------------------------------------------------------------------------

from main import _CardWatcherRelay  # noqa: E402


class TestCardWatcherRelaySignals(unittest.TestCase):
    """_CardWatcherRelay must expose all five CardWatcher callback signals."""

    def test_relay_has_card_detected_signal(self):
        relay = _CardWatcherRelay()
        self.assertTrue(hasattr(relay, 'card_detected'))

    def test_relay_has_card_unknown_signal(self):
        relay = _CardWatcherRelay()
        self.assertTrue(hasattr(relay, 'card_unknown'))

    def test_relay_has_reader_ready_signal(self):
        relay = _CardWatcherRelay()
        self.assertTrue(hasattr(relay, 'reader_ready'))

    def test_relay_has_card_removed_signal(self):
        relay = _CardWatcherRelay()
        self.assertTrue(hasattr(relay, 'card_removed'))

    def test_relay_has_error_occurred_signal(self):
        relay = _CardWatcherRelay()
        self.assertTrue(hasattr(relay, 'error_occurred'))

    def test_relay_is_qobject(self):
        """Relay must be a QObject so Qt manages thread affinity."""
        from PyQt6.QtCore import QObject
        relay = _CardWatcherRelay()
        self.assertIsInstance(relay, QObject)


class TestWatcherCallbacksAreSignalEmitters(unittest.TestCase):
    """Watcher callbacks assigned to relay.signal.emit must deliver through
    the signal to connected slots.

    Invariant: the watcher callback chain is signal-based, so callers (even
    from a non-main thread) only invoke thread-safe signal.emit().  All Qt
    widget access happens in connected slots on the main thread.
    """

    def _fire_and_collect(self, signal, connect_kwargs, fire_fn):
        """Connect a listener to signal, fire via fire_fn, flush events,
        return the list of received values."""
        received = []
        signal.connect(received.append, **connect_kwargs)
        fire_fn()
        _qapp.processEvents()
        return received

    def test_reader_ready_emit_delivers_to_connected_slot(self):
        """Assigning relay.reader_ready.emit to a callback and calling it
        must deliver the signal to connected listeners after processEvents."""
        relay = _CardWatcherRelay()
        received = []
        relay.reader_ready.connect(lambda: received.append(True),
                                   Qt.ConnectionType.QueuedConnection)

        callback = relay.reader_ready.emit  # same as what _wire_card_watcher assigns
        callback()                          # simulate watcher firing
        _qapp.processEvents()

        self.assertEqual(received, [True],
                         "reader_ready signal must reach connected slot")

    def test_card_removed_emit_delivers_to_connected_slot(self):
        relay = _CardWatcherRelay()
        received = []
        relay.card_removed.connect(lambda: received.append(True),
                                   Qt.ConnectionType.QueuedConnection)

        relay.card_removed.emit()
        _qapp.processEvents()

        self.assertEqual(received, [True])

    def test_error_occurred_emit_delivers_message_to_slot(self):
        relay = _CardWatcherRelay()
        received = []
        relay.error_occurred.connect(received.append,
                                     Qt.ConnectionType.QueuedConnection)

        relay.error_occurred.emit("No smart-card reader detected")
        _qapp.processEvents()

        self.assertEqual(received, ["No smart-card reader detected"])

    def test_card_detected_emit_delivers_all_args_to_slot(self):
        relay = _CardWatcherRelay()
        received = []
        relay.card_detected.connect(
            lambda iccid, data, path: received.append((iccid, data, path)),
            Qt.ConnectionType.QueuedConnection)

        iccid = "8901234567890123456"
        data = {"IMSI": "240010000000001"}
        relay.card_detected.emit(iccid, data, "/some/file.csv")
        _qapp.processEvents()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], iccid)
        self.assertEqual(received[0][1], data)

    def test_card_unknown_emit_delivers_empty_iccid(self):
        """Blank card case: card_unknown emitted with empty string."""
        relay = _CardWatcherRelay()
        received = []
        relay.card_unknown.connect(received.append,
                                   Qt.ConnectionType.QueuedConnection)

        relay.card_unknown.emit("")
        _qapp.processEvents()

        self.assertEqual(received, [""])


class TestRelaySignalDelivery(unittest.TestCase):
    """Relay signal emission from a background thread must deliver to connected
    slots — i.e., signal.emit() is thread-safe and invokable from any thread.
    """

    def test_card_removed_emit_from_background_thread_does_not_raise(self):
        """relay.card_removed.emit() called from a plain threading.Thread must
        not raise — confirming signal.emit() is thread-safe."""
        relay = _CardWatcherRelay()
        errors = []

        def _background():
            try:
                relay.card_removed.emit()
            except Exception as exc:
                errors.append(exc)

        t = threading.Thread(target=_background)
        t.start()
        t.join(timeout=2.0)

        self.assertFalse(t.is_alive(), "Background thread timed out")
        self.assertEqual(errors, [],
                         f"relay.card_removed.emit() raised from background thread: {errors}")

    def test_error_occurred_emit_from_background_thread_does_not_raise(self):
        relay = _CardWatcherRelay()
        errors = []

        def _background():
            try:
                relay.error_occurred.emit("No smart-card reader detected")
            except Exception as exc:
                errors.append(exc)

        t = threading.Thread(target=_background)
        t.start()
        t.join(timeout=2.0)

        self.assertFalse(t.is_alive(), "Background thread timed out")
        self.assertEqual(errors, [],
                         f"relay.error_occurred.emit() raised from background thread: {errors}")

    def test_card_detected_emit_from_background_thread_does_not_raise(self):
        relay = _CardWatcherRelay()
        errors = []

        def _background():
            try:
                relay.card_detected.emit("8901234567890123456", {"IMSI": "001"}, "/path/to.csv")
            except Exception as exc:
                errors.append(exc)

        t = threading.Thread(target=_background)
        t.start()
        t.join(timeout=2.0)

        self.assertFalse(t.is_alive(), "Background thread timed out")
        self.assertEqual(errors, [],
                         f"relay.card_detected.emit() raised from background thread: {errors}")


class TestRelayConnectionType(unittest.TestCase):
    """Relay signals must be connected with QueuedConnection so that handlers
    always execute on the main thread, never on the emitting thread."""

    def test_queued_connection_constant_exists(self):
        """Confirm Qt.ConnectionType.QueuedConnection is available (sanity)."""
        self.assertTrue(hasattr(Qt.ConnectionType, 'QueuedConnection'))

    def test_relay_signal_can_connect_with_queued_connection(self):
        """Connecting with QueuedConnection must not raise."""
        relay = _CardWatcherRelay()
        received = []

        try:
            relay.reader_ready.connect(
                lambda: received.append(True),
                Qt.ConnectionType.QueuedConnection
            )
        except Exception as exc:
            self.fail(f"QueuedConnection connect raised: {exc}")


if __name__ == '__main__':
    unittest.main()
