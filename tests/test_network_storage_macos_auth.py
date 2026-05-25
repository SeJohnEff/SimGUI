"""Targeted tests for macOS SMB authentication fixes.

Covers:
1. macOS Test Connection does not use socket-only success.
2. macOS Test Connection includes credentials/auth path (temp mount).
3. macOS Connect & Save includes password non-interactively (URL encoding).
4. Blank password fails in GUI before mount command runs.
5. Linux smbclient path unchanged.
"""

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from managers.network_storage_manager import NetworkStorageManager, StorageProfile


def _smb_profile(**kwargs):
    defaults = dict(label="NAS", protocol="smb", server="nas.local", share="simdata",
                    username="admin", password="secret")
    defaults.update(kwargs)
    return StorageProfile(**defaults)


# ---------------------------------------------------------------------------
# 1. macOS Test Connection does not use socket-only success
# ---------------------------------------------------------------------------

class TestMacosTestConnectionNotSocketOnly:
    """_test_smb_macos must NOT return success based purely on TCP reachability."""

    def test_wrong_credentials_returns_failure_even_if_server_reachable(self, monkeypatch):
        """When mount_smbfs fails (wrong creds), test connection returns False."""
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)
        monkeypatch.setattr("managers.network_storage_manager._MOUNT_SMB_FS",
                            "/sbin/mount_smbfs")
        ns = NetworkStorageManager()
        p = _smb_profile(password="wrongpass")

        mock_result = MagicMock(returncode=1, stderr="NT_STATUS_LOGON_FAILURE", stdout="")
        with patch("subprocess.run", return_value=mock_result), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"):
            ok, msg = ns._test_smb_macos(p)

        assert ok is False
        assert "NT_STATUS_LOGON_FAILURE" in msg or "failed" in msg.lower()

    def test_no_socket_import_in_test_smb_macos(self):
        """_test_smb_macos does not call socket.create_connection."""
        ns = NetworkStorageManager()
        p = _smb_profile()

        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="", stdout="")), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"), \
             patch("socket.create_connection") as mock_socket, \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ns._test_smb_macos(p)

        mock_socket.assert_not_called()


# ---------------------------------------------------------------------------
# 2. macOS Test Connection includes credentials/auth path
# ---------------------------------------------------------------------------

class TestMacosTestConnectionIncludesAuth:
    """_test_smb_macos must invoke a mount command that includes credentials."""

    def test_subprocess_run_called_with_mount_smbfs(self):
        """Temp-mount approach calls subprocess.run with mount_smbfs."""
        ns = NetworkStorageManager()
        p = _smb_profile()

        captured_cmds = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(cmd)
            return MagicMock(returncode=0, stderr="", stdout="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ok, msg = ns._test_smb_macos(p)

        assert ok is True
        # First call is the mount attempt
        mount_cmd = captured_cmds[0]
        assert any("mount_smbfs" in str(part) for part in mount_cmd)

    def test_credentials_appear_in_mount_url(self):
        """The mount command URL contains the username and password."""
        ns = NetworkStorageManager()
        p = _smb_profile(username="user", password="pass")

        captured_cmds = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0, stderr="", stdout="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ok, _ = ns._test_smb_macos(p)

        mount_cmd = captured_cmds[0]
        url = next(a for a in mount_cmd if a.startswith("//"))
        assert "user" in url
        assert "pass" in url

    def test_success_returns_auth_successful_message(self):
        """Successful temp mount → message says authentication successful."""
        ns = NetworkStorageManager()
        p = _smb_profile()

        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="", stdout="")), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ok, msg = ns._test_smb_macos(p)

        assert ok is True
        assert "authentication" in msg.lower() or "successful" in msg.lower()


# ---------------------------------------------------------------------------
# 3. macOS Connect & Save includes password non-interactively
# ---------------------------------------------------------------------------

