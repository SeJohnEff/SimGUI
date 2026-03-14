"""
Network Storage Manager — NFS and SMB mount/unmount for SimGUI.

Handles mounting remote shares to local mount points so the rest of
the application can use standard file I/O.  Connection profiles are
persisted via :class:`SettingsManager`.

Mount points live under ``/tmp/simgui-mounts/<label>/`` and are
created/removed automatically.  Mounting requires *sudo* privileges
(the install script adds a polkit rule for mount/umount).

Security note: SMB passwords are stored in a 0600 credentials file
under ``~/.config/simgui/`` — never in the JSON settings.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

MOUNT_BASE = "/tmp/simgui-mounts"

# Absolute paths for system commands — critical for desktop-launcher
# environments where PATH may not include /usr/bin or sudo's
# secure_path may differ.  The sudoers NOPASSWD rule references
# these exact paths, so using bare 'mount' could fail to match.
_SUDO = "/usr/bin/sudo"
_MOUNT = "/usr/bin/mount"
_UMOUNT = "/usr/bin/umount"


@dataclass
class StorageProfile:
    """One saved network storage connection."""

    label: str                        # Human-readable name (e.g. "SIM Data NAS")
    protocol: str = "smb"            # "smb" or "nfs"
    server: str = ""                  # hostname / IP
    share: str = ""                   # share name or NFS export path
    username: str = ""                # SMB only
    password: str = ""                # SMB only (stored separately, not in JSON)
    domain: str = ""                  # SMB workgroup / domain (optional)
    mount_options: str = ""           # Extra mount options (advanced)
    # Artifact export defaults
    export_subdir: str = "artifacts"  # Sub-directory for saving artifacts
    export_fields: list = field(default_factory=lambda: [
        "ICCID", "IMSI", "Ki", "OPc",
    ])
    # Auto-reconnect: True means mount this share on app startup
    auto_connect: bool = False

    @property
    def mount_point(self) -> str:
        """Local path where this share will be mounted."""
        safe = self.label.replace(" ", "_").replace("/", "_")
        return os.path.join(MOUNT_BASE, safe)

    @property
    def source_path(self) -> str:
        """The remote path in mount(8) notation."""
        if self.protocol == "nfs":
            return f"{self.server}:{self.share}"
        # SMB: //server/share
        share = self.share.lstrip("/")
        return f"//{self.server}/{share}"

    def to_dict(self) -> dict:
        """Serialise for JSON (excludes password)."""
        d = asdict(self)
        d.pop("password", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StorageProfile":
        # Accept unknown keys gracefully
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


class NetworkStorageManager:
    """Mount / unmount NFS and SMB shares."""

    def __init__(self, settings_manager=None):
        self._settings = settings_manager
        self._active_mounts: dict[str, StorageProfile] = {}
        self._cred_dir = os.path.join(
            os.environ.get("XDG_CONFIG_HOME",
                           os.path.expanduser("~/.config")),
            "simgui",
        )

    # ---- Profile persistence -------------------------------------------

    def load_profiles(self) -> list[StorageProfile]:
        """Load saved profiles from settings."""
        if self._settings is None:
            return []
        raw = self._settings.get("network_profiles", [])
        profiles = []
        for d in raw:
            p = StorageProfile.from_dict(d)
            # Try loading password from cred file
            p.password = self._read_password(p.label)
            profiles.append(p)
        return profiles

    def save_profiles(self, profiles: list[StorageProfile]) -> None:
        """Persist profiles to settings (passwords stored separately)."""
        if self._settings is None:
            return
        self._settings.set("network_profiles",
                           [p.to_dict() for p in profiles])
        self._settings.save()
        for p in profiles:
            if p.password:
                self._write_password(p.label, p.username, p.password,
                                     p.domain)

    # ---- Mount / unmount -----------------------------------------------

    def mount(self, profile: StorageProfile) -> tuple[bool, str]:
        """Mount the share.  Returns (success, message)."""
        mp = profile.mount_point
        if self.is_mounted(profile):
            return True, f"Already mounted at {mp}"

        os.makedirs(mp, exist_ok=True)

        try:
            cmd = self._build_mount_cmd(profile)
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout).strip()
                if self._is_sudo_permission_error(err):
                    return False, self._sudo_fix_message()
                return False, f"Mount failed: {err}"
        except FileNotFoundError as exc:
            return False, f"Mount command not found: {exc}"
        except subprocess.TimeoutExpired:
            return False, "Mount timed out (30 s)"

        self._active_mounts[profile.label] = profile
        return True, f"Mounted at {mp}"

    def unmount(self, profile: StorageProfile) -> tuple[bool, str]:
        """Unmount a previously mounted share."""
        mp = profile.mount_point
        if not self.is_mounted(profile):
            return True, "Not mounted"

        try:
            result = subprocess.run(
                [_SUDO, _UMOUNT, mp],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout).strip()
                if self._is_sudo_permission_error(err):
                    return False, self._sudo_fix_message()
                return False, f"Unmount failed: {err}"
        except subprocess.TimeoutExpired:
            return False, "Unmount timed out"

        self._active_mounts.pop(profile.label, None)
        # Clean up empty dir
        try:
            os.rmdir(mp)
        except OSError:
            pass
        return True, "Unmounted"

    def unmount_all(self) -> None:
        """Unmount every active mount (call on app exit)."""
        for label in list(self._active_mounts):
            self.unmount(self._active_mounts[label])

    def reconnect_saved(self) -> list[tuple[str, bool, str]]:
        """Mount every profile that has *auto_connect* enabled.

        Called once at startup.  Returns a list of
        ``(label, success, message)`` for each attempted reconnection.
        Profiles that are already mounted are silently skipped.
        """
        results: list[tuple[str, bool, str]] = []
        profiles = self.load_profiles()
        for p in profiles:
            if not p.auto_connect:
                continue
            if self.is_mounted(p):
                results.append((p.label, True, "Already mounted"))
                continue
            ok, msg = self.mount(p)
            results.append((p.label, ok, msg))
            if ok:
                logger.info("Auto-reconnected: %s", p.label)
            else:
                logger.warning("Auto-reconnect failed for %s: %s",
                               p.label, msg)
        return results

    def is_mounted(self, profile: StorageProfile) -> bool:
        """Check if the profile's mount point is actually mounted."""
        mp = profile.mount_point
        try:
            return os.path.ismount(mp)
        except OSError:
            return False

    def test_connection(self, profile: StorageProfile) -> tuple[bool, str]:
        """Quick connectivity test without mounting."""
        if profile.protocol == "smb":
            return self._test_smb(profile)
        return self._test_nfs(profile)

    def get_active_mount_paths(self) -> list[tuple[str, str]]:
        """Return [(label, mount_point), ...] for all active mounts."""
        return [(label, p.mount_point)
                for label, p in self._active_mounts.items()
                if self.is_mounted(p)]

    # ---- Artifact duplicate detection ----------------------------------

    def find_duplicate_iccids(self, profile: StorageProfile,
                              iccids: list[str]) -> list[str]:
        """Check if any *iccids* already appear in artifact CSVs on the share.

        Scans all ``.csv`` files in the profile's artifact sub-directory.
        Returns the subset of *iccids* that were found (i.e. already
        exported).  Returns an empty list if the share is not mounted
        or no duplicates are found.
        """
        if not self.is_mounted(profile):
            return []

        artifact_dir = os.path.join(profile.mount_point,
                                    profile.export_subdir)
        if not os.path.isdir(artifact_dir):
            return []

        iccid_set = set(iccids)
        found: set[str] = set()

        import csv as _csv
        for fname in os.listdir(artifact_dir):
            if not fname.lower().endswith(".csv"):
                continue
            fpath = os.path.join(artifact_dir, fname)
            try:
                with open(fpath, "r", newline="", encoding="utf-8-sig") as fh:
                    reader = _csv.DictReader(fh)
                    for row in reader:
                        val = row.get("ICCID", "").strip()
                        if val in iccid_set:
                            found.add(val)
            except (OSError, UnicodeDecodeError, _csv.Error):
                continue  # skip unreadable files

            # Early exit if we've found all of them
            if found == iccid_set:
                break

        return sorted(found)

    # ---- Sudo / permission helpers --------------------------------------

    _SUDO_ERROR_KEYWORDS = (
        "a terminal is required",
        "askpass helper",
        "sudo: a password is required",
        "no tty present",
        "password is required",
    )

    @classmethod
    def _is_sudo_permission_error(cls, msg: str) -> bool:
        """Return True if *msg* indicates sudo cannot run without a TTY."""
        lower = msg.lower()
        return any(kw in lower for kw in cls._SUDO_ERROR_KEYWORDS)

    @staticmethod
    def _sudo_fix_message() -> str:
        """User-friendly message explaining how to fix sudo permissions."""
        return (
            "SimGUI needs permission to mount network shares.\n\n"
            "Run this once in a terminal to fix it:\n\n"
            "  sudo simgui-setup-mount\n\n"
            "Or manually:\n"
            "  sudo cp /opt/simgui/etc/simgui-mount.sudoers "
            "/etc/sudoers.d/simgui-mount\n"
            "  sudo chmod 0440 /etc/sudoers.d/simgui-mount"
        )

    def check_sudo_mount(self) -> bool:
        """Return True if passwordless sudo mount is available.

        Uses ``sudo -n /usr/bin/mount --help`` to test without prompting.
        Absolute path ensures the sudoers NOPASSWD rule matches.
        """
        try:
            r = subprocess.run(
                [_SUDO, "-n", _MOUNT, "--help"],
                capture_output=True, text=True, timeout=5,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    # ---- Internal helpers ----------------------------------------------

    def _build_mount_cmd(self, profile: StorageProfile) -> list[str]:
        """Build the mount command for the given profile."""
        mp = profile.mount_point
        src = profile.source_path

        if profile.protocol == "nfs":
            opts = profile.mount_options or "soft,timeo=50,retrans=3"
            return [_SUDO, _MOUNT, "-t", "nfs",
                    "-o", opts, src, mp]

        # SMB / CIFS
        opts_parts = [
            f"uid={os.getuid()}",
            f"gid={os.getgid()}",
            "file_mode=0664",
            "dir_mode=0775",
        ]
        if profile.username:
            cred_path = self._cred_file_path(profile.label)
            if os.path.isfile(cred_path):
                opts_parts.append(f"credentials={cred_path}")
            else:
                opts_parts.append(f"username={profile.username}")
                if profile.password:
                    opts_parts.append(f"password={profile.password}")
                if profile.domain:
                    opts_parts.append(f"domain={profile.domain}")
        else:
            opts_parts.append("guest")

        if profile.mount_options:
            opts_parts.append(profile.mount_options)

        return [_SUDO, _MOUNT, "-t", "cifs",
                "-o", ",".join(opts_parts), src, mp]

    def _test_smb(self, profile: StorageProfile) -> tuple[bool, str]:
        """Test SMB connectivity with smbclient."""
        src = profile.source_path
        if profile.username:
            cmd = ["smbclient", src,
                   "-U", f"{profile.username}%{profile.password}"]
            if profile.domain:
                cmd.extend(["-W", profile.domain])
            cmd.extend(["-c", "ls"])
        else:
            cmd = ["smbclient", src, "-N", "-c", "ls"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return True, "Connection successful"
            return False, (r.stderr or r.stdout).strip()[:200]
        except FileNotFoundError:
            return False, "smbclient not installed (apt install smbclient)"
        except subprocess.TimeoutExpired:
            return False, "Connection timed out"

    def _test_nfs(self, profile: StorageProfile) -> tuple[bool, str]:
        """Test NFS connectivity with showmount."""
        try:
            r = subprocess.run(
                ["showmount", "-e", profile.server],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                exports = r.stdout
                if profile.share in exports:
                    return True, "Export found and accessible"
                return False, f"Export '{profile.share}' not listed:\n{exports}"
            return False, (r.stderr or r.stdout).strip()[:200]
        except FileNotFoundError:
            return False, "showmount not installed (apt install nfs-common)"
        except subprocess.TimeoutExpired:
            return False, "Connection timed out"

    # ---- Credential file helpers ---------------------------------------

    def _cred_file_path(self, label: str) -> str:
        safe = label.replace(" ", "_").replace("/", "_")
        return os.path.join(self._cred_dir, f".smb-{safe}")

    def _write_password(self, label: str, username: str, password: str,
                        domain: str = "") -> None:
        """Write an SMB credentials file with 0600 permissions."""
        os.makedirs(self._cred_dir, exist_ok=True)
        path = self._cred_file_path(label)
        lines = [f"username={username}", f"password={password}"]
        if domain:
            lines.append(f"domain={domain}")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError as exc:
            logger.warning("Failed to write credentials to %s: %s", path, exc)

    def _read_password(self, label: str) -> str:
        """Read password from the credentials file, if it exists."""
        path = self._cred_file_path(label)
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r") as fh:
                for line in fh:
                    if line.startswith("password="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            pass
        return ""
