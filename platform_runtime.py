"""
Optional platform adapter for SimGUI.

This module provides platform-specific path and command helpers. It is
imported locally (inside the one function that needs it) via try/except
ImportError — never at module scope in any shared manager. Common modules
(card_manager, network_storage_manager, etc.) must remain importable and
fully functional when this file is absent.

Do not add card detection logic, ADM1 logic, CardState references, signal
emissions, or SIM programming logic to this file.
"""

import os
import sys

_MACOS = sys.platform == "darwin"


def pysim_search_dirs() -> list:
    """Directories to search for pySim CLI tools, in priority order."""
    if _MACOS:
        return [os.path.expanduser("~/pysim")]
    return ["/opt/pysim"]


def sysmo_search_dirs() -> list:
    """Directories to search for sysmocom tools, in priority order."""
    return ["/opt/sysmo-usim-tool"]


def config_dir() -> str:
    """Per-user configuration directory for SimGUI."""
    if _MACOS:
        return os.path.expanduser("~/Library/Application Support/simgui")
    return os.path.expanduser("~/.config/simgui")


def mount_cmd_nfs(src: str, dst: str) -> list:
    """Build the mount command for an NFS share."""
    if _MACOS:
        return ["/usr/bin/mount", "-t", "nfs", src, dst]
    return ["mount", "-t", "nfs", src, dst]


def mount_cmd_smb(src: str, dst: str, opts: list) -> list:
    """Build the mount command for an SMB/CIFS share.

    On macOS, credential embedding requires URL-encoded credentials that are
    only available in _build_mount_cmd(). Return [] here so the caller's
    _MACOS branch handles credentials correctly instead.
    """
    if _MACOS:
        return []
    return ["mount", "-t", "cifs", src, dst, *opts]
