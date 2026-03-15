"""Tests for network share auto-reconnect and auto_connect persistence."""

import pytest
from unittest.mock import MagicMock, patch

from managers.network_storage_manager import (
    NetworkStorageManager,
    StorageProfile,
)


# ---------------------------------------------------------------------------
# StorageProfile.auto_connect field
# ---------------------------------------------------------------------------

class TestAutoConnectField:
    def test_default_is_false(self):
        p = StorageProfile(label="test")
        assert p.auto_connect is False

    def test_serialises_to_dict(self):
        p = StorageProfile(label="test", auto_connect=True)
        d = p.to_dict()
        assert d["auto_connect"] is True

    def test_deserialises_from_dict(self):
        d = {"label": "test", "auto_connect": True, "protocol": "smb",
             "server": "nas", "share": "data"}
        p = StorageProfile.from_dict(d)
        assert p.auto_connect is True

    def test_deserialises_missing_field(self):
        """Old profiles without auto_connect should default to False."""
        d = {"label": "old-profile", "protocol": "smb",
             "server": "nas", "share": "data"}
        p = StorageProfile.from_dict(d)
        assert p.auto_connect is False


# ---------------------------------------------------------------------------
# NetworkStorageManager.reconnect_saved()
# ---------------------------------------------------------------------------

class TestReconnectSaved:
    def _make_manager(self, profiles):
        """Create a manager with mock settings that returns *profiles*."""
        settings = MagicMock()
        settings.get.return_value = [p.to_dict() for p in profiles]
        mgr = NetworkStorageManager(settings)
        # Inject passwords (normally loaded from cred files)
        for p in profiles:
            if p.password:
                mgr._read_password = MagicMock(return_value=p.password)
        return mgr

    def test_no_profiles(self):
        mgr = self._make_manager([])
        results = mgr.reconnect_saved()
        assert results == []

    def test_skips_non_auto_connect(self):
        p = StorageProfile(label="no-auto", server="nas", share="data",
                           auto_connect=False)
        mgr = self._make_manager([p])
        results = mgr.reconnect_saved()
        assert results == []

    @patch.object(NetworkStorageManager, "mount")
    @patch.object(NetworkStorageManager, "is_mounted", return_value=False)
    def test_reconnects_auto_connect(self, mock_mounted, mock_mount):
        mock_mount.return_value = (True, "Mounted at /tmp/test")
        p = StorageProfile(label="auto-share", server="nas", share="data",
                           auto_connect=True)
        mgr = self._make_manager([p])
        results = mgr.reconnect_saved()
        assert len(results) == 1
        label, ok, msg = results[0]
        assert label == "auto-share"
        assert ok is True
        mock_mount.assert_called_once()

    @patch.object(NetworkStorageManager, "is_mounted", return_value=True)
    def test_already_mounted_still_tracked(self, mock_mounted):
        """Shares already mounted at startup must still be tracked
        in _active_mounts (mount() handles the 'already mounted' path).
        """
        p = StorageProfile(label="mounted", server="nas", share="data",
                           auto_connect=True)
        mgr = self._make_manager([p])
        results = mgr.reconnect_saved()
        assert len(results) == 1
        label, ok, msg = results[0]
        assert label == "mounted"
        assert ok is True
        assert "Already mounted" in msg
        # Critical: profile must be in _active_mounts
        assert "mounted" in mgr._active_mounts

    @patch.object(NetworkStorageManager, "mount")
    @patch.object(NetworkStorageManager, "is_mounted", return_value=False)
    def test_reports_mount_failure(self, mock_mounted, mock_mount):
        mock_mount.return_value = (False, "Connection refused")
        p = StorageProfile(label="fail-share", server="nas", share="data",
                           auto_connect=True)
        mgr = self._make_manager([p])
        results = mgr.reconnect_saved()
        assert len(results) == 1
        label, ok, msg = results[0]
        assert label == "fail-share"
        assert ok is False
        assert "Connection refused" in msg

    @patch.object(NetworkStorageManager, "mount")
    @patch.object(NetworkStorageManager, "is_mounted", return_value=False)
    def test_mixed_profiles(self, mock_mounted, mock_mount):
        """Only auto_connect profiles are attempted."""
        mock_mount.return_value = (True, "Mounted")
        p1 = StorageProfile(label="auto", server="a", share="s",
                            auto_connect=True)
        p2 = StorageProfile(label="manual", server="b", share="s",
                            auto_connect=False)
        p3 = StorageProfile(label="auto2", server="c", share="s",
                            auto_connect=True)
        mgr = self._make_manager([p1, p2, p3])
        results = mgr.reconnect_saved()
        # Only p1 and p3 should be attempted
        assert len(results) == 2
        labels = [r[0] for r in results]
        assert "auto" in labels
        assert "auto2" in labels
        assert "manual" not in labels
