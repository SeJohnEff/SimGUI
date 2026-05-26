"""Tests for non-blocking Test Connection in NetworkStorageDialogQt.

Verifies:
- _on_test does not call test_connection synchronously on the UI thread.
- Clicking Test disables buttons and sets "Testing…" text immediately.
- Worker success shows info message and restores buttons.
- Worker failure shows warning message and restores buttons.
- Duplicate label validation fires before the worker is started.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

_app = QApplication.instance() or QApplication(sys.argv)


def _make_ns_manager(unique=(True, ""), test_result=(True, "ok")):
    ns = MagicMock()
    ns.load_profiles.return_value = []
    ns.is_tracked_as_mounted.return_value = False
    ns.validate_label_unique.return_value = unique
    ns.test_connection.return_value = test_result
    return ns


def _make_dialog(ns=None):
    dlg = NetworkStorageDialogQt(ns_manager=ns or _make_ns_manager())
    dlg.server_input.setText("nas.local")
    dlg.share_input.setText("SIM")
    dlg.label_input.setText("test-nas")
    return dlg


class TestTestConnectionNonBlocking:
    """_on_test must delegate to a worker, not call test_connection directly."""

    def test_on_test_does_not_call_test_connection_synchronously(self):
        ns = _make_ns_manager()
        dlg = _make_dialog(ns)
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker:
            MockWorker.return_value = MagicMock()
            dlg._on_test()
        ns.test_connection.assert_not_called()

    def test_on_test_creates_and_starts_worker(self):
        ns = _make_ns_manager()
        dlg = _make_dialog(ns)
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker:
            mock_worker = MagicMock()
            MockWorker.return_value = mock_worker
            dlg._on_test()
        MockWorker.assert_called_once()
        mock_worker.start.assert_called_once()


class TestTestConnectionImmediateFeedback:
    """UI must show testing state before any network I/O."""

    def test_test_btn_disabled_immediately(self):
        dlg = _make_dialog()
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker:
            MockWorker.return_value = MagicMock()
            dlg._on_test()
        assert not dlg.test_btn.isEnabled()

    def test_test_btn_text_set_to_testing(self):
        dlg = _make_dialog()
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker:
            MockWorker.return_value = MagicMock()
            dlg._on_test()
        assert dlg.test_btn.text() == "Testing…"

    def test_connect_btn_disabled_immediately(self):
        dlg = _make_dialog()
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker:
            MockWorker.return_value = MagicMock()
            dlg._on_test()
        assert not dlg.connect_btn.isEnabled()


class TestTestConnectionResult:
    """Worker result must restore buttons and show the correct popup."""

    def _put_in_testing_state(self, dlg):
        dlg.test_btn.setEnabled(False)
        dlg.test_btn.setText("Testing…")
        dlg.connect_btn.setEnabled(False)

    def test_success_restores_test_btn(self):
        dlg = _make_dialog()
        self._put_in_testing_state(dlg)
        with patch("dialogs.network_storage_dialog_qt.QMessageBox"):
            dlg._on_test_result(True, "all good")
        assert dlg.test_btn.isEnabled()
        assert dlg.test_btn.text() == "Test Connection"

    def test_success_restores_connect_btn(self):
        dlg = _make_dialog()
        self._put_in_testing_state(dlg)
        with patch("dialogs.network_storage_dialog_qt.QMessageBox"):
            dlg._on_test_result(True, "all good")
        assert dlg.connect_btn.isEnabled()

    def test_success_shows_information_popup(self):
        dlg = _make_dialog()
        self._put_in_testing_state(dlg)
        with patch("dialogs.network_storage_dialog_qt.QMessageBox") as MockMB:
            dlg._on_test_result(True, "all good")
        MockMB.information.assert_called_once()
        MockMB.warning.assert_not_called()

    def test_failure_restores_test_btn(self):
        dlg = _make_dialog()
        self._put_in_testing_state(dlg)
        with patch("dialogs.network_storage_dialog_qt.QMessageBox"):
            dlg._on_test_result(False, "Connection timed out (15 s)")
        assert dlg.test_btn.isEnabled()
        assert dlg.test_btn.text() == "Test Connection"

    def test_failure_restores_connect_btn(self):
        dlg = _make_dialog()
        self._put_in_testing_state(dlg)
        with patch("dialogs.network_storage_dialog_qt.QMessageBox"):
            dlg._on_test_result(False, "Connection timed out (15 s)")
        assert dlg.connect_btn.isEnabled()

    def test_failure_shows_warning_popup(self):
        dlg = _make_dialog()
        self._put_in_testing_state(dlg)
        with patch("dialogs.network_storage_dialog_qt.QMessageBox") as MockMB:
            dlg._on_test_result(False, "Connection timed out (15 s)")
        MockMB.warning.assert_called_once()
        MockMB.information.assert_not_called()


class TestDuplicateLabelBlocksWorker:
    """Label uniqueness failure must prevent worker from starting."""

    def test_duplicate_label_no_worker_created(self):
        ns = _make_ns_manager(unique=(False, "Label already used"))
        dlg = _make_dialog(ns)
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker, \
             patch("dialogs.network_storage_dialog_qt.QMessageBox"):
            dlg._on_test()
        MockWorker.assert_not_called()

    def test_duplicate_label_buttons_unchanged(self):
        ns = _make_ns_manager(unique=(False, "Label already used"))
        dlg = _make_dialog(ns)
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker"), \
             patch("dialogs.network_storage_dialog_qt.QMessageBox"):
            dlg._on_test()
        assert dlg.test_btn.isEnabled()
        assert dlg.connect_btn.isEnabled()
