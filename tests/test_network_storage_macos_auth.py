"""Targeted tests for macOS SMB authentication fixes.

Covers:
1. macOS Test Connection does not use socket-only success.
2. macOS Test Connection includes credentials/auth path (temp mount).
3. macOS Connect & Save includes password non-interactively (URL encoding).
4. Blank password fails before subprocess if share is not already mounted.
5. Linux smbclient path unchanged.
6. Already-mounted share succeeds without a new mount command.
7. _build_mount_cmd does not include sudo on macOS.
8. Masked URL logging hides password.
"""

import subprocess
import sys
from unittest.mock import MagicMock, patch, call

import pytest

from managers.network_storage_manager import (
    NetworkStorageManager,
    StorageProfile,
    _mask_smb_url,
)


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

        # First call: /sbin/mount (existing-mount check) — returns empty output
        # Second call: mount_smbfs (temp mount) — returns auth failure
        def fake_run(cmd, **kwargs):
            if cmd[0] == "/sbin/mount":
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=1, stderr="NT_STATUS_LOGON_FAILURE", stdout="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=False):
            ok, msg = ns._test_smb_macos(p)

        assert ok is False
        assert "NT_STATUS_LOGON_FAILURE" in msg or "failed" in msg.lower()

    def test_no_socket_import_in_test_smb_macos(self):
        """_test_smb_macos does not call socket.create_connection."""
        ns = NetworkStorageManager()
        p = _smb_profile()

        def fake_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"), \
             patch("os.path.ismount", return_value=False), \
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
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"), \
             patch("os.path.ismount", return_value=False), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ok, msg = ns._test_smb_macos(p)

        assert ok is True
        # Find the mount_smbfs call among all subprocess calls
        mount_calls = [c for c in captured_cmds if any("mount_smbfs" in str(p) for p in c)]
        assert mount_calls, "mount_smbfs was never called"

    def test_credentials_appear_in_mount_url(self):
        """The mount command URL contains the username and password."""
        ns = NetworkStorageManager()
        p = _smb_profile(username="user", password="pass")

        captured_cmds = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"), \
             patch("os.path.ismount", return_value=False), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ok, _ = ns._test_smb_macos(p)

        # Find the mount_smbfs call
        mount_cmd = next(c for c in captured_cmds if any("mount_smbfs" in str(x) for x in c))
        url = next(a for a in mount_cmd if a.startswith("//"))
        assert "user" in url
        assert "pass" in url

    def test_success_returns_auth_successful_message(self):
        """Successful temp mount → message says authentication successful."""
        ns = NetworkStorageManager()
        p = _smb_profile()

        def fake_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("tempfile.mkdtemp", return_value="/tmp/simgui-test-fake"), \
             patch("os.rmdir"), \
             patch("os.path.ismount", return_value=False), \
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

    def test_build_mount_cmd_does_not_include_sudo_on_macos(self):
        """_build_mount_cmd macOS path must not include sudo (sudo opens /dev/tty)."""
        ns = NetworkStorageManager()
        p = _smb_profile()

        with patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            cmd = ns._build_mount_cmd(p)

        assert cmd[0] == "/sbin/mount_smbfs", (
            f"First element should be mount_smbfs, got {cmd[0]!r}"
        )
        assert not any("sudo" in str(part) for part in cmd), (
            "sudo must not appear in macOS mount command"
        )

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
# 4. Blank password fails before subprocess if not already mounted
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

    def test_test_connection_returns_failure_for_blank_password_when_not_mounted(self):
        """_test_smb_macos() fails with a clear message when share is not mounted
        and password is blank (subprocess is not called for the mount attempt)."""
        ns = NetworkStorageManager()
        p = _smb_profile(password="")  # username set, password blank

        mount_smbfs_calls = []

        def fake_run(cmd, **kwargs):
            if _MOUNT_SMB_FS_VAL in str(cmd):
                mount_smbfs_calls.append(cmd)
            # Return empty mount list so existing-mount check finds nothing
            return MagicMock(returncode=0, stdout="", stderr="")

        _MOUNT_SMB_FS_VAL = "/sbin/mount_smbfs"

        with patch("subprocess.run", side_effect=fake_run), \
             patch("os.path.ismount", return_value=False), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", _MOUNT_SMB_FS_VAL):
            ok, msg = ns._test_smb_macos(p)

        assert ok is False
        assert "password" in msg.lower()
        assert not mount_smbfs_calls, "mount_smbfs must not be called when password is blank"

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


