"""Tests for NetworkStorageManager and StorageProfile."""

import json
import os
import sys
import tempfile

import pytest

from managers.network_storage_manager import (
    MOUNT_BASE,
    NetworkStorageManager,
    StorageProfile,
)
from managers.settings_manager import SettingsManager

_MACOS = sys.platform == "darwin"


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
        if _MACOS:
            # macOS uses mount_smbfs with the share URL; no -t cifs, no -o guest
            assert "mount_smbfs" in " ".join(cmd)
            assert "//nas.local/simdata" in cmd
        else:
            # Linux uses mount -t cifs with -o guest
            assert "cifs" in cmd
            opts = cmd[cmd.index("-o") + 1]
            assert "guest" in opts

    def test_build_mount_cmd_smb_with_username(self):
        ns = NetworkStorageManager()
        p = StorageProfile(label="smb-auth", protocol="smb",
                           server="nas.local", share="simdata",
                           username="admin", password="pass123")
        cmd = ns._build_mount_cmd(p)
        if _MACOS:
            # macOS embeds credentials in the URL: //user:pass@server/share
            assert "mount_smbfs" in " ".join(cmd)
            assert "admin" in " ".join(cmd)
        else:
            # Linux passes credentials via -o username=
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


class TestAutoConnectDefault:
    """auto_connect must default to True for new profiles."""

    def test_storage_profile_auto_connect_default_true(self):
        p = StorageProfile(label="x")
        assert p.auto_connect is True

    def test_storage_profile_auto_connect_explicit_false(self):
        p = StorageProfile(label="x", auto_connect=False)
        assert p.auto_connect is False


class TestMacOSSmbTest:
    """On macOS, _test_smb must use temp-mount auth test — no smbclient."""

    def _ns(self):
        return NetworkStorageManager()

    def _profile(self):
        return StorageProfile(
            label="t", protocol="smb", server="192.168.131.188",
            share="SIM", username="simgui", password="pw",
        )

    def test_macos_does_not_call_smbclient(self, monkeypatch):
        """macOS SMB test must use mount_smbfs, not smbclient."""
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)
        monkeypatch.setattr("managers.network_storage_manager._MOUNT_SMB_FS",
                            "/sbin/mount_smbfs")
        import subprocess
        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: "/tmp/simgui-test-fake")
        monkeypatch.setattr("os.rmdir", lambda p: None)

        self._ns()._test_smb(self._profile())

        all_args = " ".join(str(a) for args in captured for a in args)
        assert "smbclient" not in all_args
        assert "mount_smbfs" in all_args

    def test_macos_no_install_or_dependency_message(self, monkeypatch):
        """Success and failure messages must not mention apt, brew, or smbclient."""
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)
        monkeypatch.setattr("managers.network_storage_manager._MOUNT_SMB_FS",
                            "/sbin/mount_smbfs")
        import subprocess
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: "/tmp/simgui-test-fake")
        monkeypatch.setattr("os.rmdir", lambda p: None)

        # success case
        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))
        ok, msg = self._ns()._test_smb(self._profile())
        assert ok
        for bad in ("apt", "brew", "smbclient", "install"):
            assert bad not in msg.lower(), f"Unexpected word '{bad}' in success message: {msg}"

        # failure case
        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="auth failed"))
        ok2, msg2 = self._ns()._test_smb(self._profile())
        assert not ok2
        for bad in ("apt", "brew", "smbclient", "install"):
            assert bad not in msg2.lower(), f"Unexpected word '{bad}' in failure message: {msg2}"

    def test_macos_succeeds_when_mount_succeeds(self, monkeypatch):
        """Returns (True, <msg>) when temp mount_smbfs succeeds."""
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)
        monkeypatch.setattr("managers.network_storage_manager._MOUNT_SMB_FS",
                            "/sbin/mount_smbfs")
        import subprocess
        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: "/tmp/simgui-test-fake")
        monkeypatch.setattr("os.rmdir", lambda p: None)

        ok, msg = self._ns()._test_smb(self._profile())
        assert ok
        assert "successful" in msg.lower() or "authentication" in msg.lower()

    def test_linux_missing_smbclient_shows_apt_message(self, monkeypatch):
        """Linux path unchanged: FileNotFoundError → apt install smbclient."""
        monkeypatch.setattr("managers.network_storage_manager._MACOS", False)
        import subprocess
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("smbclient")),
        )
        ok, msg = self._ns()._test_smb(self._profile())
        assert not ok
        assert "apt install smbclient" in msg


