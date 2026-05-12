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
