"""
Optional platform adapter for SimGUI.

This module provides platform-specific path and command helpers. It is
imported locally (inside the one function that needs it) via try/except
ImportError — never at module scope in any shared manager. Common modules
(card_manager, network_storage_manager, etc.) must remain importable and
fully functional when this file is absent.

Current state (S2-A stub): all functions return their correct Linux/Ubuntu
values. macOS-specific values are added in S2-E after the Linux contract is
locked and wired. Do not add card detection logic, ADM1 logic, CardState
references, signal emissions, or SIM programming logic to this file.
"""

import os


def pysim_search_dirs() -> list:
    """Directories to search for pySim CLI tools, in priority order."""
    return ["/opt/pysim"]


def sysmo_search_dirs() -> list:
    """Directories to search for sysmocom tools, in priority order."""
    return ["/opt/sysmo-usim-tool"]


def config_dir() -> str:
    """Per-user configuration directory for SimGUI."""
    return os.path.expanduser("~/.config/simgui")


def mount_cmd_nfs(src: str, dst: str) -> list:
    """Build the mount command for an NFS share."""
    return ["mount", "-t", "nfs", src, dst]


def mount_cmd_smb(src: str, dst: str, opts: list) -> list:
    """Build the mount command for an SMB/CIFS share."""
    return ["mount", "-t", "cifs", src, dst, *opts]
