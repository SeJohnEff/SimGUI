"""Comprehensive tests for managers/network_storage_manager.py.

Covers:
- StorageProfile dataclass (to_dict, from_dict, mount_point, source_path)
- _build_mount_cmd for SMB (guest, creds file, username/password/domain)
- _build_mount_cmd for NFS (default + custom options)
- _test_smb and _test_nfs (mocked subprocess)
- mount / unmount (mocked subprocess, os.path.ismount)
- load_profiles / save_profiles (real SettingsManager with temp JSON)
- _write_password / _read_password (real temp directory)
- find_duplicate_iccids (real temp CSV files)
- unmount_all
- get_active_mount_paths
"""

import csv
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.network_storage_manager import (
    MOUNT_BASE,
    NetworkStorageManager,
    StorageProfile,
)
from managers.settings_manager import SettingsManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(tmp_path):
    """Create a SettingsManager backed by a temp JSON file."""
    p = tmp_path / "settings.json"
    p.write_text("{}")
    return SettingsManager(path=str(p))


def _make_smb_profile(**kwargs):
    defaults = dict(label="TestSMB", protocol="smb",
                    server="nas.local", share="simdata",
                    username="user1", password="pass1")
    defaults.update(kwargs)
    return StorageProfile(**defaults)


def _make_nfs_profile(**kwargs):
    defaults = dict(label="TestNFS", protocol="nfs",
                    server="10.0.0.1", share="/exports/sim")
    defaults.update(kwargs)
    return StorageProfile(**defaults)


# ---------------------------------------------------------------------------
# StorageProfile — dataclass
# ---------------------------------------------------------------------------

class TestStorageProfileDataclass:
    """Detailed tests for StorageProfile properties and serialisation."""

    def test_to_dict_excludes_password(self):
        """to_dict() must never include the password field."""
        p = StorageProfile(label="x", password="s3cr3t")
        d = p.to_dict()
        assert "password" not in d

    def test_to_dict_includes_all_other_fields(self):
        """to_dict() includes label, protocol, server, share, etc."""
        p = StorageProfile(label="y", protocol="nfs", server="10.0.0.1",
                           share="/data", username="u", domain="WORKGROUP",
                           export_subdir="out", export_fields=["ICCID"])
        d = p.to_dict()
        assert d["label"] == "y"
        assert d["protocol"] == "nfs"
        assert d["server"] == "10.0.0.1"
        assert d["share"] == "/data"
        assert d["username"] == "u"
        assert d["domain"] == "WORKGROUP"
        assert d["export_subdir"] == "out"
        assert d["export_fields"] == ["ICCID"]

    def test_from_dict_roundtrip_smb(self):
        """from_dict(to_dict()) must reproduce all non-password fields."""
        original = StorageProfile(label="SMB1", protocol="smb",
                                   server="srv", share="share1",
                                   username="admin", domain="CORP",
                                   export_fields=["ICCID", "Ki"])
        d = original.to_dict()
        restored = StorageProfile.from_dict(d)
        assert restored.label == "SMB1"
        assert restored.protocol == "smb"
        assert restored.server == "srv"
        assert restored.share == "share1"
        assert restored.username == "admin"
        assert restored.domain == "CORP"
        assert restored.export_fields == ["ICCID", "Ki"]

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict() silently ignores keys that aren't dataclass fields."""
        d = {"label": "z", "future_field": "ignore_me", "protocol": "nfs"}
        p = StorageProfile.from_dict(d)
        assert p.label == "z"
        assert p.protocol == "nfs"

    def test_from_dict_minimal(self):
        """from_dict() works with only label provided."""
        p = StorageProfile.from_dict({"label": "minimal"})
        assert p.label == "minimal"
        assert p.protocol == "smb"  # default
        assert p.server == ""

    def test_mount_point_spaces_replaced(self):
        """Spaces in label are replaced with underscores in mount_point."""
        p = StorageProfile(label="SIM Data NAS")
        mp = p.mount_point
        assert " " not in mp
        assert "SIM_Data_NAS" in mp

    def test_mount_point_slashes_replaced(self):
        """Slashes in label are replaced with underscores."""
        p = StorageProfile(label="a/b/c")
        mp = p.mount_point
        basename = os.path.basename(mp)
        assert "/" not in basename
        assert "a_b_c" in basename

    def test_mount_point_under_mount_base(self):
        """mount_point lives under MOUNT_BASE."""
        p = StorageProfile(label="myshare")
        assert p.mount_point.startswith(MOUNT_BASE)

    def test_source_path_smb_no_leading_slash(self):
        """SMB source path is //server/share (no leading slash in share)."""
        p = StorageProfile(label="x", protocol="smb",
                           server="nas", share="simdata")
        assert p.source_path == "//nas/simdata"

    def test_source_path_smb_strips_leading_slash_from_share(self):
        """SMB source path strips leading slash from share."""
        p = StorageProfile(label="x", protocol="smb",
                           server="nas", share="/simdata")
        assert p.source_path == "//nas/simdata"

    def test_source_path_nfs_colon_notation(self):
        """NFS source path uses server:/path notation."""
        p = StorageProfile(label="x", protocol="nfs",
                           server="10.0.0.1", share="/exports/sim")
        assert p.source_path == "10.0.0.1:/exports/sim"

    def test_default_export_fields(self):
        """Default export_fields includes the four standard fields."""
        p = StorageProfile(label="x")
        assert "ICCID" in p.export_fields
        assert "IMSI" in p.export_fields
        assert "Ki" in p.export_fields
        assert "OPc" in p.export_fields

    def test_export_fields_are_independent_per_instance(self):
        """Each StorageProfile instance has its own export_fields list."""
        p1 = StorageProfile(label="a")
        p2 = StorageProfile(label="b")
        p1.export_fields.append("ADM1")
        assert "ADM1" not in p2.export_fields