# ---------------------------------------------------------------------------
# 6. Already-mounted share succeeds without a new mount command
# ---------------------------------------------------------------------------

class TestAlreadyMountedShareSucceeds:
    """If the share is already mounted, Test Connection must succeed
    without running any mount_smbfs command."""

    def test_test_connection_succeeds_when_own_mount_point_active(self):
        """_test_smb_macos returns success when profile mount point is mounted."""
        ns = NetworkStorageManager()
        p = _smb_profile()

        with patch("subprocess.run") as mock_run, \
             patch("os.path.ismount", return_value=True), \
             patch("managers.network_storage_manager._MACOS", True):
            ok, msg = ns._test_smb_macos(p)

        assert ok is True
        assert "already mounted" in msg.lower()
        # No mount_smbfs invocation needed
        mount_calls = [c for c in mock_run.call_args_list
                       if "mount_smbfs" in str(c)]
        assert not mount_calls

    def test_test_connection_succeeds_when_finder_mounted(self):
        """_test_smb_macos returns success when share is mounted by Finder."""
        ns = NetworkStorageManager()
        p = _smb_profile(server="nas.local", share="simdata")

        mount_output = (
            "//admin@nas.local/simdata on /Volumes/simdata (smbfs, nodev, nosuid)\n"
        )

        captured_cmds = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0, stdout=mount_output, stderr="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True), \
             patch("managers.network_storage_manager._MACOS", True):
            ok, msg = ns._test_smb_macos(p)

        assert ok is True
        assert "/Volumes/simdata" in msg
        # Only /sbin/mount was called (to list mounts) — no mount_smbfs
        assert all("mount_smbfs" not in str(c) for c in captured_cmds)

    def test_macos_find_smb_mount_parses_mount_output(self):
        """_macos_find_smb_mount returns path when share appears in mount output."""
        ns = NetworkStorageManager()
        p = _smb_profile(server="nas.local", share="simdata")

        mount_output = (
            "devfs on /dev (devfs, local, nobrowse)\n"
            "//user@nas.local/simdata on /Volumes/simdata (smbfs, nodev)\n"
        )

        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=mount_output, stderr="")), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True):
            result = ns._macos_find_smb_mount(p)

        assert result == "/Volumes/simdata"

    def test_macos_find_smb_mount_returns_none_when_not_mounted(self):
        """_macos_find_smb_mount returns None when share is not in mount list."""
        ns = NetworkStorageManager()
        p = _smb_profile(server="nas.local", share="simdata")

        mount_output = "devfs on /dev (devfs, local, nobrowse)\n"

        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=mount_output, stderr="")), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=False):
            result = ns._macos_find_smb_mount(p)

        assert result is None

    def test_macos_find_smb_mount_prefers_own_mount_point(self):
        """_macos_find_smb_mount returns profile.mount_point when it is mounted."""
        ns = NetworkStorageManager()
        p = _smb_profile()

        with patch("subprocess.run") as mock_run, \
             patch("os.path.ismount", return_value=True):
            result = ns._macos_find_smb_mount(p)

        assert result == p.mount_point
        # /sbin/mount not needed — own mount point check is first
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Masked URL logging hides password
# ---------------------------------------------------------------------------

