"""Tests for network share auto-reconnect (last_used) persistence."""

import pytest
from unittest.mock import MagicMock, patch

from managers.network_storage_manager import (
    NetworkStorageManager,
    StorageProfile,
)


# ---------------------------------------------------------------------------
# NetworkStorageManager.reconnect_saved()
# ---------------------------------------------------------------------------

class TestReconnectSaved:
    def _make_manager(self, profiles):
        """Create a manager with mock settings that returns *profiles*."""
        settings = MagicMock()
        settings.get.return_value = [p.to_dict() for p in profiles]
        mgr = NetworkStorageManager(settings)
        for p in profiles:
            if p.password:
                mgr._read_password = MagicMock(return_value=p.password)
        return mgr

    def test_no_profiles(self):
        mgr = self._make_manager([])
        results = mgr.reconnect_saved()
        assert results == []

    def test_no_last_used_skips_all(self):
        """Profile without last_used=True is never attempted."""
        p = StorageProfile(label="no-last", server="nas", share="data",
                           last_used=False)
        mgr = self._make_manager([p])
        results = mgr.reconnect_saved()
        assert results == []

    @patch.object(NetworkStorageManager, "verify_mount_accessible", return_value=True)
    @patch.object(NetworkStorageManager, "mount")
    @patch.object(NetworkStorageManager, "is_mounted", return_value=False)
    def test_reconnects_last_used(self, mock_mounted, mock_mount, mock_verify):
        mock_mount.return_value = (True, "Mounted at /tmp/test")
        p = StorageProfile(label="last-share", server="nas", share="data",
                           last_used=True)
        mgr = self._make_manager([p])
        results = mgr.reconnect_saved()
        assert len(results) == 1
        label, ok, msg = results[0]
        assert label == "last-share"
        assert ok is True
        mock_mount.assert_called_once()

    @patch.object(NetworkStorageManager, "verify_mount_accessible", return_value=True)
    @patch.object(NetworkStorageManager, "is_mounted", return_value=True)
    def test_already_mounted_still_tracked(self, mock_mounted, mock_verify):
        """Shares already mounted at startup must still be tracked
        in _active_mounts (mount() handles the 'already mounted' path).
        """
        p = StorageProfile(label="mounted", server="nas", share="data",
                           last_used=True)
        mgr = self._make_manager([p])
        results = mgr.reconnect_saved()
        assert len(results) == 1
        label, ok, msg = results[0]
        assert label == "mounted"
        assert ok is True
        assert "Already mounted" in msg
        assert "mounted" in mgr._active_mounts

    @patch.object(NetworkStorageManager, "mount")
    @patch.object(NetworkStorageManager, "is_mounted", return_value=False)
    def test_reports_mount_failure(self, mock_mounted, mock_mount):
        mock_mount.return_value = (False, "Connection refused")
        p = StorageProfile(label="fail-share", server="nas", share="data",
                           last_used=True)
        mgr = self._make_manager([p])
        results = mgr.reconnect_saved()
        assert len(results) == 1
        label, ok, msg = results[0]
        assert label == "fail-share"
        assert ok is False
        assert "Connection refused" in msg

    @patch.object(NetworkStorageManager, "verify_mount_accessible", return_value=True)
    @patch.object(NetworkStorageManager, "mount")
    @patch.object(NetworkStorageManager, "is_mounted", return_value=False)
    def test_only_last_used_attempted(self, mock_mounted, mock_mount, mock_verify):
        """Only the last_used=True profile is attempted; others are ignored."""
        mock_mount.return_value = (True, "Mounted")
        p1 = StorageProfile(label="last", server="a", share="s",
                            last_used=True)
        p2 = StorageProfile(label="other1", server="b", share="s",
                            last_used=False)
        p3 = StorageProfile(label="other2", server="c", share="s",
                            last_used=False)
        mgr = self._make_manager([p1, p2, p3])
        results = mgr.reconnect_saved()
        assert len(results) == 1
        assert results[0][0] == "last"
