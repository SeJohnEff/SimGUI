"""Tests for the Disconnect button in NetworkStorageDialogQt.

Verifies:
- Disconnect button is disabled initially (no profile selected).
- Enabled when a profile is selected and is_tracked_as_mounted returns True.
- Disabled when is_tracked_as_mounted returns False.
- Clicking Disconnect calls ns_manager.unmount() with the correct profile.
- Button is disabled after successful unmount.
- Warning shown and button stays enabled on unmount failure.
- Stale unmount (returns True / "Not mounted") also disables the button.
- Prefill from mounted profile enables the disconnect button.
- Prefill from last-used (not mounted) profile leaves button disabled.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
from managers.network_storage_manager import StorageProfile

_app = QApplication.instance() or QApplication(sys.argv)


def _make_profile(label="SIM NAS", mounted=False):
    return StorageProfile(
        label=label, protocol="smb", server="nas.local", share="sim"
    )


def _make_ns_manager(profiles=None, mounted_labels=None):
    ns = MagicMock()
    profiles = profiles or []
    mounted_labels = set(mounted_labels or [])
    ns.load_profiles.return_value = profiles
    ns.is_tracked_as_mounted.side_effect = lambda p: p.label in mounted_labels
    ns.validate_label_unique.return_value = (True, "")
    return ns


def _make_dialog(profiles=None, mounted_labels=None):
    ns = _make_ns_manager(profiles=profiles or [], mounted_labels=mounted_labels or [])
    return NetworkStorageDialogQt(ns_manager=ns), ns


class TestDisconnectButtonInitialState:
    def test_disconnect_btn_disabled_initially_no_profiles(self):
        dlg, _ = _make_dialog()
        assert not dlg.disconnect_btn.isEnabled()

    def test_disconnect_btn_disabled_initially_with_profiles(self):
        p = _make_profile()
        dlg, _ = _make_dialog(profiles=[p], mounted_labels=[])
        # Combo is at index 0 ("Select saved profile"), so no profile selected
        dlg.profiles_combo.setCurrentIndex(0)
        assert not dlg.disconnect_btn.isEnabled()


class TestDisconnectButtonOnProfileSelected:
    def test_enabled_when_profile_is_active(self):
        p = _make_profile("NAS-A")
        dlg, _ = _make_dialog(profiles=[p], mounted_labels=["NAS-A"])
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.disconnect_btn.isEnabled()

    def test_disabled_when_profile_not_active(self):
        p = _make_profile("NAS-B")
        dlg, _ = _make_dialog(profiles=[p], mounted_labels=[])
        dlg.profiles_combo.setCurrentIndex(1)
        assert not dlg.disconnect_btn.isEnabled()

    def test_disabled_after_selecting_placeholder(self):
        p = _make_profile("NAS-C")
        dlg, _ = _make_dialog(profiles=[p], mounted_labels=["NAS-C"])
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.disconnect_btn.isEnabled()
        dlg.profiles_combo.setCurrentIndex(0)
        assert not dlg.disconnect_btn.isEnabled()


class TestPrefillDisconnectState:
    def test_prefill_mounted_enables_disconnect(self):
        p = _make_profile("NAS-D")
        p.last_used = True
        dlg, _ = _make_dialog(profiles=[p], mounted_labels=["NAS-D"])
        assert dlg.disconnect_btn.isEnabled()

    def test_prefill_last_used_not_mounted_leaves_disconnect_disabled(self):
        p = _make_profile("NAS-E")
        p.last_used = True
        dlg, _ = _make_dialog(profiles=[p], mounted_labels=[])
        assert not dlg.disconnect_btn.isEnabled()


class TestDisconnectAction:
    def test_disconnect_calls_unmount(self):
        p = _make_profile("NAS-F")
        dlg, ns = _make_dialog(profiles=[p], mounted_labels=["NAS-F"])
        dlg.profiles_combo.setCurrentIndex(1)
        ns.unmount.return_value = (True, "Unmounted")

        with patch.object(dlg, "disconnect_btn"):
            with patch("PyQt6.QtWidgets.QMessageBox.information"):
                dlg._on_disconnect()

        ns.unmount.assert_called_once_with(p)

    def test_disconnect_disables_btn_on_success(self):
        p = _make_profile("NAS-G")
        dlg, ns = _make_dialog(profiles=[p], mounted_labels=["NAS-G"])
        dlg.profiles_combo.setCurrentIndex(1)
        ns.unmount.return_value = (True, "Unmounted")

        with patch("PyQt6.QtWidgets.QMessageBox.information"):
            dlg._on_disconnect()

        assert not dlg.disconnect_btn.isEnabled()

    def test_disconnect_stale_also_disables_btn(self):
        """unmount() returning (True, 'Not mounted') is treated as success."""
        p = _make_profile("NAS-H")
        dlg, ns = _make_dialog(profiles=[p], mounted_labels=["NAS-H"])
        dlg.profiles_combo.setCurrentIndex(1)
        ns.unmount.return_value = (True, "Not mounted")

        with patch("PyQt6.QtWidgets.QMessageBox.information"):
            dlg._on_disconnect()

        assert not dlg.disconnect_btn.isEnabled()

    def test_disconnect_failure_shows_warning(self):
        p = _make_profile("NAS-I")
        dlg, ns = _make_dialog(profiles=[p], mounted_labels=["NAS-I"])
        dlg.profiles_combo.setCurrentIndex(1)
        ns.unmount.return_value = (False, "Unmount failed: device busy")

        with patch("PyQt6.QtWidgets.QMessageBox.warning") as mock_warn:
            dlg._on_disconnect()

        mock_warn.assert_called_once()
        call_args = mock_warn.call_args[0]
        assert "Disconnect Failed" in call_args[1]

    def test_disconnect_failure_leaves_btn_enabled(self):
        p = _make_profile("NAS-J")
        dlg, ns = _make_dialog(profiles=[p], mounted_labels=["NAS-J"])
        dlg.profiles_combo.setCurrentIndex(1)
        ns.unmount.return_value = (False, "Unmount failed")

        with patch("PyQt6.QtWidgets.QMessageBox.warning"):
            dlg._on_disconnect()

        assert dlg.disconnect_btn.isEnabled()

    def test_disconnect_does_not_close_dialog(self):
        p = _make_profile("NAS-K")
        dlg, ns = _make_dialog(profiles=[p], mounted_labels=["NAS-K"])
        dlg.profiles_combo.setCurrentIndex(1)
        ns.unmount.return_value = (True, "Unmounted")

        with patch("PyQt6.QtWidgets.QMessageBox.information"):
            with patch.object(dlg, "accept") as mock_accept:
                with patch.object(dlg, "reject") as mock_reject:
                    dlg._on_disconnect()

        mock_accept.assert_not_called()
        mock_reject.assert_not_called()