class TestMountFileExists:
    """mount() must probe accessibility when OS reports 'File exists'."""

    def _profile(self):
        return StorageProfile(label="NAS SIM", server="nas.local", share="SIM")

    def _make_run(self, stderr):
        """Return a subprocess.run replacement that fails with given stderr."""
        import subprocess

        class _Result:
            returncode = 1
            stdout = ""

        r = _Result()
        r.stderr = stderr

        def _run(*args, **kwargs):
            return r

        return _run

    def test_file_exists_accessible_returns_success(self, monkeypatch):
        """'File exists' + accessible share → returns True, profile tracked."""
        import subprocess

        ns = NetworkStorageManager()
        p = self._profile()
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        monkeypatch.setattr(subprocess, "run",
                            self._make_run("mount_smbfs: mount error: //nas.local/SIM: File exists"))
        # _check_path_accessible is the path-based probe now used in this branch
        monkeypatch.setattr(ns, "_check_path_accessible", lambda path, timeout=5: True)

        ok, msg = ns.mount(p)

        assert ok
        assert p.label in ns._active_mounts
        assert "adopted" in msg.lower() or "existing" in msg.lower()

    def test_file_exists_inaccessible_returns_failure(self, monkeypatch):
        """'File exists' + inaccessible share → returns False, profile not tracked."""
        import subprocess

        ns = NetworkStorageManager()
        p = self._profile()
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        monkeypatch.setattr(subprocess, "run",
                            self._make_run("mount_smbfs: mount error: //nas.local/SIM: File exists"))
        monkeypatch.setattr(ns, "verify_mount_accessible", lambda prof: False)

        ok, msg = ns.mount(p)

        assert not ok
        assert p.label not in ns._active_mounts
        assert "stale" in msg.lower() or "conflicting" in msg.lower()

    def test_file_exists_inaccessible_message_contains_original_error(self, monkeypatch):
        """Failure message must include the original OS error for diagnostics."""
        import subprocess

        ns = NetworkStorageManager()
        p = self._profile()
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        monkeypatch.setattr(subprocess, "run",
                            self._make_run("mount_smbfs: mount error: //nas.local/SIM: File exists"))
        monkeypatch.setattr(ns, "verify_mount_accessible", lambda prof: False)

        _, msg = ns.mount(p)

        assert "File exists" in msg

    def test_file_exists_inaccessible_does_not_call_umount(self, monkeypatch):
        """No automatic unmount is attempted — side effects on user mounts must be avoided."""
        import subprocess

        calls = []
        original_run = subprocess.run

        def _tracking_run(cmd, *args, **kwargs):
            calls.append(cmd)
            r = type("R", (), {"returncode": 1, "stdout": "", "stderr": "File exists"})()
            return r

        ns = NetworkStorageManager()
        p = self._profile()
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        monkeypatch.setattr(subprocess, "run", _tracking_run)
        monkeypatch.setattr(ns, "verify_mount_accessible", lambda prof: False)

        ns.mount(p)

        umount_calls = [c for c in calls if any("umount" in str(part) for part in c)]
        assert umount_calls == [], f"Unexpected umount call(s): {umount_calls}"

    def test_already_mounted_string_also_adopts(self, monkeypatch):
        """'already mounted' error string is also handled (not just 'File exists')."""
        import subprocess

        ns = NetworkStorageManager()
        p = self._profile()
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        monkeypatch.setattr(subprocess, "run",
                            self._make_run("mount: //nas.local/SIM already mounted on /tmp/simgui-mounts/NAS_SIM"))
        monkeypatch.setattr(ns, "_check_path_accessible", lambda path, timeout=5: True)

        ok, _ = ns.mount(p)

        assert ok
        assert p.label in ns._active_mounts

class _FakeSocket:
    """Minimal context-manager socket stub."""
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def close(self):
        pass
