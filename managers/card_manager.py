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
        """Detect a card in the reader (or the virtual card if simulator active)."""
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
        """Convert ADM1 to the hex format expected by pySim -A flag.

        If adm1 is 8 decimal digits, encode as ASCII hex (each char -> 2 hex).
        If adm1 is already 16 hex chars, return as-is (uppercase).
        """
        import re
        if re.match(r'^\d{8}$', adm1):
            # ASCII-encode each digit: e.g. '8' -> 0x38 -> '38'
            return ''.join(f'{ord(c):02X}' for c in adm1)
        if re.match(r'^[0-9a-fA-F]{16}$', adm1):
            return adm1.upper()
        return adm1  # pass through, let pySim error

    def _run_pysim_shell(self, adm1_hex: str, commands: str,
                         timeout: int = 30) -> Tuple[bool, str, str]:
        """Run pySim-shell.py with ADM1 auth and piped commands.

        Starts pySim-shell with -p0 (first reader) and -A (hex ADM1),
        then pipes *commands* via stdin.  Returns (success, stdout, stderr).
        """
        if self.cli_path is None:
            return False, "", "pySim not found"

        script_path = self._validate_script_path('pySim-shell.py')
        if script_path is None:
            return False, "", "pySim-shell.py not found"

        python_exe = self._venv_python or sys.executable
        cmd = [python_exe, script_path, '-p0', '-A', adm1_hex]
        # Append 'exit' so the shell terminates cleanly
        full_input = commands.rstrip('\n') + '\nexit\n'
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
            return (result.returncode == 0,
                    result.stdout.strip(),
                    result.stderr.strip())
        except subprocess.TimeoutExpired:
            return False, "", "pySim-shell timed out"
        except FileNotFoundError:
            return False, "", "pySim-shell.py not found"
        except Exception as e:
            return False, "", str(e)

    def authenticate(self, adm1: str, force: bool = False,
                     expected_iccid: Optional[str] = None) -> Tuple[bool, str]:
        """Authenticate with ADM1 key.

        Args:
            adm1: The ADM1 key.
            force: Force auth even with low attempts.
            expected_iccid: If provided, cross-verify the card's ICCID before
                authenticating. Prevents wrong-ADM1 lockout from mismatched
                card/data rows.
        """
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
            return ok, msg

        err = validate_adm1(adm1)
        if err:
            return False, err

        if self.cli_backend != CLIBackend.PYSIM:
            # Non-pySim backends not yet implemented
            logger.warning("authenticate(): non-pySim backend not implemented")
            return False, "Authentication not supported for this CLI backend"

        # Use pySim-shell with verify_adm to authenticate
        adm1_hex = self._adm1_to_hex(adm1)
        ok, stdout, stderr = self._run_pysim_shell(
            adm1_hex, 'verify_adm', timeout=15)

        if ok:
            self.authenticated = True
            self._authenticated_adm1_hex = adm1_hex
            logger.info("ADM1 authentication successful")
            return True, "Authentication successful"

        # Check for specific failure patterns
        combined = (stdout + '\n' + stderr).lower()
        if 'sw mismatch' in combined and '6982' in combined:
            return False, (
                "Authentication FAILED — wrong ADM1 key. "
                "Remaining attempts may be reduced. "
                "3 wrong attempts = permanent card lock!"
            )
        if 'sw mismatch' in combined and '6983' in combined:
            return False, (
                "Card is PERMANENTLY LOCKED — "
                "ADM1 authentication blocked (0 attempts remaining)"
            )

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
            f'update_binary_decoded \'{{"imsi": "{imsi}"}}\''  ,
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

    def program_card(self, card_data: Dict[str, str],
                     original_data: Optional[Dict[str, str]] = None
                     ) -> Tuple[bool, str]:
        """Program a card with the given parameters.

        Only writes fields that have changed relative to *original_data*
        (or ``self._original_card_data`` if not provided).  For empty
        cards where no original exists, all non-empty fields are written.

        Args:
            card_data: Dict of field values to write (IMSI, Ki, OPc, etc.).
            original_data: Optional baseline data for change detection.
                If None, uses self._original_card_data from the last detect.
        """
        if self._simulator:
            return self._simulator.program_card(card_data)
        if not self.authenticated:
            return False, "Not authenticated"
        if self.cli_backend != CLIBackend.PYSIM:
            return False, "Programming not supported for this CLI backend"
        if not self._authenticated_adm1_hex:
            return False, "No ADM1 key stored — re-authenticate first"

        # Determine what changed
        orig = original_data if original_data is not None else self._original_card_data
        if orig:
            changed = self._compute_changed_fields(card_data, orig)
        else:
            # No original (empty card) — write everything non-empty
            changed = {k: v.strip() for k, v in card_data.items() if v.strip()}

        if not changed:
            return True, "No changes to program — card data already matches"

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
                logger.warning("Ki changed but OPc not provided; skipping Ki/OPc write")
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

        # Warn about any remaining unhandled fields
        for key in changed:
            logger.warning("program_card: field '%s' has no write handler, skipped", key)

        if not commands:
            return True, "No programmable fields changed"

        # Execute via pySim-shell
        cmd_str = '\n'.join(commands)
        logger.info("Programming card: fields=%s", fields_written)
        logger.debug("pySim-shell commands:\n%s", cmd_str)

        ok, stdout, stderr = self._run_pysim_shell(
            self._authenticated_adm1_hex, cmd_str, timeout=30)

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
                return True, f"Card programmed and verified: {summary}"
            else:
                logger.warning("Card programmed but verification failed: %s", v_msg)
                return False, (
                    f"Programming commands sent ({summary}) but "
                    f"read-back verification FAILED.\n{v_msg}"
                )

        # Check for partial success by scanning stdout for errors
        combined = (stdout + '\n' + stderr).lower()
        if 'sw mismatch' in combined:
            error_detail = self._clean_pysim_error(stderr) if stderr else "write error"
            return False, f"Programming failed (write error): {error_detail}"

        error_msg = self._clean_pysim_error(stderr) if stderr else "Programming failed"
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
        return None

    def disconnect(self):
        if self._simulator:
            self._simulator.disconnect()
        self.authenticated = False
        self._authenticated_adm1_hex = None
        self._original_card_data = {}
        self.card_type = CardType.UNKNOWN
        self.card_info = {}

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

    def _parse_pysim_output(self, output: str):
        """Parse pySim-read output for card info.

        Extracts ICCID, IMSI, ACC, SPN, and FPLMN from pySim-read.py
        output.  These are public fields that don't require ADM1 auth.
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
        if fplmn_values:
            self.card_info['FPLMN'] = ';'.join(fplmn_values)
