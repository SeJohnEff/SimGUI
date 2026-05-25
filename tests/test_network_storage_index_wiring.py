"""
Targeted tests: network-storage connect → ICCID index rebuild → CardWatcher wiring.

Verifies:
  1. _ScanSharesWorker.run() calls scan_directory() for each mounted path and
     emits index_updated (simulates the rescan triggered by a successful connect).
  2. _on_worker_index_updated() assigns self._iccid_index to self._card_watcher.index
     (CardWatcher receives the refreshed index after every rescan).
"""
import sys
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# QApplication fixture (module-scoped — shared across all tests here)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    existing = QApplication.instance()
    if existing:
        yield existing
        return
    app = QApplication([])
    yield app


# ---------------------------------------------------------------------------
# 1. Simulated network-storage connect triggers index refresh
# ---------------------------------------------------------------------------

def test_connect_triggers_scan_directory(qt_app):
    """_ScanSharesWorker.run() calls iccid_index.scan_directory() for each mount."""
    from main import _ScanSharesWorker

    mock_index = MagicMock()
    mock_index.scan_directory.return_value = MagicMock(
        total_cards=4, files_scanned=1, files_skipped=0, errors=[])

    mounts = [("SIM NAS", "/mnt/simdata")]
    worker = _ScanSharesWorker(mounts, mock_index)

    worker.run()

    mock_index.scan_directory.assert_called_once_with("/mnt/simdata")


def test_connect_triggers_index_updated_signal(qt_app):
    """_ScanSharesWorker emits index_updated after all mounts are scanned."""
    from main import _ScanSharesWorker

    mock_index = MagicMock()
    mock_index.scan_directory.return_value = MagicMock(
        total_cards=0, files_scanned=0, files_skipped=0, errors=[])

    mounts = [("NAS", "/mnt/nas")]
    worker = _ScanSharesWorker(mounts, mock_index)

    emitted = []
    worker.index_updated.connect(lambda: emitted.append(True))
    worker.run()

    assert emitted, "index_updated must fire once after scanning all mounts"


# ---------------------------------------------------------------------------
# 2. CardWatcher receives refreshed index after rescan
# ---------------------------------------------------------------------------

def test_on_worker_index_updated_assigns_index_to_card_watcher():
    """_on_worker_index_updated() sets card_watcher.index = iccid_index."""
    from main import SimGUIApp

    class _FakeWatcher:
        index = None

    class _FakeApp:
        def __init__(self):
            self._card_watcher = _FakeWatcher()
            self._iccid_index = object()   # unique sentinel
            self.state_manager = MagicMock()
            self._batch_panel = MagicMock()

    subject = _FakeApp()
    sentinel = subject._iccid_index

    # Call the real method with our fake self
    SimGUIApp._on_worker_index_updated(subject)

    assert subject._card_watcher.index is sentinel, (
        "card_watcher.index must be assigned iccid_index in _on_worker_index_updated"
    )
