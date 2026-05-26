"""Tests for form-authority and Saved-dropdown clearing in NetworkStorageDialogQt.

Covers the bug where editing form fields after selecting a saved profile left
_editing_label stale, causing Test Connection, Save & Connect, Delete, and
Disconnect to silently operate on the previously-selected saved profile.

Scenarios tested:
1. Selecting a saved profile sets _editing_label and populates the form.
2. Programmatic prefill does NOT clear the Saved combo (guard works).
3. Editing server after selecting a profile clears Saved and _editing_label.
4. Editing label after selecting a profile clears Saved and _editing_label.
5. After editing a profile-defining field, Delete is disabled.
6. After editing a profile-defining field, Disconnect is disabled.
7. Test Connection after editing uses _build_profile() values (HOME_NAS, new server).
8. Test Connection after editing does not carry stale saved-profile identity.
9. Save & Connect after editing uses exclude_label=None for uniqueness validation.
10. Save & Connect while keeping the same label uses exclude_label="DGTLAB_NAS".
11. Delete/Disconnect still work when a saved profile is selected and form is untouched.
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

_DGTLAB_SERVER = "192.168.131.188"
_HOME_SERVER = "192.168.10.197"


def _make_dgtlab():
    return StorageProfile(
        label="DGTLAB_NAS",
        protocol="smb",
        server=_DGTLAB_SERVER,
        share="SIM",
        username="simgui",
        last_used=True,
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
    ns = _make_ns_manager(
        profiles=profiles or [],
        mounted_labels=mounted_labels or [],
    )
    return NetworkStorageDialogQt(ns_manager=ns), ns


# ---------------------------------------------------------------------------
# 1. Selecting a saved profile sets _editing_label and populates the form
# ---------------------------------------------------------------------------

class TestProfileSelectionSetsEditingLabel:
    def test_selecting_dgtlab_sets_editing_label(self):
        p = _make_dgtlab()
        dlg, _ = _make_dialog(profiles=[p])
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg._editing_label == "DGTLAB_NAS"

    def test_selecting_dgtlab_fills_server(self):
        p = _make_dgtlab()
        dlg, _ = _make_dialog(profiles=[p])
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.server_input.text() == _DGTLAB_SERVER

    def test_selecting_dgtlab_fills_label_field(self):
        p = _make_dgtlab()
        dlg, _ = _make_dialog(profiles=[p])
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.label_input.text() == "DGTLAB_NAS"


# ---------------------------------------------------------------------------
# 2. Programmatic prefill does NOT clear the Saved combo
# ---------------------------------------------------------------------------

class TestPrefillDoesNotClearSavedCombo:
    def test_prefill_keeps_combo_at_profile_index(self):
        """_prefill_from_saved() selects the profile in combo; no clearing."""
        p = _make_dgtlab()
        p.last_used = True
        dlg, _ = _make_dialog(profiles=[p])
        # After __init__, the combo should show DGTLAB_NAS (index 1)
        assert dlg.profiles_combo.currentIndex() == 1

    def test_editing_label_set_after_prefill(self):
        p = _make_dgtlab()
        p.last_used = True
        dlg, _ = _make_dialog(profiles=[p])
        assert dlg._editing_label == "DGTLAB_NAS"


# ---------------------------------------------------------------------------
# 3 & 4. Editing a profile-defining field clears Saved and _editing_label
# ---------------------------------------------------------------------------

class TestFormEditClearsSavedSelection:
    def _dlg_with_dgtlab_selected(self):
        p = _make_dgtlab()
        dlg, ns = _make_dialog(profiles=[p])
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg._editing_label == "DGTLAB_NAS"
        return dlg, ns

    def test_editing_server_clears_editing_label(self):
        dlg, _ = self._dlg_with_dgtlab_selected()
        dlg.server_input.setText(_HOME_SERVER)
        assert dlg._editing_label is None

    def test_editing_server_resets_combo_to_placeholder(self):
        dlg, _ = self._dlg_with_dgtlab_selected()
        dlg.server_input.setText(_HOME_SERVER)
        assert dlg.profiles_combo.currentIndex() == 0

    def test_editing_label_clears_editing_label(self):
        dlg, _ = self._dlg_with_dgtlab_selected()
        dlg.label_input.setText("HOME_NAS")
        assert dlg._editing_label is None

    def test_editing_label_resets_combo_to_placeholder(self):
        dlg, _ = self._dlg_with_dgtlab_selected()
        dlg.label_input.setText("HOME_NAS")
        assert dlg.profiles_combo.currentIndex() == 0

    def test_editing_share_clears_editing_label(self):
        dlg, _ = self._dlg_with_dgtlab_selected()
        dlg.share_input.setText("OTHER")
        assert dlg._editing_label is None

    def test_editing_username_clears_editing_label(self):
        dlg, _ = self._dlg_with_dgtlab_selected()
        dlg.username_input.setText("alice")
        assert dlg._editing_label is None

    def test_editing_password_clears_editing_label(self):
        dlg, _ = self._dlg_with_dgtlab_selected()
        dlg.password_input.setText("secret")
        assert dlg._editing_label is None

    def test_changing_protocol_clears_editing_label(self):
        dlg, _ = self._dlg_with_dgtlab_selected()
        # Switch to NFS
        dlg.protocol_combo.setCurrentIndex(1)
        assert dlg._editing_label is None


# ---------------------------------------------------------------------------
# 5 & 6. After editing, Delete and Disconnect are disabled
# ---------------------------------------------------------------------------

class TestFormEditDisablesProfileActions:
    def _dlg_with_dgtlab_selected_and_mounted(self):
        p = _make_dgtlab()
        dlg, ns = _make_dialog(profiles=[p], mounted_labels=["DGTLAB_NAS"])
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg.delete_btn.isEnabled()
        assert dlg.disconnect_btn.isEnabled()
        return dlg, ns

    def test_editing_server_disables_delete(self):
        dlg, _ = self._dlg_with_dgtlab_selected_and_mounted()
        dlg.server_input.setText(_HOME_SERVER)
        assert not dlg.delete_btn.isEnabled()

    def test_editing_server_disables_disconnect(self):
        dlg, _ = self._dlg_with_dgtlab_selected_and_mounted()
        dlg.server_input.setText(_HOME_SERVER)
        assert not dlg.disconnect_btn.isEnabled()

    def test_editing_label_disables_delete(self):
        dlg, _ = self._dlg_with_dgtlab_selected_and_mounted()
        dlg.label_input.setText("HOME_NAS")
        assert not dlg.delete_btn.isEnabled()

    def test_editing_label_disables_disconnect(self):
        dlg, _ = self._dlg_with_dgtlab_selected_and_mounted()
        dlg.label_input.setText("HOME_NAS")
        assert not dlg.disconnect_btn.isEnabled()


# ---------------------------------------------------------------------------
# 7 & 8. Test Connection after editing uses form values, not stale state
# ---------------------------------------------------------------------------

class TestTestConnectionUsesFormValues:
    def _dlg_edited_to_home_nas(self):
        """Simulate: select DGTLAB_NAS, then edit form to HOME_NAS values."""
        p = _make_dgtlab()
        dlg, ns = _make_dialog(profiles=[p])
        dlg.profiles_combo.setCurrentIndex(1)
        # User edits form — these clear _editing_label
        dlg.server_input.setText(_HOME_SERVER)
        dlg.label_input.setText("HOME_NAS")
        return dlg, ns

    def test_test_connection_profile_has_new_server(self):
        dlg, _ = self._dlg_edited_to_home_nas()
        captured = {}
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker:
            MockWorker.return_value = MagicMock()
            dlg._on_test()
        _, profile_arg = MockWorker.call_args[0]
        assert profile_arg.server == _HOME_SERVER

    def test_test_connection_profile_has_new_label(self):
        dlg, _ = self._dlg_edited_to_home_nas()
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker:
            MockWorker.return_value = MagicMock()
            dlg._on_test()
        _, profile_arg = MockWorker.call_args[0]
        assert profile_arg.label == "HOME_NAS"

    def test_test_connection_profile_has_no_stale_dgtlab_server(self):
        dlg, _ = self._dlg_edited_to_home_nas()
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker:
            MockWorker.return_value = MagicMock()
            dlg._on_test()
        _, profile_arg = MockWorker.call_args[0]
        assert profile_arg.server != _DGTLAB_SERVER

    def test_test_connection_editing_label_is_none_after_form_edit(self):
        """_editing_label is cleared, so validate_label_unique gets exclude_label=None."""
        dlg, ns = self._dlg_edited_to_home_nas()
        assert dlg._editing_label is None
        with patch("dialogs.network_storage_dialog_qt._TestConnectionWorker") as MockWorker:
            MockWorker.return_value = MagicMock()
            dlg._on_test()
        _, kwargs = ns.validate_label_unique.call_args
        assert kwargs.get("exclude_label") is None


# ---------------------------------------------------------------------------
# 9 & 10. Save & Connect exclude_label behaviour
# ---------------------------------------------------------------------------

class TestSaveConnectExcludeLabel:
    def test_save_after_editing_uses_exclude_label_none(self):
        """Form edited → _editing_label=None → exclude_label=None passed."""
        p = _make_dgtlab()
        dlg, ns = _make_dialog(profiles=[p])
        dlg.profiles_combo.setCurrentIndex(1)
        # Edit form
        dlg.server_input.setText(_HOME_SERVER)
        dlg.label_input.setText("HOME_NAS")
        assert dlg._editing_label is None

        ns.mount.return_value = (False, "test-stop")  # prevent accept()
        dlg._on_connect()

        _, kwargs = ns.validate_label_unique.call_args
        assert kwargs.get("exclude_label") is None

    def test_save_without_editing_uses_exclude_label_dgtlab(self):
        """No form edit → _editing_label="DGTLAB_NAS" → exclude_label="DGTLAB_NAS"."""
        p = _make_dgtlab()
        dlg, ns = _make_dialog(profiles=[p])
        dlg.profiles_combo.setCurrentIndex(1)
        assert dlg._editing_label == "DGTLAB_NAS"

        ns.mount.return_value = (False, "test-stop")  # prevent accept()
        dlg._on_connect()

        _, kwargs = ns.validate_label_unique.call_args
        assert kwargs.get("exclude_label") == "DGTLAB_NAS"


# ---------------------------------------------------------------------------
# 11. Delete / Disconnect still work when profile is selected and unedited
# ---------------------------------------------------------------------------

class TestDeleteDisconnectWorkWhenUnedited:
    def test_delete_works_when_profile_selected_and_unedited(self):
        p = _make_dgtlab()
        dlg, ns = _make_dialog(profiles=[p])
        dlg.profiles_combo.setCurrentIndex(1)
        ns.delete_profile.return_value = (True, "Profile 'DGTLAB_NAS' deleted.")

        with patch("PyQt6.QtWidgets.QMessageBox.information"):
            dlg._on_delete()

        ns.delete_profile.assert_called_once_with("DGTLAB_NAS")

    def test_disconnect_works_when_profile_selected_and_unedited(self):
        p = _make_dgtlab()
        dlg, ns = _make_dialog(profiles=[p], mounted_labels=["DGTLAB_NAS"])
        dlg.profiles_combo.setCurrentIndex(1)
        ns.unmount.return_value = (True, "Unmounted")

        with patch("PyQt6.QtWidgets.QMessageBox.information"):
            dlg._on_disconnect()

        ns.unmount.assert_called_once()
        unmounted_profile = ns.unmount.call_args[0][0]
        assert unmounted_profile.label == "DGTLAB_NAS"

    def test_delete_does_not_fire_when_form_edited(self):
        p = _make_dgtlab()
        dlg, ns = _make_dialog(profiles=[p])
        dlg.profiles_combo.setCurrentIndex(1)
        dlg.server_input.setText(_HOME_SERVER)  # triggers form-edit clear

        dlg._on_delete()  # _editing_label is None → early return

        ns.delete_profile.assert_not_called()

    def test_disconnect_does_not_fire_when_form_edited(self):
        p = _make_dgtlab()
        dlg, ns = _make_dialog(profiles=[p], mounted_labels=["DGTLAB_NAS"])
        dlg.profiles_combo.setCurrentIndex(1)
        dlg.server_input.setText(_HOME_SERVER)  # triggers form-edit clear

        dlg._on_disconnect()  # _editing_label is None → early return

        ns.unmount.assert_not_called()