class TestMaskedUrlLogging:
    """_mask_smb_url must replace passwords in SMB URLs with ***."""

    def test_password_replaced_in_url(self):
        cmd = ["/sbin/mount_smbfs", "//admin:s3cr3t@nas.local/share", "/mnt/point"]
        masked = _mask_smb_url(cmd)
        assert "s3cr3t" not in " ".join(masked)
        assert "***" in " ".join(masked)
        assert "admin" in " ".join(masked)
        assert "nas.local" in " ".join(masked)

    def test_url_without_password_unchanged(self):
        cmd = ["/sbin/mount_smbfs", "//admin@nas.local/share", "/mnt/point"]
        masked = _mask_smb_url(cmd)
        assert masked == cmd

    def test_non_url_parts_unchanged(self):
        cmd = ["/sbin/mount_smbfs", "//u:p@h/s", "/tmp/mp"]
        masked = _mask_smb_url(cmd)
        assert masked[0] == "/sbin/mount_smbfs"
        assert masked[2] == "/tmp/mp"

    def test_special_chars_in_password_masked(self):
        cmd = ["//user:p%40ss!@host/share"]
        masked = _mask_smb_url(cmd)
        assert "p%40ss!" not in masked[0]
        assert "***" in masked[0]


# ---------------------------------------------------------------------------
# 9. macOS unmount uses _UMOUNT_MACOS without sudo (no /dev/tty prompt)
# ---------------------------------------------------------------------------

class TestMacosUnmountNoSudo:
    """unmount() on macOS must not use sudo so quit path is non-interactive."""

    def test_unmount_macos_uses_umount_macos_not_sudo(self):
        """On macOS, unmount cmd is [_UMOUNT_MACOS, mp] — no sudo prefix."""
        ns = NetworkStorageManager()
        p = _smb_profile(label="TestShare")
        ns._active_mounts["TestShare"] = p

        captured_cmds = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0, stderr="", stdout="")

        with patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._UMOUNT_MACOS", "/sbin/umount"), \
             patch.object(ns, "is_mounted", return_value=True), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("os.rmdir"):
            ok, msg = ns.unmount(p)

        assert ok is True
        assert captured_cmds, "subprocess.run was never called"
        cmd = captured_cmds[0]
        assert "/sbin/umount" in cmd, f"Expected /sbin/umount in cmd, got {cmd}"
        assert not any("sudo" in str(part) for part in cmd), (
            f"sudo must not appear in macOS unmount cmd: {cmd}"
        )

    def test_unmount_macos_passes_stdin_devnull(self):
        """unmount() on macOS passes stdin=DEVNULL so no /dev/tty is opened."""
        ns = NetworkStorageManager()
        p = _smb_profile(label="TestShare2")
        ns._active_mounts["TestShare2"] = p

        run_kwargs = {}

        def fake_run(cmd, **kwargs):
            run_kwargs.update(kwargs)
            return MagicMock(returncode=0, stderr="", stdout="")

        with patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._UMOUNT_MACOS", "/sbin/umount"), \
             patch.object(ns, "is_mounted", return_value=True), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("os.rmdir"):
            ns.unmount(p)

        assert run_kwargs.get("stdin") == subprocess.DEVNULL

    def test_unmount_linux_still_uses_sudo(self):
        """On Linux, unmount cmd retains the sudo prefix."""
        ns = NetworkStorageManager()
        p = _smb_profile(label="LinuxShare")
        ns._active_mounts["LinuxShare"] = p

        captured_cmds = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0, stderr="", stdout="")

        with patch("managers.network_storage_manager._MACOS", False), \
             patch.object(ns, "is_mounted", return_value=True), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("os.rmdir"):
            ok, msg = ns.unmount(p)

        assert ok is True
        cmd = captured_cmds[0]
        assert cmd[0] == "/usr/bin/sudo", f"Linux unmount must start with sudo, got {cmd[0]!r}"


# ---------------------------------------------------------------------------
# 10. Connected share updates bottom status bar with label and mount path
# ---------------------------------------------------------------------------

