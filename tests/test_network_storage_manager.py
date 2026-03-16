"""Tests for NetworkStorageManager and StorageProfile."""

import json
import os
import tempfile

import pytest

from managers.network_storage_manager import (
    MOUNT_BASE,
    NetworkStorageManager,
    StorageProfile,
)
from managers.settings_manager import SettingsManager


class TestStorageProfile:
    """Unit tests for StorageProfile dataclass."""

    def test_smb_source_path(self):
        p = StorageProfile(label="test", protocol="smb",
                           server="nas.local", share="simdata")
        assert p.source_path == "//nas.local/simdata"

    def test_smb_source_path_strips_leading_slash(self):
        p = StorageProfile(label="test", protocol="smb",
                           server="nas.local", share="/simdata")
        assert p.source_path == "//nas.local/simdata"

    def test_nfs_source_path(self):
        p = StorageProfile(label="test", protocol="nfs",
                           server="nas.local", share="/exports/sim")
        assert p.source_path == "nas.local:/exports/sim"

    def test_mount_point_uses_label(self):
        p = StorageProfile(label="SIM Data NAS")
        assert p.mount_point == os.path.join(MOUNT_BASE, "SIM_Data_NAS")

    def test_mount_point_sanitises_slashes(self):
        p = StorageProfile(label="a/b/c")
        assert "/" not in os.path.basename(p.mount_point)

    def test_to_dict_excludes_password(self):
        p = StorageProfile(label="x", password="secret")
        d = p.to_dict()
        assert "password" not in d
        assert d["label"] == "x"

    def test_from_dict_round_trip(self):
        p = StorageProfile(label="nas", protocol="nfs",
                           server="10.0.0.1", share="/data",
                           export_fields=["ICCID", "IMSI"])
        d = p.to_dict()
        p2 = StorageProfile.from_dict(d)
        assert p2.label == "nas"
        assert p2.protocol == "nfs"
        assert p2.server == "10.0.0.1"
        assert p2.export_fields == ["ICCID", "IMSI"]

    def test_from_dict_ignores_unknown_keys(self):
        d = {"label": "x", "unknown_field": "ignored"}
        p = StorageProfile.from_dict(d)
        assert p.label == "x"

    def test_default_export_fields(self):
        p = StorageProfile(label="x")
        assert "ICCID" in p.export_fields
        assert "IMSI" in p.export_fields
        assert "Ki" in p.export_fields
        assert "OPc" in p.export_fields


class TestNetworkStorageManager:
    """Unit tests for NetworkStorageManager."""

    def test_load_empty_profiles(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         delete=False) as fh:
            json.dump({}, fh)
            path = fh.name
        try:
            sm = SettingsManager(path=path)
            ns = NetworkStorageManager(sm)
            assert ns.load_profiles() == []
        finally:
            os.unlink(path)

    def test_save_and_load_profiles(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         delete=False) as fh:
            json.dump({}, fh)
            path = fh.name
        try:
            sm = SettingsManager(path=path)
            ns = NetworkStorageManager(sm)
            profiles = [
                StorageProfile(label="NAS1", protocol="smb",
                               server="10.0.0.1", share="sim",
                               username="admin"),
                StorageProfile(label="NFS", protocol="nfs",
                               server="10.0.0.2", share="/exports/sim"),
            ]
            ns.save_profiles(profiles)
            loaded = ns.load_profiles()
            assert len(loaded) == 2
            assert loaded[0].label == "NAS1"
            assert loaded[0].protocol == "smb"
            assert loaded[1].protocol == "nfs"
        finally:
            os.unlink(path)

    def test_get_active_mount_paths_empty(self):
        ns = NetworkStorageManager()
        assert ns.get_active_mount_paths() == []

    def test_is_mounted_false_when_not_mounted(self):
        ns = NetworkStorageManager()
        p = StorageProfile(label="nonexistent")
        assert not ns.is_mounted(p)

    def test_build_mount_cmd_nfs(self):
        ns = NetworkStorageManager()
        p = StorageProfile(label="nfs-test", protocol="nfs",
                           server="10.0.0.1", share="/data/sim")
        cmd = ns._build_mount_cmd(p)
        assert cmd[0] == "/usr/bin/sudo"
        assert "/usr/bin/mount" in cmd
        assert "-t" in cmd
        assert "nfs" in cmd
        assert "10.0.0.1:/data/sim" in cmd

    def test_build_mount_cmd_smb_guest(self):
        ns = NetworkStorageManager()
        p = StorageProfile(label="smb-test", protocol="smb",
                           server="nas.local", share="simdata")
        cmd = ns._build_mount_cmd(p)
        assert "cifs" in cmd
        opts = cmd[cmd.index("-o") + 1]
        assert "guest" in opts

    def test_build_mount_cmd_smb_with_username(self):
        ns = NetworkStorageManager()
        p = StorageProfile(label="smb-auth", protocol="smb",
                           server="nas.local", share="simdata",
                           username="admin", password="pass123")
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "username=admin" in opts


class TestSyncOsMounts:
    """Tests for sync_os_mounts — adopts OS-level mounts into _active_mounts."""

    def test_sync_adopts_mounted_profile(self, monkeypatch):
        """A profile whose mount point is already mounted gets adopted."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="nas-1", server="10.0.0.1", share="data")
        monkeypatch.setattr(ns, "load_profiles", lambda: [p])
        monkeypatch.setattr(os.path, "ismount",
                            lambda mp: mp == p.mount_point)
        assert ns.get_active_mount_paths() == []  # not tracked yet
        ns.sync_os_mounts()
        paths = ns.get_active_mount_paths()
        assert len(paths) == 1
        assert paths[0][0] == "nas-1"

    def test_sync_skips_not_mounted(self, monkeypatch):
        """Profiles that are NOT mounted at OS level are not adopted."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="nas-2", server="10.0.0.2", share="data")
        monkeypatch.setattr(ns, "load_profiles", lambda: [p])
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        ns.sync_os_mounts()
        assert ns.get_active_mount_paths() == []

    def test_sync_skips_already_tracked(self, monkeypatch):
        """Profiles already in _active_mounts are not re-loaded."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="nas-3", server="10.0.0.3", share="data")
        ns._active_mounts["nas-3"] = p  # already tracked
        monkeypatch.setattr(ns, "load_profiles", lambda: [p])
        monkeypatch.setattr(os.path, "ismount",
                            lambda mp: mp == p.mount_point)
        # Should not raise or double-add
        ns.sync_os_mounts()
        assert len(ns.get_active_mount_paths()) == 1

    def test_sync_no_profiles(self, monkeypatch):
        """No crash when no profiles are configured."""
        ns = NetworkStorageManager()
        monkeypatch.setattr(ns, "load_profiles", lambda: [])
        ns.sync_os_mounts()  # should not raise
        assert ns.get_active_mount_paths() == []
