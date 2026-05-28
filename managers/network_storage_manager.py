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
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

MOUNT_BASE = "/tmp/simgui-mounts"

# Platform detection — used only in this module for mount command assembly
# and sudo permission checking.  All SIM card logic, authentication, and
# state machine code is platform-free; this is the thin adapter boundary.
_MACOS = sys.platform == "darwin"

# Absolute paths for system commands — critical for desktop-launcher
# environments where PATH may not include /usr/bin or sudo's
# secure_path may differ.  The sudoers NOPASSWD rule references
# these exact paths, so using bare 'mount' could fail to match.
_SUDO = "/usr/bin/sudo"
_MOUNT = "/usr/bin/mount"
_UMOUNT = "/usr/bin/umount"
# SMB mount binary differs by platform:
#   macOS  → /sbin/mount_smbfs  (built-in, URL-based credential syntax)
#   Linux  → /usr/bin/mount     (used with -t cifs and -o options)
_MOUNT_SMB_FS = "/sbin/mount_smbfs" if _MACOS else "/usr/bin/mount"

# macOS umount path (setuid; usable without sudo for user-owned mounts)
_UMOUNT_MACOS = "/sbin/umount"


def _mask_smb_url(cmd: list) -> list:
    """Return cmd with any SMB password in URLs replaced by ***."""
    return [re.sub(r"(//[^:]+:)[^@]+(@)", r"\1***\2", str(part)) for part in cmd]


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
    # Last-used: True on the profile the user most recently connected.
    # Exactly one profile must have this set at any time; reconnect_saved()
    # attempts only this profile on startup.  mark_last_used() maintains
    # the invariant by clearing all other profiles when it sets this flag.
    last_used: bool = False

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
        # Maps label → actual OS mount path when it differs from profile.mount_point
        # (e.g. /Volumes/SIM for a Finder mount vs /tmp/simgui-mounts/SIM).
        self._actual_mount_paths: dict[str, str] = {}
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

    def validate_label_unique(
        self, label: str, exclude_label: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Return (True, "") if *label* is not used by any other saved profile.

        Parameters
        ----------
        label :
            The label the user wants to use.
        exclude_label :
            When editing an existing profile, pass its current label so that
            re-saving the same profile under the same name is allowed.

        Returns (False, error_message) if another saved profile already uses
        *label*.
        """
        for p in self.load_profiles():
            if p.label == label and p.label != exclude_label:
                return False, "Label has to be unique. Label/name already used."
        return True, ""

    def get_last_used_label(self) -> Optional[str]:
        """Return the label of the profile with last_used=True, or None.

        Scans saved profiles; the flag lives on the profile itself so no
        separate settings key is required.  Returns None when no profile
        has last_used=True (fresh install, legacy settings, or all profiles
        deleted).
        """
        for p in self.load_profiles():
            if p.last_used:
                return p.label
        return None

    def mark_last_used(self, label: str) -> None:
        """Set last_used=True on *label*; clear it on every other profile.

        Persists immediately so the choice survives an app restart.  Call
        after a successful Save & Connect so that startup auto-connect
        prefers this profile on next launch.
        """
        profiles = self.load_profiles()
        for p in profiles:
            p.last_used = (p.label == label)
        self.save_profiles(profiles)

    def delete_profile(self, label: str) -> tuple[bool, str]:
        """Remove a saved profile by label.

        Refuses if the profile is currently active (mounted), because an
        in-flight mount state would be left orphaned.

        On success: removes the settings entry and deletes the credential file.
        If the deleted profile had last_used=True, that flag disappears with
        it — no other profile gains it, and reconnect_saved() will find no
        last_used profile and perform no auto-connect on next startup.
        """
        if label in self._active_mounts:
            return False, "Cannot delete a connected share. Disconnect first."
        profiles = [p for p in self.load_profiles() if p.label != label]
        self.save_profiles(profiles)
        cred = self._cred_file_path(label)
        try:
            if os.path.isfile(cred):
                os.remove(cred)
        except OSError as exc:
            logger.warning("Failed to delete credential file %s: %s", cred, exc)
        return True, f"Profile '{label}' deleted."

    # ---- Mount / unmount -----------------------------------------------

    def mount(self, profile: StorageProfile) -> tuple[bool, str]:
        """Mount the share.  Returns (success, message).

        If the share is already mounted (e.g. left from a previous
        session), we still track it in ``_active_mounts`` so that
        ``get_active_mount_paths`` returns it.
        """
        mp = profile.mount_point

        # Clear stale internal state: tracked as mounted but OS disagrees.
        # Happens after sleep/wake when the SMB VFS entry disappears silently.
        if profile.label in self._active_mounts and not self.is_mounted(profile):
            self._active_mounts.pop(profile.label, None)
            self._actual_mount_paths.pop(profile.label, None)
            logger.info("mount: cleared stale internal tracking for %s", profile.label)

        if self.is_mounted(profile):
            # OS reports a live mount — verify it is actually accessible before trusting it.
            # Stale VFS entries after sleep/wake report ismount=True but block on I/O.
            if self.verify_mount_accessible(profile):
                self._active_mounts[profile.label] = profile
                return True, f"Already mounted at {mp}"
            # Stale OS mount: clear internal state and attempt a force-umount.
            self._active_mounts.pop(profile.label, None)
            self._actual_mount_paths.pop(profile.label, None)
            logger.info("mount: stale OS mount for %s at %s, attempting cleanup",
                        profile.label, mp)
            try:
                _umount_stale = [_UMOUNT_MACOS, mp] if _MACOS else [_SUDO, _UMOUNT, mp]
                subprocess.run(_umount_stale, capture_output=True, text=True, timeout=10,
                               stdin=subprocess.DEVNULL)
            except Exception:
                pass
            # Fall through to fresh mount attempt.

        # Handle stale mount-point directory that may remain after a dead SMB mount
        # is cleaned up by the OS (e.g. after sleep/wake with VFS entry already gone).
        if os.path.exists(mp) and not os.path.ismount(mp):
            try:
                entries = os.listdir(mp)
            except OSError as exc:
                return False, f"Cannot inspect mount point '{mp}': {exc}"
            if entries:
                return False, (
                    f"Mount point '{mp}' exists with content but is not mounted. "
                    f"Remove it manually to reconnect."
                )
            try:
                os.rmdir(mp)
            except OSError as exc:
                return False, f"Cannot clear stale mount point '{mp}': {exc}"

        os.makedirs(mp, exist_ok=True)

        # macOS: mount_smbfs will prompt the terminal if username is set
        # but no password is provided.  Fail early instead.
        if _MACOS and profile.protocol == "smb" and profile.username and not profile.password:
            return False, (
                "Password required: username is set but password is blank.\n"
                "Enter the password in the Password field."
            )

        try:
            cmd = self._build_mount_cmd(profile)
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout).strip()
                if self._is_sudo_permission_error(err):
                    return False, self._sudo_fix_message()
                if "File exists" in err or "already mounted" in err.lower():
                    # The OS reports the mount point is already occupied —
                    # either a stale VFS entry that os.path.ismount() missed,
                    # or a Finder/OS mount at a different path (e.g. /Volumes/SIM).
                    # Find the actual mount path and probe accessibility there.
                    if _MACOS:
                        actual, adoption_err = self._macos_find_smb_mount_for_adoption(profile)
                        if adoption_err:
                            # Attempt explicit mount to our own mountpoint before refusing.
                            # macOS may allow a second connection with different credentials
                            # even when the share is already mounted by another user.
                            cmd2 = self._build_mount_cmd(profile)
                            result2 = subprocess.run(
                                cmd2, capture_output=True, text=True, timeout=30,
                                stdin=subprocess.DEVNULL,
                            )
                            if result2.returncode == 0:
                                self._active_mounts[profile.label] = profile
                                logger.info("mount: explicit mount succeeded for %s at %s "
                                            "after adoption refusal", profile.label, mp)
                                return True, f"Mounted at {mp}"
                            self._active_mounts.pop(profile.label, None)
                            return False, adoption_err
                    else:
                        actual = None
                    check_path = actual if actual else mp
                    if self._check_path_accessible(check_path):
                        if actual and actual != mp:
                            self._actual_mount_paths[profile.label] = actual
                        self._active_mounts[profile.label] = profile
                        logger.info("mount: adopted existing mount for %s at %s",
                                    profile.label, check_path)
                        return True, f"Mounted (adopted existing) at {check_path}"
                    self._active_mounts.pop(profile.label, None)
                    return False, (
                        f"Mount failed (stale or conflicting mount — "
                        f"unmount manually and retry): {err}"
                    )
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
            # Stale tracking: OS mount is gone but internal state still lists
            # this profile as active.  Clear both tracking dicts so that
            # delete_profile() and is_tracked_as_mounted() see the correct state.
            self._active_mounts.pop(profile.label, None)
            self._actual_mount_paths.pop(profile.label, None)
            return True, "Not mounted"

        try:
            # macOS: mount_smbfs is user-executable (no sudo needed); sudo would
            # open /dev/tty to prompt for a password even with stdin=DEVNULL.
            cmd = [_UMOUNT_MACOS, mp] if _MACOS else [_SUDO, _UMOUNT, mp]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout).strip()
                if not _MACOS and self._is_sudo_permission_error(err):
                    return False, self._sudo_fix_message()
                return False, f"Unmount failed: {err}"
        except subprocess.TimeoutExpired:
            return False, "Unmount timed out"

        self._active_mounts.pop(profile.label, None)
        self._actual_mount_paths.pop(profile.label, None)
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
        """Mount the single profile with ``last_used=True``, if any.

        Called once at startup.  Returns a list of
        ``(label, success, message)`` with at most one entry.

        Policy:
        - If exactly one profile has ``last_used=True``, attempt to connect it.
        - If none has ``last_used=True``, return [] (no auto-connect).
        - If more than one has ``last_used=True`` (settings corruption),
          keep the first in saved order, clear the rest, persist, then
          attempt the first one.

        After a successful mount (including stale OS mounts), the share is
        probed for actual accessibility.  If unreachable, the profile is
        removed from *_active_mounts* and reported as failed — green status
        requires a verified live connection, not just a VFS mount entry.
        """
        results: list[tuple[str, bool, str]] = []
        profiles = self.load_profiles()
        if not profiles:
            return results

        last_used = [p for p in profiles if p.last_used]
        if len(last_used) > 1:
            # Normalize: more than one last_used=True is invalid.
            for p in last_used[1:]:
                p.last_used = False
            self.save_profiles(profiles)
            last_used = last_used[:1]

        if not last_used:
            return results

        p = last_used[0]
        ok, msg = self.mount(p)
        if ok and not self.verify_mount_accessible(p):
            self._active_mounts.pop(p.label, None)
            ok = False
            msg = "Share not accessible (network unreachable)"
            logger.warning("Auto-connect: %s mounted but inaccessible, "
                           "marking disconnected", p.label)
        results.append((p.label, ok, msg))
        if ok:
            logger.info("Auto-reconnected: %s", p.label)
        else:
            logger.warning("Auto-reconnect failed for %s: %s", p.label, msg)
        return results

    def is_mounted(self, profile: StorageProfile) -> bool:
        """Check if the profile's mount point is actually mounted."""
        mp = profile.mount_point
        try:
            return os.path.ismount(mp)
        except OSError:
            return False

    def is_tracked_as_mounted(self, profile: StorageProfile) -> bool:
        """Return True if this profile is tracked as mounted in memory.

        Does NOT perform any filesystem or OS-level check — safe to call
        on the UI thread where blocking stat() calls must be avoided.
        """
        return profile.label in self._active_mounts

    def verify_mount_accessible(self, profile: StorageProfile,
                                timeout: int = 5) -> bool:
        """Return True if the mounted share is actually accessible.

        Runs a short-lived subprocess to probe the mount point with a
        bounded timeout.  A stale OS mount (server unreachable) causes
        the filesystem call inside the subprocess to block; killing the
        subprocess after *timeout* seconds is the only portable way to
        escape a hung VFS stat.  Returns False on timeout or any error.
        """
        mp = profile.mount_point
        try:
            result = subprocess.run(
                ["/bin/ls", mp], capture_output=True, timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning("verify_mount_accessible: timeout probing %s", mp)
            return False
        except Exception as exc:
            logger.warning("verify_mount_accessible: error probing %s: %s",
                           mp, exc)
            return False

    def test_connection(self, profile: StorageProfile) -> tuple[bool, str]:
        """Quick connectivity test without mounting."""
        if profile.protocol == "smb":
            return self._test_smb(profile)
        return self._test_nfs(profile)

    def sync_os_mounts(self) -> None:
        """Populate ``_active_mounts`` for profiles that are mounted at
        the OS level but were not explicitly mounted by this session.

        This covers the case where a share was left mounted from a
        previous session or was mounted externally.  Without this,
        ``get_active_mount_paths`` would return nothing and the UI
        share indicator would stay grey.

        Stale OS mounts (VFS entry present but server unreachable) are
        detected via ``verify_mount_accessible`` and silently skipped —
        they must not contribute to the connected (green) status.
        """
        for p in self.load_profiles():
            if p.label in self._active_mounts:
                continue  # already tracked
            if self.is_mounted(p):
                if not self.verify_mount_accessible(p):
                    logger.info("sync_os_mounts: %s is OS-mounted but "
                                "inaccessible, skipping", p.label)
                    continue
                self._active_mounts[p.label] = p
                logger.info("sync_os_mounts: adopted existing mount %s",
                            p.label)
            elif _MACOS and p.protocol == "smb":
                # Check for Finder/OS mounts at non-SimGUI paths (e.g. /Volumes/SIM).
                # Validates username before adopting to prevent cross-user mount
                # adoption (e.g. Finder's johneff@ mount adopted for simgui profile).
                actual, adoption_err = self._macos_find_smb_mount_for_adoption(p)
                if adoption_err:
                    logger.warning("sync_os_mounts: refused adoption for %s: %s",
                                   p.label, adoption_err)
                elif actual and self._check_path_accessible(actual):
                    self._actual_mount_paths[p.label] = actual
                    self._active_mounts[p.label] = p
                    logger.info("sync_os_mounts: adopted Finder/OS mount %s "
                                "at %s", p.label, actual)

    def get_active_mount_paths(self) -> list[tuple[str, str]]:
        """Return [(label, mount_point), ...] for all active mounts.

        Uses the actual OS path (e.g. /Volumes/SIM) when the share was
        adopted from a Finder/OS mount rather than SimGUI's own mount point.
        """
        result = []
        for label, p in self._active_mounts.items():
            path = self._actual_mount_paths.get(label, p.mount_point)
            try:
                if os.path.ismount(path):
                    result.append((label, path))
            except OSError:
                pass
        return result

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
        """Return a user-friendly message explaining how to fix sudo permissions.

        The message is platform-specific:
        - macOS: instructs the user to check admin group membership and use
          Finder as an alternative.
        - Linux: instructs the user to run ``simgui-setup-mount`` to install
          the sudoers drop-in rule.
        """
        if _MACOS:
            return (
                "SimGUI needs permission to mount network shares.\n\n"
                "On macOS, you may need to:\n"
                "  1. Unlock System Settings > General > Login Items & Extensions\n"
                "  2. Add yourself to the 'admin' group if needed\n"
                "  3. Ensure mount_smbfs is available: /sbin/mount_smbfs --help\n\n"
                "Or use native Finder: Cmd+K > 'smb://server/share'"
            )
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

        Platform behaviour:
        - macOS: always returns True.  ``mount_smbfs`` requires sudo, but
          macOS grants passwordless sudo to members of the ``admin`` group
          by default, so no sudoers drop-in file is needed.
        - Linux: checks for the ``/etc/sudoers.d/simgui-mount`` drop-in
          rule installed by ``simgui-setup-mount``.  Returns False if the
          file is absent, indicating the user must run the setup command.
        """
        if _MACOS:
            # macOS admin users have sudo by default — no sudoers file needed
            return True
        sudoers_path = '/etc/sudoers.d/simgui-mount'
        try:
            return os.path.isfile(sudoers_path)
        except OSError:
            return False

    # ---- Internal helpers ----------------------------------------------

    def _check_path_accessible(self, path: str, timeout: int = 5) -> bool:
        """Return True if *path* is accessible via a bounded subprocess probe.

        Path-based variant of ``verify_mount_accessible`` — accepts any path,
        not just a profile's own mount point.  Used when the actual OS mount
        path differs from ``profile.mount_point`` (e.g. /Volumes/SIM).
        """
        try:
            result = subprocess.run(
                ["/bin/ls", path], capture_output=True, timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning("_check_path_accessible: timeout probing %s", path)
            return False
        except Exception as exc:
            logger.warning("_check_path_accessible: error probing %s: %s",
                           path, exc)
            return False

    def _build_mount_cmd(self, profile: StorageProfile) -> list[str]:
        """Build the OS-level mount command for the given profile.

        Returns a list suitable for ``subprocess.run``.  Three paths:

        NFS (both platforms):
            ``sudo mount -t nfs -o <opts> server:/path /mountpoint``

        SMB on macOS:
            ``sudo mount_smbfs [-o <opts>] //[user[:pass]@]server/share /mountpoint``
            Credentials are embedded in the URL using percent-encoding.
            No ``-t cifs``, no ``uid=``/``gid=`` options.

        SMB on Linux (CIFS):
            ``sudo mount -t cifs -o uid=…,gid=…,credentials=…,… //server/share /mountpoint``
            Credentials are passed via a 0600 credentials file when one
            exists for this profile label; otherwise inline username=/password=.
        """
        mp = profile.mount_point
        src = profile.source_path

        if profile.protocol == "nfs":
            opts = profile.mount_options or "soft,timeo=50,retrans=3"
            # platform_runtime hook: use when it returns an absolute-path command.
            # The Ubuntu stub returns bare "mount" (relative) so the guard always
            # falls through, preserving v0.5.50 NFS behavior unchanged on Linux.
            try:
                import platform_runtime as _pr
                _base = _pr.mount_cmd_nfs(src, mp)
                if isinstance(_base, list) and len(_base) >= 4 and os.path.isabs(_base[0]):
                    # Splice -o opts before the trailing [src, mountpoint].
                    return [_SUDO] + _base[:-2] + ["-o", opts] + _base[-2:]
            except Exception:
                pass
            return [_SUDO, _MOUNT, "-t", "nfs",
                    "-o", opts, src, mp]

        # SMB / CIFS — command structure differs by platform.
        #
        # Compute CIFS options before the platform_runtime probe so they are
        # available to both the hook call and the Linux fallback.  The
        # computation is side-effect-free and harmless when run on macOS even
        # though the macOS branch below does not use opts_parts.
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

        # platform_runtime hook: use when it returns an absolute-path command.
        # The Ubuntu stub returns bare "mount" (relative) so the guard always
        # falls through, preserving v0.5.50 SMB behavior unchanged on Linux and
        # macOS.  In S2-E, platform_runtime returns an absolute-path macOS
        # command (e.g. /sbin/mount_smbfs) and the hook takes effect.
        try:
            import platform_runtime as _pr
            _cmd = _pr.mount_cmd_smb(src, mp, ["-o", ",".join(opts_parts)])
            if isinstance(_cmd, list) and _cmd and os.path.isabs(_cmd[0]):
                return [_SUDO] + _cmd
        except Exception:
            pass

        if _MACOS:
            # macOS: mount_smbfs //[user[:password]@]server/share mountpoint
            # mount_smbfs is user-executable (no sudo needed); sudo would
            # open /dev/tty to prompt for a password even with stdin=DEVNULL.
            url = self._smb_url(profile)
            cmd = [_MOUNT_SMB_FS]
            if profile.mount_options:
                cmd.extend(["-o", profile.mount_options])
            cmd.extend([url, mp])
            logger.debug("SMB mount cmd: %s", _mask_smb_url(cmd))
            return cmd

        # Linux CIFS: mount -t cifs with uid/gid/credentials options
        return [_SUDO, _MOUNT_SMB_FS, "-t", "cifs",
                "-o", ",".join(opts_parts), src, mp]

    def _test_smb(self, profile: StorageProfile) -> tuple[bool, str]:
        """Test SMB connectivity.

        macOS: probes TCP port 445 using stdlib socket — no smbclient needed.
        Linux: uses smbclient for a full auth/listing test.
        """
        if _MACOS:
            return self._test_smb_macos(profile)
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

    def _macos_find_smb_mount(self, profile: StorageProfile) -> Optional[str]:
        """Return the path where the SMB share is already mounted, or None.

        Checks our own profile mount point first, then the system mount list
        for any path mounting ``//server/share`` — e.g. a Finder connection.
        """
        if os.path.ismount(profile.mount_point):
            return profile.mount_point
        share = profile.share.strip("/")
        server = profile.server
        try:
            r = subprocess.run(
                ["/sbin/mount"], capture_output=True, text=True, timeout=5,
                stdin=subprocess.DEVNULL,
            )
            for line in r.stdout.splitlines():
                # Format: //[user@]server/share on /mountpoint (smbfs, ...)
                if f"{server}/{share}" in line and " on " in line:
                    mp = line.split(" on ", 1)[1].split(" ")[0]
                    if mp and os.path.isdir(mp):
                        return mp
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_smb_url_username(mount_line: str) -> Optional[str]:
        """Extract the username from a macOS SMB mount line.

        Parses lines of the form ``//[user@]server/share on /mountpoint (...)``.
        Returns the username string when an ``@``-prefixed user is present,
        or ``None`` when the URL has no user component (anonymous/guest or
        username cannot be determined).
        """
        m = re.match(r'(//[^ ]+)\s+on\s+', mount_line)
        if not m:
            return None
        url = m.group(1)
        # Capture user-info before the @: may be "user" or "user:password"
        user_match = re.match(r'//([^@/]+)@', url)
        if user_match:
            # Strip any embedded password ("user:pass" → "user")
            return user_match.group(1).split(":", 1)[0]
        return None

    def _macos_find_smb_mount_for_adoption(
        self, profile: StorageProfile,
    ) -> tuple[Optional[str], Optional[str]]:
        """Find an existing macOS SMB mount and validate username before adoption.

        Returns ``(path, None)`` when a mount is found and the username check
        passes (or no username check is required).
        Returns ``(None, error_message)`` when a mount is found but a username
        mismatch prevents safe adoption — caller must NOT update
        ``_active_mounts`` or ``_actual_mount_paths``.
        Returns ``(None, None)`` when no existing mount is found at all.
        """
        if os.path.ismount(profile.mount_point):
            # SimGUI's own mount point — credentials were ours, no check needed.
            return profile.mount_point, None
        share = profile.share.strip("/")
        server = profile.server
        try:
            r = subprocess.run(
                ["/sbin/mount"], capture_output=True, text=True, timeout=5,
                stdin=subprocess.DEVNULL,
            )
            for line in r.stdout.splitlines():
                if f"{server}/{share}" in line and " on " in line:
                    mp = line.split(" on ", 1)[1].split(" ")[0]
                    if not mp or not os.path.isdir(mp):
                        continue
                    if profile.username:
                        mount_username = self._parse_smb_url_username(line)
                        if mount_username is None:
                            return None, (
                                "Share is already mounted by an unknown user. "
                                "Disconnect that mount, use matching credentials, "
                                "or choose to use the existing mount."
                            )
                        if mount_username != profile.username:
                            return None, (
                                f"Share is already mounted as {mount_username}. "
                                "Disconnect that mount, use matching credentials, "
                                "or choose to use the existing mount."
                            )
                    return mp, None
        except Exception:
            pass
        return None, None

    def _test_smb_macos(self, profile: StorageProfile) -> tuple[bool, str]:
        """Test SMB connectivity and authentication on macOS.

        1. Returns success immediately if the share is already mounted anywhere
           (our own mount point or a Finder connection).
        2. Fails early if username is set but password is blank.
        3. Performs a temporary mount using URL-encoded credentials to verify
           both reachability and authentication.  No smbclient required.

        mount_smbfs is user-executable on macOS; no sudo wrapper is used so
        that sudo never opens /dev/tty to prompt for a password.
        """
        existing = self._macos_find_smb_mount(profile)
        if existing:
            return True, f"Share already mounted at {existing}"

        if profile.username and not profile.password:
            return False, (
                "Password required: username is set but password is blank.\n"
                "Enter the password in the Password field."
            )
        tmp_mp = tempfile.mkdtemp(prefix="simgui-test-")
        try:
            url = self._smb_url(profile)
            cmd = [_MOUNT_SMB_FS]
            if profile.mount_options:
                cmd.extend(["-o", profile.mount_options])
            cmd.extend([url, tmp_mp])
            logger.debug("Test mount cmd: %s", _mask_smb_url(cmd))
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                subprocess.run(
                    [_UMOUNT_MACOS, tmp_mp],
                    capture_output=True, timeout=10,
                    stdin=subprocess.DEVNULL,
                )
                return True, "Connection and authentication successful"
            err = (result.stderr or result.stdout).strip()[:200]
            return False, f"Authentication failed: {err or 'mount_smbfs rejected credentials'}"
        except subprocess.TimeoutExpired:
            return False, "Connection timed out (15 s)"
        except FileNotFoundError as exc:
            return False, f"mount_smbfs not found: {exc}"
        finally:
            try:
                os.rmdir(tmp_mp)
            except OSError:
                pass

    def _smb_url(self, profile: StorageProfile) -> str:
        """Build the //[user[:password]@]server/share URL for mount_smbfs."""
        share = profile.share.lstrip("/")
        if profile.username:
            user = quote(profile.username, safe="")
            if profile.password:
                pwd = quote(profile.password, safe="")
                return f"//{user}:{pwd}@{profile.server}/{share}"
            return f"//{user}@{profile.server}/{share}"
        return f"//{profile.server}/{share}"

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
