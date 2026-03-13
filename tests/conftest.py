"""Shared pytest fixtures for SimGUI tests."""

import os
import sys
import tempfile

import pytest

# Ensure the project root is on sys.path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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
