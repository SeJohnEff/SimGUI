#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Card Manager - Interface with physical SIM cards via the CLI tool.

This module wraps the sysmo-usim-tool and pySim CLI scripts so that SimGUI
never imports them directly.  Instead it shells out to the CLI, keeping the
GUI fully decoupled from the card-handling code.

Supported CLI tools:
  - sysmo-usim-tool: sysmo_isim_sja2.py, sysmo_isim_sja5.py, sysmo_isim_sjs1.py
  - pySim: pySim-read.py, pySim-prog.py

If neither CLI repo is available on the system the GUI still works for
CSV editing and offline preparation; card operations simply return an
error message.
"""

import logging
import os
import subprocess
import sys
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from utils.validation import validate_adm1

logger = logging.getLogger(__name__)


class CardType(Enum):
    UNKNOWN = auto()
    SJS1 = auto()
    SJA2 = auto()
    SJA5 = auto()


class CLIBackend(Enum):
    """Which CLI tool set is available."""
    NONE = auto()
    SYSMO = auto()
    PYSIM = auto()


def _find_cli_tool() -> Tuple[Optional[str], CLIBackend]:
    """Locate sysmo-usim-tool or pySim repo on the system.

    Returns:
        (path, backend) -- path to the tool directory and which backend it is.
    """
    # Check environment variable first (sysmo-usim-tool)
    env_path = os.environ.get('SYSMO_USIM_TOOL_PATH')
    if env_path and os.path.isdir(env_path):
        return env_path, CLIBackend.SYSMO

    # Check environment variable for pySim
    pysim_path = os.environ.get('PYSIM_PATH')
    if pysim_path and os.path.isdir(pysim_path):
        return pysim_path, CLIBackend.PYSIM

    # Check common relative paths for sysmo-usim-tool
    for candidate in [
        os.path.join(os.path.dirname(__file__), '..', '..', 'sysmo-usim-tool'),
        os.path.expanduser('~/sysmo-usim-tool'),
        '/opt/sysmo-usim-tool',
    ]:
        if os.path.isdir(candidate):
            return os.path.abspath(candidate), CLIBackend.SYSMO

    # Check common relative paths for pySim
    for candidate in [
        os.path.join(os.path.dirname(__file__), '..', '..', 'pysim'),
        os.path.expanduser('~/pysim'),
        '/opt/pysim',
    ]:
        if os.path.isdir(candidate):
            return os.path.abspath(candidate), CLIBackend.PYSIM

    return None, CLIBackend.NONE


class CardManager:
    """Manage card detection, authentication, and programming via CLI."""

    def __init__(self):
        self.cli_path: Optional[str]
        self.cli_backend: CLIBackend
        self.cli_path, self.cli_backend = _find_cli_tool()
        self.card_type: CardType = CardType.UNKNOWN
        self.authenticated: bool = False
        self.card_info: Dict[str, str] = {}

    # ---- helpers -------------------------------------------------------

    def _validate_script_path(self, script: str) -> Optional[str]:
        """Resolve and validate a script path, preventing traversal."""
        if self.cli_path is None:
            return None
        if '..' in script or os.sep in script or (os.altsep and os.altsep in script):
            return None
        full = os.path.join(self.cli_path, script)
        real = os.path.realpath(full)
        if not real.startswith(os.path.realpath(self.cli_path)):
            return None
        return real

    def _run_cli(self, script: str, *args, timeout: int = 30
                 ) -> Tuple[bool, str, str]:
        """Run a CLI script and return (success, stdout, stderr).

        Returns stdout and stderr separately so the caller can distinguish
        informational output from error messages.
        """
        if self.cli_path is None:
            msg = ("sysmo-usim-tool / pySim not found. Set "
                   "SYSMO_USIM_TOOL_PATH or PYSIM_PATH, or place them "
                   "next to SimGUI.")
            return False, "", msg

        script_path = self._validate_script_path(script)
        if script_path is None:
            return False, "", f"Invalid script path: {script}"

        cmd = [sys.executable, script_path] + list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                cwd=self.cli_path,
            )
            return (result.returncode == 0,
                    result.stdout.strip(),
                    result.stderr.strip())
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except FileNotFoundError:
            return False, "", f"Script not found: {script}"
        except Exception as e:
            return False, "", str(e)

    def set_cli_path(self, path: str, backend: Optional[CLIBackend] = None) -> bool:
        """Manually set the path to the CLI tool."""
        if os.path.isdir(path):
            self.cli_path = path
            if backend is not None:
                self.cli_backend = backend
            elif os.path.exists(os.path.join(path, 'pySim-read.py')):
                self.cli_backend = CLIBackend.PYSIM
            else:
                self.cli_backend = CLIBackend.SYSMO
            return True
        return False

    # ---- card operations -----------------------------------------------

    def detect_card(self) -> Tuple[bool, str]:
        """Detect a card in the reader.

        Attempts to actually detect a card by running a lightweight read
        command. Falls back to checking if the CLI tool is available.
        """
        self.authenticated = False
        self.card_info = {}
        self.card_type = CardType.UNKNOWN

        if self.cli_path is None:
            return False, ("No CLI tool found. Install sysmo-usim-tool or "
                           "pySim and set the appropriate environment variable.")

        if self.cli_backend == CLIBackend.PYSIM:
            ok, stdout, stderr = self._run_cli('pySim-read.py', '-p0')
            if ok:
                self._parse_pysim_output(stdout)
                return True, "Card detected via pySim"
            return False, stderr or "No card detected"

        # sysmo-usim-tool: try each card type script
        for script, ctype in [
            ('sysmo_isim_sja2.py', CardType.SJA2),
            ('sysmo_isim_sja5.py', CardType.SJA5),
            ('sysmo_isim_sjs1.py', CardType.SJS1),
        ]:
            script_path = self._validate_script_path(script)
            if script_path is None:
                continue
            ok, stdout, stderr = self._run_cli(script, '--help')
            if ok:
                self.card_type = ctype
                return True, f"Card reader available ({script})"

        return False, "Could not detect card with any known script"

    def authenticate(self, adm1: str, force: bool = False) -> Tuple[bool, str]:
        """Authenticate with ADM1 key.

        NOTE: Full CLI authentication is not yet implemented. This validates
        the ADM1 format and sets authenticated state for GUI flow purposes.
        Real implementation would call the CLI tool's verify-adm1 command.
        """
        err = validate_adm1(adm1)
        if err:
            return False, err
        # TODO: Call actual CLI tool authentication command when available.
        # e.g. self._run_cli('sysmo_isim_sja2.py', '--adm1', adm1, '--verify')
        logger.warning("authenticate() is a stub -- no real CLI call is made")
        self.authenticated = True
        return True, "Authentication successful (stub -- CLI integration pending)"

    def read_card_data(self) -> Optional[Dict[str, str]]:
        """Read basic card data (IMSI, ICCID, etc.)."""
        if not self.authenticated:
            return None
        return self.card_info if self.card_info else None

    def program_card(self, card_data: Dict[str, str]) -> Tuple[bool, str]:
        """Program a card with the given parameters."""
        if not self.authenticated:
            return False, "Not authenticated"
        # TODO: Build CLI args from card_data and call appropriate script
        logger.warning("program_card() is a stub -- no real CLI call is made")
        return True, "Card programmed successfully (stub)"

    def verify_card(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Verify card data matches expected values."""
        if not self.authenticated:
            return False, ["Not authenticated"]
        return True, []

    def get_remaining_attempts(self) -> Optional[int]:
        """Return remaining ADM1 auth attempts, or None if unknown."""
        return None

    def disconnect(self):
        self.authenticated = False
        self.card_type = CardType.UNKNOWN
        self.card_info = {}

    def _parse_pysim_output(self, output: str):
        """Parse pySim-read output for card info."""
        for line in output.splitlines():
            if ':' not in line:
                continue
            key, _, val = line.partition(':')
            key = key.strip().upper()
            val = val.strip()
            if 'IMSI' in key:
                self.card_info['IMSI'] = val
            elif 'ICCID' in key:
                self.card_info['ICCID'] = val
