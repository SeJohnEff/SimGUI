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
import time
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from utils.validation import validate_adm1

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pyscard (smartcard) lazy import
# ---------------------------------------------------------------------------
# pyscard lives in the pySim venv.  We add its site-packages to sys.path
# once so subsequent imports work in-process - no subprocess needed.

_pyscard_available: Optional[bool] = None
_smartcard_readers = None     # smartcard.System.readers
_NoCardException = None       # smartcard.Exceptions.NoCardException
_CardConnectionException = None


def _init_pyscard(venv_python: Optional[str] = None) -> bool:
    """Try to import pyscard, adding venv site-packages if needed.

    Returns True if pyscard is usable.
    """
    global _pyscard_available, _smartcard_readers
    global _NoCardException, _CardConnectionException

    if _pyscard_available is not None:
        return _pyscard_available

    # First try a direct import (works if pyscard is on the system)
    try:
        from smartcard.System import readers as _r
        from smartcard.Exceptions import (
            NoCardException as _nc,
            CardConnectionException as _cc,
        )
        _smartcard_readers = _r
        _NoCardException = _nc
        _CardConnectionException = _cc
        _pyscard_available = True
        logger.info("pyscard available (system)")
        return True
    except ImportError:
        pass

    # Try adding the venv site-packages to sys.path
    if venv_python:
        venv_dir = os.path.dirname(os.path.dirname(venv_python))  # .venv/
        import glob as _glob
        patterns = [
            os.path.join(venv_dir, 'lib', 'python*', 'site-packages'),
            os.path.join(venv_dir, 'lib64', 'python*', 'site-packages'),
        ]
        for pat in patterns:
            for sp in _glob.glob(pat):
                if sp not in sys.path:
                    sys.path.insert(0, sp)
                    logger.info("Added venv site-packages: %s", sp)

        try:
            from smartcard.System import readers as _r
            from smartcard.Exceptions import (
                NoCardException as _nc,
                CardConnectionException as _cc,
            )
            _smartcard_readers = _r
            _NoCardException = _nc
            _CardConnectionException = _cc
            _pyscard_available = True
            logger.info("pyscard available (venv)")
            return True
        except ImportError:
            pass

    _pyscard_available = False
    logger.info("pyscard not available")
    return False


class CardType(Enum):
    UNKNOWN = auto()
    SJS1 = auto()
    SJA2 = auto()
    SJA5 = auto()
    GIALERSIM = auto()


class CLIBackend(Enum):
    """Which CLI tool set is available."""
    NONE = auto()
    SYSMO = auto()
    PYSIM = auto()
    SIMULATOR = auto()


def _find_venv_python(tool_path: str) -> Optional[str]:
    """Find the venv Python interpreter for a CLI tool directory.

    Checks for a virtual environment inside the tool directory and returns
    the path to its Python interpreter.  Falls back to None (meaning use
    sys.executable) when no venv is present.
    """
    for venv_dir in ['.venv', 'venv', '.env', 'env']:
        candidate = os.path.join(tool_path, venv_dir, 'bin', 'python')
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            logger.info("Found venv Python at %s", candidate)
            return candidate
    # Also check for a python3 symlink
    for venv_dir in ['.venv', 'venv', '.env', 'env']:
        candidate = os.path.join(tool_path, venv_dir, 'bin', 'python3')
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            logger.info("Found venv Python3 at %s", candidate)
            return candidate
    return None


def _find_cli_tool() -> Tuple[Optional[str], CLIBackend]:
    """Locate sysmo-usim-tool or pySim repo on the system.

    Returns:
        (path, backend) -- path to the tool directory and which backend it is.
    """
    # Check environment variable first (sysmo-usim-tool)
    env_path = os.environ.get('SYSMO_USIM_TOOL_PATH')
    if env_path and os.path.isdir(env_path):
        logger.info("Found sysmo-usim-tool via env var: %s", env_path)
        return env_path, CLIBackend.SYSMO

    # Check environment variable for pySim
    pysim_path = os.environ.get('PYSIM_PATH')
    if pysim_path and os.path.isdir(pysim_path):
        logger.info("Found pySim via env var: %s", pysim_path)
        return pysim_path, CLIBackend.PYSIM

    # Check common relative paths for sysmo-usim-tool
    for candidate in [
        os.path.join(os.path.dirname(__file__), '..', '..', 'sysmo-usim-tool'),
        os.path.expanduser('~/sysmo-usim-tool'),
        '/opt/sysmo-usim-tool',
    ]:
        if os.path.isdir(candidate):
            logger.info("Found sysmo-usim-tool at %s", candidate)
            return os.path.abspath(candidate), CLIBackend.SYSMO

    # Check common relative paths for pySim
    for candidate in [
        os.path.join(os.path.dirname(__file__), '..', '..', 'pysim'),
        os.path.expanduser('~/pysim'),
        '/opt/pysim',
    ]:
        if os.path.isdir(candidate):
            logger.info("Found pySim at %s", candidate)
            return os.path.abspath(candidate), CLIBackend.PYSIM

    logger.warning("No CLI tool found (sysmo-usim-tool or pySim)")
    return None, CLIBackend.NONE


