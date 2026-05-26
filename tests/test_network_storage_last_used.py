"""Tests for last-used profile tracking in NetworkStorageManager.

Covers:
- StorageProfile.last_used schema field (serialise / deserialise)
- mark_last_used() sets flag on one profile, clears it on all others
- get_last_used_label() reads the flag from saved profiles
- reconnect_saved() attempts only the last_used profile
- reconnect_saved() with multiple profiles only connects the last_used one
- deleting the last_used profile clears the flag; no crash on next startup
- no-last_used state → reconnect_saved() returns []
- failed startup reconnect reported as disconnected, not silent success
- successful startup reconnect reflected in active mounts
"""

import json
import os
import sys
import tempfile

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from managers.network_storage_manager import NetworkStorageManager, StorageProfile
from managers.settings_manager import SettingsManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(label="NAS SIM", last_used=False, **kwargs):
    defaults = dict(
        protocol="smb", server="nas.local", share="SIM",
        username="user", password="pw",
    )
    defaults.update(kwargs)
    return StorageProfile(label=label, last_used=last_used, **defaults)


def _make_mgr_with_profiles(profiles):
    """Return a NetworkStorageManager backed by a temp settings file."""
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as fh:
        json.dump({}, fh)
        path = fh.name
    sm = SettingsManager(path=path)
    mgr = NetworkStorageManager(sm)
    mgr.save_profiles(profiles)
    return mgr, path


# ---------------------------------------------------------------------------
# StorageProfile schema: last_used field
# ---------------------------------------------------------------------------

class TestStorageProfileLastUsedField:

    def test_default_is_false(self):
        p = StorageProfile(label="x")
        assert p.last_used is False

    def test_explicit_true(self):
        p = StorageProfile(label="x", last_used=True)
        assert p.last_used is True

    def test_serialises_to_dict(self):
        p = StorageProfile(label="x", last_used=True)
        d = p.to_dict()
        assert "last_used" in d
        assert d["last_used"] is True

    def test_false_serialises_to_dict(self):
        p = StorageProfile(label="x", last_used=False)
        d = p.to_dict()
        assert d["last_used"] is False

    def test_round_trip_via_from_dict(self):
        p = StorageProfile(label="y", last_used=True, server="s", share="sh")
        p2 = StorageProfile.from_dict(p.to_dict())
        assert p2.last_used is True

    def test_from_dict_missing_key_defaults_false(self):
        """Old saved profiles without 'last_used' key still load correctly."""
        d = {"label": "legacy", "server": "s", "share": "sh"}
        p = StorageProfile.from_dict(d)
        assert p.last_used is False


# ---------------------------------------------------------------------------
# mark_last_used / get_last_used_label
# ---------------------------------------------------------------------------

class TestMarkLastUsed:

    def test_mark_sets_flag_on_target(self):
        p1 = _make_profile("A")
        p2 = _make_profile("B")
        mgr, path = _make_mgr_with_profiles([p1, p2])
        try:
            mgr.mark_last_used("A")
            loaded = mgr.load_profiles()
            a = next(p for p in loaded if p.label == "A")
            assert a.last_used is True
        finally:
            os.unlink(path)

    def test_mark_clears_flag_on_others(self):
        p1 = _make_profile("A", last_used=True)
        p2 = _make_profile("B")
        mgr, path = _make_mgr_with_profiles([p1, p2])
        try:
            mgr.mark_last_used("B")
            loaded = mgr.load_profiles()
            a = next(p for p in loaded if p.label == "A")
            b = next(p for p in loaded if p.label == "B")
            assert b.last_used is True
            assert a.last_used is False
        finally:
            os.unlink(path)

    def test_mark_persists_across_reload(self):
        p1 = _make_profile("A")
        mgr, path = _make_mgr_with_profiles([p1])
        try:
            mgr.mark_last_used("A")
            sm2 = SettingsManager(path=path)
            mgr2 = NetworkStorageManager(sm2)
            loaded = mgr2.load_profiles()
            assert loaded[0].last_used is True
        finally:
            os.unlink(path)

    def test_get_last_used_label_returns_label(self):
        p1 = _make_profile("A")
        p2 = _make_profile("B")
        mgr, path = _make_mgr_with_profiles([p1, p2])
        try:
            mgr.mark_last_used("B")
            assert mgr.get_last_used_label() == "B"
        finally:
            os.unlink(path)

    def test_get_last_used_label_none_when_none_marked(self):
        p1 = _make_profile("A")
        mgr, path = _make_mgr_with_profiles([p1])
        try:
            assert mgr.get_last_used_label() is None
        finally:
            os.unlink(path)

    def test_get_last_used_label_none_with_no_settings(self):
        mgr = NetworkStorageManager()  # no settings manager
        assert mgr.get_last_used_label() is None