class TestShareStatusLabel:
    """_on_share_status_changed must show '● label (path)' when connected."""

    def _make_app_stub(self):
        import types
        import main as main_mod
        stub = MagicMock()
        stub._on_share_status_changed = types.MethodType(
            main_mod.SimGUIApp._on_share_status_changed, stub)
        return stub

    def test_connected_status_shows_label_and_path(self):
        """Handler sets _share_label text to include both label and mount path."""
        from state_manager import ShareStatus
        stub = self._make_app_stub()

        status = ShareStatus(
            connected=True,
            labels=["NAS"],
            mount_paths=[("NAS", "/tmp/simgui-mounts/NAS")],
        )
        with patch("main.QtTheme") as mock_theme:
            mock_theme.get_color.return_value = "#00ff00"
            stub._on_share_status_changed(status)

        text = stub._share_label.setText.call_args[0][0]
        assert "NAS" in text
        assert "/tmp/simgui-mounts/NAS" in text

    def test_disconnected_status_clears_label(self):
        """Handler sets _share_label to empty string when not connected."""
        from state_manager import ShareStatus
        stub = self._make_app_stub()

        status = ShareStatus(connected=False, labels=[], mount_paths=[])
        stub._on_share_status_changed(status)

        stub._share_label.setText.assert_called_with("")

    def test_connected_no_paths_falls_back_to_display_text(self):
        """Handler falls back to display_text when mount_paths is empty."""
        from state_manager import ShareStatus
        stub = self._make_app_stub()

        status = ShareStatus(connected=True, labels=["NAS"], mount_paths=[])
        with patch("main.QtTheme") as mock_theme:
            mock_theme.get_color.return_value = "#00ff00"
            stub._on_share_status_changed(status)

        text = stub._share_label.setText.call_args[0][0]
        assert "NAS" in text


# ---------------------------------------------------------------------------
# 11. macOS SMB existing-mount adoption username check
# ---------------------------------------------------------------------------

