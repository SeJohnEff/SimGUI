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


# ---------------------------------------------------------------------------
# 3. If CardWatcher is replaced/recreated, refreshed index is preserved
# ---------------------------------------------------------------------------

def test_card_watcher_index_preserved_if_recreated():
    """If card_watcher is replaced, next _on_worker_index_updated wires index to new watcher."""
    from main import SimGUIApp

    class _FakeWatcher:
        index = None

    class _FakeApp:
        def __init__(self):
            self._card_watcher = _FakeWatcher()
            self._iccid_index = object()
            self.state_manager = MagicMock()
            self._batch_panel = MagicMock()

    subject = _FakeApp()
    sentinel = subject._iccid_index

    # First wiring
    SimGUIApp._on_worker_index_updated(subject)
    assert subject._card_watcher.index is sentinel

    # Simulate watcher recreation
    subject._card_watcher = _FakeWatcher()
    assert subject._card_watcher.index is None  # new watcher starts unwired

    # Next rescan restores the wiring
    SimGUIApp._on_worker_index_updated(subject)
    assert subject._card_watcher.index is sentinel


# ---------------------------------------------------------------------------
# 4. Connected share updates bottom status label with share label + mount path
# ---------------------------------------------------------------------------

def test_connected_share_shows_label_and_mount_path(qt_app):
    """Status label shows share label and local mount path when connected."""
    from main import SimGUIApp
    from state_manager import ShareStatus

    class _FakeLabel:
        def __init__(self):
            self._text = ""
        def setText(self, t):
            self._text = t
        def setStyleSheet(self, _):
            pass

    class _FakeApp:
        def __init__(self):
            self._share_label = _FakeLabel()

    subject = _FakeApp()
    status = ShareStatus(connected=True, mount_paths=[("SIM NAS", "/mnt/simdata")])
    SimGUIApp._on_share_status_changed(subject, status)

    assert "SIM NAS" in subject._share_label._text
    assert "/mnt/simdata" in subject._share_label._text


def test_disconnected_shows_fallback_display_text(qt_app):
    """Status label shows generic fallback when disconnected with no error_text."""
    from main import SimGUIApp
    from state_manager import ShareStatus

    class _FakeLabel:
        def __init__(self):
            self._text = ""
        def setText(self, t):
            self._text = t
        def setStyleSheet(self, _):
            pass

    class _FakeApp:
        def __init__(self):
            self._share_label = _FakeLabel()

    subject = _FakeApp()
    SimGUIApp._on_share_status_changed(subject, ShareStatus(connected=False))

    assert subject._share_label._text == "No network storage connected"


# ---------------------------------------------------------------------------
# 5. _rescan_shares_background: active mount causes scan_directory call
# ---------------------------------------------------------------------------

def test_rescan_background_active_mount_calls_scan_directory(qt_app):
    """Active mount path causes scan_directory(path) call in _ScanSharesWorker."""
    from main import _ScanSharesWorker

    mock_index = MagicMock()
    mock_index.scan_directory.return_value = MagicMock(
        total_cards=3, files_scanned=1, files_skipped=0, errors=[])
    mock_index.stats.return_value = {"total_cards": 3}

    mounts = [("simgui", "/tmp/simgui-mounts/simgui")]
    worker = _ScanSharesWorker(mounts, mock_index)
    worker.run()

    mock_index.scan_directory.assert_called_once_with("/tmp/simgui-mounts/simgui")


def test_rescan_background_emits_index_updated_after_scan(qt_app):
    """After scan_directory completes, index_updated signal fires."""
    from main import _ScanSharesWorker

    mock_index = MagicMock()
    mock_index.scan_directory.return_value = MagicMock(
        total_cards=2, files_scanned=1, files_skipped=0, errors=[])
    mock_index.stats.return_value = {"total_cards": 2}

    emitted = []
    mounts = [("simgui", "/tmp/simgui-mounts/simgui")]
    worker = _ScanSharesWorker(mounts, mock_index)
    worker.index_updated.connect(lambda: emitted.append(True))
    worker.run()

    assert emitted, "index_updated must fire after scan"
    mock_index.scan_directory.assert_called_once()


def test_rescan_background_scan_exception_is_logged_not_swallowed(qt_app, caplog):
    """scan_directory exception is logged and index_updated still fires."""
    import logging
    from main import _ScanSharesWorker

    mock_index = MagicMock()
    mock_index.scan_directory.side_effect = OSError("disk read error")
    mock_index.stats.return_value = {"total_cards": 0}

    emitted = []
    mounts = [("simgui", "/tmp/simgui-mounts/simgui")]
    worker = _ScanSharesWorker(mounts, mock_index)
    worker.index_updated.connect(lambda: emitted.append(True))

    with caplog.at_level(logging.ERROR):
        worker.run()

    assert any("disk read error" in r.message for r in caplog.records), (
        "exception message must appear in logs")
    assert emitted, "index_updated must still fire even after scan exception"