# ---------------------------------------------------------------------------
# _build_mount_cmd
# ---------------------------------------------------------------------------

class TestBuildMountCmd:
    """Tests for the mount command builder."""

    def test_nfs_uses_nfs_type(self):
        """NFS command uses -t nfs."""
        ns = NetworkStorageManager()
        p = _make_nfs_profile()
        cmd = ns._build_mount_cmd(p)
        assert "nfs" in cmd
        assert "-t" in cmd
        idx = cmd.index("-t")
        assert cmd[idx + 1] == "nfs"

    def test_nfs_includes_source_and_mountpoint(self):
        """NFS command includes the source path and mount point."""
        ns = NetworkStorageManager()
        p = _make_nfs_profile(server="10.0.0.1", share="/data/sim",
                              label="mynfs")
        cmd = ns._build_mount_cmd(p)
        assert "10.0.0.1:/data/sim" in cmd
        assert p.mount_point in cmd

    def test_nfs_default_options(self):
        """NFS command uses default mount options when none specified."""
        ns = NetworkStorageManager()
        p = _make_nfs_profile(mount_options="")
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "soft" in opts
        assert "timeo" in opts

    def test_nfs_custom_options(self):
        """NFS command uses custom options when provided."""
        ns = NetworkStorageManager()
        p = _make_nfs_profile(mount_options="hard,intr")
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "hard" in opts
        assert "intr" in opts

    def test_smb_uses_cifs_type(self):
        """SMB command uses -t cifs."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        cmd = ns._build_mount_cmd(p)
        assert "cifs" in cmd

    def test_smb_guest_when_no_username(self):
        """SMB guest mount when no username provided."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="guest", protocol="smb",
                           server="nas", share="public")
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "guest" in opts

    def test_smb_username_in_opts_when_no_cred_file(self):
        """SMB with username uses username= in opts when no cred file exists."""
        ns = NetworkStorageManager()
        p = _make_smb_profile(username="user1", password="pass1")
        # Ensure cred file does not exist
        cred_path = ns._cred_file_path(p.label)
        if os.path.exists(cred_path):
            os.unlink(cred_path)
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "username=user1" in opts
        assert "password=pass1" in opts

    def test_smb_domain_in_opts(self):
        """SMB with domain includes domain= in opts."""
        ns = NetworkStorageManager()
        p = _make_smb_profile(domain="CORP")
        cred_path = ns._cred_file_path(p.label)
        if os.path.exists(cred_path):
            os.unlink(cred_path)
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "domain=CORP" in opts

    def test_smb_cred_file_used_when_present(self, tmp_path):
        """SMB uses credentials= option when cred file exists."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path)
        p = _make_smb_profile(label="credtest")
        # Write a fake cred file
        cred_path = ns._cred_file_path("credtest")
        with open(cred_path, "w") as fh:
            fh.write("username=user1\npassword=pass1\n")
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "credentials=" in opts

    def test_smb_extra_mount_options_appended(self):
        """Extra mount_options are appended to SMB opts."""
        ns = NetworkStorageManager()
        p = _make_smb_profile(username="", mount_options="vers=3.0")
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "vers=3.0" in opts

    def test_smb_uid_gid_in_opts(self):
        """SMB mount options include uid and gid."""
        ns = NetworkStorageManager()
        p = _make_smb_profile(username="")
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "uid=" in opts
        assert "gid=" in opts

    def test_smb_file_dir_mode_in_opts(self):
        """SMB mount options include file_mode and dir_mode."""
        ns = NetworkStorageManager()
        p = _make_smb_profile(username="")
        cmd = ns._build_mount_cmd(p)
        opts = cmd[cmd.index("-o") + 1]
        assert "file_mode=" in opts
        assert "dir_mode=" in opts

    def test_sudo_first_argument(self):
        """All mount commands start with absolute-path sudo."""
        ns = NetworkStorageManager()
        for p in [_make_smb_profile(), _make_nfs_profile()]:
            cmd = ns._build_mount_cmd(p)
            assert cmd[0] == "/usr/bin/sudo"


# ---------------------------------------------------------------------------
# _test_smb and _test_nfs
# ---------------------------------------------------------------------------

class TestConnectionTest:
    """Tests for _test_smb and _test_nfs (mocked subprocess)."""

    def test_smb_success_no_username(self):
        """_test_smb succeeds when smbclient returns 0 (no auth)."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="x", protocol="smb",
                           server="nas", share="pub")
        mock_result = MagicMock(returncode=0, stdout="share listing")
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = ns._test_smb(p)
        assert ok is True
        assert "successful" in msg.lower()

    def test_smb_success_with_username(self):
        """_test_smb succeeds with username/password."""
        ns = NetworkStorageManager()
        p = _make_smb_profile(username="admin", password="pass",
                              domain="CORP")
        mock_result = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = ns._test_smb(p)
        assert ok is True

    def test_smb_failure_nonzero_returncode(self):
        """_test_smb returns failure when smbclient exits non-zero."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        mock_result = MagicMock(returncode=1, stderr="NT_STATUS_LOGON_FAILURE",
                                stdout="")
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = ns._test_smb(p)
        assert ok is False
        assert "NT_STATUS" in msg

    def test_smb_smbclient_not_found(self):
        """_test_smb returns error when smbclient binary is missing."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            ok, msg = ns._test_smb(p)
        assert ok is False
        assert "smbclient" in msg.lower()

    def test_smb_timeout(self):
        """_test_smb returns timeout error on subprocess.TimeoutExpired."""
        import subprocess
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="smb", timeout=10)):
            ok, msg = ns._test_smb(p)
        assert ok is False
        assert "timed out" in msg.lower()

    def test_nfs_success_export_found(self):
        """_test_nfs succeeds when export is listed."""
        ns = NetworkStorageManager()
        p = _make_nfs_profile(share="/exports/sim")
        mock_result = MagicMock(returncode=0,
                                stdout="Export list for nas:\n/exports/sim\n")
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = ns._test_nfs(p)
        assert ok is True
        assert "accessible" in msg.lower()

    def test_nfs_export_not_listed(self):
        """_test_nfs fails when export is not in showmount output."""
        ns = NetworkStorageManager()
        p = _make_nfs_profile(share="/exports/other")
        mock_result = MagicMock(returncode=0,
                                stdout="/exports/sim\n")
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = ns._test_nfs(p)
        assert ok is False
        assert "/exports/other" in msg

    def test_nfs_showmount_not_found(self):
        """_test_nfs returns error when showmount binary is missing."""
        ns = NetworkStorageManager()
        p = _make_nfs_profile()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            ok, msg = ns._test_nfs(p)
        assert ok is False
        assert "showmount" in msg.lower()

    def test_nfs_timeout(self):
        """_test_nfs returns timeout error on subprocess.TimeoutExpired."""
        import subprocess
        ns = NetworkStorageManager()
        p = _make_nfs_profile()
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="showmount", timeout=10)):
            ok, msg = ns._test_nfs(p)
        assert ok is False
        assert "timed out" in msg.lower()

    def test_nfs_returncode_nonzero(self):
        """_test_nfs returns failure when showmount exits non-zero."""
        ns = NetworkStorageManager()
        p = _make_nfs_profile()
        mock_result = MagicMock(returncode=1, stderr="clnt_create error",
                                stdout="")
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = ns._test_nfs(p)
        assert ok is False

    def test_test_connection_dispatches_smb(self):
        """test_connection() calls _test_smb for SMB profiles."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "_test_smb", return_value=(True, "ok")) as m:
            ns.test_connection(p)
            m.assert_called_once_with(p)

    def test_test_connection_dispatches_nfs(self):
        """test_connection() calls _test_nfs for NFS profiles."""
        ns = NetworkStorageManager()
        p = _make_nfs_profile()
        with patch.object(ns, "_test_nfs", return_value=(True, "ok")) as m:
            ns.test_connection(p)
            m.assert_called_once_with(p)


# ---------------------------------------------------------------------------
# mount / unmount
# ---------------------------------------------------------------------------

class TestMountUnmount:
    """Tests for mount() and unmount() with mocked subprocess."""

    def test_mount_success(self, tmp_path):
        """mount() returns success when subprocess exits 0."""
        ns = NetworkStorageManager()
        p = _make_smb_profile(label="mnt_test")
        str(tmp_path / "mnt_test")
        with patch.object(ns, "is_mounted", return_value=False), \
             patch("os.makedirs"), \
             patch.object(ns, "_build_mount_cmd",
                          return_value=["/usr/bin/sudo", "/usr/bin/mount"]), \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stderr="")):
            with patch.object(ns, "is_mounted", side_effect=[False, True]):
                # First call (already_mounted check) → False, mount
                mock_result = MagicMock(returncode=0, stderr="")
                with patch("subprocess.run", return_value=mock_result):
                    with patch("os.makedirs"):
                        ok, msg = ns.mount(p)
        assert ok is True

    def test_mount_already_mounted(self):
        """mount() returns success immediately if already mounted."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "is_mounted", return_value=True):
            ok, msg = ns.mount(p)
        assert ok is True
        assert "Already mounted" in msg

    def test_mount_already_mounted_adds_to_active_mounts(self):
        """mount() must track the profile even when already mounted.

        Bug fix v0.5.3: previously 'Already mounted' returned early
        without adding to _active_mounts, causing get_active_mount_paths
        to return empty and the ICCID index to never scan the share.
        """
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        assert ns._active_mounts == {}
        with patch.object(ns, "is_mounted", return_value=True):
            ok, msg = ns.mount(p)
        assert ok is True
        assert p.label in ns._active_mounts

    def test_get_active_mount_paths_after_already_mounted(self):
        """get_active_mount_paths must include 'Already mounted' shares."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "is_mounted", return_value=True):
            ns.mount(p)
            paths = ns.get_active_mount_paths()
        assert len(paths) == 1
        assert paths[0][0] == p.label

    def test_mount_subprocess_failure(self):
        """mount() returns failure when subprocess exits non-zero."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "is_mounted", return_value=False), \
             patch("os.makedirs"), \
             patch.object(ns, "_build_mount_cmd", return_value=["/usr/bin/sudo", "/usr/bin/mount"]), \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=1,
                                          stderr="Permission denied",
                                          stdout="")):
            ok, msg = ns.mount(p)
        assert ok is False
        assert "Mount failed" in msg

    def test_mount_command_not_found(self):
        """mount() returns error when sudo/mount binary is missing."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "is_mounted", return_value=False), \
             patch("os.makedirs"), \
             patch.object(ns, "_build_mount_cmd", return_value=["/usr/bin/sudo"]), \
             patch("subprocess.run", side_effect=FileNotFoundError("no sudo")):
            ok, msg = ns.mount(p)
        assert ok is False
        assert "not found" in msg.lower()

    def test_mount_timeout(self):
        """mount() returns timeout error on TimeoutExpired."""
        import subprocess
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "is_mounted", return_value=False), \
             patch("os.makedirs"), \
             patch.object(ns, "_build_mount_cmd", return_value=["/usr/bin/sudo"]), \
             patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("mount", 30)):
            ok, msg = ns.mount(p)
        assert ok is False
        assert "timed out" in msg.lower()

    def test_unmount_not_mounted(self):
        """unmount() returns True/not-mounted when share is not mounted."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "is_mounted", return_value=False):
            ok, msg = ns.unmount(p)
        assert ok is True
        assert "Not mounted" in msg

    def test_unmount_success(self):
        """unmount() succeeds when umount exits 0."""
        ns = NetworkStorageManager()
        p = _make_smb_profile(label="to_unmount")
        ns._active_mounts["to_unmount"] = p
        with patch.object(ns, "is_mounted", return_value=True), \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stderr="")), \
             patch("os.rmdir"):
            ok, msg = ns.unmount(p)
        assert ok is True
        assert "Unmounted" in msg
        assert "to_unmount" not in ns._active_mounts

    def test_unmount_failure(self):
        """unmount() returns failure when umount exits non-zero."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "is_mounted", return_value=True), \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=1,
                                          stderr="device busy",
                                          stdout="")):
            ok, msg = ns.unmount(p)
        assert ok is False
        assert "Unmount failed" in msg

    def test_unmount_timeout(self):
        """unmount() returns timeout error on TimeoutExpired."""
        import subprocess
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "is_mounted", return_value=True), \
             patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("umount", 15)):
            ok, msg = ns.unmount(p)
        assert ok is False
        assert "timed out" in msg.lower()

    def test_unmount_all(self):
        """unmount_all() calls unmount for every active mount."""
        ns = NetworkStorageManager()
        p1 = _make_smb_profile(label="m1")
        p2 = _make_nfs_profile(label="m2")
        ns._active_mounts = {"m1": p1, "m2": p2}
        results = []
        with patch.object(ns, "unmount",
                          side_effect=lambda p: results.append(p.label) or (True, "ok")):
            ns.unmount_all()
        assert len(results) == 2

    def test_is_mounted_uses_os_path_ismount(self):
        """is_mounted() delegates to os.path.ismount."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch("os.path.ismount", return_value=True):
            assert ns.is_mounted(p) is True
        with patch("os.path.ismount", return_value=False):
            assert ns.is_mounted(p) is False

    def test_is_mounted_oserror_returns_false(self):
        """is_mounted() returns False on OSError."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch("os.path.ismount", side_effect=OSError("permission")):
            assert ns.is_mounted(p) is False

    def test_get_active_mount_paths_filters_unmounted(self):
        """get_active_mount_paths() only lists actually-mounted shares."""
        ns = NetworkStorageManager()
        p1 = _make_smb_profile(label="active")
        p2 = _make_nfs_profile(label="stale")
        ns._active_mounts = {"active": p1, "stale": p2}

        def is_mounted(profile):
            return profile.label == "active"

        with patch.object(ns, "is_mounted", side_effect=is_mounted):
            paths = ns.get_active_mount_paths()
        labels = [lbl for lbl, _ in paths]
        assert "active" in labels
        assert "stale" not in labels


# ---------------------------------------------------------------------------
# reconnect_saved
# ---------------------------------------------------------------------------

class TestReconnectSaved:
    """Tests for auto-reconnection at startup."""

    def test_reconnect_already_mounted_populates_active_mounts(self):
        """Shares that are already mounted at startup must still be
        tracked in _active_mounts so the ICCID index can scan them.

        Bug fix v0.5.3: previously reconnect_saved checked is_mounted
        before calling mount(), skipping the _active_mounts update.
        """
        p = _make_smb_profile()
        p.auto_connect = True
        ns = NetworkStorageManager()
        with patch.object(ns, "load_profiles", return_value=[p]), \
             patch.object(ns, "is_mounted", return_value=True):
            results = ns.reconnect_saved()
        assert len(results) == 1
        label, ok, msg = results[0]
        assert ok is True
        assert p.label in ns._active_mounts

    def test_reconnect_not_mounted_triggers_mount(self):
        """Shares not currently mounted should be mounted."""
        p = _make_smb_profile()
        p.auto_connect = True
        ns = NetworkStorageManager()
        # is_mounted: first False (not yet mounted), succeeds on mount
        with patch.object(ns, "load_profiles", return_value=[p]), \
             patch.object(ns, "is_mounted", return_value=False), \
             patch("os.makedirs"), \
             patch.object(ns, "_build_mount_cmd", return_value=["mount"]), \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=0)):
            results = ns.reconnect_saved()
        assert len(results) == 1
        _, ok, _ = results[0]
        assert ok is True
        assert p.label in ns._active_mounts

    def test_reconnect_skips_non_auto_connect(self):
        """Profiles without auto_connect=True are skipped."""
        p = _make_smb_profile()
        p.auto_connect = False
        ns = NetworkStorageManager()
        with patch.object(ns, "load_profiles", return_value=[p]):
            results = ns.reconnect_saved()
        assert results == []
        assert ns._active_mounts == {}


# ---------------------------------------------------------------------------
# load_profiles / save_profiles
# ---------------------------------------------------------------------------

class TestProfilePersistence:
    """Tests for profile loading and saving via SettingsManager."""

    def test_load_profiles_no_settings(self):
        """load_profiles() returns [] when no settings manager provided."""
        ns = NetworkStorageManager(settings_manager=None)
        assert ns.load_profiles() == []

    def test_save_profiles_no_settings(self):
        """save_profiles() is a no-op when no settings manager provided."""
        ns = NetworkStorageManager(settings_manager=None)
        ns.save_profiles([_make_smb_profile()])  # must not raise

    def test_save_and_load_roundtrip(self, tmp_path):
        """Profiles saved to settings can be reloaded."""
        sm = _make_settings(tmp_path)
        ns = NetworkStorageManager(sm)
        profiles = [
            _make_smb_profile(label="SMB1"),
            _make_nfs_profile(label="NFS1"),
        ]
        ns.save_profiles(profiles)
        loaded = ns.load_profiles()
        assert len(loaded) == 2
        labels = [p.label for p in loaded]
        assert "SMB1" in labels
        assert "NFS1" in labels

    def test_save_excludes_password_from_settings(self, tmp_path):
        """Password is never stored in the settings JSON."""
        sm = _make_settings(tmp_path)
        ns = NetworkStorageManager(sm)
        p = _make_smb_profile(password="secret123")
        ns.save_profiles([p])

        # Read the raw JSON and verify password is absent
        raw = sm.get("network_profiles", [])
        assert len(raw) == 1
        assert "password" not in raw[0]

    def test_save_writes_password_to_cred_file(self, tmp_path):
        """save_profiles() writes the password to a credential file."""
        sm = _make_settings(tmp_path)
        ns = NetworkStorageManager(sm)
        ns._cred_dir = str(tmp_path / "creds")
        p = _make_smb_profile(label="mycred", password="secret")
        ns.save_profiles([p])
        cred_path = ns._cred_file_path("mycred")
        assert os.path.isfile(cred_path)
        content = open(cred_path).read()
        assert "secret" in content

    def test_save_empty_password_no_cred_file(self, tmp_path):
        """save_profiles() does not write a cred file when password is empty."""
        sm = _make_settings(tmp_path)
        ns = NetworkStorageManager(sm)
        ns._cred_dir = str(tmp_path / "creds")
        p = _make_smb_profile(label="nocred", password="")
        ns.save_profiles([p])
        cred_path = ns._cred_file_path("nocred")
        assert not os.path.isfile(cred_path)


# ---------------------------------------------------------------------------
# _write_password / _read_password
# ---------------------------------------------------------------------------

class TestCredentialFiles:
    """Tests for _write_password and _read_password helpers."""

    def test_write_and_read_password(self, tmp_path):
        """A written password can be read back correctly."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path)
        ns._write_password("mylabel", "user1", "secretpw")
        pw = ns._read_password("mylabel")
        assert pw == "secretpw"

    def test_write_includes_username(self, tmp_path):
        """Credential file contains username= line."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path)
        ns._write_password("test", "admin", "pw123")
        content = open(ns._cred_file_path("test")).read()
        assert "username=admin" in content

    def test_write_includes_domain(self, tmp_path):
        """Credential file contains domain= line when domain is provided."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path)
        ns._write_password("test", "user", "pw", domain="CORP")
        content = open(ns._cred_file_path("test")).read()
        assert "domain=CORP" in content

    def test_write_no_domain_omits_domain_line(self, tmp_path):
        """Credential file omits domain= when domain is empty."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path)
        ns._write_password("test", "user", "pw", domain="")
        content = open(ns._cred_file_path("test")).read()
        assert "domain=" not in content

    def test_read_password_missing_file(self, tmp_path):
        """_read_password() returns '' when cred file does not exist."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path)
        pw = ns._read_password("nonexistent")
        assert pw == ""

    def test_write_creates_directory(self, tmp_path):
        """_write_password() creates the credential directory if needed."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path / "new_cred_dir")
        ns._write_password("label", "user", "pw")
        assert os.path.isdir(ns._cred_dir)

    def test_file_permissions_600(self, tmp_path):
        """Credential file is created with 0600 permissions."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path)
        ns._write_password("label", "user", "pw")
        path = ns._cred_file_path("label")
        mode = os.stat(path).st_mode & 0o777
        assert mode == 0o600

    def test_cred_file_path_sanitises_label(self, tmp_path):
        """_cred_file_path replaces spaces and slashes in the label."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path)
        path = ns._cred_file_path("my label/x")
        assert " " not in os.path.basename(path)
        assert "/" not in os.path.basename(path)

    def test_read_password_from_file_with_multiple_lines(self, tmp_path):
        """_read_password() picks the password= line from multi-line file."""
        ns = NetworkStorageManager()
        ns._cred_dir = str(tmp_path)
        path = ns._cred_file_path("multi")
        with open(path, "w") as fh:
            fh.write("username=user\npassword=mypassword\ndomain=CORP\n")
        pw = ns._read_password("multi")
        assert pw == "mypassword"

    def test_load_profiles_reads_password_from_cred_file(self, tmp_path):
        """load_profiles() injects passwords from cred files into profiles."""
        sm = _make_settings(tmp_path)
        ns = NetworkStorageManager(sm)
        ns._cred_dir = str(tmp_path / "creds")
        os.makedirs(ns._cred_dir)

        # Manually save a profile (without password in JSON)
        p = _make_smb_profile(label="withpw", password="")
        sm.set("network_profiles", [p.to_dict()])
        sm.save()

        # Write a cred file as if it was previously saved
        ns._write_password("withpw", "user1", "loadedpw")

        loaded = ns.load_profiles()
        assert len(loaded) == 1
        assert loaded[0].password == "loadedpw"


# ---------------------------------------------------------------------------
# find_duplicate_iccids
# ---------------------------------------------------------------------------

class TestFindDuplicateIccids:
    """Tests for find_duplicate_iccids() with real temp CSV files."""

    def _write_csv(self, path, iccids):
        """Helper: write a CSV with ICCID column."""
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["ICCID", "IMSI"])
            writer.writeheader()
            for iccid in iccids:
                writer.writerow({"ICCID": iccid, "IMSI": f"imsi_{iccid}"})

    def test_not_mounted_returns_empty(self):
        """find_duplicate_iccids() returns [] when share is not mounted."""
        ns = NetworkStorageManager()
        p = _make_smb_profile()
        with patch.object(ns, "is_mounted", return_value=False):
            result = ns.find_duplicate_iccids(p, ["123", "456"])
        assert result == []

    def test_no_csv_files_returns_empty(self, tmp_path):
        """find_duplicate_iccids() returns [] when artifact dir has no CSVs."""
        ns = NetworkStorageManager()
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()

        class PatchedProfile(StorageProfile):
            @property
            def mount_point(self):
                return str(tmp_path)

        pp = PatchedProfile(label="dup_test", export_subdir="artifacts")
        with patch.object(ns, "is_mounted", return_value=True):
            result = ns.find_duplicate_iccids(pp, ["123"])
        assert result == []

    def test_finds_duplicates(self, tmp_path):
        """find_duplicate_iccids() correctly finds matching ICCIDs."""
        ns = NetworkStorageManager()
        artifact_dir = tmp_path / "out"
        artifact_dir.mkdir()
        csv_path = artifact_dir / "batch1.csv"
        self._write_csv(str(csv_path), ["111", "222", "333"])

        class PatchedProfile(StorageProfile):
            @property
            def mount_point(self):
                return str(tmp_path)

        pp = PatchedProfile(label="x", export_subdir="out")
        with patch.object(ns, "is_mounted", return_value=True):
            result = ns.find_duplicate_iccids(pp, ["111", "444"])
        assert "111" in result
        assert "444" not in result

    def test_no_duplicates_returns_empty(self, tmp_path):
        """find_duplicate_iccids() returns [] when no ICCIDs overlap."""
        ns = NetworkStorageManager()
        artifact_dir = tmp_path / "out"
        artifact_dir.mkdir()
        csv_path = artifact_dir / "batch.csv"
        self._write_csv(str(csv_path), ["111", "222"])

        class PatchedProfile(StorageProfile):
            @property
            def mount_point(self):
                return str(tmp_path)

        pp = PatchedProfile(label="y", export_subdir="out")
        with patch.object(ns, "is_mounted", return_value=True):
            result = ns.find_duplicate_iccids(pp, ["999", "888"])
        assert result == []

    def test_multiple_csv_files(self, tmp_path):
        """find_duplicate_iccids() scans all CSV files in the directory."""
        ns = NetworkStorageManager()
        artifact_dir = tmp_path / "out"
        artifact_dir.mkdir()
        self._write_csv(str(artifact_dir / "a.csv"), ["111"])
        self._write_csv(str(artifact_dir / "b.csv"), ["222"])
        self._write_csv(str(artifact_dir / "c.csv"), ["333"])

        class PatchedProfile(StorageProfile):
            @property
            def mount_point(self):
                return str(tmp_path)

        pp = PatchedProfile(label="z", export_subdir="out")
        with patch.object(ns, "is_mounted", return_value=True):
            result = ns.find_duplicate_iccids(pp, ["111", "222", "444"])
        assert sorted(result) == ["111", "222"]

    def test_skips_non_csv_files(self, tmp_path):
        """find_duplicate_iccids() ignores non-CSV files."""
        ns = NetworkStorageManager()
        artifact_dir = tmp_path / "out"
        artifact_dir.mkdir()
        # Write a .txt file with ICCID-like content
        (artifact_dir / "notes.txt").write_text("111\n222\n")
        self._write_csv(str(artifact_dir / "real.csv"), ["333"])

        class PatchedProfile(StorageProfile):
            @property
            def mount_point(self):
                return str(tmp_path)

        pp = PatchedProfile(label="w", export_subdir="out")
        with patch.object(ns, "is_mounted", return_value=True):
            result = ns.find_duplicate_iccids(pp, ["111", "333"])
        assert "333" in result
        assert "111" not in result  # only in .txt, not CSV

    def test_artifact_dir_missing_returns_empty(self, tmp_path):
        """find_duplicate_iccids() returns [] when artifact dir doesn't exist."""
        ns = NetworkStorageManager()

        class PatchedProfile(StorageProfile):
            @property
            def mount_point(self):
                return str(tmp_path)

        pp = PatchedProfile(label="q", export_subdir="nonexistent_dir")
        with patch.object(ns, "is_mounted", return_value=True):
            result = ns.find_duplicate_iccids(pp, ["111"])
        assert result == []

    def test_result_is_sorted(self, tmp_path):
        """find_duplicate_iccids() returns results in sorted order."""
        ns = NetworkStorageManager()
        artifact_dir = tmp_path / "out"
        artifact_dir.mkdir()
        self._write_csv(str(artifact_dir / "batch.csv"), ["333", "111", "222"])

        class PatchedProfile(StorageProfile):
            @property
            def mount_point(self):
                return str(tmp_path)

        pp = PatchedProfile(label="sorted", export_subdir="out")
        with patch.object(ns, "is_mounted", return_value=True):
            result = ns.find_duplicate_iccids(pp, ["333", "111", "222"])
        assert result == sorted(result)
