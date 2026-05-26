"""Tests for label-uniqueness validation and profile deletion.

Covers:
- NetworkStorageManager.validate_label_unique()
- NetworkStorageManager.delete_profile()
- Dialog label-check integration (Test Connection, Save & Connect)
- Delete button enable/disable and _on_delete() flow
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from managers.network_storage_manager import NetworkStorageManager, StorageProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(label="NAS SIM", server="nas.local", share="SIM", **kw):
    return StorageProfile(label=label, server=server, share=share, **kw)


def _ns_with_profiles(*labels):
    """Return a NetworkStorageManager whose load_profiles returns profiles."""
    ns = NetworkStorageManager()
    ns.load_profiles = MagicMock(
        return_value=[_make_profile(label=lbl) for lbl in labels])
    return ns


# ---------------------------------------------------------------------------
# NetworkStorageManager.validate_label_unique
# ---------------------------------------------------------------------------

class TestValidateLabelUnique:

    def test_rejects_duplicate_label(self):
        """Label already used by a saved profile → False."""
        ns = _ns_with_profiles("NAS SIM", "NAS BACKUP")
        ok, msg = ns.validate_label_unique("NAS SIM")
        assert not ok

    def test_error_text_exact(self):
        """Error message must match the specified string exactly."""
        ns = _ns_with_profiles("NAS SIM")
        _, msg = ns.validate_label_unique("NAS SIM")
        assert msg == "Label has to be unique. Label/name already used."

    def test_allows_new_label(self):
        """Label not used by any saved profile → True."""
        ns = _ns_with_profiles("NAS SIM")
        ok, msg = ns.validate_label_unique("NAS BACKUP")
        assert ok
        assert msg == ""

    def test_allows_same_label_when_excluded(self):
        """Editing existing profile: same label excluded → True."""
        ns = _ns_with_profiles("NAS SIM", "NAS BACKUP")
        ok, _ = ns.validate_label_unique("NAS SIM", exclude_label="NAS SIM")
        assert ok

    def test_rejects_label_of_different_profile(self):
        """Editing profile A, entering profile B's label → False."""
        ns = _ns_with_profiles("NAS SIM", "NAS BACKUP")
        ok, _ = ns.validate_label_unique("NAS BACKUP", exclude_label="NAS SIM")
        assert not ok

    def test_allows_any_label_when_no_saved_profiles(self):
        """Empty profile list → any label is valid."""
        ns = _ns_with_profiles()
        ok, _ = ns.validate_label_unique("NAS SIM")
        assert ok

    def test_exclude_none_does_full_check(self):
        """exclude_label=None means no exemption — collision with same label rejected."""
        ns = _ns_with_profiles("NAS SIM")
        ok, _ = ns.validate_label_unique("NAS SIM", exclude_label=None)
        assert not ok


# ---------------------------------------------------------------------------
# NetworkStorageManager.delete_profile
# ---------------------------------------------------------------------------