class CardManager:
    """Manage card detection, authentication, and programming via CLI."""

    # ADM1 key reference byte for VERIFY APDU on SIM/USIM cards.
    # Standard value for sysmocom cards (ETSI TS 102.221, key ref 0x0A).
    _ADM1_KEY_REF = 0x0A

    def __init__(self):
        self.cli_path: Optional[str]
        self.cli_backend: CLIBackend
        self.cli_path, self.cli_backend = _find_cli_tool()
        self._venv_python: Optional[str] = None
        if self.cli_path:
            self._venv_python = _find_venv_python(self.cli_path)
        self.card_type: CardType = CardType.UNKNOWN
        self.authenticated: bool = False
        self.card_info: Dict[str, str] = {}
        self._authenticated_adm1_hex: Optional[str] = None
        self._original_card_data: Dict[str, str] = {}  # snapshot at detect time
        self._simulator = None  # Optional[SimulatorBackend]
        self.card_blocked: bool = False   # True when ADM1 retry counter = 0
        self._adm1_remaining_attempts: Optional[int] = None
        self._safety_override_acknowledged: bool = False  # Set by authenticate(force=True)
        logger.info("CardManager init: backend=%s, cli_path=%s, venv_python=%s",
                    self.cli_backend.name, self.cli_path, self._venv_python)

    # ---- simulator ---------------------------------------------------------

    def enable_simulator(self, settings=None):
        """Enable the simulator backend."""
        from simulator import SimulatorBackend, SimulatorSettings
        self._simulator = SimulatorBackend(settings or SimulatorSettings())
        self.disconnect()

    def disable_simulator(self):
        """Disable the simulator backend; revert to hardware/CLI."""
        self._simulator = None
        self.disconnect()

    @property
    def is_simulator_active(self) -> bool:
        return self._simulator is not None

    def next_virtual_card(self) -> Optional[Tuple[int, int]]:
        if self._simulator:
            return self._simulator.next_card()
        return None

    def previous_virtual_card(self) -> Optional[Tuple[int, int]]:
        if self._simulator:
            return self._simulator.previous_card()
        return None

    def get_simulator_info(self) -> Optional[Dict]:
        if self._simulator is None:
            return None
        card = self._simulator._current_card()
        return {
            "current_index": self._simulator.current_card_index,
            "total_cards": len(self._simulator.card_deck),
            "card": card.get_current_data() if card else None,
            "card_type": card.card_type if card else None,
        }

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

        python_exe = self._venv_python or sys.executable
        cmd = [python_exe, script_path] + list(args)
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
            self._venv_python = _find_venv_python(path)
            if backend is not None:
                self.cli_backend = backend
            elif os.path.exists(os.path.join(path, 'pySim-read.py')):
                self.cli_backend = CLIBackend.PYSIM
            else:
                self.cli_backend = CLIBackend.SYSMO
            logger.info("CLI path set to %s (backend=%s, venv=%s)",
                        path, self.cli_backend.name, self._venv_python)
            return True
        return False

    # ---- card presence (fast, no pySim) --------------------------------

    def probe_card_presence(self) -> Tuple[bool, str]:
        """Lightweight card presence check via PC/SC (in-process).

        Returns (True, atr_hex) if a card is physically present,
        (False, reason) otherwise.  Runs in-process using the pyscard
        library - typically completes in <50 ms, suitable for 1.5 s polling.
        """
        if not _init_pyscard(self._venv_python):
            return False, 'NO_PYSCARD'

        try:
            rlist = _smartcard_readers()
        except Exception as exc:
            return False, f'PC/SC error: {exc}'

        if not rlist:
            return False, 'No smart-card reader detected'

        reader = rlist[0]
        try:
            conn = reader.createConnection()
            conn.connect()
            atr = conn.getATR()
            atr_hex = ' '.join(f'{b:02X}' for b in atr)
            conn.disconnect()
            return True, atr_hex
        except _NoCardException:
            return False, 'No card in reader'
        except _CardConnectionException as exc:
            return False, self._clean_pysim_error(str(exc))
        except Exception as exc:
            return False, self._clean_pysim_error(str(exc))

    # ---- card operations -----------------------------------------------

    def detect_card(self) -> Tuple[bool, str]:
        """Detect a card in the reader (or the virtual card if simulator active).

        Reads public card data only (ICCID, IMSI, etc.) via pySim-read.
        Does NOT check the ADM1 retry counter — that is deferred to
        ``authenticate()`` to avoid burning attempts on gialersim/blank
        cards where VERIFY CHV 0x0A is unsupported.
        """
        if self._simulator:
            ok, msg = self._simulator.detect_card()
            if ok:
                card = self._simulator._current_card()
                if card:
                    ct = card.card_type
                    self.card_type = CardType[ct] if ct in CardType.__members__ else CardType.UNKNOWN
                    data = card.get_current_data()
                    self.card_info = {
                        "IMSI": data.get("imsi", ""),
                        "ICCID": data.get("iccid", ""),
                    }
                    self.authenticated = card.authenticated
            return ok, msg

        self.authenticated = False
        self.card_info = {}
        self.card_type = CardType.UNKNOWN
        self.card_blocked = False
        self._adm1_remaining_attempts = None

        if self.cli_path is None:
            return False, ("No CLI tool found. Install sysmo-usim-tool or "
                           "pySim and set the appropriate environment variable.")

        if self.cli_backend == CLIBackend.PYSIM:
            ok, stdout, stderr = self._run_cli('pySim-read.py', '-p0')
            if ok:
                self._parse_pysim_output(stdout)
                self._original_card_data = dict(self.card_info)  # snapshot
                return True, "Card detected via pySim"
            # Also check stdout - pySim sometimes prints data before failing
            if stdout:
                self._parse_pysim_output(stdout)
                if self.card_info.get('ICCID'):
                    self._original_card_data = dict(self.card_info)
                    return True, "Card detected via pySim"
            return False, self._clean_pysim_error(stderr) or "No card detected"

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

    def read_iccid(self) -> Optional[str]:
        """Read ICCID from the card without authentication."""
        if self._simulator:
            card = self._simulator._current_card()
            return card.iccid if card else None
        # Hardware: ICCID is available from card_info after detect
        return self.card_info.get("ICCID")

    def _adm1_to_hex(self, adm1: str) -> str:
        """Convert ADM1 to the 16-char hex string expected by pySim ``-A``.

        ADM1 is an 8-byte key.  Files store it in one of two formats:

        - **16 hex chars** (e.g. ``3838383838383838``) — the raw key
          bytes in hex.  Passed through as-is.
        - **≤8 ASCII chars** (e.g. ``88888888``) — the human-readable
          form, identical to what you type in ``verify_adm 88888888``.
          Each character is encoded to its ASCII hex value.

        Detection is by length: 16 hex chars → already hex; otherwise
        treat as ASCII and encode.
        """
        import re
        # Already in hex format (16 hex chars = 8 bytes)
        if re.match(r'^[0-9a-fA-F]{16}$', adm1):
            return adm1.upper()
        # ASCII key (≤8 chars) — encode each char to hex
        if len(adm1) <= 8:
            return ''.join(f'{ord(c):02X}' for c in adm1)
        # Unexpected format — pass through, let pySim error
        return adm1

    @staticmethod
    def _hex_to_adm1_ascii(adm1_hex: str) -> str:
        """Convert 16-char hex ADM1 back to ASCII (for pySim ``-a`` flag).

        E.g. ``3838383838383838`` → ``88888888``.
        If the hex cannot be decoded to printable ASCII, returns the
        original hex string (pySim will receive it as-is).
        """
        try:
            raw = bytes.fromhex(adm1_hex)
            ascii_str = raw.decode('ascii')
            if ascii_str.isprintable():
                return ascii_str
        except (ValueError, UnicodeDecodeError):
            pass
        return adm1_hex

    # Patterns in pySim-shell stdout/stderr that indicate the shell
    # failed to initialise properly (card not equipped).  When these
    # appear the process may still exit 0 but no commands ran.
    _PYSIM_SHELL_INIT_ERRORS = (
        'not equipped',
        'card error',
        'card initialization',
        'autodetection failed',
        'no card',
    )

    # Command-level errors: pySim-shell can exit 0 even when an
    # individual command (e.g. verify_adm) fails.  These patterns
    # in stdout/stderr indicate an APDU or command failure.
    _PYSIM_SHELL_CMD_ERRORS = (
        'swmatcherror',       # Python exception from pySim
        'sw: 6f00',           # Generic "no precise diagnosis"
        'sw: 6982',           # Security status not satisfied
        'sw: 6983',           # Auth method blocked (permanent)
        'got 6f00',           # "Expected 9000 and got 6f00"
        'got 6982',           # "Expected 9000 and got 6982"
        'got 6983',           # "Expected 9000 and got 6983"
    )

    def _run_pysim_shell_safe(self, commands: str,
                              timeout: int = 30) -> Tuple[bool, str, str]:
        """Run pySim-shell.py WITHOUT -A flag (no auto-authentication).

        Starts pySim-shell in **read-only** mode.  The caller can pipe
        ``verify_adm`` or other commands through stdin.  This is the
        SAFE way to interact with the card — no ADM1 attempt is consumed
        unless the caller explicitly sends a verify_adm command.

        Returns (success, stdout, stderr).
        """
        return self._run_pysim_shell_impl(
            adm1_hex=None, commands=commands, timeout=timeout)

    def _run_pysim_shell(self, adm1_hex: str, commands: str,
                         timeout: int = 30) -> Tuple[bool, str, str]:
        """Run pySim-shell.py WITH -A (auto-authentication at startup).

        **WARNING**: Using -A sends a VERIFY APDU at startup, consuming
        one ADM1 attempt even if the key is wrong.  Only call this
        method from ``_program_nonempty_card`` after ICCID cross-check
        has confirmed the card matches the data row.

        Returns (success, stdout, stderr).
        """
        return self._run_pysim_shell_impl(
            adm1_hex=adm1_hex, commands=commands, timeout=timeout)

    def _run_pysim_shell_impl(
            self, adm1_hex: Optional[str], commands: str,
            timeout: int = 30) -> Tuple[bool, str, str]:
        """Internal: run pySim-shell.py, optionally with -A.

        Commands are piped via stdin in interactive mode (no --noprompt).
        ``--noprompt`` is intentionally NOT used because it prevents
        pySim-shell from reading stdin commands — with --noprompt the
        shell initialises the card and exits immediately, ignoring any
        piped verify_adm or write commands.

        Init-failure detection relies on scanning stdout/stderr for
        known error patterns (see ``_PYSIM_SHELL_INIT_ERRORS``).
        """
        if self.cli_path is None:
            return False, "", "pySim not found"

        script_path = self._validate_script_path('pySim-shell.py')
        if script_path is None:
            return False, "", "pySim-shell.py not found"

        python_exe = self._venv_python or sys.executable
        cmd = [python_exe, script_path, '-p0']
        if adm1_hex:
            # johneff 260318 remember legacy/cards.py patch in pysim
            # Gialersim cards: pySim-shell does not support -t, and
            # standard VERIFY ADM1 (CHV 0x0A) fails with 6f00 on these
            # cards. Auth is handled by pySim-prog during initial
            # programming. For extra-field writes after pySim-prog,
            # pySim-shell runs without -A since the card session is
            # already authenticated.
            if self.card_type != CardType.GIALERSIM:
                cmd += ['-A', adm1_hex]
        # Append 'quit' so the shell terminates cleanly.
        # NOTE: pySim-shell uses 'quit', NOT 'exit'.
        full_input = commands.rstrip('\n') + '\nquit\n'
        logger.debug("pySim-shell input:\n%s", full_input)
        try:
            result = subprocess.run(
                cmd, input=full_input, capture_output=True, text=True,
                timeout=timeout, cwd=self.cli_path,
            )
            if result.stdout:
                logger.info("pySim-shell stdout:\n%s", result.stdout.strip())
            if result.stderr:
                logger.info("pySim-shell stderr:\n%s", result.stderr.strip())

            # pySim-shell can exit 0 even when commands fail.
            # Scan output for BOTH init-failure AND command-failure
            # patterns to catch those cases.
            combined_lower = (
                (result.stdout or '') + '\n' + (result.stderr or '')
            ).lower()
            init_failed = any(
                pat in combined_lower
                for pat in self._PYSIM_SHELL_INIT_ERRORS
            )
            if init_failed:
                logger.warning(
                    "pySim-shell init failure detected in output")
                return (False,
                        result.stdout.strip(),
                        result.stderr.strip())

            # Check for command-level APDU failures (e.g. verify_adm
            # returning 6f00).  pySim-shell exits 0 even on these.
            cmd_failed = any(
                pat in combined_lower
                for pat in self._PYSIM_SHELL_CMD_ERRORS
            )
            if cmd_failed:
                logger.warning(
                    "pySim-shell command failure detected in output "
                    "(APDU error despite exit code 0)")
                return (False,
                        result.stdout.strip(),
                        result.stderr.strip())

            return (result.returncode == 0,
                    result.stdout.strip(),
                    result.stderr.strip())
        except subprocess.TimeoutExpired:
            return False, "", "pySim-shell timed out"
        except FileNotFoundError:
            return False, "", "pySim-shell.py not found"
        except Exception as e:
            return False, "", str(e)

    def _run_pysim_prog(
            self, card_data: Dict[str, str],
            adm1_hex: str,
            timeout: int = 60) -> Tuple[bool, str, str]:
        """Program an empty card using pySim-prog.py.

        ``pySim-prog.py`` is purpose-built for initial card programming
        and handles blank sysmoISIM cards that ``pySim-shell.py`` cannot
        auto-detect.  It writes ICCID, IMSI, Ki, OPc, ACC, and operator
        name (SPN) in a single invocation.

        Returns (success, stdout, stderr).
        """
        if self.cli_path is None:
            return False, "", "pySim not found"

        script_path = self._validate_script_path('pySim-prog.py')
        if script_path is None:
            return False, "", "pySim-prog.py not found"

        python_exe = self._venv_python or sys.executable

        # Pick pySim-prog card type flag based on detected type.
        # Gialersim cards use a different VERIFY path internally
        # (CHV 0x0C vs 0x0A) and must be explicitly selected.
        pysim_type = 'auto'
        if self.card_type == CardType.GIALERSIM:
            pysim_type = 'gialersim'
        elif self.card_type == CardType.SJA5:
            pysim_type = 'sysmoISIM-SJA5'
        elif self.card_type == CardType.SJA2:
            pysim_type = 'sysmoISIM-SJA2'
        elif self.card_type == CardType.SJS1:
            pysim_type = 'sysmoUSIM-SJS1'

        cmd = [python_exe, script_path, '-p0', '-t', pysim_type]

        # Gialersim cards: pass ADM1 as ASCII (-a) because the
        # gialersim driver handles its own internal auth and uses
        # the -a value for file writes.  Other cards: pass raw hex
        # via -A for direct VERIFY ADM1 APDU.
        if self.card_type == CardType.GIALERSIM:
            # Convert hex back to ASCII for -a flag
            adm1_ascii = self._hex_to_adm1_ascii(adm1_hex)
            cmd += ['-a', adm1_ascii]
        else:
            cmd += ['-A', adm1_hex]

        # Map card_data fields to pySim-prog flags
        if card_data.get('ICCID'):
            cmd += ['-s', card_data['ICCID']]
        if card_data.get('IMSI'):
            cmd += ['-i', card_data['IMSI']]
        if card_data.get('Ki'):
            cmd += ['-k', card_data['Ki']]
        if card_data.get('OPc'):
            cmd += ['-o', card_data['OPc']]
        if card_data.get('SPN'):
            cmd += ['-n', card_data['SPN']]
        if card_data.get('ACC'):
            cmd += ['--acc', card_data['ACC']]
        if card_data.get('FPLMN'):
            for plmn in card_data['FPLMN'].replace(';', ',').split(','):
                plmn = plmn.strip()
                if plmn:
                    cmd += ['-f', plmn]

        # Derive MCC/MNC from IMSI so pySim-prog can configure HPLMN
        imsi = card_data.get('IMSI', '')
        if len(imsi) >= 5:
            cmd += ['-x', imsi[:3], '-y', imsi[3:5]]

        # Mask both hex and ASCII ADM1 values in log output
        secrets = {adm1_hex}
        if self.card_type == CardType.GIALERSIM:
            secrets.add(self._hex_to_adm1_ascii(adm1_hex))
        logger.info("pySim-prog command: %s",
                    ' '.join('***' if c in secrets else c for c in cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=self.cli_path,
            )
            if result.stdout:
                logger.info("pySim-prog stdout:\n%s",
                            result.stdout.strip())
            if result.stderr:
                logger.info("pySim-prog stderr:\n%s",
                            result.stderr.strip())
            return (result.returncode == 0,
                    result.stdout.strip(),
                    result.stderr.strip())
        except subprocess.TimeoutExpired:
            return False, "", "pySim-prog timed out"
        except FileNotFoundError:
            return False, "", "pySim-prog.py not found"
        except Exception as e:
            return False, "", str(e)

    def check_adm1_retry_counter(self) -> Optional[int]:
        """Check how many ADM1 authentication attempts remain.

        Sends a VERIFY APDU **without data** to the card.  Per ISO 7816
        / ETSI TS 102.221, the card responds with SW ``63 CX`` where
        ``X`` is the number of remaining retries, WITHOUT decrementing
        the counter.  SW ``6983`` means the card is permanently blocked.

        Returns:
            Number of remaining attempts (0 = blocked), or None if
            the counter could not be read (e.g. no pyscard, no card).
        """
        if self._simulator:
            sim_card = self._simulator._current_card()
            if sim_card:
                return sim_card.remaining_attempts
            return None

        if not _init_pyscard(self._venv_python):
            logger.debug("check_adm1_retry_counter: pyscard not available")
            return None

        try:
            rlist = _smartcard_readers()
            if not rlist:
                return None
            reader = rlist[0]
            conn = reader.createConnection()
            conn.connect()

            # VERIFY APDU without data: CLA=00, INS=20, P1=00,
            # P2=key_ref (0x0A for ADM1), no Lc/data.
            apdu = [0x00, 0x20, 0x00, self._ADM1_KEY_REF]
            data, sw1, sw2 = conn.transmit(apdu)
            conn.disconnect()

            if sw1 == 0x63 and (sw2 & 0xF0) == 0xC0:
                remaining = sw2 & 0x0F
                self._adm1_remaining_attempts = remaining
                self.card_blocked = (remaining == 0)
                logger.info("ADM1 retry counter: %d remaining", remaining)
                return remaining
            elif sw1 == 0x69 and sw2 == 0x83:
                # 6983 = authentication method blocked
                self._adm1_remaining_attempts = 0
                self.card_blocked = True
                logger.warning("ADM1 retry counter: BLOCKED (6983)")
                return 0
            elif sw1 == 0x90 and sw2 == 0x00:
                # Some cards return 9000 when PIN is already verified
                # in this session — retry counter not decremented
                logger.info("ADM1 appears already verified this session")
                return None  # can't determine count
            else:
                logger.debug("Unexpected VERIFY response: %02X %02X",
                             sw1, sw2)
                return None
        except Exception as exc:
            logger.debug("check_adm1_retry_counter failed: %s", exc)
            return None

    @property
    def adm1_remaining_attempts(self) -> Optional[int]:
        """Last known ADM1 remaining attempts (None if never checked)."""
        return self._adm1_remaining_attempts

    def authenticate(self, adm1: str, force: bool = False,
                     expected_iccid: Optional[str] = None) -> Tuple[bool, str]:
        """Authenticate with ADM1 key.

        **SAFETY**: This method NEVER uses the ``-A`` flag on pySim-shell.
        Instead it starts pySim-shell in read-only mode and pipes
        ``verify_adm`` interactively.  This means the VERIFY APDU is
        only sent when the shell is ready and the card has been
        successfully initialised — blank cards that fail init will
        never have an attempt consumed.

        Args:
            adm1: The ADM1 key.
            force: Force auth even with low attempts.
            expected_iccid: If provided, cross-verify the card's ICCID before
                authenticating. Prevents wrong-ADM1 lockout from mismatched
                card/data rows.
        """
        # --- Pre-flight: blocked card check ---
        if self.card_blocked:
            return False, (
                "Card is PERMANENTLY LOCKED \u2014 "
                "ADM1 authentication blocked (0 attempts remaining). "
                "This card cannot be programmed."
            )

        # ICCID cross-verification safety check
        if expected_iccid is not None:
            card_iccid = self.read_iccid()
            if card_iccid and card_iccid != expected_iccid:
                return False, (
                    f"ICCID mismatch! Card ICCID: {card_iccid} does not match "
                    f"expected: {expected_iccid}. Wrong card or wrong data row. "
                    f"Authentication aborted to prevent card lockout."
                )

        if self._simulator:
            ok, msg = self._simulator.authenticate(adm1, force=force)
            if ok:
                self.authenticated = True
                if force:
                    self._safety_override_acknowledged = True
            return ok, msg

        err = validate_adm1(adm1)
        if err:
            return False, err

        if self.cli_backend != CLIBackend.PYSIM:
            # Non-pySim backends not yet implemented
            logger.warning("authenticate(): non-pySim backend not implemented")
            return False, "Authentication not supported for this CLI backend"

        # --- Pre-flight: check retry counter (non-destructive) ---
        if not force:
            remaining = self.check_adm1_retry_counter()
            if remaining is not None and remaining == 0:
                self.card_blocked = True
                return False, (
                    "Card is PERMANENTLY LOCKED \u2014 "
                    "ADM1 authentication blocked (0 attempts remaining). "
                    "This card cannot be programmed."
                )
            if remaining is not None and remaining <= 1:
                return False, (
                    f"DANGER: Only {remaining} ADM1 attempt(s) remaining! "
                    f"Authentication aborted to protect the card. "
                    f"Use force=True to override (at your own risk)."
                )

        # Use pySim-shell WITHOUT -A (safe: no auto-auth at startup)
        # Pipe verify_adm with the hex key interactively.
        adm1_hex = self._adm1_to_hex(adm1)

        # --- Blank / gialersim card safety check ---
        # Skip VERIFY ADM1 and store the key for deferred auth via
        # pySim-prog in two cases:
        #
        # 1. Blank cards (no original data at all, or present but
        #    missing both ICCID and IMSI).  These cannot process a
        #    standard VERIFY ADM1 APDU — on sysmoISIM cards this
        #    causes 6f00 (internal card error) which STILL consumes
        #    a retry-counter attempt, bricking the card after 3 tries.
        #
        # 2. Gialersim-type cards.  These use CHV 0x0C (not 0x0A)
        #    with their own internal auth sequence.  The standard
        #    verify_adm (CHV 0x0A) will always fail.  pySim-prog
        #    with -t gialersim handles auth correctly.
        orig = self._original_card_data or {}
        is_blank = (not orig
                    or (not orig.get('ICCID') and not orig.get('IMSI')))
        is_gialersim = self.card_type == CardType.GIALERSIM

        if is_blank or is_gialersim:
            self.authenticated = True
            self._authenticated_adm1_hex = adm1_hex
            if force:
                self._safety_override_acknowledged = True
            if is_gialersim:
                reason = "gialersim card (uses different auth method)"
            else:
                reason = "blank card detected"
            logger.info(
                "%s \u2014 ADM1 stored "
                "(will authenticate during programming via pySim-prog)",
                reason.capitalize())
            return True, (
                f"Authentication stored \u2014 {reason}. "
                f"ADM1 will be used during programming via pySim-prog."
            )

        verify_cmd = f'verify_adm --pin-is-hex {adm1_hex}'

        # Brief pause after the retry-counter check to ensure the
        # PC/SC reader is fully released before pySim-shell opens it.
        # USB readers (especially through VM passthrough) need time
        # to settle after a disconnect — without this, pySim-shell
        # can get a 6f00 error on the VERIFY APDU.
        time.sleep(0.3)

        ok, stdout, stderr = self._run_pysim_shell_safe(
            verify_cmd, timeout=15)

        if ok:
            self.authenticated = True
            self._authenticated_adm1_hex = adm1_hex
            if force:
                self._safety_override_acknowledged = True
            logger.info("ADM1 authentication successful (safe mode)")
            return True, "Authentication successful"

        # Check whether pySim-shell failed because the card is blank
        # (init failure / "not equipped").  Blank cards cannot be
        # verified via pySim-shell because it can't auto-detect them.
        # Store the ADM1 anyway — pySim-prog.py will authenticate
        # during programming.
        combined = (stdout + '\n' + stderr).lower()
        init_failed = any(
            pat in combined
            for pat in self._PYSIM_SHELL_INIT_ERRORS
        )
        if init_failed and not self._original_card_data:
            # Blank card: store ADM1, defer real auth to pySim-prog
            self.authenticated = True
            self._authenticated_adm1_hex = adm1_hex
            if force:
                self._safety_override_acknowledged = True
            logger.info("Blank card \u2014 ADM1 stored (will authenticate "
                        "during programming via pySim-prog)")
            return True, (
                "Authentication stored \u2014 blank card will be "
                "authenticated during programming"
            )

        # Check for specific failure patterns.
        # NOTE: pySim reports errors as "Expected 9000 and got XXXX"
        # (SwMatchError).  We check for all known VERIFY failure SWs.

        # 6983 = permanently blocked — check first
        if '6983' in combined:
            self.card_blocked = True
            self._adm1_remaining_attempts = 0
            return False, (
                "Card is PERMANENTLY LOCKED \u2014 "
                "ADM1 authentication blocked (0 attempts remaining)"
            )

        # 6982 = wrong key (security status not satisfied)
        # 6f00 = generic card error (internal card OS failure, may still
        #        consume an ADM1 attempt on some card types)
        if '6982' in combined or '6f00' in combined or 'swmatcherror' in combined:
            # Re-check retry counter after failure
            remaining = self.check_adm1_retry_counter()
            remaining_msg = ""
            if remaining is not None:
                remaining_msg = f" ({remaining} attempt(s) remaining)"
                if remaining == 0:
                    self.card_blocked = True
            sw_code = '6f00' if '6f00' in combined else '6982'
            if sw_code == '6f00':
                detail = (
                    f"Authentication FAILED \u2014 VERIFY returned SW 6f00 "
                    f"(internal card error).{remaining_msg} "
                    f"This may indicate a card that cannot process "
                    f"VERIFY ADM1. 3 wrong attempts = permanent card lock!"
                )
            else:
                detail = (
                    f"Authentication FAILED \u2014 wrong ADM1 key "
                    f"(SW {sw_code}).{remaining_msg} "
                    f"3 wrong attempts = permanent card lock!"
                )
            return False, detail

        error_msg = self._clean_pysim_error(stderr) if stderr else "Authentication failed"
        return False, f"Authentication failed: {error_msg}"

    def read_public_data(self) -> Optional[Dict[str, str]]:
        """Read public fields without authentication."""
        if self._simulator:
            return self._simulator.read_public_data()
        # For hardware: return what we have from detect (ICCID, IMSI, etc.)
        return self.card_info if self.card_info else None

    def read_protected_data(self) -> Optional[Dict[str, str]]:
        """Read protected fields (requires ADM1 auth)."""
        if self._simulator:
            return self._simulator.read_protected_data()
        if not self.authenticated:
            return None
        # TODO: Real CLI read of Ki, OPc, etc.
        return {}

    def read_card_data(self) -> Optional[Dict[str, str]]:
        """Read basic card data (IMSI, ICCID, etc.)."""
        if self._simulator:
            return self._simulator.read_card_data()
        if not self.authenticated:
            return None
        return self.card_info if self.card_info else None

    # ---- pySim field-write helpers ------------------------------------

    # Map from our field keys to pySim-shell commands.
    # Each entry: (list_of_commands_fn) that takes (value) and returns
    # a list of shell command strings.

    @staticmethod
    def _pysim_write_imsi(imsi: str) -> List[str]:
        """Commands to write IMSI via pySim-shell."""
        return [
            'select MF/ADF.USIM/EF.IMSI',
            f'update_binary_decoded \'{{"imsi": "{imsi}"}}\'',
        ]

    @staticmethod
    def _pysim_write_ki_opc(ki: str, opc: str) -> List[str]:
        """Commands to write Ki and OPc via pySim-shell.

        These are stored together in EF.USIM_AUTH_KEY.
        The JSON includes the algorithm config (milenage, use OPc).
        """
        import json
        payload = json.dumps({
            "cfg": {
                "only_4bytes_res_in_3g": False,
                "sres_deriv_func_in_2g": 1,
                "use_opc_instead_of_op": True,
                "algorithm": "milenage",
            },
            "key": ki.lower(),
            "op_opc": opc.lower(),
        })
        return [
            'select MF/ADF.USIM/EF.USIM_AUTH_KEY',
            f"update_binary_decoded '{payload}'",
        ]

    @staticmethod
    def _pysim_write_spn(spn: str) -> List[str]:
        """Commands to write SPN via pySim-shell."""
        import json
        payload = json.dumps({
            "spn": spn,
            "show_in_hplmn": True,
            "hide_in_oplmn": False,
        })
        return [
            'select MF/ADF.USIM/EF.SPN',
            f"update_binary_decoded '{payload}'",
        ]

    @staticmethod
    def _pysim_write_fplmn(fplmn_str: str) -> List[str]:
        """Commands to write FPLMN list via pySim-shell.

        fplmn_str is semicolon-separated, e.g. '24007;24024;24001'.
        Each PLMN is 5-6 digits (MCC+MNC).
        """
        import json
        plmns = [p.strip() for p in fplmn_str.split(';') if p.strip()]
        # Build list of {mcc, mnc} dicts
        plmn_list = []
        for p in plmns:
            if len(p) == 5:
                plmn_list.append({"mcc": p[:3], "mnc": p[3:]})
            elif len(p) == 6:
                plmn_list.append({"mcc": p[:3], "mnc": p[3:]})
            # else skip malformed
        payload = json.dumps(plmn_list)
        return [
            'select MF/ADF.USIM/EF.FPLMN',
            f"update_binary_decoded '{payload}'",
        ]

    @staticmethod
    def _pysim_write_acc(acc: str) -> List[str]:
        """Commands to write ACC via pySim-shell.

        ACC is 4 hex digits representing 2 bytes.
        """
        acc_hex = acc.strip().lower().zfill(4)
        return [
            'select MF/ADF.USIM/EF.ACC',
            f'update_binary {acc_hex}',
        ]

    @staticmethod
    def _pysim_write_iccid(iccid: str) -> List[str]:
        """Commands to write ICCID via pySim-shell (empty cards only).

        ICCID is stored in EF.ICCID under MF (not ADF.USIM).
        The binary encoding swaps nibbles of BCD digits.
        """
        import json
        payload = json.dumps({"iccid": iccid})
        return [
            'select MF/EF.ICCID',
            f"update_binary_decoded '{payload}'",
        ]

    def _compute_changed_fields(self, card_data: Dict[str, str],
                                original: Dict[str, str]
                                ) -> Dict[str, str]:
        """Return only fields in card_data that differ from original.

        Keys are compared case-insensitively. Empty/missing values in
        card_data are skipped (don't erase existing data).
        """
        changed: Dict[str, str] = {}
        orig_lower = {k.lower(): v for k, v in original.items()}
        for key, val in card_data.items():
            if not val:  # skip empty
                continue
            orig_val = orig_lower.get(key.lower(), "")
            if val.strip() != orig_val.strip():
                changed[key] = val.strip()
        return changed

    def _is_empty_card(
            self, original_data: Optional[Dict[str, str]]) -> bool:
        """Return True when programming a blank / empty card.

        A card is considered empty when:
        - No original baseline data at all (``detect_card`` returned
          nothing or the UI set the baseline to ``{}`` / ``None``), OR
        - Original data exists but has no ICCID and no IMSI (blank
          card that pySim-read could partially read, e.g. gialersim
          type detected but no subscriber data), OR
        - Card type is GIALERSIM (these always use pySim-prog with
          ``-t gialersim`` for initial programming).
        """
        orig = (original_data if original_data is not None
                else self._original_card_data)
        if not orig:
            return True
        if not orig.get('ICCID') and not orig.get('IMSI'):
            return True
        if self.card_type == CardType.GIALERSIM:
            return True
        return False

    def program_card(self, card_data: Dict[str, str],
                     original_data: Optional[Dict[str, str]] = None
                     ) -> Tuple[bool, str]:
        """Program a card with the given parameters.

        For **non-empty cards** (already have ICCID/IMSI), only the
        fields that differ from *original_data* are written via
        ``pySim-shell.py`` (delta-write).

        For **empty / blank cards** (no original data), all non-empty
        fields are written in a single ``pySim-prog.py`` invocation.
        ``pySim-prog`` is purpose-built for initial card programming and
        correctly handles blank sysmoISIM cards that ``pySim-shell``
        cannot auto-detect.

        If ``pySim-prog`` is not available, falls back to ``pySim-shell``
        (which may work on some card variants).

        Args:
            card_data: Dict of field values to write (IMSI, Ki, OPc, etc.).
            original_data: Optional baseline data for change detection.
                If None, uses self._original_card_data from the last detect.
        """
        if self._simulator:
            return self._simulator.program_card(card_data)
        if self.card_blocked:
            return False, (
                "Card is PERMANENTLY LOCKED \u2014 cannot program. "
                "Remove this card and insert a different one."
            )
        if not self.authenticated:
            return False, "Not authenticated"
        if self.cli_backend != CLIBackend.PYSIM:
            return False, "Programming not supported for this CLI backend"
        if not self._authenticated_adm1_hex:
            return False, "No ADM1 key stored \u2014 re-authenticate first"

        # --- Pre-flight: verify ADM1 retry counter is safe ----------------
        # Programming sends a VERIFY APDU.  If the counter is already
        # dangerously low (e.g. from a previous 6f00 failure that was
        # counted), refuse to proceed to protect the card.
        # Skip this check if the user already forced past the safety
        # warning during authenticate() — asking twice is redundant.
        if not self._safety_override_acknowledged:
            remaining = self.check_adm1_retry_counter()
            if remaining is not None:
                if remaining == 0:
                    self.card_blocked = True
                    return False, (
                        "Card is PERMANENTLY LOCKED \u2014 "
                        "ADM1 retry counter is 0. Cannot program."
                    )
                if remaining < 2:
                    return False, (
                        f"DANGER: Only {remaining} ADM1 attempt(s) remaining. "
                        f"Programming aborted to protect the card. "
                        f"Re-authenticate first to confirm the key is correct."
                    )

        # Determine what changed
        orig = original_data if original_data is not None else self._original_card_data
        empty_card = self._is_empty_card(original_data)
        if not empty_card and orig:
            changed = self._compute_changed_fields(card_data, orig)
        else:
            # Empty / blank / gialersim card — write everything non-empty
            changed = {k: v.strip() for k, v in card_data.items() if v.strip()}

        if not changed:
            return True, "No changes to program — card data already matches"

        # ---- Empty card: prefer pySim-prog.py --------------------------
        if empty_card:
            return self._program_empty_card(card_data, changed)

        # ---- Non-empty card: delta-write via pySim-shell.py ------------
        # Brief pause after retry-counter check to let the reader settle
        time.sleep(0.3)
        return self._program_nonempty_card(card_data, changed)

    # Fields supported by pySim-prog.py command-line flags
    _PYSIM_PROG_FIELDS = {'ICCID', 'IMSI', 'Ki', 'OPc', 'SPN', 'ACC', 'FPLMN'}

    def _program_empty_card(self, card_data: Dict[str, str],
                            changed: Dict[str, str]) -> Tuple[bool, str]:
        """Initial programming of a blank card via pySim-prog.py.

        ``pySim-prog.py`` handles ICCID, IMSI, Ki, OPc, SPN, and ACC.
        Any remaining fields (e.g. FPLMN) are written in a follow-up
        ``pySim-shell.py`` call after the card has been initialised.

        Falls back to pySim-shell.py entirely if pySim-prog.py is not
        available.
        """
        # Split fields into those pySim-prog can handle and the rest
        prog_fields = {k: v for k, v in changed.items()
                       if k in self._PYSIM_PROG_FIELDS}
        extra_fields = {k: v for k, v in changed.items()
                        if k not in self._PYSIM_PROG_FIELDS
                        and k != 'ADM1'}

        all_fields = [k for k in changed if k != 'ADM1']
        summary = ', '.join(all_fields) or 'all fields'
        logger.info("Empty card detected — using pySim-prog for: %s",
                    summary)

        # Try pySim-prog first (purpose-built for initial programming)
        ok, stdout, stderr = self._run_pysim_prog(
            prog_fields, self._authenticated_adm1_hex, timeout=60)

        if ok:
            prog_summary = ', '.join(prog_fields.keys())
            logger.info("pySim-prog succeeded: %s", prog_summary)

            # Write extra fields (FPLMN etc.) via pySim-shell now that
            # the card is initialised and pySim-shell can detect it.
            if extra_fields:
                logger.info("Writing extra fields via pySim-shell: %s",
                            list(extra_fields.keys()))
                ex_ok, ex_msg = self._program_nonempty_card(
                    card_data, extra_fields)
                if not ex_ok:
                    logger.warning(
                        "Extra fields failed after pySim-prog: %s",
                        ex_msg)
                    return True, (
                        f"Card programmed: {prog_summary}\n"
                        f"Warning: extra fields failed: {ex_msg}"
                    )

            # Run read-back verification
            v_ok, v_msg, v_data = self.verify_after_program(card_data)
            if v_ok:
                if v_data:
                    for k, v in v_data.items():
                        self.card_info[k] = v
                return True, f"Card programmed and verified: {summary}"
            else:
                # pySim-prog reported success — trust it even if
                # pySim-read can't read back (common on freshly
                # programmed blank cards).
                logger.warning(
                    "pySim-prog OK but read-back failed: %s", v_msg)
                return True, (
                    f"Card programmed: {summary}\n"
                    f"(read-back verification could not confirm "
                    f"— re-insert card to verify)"
                )

        # pySim-prog failed — check if it's just not installed
        prog_missing = 'not found' in stderr.lower()
        if prog_missing:
            logger.info("pySim-prog.py not available, "
                        "falling back to pySim-shell")
            return self._program_nonempty_card(card_data, changed)

        # Genuine programming failure
        error_msg = (self._clean_pysim_error(stderr)
                     if stderr else "Programming failed")
        return False, f"Programming failed: {error_msg}"

    def _program_nonempty_card(self, card_data: Dict[str, str],
                               changed: Dict[str, str]
                               ) -> Tuple[bool, str]:
        """Delta-write to a non-empty card via pySim-shell.py."""
        # Build pySim-shell command sequence
        commands: List[str] = []
        fields_written: List[str] = []

        # Ki and OPc must be written together (same EF)
        ki_changed = 'Ki' in changed
        opc_changed = 'OPc' in changed
        if ki_changed or opc_changed:
            ki_val = changed.get('Ki', card_data.get('Ki', ''))
            opc_val = changed.get('OPc', card_data.get('OPc', ''))
            if ki_val and opc_val:
                commands.extend(self._pysim_write_ki_opc(ki_val, opc_val))
                fields_written.append('Ki/OPc')
            elif ki_val:
                # OPc not provided — can't write Ki alone safely
                logger.warning("Ki changed but OPc not provided; "
                               "skipping Ki/OPc write")
            # Remove from changed so they're not processed again
            changed.pop('Ki', None)
            changed.pop('OPc', None)

        # ICCID (only for empty cards — caller ensures this)
        if 'ICCID' in changed:
            commands.extend(self._pysim_write_iccid(changed['ICCID']))
            fields_written.append('ICCID')
            del changed['ICCID']

        # IMSI
        if 'IMSI' in changed:
            commands.extend(self._pysim_write_imsi(changed['IMSI']))
            fields_written.append('IMSI')
            del changed['IMSI']

        # SPN
        if 'SPN' in changed:
            commands.extend(self._pysim_write_spn(changed['SPN']))
            fields_written.append('SPN')
            del changed['SPN']

        # FPLMN
        if 'FPLMN' in changed:
            commands.extend(self._pysim_write_fplmn(changed['FPLMN']))
            fields_written.append('FPLMN')
            del changed['FPLMN']

        # ACC
        if 'ACC' in changed:
            commands.extend(self._pysim_write_acc(changed['ACC']))
            fields_written.append('ACC')
            del changed['ACC']

        # ADM1 is never written to the card (it's the auth key, not data)
        changed.pop('ADM1', None)

        # Warn about any remaining unhandled fields and collect them
        # so the warning is surfaced to the operator in the UI.
        skipped_fields: List[str] = []
        for key in changed:
            logger.warning("program_card: field '%s' has no write handler, "
                           "skipped", key)
            skipped_fields.append(key)

        if not commands:
            if skipped_fields:
                return True, (
                    "No programmable fields changed\n"
                    f"Warning: skipped fields (no write handler): "
                    f"{', '.join(skipped_fields)}")
            return True, "No programmable fields changed"

        # Execute via pySim-shell WITH -A flag (auto-auth at startup).
        # This consumes only ONE ADM1 attempt for both authentication
        # and writes, instead of two (one in authenticate(), one here).
        # The caller MUST pause the CardWatcher before calling this
        # method — watcher probes during -A init caused 6f00 errors
        # in v0.5.15, but with paused_context() this is safe.
        cmd_str = '\n'.join(commands)
        logger.info("Programming card: fields=%s", fields_written)
        logger.debug("pySim-shell commands:\n%s", cmd_str)

        ok, stdout, stderr = self._run_pysim_shell(
            self._authenticated_adm1_hex, cmd_str, timeout=30)

        # Build a suffix for any skipped fields so the operator sees it.
        skip_suffix = ""
        if skipped_fields:
            skip_suffix = (
                f"\nWarning: skipped fields (no write handler): "
                f"{', '.join(skipped_fields)}")

        if ok:
            summary = ', '.join(fields_written)
            logger.info("Card programmed (pre-verify): %s", summary)

            # --- Post-programming read-back verification ---------------
            v_ok, v_msg, v_data = self.verify_after_program(card_data)
            if v_ok:
                # Update card_info so the watcher sees the new ICCID
                if v_data:
                    for k, v in v_data.items():
                        self.card_info[k] = v
                logger.info("Card programmed and verified: %s", summary)
                return True, (
                    f"Card programmed and verified: {summary}"
                    f"{skip_suffix}")
            else:
                logger.warning(
                    "Card programmed but verification failed: %s", v_msg)
                return False, (
                    f"Programming commands sent ({summary}) but "
                    f"read-back verification FAILED.\n{v_msg}"
                )

        # Check for partial success by scanning stdout for errors
        combined = (stdout + '\n' + stderr).lower()
        if 'sw mismatch' in combined:
            error_detail = (self._clean_pysim_error(stderr)
                            if stderr else "write error")
            return False, (
                f"Programming failed (write error): {error_detail}")

        error_msg = (self._clean_pysim_error(stderr)
                     if stderr else "Programming failed")
        return False, f"Programming failed: {error_msg}"

    _VERIFY_RETRIES = 2
    _VERIFY_DELAY_S = 1.0  # seconds between retries

    def verify_after_program(
            self, written_data: Dict[str, str],
    ) -> Tuple[bool, str, Dict[str, str]]:
        """Read-back verification after programming.

        Runs ``pySim-read.py -p0`` to confirm fields written to the card.
        Compares ICCID and IMSI against *written_data*.  Retries up to
        ``_VERIFY_RETRIES`` times with a short delay, because the card
        may need a moment to settle after writes.

        The caller MUST pause the CardWatcher before calling this method
        to avoid reader contention (probes during pySim-read cause
        spurious "card removed" events and read failures).

        Returns:
            (ok, message, read_back_data)
            *read_back_data* is the dict parsed from pySim-read output.
        """
        if self._simulator:
            return True, "Simulator — verification skipped", {}

        if self.cli_backend != CLIBackend.PYSIM:
            return True, "Verification not supported for this backend", {}

        import time
        last_mismatches: List[str] = []
        readback: Dict[str, str] = {}

        for attempt in range(1, self._VERIFY_RETRIES + 1):
            if attempt > 1:
                time.sleep(self._VERIFY_DELAY_S)
                logger.info("Verify attempt %d/%d", attempt, self._VERIFY_RETRIES)

            # Pass card type to pySim-read for gialersim cards so it
            # can locate EFs (e.g. EF_SPN) that require type-specific
            # knowledge.  Without -t, pySim-read may fail to read SPN.
            if self.card_type == CardType.GIALERSIM:
                ok, stdout, stderr = self._run_cli(
                    'pySim-read.py', '-p0', '-t', 'gialersim')
            else:
                ok, stdout, stderr = self._run_cli('pySim-read.py', '-p0')
            logger.info("Verify read-back (attempt %d): ok=%s, "
                        "stdout_lines=%d, stderr_lines=%d",
                        attempt, ok,
                        len(stdout.splitlines()) if stdout else 0,
                        len(stderr.splitlines()) if stderr else 0)
            if stdout:
                logger.debug("Verify stdout:\n%s", stdout[:500])
            if not ok and not stdout:
                last_mismatches = [
                    f"pySim-read error: "
                    f"{self._clean_pysim_error(stderr) or 'Unknown error'}"
                ]
                continue  # retry

            # Parse the output into a fresh dict
            saved_info = self.card_info
            self.card_info = {}
            self._parse_pysim_output(stdout)
            readback = dict(self.card_info)
            self.card_info = saved_info  # restore

            # Compare key fields
            last_mismatches = []
            for field in ('ICCID', 'IMSI'):
                expected = written_data.get(field, '').strip()
                actual = readback.get(field, '').strip()
                if expected and actual and expected != actual:
                    last_mismatches.append(
                        f"{field}: wrote {expected}, read back {actual}")
                elif expected and not actual:
                    last_mismatches.append(
                        f"{field}: wrote {expected}, not found in read-back")

            if not last_mismatches:
                logger.info("Post-program verification OK: %s", readback)
                return True, "Verification OK", readback

        # All retries exhausted
        detail = '; '.join(last_mismatches)
        return False, (
            f"Programming commands sent but read-back verification FAILED "
            f"after {self._VERIFY_RETRIES} attempts.\n{detail}"
        ), readback

    def verify_card(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Verify card data matches expected values."""
        if self._simulator:
            return self._simulator.verify_card(expected)
        if not self.authenticated:
            return False, ["Not authenticated"]
        return True, []

    def get_remaining_attempts(self) -> Optional[int]:
        """Return remaining ADM1 auth attempts, or None if unknown."""
        if self._simulator:
            return self._simulator.get_remaining_attempts()
        return self._adm1_remaining_attempts

    def disconnect(self):
        if self._simulator:
            self._simulator.disconnect()
        self.authenticated = False
        self._authenticated_adm1_hex = None
        self._original_card_data = {}
        self.card_type = CardType.UNKNOWN
        self.card_info = {}
        self.card_blocked = False
        self._adm1_remaining_attempts = None
        self._safety_override_acknowledged = False

    # Error patterns from pySim that indicate specific conditions.
    # Each tuple is (keyword_in_stderr, user_friendly_message).
    _PYSIM_ERROR_MAP = [
        ("no card", "No SIM card in reader"),
        ("card is unpowered", "Card not powered - re-seat the SIM in the reader"),
        ("unable to connect with protocol", "Card not powered - re-seat the SIM in the reader"),
        ("no reader", "No smart-card reader detected"),
        ("no pc/sc", "PC/SC service not available - run: sudo systemctl start pcscd"),
        ("establish_context", "PC/SC service not available - run: sudo systemctl start pcscd"),
        ("could not connect", "Cannot connect to card reader"),
        ("protocoerror", "Card communication error - re-seat the SIM"),
        ("protocolerror", "Card communication error - re-seat the SIM"),
    ]

    def _clean_pysim_error(self, stderr: str) -> str:
        """Extract a user-friendly message from pySim stderr.

        pySim outputs full Python tracebacks on errors.  We scan for
        known patterns and return a short, readable summary instead of
        dumping the raw traceback into the UI.
        """
        if not stderr:
            return ""
        lower = stderr.lower()
        for pattern, friendly in self._PYSIM_ERROR_MAP:
            if pattern in lower:
                return friendly
        # Fallback: take the last non-empty line (usually the actual error)
        lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
        if lines:
            last = lines[-1]
            # Strip common Python exception prefixes
            for prefix in [
                "pysim.exceptions.", "smartcard.Exceptions.",
                "Exception:", "RuntimeError:", "OSError:",
            ]:
                if last.startswith(prefix):
                    last = last[len(prefix):].strip()
                    break
            # Truncate overly long messages
            if len(last) > 120:
                last = last[:117] + "..."
            return last
        return "Card read failed"

    # Map pySim auto-detected card type names to CardType enum values.
    _PYSIM_CARD_TYPE_MAP: Dict[str, CardType] = {
        'sysmoisim-sja5': CardType.SJA5,
        'sysmoisim-sja2': CardType.SJA2,
        'sysmousim-sjs1': CardType.SJS1,
        'gialersim': CardType.GIALERSIM,
    }

    def _parse_pysim_output(self, output: str):
        """Parse pySim-read output for card info.

        Extracts ICCID, IMSI, ACC, SPN, FPLMN, and auto-detected card
        type from pySim-read.py output.  These are public fields that
        don't require ADM1 auth.
        """
        fplmn_values: list[str] = []
        for line in output.splitlines():
            if ':' not in line:
                continue
            # Skip lines that look like tracebacks or file paths
            stripped = line.strip()
            if stripped.startswith(('File "', 'Traceback', 'raise ')):
                continue
            key, _, val = line.partition(':')
            key = key.strip().upper()
            val = val.strip()
            if not val:
                continue
            if 'IMSI' in key:
                self.card_info['IMSI'] = val
            elif 'ICCID' in key:
                self.card_info['ICCID'] = val
            elif key == 'ACC' or 'ACCESS CONTROL' in key:
                self.card_info['ACC'] = val
            elif key == 'SPN' or 'SERVICE PROVIDER' in key:
                self.card_info['SPN'] = val
            elif 'FPLMN' in key or 'FORBIDDEN' in key:
                # pySim may output multiple FPLMN lines or a single one
                if val and val.lower() not in ('none', 'empty', 'ffffff'):
                    fplmn_values.append(val)
            elif 'AUTODETECTED CARD TYPE' in key:
                ct = self._PYSIM_CARD_TYPE_MAP.get(val.lower())
                if ct is not None:
                    self.card_type = ct
                    logger.info("pySim auto-detected card type: %s -> %s",
                                val, ct.name)
        if fplmn_values:
            self.card_info['FPLMN'] = ';'.join(fplmn_values)
