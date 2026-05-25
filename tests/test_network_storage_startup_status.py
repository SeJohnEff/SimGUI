"""Tests for network storage startup reachability and UI-thread safety.

Verifies that:
- A saved profile with an unreachable share does not show as connected/green.
- A stale OS mount (is_mounted=True but inaccessible) is not adopted by
  sync_os_mounts().
- A reachable share still shows as connected.
- Opening the Network Storage dialog does not call blocking is_mounted()
  on the UI thread.
"""

import subprocess
import sys
import os

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from managers.network_storage_manager import NetworkStorageManager, StorageProfile


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


# ---------------------------------------------------------------------------
# reconnect_saved — stale mount detection
# ---------------------------------------------------------------------------

class TestReconnectSavedReachability:
    """reconnect_saved() must not mark inaccessible shares as connected."""

    def test_stale_mount_not_in_active_mounts(self):
        """OS mount present but inaccessible → removed from _active_mounts."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock(return_value=(True, "Already mounted"))
        mgr.verify_mount_accessible = MagicMock(return_value=False)

        mgr.reconnect_saved()

        assert p.label not in mgr._active_mounts

    def test_stale_mount_reported_as_failure(self):
        """Stale mount → reconnect_saved returns ok=False."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock(return_value=(True, "Already mounted"))
        mgr.verify_mount_accessible = MagicMock(return_value=False)

        results = mgr.reconnect_saved()

        assert len(results) == 1
        label, ok, msg = results[0]
        assert label == "NAS SIM"
        assert not ok

    def test_accessible_share_stays_connected(self):
        """Accessible mount → ok=True and label in _active_mounts."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])

        def _mock_mount(prof):
            mgr._active_mounts[prof.label] = prof
            return True, "Mounted"

        mgr.mount = _mock_mount
        mgr.verify_mount_accessible = MagicMock(return_value=True)

        results = mgr.reconnect_saved()

        label, ok, msg = results[0]
        assert ok
        assert p.label in mgr._active_mounts

    def test_mount_failure_skips_verify(self):
        """If mount() fails, verify_mount_accessible is never called."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock(return_value=(False, "Host unreachable"))
        mgr.verify_mount_accessible = MagicMock()

        results = mgr.reconnect_saved()

        label, ok, msg = results[0]
        assert not ok
        mgr.verify_mount_accessible.assert_not_called()

    def test_auto_connect_false_not_attempted(self):
        """Profiles with auto_connect=False are never mounted."""
        mgr = NetworkStorageManager()
        p = _make_profile(auto_connect=False)
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock()

        results = mgr.reconnect_saved()

        assert results == []
        mgr.mount.assert_not_called()

    def test_previously_tracked_stale_mount_removed(self):
        """Even if label was in _active_mounts before, stale detection removes it."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts["NAS SIM"] = p  # simulate leftover from prior call
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock(return_value=(True, "Already mounted"))
        mgr.verify_mount_accessible = MagicMock(return_value=False)

        mgr.reconnect_saved()

        assert "NAS SIM" not in mgr._active_mounts


# ---------------------------------------------------------------------------
# sync_os_mounts — stale OS mount detection
# ---------------------------------------------------------------------------

class TestSyncOsMountsReachability:
    """sync_os_mounts() must not adopt stale OS mounts."""

    def test_inaccessible_os_mount_not_adopted(self):
        """OS mount present but inaccessible → not added to _active_mounts."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.is_mounted = MagicMock(return_value=True)
        mgr.verify_mount_accessible = MagicMock(return_value=False)

        mgr.sync_os_mounts()

        assert p.label not in mgr._active_mounts

    def test_accessible_os_mount_adopted(self):
        """OS mount present and accessible → added to _active_mounts."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.is_mounted = MagicMock(return_value=True)
        mgr.verify_mount_accessible = MagicMock(return_value=True)

        mgr.sync_os_mounts()

        assert p.label in mgr._active_mounts

    def test_not_os_mounted_not_checked(self):
        """Profile not in OS mount table → verify_mount_accessible not called."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.is_mounted = MagicMock(return_value=False)
        mgr.verify_mount_accessible = MagicMock()

        mgr.sync_os_mounts()

        mgr.verify_mount_accessible.assert_not_called()
        assert p.label not in mgr._active_mounts

    def test_already_tracked_not_rechecked(self):
        """Profile already in _active_mounts is not re-probed."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts["NAS SIM"] = p
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.is_mounted = MagicMock()
        mgr.verify_mount_accessible = MagicMock()

        mgr.sync_os_mounts()

        mgr.is_mounted.assert_not_called()
        mgr.verify_mount_accessible.assert_not_called()


# ---------------------------------------------------------------------------
# verify_mount_accessible — subprocess probe with bounded timeout
# ---------------------------------------------------------------------------

class TestVerifyMountAccessible:
    """verify_mount_accessible probes the mount via subprocess with timeout."""

    def test_accessible_mount_returns_true(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = mgr.verify_mount_accessible(p)
        assert result is True

    def test_inaccessible_mount_returns_false(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = mgr.verify_mount_accessible(p)
        assert result is False

    def test_timeout_returns_false(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("/bin/ls", 5)):
            result = mgr.verify_mount_accessible(p)
        assert result is False

    def test_exception_returns_false(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run",
                   side_effect=OSError("broken pipe")):
            result = mgr.verify_mount_accessible(p)
        assert result is False

    def test_uses_bounded_timeout(self):
        """subprocess.run must be called with an explicit timeout kwarg."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            mgr.verify_mount_accessible(p)
        _, kwargs = mock_run.call_args
        assert "timeout" in kwargs
        assert kwargs["timeout"] > 0

    def test_probes_mount_point_path(self):
        """subprocess.run target must include the profile's mount point."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            mgr.verify_mount_accessible(p)
        args, _ = mock_run.call_args
        cmd = args[0]
        assert p.mount_point in cmd


# ---------------------------------------------------------------------------
# is_tracked_as_mounted — in-memory check, UI-thread safe
# ---------------------------------------------------------------------------

class TestIsTrackedAsMounted:
    """is_tracked_as_mounted must check _active_mounts only (no filesystem call)."""

    def test_not_tracked_returns_false(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        assert mgr.is_tracked_as_mounted(p) is False

    def test_tracked_returns_true(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts["NAS SIM"] = p
        assert mgr.is_tracked_as_mounted(p) is True

    def test_different_label_returns_false(self):
        mgr = NetworkStorageManager()
        p1 = _make_profile(label="NAS A")
        p2 = _make_profile(label="NAS B")
        mgr._active_mounts["NAS A"] = p1
        assert mgr.is_tracked_as_mounted(p2) is False


# ---------------------------------------------------------------------------
# Dialog prefill — no blocking is_mounted() on UI thread
# ---------------------------------------------------------------------------

class TestDialogPrefillNoBlockingCall:
    """_prefill_from_saved must use is_tracked_as_mounted, not is_mounted."""

    @pytest.fixture(autouse=True)
    def _ensure_app(self):
        from PyQt6.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication(sys.argv)

    def _make_ns(self, profile, tracked=True):
        ns = MagicMock()
        ns.load_profiles.return_value = [profile]
        ns.is_tracked_as_mounted.return_value = tracked
        return ns

    def test_uses_is_tracked_not_is_mounted(self):
        """is_mounted must not be called when opening the dialog."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        p = _make_profile()
        ns = self._make_ns(p, tracked=True)

        NetworkStorageDialogQt(ns_manager=ns)

        ns.is_tracked_as_mounted.assert_called()
        ns.is_mounted.assert_not_called()

    def test_tracked_profile_prefills_fields(self):
        """When a tracked mount exists, its fields are shown in the form."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        p = _make_profile(server="nas.example.com", share="simdata")
        ns = self._make_ns(p, tracked=True)

        dlg = NetworkStorageDialogQt(ns_manager=ns)

        assert dlg.server_input.text() == "nas.example.com"
        assert dlg.share_input.text() == "simdata"

    def test_untracked_share_falls_back_to_auto_connect(self):
        """If no tracked mount, fall back to first auto_connect profile."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        p = _make_profile(server="fallback.host", auto_connect=True)
        ns = self._make_ns(p, tracked=False)

        dlg = NetworkStorageDialogQt(ns_manager=ns)

        assert dlg.server_input.text() == "fallback.host"
        ns.is_mounted.assert_not_called()

    def test_untracked_no_auto_connect_leaves_fields_empty(self):
        """No tracked mount, auto_connect=False → form fields empty."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        p = _make_profile(auto_connect=False)
        ns = self._make_ns(p, tracked=False)

        dlg = NetworkStorageDialogQt(ns_manager=ns)

        assert dlg.server_input.text() == ""
        ns.is_mounted.assert_not_called()
