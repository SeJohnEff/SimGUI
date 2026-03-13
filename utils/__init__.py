"""Utility functions for SimGUI."""

import os

from utils.iccid_utils import (
    compute_luhn_check,
    generate_iccid,
    generate_imsi,
    validate_luhn,
)
from utils.network_scanner import DiscoveredServer, list_smb_shares, scan_smb_servers
from utils.validation import validate_adm1, validate_hex_field, validate_iccid, validate_imsi


def get_browse_initial_dir(ns_manager=None, last_dir: str | None = None) -> str | None:
    """Return the best initial directory for file browse dialogs.

    Priority:
    1. *last_dir* — if set and the directory still exists
    2. First active network mount point (if any share is connected)
    3. ``None`` — let tkinter fall back to its own default
    """
    if last_dir and os.path.isdir(last_dir):
        return last_dir
    if ns_manager:
        mounts = ns_manager.get_active_mount_paths()
        if mounts:
            # Return the first active mount's path
            return mounts[0][1]
    return None


__all__ = ['validate_adm1', 'validate_imsi', 'validate_iccid', 'validate_hex_field',
           'compute_luhn_check', 'validate_luhn', 'generate_imsi', 'generate_iccid',
           'DiscoveredServer', 'scan_smb_servers', 'list_smb_shares',
           'get_browse_initial_dir']