class TestMacosSmBAdoptionUsernameCheck:
    """_macos_find_smb_mount_for_adoption must verify username before adopting."""

    def _profile(self, **kwargs):
        defaults = dict(label="SIM", protocol="smb", server="nas.local", share="SIM",
                        username="simgui", password="secret")
        defaults.update(kwargs)
        return StorageProfile(**defaults)

    def test_matching_username_is_adopted(self):
        """Adoption succeeds when mount username matches profile.username."""
        ns = NetworkStorageManager()
        p = self._profile()
        mount_output = "//simgui@nas.local/SIM on /Volumes/SIM (smbfs, nodev, nosuid)\n"

        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=mount_output, stderr="")), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True):
            path, err = ns._macos_find_smb_mount_for_adoption(p)

        assert err is None
        assert path == "/Volumes/SIM"

    def test_different_username_is_refused(self):
        """Adoption fails when mount username differs from profile.username."""
        ns = NetworkStorageManager()
        p = self._profile(username="simgui")
        mount_output = "//johneff@nas.local/SIM on /Volumes/SIM (smbfs, nodev, nosuid)\n"

        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=mount_output, stderr="")), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True):
            path, err = ns._macos_find_smb_mount_for_adoption(p)

        assert path is None
        assert err is not None

    def test_refusal_message_names_existing_username_not_password(self):
        """Refusal error names the existing mount username and does not contain the profile password."""
        ns = NetworkStorageManager()
        p = self._profile(username="simgui", password="s3cr3t")
        mount_output = "//johneff@nas.local/SIM on /Volumes/SIM (smbfs, nodev, nosuid)\n"

        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=mount_output, stderr="")), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True):
            path, err = ns._macos_find_smb_mount_for_adoption(p)

        assert err == (
            "Share is already mounted as johneff. "
            "Disconnect that mount, use matching credentials, "
            "or choose to use the existing mount."
        )
        assert "s3cr3t" not in err

    def test_refused_adoption_leaves_active_mounts_empty(self):
        """mount() with a refused adoption leaves _active_mounts and _actual_mount_paths empty."""
        ns = NetworkStorageManager()
        p = self._profile()
        mount_scan_output = "//johneff@nas.local/SIM on /Volumes/SIM (smbfs, nodev, nosuid)\n"

        def fake_run(cmd, **kwargs):
            if "mount_smbfs" in str(cmd):
                return MagicMock(returncode=1, stderr="already mounted", stdout="")
            if cmd == ["/sbin/mount"]:
                return MagicMock(returncode=0, stdout=mount_scan_output, stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("os.makedirs"), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ok, msg = ns.mount(p)

        assert ok is False
        assert "SIM" not in ns._active_mounts
        assert "SIM" not in ns._actual_mount_paths

    def test_unknown_username_does_not_silently_adopt_profile_credential_mount(self):
        """If mount URL has no @-username and profile.username is set, adoption is refused."""
        ns = NetworkStorageManager()
        p = self._profile(username="simgui")
        # Mount line without @ — username cannot be determined
        mount_output = "//nas.local/SIM on /Volumes/SIM (smbfs, nodev, nosuid)\n"

        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=mount_output, stderr="")), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True):
            path, err = ns._macos_find_smb_mount_for_adoption(p)

        assert path is None
        assert err is not None

    def test_refusal_message_includes_all_three_options(self):
        """Refusal message includes disconnect, credential, and existing-mount options."""
        ns = NetworkStorageManager()
        p = self._profile(username="simgui", password="s3cr3t")
        mount_output = "//johneff@nas.local/SIM on /Volumes/SIM (smbfs, nodev, nosuid)\n"

        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=mount_output, stderr="")), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True):
            _, err = ns._macos_find_smb_mount_for_adoption(p)

        assert "johneff" in err
        assert "Disconnect" in err
        assert "matching credentials" in err
        assert "existing mount" in err

    def test_explicit_mount_attempted_after_username_mismatch(self):
        """mount() calls mount_smbfs a second time after detecting username mismatch."""
        ns = NetworkStorageManager()
        p = self._profile(username="simgui")
        mount_scan_output = "//johneff@nas.local/SIM on /Volumes/SIM (smbfs, nodev, nosuid)\n"

        mount_smbfs_calls = []

        def fake_run(cmd, **kwargs):
            if any("mount_smbfs" in str(x) for x in cmd):
                mount_smbfs_calls.append(list(cmd))
                return MagicMock(returncode=1, stderr="already mounted", stdout="")
            if cmd == ["/sbin/mount"]:
                return MagicMock(returncode=0, stdout=mount_scan_output, stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("os.makedirs"), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ok, msg = ns.mount(p)

        assert ok is False
        # Two mount_smbfs calls: the initial attempt and the explicit retry
        assert len(mount_smbfs_calls) == 2, (
            f"Expected 2 mount_smbfs calls (initial + explicit retry), got {len(mount_smbfs_calls)}"
        )

    def test_explicit_mount_succeeds_after_username_mismatch(self):
        """mount() succeeds and tracks the profile when the explicit retry mount works."""
        ns = NetworkStorageManager()
        p = self._profile(username="simgui", password="secret")
        mount_scan_output = "//johneff@nas.local/SIM on /Volumes/SIM (smbfs, nodev, nosuid)\n"
        call_count = {"n": 0}

        def fake_run(cmd, **kwargs):
            if any("mount_smbfs" in str(x) for x in cmd):
                call_count["n"] += 1
                # First call fails (initial attempt), second call succeeds (explicit retry)
                rc = 1 if call_count["n"] == 1 else 0
                return MagicMock(returncode=rc, stderr="already mounted" if rc else "", stdout="")
            if cmd == ["/sbin/mount"]:
                return MagicMock(returncode=0, stdout=mount_scan_output, stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("os.makedirs"), \
             patch("os.path.ismount", return_value=False), \
             patch("os.path.isdir", return_value=True), \
             patch("managers.network_storage_manager._MACOS", True), \
             patch("managers.network_storage_manager._MOUNT_SMB_FS", "/sbin/mount_smbfs"):
            ok, msg = ns.mount(p)

        assert ok is True
        assert p.label in ns._active_mounts
        assert "Mounted" in msg
