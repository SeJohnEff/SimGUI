"""Shared pytest fixtures for SimGUI tests."""

import os
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

# Ensure the project root is on sys.path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox


@pytest.fixture(scope='session', autouse=True)
def qapp():
    """Create a QApplication for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def mock_qt_dialogs(monkeypatch):
    """Mock all blocking Qt dialogs to prevent hangs in tests.

    This fixture is applied to all tests automatically to ensure:
    - No QFileDialog blocks waiting for user input
    - No QMessageBox blocks waiting for user interaction
    - No dialog.exec() is called
    """
    # Mock QFileDialog.getOpenFileName
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *a, **k: ("/tmp/test.csv", "")
    )

    # Mock QFileDialog.getSaveFileName
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *a, **k: ("/tmp/test_save.csv", "")
    )

    # Mock QFileDialog.getExistingDirectory
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *a, **k: "/tmp/test_dir"
    )

    # Mock QMessageBox.information (returns OK)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    # Mock QMessageBox.warning (returns Ok)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    # Mock QMessageBox.critical (returns Ok)
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    # Mock QMessageBox.question (returns Yes)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes
    )


from managers.backup_manager import BackupManager
from managers.card_manager import CardManager
from managers.csv_manager import STANDARD_COLUMNS, CSVManager


@pytest.fixture
def csv_manager():
    """Return a fresh CSVManager."""
    return CSVManager()


@pytest.fixture
def card_manager():
    """Return a CardManager (no real CLI tool expected)."""
    return CardManager()


@pytest.fixture
def backup_manager():
    return BackupManager()


@pytest.fixture
def sample_card():
    """Return a valid card data dict."""
    return {
        'ICCID': '89860012345678901234',
        'IMSI': '001010123456789',
        'Ki': 'A' * 32,
        'OPc': 'B' * 32,
        'ADM1': '12345678',
    }


@pytest.fixture
def sample_csv_file(sample_card):
    """Write a temporary CSV file with one card row and return the path."""
    import csv
    cols = list(STANDARD_COLUMNS)
    fd, path = tempfile.mkstemp(suffix='.csv')
    try:
        with os.fdopen(fd, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
            writer.writeheader()
            writer.writerow(sample_card)
        yield path
    finally:
        os.unlink(path)


@pytest.fixture
def tmp_path_factory_file():
    """Return a temporary file path (caller writes to it)."""
    fd, path = tempfile.mkstemp()
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


import logging as _logging
_cleanup_log = _logging.getLogger("simgui.test.cleanup")


def cleanup_simgui_app(instance) -> None:
    """Defensively tear down a SimGUIApp-like instance started by tests.

    Lifecycle: STARTED → TEARDOWN_REQUESTED → STOPPED
      Each step signals the relevant subsystem to stop, then waits for it.
      Order mirrors SimGUIApp._cleanup_threads so no new work is spawned
      after the watcher is stopped.

    Safe to call on partially-constructed objects and idempotent (each
    attribute is fetched with getattr and each step is independently guarded).
    Exceptions are logged at DEBUG and never re-raised so teardown cannot
    mask the original test failure.

    Owned resources released (in order):
      1. _card_watcher          — CardWatcher daemon poll thread (stop())
      2. _worker_client         — CardWorkerClient or similar (stop/close/shutdown)
      3. _startup_worker_thread — QThread for BackgroundStartupWorker (quit + wait)
      4. window                 — Qt window / pending event queue (close())
    """
    if instance is None:
        return

    # 1. CardWatcher daemon thread
    try:
        watcher = getattr(instance, "_card_watcher", None)
        if watcher is not None and callable(getattr(watcher, "stop", None)):
            watcher.stop()
    except Exception:
        _cleanup_log.debug("cleanup_simgui_app: _card_watcher.stop() raised", exc_info=True)

    # 2. Worker-process client (CardWorkerClient or similar)
    try:
        client = getattr(instance, "_worker_client", None)
        if client is not None:
            for method in ("stop", "close", "shutdown"):
                fn = getattr(client, method, None)
                if callable(fn):
                    fn()
                    break
    except Exception:
        _cleanup_log.debug("cleanup_simgui_app: worker_client cleanup raised", exc_info=True)

    # 3. QThread startup worker
    try:
        thread = getattr(instance, "_startup_worker_thread", None)
        if thread is not None:
            if callable(getattr(thread, "quit", None)):
                thread.quit()
            if callable(getattr(thread, "wait", None)):
                thread.wait(2000)  # 2 s max
    except Exception:
        _cleanup_log.debug("cleanup_simgui_app: _startup_worker_thread cleanup raised", exc_info=True)

    # 4. Qt window close (drains pending events; guard against already-destroyed)
    try:
        if callable(getattr(instance, "close", None)):
            instance.close()
    except Exception:
        _cleanup_log.debug("cleanup_simgui_app: close() raised", exc_info=True)