class TestMacosConnectSavePasswordNonInteractive:
    """mount() must embed the password in the URL; no interactive prompting."""

    def test_build_mount_cmd_embeds_password_in_url(self):
        """_build_mount_cmd macOS path puts password in the URL (non-interactive)."""
        ns = NetworkStorageManager()
        p = _smb_profile(username="admin", password="s3cr3t")

        with patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            cmd = ns._build_mount_cmd(p)

        url = next(a for a in cmd if a.startswith("//"))
        assert "admin" in url
        assert "s3cr3t" in url

    def test_mount_passes_stdin_devnull(self):
        """subprocess.run inside mount() is called with stdin=DEVNULL."""
        ns = NetworkStorageManager()
        p = _smb_profile()

        run_kwargs = {}

        def fake_run(cmd, **kwargs):
            run_kwargs.update(kwargs)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run), \
             patch("os.makedirs"), \
             patch("os.path.ismount", return_value=False), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ns.mount(p)

        assert run_kwargs.get("stdin") == subprocess.DEVNULL


# ---------------------------------------------------------------------------
# 4. Blank password fails in GUI before mount command runs
# ---------------------------------------------------------------------------

class TestBlankPasswordFailsBeforeMount:
    """mount() and _test_smb_macos() must fail early when password is blank."""

    def test_mount_returns_failure_for_blank_password_on_macos(self):
        """mount() returns (False, message) without calling subprocess when password is blank."""
        ns = NetworkStorageManager()
        p = _smb_profile(password="")  # username set, password blank

        with patch("subprocess.run") as mock_run, \
             patch("os.makedirs"), \
             patch("os.path.ismount", return_value=False), \
             patch("managers.network_storage_manager._MACOS", True):
            ok, msg = ns.mount(p)

        assert ok is False
        assert "password" in msg.lower()
        mock_run.assert_not_called()

    def test_test_connection_returns_failure_for_blank_password_on_macos(self):
        """_test_smb_macos() returns (False, message) without running subprocess."""
        ns = NetworkStorageManager()
        p = _smb_profile(password="")  # username set, password blank

        with patch("subprocess.run") as mock_run, \
             patch("managers.network_storage_manager._MACOS", True):
            ok, msg = ns._test_smb_macos(p)

        assert ok is False
        assert "password" in msg.lower()
        mock_run.assert_not_called()

    def test_mount_linux_not_affected_by_blank_password_guard(self):
        """Linux mount() does not apply the macOS blank-password guard."""
        ns = NetworkStorageManager()
        p = _smb_profile(password="")  # blank password, Linux path

        with patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch("os.makedirs"), \
             patch("os.path.ismount", return_value=False), \
             patch("managers.network_storage_manager._MACOS", False):
            ok, _ = ns.mount(p)

        # Linux should proceed to the mount command (may succeed or fail — just
        # must not be blocked by the macOS guard)
        assert ok is True  # subprocess mock returns 0


# ---------------------------------------------------------------------------
# 5. Linux smbclient path unchanged
# ---------------------------------------------------------------------------

class TestLinuxSmbclientUnchanged:
    """_test_smb on Linux must still use smbclient (not temp-mount)."""

    def test_linux_uses_smbclient_command(self, monkeypatch):
        """_test_smb on Linux invokes smbclient."""
        monkeypatch.setattr("managers.network_storage_manager._MACOS", False)
        ns = NetworkStorageManager()
        p = _smb_profile()

        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            ok, msg = ns._test_smb(p)

        assert ok is True
        assert any("smbclient" in str(part) for part in captured[0])

    def test_linux_smbclient_includes_credentials(self, monkeypatch):
        """Linux _test_smb passes username%password to smbclient."""
        monkeypatch.setattr("managers.network_storage_manager._MACOS", False)
        ns = NetworkStorageManager()
        p = _smb_profile(username="admin", password="pass")

        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            ns._test_smb(p)

        full = " ".join(captured[0])
        assert "admin%pass" in full

    def test_linux_smbclient_not_found_returns_install_hint(self, monkeypatch):
        """Linux _test_smb returns install hint when smbclient is missing."""
        monkeypatch.setattr("managers.network_storage_manager._MACOS", False)
        ns = NetworkStorageManager()
        p = _smb_profile()

        with patch("subprocess.run", side_effect=FileNotFoundError):
            ok, msg = ns._test_smb(p)

        assert ok is False
        assert "smbclient" in msg.lower()
