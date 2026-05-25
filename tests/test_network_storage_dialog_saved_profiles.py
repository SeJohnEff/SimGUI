"""Tests for the saved-profile dropdown and button rename in NetworkStorageDialogQt."""

import sys
import os

import pytest
from unittest.mock import MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PyQt6.QtWidgets import QApplication
from managers.network_storage_manager import StorageProfile
from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

_app = QApplication.instance() or QApplication(sys.argv)


def _make_profile(**kwargs):
    defaults = dict(
        label="NAS SIM",
        protocol="smb",
        server="192.168.1.10",
        share="simdata",
        username="simgui",
        password="secret",
        auto_connect=True,
    )
    defaults.update(kwargs)
    return StorageProfile(**defaults)


def _make_ns(profiles=None, tracked=False):
    ns = MagicMock()
    ns.load_profiles.return_value = profiles or []
    ns.is_tracked_as_mounted.return_value = tracked
    return ns


# ---------------------------------------------------------------------------
# Saved-profile dropdown population
# ---------------------------------------------------------------------------

class TestSavedProfilesDropdown:

    def test_dropdown_exists(self):
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns())
        assert hasattr(dlg, "profiles_combo")

    def test_placeholder_at_index_zero(self):
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns())
        assert dlg.profiles_combo.itemText(0) == "— Select saved profile —"

    def test_shows_saved_profiles(self):
        profiles = [_make_profile(label=f"NAS {i}") for i in range(3)]
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns(profiles))
        assert dlg.profiles_combo.count() == 4  # placeholder + 3 profiles

    def test_capped_at_five_profiles(self):
        profiles = [_make_profile(label=f"NAS {i}") for i in range(8)]
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns(profiles))
        assert dlg.profiles_combo.count() == 6  # placeholder + 5

    def test_profile_label_shown_in_dropdown(self):
        p = _make_profile(label="Office NAS")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p]))
        assert dlg.profiles_combo.itemText(1) == "Office NAS"

    def test_fallback_to_server_share_when_no_label(self):
        p = _make_profile(label="", server="10.0.0.1", share="data")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p]))
        assert dlg.profiles_combo.itemText(1) == "10.0.0.1/data"

    def test_no_profiles_shows_only_placeholder(self):
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([]))
        assert dlg.profiles_combo.count() == 1

    def test_no_ns_manager_shows_only_placeholder(self):
        dlg = NetworkStorageDialogQt(ns_manager=None)
        assert dlg.profiles_combo.count() == 1


# ---------------------------------------------------------------------------
# Selecting a profile populates fields
# ---------------------------------------------------------------------------

class TestProfileSelectionPopulatesFields:

    def test_select_profile_sets_server(self):
        p = _make_profile(server="nas.example.com")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p]))
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.server_input.text() == "nas.example.com"

    def test_select_profile_sets_share(self):
        p = _make_profile(share="myshare")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p]))
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.share_input.text() == "myshare"

    def test_select_profile_sets_username(self):
        p = _make_profile(username="admin")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p]))
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.username_input.text() == "admin"

    def test_select_profile_sets_label(self):
        p = _make_profile(label="My NAS")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p]))
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.label_input.text() == "My NAS"

    def test_select_profile_sets_auto_connect(self):
        p = _make_profile(auto_connect=False)
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p]))
        dlg.profiles_combo.setCurrentIndex(1)
        assert not dlg.auto_connect.isChecked()

    def test_select_profile_sets_protocol(self):
        p = _make_profile(protocol="nfs")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p]))
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.protocol_combo.currentText().lower() == "nfs"

    def test_selecting_placeholder_does_not_change_fields(self):
        p = _make_profile(server="192.168.1.1")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p]))
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.server_input.text() == "192.168.1.1"
        dlg.profiles_combo.setCurrentIndex(0)
        # Fields unchanged — placeholder selection is a no-op
        assert dlg.server_input.text() == "192.168.1.1"

    def test_second_profile_populates_over_first(self):
        p1 = _make_profile(label="A", server="10.0.0.1")
        p2 = _make_profile(label="B", server="10.0.0.2")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns([p1, p2]))
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.server_input.text() == "10.0.0.1"
        dlg.profiles_combo.setCurrentIndex(2)
        assert dlg.server_input.text() == "10.0.0.2"


# ---------------------------------------------------------------------------
# Selecting a profile must not trigger any network/mount/verify operation
# ---------------------------------------------------------------------------

class TestProfileSelectionNoNetworkOps:

    def test_select_does_not_call_mount(self):
        p = _make_profile()
        ns = _make_ns([p])
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.profiles_combo.setCurrentIndex(1)
        ns.mount.assert_not_called()

    def test_select_does_not_call_verify_mount_accessible(self):
        p = _make_profile()
        ns = _make_ns([p])
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.profiles_combo.setCurrentIndex(1)
        ns.verify_mount_accessible.assert_not_called()

    def test_select_does_not_call_is_mounted(self):
        p = _make_profile()
        ns = _make_ns([p])
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        ns.is_mounted.reset_mock()
        dlg.profiles_combo.setCurrentIndex(1)
        ns.is_mounted.assert_not_called()

    def test_select_does_not_call_test_connection(self):
        p = _make_profile()
        ns = _make_ns([p])
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.profiles_combo.setCurrentIndex(1)
        ns.test_connection.assert_not_called()


# ---------------------------------------------------------------------------
# Button label
# ---------------------------------------------------------------------------

class TestButtonLabel:

    def test_connect_button_label_is_save_and_connect(self):
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns())
        assert dlg.connect_btn.text() == "Save & Connect"

    def test_connect_button_label_not_old_label(self):
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns())
        assert dlg.connect_btn.text() != "Connect & Save"


# ---------------------------------------------------------------------------
# Save & Connect still calls the same underlying path
# ---------------------------------------------------------------------------

class TestSaveAndConnectAction:

    def test_successful_connect_calls_mount(self):
        p = _make_profile()
        ns = _make_ns([p])
        ns.mount.return_value = (True, "Mounted")
        ns.load_profiles.return_value = []
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.server_input.setText("10.0.0.1")
        dlg.share_input.setText("data")
        dlg.label_input.setText("Test NAS")
        # Patch QMessageBox to avoid interactive popup
        import unittest.mock as mock
        with mock.patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_connect()
        ns.mount.assert_called_once()

    def test_successful_connect_calls_save_profiles(self):
        p = _make_profile()
        ns = _make_ns([p])
        ns.mount.return_value = (True, "Mounted")
        ns.load_profiles.return_value = []
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.server_input.setText("10.0.0.1")
        dlg.share_input.setText("data")
        dlg.label_input.setText("Test NAS")
        import unittest.mock as mock
        with mock.patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_connect()
        ns.save_profiles.assert_called_once()

    def test_failed_connect_does_not_call_save_profiles(self):
        p = _make_profile()
        ns = _make_ns([p])
        ns.mount.return_value = (False, "Host unreachable")
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.server_input.setText("10.0.0.1")
        dlg.share_input.setText("data")
        dlg.label_input.setText("Test NAS")
        import unittest.mock as mock
        with mock.patch("dialogs.network_storage_dialog_qt.QMessageBox.warning"):
            dlg._on_connect()
        ns.save_profiles.assert_not_called()