# ---------------------------------------------------------------------------
# reconnect_saved: only last_used profile is attempted
# ---------------------------------------------------------------------------

class TestReconnectSavedLastUsedFirst:

    def _make_mgr(self, profiles):
        mgr = NetworkStorageManager()
        mgr.load_profiles = MagicMock(return_value=profiles)
        mgr.verify_mount_accessible = MagicMock(return_value=True)
        return mgr

    def test_last_used_profile_attempted(self):
        """last_used=True profile must be the reconnect attempt."""
        p_secondary = _make_profile("Secondary", last_used=False)
        p_primary = _make_profile("Primary", last_used=True)
        mgr = self._make_mgr([p_secondary, p_primary])

        attempted = []

        def _mock_mount(prof):
            attempted.append(prof.label)
            mgr._active_mounts[prof.label] = prof
            return True, "Mounted"

        mgr.mount = _mock_mount
        mgr.reconnect_saved()

        assert attempted == ["Primary"]

    def test_multiple_profiles_only_last_used_attempted(self):
        """With 3 profiles, only the last_used one is attempted."""
        p1 = _make_profile("NAS-A", last_used=False)
        p2 = _make_profile("NAS-B", last_used=True)
        p3 = _make_profile("NAS-C", last_used=False)
        mgr = self._make_mgr([p1, p2, p3])

        attempted = []

        def _mock_mount(prof):
            attempted.append(prof.label)
            mgr._active_mounts[prof.label] = prof
            return True, "Mounted"

        mgr.mount = _mock_mount
        mgr.reconnect_saved()

        assert attempted == ["NAS-B"]

    def test_no_last_used_nothing_attempted(self):
        """When no profile has last_used=True, nothing is attempted."""
        p1 = _make_profile("First", last_used=False)
        p2 = _make_profile("Second", last_used=False)
        mgr = self._make_mgr([p1, p2])
        mgr.mount = MagicMock()

        results = mgr.reconnect_saved()

        assert results == []
        mgr.mount.assert_not_called()

    def test_successful_reconnect_in_active_mounts(self):
        """Successful reconnect must add profile to _active_mounts."""
        p = _make_profile("NAS", last_used=True)
        mgr = self._make_mgr([p])

        def _mock_mount(prof):
            mgr._active_mounts[prof.label] = prof
            return True, "Mounted"

        mgr.mount = _mock_mount
        mgr.reconnect_saved()

        assert "NAS" in mgr._active_mounts

    def test_failed_reconnect_not_in_active_mounts(self):
        """Failed reconnect must NOT add profile to _active_mounts."""
        p = _make_profile("NAS", last_used=True)
        mgr = self._make_mgr([p])
        mgr.mount = MagicMock(return_value=(False, "Host unreachable"))

        results = mgr.reconnect_saved()

        assert "NAS" not in mgr._active_mounts
        label, ok, msg = results[0]
        assert not ok

    def test_inaccessible_last_used_reported_as_failure(self):
        """last_used profile mounted but inaccessible → reported as failure."""
        p = _make_profile("NAS", last_used=True)
        mgr = self._make_mgr([p])
        mgr.verify_mount_accessible = MagicMock(return_value=False)

        def _mock_mount(prof):
            mgr._active_mounts[prof.label] = prof
            return True, "Mounted"

        mgr.mount = _mock_mount
        results = mgr.reconnect_saved()

        label, ok, msg = results[0]
        assert not ok
        assert "NAS" not in mgr._active_mounts

    def test_multiple_last_used_normalized_to_one(self):
        """If multiple profiles have last_used=True, only first is attempted
        and the others are cleared (persisted)."""
        p1 = _make_profile("First", last_used=True)
        p2 = _make_profile("Second", last_used=True)
        mgr = NetworkStorageManager()
        mgr.load_profiles = MagicMock(return_value=[p1, p2])
        mgr.save_profiles = MagicMock()
        mgr.verify_mount_accessible = MagicMock(return_value=True)

        attempted = []

        def _mock_mount(prof):
            attempted.append(prof.label)
            mgr._active_mounts[prof.label] = prof
            return True, "Mounted"

        mgr.mount = _mock_mount
        mgr.reconnect_saved()

        # Only the first last_used profile attempted
        assert attempted == ["First"]
        # save_profiles called to normalize
        mgr.save_profiles.assert_called_once()
        saved = mgr.save_profiles.call_args[0][0]
        last_used_flags = [p.last_used for p in saved]
        assert last_used_flags.count(True) == 1
        assert saved[0].last_used is True
        assert saved[1].last_used is False


