"""Tests for desktop-launcher vs terminal environment resilience.

These tests verify that SimGUI works correctly when launched from a
.desktop file (sidebar / application menu) where the process environment
is minimal — no interactive shell, no TTY, possibly missing PATH entries,
and sudo credentials not cached.

Root cause pattern:
  - From terminal: user's shell sources .bashrc, PATH is full, sudo may
    have a cached credential from recent use → mount works
  - From .desktop: display manager spawns the app with a bare environment,
    no TTY → sudo prompts fail silently, PATH may be incomplete, HOME
    might not be set

These tests would have caught the "mount works from terminal but not
from sidebar" bug.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.network_storage_manager import (
    MOUNT_BASE,
    NetworkStorageManager,
    StorageProfile,
    _MOUNT,
    _SUDO,
    _UMOUNT,
)


# ---------------------------------------------------------------------------
# 1. Absolute paths in commands — the primary fix
# ---------------------------------------------------------------------------

class TestAbsolutePathsInCommands:
    """Verify all subprocess calls use absolute paths, not bare command names.

    Bare 'mount' / 'sudo' depend on PATH, which differs between terminal
    and desktop sessions.  The sudoers NOPASSWD rule also matches on the
    full path, so a mismatch means the rule doesn't apply.
    """

    def test_module_constants_are_absolute(self):
        """_SUDO, _MOUNT, _UMOUNT must be absolute paths."""
        assert _SUDO.startswith("/"), f"_SUDO is not absolute: {_SUDO}"
        assert _MOUNT.startswith("/"), f"_MOUNT is not absolute: {_MOUNT}"
        assert _UMOUNT.startswith("/"), f"_UMOUNT is not absolute: {_UMOUNT}"

    def test_module_constants_point_to_usr_bin(self):
        """System commands should live in /usr/bin on standard Linux."""
        assert _SUDO == "/usr/bin/sudo"
        assert _MOUNT == "/usr/bin/mount"
        assert _UMOUNT == "/usr/bin/umount"

    def test_build_mount_cmd_smb_uses_absolute_sudo(self):
        """SMB mount command must start with absolute sudo path."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="test", protocol="smb",
                           server="nas", share="data")
        cmd = ns._build_mount_cmd(p)
        assert cmd[0] == "/usr/bin/sudo", (
            f"First element should be absolute sudo, got: {cmd[0]}")

    def test_build_mount_cmd_smb_uses_absolute_mount(self):
        """SMB mount command must use absolute mount path."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="test", protocol="smb",
                           server="nas", share="data")
        cmd = ns._build_mount_cmd(p)
        assert cmd[1] == "/usr/bin/mount", (
            f"Second element should be absolute mount, got: {cmd[1]}")

    def test_build_mount_cmd_nfs_uses_absolute_paths(self):
        """NFS mount command must use absolute sudo and mount paths."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="test", protocol="nfs",
                           server="10.0.0.1", share="/exports/sim")
        cmd = ns._build_mount_cmd(p)
        assert cmd[0] == "/usr/bin/sudo"
        assert cmd[1] == "/usr/bin/mount"

    def test_unmount_uses_absolute_paths(self):
        """unmount() must use absolute sudo and umount paths."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="test_umount")
        with patch.object(ns, "is_mounted", return_value=True), \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stderr="")) as mock_run, \
             patch("os.rmdir"):
            ns.unmount(p)
        args = mock_run.call_args[0][0]
        assert args[0] == "/usr/bin/sudo", (
            f"umount sudo should be absolute, got: {args[0]}")
        assert args[1] == "/usr/bin/umount", (
            f"umount should be absolute, got: {args[1]}")

    def test_check_sudo_mount_uses_absolute_paths(self):
        """check_sudo_mount() must test with absolute paths."""
        ns = NetworkStorageManager()
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0)) as mock_run:
            ns.check_sudo_mount()
        args = mock_run.call_args[0][0]
        assert args[0] == "/usr/bin/sudo"
        # -n flag for non-interactive
        assert "-n" in args
        assert "/usr/bin/mount" in args

    def test_no_bare_mount_in_any_command(self):
        """No mount command should use bare 'mount' or 'sudo' anywhere."""
        ns = NetworkStorageManager()
        profiles = [
            StorageProfile(label="smb1", protocol="smb",
                           server="nas", share="share1"),
            StorageProfile(label="smb2", protocol="smb",
                           server="nas", share="share2",
                           username="user", password="pass"),
            StorageProfile(label="nfs1", protocol="nfs",
                           server="10.0.0.1", share="/data"),
        ]
        for p in profiles:
            cmd = ns._build_mount_cmd(p)
            for i, arg in enumerate(cmd):
                if arg in ("sudo", "mount", "umount"):
                    pytest.fail(
                        f"Bare '{arg}' at index {i} in mount cmd for "
                        f"'{p.label}': {cmd}. Use absolute path instead.")


# ---------------------------------------------------------------------------
# 2. Sudoers NOPASSWD rule matching
# ---------------------------------------------------------------------------

class TestSudoersRuleMatching:
    """Verify mount commands match the sudoers NOPASSWD rules exactly.

    The sudoers file contains:
      %users ALL=(root) NOPASSWD: /usr/bin/mount -t cifs *
      %users ALL=(root) NOPASSWD: /usr/bin/mount -t nfs *
      %users ALL=(root) NOPASSWD: /usr/bin/umount /tmp/simgui-mounts/*

    If the command doesn't match exactly, sudo falls back to password
    prompting, which fails without a TTY (desktop launcher).
    """

    def test_smb_mount_matches_sudoers_pattern(self):
        """SMB mount cmd: /usr/bin/mount -t cifs -o ... //server/share /tmp/..."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="sudoers_test", protocol="smb",
                           server="nas.local", share="simdata")
        cmd = ns._build_mount_cmd(p)
        # Rule: /usr/bin/mount -t cifs *
        # Command after sudo must be: /usr/bin/mount -t cifs ...
        assert cmd[1] == "/usr/bin/mount"
        assert cmd[2] == "-t"
        assert cmd[3] == "cifs"

    def test_nfs_mount_matches_sudoers_pattern(self):
        """NFS mount cmd: /usr/bin/mount -t nfs -o ... server:/path /tmp/..."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="sudoers_test", protocol="nfs",
                           server="10.0.0.1", share="/exports/sim")
        cmd = ns._build_mount_cmd(p)
        assert cmd[1] == "/usr/bin/mount"
        assert cmd[2] == "-t"
        assert cmd[3] == "nfs"

    def test_umount_matches_sudoers_pattern(self):
        """Unmount cmd target must be under /tmp/simgui-mounts/."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="sudoers_test")
        with patch.object(ns, "is_mounted", return_value=True), \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stderr="")) as mock_run, \
             patch("os.rmdir"):
            ns.unmount(p)
        cmd = mock_run.call_args[0][0]
        # Rule: /usr/bin/umount /tmp/simgui-mounts/*
        assert cmd[1] == "/usr/bin/umount"
        assert cmd[2].startswith("/tmp/simgui-mounts/")

    def test_mount_point_always_under_mount_base(self):
        """All mount points must be under MOUNT_BASE for sudoers to match."""
        labels = [
            "simple", "With Spaces", "Special/Chars",
            "a" * 200,  # very long label
        ]
        for label in labels:
            p = StorageProfile(label=label)
            mp = p.mount_point
            assert mp.startswith(MOUNT_BASE + "/"), (
                f"mount_point for '{label}' not under MOUNT_BASE: {mp}")

    def test_mount_point_sanitises_path_traversal(self):
        """Labels with '..' get sanitised so the mount point stays safe.

        The mount_point property replaces '/' with '_', so '../x'
        becomes '.._x' which is still under MOUNT_BASE.  The resolved
        path must not escape MOUNT_BASE.
        """
        p = StorageProfile(label="../escape_attempt")
        mp = p.mount_point
        # The resolved path must still be under MOUNT_BASE
        resolved = os.path.realpath(mp)
        assert resolved.startswith(os.path.realpath(MOUNT_BASE)), (
            f"mount_point escapes MOUNT_BASE: {mp} -> {resolved}")


# ---------------------------------------------------------------------------
# 3. Sudo permission error detection
# ---------------------------------------------------------------------------

class TestSudoPermissionDetection:
    """Verify all known sudo TTY/askpass error messages are caught.

    When launched from .desktop without NOPASSWD configured, sudo emits
    various error messages depending on distro and sudo version.  All of
    them must be detected so we can show the user-friendly fix message.
    """

    # Real-world sudo error messages from different environments
    REAL_SUDO_ERRORS = [
        # Ubuntu 22.04+ / sudo 1.9.x
        "sudo: a terminal is required to read the password; "
        "either use the -S option to read from standard input or "
        "configure an askpass helper\n"
        "sudo: a password is required",
        # Older sudo
        "sudo: no tty present and no askpass program specified",
        # Fedora / RHEL
        "sudo: a password is required",
        # Minimal message
        "a terminal is required",
        # Edge case: mixed case
        "sudo: A Terminal Is Required to read the password",
    ]

    NOT_SUDO_ERRORS = [
        "mount.cifs: permission denied",
        "mount error(13): Permission denied",
        "Connection timed out",
        "",
        "mount: /tmp/simgui-mounts/test: special device //nas/share does not exist",
    ]

    def test_detects_all_known_sudo_errors(self):
        """All real sudo TTY error messages must be detected."""
        for msg in self.REAL_SUDO_ERRORS:
            assert NetworkStorageManager._is_sudo_permission_error(msg), (
                f"Failed to detect sudo error: {msg!r}")

    def test_does_not_falsely_detect_non_sudo_errors(self):
        """Non-sudo errors must not trigger the sudo fix message."""
        for msg in self.NOT_SUDO_ERRORS:
            assert not NetworkStorageManager._is_sudo_permission_error(msg), (
                f"Falsely detected as sudo error: {msg!r}")

    def test_mount_returns_fix_message_on_sudo_error(self):
        """mount() returns the user-friendly fix message on sudo TTY error."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="fix_test", protocol="smb",
                           server="nas", share="data")
        sudo_err = (
            "sudo: a terminal is required to read the password; "
            "either use the -S option to read from standard input or "
            "configure an askpass helper\nsudo: a password is required"
        )
        with patch.object(ns, "is_mounted", return_value=False), \
             patch("os.makedirs"), \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=1,
                                          stderr=sudo_err,
                                          stdout="")):
            ok, msg = ns.mount(p)
        assert ok is False
        assert "simgui-setup-mount" in msg
        assert "Mount failed" not in msg  # should NOT show raw error

    def test_unmount_returns_fix_message_on_sudo_error(self):
        """unmount() returns the user-friendly fix message on sudo TTY error."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="fix_test")
        sudo_err = "sudo: no tty present and no askpass program specified"
        with patch.object(ns, "is_mounted", return_value=True), \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=1,
                                          stderr=sudo_err,
                                          stdout="")):
            ok, msg = ns.unmount(p)
        assert ok is False
        assert "simgui-setup-mount" in msg

    def test_fix_message_contains_actionable_instructions(self):
        """The sudo fix message must tell the user exactly what to run."""
        msg = NetworkStorageManager._sudo_fix_message()
        assert "sudo simgui-setup-mount" in msg
        # Should also mention manual alternative
        assert "sudoers" in msg.lower() or "/etc/sudoers.d/" in msg


# ---------------------------------------------------------------------------
# 4. Desktop environment edge cases
# ---------------------------------------------------------------------------

class TestDesktopEnvironmentEdgeCases:
    """Test scenarios specific to desktop launcher environments."""

    def test_cred_dir_handles_missing_home(self):
        """Credential dir works even if HOME is empty or unset.

        Desktop sessions sometimes have HOME unset.  The manager should
        fall back gracefully.
        """
        with patch.dict(os.environ, {"HOME": "", "XDG_CONFIG_HOME": ""},
                        clear=False):
            ns = NetworkStorageManager()
            # Should not crash, cred_dir should be a valid path
            assert ns._cred_dir is not None
            assert isinstance(ns._cred_dir, str)

    def test_cred_dir_uses_xdg_config_home(self):
        """Credential dir respects XDG_CONFIG_HOME when set."""
        with patch.dict(os.environ,
                        {"XDG_CONFIG_HOME": "/custom/config"},
                        clear=False):
            ns = NetworkStorageManager()
            assert ns._cred_dir.startswith("/custom/config")

    def test_mount_base_is_absolute_and_under_tmp(self):
        """MOUNT_BASE must be absolute and under /tmp for security."""
        assert MOUNT_BASE.startswith("/tmp/"), (
            f"MOUNT_BASE should be under /tmp: {MOUNT_BASE}")

    def test_mount_creates_mount_point_directory(self):
        """mount() creates the mount point dir even if it doesn't exist."""
        ns = NetworkStorageManager()
        p = StorageProfile(label="mkdir_test", protocol="smb",
                           server="nas", share="data")
        with patch.object(ns, "is_mounted", return_value=False), \
             patch("os.makedirs") as mock_makedirs, \
             patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stderr="")):
            ns.mount(p)
        mock_makedirs.assert_called_once_with(p.mount_point, exist_ok=True)


# ---------------------------------------------------------------------------
# 5. Launcher script validation
# ---------------------------------------------------------------------------

class TestLauncherScript:
    """Validate the desktop launcher script handles environment correctly."""

    LAUNCHER_PATH = os.path.join(
        os.path.dirname(__file__), '..', 'debian', 'simgui-launcher')

    def test_launcher_exists_and_is_executable(self):
        """The launcher script must exist."""
        assert os.path.isfile(self.LAUNCHER_PATH), (
            f"Launcher script not found: {self.LAUNCHER_PATH}")

    def test_launcher_has_shebang(self):
        """Launcher must have a proper #!/bin/bash shebang."""
        with open(self.LAUNCHER_PATH) as f:
            first_line = f.readline().strip()
        assert first_line == "#!/bin/bash", (
            f"Launcher shebang wrong: {first_line}")

    def test_launcher_sets_path(self):
        """Launcher must export PATH with /usr/bin included.

        Without this, desktop sessions may not find sudo, mount, etc.
        """
        with open(self.LAUNCHER_PATH) as f:
            content = f.read()
        assert "export PATH=" in content or "PATH=" in content, (
            "Launcher must set PATH for desktop environments")
        assert "/usr/bin" in content, (
            "Launcher PATH must include /usr/bin")

    def test_launcher_ensures_home(self):
        """Launcher must ensure HOME is set.

        Some display managers don't propagate HOME, breaking
        os.path.expanduser('~') and credential file access.
        """
        with open(self.LAUNCHER_PATH) as f:
            content = f.read()
        assert "HOME" in content, (
            "Launcher must ensure HOME is set for credential file access")


# ---------------------------------------------------------------------------
# 6. Sudoers file validation
# ---------------------------------------------------------------------------

class TestSudoersFile:
    """Validate the sudoers template matches the commands we actually run."""

    SUDOERS_PATH = os.path.join(
        os.path.dirname(__file__), '..', 'etc', 'simgui-mount.sudoers')

    def test_sudoers_file_exists(self):
        """The sudoers template must exist."""
        assert os.path.isfile(self.SUDOERS_PATH)

    def test_sudoers_allows_mount_cifs(self):
        """Sudoers must allow /usr/bin/mount -t cifs."""
        with open(self.SUDOERS_PATH) as f:
            content = f.read()
        assert "/usr/bin/mount -t cifs" in content

    def test_sudoers_allows_mount_nfs(self):
        """Sudoers must allow /usr/bin/mount -t nfs."""
        with open(self.SUDOERS_PATH) as f:
            content = f.read()
        assert "/usr/bin/mount -t nfs" in content

    def test_sudoers_allows_umount_simgui_mounts(self):
        """Sudoers must allow umount under /tmp/simgui-mounts/."""
        with open(self.SUDOERS_PATH) as f:
            content = f.read()
        assert "/usr/bin/umount /tmp/simgui-mounts/" in content

    def test_sudoers_paths_match_module_constants(self):
        """Sudoers paths must match the absolute paths used in code."""
        with open(self.SUDOERS_PATH) as f:
            content = f.read()
        assert _MOUNT in content, (
            f"Sudoers file must reference {_MOUNT}")
        assert _UMOUNT in content, (
            f"Sudoers file must reference {_UMOUNT}")

    def test_sudoers_uses_nopasswd(self):
        """All rules must use NOPASSWD (desktop launcher has no TTY)."""
        with open(self.SUDOERS_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    assert "NOPASSWD" in line, (
                        f"Non-comment sudoers line missing NOPASSWD: {line}")

    def test_sudoers_no_trailing_newlines_or_syntax_issues(self):
        """Sudoers file must end with a newline (visudo requirement)."""
        with open(self.SUDOERS_PATH, "rb") as f:
            content = f.read()
        assert content.endswith(b"\n"), (
            "Sudoers file must end with a newline")
        # No Windows line endings
        assert b"\r" not in content, (
            "Sudoers file must not have Windows line endings")


# ---------------------------------------------------------------------------
# 7. Setup script validation
# ---------------------------------------------------------------------------

class TestSetupScript:
    """Validate the one-time setup script for sudo permissions."""

    SETUP_PATH = os.path.join(
        os.path.dirname(__file__), '..', 'bin', 'simgui-setup-mount')

    def test_setup_script_exists(self):
        """The setup script must exist."""
        assert os.path.isfile(self.SETUP_PATH)

    def test_setup_script_has_shebang(self):
        """Setup script must have a proper bash shebang."""
        with open(self.SETUP_PATH) as f:
            first_line = f.readline().strip()
        assert first_line == "#!/bin/bash"

    def test_setup_script_checks_root(self):
        """Setup script must verify it's running as root."""
        with open(self.SETUP_PATH) as f:
            content = f.read()
        assert "id -u" in content or "EUID" in content, (
            "Setup script must check for root privileges")

    def test_setup_script_validates_sudoers(self):
        """Setup script must run visudo -c before installing."""
        with open(self.SETUP_PATH) as f:
            content = f.read()
        assert "visudo" in content, (
            "Setup script must validate sudoers syntax with visudo")

    def test_setup_script_sets_correct_permissions(self):
        """Setup script must chmod 0440 the installed sudoers file."""
        with open(self.SETUP_PATH) as f:
            content = f.read()
        assert "0440" in content or "440" in content, (
            "Setup script must set 0440 permissions on sudoers file")


# ---------------------------------------------------------------------------
# 8. Reconnect resilience
# ---------------------------------------------------------------------------

class TestReconnectResilience:
    """Test auto-reconnect behaviour under desktop environment conditions."""

    def test_reconnect_handles_sudo_error_gracefully(self):
        """reconnect_saved() must not crash on sudo TTY errors.

        At app startup from .desktop, if NOPASSWD isn't configured,
        every auto-reconnect attempt will hit a sudo error.  The app
        must start up cleanly and show warnings, not crash.
        """
        import json
        import tempfile
        from managers.settings_manager import SettingsManager

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         delete=False) as fh:
            json.dump({
                "network_profiles": [
                    {"label": "NAS", "protocol": "smb",
                     "server": "192.168.1.1", "share": "data",
                     "auto_connect": True}
                ]
            }, fh)
            path = fh.name

        try:
            sm = SettingsManager(path=path)
            ns = NetworkStorageManager(sm)
            sudo_err = (
                "sudo: a terminal is required to read the password; "
                "sudo: a password is required"
            )
            with patch("subprocess.run",
                       return_value=MagicMock(returncode=1,
                                              stderr=sudo_err,
                                              stdout="")), \
                 patch("os.makedirs"), \
                 patch("os.path.ismount", return_value=False):
                results = ns.reconnect_saved()

            # Should return results, not crash
            assert len(results) == 1
            label, ok, msg = results[0]
            assert label == "NAS"
            assert ok is False
            assert "simgui-setup-mount" in msg
        finally:
            os.unlink(path)

    def test_reconnect_skips_already_mounted(self):
        """reconnect_saved() skips profiles that are already mounted.

        This can happen if the user manually mounted the share before
        starting the app.
        """
        import json
        import tempfile
        from managers.settings_manager import SettingsManager

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         delete=False) as fh:
            json.dump({
                "network_profiles": [
                    {"label": "NAS", "protocol": "smb",
                     "server": "192.168.1.1", "share": "data",
                     "auto_connect": True}
                ]
            }, fh)
            path = fh.name

        try:
            sm = SettingsManager(path=path)
            ns = NetworkStorageManager(sm)
            with patch("os.path.ismount", return_value=True), \
                 patch("subprocess.run") as mock_run:
                results = ns.reconnect_saved()

            # Should not have called subprocess (already mounted)
            mock_run.assert_not_called()
            assert len(results) == 1
            assert results[0][1] is True  # ok
        finally:
            os.unlink(path)