class TestDeleteProfile:

    def _ns_with_settings(self, profiles):
        """Return a manager with real save/load backed by a temp settings stub."""
        ns = NetworkStorageManager()
        store = {"network_profiles": [p.to_dict() for p in profiles]}

        class _FakeSettings:
            def get(self, key, default=None):
                return store.get(key, default)
            def set(self, key, value):
                store[key] = value
            def save(self):
                pass

        ns._settings = _FakeSettings()
        # _read_password not needed for these tests
        ns._read_password = lambda label: ""
        return ns

    def test_refuses_if_active(self):
        """Profile currently in _active_mounts → deletion refused."""
        p = _make_profile("NAS SIM")
        ns = self._ns_with_settings([p])
        ns._active_mounts["NAS SIM"] = p

        ok, msg = ns.delete_profile("NAS SIM")

        assert not ok
        assert "Cannot delete a connected share" in msg
        assert "Disconnect first" in msg

    def test_removes_from_settings(self):
        """Deleted profile is absent from subsequent load_profiles()."""
        p = _make_profile("NAS SIM")
        ns = self._ns_with_settings([p])

        ok, _ = ns.delete_profile("NAS SIM")

        assert ok
        remaining = ns.load_profiles()
        assert all(r.label != "NAS SIM" for r in remaining)

    def test_other_profiles_untouched(self):
        """Deleting one profile leaves other profiles intact."""
        p1 = _make_profile("NAS SIM")
        p2 = _make_profile("NAS BACKUP", server="backup.local", share="BKP")
        ns = self._ns_with_settings([p1, p2])

        ns.delete_profile("NAS SIM")

        remaining = ns.load_profiles()
        assert any(r.label == "NAS BACKUP" for r in remaining)

    def test_deletes_credential_file(self, tmp_path):
        """Credential file for the profile is removed on delete."""
        p = _make_profile("NAS SIM")
        ns = self._ns_with_settings([p])
        # Point cred dir to tmp and create a fake cred file
        ns._cred_dir = str(tmp_path)
        cred_path = ns._cred_file_path("NAS SIM")
        cred_path_obj = tmp_path / os.path.basename(cred_path)
        cred_path_obj.write_text("username=sim\npassword=secret\n")

        ns.delete_profile("NAS SIM")

        assert not cred_path_obj.exists()

    def test_missing_credential_does_not_raise(self):
        """Deleting a profile with no credential file succeeds without error."""
        p = _make_profile("NAS SIM")
        ns = self._ns_with_settings([p])
        ns._cred_dir = "/tmp/nonexistent-simgui-test-dir"

        ok, _ = ns.delete_profile("NAS SIM")

        assert ok

    def test_returns_success_message_with_label(self):
        """Success message includes the deleted profile's label."""
        p = _make_profile("NAS SIM")
        ns = self._ns_with_settings([p])

        ok, msg = ns.delete_profile("NAS SIM")

        assert ok
        assert "NAS SIM" in msg

    def test_legacy_label_profile_deletable(self):
        """Legacy profile (no extra fields beyond label) can be deleted."""
        # Simulate a legacy profile dict with only the original fields
        ns = NetworkStorageManager()
        store = {"network_profiles": [
            {"label": "NAS SIM", "protocol": "smb", "server": "nas.local",
             "share": "SIM", "username": "", "domain": "",
             "mount_options": "", "export_subdir": "artifacts",
             "export_fields": ["ICCID"]}
        ]}

        class _FakeSettings:
            def get(self, key, default=None):
                return store.get(key, default)
            def set(self, key, value):
                store[key] = value
            def save(self):
                pass

        ns._settings = _FakeSettings()
        ns._read_password = lambda label: ""

        ok, _ = ns.delete_profile("NAS SIM")

        assert ok
        assert ns.load_profiles() == []


# ---------------------------------------------------------------------------
# Dialog — label uniqueness integration
# ---------------------------------------------------------------------------

def _make_ns_mock(saved_labels=None, validate_result=(True, ""),
                  delete_result=(True, "Profile deleted.")):
    """Return a mock NetworkStorageManager for dialog tests."""
    ns = MagicMock(spec=NetworkStorageManager)
    profiles = [_make_profile(label=lbl) for lbl in (saved_labels or [])]
    ns.load_profiles.return_value = profiles
    ns.is_tracked_as_mounted.return_value = False
    ns.validate_label_unique.return_value = validate_result
    ns.delete_profile.return_value = delete_result
    ns.mount.return_value = (True, "Mounted")
    return ns


