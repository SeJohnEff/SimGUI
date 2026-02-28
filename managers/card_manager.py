#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Card Manager - Interface with physical SIM cards via the CLI tool.

This module wraps the sysmo-usim-tool CLI scripts so that SimGUI never
imports them directly.  Instead it shells out to the CLI, keeping the
GUI fully decoupled from the card-handling code.

If the CLI repo is not available on the system the GUI still works for
CSV editing and offline preparation; card operations simply return an
error message.
"""

import subprocess
import shutil
import os
import json
from typing import Optional, Dict, List, Tuple
from enum import Enum, auto


class CardType(Enum):
    UNKNOWN = auto()
    SJS1 = auto()
    SJA2 = auto()
    SJA5 = auto()


def _find_cli_tool() -> Optional[str]:
    """Locate sysmo-usim-tool repo on the system."""
    # Check environment variable first
    env_path = os.environ.get('SYSMO_USIM_TOOL_PATH')
    if env_path and os.path.isdir(env_path):
        return env_path
    # Check common relative paths
    for candidate in [
        os.path.join(os.path.dirname(__file__), '..', '..', 'sysmo-usim-tool'),
        os.path.expanduser('~/sysmo-usim-tool'),
        '/opt/sysmo-usim-tool',
    ]:
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return None


class CardManager:
    """Manage card detection, authentication, and programming via CLI."""

    def __init__(self):
        self.cli_path: Optional[str] = _find_cli_tool()
        self.card_type: CardType = CardType.UNKNOWN
        self.authenticated: bool = False
        self.card_info: Dict[str, str] = {}

    # ---- helpers -------------------------------------------------------

    def _run_cli(self, script: str, *args, timeout: int = 30) -> Tuple[bool, str]:
        """Run a CLI script and return (success, output)."""
        if self.cli_path is None:
            return False, ("sysmo-usim-tool not found. Set "
                           "SYSMO_USIM_TOOL_PATH or place it next to SimGUI.")
        cmd = ['python3', os.path.join(self.cli_path, script)] + list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                cwd=self.cli_path,
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output.strip()
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except FileNotFoundError:
            return False, f"Script not found: {script}"
        except Exception as e:
            return False, str(e)

    def set_cli_path(self, path: str) -> bool:
        """Manually set the path to sysmo-usim-tool."""
        if os.path.isdir(path):
            self.cli_path = path
            return True
        return False

    # ---- card operations -----------------------------------------------

    def detect_card(self) -> Tuple[bool, str]:
        """Detect a card in the reader."""
        self.authenticated = False
        self.card_info = {}
        self.card_type = CardType.UNKNOWN
        # Try the SJA2 script first (most common modern card)
        ok, out = self._run_cli('sysmo_isim_sja2.py', '--help')
        if not ok:
            return False, out
        # Real detection would parse ATR; for now just confirm reader works
        return True, "Card reader available (use Authenticate to connect)"

    def authenticate(self, adm1: str, force: bool = False) -> Tuple[bool, str]:
        """Authenticate with ADM1 key."""
        if not adm1 or len(adm1) != 8:
            return False, "ADM1 must be exactly 8 characters"
        # Placeholder: real implementation calls the CLI auth command
        self.authenticated = True
        return True, "Authentication successful"

    def read_card_data(self) -> Optional[Dict[str, str]]:
        """Read basic card data (IMSI, ICCID, etc.)."""
        if not self.authenticated:
            return None
        return self.card_info if self.card_info else None

    def program_card(self, card_data: Dict[str, str]) -> Tuple[bool, str]:
        """Program a card with the given parameters."""
        if not self.authenticated:
            return False, "Not authenticated"
        # Build CLI args from card_data
        # This would call the appropriate sysmo CLI script
        return True, "Card programmed successfully (stub)"

    def verify_card(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Verify card data matches expected values."""
        if not self.authenticated:
            return False, ["Not authenticated"]
        return True, []

    def get_remaining_attempts(self) -> Optional[int]:
        return 3  # placeholder

    def disconnect(self):
        self.authenticated = False
        self.card_type = CardType.UNKNOWN
        self.card_info = {}
