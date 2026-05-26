"""Tests for stale-safe unmount behaviour in NetworkStorageManager.

Verifies:
- Stale tracking (profile in _active_mounts but OS not mounted) is cleared
  by unmount() for both _active_mounts and _actual_mount_paths.
- Normal successful unmount also clears _actual_mount_paths.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from managers.network_storage_manager import NetworkStorageManager, StorageProfile


def _make_profile(label="test-nas"):
    return StorageProfile(
        label=label,
        protocol="smb",
        server="nas.local",
        share="sim",
    )


class TestUnmountStale:
    """unmount() must clear internal state even when the OS mount is already gone."""

    def test_stale_unmount_clears_active_mounts(self, monkeypatch):
        """Profile tracked in _active_mounts but not OS-mounted: unmount() clears it."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts[p.label] = p

        # Simulate OS mount gone
        monkeypatch.setattr(mgr, "is_mounted", lambda _: False)

        ok, msg = mgr.unmount(p)

        assert ok is True
        assert p.label not in mgr._active_mounts

    def test_stale_unmount_returns_not_mounted_message(self, monkeypatch):
        """Stale unmount reports 'Not mounted', not an error."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts[p.label] = p
        monkeypatch.setattr(mgr, "is_mounted", lambda _: False)

        ok, msg = mgr.unmount(p)

        assert ok is True
        assert "Not mounted" in msg

    def test_stale_unmount_clears_actual_mount_paths(self, monkeypatch):
        """Stale unmount also clears _actual_mount_paths for the profile."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts[p.label] = p
        mgr._actual_mount_paths[p.label] = "/Volumes/SIM"
        monkeypatch.setattr(mgr, "is_mounted", lambda _: False)

        mgr.unmount(p)

        assert p.label not in mgr._actual_mount_paths

    def test_stale_unmount_allows_subsequent_delete(self, monkeypatch):
        """After stale unmount, delete_profile() no longer refuses."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts[p.label] = p
        monkeypatch.setattr(mgr, "is_mounted", lambda _: False)
        # Stub save so no settings dependency
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.save_profiles = MagicMock()

        mgr.unmount(p)
        ok, msg = mgr.delete_profile(p.label)

        assert ok is True


class TestUnmountSuccess:
    """Normal successful unmount must also clear _actual_mount_paths."""

    def test_success_clears_actual_mount_paths(self, monkeypatch):
        """Successful unmount removes entry from _actual_mount_paths."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts[p.label] = p
        mgr._actual_mount_paths[p.label] = "/Volumes/SIM"

        monkeypatch.setattr(mgr, "is_mounted", lambda _: True)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            with patch("os.rmdir"):
                ok, _ = mgr.unmount(p)

        assert ok is True
        assert p.label not in mgr._actual_mount_paths
        assert p.label not in mgr._active_mounts