class TestDialogLabelValidation:
    """Dialog must call validate_label_unique before Test and Save & Connect."""

    def _make_dlg(self, saved_labels=None, validate_result=(True, "")):
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock(saved_labels=saved_labels,
                           validate_result=validate_result)
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.server_input.setText("nas.local")
        dlg.share_input.setText("SIM")
        dlg.label_input.setText("NAS SIM")
        return dlg, ns

    def test_test_connection_blocked_on_duplicate_label(self):
        """validate_label_unique returning False prevents test_connection call."""
        dlg, ns = self._make_dlg(
            validate_result=(False, "Label has to be unique. Label/name already used."))
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.warning"):
            dlg._on_test()
        ns.test_connection.assert_not_called()

    def test_save_and_connect_blocked_on_duplicate_label(self):
        """validate_label_unique returning False prevents mount call."""
        dlg, ns = self._make_dlg(
            validate_result=(False, "Label has to be unique. Label/name already used."))
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.warning"):
            dlg._on_connect()
        ns.mount.assert_not_called()

    def test_duplicate_label_warning_text(self):
        """Warning dialog receives the exact error message from validation."""
        dlg, ns = self._make_dlg(
            validate_result=(False, "Label has to be unique. Label/name already used."))
        shown = []
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.warning",
                   side_effect=lambda *a, **kw: shown.append(a)):
            dlg._on_test()
        assert any("Label has to be unique. Label/name already used." in str(a)
                   for a in shown)

    def test_test_connection_runs_when_label_is_valid(self):
        """validate_label_unique returning True allows test_connection to proceed."""
        dlg, ns = self._make_dlg(validate_result=(True, ""))
        ns.test_connection.return_value = (True, "OK")
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_test()
        ns.test_connection.assert_called_once()

    def test_save_and_connect_runs_when_label_is_valid(self):
        """validate_label_unique returning True allows mount to proceed."""
        dlg, ns = self._make_dlg(validate_result=(True, ""))
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_connect()
        ns.mount.assert_called_once()

    def test_validate_called_with_exclude_label_on_test(self):
        """validate_label_unique receives exclude_label from _editing_label on Test."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock(saved_labels=["NAS SIM"])
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.server_input.setText("nas.local")
        dlg.share_input.setText("SIM")
        dlg.label_input.setText("NAS SIM")
        dlg._editing_label = "NAS SIM"  # simulate profile was selected from combo

        ns.validate_label_unique.return_value = (True, "")
        ns.test_connection.return_value = (True, "OK")
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_test()

        ns.validate_label_unique.assert_called_once_with(
            "NAS SIM", exclude_label="NAS SIM")

    def test_validate_called_with_exclude_label_on_save(self):
        """validate_label_unique receives exclude_label from _editing_label on Save."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock(saved_labels=["NAS SIM"])
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.server_input.setText("nas.local")
        dlg.share_input.setText("SIM")
        dlg.label_input.setText("NAS SIM")
        dlg._editing_label = "NAS SIM"

        ns.validate_label_unique.return_value = (True, "")
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_connect()

        ns.validate_label_unique.assert_called_once_with(
            "NAS SIM", exclude_label="NAS SIM")

    def test_no_editing_label_passes_none_as_exclude(self):
        """Creating new profile: _editing_label is None → exclude_label=None."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock()
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.server_input.setText("nas.local")
        dlg.share_input.setText("SIM")
        dlg.label_input.setText("NAS NEW")
        assert dlg._editing_label is None

        ns.validate_label_unique.return_value = (True, "")
        ns.test_connection.return_value = (True, "OK")
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_test()

        ns.validate_label_unique.assert_called_once_with("NAS NEW", exclude_label=None)


# ---------------------------------------------------------------------------
# Dialog — editing_label tracking from combo selection
# ---------------------------------------------------------------------------

class TestEditingLabelTracking:

    def test_editing_label_set_when_profile_selected_from_combo(self):
        """Selecting a profile in the combo sets _editing_label."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock(saved_labels=["NAS SIM", "NAS BACKUP"])
        dlg = NetworkStorageDialogQt(ns_manager=ns)

        dlg._on_profile_selected(1)  # index 1 = first real profile

        assert dlg._editing_label == "NAS SIM"

    def test_editing_label_cleared_on_placeholder_selection(self):
        """Selecting the placeholder (index 0) clears _editing_label."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock(saved_labels=["NAS SIM"])
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg._editing_label = "NAS SIM"

        dlg._on_profile_selected(0)

        assert dlg._editing_label is None

    def test_editing_label_set_by_prefill_mounted(self):
        """_prefill_from_saved sets _editing_label when a tracked mount is found."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        p = _make_profile("NAS SIM")
        ns = _make_ns_mock(saved_labels=["NAS SIM"])
        ns.load_profiles.return_value = [p]
        ns.is_tracked_as_mounted.return_value = True

        dlg = NetworkStorageDialogQt(ns_manager=ns)

        assert dlg._editing_label == "NAS SIM"

    def test_editing_label_set_by_prefill_last_used(self):
        """_prefill_from_saved sets _editing_label via last_used fallback."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        p = _make_profile("NAS SIM", last_used=True)
        ns = _make_ns_mock()
        ns.load_profiles.return_value = [p]
        ns.is_tracked_as_mounted.return_value = False

        dlg = NetworkStorageDialogQt(ns_manager=ns)

        assert dlg._editing_label == "NAS SIM"


# ---------------------------------------------------------------------------
# Dialog — Delete button
# ---------------------------------------------------------------------------

class TestDeleteButton:

    def _make_dlg(self, saved_labels=None, delete_result=(True, "Profile deleted.")):
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock(saved_labels=saved_labels or [], delete_result=delete_result)
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        return dlg, ns

    def test_delete_button_exists(self):
        """Dialog has a delete_btn attribute."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock()
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        assert hasattr(dlg, "delete_btn")

    def test_delete_button_disabled_by_default(self):
        """Delete button is disabled when no profile is selected."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock()
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        assert not dlg.delete_btn.isEnabled()

    def test_delete_button_enabled_when_profile_selected(self):
        """Delete button is enabled after selecting a profile from combo."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock(saved_labels=["NAS SIM"])
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg._on_profile_selected(1)
        assert dlg.delete_btn.isEnabled()

    def test_delete_button_disabled_after_placeholder_reselected(self):
        """Delete button goes back to disabled when placeholder is selected."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
        ns = _make_ns_mock(saved_labels=["NAS SIM"])
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg._on_profile_selected(1)
        dlg._on_profile_selected(0)
        assert not dlg.delete_btn.isEnabled()

    def test_delete_calls_delete_profile_with_editing_label(self):
        """_on_delete() calls ns_manager.delete_profile with _editing_label."""
        dlg, ns = self._make_dlg(saved_labels=["NAS SIM"])
        dlg._editing_label = "NAS SIM"
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_delete()
        ns.delete_profile.assert_called_once_with("NAS SIM")

    def test_delete_success_reloads_combo(self):
        """Successful delete reloads the saved-profiles combo."""
        dlg, ns = self._make_dlg(saved_labels=["NAS SIM"])
        dlg._editing_label = "NAS SIM"
        initial_call_count = ns.load_profiles.call_count
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_delete()
        assert ns.load_profiles.call_count > initial_call_count

    def test_delete_success_clears_editing_label(self):
        """After successful delete, _editing_label is cleared."""
        dlg, ns = self._make_dlg(saved_labels=["NAS SIM"])
        dlg._editing_label = "NAS SIM"
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_delete()
        assert dlg._editing_label is None

    def test_delete_success_disables_delete_button(self):
        """After successful delete, delete button is disabled."""
        dlg, ns = self._make_dlg(saved_labels=["NAS SIM"])
        dlg._editing_label = "NAS SIM"
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.information"):
            dlg._on_delete()
        assert not dlg.delete_btn.isEnabled()

    def test_delete_refused_shows_warning(self):
        """If delete_profile returns False, a warning is shown."""
        dlg, ns = self._make_dlg(
            delete_result=(False, "Cannot delete a connected share. Disconnect first."))
        dlg._editing_label = "NAS SIM"
        shown = []
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.warning",
                   side_effect=lambda *a, **kw: shown.append(a)):
            dlg._on_delete()
        assert any("Cannot delete a connected share" in str(a) for a in shown)

    def test_delete_refused_keeps_editing_label(self):
        """Failed delete leaves _editing_label and button state unchanged."""
        dlg, ns = self._make_dlg(
            delete_result=(False, "Cannot delete a connected share. Disconnect first."))
        dlg._editing_label = "NAS SIM"
        dlg.delete_btn.setEnabled(True)
        with patch("dialogs.network_storage_dialog_qt.QMessageBox.warning"):
            dlg._on_delete()
        assert dlg._editing_label == "NAS SIM"
        assert dlg.delete_btn.isEnabled()

    def test_delete_noop_when_no_editing_label(self):
        """_on_delete() is a no-op when _editing_label is None."""
        dlg, ns = self._make_dlg()
        dlg._editing_label = None
        dlg._on_delete()
        ns.delete_profile.assert_not_called()