# ---------------------------------------------------------------------------
# Deleting the last_used profile
# ---------------------------------------------------------------------------

class TestDeleteLastUsedProfile:

    def test_delete_last_used_clears_flag_from_saved_profiles(self):
        """After deleting last_used profile, no remaining profile has last_used=True."""
        p1 = _make_profile("Primary", last_used=True)
        p2 = _make_profile("Secondary", last_used=False)
        mgr, path = _make_mgr_with_profiles([p1, p2])
        try:
            mgr.delete_profile("Primary")
            loaded = mgr.load_profiles()
            assert all(not p.last_used for p in loaded)
            assert mgr.get_last_used_label() is None
        finally:
            os.unlink(path)

    def test_delete_last_used_does_not_crash_startup_reconnect(self):
        """After deleting last_used, reconnect_saved() must not raise."""
        p1 = _make_profile("Primary", last_used=True)
        p2 = _make_profile("Secondary", last_used=False)
        mgr, path = _make_mgr_with_profiles([p1, p2])
        try:
            mgr.delete_profile("Primary")
            mgr.mount = MagicMock(return_value=(True, "Mounted"))
            mgr.verify_mount_accessible = MagicMock(return_value=True)
            # No last_used → no reconnect attempt
            results = mgr.reconnect_saved()
            assert results == []
        finally:
            os.unlink(path)

    def test_delete_non_last_used_does_not_affect_last_used_flag(self):
        """Deleting a non-last_used profile leaves the last_used flag intact."""
        p1 = _make_profile("Primary", last_used=True)
        p2 = _make_profile("Secondary", last_used=False)
        mgr, path = _make_mgr_with_profiles([p1, p2])
        try:
            mgr.delete_profile("Secondary")
            assert mgr.get_last_used_label() == "Primary"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Dialog: Save & Connect marks profile as last_used
# ---------------------------------------------------------------------------

class TestDialogSaveConnectMarksLastUsed:

    @pytest.fixture(autouse=True)
    def _ensure_app(self):
        from PyQt6.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication(sys.argv)

    def _make_ns(self, profiles=None, mount_ok=True):
        ns = MagicMock()
        ns.load_profiles.return_value = profiles or []
        ns.validate_label_unique.return_value = (True, "")
        ns.mount.return_value = (mount_ok, "Mounted" if mount_ok else "Failed")
        ns.is_tracked_as_mounted.return_value = False
        return ns

    def test_successful_connect_calls_mark_last_used(self):
        """_on_connect: successful mount must call mark_last_used with the profile label."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        ns = self._make_ns(mount_ok=True)
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.server_input.setText("nas.local")
        dlg.share_input.setText("SIM")
        dlg.label_input.setText("My NAS")

        with patch.object(dlg, "accept"):
            with patch("PyQt6.QtWidgets.QMessageBox.information"):
                dlg._on_connect()

        ns.mark_last_used.assert_called_once_with("My NAS")

    def test_failed_connect_does_not_call_mark_last_used(self):
        """_on_connect: failed mount must NOT call mark_last_used."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        ns = self._make_ns(mount_ok=False)
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        dlg.server_input.setText("nas.local")
        dlg.share_input.setText("SIM")
        dlg.label_input.setText("My NAS")

        with patch("PyQt6.QtWidgets.QMessageBox.warning"):
            dlg._on_connect()

        ns.mark_last_used.assert_not_called()
