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

import dataclasses
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from utils.validation import validate_adm1
from pysim_parser import parse_pysim_output as _parse_pysim_output_fn
from state_manager import ProgramOutcome, ProgramResult

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


def reset_pyscard() -> None:
    """Force _init_pyscard to re-run on next probe call.

    Used when the PC/SC system state changes (e.g. pcscd restarts, reader
    reconnects) and we need to force a fresh enumeration. Clears the module-level
    cache so _init_pyscard will attempt import and context establishment again.
    """
    global _pyscard_available, _smartcard_readers
    _pyscard_available = None
    _smartcard_readers = None
    logger.debug("pyscard cache cleared; next probe will re-initialize")


# ---------------------------------------------------------------------------
# Subprocess-based PC/SC probe
# ---------------------------------------------------------------------------
# The script is launched in a fresh interpreter so SCardConnect cannot stall
# the parent process.  Output is a single JSON line on stdout.

_PCSC_PROBE_SCRIPT = """\
import sys, json
try:
    from smartcard.System import readers
    from smartcard.Exceptions import NoCardException, CardConnectionException
except ImportError as e:
    print(json.dumps({"ok": False, "msg": "pyscard import failed: " + str(e)}))
    sys.exit(0)
reader_index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
try:
    rlist = readers()
except Exception as e:
    print(json.dumps({"ok": False, "msg": "PC/SC error: " + str(e)}))
    sys.exit(0)
if reader_index >= len(rlist):
    print(json.dumps({"ok": False, "msg": "reader index out of range"}))
    sys.exit(0)
reader = rlist[reader_index]
try:
    conn = reader.createConnection()
    conn.connect()
    atr = conn.getATR()
    conn.disconnect()
    print(json.dumps({"ok": True, "atr": " ".join("{:02X}".format(b) for b in atr)}))
except NoCardException:
    print(json.dumps({"ok": False, "msg": "No card in reader"}))
except CardConnectionException as e:
    print(json.dumps({"ok": False, "msg": str(e)}))
except Exception as e:
    print(json.dumps({"ok": False, "msg": str(e)}))
"""


def _pyscard_with_connection(reader, fn):
    """Open a PC/SC connection to *reader*, call ``fn(conn)``, then disconnect.

    This is the single canonical place that calls ``conn.connect()`` and
    ``conn.disconnect()``.  Callers supply the work to perform via *fn* and
    handle ``_NoCardException`` / ``_CardConnectionException`` themselves.

    ``fn`` receives the live ``CardConnection`` and may return any value;
    that value is returned to the caller.  Disconnect is guaranteed even if
    ``fn`` raises.
    """
    conn = reader.createConnection()
    conn.connect()
    try:
        return fn(conn)
    finally:
        conn.disconnect()


@dataclasses.dataclass
class _ProbeResult:
    """Internal result type for subprocess-based card presence probe."""
    available: bool   # True if the backend produced a definitive result
    present: bool     # True if a card is physically present
    message: str      # ATR hex string or error/reason text

    @staticmethod
    def card_present(atr: str) -> '_ProbeResult':
        return _ProbeResult(available=True, present=True, message=atr)

    @staticmethod
    def card_absent(reason: str) -> '_ProbeResult':
        return _ProbeResult(available=True, present=False, message=reason)

    @staticmethod
    def unavailable(reason: str) -> '_ProbeResult':
        return _ProbeResult(available=False, present=False, message=reason)


@dataclasses.dataclass
class _VerificationReport:
    """Internal classification of a post-write read-back result.

    Not a domain state — used only inside CardManager to decide which
    ProgramOutcome to surface.  Ki/OPc and HNET_PUBKEY are structurally unreadable;
    all other written fields are either verified, mismatched, or caused
    an error that prevented verification.
    """
    verified_fields: Tuple[str, ...] = dataclasses.field(default_factory=tuple)
    failed_fields: Tuple[str, ...] = dataclasses.field(default_factory=tuple)
    unreadable_fields: Tuple[str, ...] = dataclasses.field(default_factory=tuple)
    verification_error: Optional[str] = None
    readback_data: Dict[str, str] = dataclasses.field(default_factory=dict)


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


def _get_bundled_python() -> Optional[str]:
    """Find the Python interpreter bundled inside the app bundle (frozen mode only).

    Returns None in dev (non-frozen) mode.  In frozen mode, searches only
    inside the app bundle — never system paths or /usr/bin.

    Search order (first executable match wins):

    1. ``Contents/Frameworks/Python3.framework/Versions/*/bin/python3*``
       This is where a properly bundled Python framework installs its
       interpreter.  Phase 3 build script must ensure the framework is
       complete (not just the dylib) so a real executable exists here.

    2. ``Contents/MacOS/python3.9``, ``python3``, ``python``
       Optional fallback for a standalone interpreter copied by the
       build script alongside the SimGUI launcher.

    Phase 3 build-script requirement: ensure that after PyInstaller runs,
    ``Contents/Frameworks/Python3.framework/Versions/<ver>/bin/python3`` (or
    ``python3.9``) exists as an executable Mach-O binary inside the .app.
    The current build ships only the Python3.framework dylib; the ``bin/``
    subdirectory is absent.

    Returns None when no bundled interpreter is found.  Callers MUST NOT fall
    back to sys.executable or any system Python in frozen mode; they must
    surface a clear "Bundled pySim runtime incomplete" error instead.
    """
    import glob as _glob

    if not (getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')):
        return None

    # sys._MEIPASS is Contents/Resources; Contents/ is one level up.
    contents_dir = os.path.dirname(sys._MEIPASS)

    # 1. Preferred: Python3.framework bin/ directory (glob over version dirs).
    fw_bin_pattern = os.path.join(
        contents_dir,
        'Frameworks', 'Python3.framework', 'Versions', '*', 'bin', 'python3*',
    )
    for candidate in sorted(_glob.glob(fw_bin_pattern), reverse=True):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            logger.info("Found bundled Python interpreter (framework): %s", candidate)
            return candidate

    # 2. Fallback: standalone interpreter next to the SimGUI launcher.
    for rel in ('MacOS/python3.9', 'MacOS/python3', 'MacOS/python'):
        candidate = os.path.join(contents_dir, rel)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            logger.info("Found bundled Python interpreter (MacOS/): %s", candidate)
            return candidate

    logger.warning(
        "Frozen mode: no bundled Python interpreter found in %s. "
        "Phase 3 must ensure Python3.framework/Versions/*/bin/python3 "
        "exists as an executable inside the app bundle.",
        contents_dir,
    )
    return None


def _get_pysim_env() -> Optional[Dict[str, str]]:
    """Return a subprocess env dict with PYTHONPATH for bundled pySim.

    In frozen mode returns a copy of os.environ with PYTHONPATH prepended to
    include the bundled pySim scripts directory and pySim site-packages.
    In dev mode returns None so subprocess calls inherit the process env.
    """
    if not (getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')):
        return None

    pysim_dir = os.path.join(sys._MEIPASS, 'pysim')
    site_pkgs = os.path.join(sys._MEIPASS, 'pysim-site-packages')

    extra = [p for p in (pysim_dir, site_pkgs) if os.path.isdir(p)]
    if not extra:
        return None

    env = dict(os.environ)
    existing = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = os.pathsep.join(extra + ([existing] if existing else []))
    return env


def _get_probe_env() -> Optional[Dict[str, str]]:
    """Return subprocess env with PYTHONPATH for the PC/SC probe helper.

    In frozen mode: prepends sys._MEIPASS (where PyInstaller bundles all
    packages including smartcard/pyscard) to PYTHONPATH so the probe
    subprocess can import smartcard.  Also adds pysim-site-packages if
    present.  In dev mode returns None so the subprocess inherits the
    active process env (venv already on sys.path).
    """
    if not (getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')):
        return None

    meipass = sys._MEIPASS
    extra = [meipass]
    site_pkgs = os.path.join(meipass, 'pysim-site-packages')
    if os.path.isdir(site_pkgs):
        extra.append(site_pkgs)

    env = dict(os.environ)
    existing = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = os.pathsep.join(extra + ([existing] if existing else []))
    return env


def _inprocess_enabled() -> bool:
    """Return True unless SIMGUI_WORKER_INPROCESS=0 explicitly opts out."""
    return os.environ.get("SIMGUI_WORKER_INPROCESS") != "0"


def _find_cli_tool() -> Tuple[Optional[str], CLIBackend]:
    """Locate sysmo-usim-tool or pySim repo on the system.

    Returns (path, backend) where path is the tool directory and backend
    is the corresponding CLIBackend enum value.  Returns (None, NONE) if
    no tool is found.

    This function is the ONLY permitted platform-specific code in
    card_manager.py.  All SIM card logic, authentication, card detection,
    programming flows, and state transitions in this module are
    platform-free.  This function is a thin path-lookup adapter: it
    resolves a directory and returns it; it contains no SIM logic.

    Search priority (first match wins):

    1. PyInstaller bundle (``sys._MEIPASS/pysim``)
       macOS .app bundles created with PyInstaller embed pySim here.
       This path is only active when running as a frozen executable.

    2. ``SYSMO_USIM_TOOL_PATH`` environment variable
       Explicit override for the legacy sysmo-usim-tool backend.

    3. ``PYSIM_PATH`` environment variable
       Explicit override for pySim.  Set this to use a non-standard
       install location on any platform.

    4. Relative sibling path (``../../sysmo-usim-tool``)
       Finds sysmo-usim-tool if both repos are checked out side-by-side.

    5. ``~/sysmo-usim-tool`` — user home directory
    6. ``/opt/sysmo-usim-tool`` — system-wide install (Linux/Ubuntu)

    7. Relative sibling path (``../../pysim``)
       Finds pySim if both repos are checked out side-by-side.

    8. ``~/pysim`` — user home directory
       Default macOS source install location.

    9. ``/opt/pysim`` — system-wide install
       Default Ubuntu install location (created by scripts/install.sh).

    Do NOT add platform branches (``if sys.platform``, ``if _MACOS``,
    etc.) anywhere else in this module.  Path differences belong here
    only; SIM logic must remain unconditional.
    """
    # 1. PyInstaller bundle — active only in frozen .app executables.
    # When frozen, the bundle is the ONLY valid source.  Do NOT fall through
    # to ~/pysim or any other filesystem candidate if the bundle is absent.
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundle_pysim = os.path.join(sys._MEIPASS, 'pysim')
        if os.path.isdir(bundle_pysim):
            logger.info("Found pySim in PyInstaller bundle: %s", bundle_pysim)
            return bundle_pysim, CLIBackend.PYSIM
        logger.error(
            "Frozen mode: bundled pySim not found at %s. "
            "Rebuild the app to include pySim resources (SimGUI.spec datas).",
            bundle_pysim,
        )
        return None, CLIBackend.NONE

    # 2. SYSMO_USIM_TOOL_PATH env var — explicit sysmo-usim-tool override
    env_path = os.environ.get('SYSMO_USIM_TOOL_PATH')
    if env_path and os.path.isdir(env_path):
        logger.info("Found sysmo-usim-tool via env var: %s", env_path)
        return env_path, CLIBackend.SYSMO

    # 3. PYSIM_PATH env var — explicit pySim override (any platform)
    pysim_path = os.environ.get('PYSIM_PATH')
    if pysim_path and os.path.isdir(pysim_path):
        logger.info("Found pySim via env var: %s", pysim_path)
        return pysim_path, CLIBackend.PYSIM

    # 4–6. Common sysmo-usim-tool locations
    # platform_runtime.sysmo_search_dirs() provides the system-install path(s);
    # falls back to the hardcoded Ubuntu default when the module is absent or broken.
    sysmo_system_dirs = ['/opt/sysmo-usim-tool']
    try:
        import platform_runtime as _pr
        _dirs = _pr.sysmo_search_dirs()
        if isinstance(_dirs, list) and _dirs:
            sysmo_system_dirs = _dirs
    except Exception:
        pass
    for candidate in [
        os.path.join(os.path.dirname(__file__), '..', '..', 'sysmo-usim-tool'),
        os.path.expanduser('~/sysmo-usim-tool'),
    ] + sysmo_system_dirs:
        if os.path.isdir(candidate):
            logger.info("Found sysmo-usim-tool at %s", candidate)
            return os.path.abspath(candidate), CLIBackend.SYSMO

    # 7–9. Common pySim locations (~/pysim = macOS default, /opt/pysim = Ubuntu default)
    # platform_runtime.pysim_search_dirs() provides the system-install path(s);
    # falls back to the hardcoded Ubuntu default when the module is absent or broken.
    pysim_system_dirs = ['/opt/pysim']
    try:
        import platform_runtime as _pr
        _dirs = _pr.pysim_search_dirs()
        if isinstance(_dirs, list) and _dirs:
            pysim_system_dirs = _dirs
    except Exception:
        pass
    for candidate in [
        os.path.join(os.path.dirname(__file__), '..', '..', 'pysim'),
        os.path.expanduser('~/pysim'),
    ] + pysim_system_dirs:
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
    # Class-level default so __new__-based test fixtures see index 0.
    # Overridden per-instance by __init__.
    _pcsc_reader_index: int = 0

    def __init__(self, *, pcsc_reader_index: int = 0):
        if not isinstance(pcsc_reader_index, int) or pcsc_reader_index < 0:
            raise ValueError(
                f"pcsc_reader_index must be a non-negative integer, got {pcsc_reader_index!r}"
            )
        self._pcsc_reader_index: int = pcsc_reader_index
        self.cli_path: Optional[str]
        self.cli_backend: CLIBackend
        self.cli_path, self.cli_backend = _find_cli_tool()
        self._venv_python: Optional[str] = None
        if self.cli_path:
            self._venv_python = _find_venv_python(self.cli_path)
        self._bundled_python: Optional[str] = _get_bundled_python()
        self.card_type: CardType = CardType.UNKNOWN
        self.authenticated: bool = False
        self.card_info: Dict[str, str] = {}
        self._authenticated_adm1_hex: Optional[str] = None
        self._original_card_data: Optional[Dict[str, str]] = None  # None = no card detected yet
        self.card_blocked: bool = False   # True when ADM1 retry counter = 0
        self._adm1_remaining_attempts: Optional[int] = None
        self._safety_override_acknowledged: bool = False  # Set by authenticate(force=True)
        self._probe_thread: Optional[threading.Thread] = None  # in-flight PCSC probe guard
        self._worker_client = None
        self._cached_worker_capabilities: Optional[List[str]] = None
        self._current_session_id: Optional[str] = None
        self._current_card_gen: Optional[int] = None
        self._last_program_result: ProgramResult = ProgramResult()
        logger.info(
            "CardManager init: backend=%s, cli_path=%s, venv_python=%s, bundled_python=%s",
            self.cli_backend.name, self.cli_path, self._venv_python, self._bundled_python,
        )

    # ---- helpers -------------------------------------------------------

    def reset_pyscard(self) -> None:
        """Force pyscard re-initialization on next probe.

        Call this when the PC/SC system state may have changed (e.g. pcscd
        restarted, reader reconnected, or pyscard context became stale).
        """
        reset_pyscard()

    def set_worker_client(self, client) -> None:
        self._worker_client = client
        self._cached_worker_capabilities = None

    def _get_worker_capabilities(self) -> List[str]:
        if getattr(self, "_cached_worker_capabilities", None) is not None:
            return self._cached_worker_capabilities
        client = getattr(self, "_worker_client", None)
        if client is None:
            return []
        try:
            caps = client.capabilities()
        except Exception as exc:
            logger.warning("Worker capabilities() failed: %s", exc)
            return []
        self._cached_worker_capabilities = caps
        return caps

    def _try_worker_program_full(
        self, fields: Dict[str, str]
    ) -> Optional[Tuple[bool, str, str]]:
        client = getattr(self, "_worker_client", None)
        if client is None:
            logger.info("WORKER_DIAG program_full: skip reason=no_client")
            return None
        if not client.is_ready():
            logger.info("WORKER_DIAG program_full: skip reason=not_ready  last_error=%r",
                        getattr(client, "last_error", None))
            return None
        if not _inprocess_enabled():
            logger.info("WORKER_DIAG program_full: skip reason=env_off")
            return None
        if "program_full" not in self._get_worker_capabilities():
            logger.info("WORKER_DIAG program_full: skip reason=missing_capability  caps=%r",
                        self._get_worker_capabilities())
            return None
        logger.info("WORKER_DIAG program_full: routing via worker")
        try:
            resp = client.program_full(
                fields,
                self._authenticated_adm1_hex,
                reader_index=self._pcsc_reader_index,
                timeout=60.0,
            )
        except Exception as exc:
            logger.warning("Worker program_full transport error: %s", exc)
            return None
        if resp.get("worker_error"):
            logger.warning("Worker returned worker_error=True: %s", resp.get("error"))
            return None
        ok = bool(resp.get("ok"))
        stdout = resp.get("stdout", "")
        stderr = resp.get("stderr", "")
        return (ok, stdout, stderr)

    def _try_worker_program_delta(
        self, changed: Dict[str, str]
    ) -> Optional[Tuple[bool, str]]:
        """Attempt delta-write via the in-process worker.

        Returns (ok, msg) on definitive outcome (worker handled it, including failures
        after write_started=True). Returns None to signal fallback to pySim-shell.
        Never falls back after write_started=True.
        """
        client = getattr(self, "_worker_client", None)
        if client is None:
            logger.info("WORKER_DIAG program_delta: skip reason=no_client")
            return None
        if not client.is_ready():
            logger.info("WORKER_DIAG program_delta: skip reason=not_ready")
            return None
        if not _inprocess_enabled():
            logger.info("WORKER_DIAG program_delta: skip reason=env_off")
            return None
        caps = self._get_worker_capabilities()
        if "program_delta" not in caps:
            logger.info("WORKER_DIAG program_delta: skip reason=missing_capability  caps=%r", caps)
            return None
        session_id = self._current_session_id
        card_gen = self._current_card_gen
        if session_id is None or card_gen is None:
            logger.info("WORKER_DIAG program_delta: skip reason=no_session")
            return None
        # Check changed keys are all supported by the worker.
        try:
            supported = set(client.program_delta_capabilities())
        except Exception as exc:
            logger.warning("WORKER_DIAG program_delta: skip reason=caps_fetch_failed  err=%s", exc)
            return None
        unsupported = set(changed.keys()) - supported
        if unsupported:
            logger.info("WORKER_DIAG program_delta: skip reason=unsupported_fields  fields=%r",
                        sorted(unsupported))
            return None
        # Map CardType → pySim card type string using same table as _run_pysim_prog.
        pysim_type = 'auto'
        if self.card_type == CardType.SJA5:
            pysim_type = 'sysmoISIM-SJA5'
        elif self.card_type == CardType.SJA2:
            pysim_type = 'sysmoISIM-SJA2'
        elif self.card_type == CardType.SJS1:
            pysim_type = 'sysmoUSIM-SJS1'
        logger.info("WORKER_DIAG program_delta: routing via worker  fields=%r  card_type=%s",
                    sorted(changed.keys()), pysim_type)
        try:
            resp = client.program_delta(
                changed=changed,
                adm1_hex=self._authenticated_adm1_hex,
                reader_index=self._pcsc_reader_index,
                card_type=pysim_type,
                session_id=session_id,
                card_gen=card_gen,
                timeout=30.0,
            )
        except Exception as exc:
            logger.warning("WORKER_DIAG program_delta: transport error=%s", exc)
            return None  # pre-write transport failure — safe to fall back

        write_started = bool(resp.get("write_started"))

        if resp.get("worker_error"):
            if write_started:
                # Cannot fall back — card state unknown.
                msg = (f"Worker delta-write error after write started: "
                       f"{resp.get('error')}. Partial write possible.")
                self._last_program_result = ProgramResult(
                    outcome=ProgramOutcome.WRITE_FAILED,
                    message=msg,
                    failed_fields=tuple(resp.get("failed_fields", [])),
                )
                return False, msg
            logger.warning("WORKER_DIAG program_delta: worker_error before write, falling back: %s",
                           resp.get("error"))
            return None

        if not write_started:
            # Pre-write rejection (e.g. UNSUPPORTED_FIELDS, STALE_SESSION). Fall back.
            logger.info("WORKER_DIAG program_delta: fallback write_started=false  error=%r",
                        resp.get("error"))
            return None

        written = resp.get("written_fields", [])
        failed = resp.get("failed_fields", [])

        if not resp.get("ok"):
            msg = (f"Worker delta-write failed: {resp.get('error')}  "
                   f"written={written}  failed={failed}")
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_FAILED,
                message=msg,
                written_only_fields=tuple(written),
                failed_fields=tuple(failed),
            )
            return False, msg

        # Worker APDUs completed — return written fields so _program_nonempty_card
        # can run the same readback verification as the legacy pySim-shell path.
        # WRITE_OK_VERIFIED is never set here; the caller sets it after verify.
        return True, written

    def apply_worker_detect_result(self, result) -> None:
        """Apply a worker DetectResult to CardManager state.

        Maps result.card_type, populates card_info, snapshots original data,
        and records the worker session_id/card_gen for subsequent authenticate
        and program calls. Single canonical entry point for all worker detect
        results — no caller should set _current_session_id directly.
        """
        if result.card_type:
            self.card_type = self._PYSIM_CARD_TYPE_MAP.get(
                result.card_type.lower(), CardType.UNKNOWN
            )
        self.card_info = dict(result.fields) if result.fields else {}
        self._original_card_data = dict(self.card_info)
        # Session tracking — required for authenticate/program IPC calls.
        if result.session_id is not None:
            self._current_session_id = result.session_id
            self._current_card_gen = result.card_gen
            print(f"[CM] session updated session_id={result.session_id!r} card_gen={result.card_gen!r}")

    def get_last_program_result(self) -> ProgramResult:
        """Return the result of the most recent programming attempt.

        Returns ProgramResult with outcome=IDLE if no programming has been attempted yet.
        The returned object is immutable (frozen dataclass).
        """
        return self._last_program_result

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

        if getattr(sys, 'frozen', False):
            if self._bundled_python is None:
                return (False, "",
                        "Bundled pySim runtime incomplete: no Python interpreter "
                        "in app bundle. Phase 3 must copy python3 into MacOS/.")
            python_exe = self._bundled_python
        else:
            python_exe = self._venv_python or sys.executable
        pysim_env = _get_pysim_env()
        cmd = [python_exe, script_path] + list(args)
        logger.info("PY_LOAD_DIAG subprocess script=%s python=%s args=%r",
                    os.path.basename(script_path), os.path.basename(python_exe), list(args))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                cwd=self.cli_path, env=pysim_env,
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
        """Lightweight card presence check via PC/SC.

        Primary path: subprocess probe (killable; no stuck threads on
        stalled SCardConnect).  Falls back to the in-process thread path
        when the subprocess cannot be launched.

        Returns (True, atr_hex) if a card is physically present,
        (False, reason) otherwise.
        """
        if not _init_pyscard(self._venv_python):
            return False, 'NO_PYSCARD'

        try:
            rlist = _smartcard_readers()
        except Exception as exc:
            return False, f'PC/SC error: {exc}'

        if not rlist:
            return False, 'No smart-card reader detected'

        if self._pcsc_reader_index >= len(rlist):
            return False, (
                f'PCSC reader index {self._pcsc_reader_index} out of range '
                f'({len(rlist)} reader(s) detected)'
            )

        # Primary: in-process thread probe (no subprocess launch overhead).
        reader = rlist[self._pcsc_reader_index]
        ip_present, ip_msg = self._probe_with_timeout(reader)
        if ip_msg != 'PC/SC probe timed out':
            return ip_present, ip_msg

        # Fallback: subprocess-based probe when in-process timed out.
        sub = self._probe_via_subprocess(self._pcsc_reader_index, self._PROBE_TIMEOUT)
        if sub.available:
            return sub.present, sub.message
        return ip_present, ip_msg

    def _probe_via_subprocess(self, reader_index: int, timeout: float) -> '_ProbeResult':
        """Run the PC/SC probe in a fresh interpreter subprocess.

        The child process is killed on TimeoutExpired so SCardConnect cannot
        stall the parent.  Returns _ProbeResult.unavailable() when the
        subprocess cannot be launched, allowing the caller to fall back to
        the in-process thread path.
        """
        if getattr(sys, 'frozen', False):
            python_exe = self._bundled_python
        else:
            python_exe = self._venv_python or sys.executable
        if not python_exe:
            return _ProbeResult.unavailable("No Python interpreter for subprocess probe")
        logger.info("PY_LOAD_DIAG subprocess pcsc-probe python=%s reader=%d",
                    os.path.basename(python_exe), reader_index)
        try:
            proc = subprocess.run(
                [python_exe, '-c', _PCSC_PROBE_SCRIPT, str(reader_index)],
                capture_output=True, text=True, timeout=timeout,
                env=_get_probe_env(),
            )
            stdout = proc.stdout.strip()
            if not stdout:
                stderr_snippet = proc.stderr.strip()[:80]
                return _ProbeResult.unavailable(
                    f"Subprocess probe returned no output (stderr: {stderr_snippet})"
                )
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                return _ProbeResult.unavailable(
                    f"Malformed subprocess probe output: {stdout[:80]}"
                )
            if data.get("ok"):
                return _ProbeResult.card_present(data.get("atr", ""))
            msg = data.get("msg") or data.get("error") or "No card in reader"
            if "pyscard import failed" in msg or "No module named" in msg:
                return _ProbeResult.unavailable(msg)
            return _ProbeResult.card_absent(msg)
        except subprocess.TimeoutExpired:
            return _ProbeResult.card_absent("PC/SC probe timed out")
        except FileNotFoundError:
            return _ProbeResult.unavailable(f"Interpreter not found: {python_exe}")
        except Exception as exc:
            return _ProbeResult.unavailable(f"Subprocess probe failed: {exc}")

    # Configurable only for tests; production default is 2 s.
    _PROBE_TIMEOUT: float = 2.0

    def _probe_with_timeout(self, reader, timeout: Optional[float] = None) -> Tuple[bool, str]:
        """Run the SCardConnect/getATR sequence in a daemon thread.

        On macOS, SCardConnect can block indefinitely in the XPC/mach layer
        after a card is removed.  Running it in a throwaway daemon thread and
        joining with a deadline keeps the CardWatcher poll loop bounded.
        """
        if timeout is None:
            timeout = self._PROBE_TIMEOUT

        # In-flight guard: at most one blocked PCSC probe thread per CardManager.
        # If the previous probe thread is still alive (SCardConnect stalled),
        # return immediately rather than spawning another thread.
        if self._probe_thread is not None and self._probe_thread.is_alive():
            logger.debug("probe_with_timeout: previous probe still in-flight, skipping new thread")
            return False, 'PC/SC probe timed out'

        result: list = []

        def _run() -> None:
            try:
                atr = _pyscard_with_connection(
                    reader, lambda conn: conn.getATR()
                )
                result.append((True, ' '.join(f'{b:02X}' for b in atr)))
                print(f"[PROBE] pyscard_with_connection ok atr={result[-1][1]!r}")
            except _NoCardException:
                result.append((False, 'No card in reader'))
            except _CardConnectionException as exc:
                result.append((False, self._clean_pysim_error(str(exc))))
            except Exception as exc:
                result.append((False, self._clean_pysim_error(str(exc))))

        t = threading.Thread(target=_run, daemon=True, name='pcsc-probe')
        self._probe_thread = t
        t.start()
        t.join(timeout)
        if not result:
            logger.warning(
                "probe_card_presence: SCardConnect did not respond within %.1f s "
                "(macOS XPC stall after card removal — probe thread orphaned, "
                "watcher will retry next cycle)",
                timeout,
            )
            return False, 'PC/SC probe timed out'
        return result[0]

    # ---- card operations -----------------------------------------------

    def detect_card(self) -> Tuple[bool, str]:
        """Detect a card in the reader.

        Reads public card data only (ICCID, IMSI, etc.) via pySim-read.
        Does NOT check the ADM1 retry counter — that is deferred to
        ``authenticate()`` to avoid burning attempts on gialersim/blank
        cards where VERIFY CHV 0x0A is unsupported.
        """
        self.authenticated = False
        self.card_info = {}
        self.card_type = CardType.UNKNOWN
        self.card_blocked = False
        self._adm1_remaining_attempts = None

        if self.cli_path is None:
            return False, ("No CLI tool found. Install sysmo-usim-tool or "
                           "pySim and set the appropriate environment variable.")

        if self.cli_backend == CLIBackend.PYSIM:
            ok, stdout, stderr = self._run_cli('pySim-read.py', f'-p{self._pcsc_reader_index}')
            if not ok and 'protocolerror' in stderr.lower():
                # Transient PCSC lock contention — retry once after a short delay.
                time.sleep(1.0)
                ok, stdout, stderr = self._run_cli('pySim-read.py', f'-p{self._pcsc_reader_index}')
            if ok:
                self._parse_pysim_output(stdout)
                self._read_public_fields_via_shell()
                self._original_card_data = dict(self.card_info)  # snapshot
                return True, "Card detected via pySim"
            # Also check stdout - pySim sometimes prints data before failing
            if stdout:
                self._parse_pysim_output(stdout)
                if self.card_info.get('ICCID'):
                    self._read_public_fields_via_shell()
                    self._original_card_data = dict(self.card_info)
                    return True, "Card detected via pySim"
                # Blank/gialersim: pySim-read detected the card type but exited
                # non-zero because unprogrammed EFs cannot be read. card_type was
                # set by _parse_pysim_output. Treat as successful detection so
                # _read_and_notify takes the ICCID-absent path (no on_error call).
                if self.card_type != CardType.UNKNOWN:
                    self._original_card_data = dict(self.card_info)  # {} or partial
                    return True, "Card detected via pySim (blank)"
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
        'sw: 6a82',           # File not found (EF.UST, etc.)
        'sw: 6a83',           # Record not found in linear fixed file
        'got 6f00',           # "Expected 9000 and got 6f00"
        'got 6982',           # "Expected 9000 and got 6982"
        'got 6983',           # "Expected 9000 and got 6983"
        'got 6a82',           # "Expected 9000 and got 6a82" (file not found)
        'got 6a83',           # "Expected 9000 and got 6a83" (record not found)
        'failed to verify',   # pySim user-message for verify_adm failure
        'tries left',         # "N tries left" suffix in verify failure output
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

        if getattr(sys, 'frozen', False):
            if self._bundled_python is None:
                return (False, "",
                        "Bundled pySim runtime incomplete: no Python interpreter "
                        "in app bundle. Phase 3 must copy python3 into MacOS/.")
            python_exe = self._bundled_python
        else:
            python_exe = self._venv_python or sys.executable
        pysim_env = _get_pysim_env()
        cmd = [python_exe, script_path, f'-p{self._pcsc_reader_index}']
        if adm1_hex and self.card_type != CardType.GIALERSIM:
            # Gialersim cards: standard VERIFY ADM1 (CHV 0x0A) fails
            # with 6f00 — auth for those cards goes through pySim-prog.
            cmd += ['-A', adm1_hex]
        # Append 'quit' so the shell terminates cleanly.
        # NOTE: pySim-shell uses 'quit', NOT 'exit'.
        full_input = commands.rstrip('\n') + '\nquit\n'
        logger.debug("pySim-shell input:\n%s", full_input)
        _ct = getattr(self, "card_type", None)
        logger.info("PY_LOAD_DIAG subprocess pySim-shell python=%s reader=%d has_adm1=%s card_type=%s",
                    os.path.basename(python_exe), self._pcsc_reader_index,
                    bool(adm1_hex), _ct.name if _ct else "UNKNOWN")
        try:
            result = subprocess.run(
                cmd, input=full_input, capture_output=True, text=True,
                timeout=timeout, cwd=self.cli_path, env=pysim_env,
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

        if getattr(sys, 'frozen', False):
            if self._bundled_python is None:
                return (False, "",
                        "Bundled pySim runtime incomplete: no Python interpreter "
                        "in app bundle. Phase 3 must copy python3 into MacOS/.")
            python_exe = self._bundled_python
        else:
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

        cmd = [python_exe, script_path, f'-p{self._pcsc_reader_index}', '-t', pysim_type]

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
        pysim_env = _get_pysim_env()
        logger.info("PY_LOAD_DIAG subprocess pySim-prog python=%s card_type=%s reader=%d",
                    os.path.basename(python_exe), pysim_type, self._pcsc_reader_index)
        logger.info("pySim-prog command: %s",
                    ' '.join('***' if c in secrets else c for c in cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=self.cli_path, env=pysim_env,
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

    @staticmethod
    def _encode_spn_raw(spn: str) -> str:
        """Encode SPN to 17-byte raw hex string for update_binary.

        Layout: 0x01 (display flags: show in HPLMN) || 16-byte ASCII SPN
        field padded with 0xFF.  Returns 34 lowercase hex characters.
        """
        spn_bytes = spn.encode('ascii', errors='replace')[:16]
        padded = spn_bytes + b'\xff' * (16 - len(spn_bytes))
        return '01' + padded.hex()

    @staticmethod
    def _parse_spn_readback(stdout: str) -> str:
        """Extract SPN string from pySim-shell read_binary_decoded output.

        Handles both Python dict repr and JSON-style output from
        read_binary_decoded.  Returns empty string if not found.
        """
        match = re.search(r"['\"]spn['\"]:\s*['\"]([^'\"]*)['\"]", stdout or "")
        if match:
            return match.group(1)
        return ""

    def _write_spn_via_shell(
            self, spn: str, adm1_hex: str, timeout: int = 20
    ) -> Tuple[bool, str, str]:
        """Write EF.SPN via pySim-shell and verify with immediate read-back.

        Authenticates via verify_adm, writes raw update_binary to both
        MF/ADF.USIM/EF.SPN and MF/DF.GSM/EF.SPN, then reads back from
        ADF.USIM to confirm.

        Returns (write_ok, message, verified_spn).
        verified_spn is the SPN string read back; empty if not confirmed.
        """
        raw_hex = self._encode_spn_raw(spn)
        commands = (
            f'verify_adm --pin-is-hex {adm1_hex}\n'
            'select MF/ADF.USIM/EF.SPN\n'
            f'update_binary {raw_hex}\n'
            'select MF/DF.GSM/EF.SPN\n'
            f'update_binary {raw_hex}\n'
            'select MF/ADF.USIM/EF.SPN\n'
            'read_binary_decoded\n'
        )
        ok, stdout, stderr = self._run_pysim_shell_safe(commands, timeout=timeout)
        if not ok:
            logger.warning(
                "SPN shell write FAILED\n"
                "  stdout: %s\n"
                "  stderr: %s",
                stdout or "(empty)", stderr or "(empty)",
            )
            return False, "SPN write via pySim-shell failed", ""
        verified_spn = self._parse_spn_readback(stdout)
        logger.info(
            "SPN shell write OK; read-back=%r\n  stdout: %s",
            verified_spn, stdout or "(empty)",
        )
        return True, "SPN written", verified_spn

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
        if not _init_pyscard(self._venv_python):
            logger.debug("check_adm1_retry_counter: pyscard not available")
            return None

        try:
            rlist = _smartcard_readers()
            if not rlist:
                return None
            if self._pcsc_reader_index >= len(rlist):
                logger.warning(
                    "check_adm1_retry_counter: reader index %d out of range "
                    "(%d reader(s))", self._pcsc_reader_index, len(rlist)
                )
                return None
            reader = rlist[self._pcsc_reader_index]

            # VERIFY APDU without data: CLA=00, INS=20, P1=00,
            # P2=key_ref (0x0A for ADM1), no Lc/data.
            apdu = [0x00, 0x20, 0x00, self._ADM1_KEY_REF]
            data, sw1, sw2 = _pyscard_with_connection(
                reader, lambda conn: conn.transmit(apdu)
            )
            print(f"[ADM1-COUNTER] pyscard_with_connection sw={sw1:02X}{sw2:02X}")

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

    def _authenticate_via_worker(self, adm1_hex: str) -> Tuple[bool, str]:
        """Route authentication through the card worker subprocess."""
        if not self._current_session_id:
            return False, (
                "Worker session not ready — card may have been removed. Re-detect."
            )
        result = self._worker_client.authenticate(
            session_id=self._current_session_id,
            card_gen=self._current_card_gen,
            adm1_hex=adm1_hex,
            is_gialersim=(self.card_type == CardType.GIALERSIM),
        )
        if result.ok:
            self.authenticated = True
            self._authenticated_adm1_hex = adm1_hex
            if result.deferred:
                return True, (
                    "Authentication stored — ADM1 will be used during programming."
                )
            return True, "Authentication successful"

        err = result.error or ""
        if err == "AUTH_FAILED":
            return False, (
                "Authentication FAILED — wrong ADM1 key. "
                "3 wrong attempts = permanent card lock!"
            )
        if err == "CARD_BLOCKED":
            self.card_blocked = True
            self._adm1_remaining_attempts = 0
            return False, (
                "Card is PERMANENTLY LOCKED — "
                "ADM1 authentication blocked (0 attempts remaining). "
                "This card cannot be programmed."
            )
        if err == "STALE_SESSION":
            self._current_session_id = None
            self._current_card_gen = None
            return False, "Session expired — card may have changed. Re-detect."
        if err == "TRANSPORT_ERROR":
            return False, "Reader/transport error during authentication. Check card reader."
        if err == "WORKER_DEAD":
            return False, "Worker process died — restart the application."
        if err == "NO_PROFILE":
            return False, "No card profile available — re-detect the card."
        return False, f"Worker authentication error: {result.msg or err}"

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

        err = validate_adm1(adm1)
        if err:
            return False, err

        adm1_hex = self._adm1_to_hex(adm1)

        # --- Worker path (before any PCSC operations) ---
        if getattr(self, "_worker_client", None) is not None:
            return self._authenticate_via_worker(adm1_hex)

        # ICCID cross-verification safety check.
        # Skipped for blank/gialersim cards: the target ICCID in the CSV is
        # the one being *written* (not what the card already holds), and all
        # blank Fiskarheden cards share the same default ADM1 so a mismatch
        # cannot lock the wrong card.
        if expected_iccid is not None:
            _orig = self._original_card_data  # None=no card, {}=blank, {...}=data
            _is_gialersim = self.card_type == CardType.GIALERSIM
            # Blank: card WAS detected (_orig is not None) but has no ICCID/IMSI
            _is_blank = (
                _orig is not None
                and not _orig.get('ICCID')
                and not _orig.get('IMSI')
            )
            if not (_is_gialersim or _is_blank):
                card_iccid = self.read_iccid()
                if card_iccid and card_iccid != expected_iccid:
                    return False, (
                        f"ICCID mismatch! Card ICCID: {card_iccid} does not match "
                        f"expected: {expected_iccid}. Wrong card or wrong data row. "
                        f"Authentication aborted to prevent card lockout."
                    )

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
        # No card has been detected yet — _original_card_data is None until
        # detect_card() runs and takes a snapshot (even a blank card sets it to {})
        if self._original_card_data is None and not self.card_info:
            return False, "No SIM card detected. Insert a card and try again."

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

        # "Failed to verify chv_no" / "N tries left" \u2014 pySim user-message for
        # verify_adm failure.  pySim-shell prints this to stdout and exits 0;
        # _PYSIM_SHELL_CMD_ERRORS catches it and makes _run_pysim_shell_impl
        # return False, but we need an explicit check here to give a clear
        # error message with remaining-attempts info.
        if 'failed to verify' in combined or 'tries left' in combined:
            remaining = self.check_adm1_retry_counter()
            remaining_msg = ""
            if remaining is not None:
                remaining_msg = f" ({remaining} attempt(s) remaining)"
                if remaining == 0:
                    self.card_blocked = True
            return False, (
                f"Authentication FAILED \u2014 wrong ADM1 key.{remaining_msg} "
                f"3 wrong attempts = permanent card lock!"
            )

        error_msg = self._clean_pysim_error(stderr) if stderr else "Authentication failed"
        return False, f"Authentication failed: {error_msg}"

    def read_public_data(self) -> Optional[Dict[str, str]]:
        """Read public fields without authentication."""
        return self.card_info if self.card_info else None

    def read_protected_data(self) -> Optional[Dict[str, str]]:
        """Read protected fields (requires ADM1 auth)."""
        if not self.authenticated:
            return None
        # TODO: Real CLI read of Ki, OPc, etc.
        return {}

    def read_card_data(self) -> Optional[Dict[str, str]]:
        """Read basic card data (IMSI, ICCID, etc.)."""
        if not self.authenticated:
            return None
        return self.card_info if self.card_info else None

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
                     ) -> Tuple[bool, str, ProgramResult]:
        """Program a card with the given parameters.

        For **non-empty cards** (SJA5/SJA2 — already have ICCID/IMSI),
        only the fields that differ from *original_data* are written via
        ``pySim-shell.py`` (delta-write, authenticated with -A flag).

        For **empty / blank / gialersim cards**, all non-empty fields are
        written in a single ``pySim-prog.py`` invocation.

        Args:
            card_data: Dict of field values to write (IMSI, Ki, OPc, etc.).
            original_data: Optional baseline data for change detection.
                If None, uses self._original_card_data from the last detect.
        """
        if self.card_blocked:
            msg = (
                "Card is PERMANENTLY LOCKED \u2014 cannot program. "
                "Remove this card and insert a different one."
            )
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.ADM1_LOCKED, message=msg)
            return False, msg, self._last_program_result
        if not self.authenticated:
            msg = "Not authenticated"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.ADM1_AUTH_FAILED, message=msg)
            return False, msg, self._last_program_result
        if self.cli_backend != CLIBackend.PYSIM:
            msg = "Programming not supported for this CLI backend"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_FAILED, message=msg)
            return False, msg, self._last_program_result
        if not self._authenticated_adm1_hex:
            msg = "No ADM1 key stored \u2014 re-authenticate first"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.ADM1_AUTH_FAILED, message=msg)
            return False, msg, self._last_program_result

        # --- Pre-flight: verify ADM1 retry counter is safe ----------------
        # Skip this check if the user already forced past the safety
        # warning during authenticate() — asking twice is redundant.
        if not self._safety_override_acknowledged:
            remaining = self.check_adm1_retry_counter()
            if remaining is not None:
                if remaining == 0:
                    self.card_blocked = True
                    msg = (
                        "Card is PERMANENTLY LOCKED \u2014 "
                        "ADM1 retry counter is 0. Cannot program."
                    )
                    self._last_program_result = ProgramResult(
                        outcome=ProgramOutcome.ADM1_LOCKED, message=msg)
                    return False, msg, self._last_program_result
                if remaining < 2:
                    msg = (
                        f"DANGER: Only {remaining} ADM1 attempt(s) remaining. "
                        f"Programming aborted to protect the card. "
                        f"Re-authenticate first to confirm the key is correct."
                    )
                    self._last_program_result = ProgramResult(
                        outcome=ProgramOutcome.ADM1_AUTH_FAILED, message=msg)
                    return False, msg, self._last_program_result

        orig = original_data if original_data is not None else self._original_card_data
        empty_card = self._is_empty_card(original_data)

        if not empty_card and orig:
            # Non-empty card: delta-write only fields that changed.
            changed = self._compute_changed_fields(card_data, orig)
            # ICCID is factory-assigned on non-empty cards — never overwrite.
            changed.pop('ICCID', None)
            # Ki and OPc share the same EF; if either changed write both.
            if 'Ki' in changed or 'OPc' in changed:
                if card_data.get('Ki'):
                    changed['Ki'] = card_data['Ki']
                if card_data.get('OPc'):
                    changed['OPc'] = card_data['OPc']
        else:
            # Empty / blank / gialersim — write every non-empty field
            changed = {k: v.strip() for k, v in card_data.items() if v.strip()}

        changed.pop('ADM1', None)
        changed.pop('SPN', None)

        if not changed:
            msg = "No changes to program \u2014 card data already matches"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.NO_CHANGES, message=msg)
            return True, msg, self._last_program_result

        # Brief pause after retry-counter check to let the reader settle
        time.sleep(0.3)
        # Routing is by CARD TYPE first — "gialersim" is a distinct card family,
        # NOT merely a synonym for "empty/blank". A gialersim card always goes
        # native (managers/gialersim.py), whether blank or already personalised,
        # because pySim's GialerSim class writes Ki/OPc in the wrong (UICC) class
        # and omits the algorithm config, so its writes return 9000 but never
        # commit. Only non-gialersim cards fall through to the pySim paths:
        # empty/blank → pySim-prog (full write), non-empty → pySim-shell (delta).
        if self.card_type == CardType.GIALERSIM:
            ok, msg = self._program_gialersim_native(changed)
        elif empty_card:
            ok, msg = self._program_via_pysim_prog(changed)
        else:
            ok, msg = self._program_nonempty_card(card_data, changed)
        return ok, msg, self._last_program_result

    def _program_via_pysim_prog(self, fields: Dict[str, str]
                                 ) -> Tuple[bool, str]:
        """Program card using pySim-prog.py (all card types, all fields).

        Handles both initial blank-card programming and delta-writes to
        already-personalised cards.  pySim-prog selects the correct auth
        sequence per card type automatically (gialersim vs SJA5).
        """
        fields = fields.copy()
        fields.pop('ADM1', None)
        fields.pop('PIN1', None)
        fields.pop('PUK1', None)
        spn_skipped = 'SPN' in fields
        fields.pop('SPN', None)
        summary = ', '.join(k for k in fields) or 'all fields'
        logger.info("Programming card via pySim-prog: %s", summary)

        worker_result = self._try_worker_program_full(fields)
        if worker_result is None:
            ok, stdout, stderr = self._run_pysim_prog(
                fields, self._authenticated_adm1_hex, timeout=60)
        else:
            ok, stdout, stderr = worker_result

        if not ok:
            if 'not found' in stderr.lower():
                msg = "pySim-prog.py not found \u2014 cannot program card"
            else:
                error_msg = self._clean_pysim_error(stderr) if stderr else "Programming failed"
                msg = f"Programming failed: {error_msg}"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_FAILED,
                message=msg,
                failed_fields=tuple(fields.keys()),
                skipped_fields=("SPN",) if spn_skipped else (),
            )
            return False, msg

        report = self._verify_written_fields(fields)

        skipped = ("SPN",) if spn_skipped else ()

        if report.failed_fields:
            msg = (
                f"Programming succeeded but verification mismatch on: "
                f"{', '.join(report.failed_fields)}"
            )
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_OK_VERIFICATION_FAILED,
                message=msg,
                verified_fields=tuple(report.verified_fields),
                written_only_fields=tuple(report.unreadable_fields),
                skipped_fields=skipped,
                failed_fields=tuple(report.failed_fields),
            )
            return False, msg

        if report.verification_error is not None:
            msg = (
                f"Card programmed: {summary}\n"
                "(Verification pending \u2014 read the card again to confirm.)"
            )
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_OK_PENDING,
                message=msg,
                written_only_fields=tuple(report.unreadable_fields),
                skipped_fields=skipped,
            )
            return True, msg

        # Ki/OPc-only write: nothing was verified by read-back \u2014 pending
        # TODO(gialersim-selfcheck): Ki/OPc are READ=NEVER (EF_ARR record 0x13),
        # so we cannot read them back. A pySim-prog UPDATE returning 9000 does
        # NOT prove the write committed (see v0.7.3 dual-ADM fix \u2014 writes used to
        # return 9000 yet be silently discarded). To positively confirm the
        # write, add an OFFLINE USIM AUTHENTICATE self-check: after programming,
        # send RAND+AUTN computed from the Ki/OPc just written and confirm the
        # card returns 'DB' (success) or 'DC' (sync failure) \u2014 both prove the MAC
        # verified against the new keys. Do NOT attempt to read Ki/OPc directly.
        if not report.verified_fields and report.unreadable_fields:
            msg = (
                f"Card programmed: {summary}\n"
                "(Verification pending \u2014 read the card again to confirm.)"
            )
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_OK_PENDING,
                message=msg,
                written_only_fields=tuple(report.unreadable_fields),
                skipped_fields=skipped,
            )
            return True, msg

        # WRITE_OK_VERIFIED \u2014 merge card_info from read-back captured in report
        if report.readback_data:
            for k, v in report.readback_data.items():
                self.card_info[k] = v

        parts = []
        if report.verified_fields:
            parts.append(f"verified: {', '.join(report.verified_fields)}")
        if report.unreadable_fields:
            parts.append(f"written: {', '.join(report.unreadable_fields)}")
        msg = (
            f"Card programmed \u2014 {'; '.join(parts)}"
            if parts
            else "Card programmed\n(Verification pending \u2014 read the card again to confirm.)"
        )
        self._last_program_result = ProgramResult(
            outcome=ProgramOutcome.WRITE_OK_VERIFIED,
            message=msg,
            verified_fields=tuple(report.verified_fields),
            written_only_fields=tuple(report.unreadable_fields),
            skipped_fields=skipped,
            failed_fields=(),
        )
        return True, msg

    def _program_gialersim_native(self, fields: Dict[str, str]
                                  ) -> Tuple[bool, str]:
        """Program a gialersim card natively via ``managers/gialersim.py``.

        Thin adapter (no card logic lives here): resolve the reader, hand the
        verified recipe the fields it needs, and translate the outcome into a
        :class:`ProgramResult`.  All GSM-class APDU logic lives in the
        ``gialersim`` module.

        Ki and OPc are ``READ=NEVER`` and cannot be read back, so a successful
        run is reported as ``WRITE_OK_PENDING`` (ICCID/IMSI are confirmed by
        read-back; the keys require the offline AUTHENTICATE self-check tracked
        as ``TODO(gialersim-selfcheck)``).  A ``9000`` on a Ki write does NOT
        prove the key committed.
        """
        from managers import gialersim

        # gialersim always writes the full identity set; SPN/FPLMN are not part
        # of the verified recipe and are intentionally not written here (see
        # TODO(gialersim-spn-fplmn) in docs/TODO.md).
        skipped = tuple(k for k in ("SPN", "FPLMN") if fields.get(k))
        required = ("ICCID", "IMSI", "Ki", "OPc")
        missing = [k for k in required if not fields.get(k)]
        if missing:
            msg = f"Cannot program gialersim: missing {', '.join(missing)}"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_FAILED, message=msg,
                failed_fields=tuple(required), skipped_fields=skipped)
            return False, msg

        if not _init_pyscard(self._venv_python):
            msg = "Cannot program gialersim: PC/SC (pyscard) unavailable"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_FAILED, message=msg,
                skipped_fields=skipped)
            return False, msg

        try:
            rlist = _smartcard_readers()
            if not rlist or self._pcsc_reader_index >= len(rlist):
                raise gialersim.GialerSimError("card reader not available")
            reader = rlist[self._pcsc_reader_index]
            iccid_ok, imsi_ok = gialersim.program_reader(
                reader,
                iccid=fields["ICCID"],
                imsi=fields["IMSI"],
                ki=fields["Ki"],
                opc=fields["OPc"],
                acc=fields.get("ACC") or "0001",
            )
        except gialersim.GialerSimError as exc:
            msg = f"gialersim programming failed: {exc}"
            logger.error(msg)
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_FAILED, message=msg,
                failed_fields=("ICCID", "IMSI", "Ki", "OPc"),
                skipped_fields=skipped)
            return False, msg
        except Exception as exc:  # noqa: BLE001 — surface transport errors
            msg = f"gialersim programming failed (transport): {exc}"
            logger.error(msg)
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_FAILED, message=msg,
                failed_fields=("ICCID", "IMSI", "Ki", "OPc"),
                skipped_fields=skipped)
            return False, msg

        readback_failed = [
            name for name, ok in (("ICCID", iccid_ok), ("IMSI", imsi_ok))
            if not ok
        ]
        if readback_failed:
            msg = ("gialersim programmed but read-back mismatch on: "
                   + ", ".join(readback_failed))
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_OK_VERIFICATION_FAILED, message=msg,
                verified_fields=tuple(
                    n for n in ("ICCID", "IMSI") if n not in readback_failed),
                written_only_fields=("Ki", "OPc"),
                failed_fields=tuple(readback_failed),
                skipped_fields=skipped)
            return False, msg

        # ICCID/IMSI confirmed; Ki/OPc written but structurally unverifiable.
        # TODO(gialersim-selfcheck): add an offline USIM AUTHENTICATE self-check
        # (RAND+AUTN from the just-written Ki/OPc; 'DB'/'DC' proves the MAC) to
        # promote this to WRITE_OK_VERIFIED. Do NOT read Ki/OPc directly.
        self.card_info["ICCID"] = fields["ICCID"]
        self.card_info["IMSI"] = fields["IMSI"]
        msg = ("Card programmed — verified: ICCID, IMSI; written: Ki, OPc\n"
               "(Ki/OPc are READ=NEVER — confirm on the network via "
               "authentication.)")
        self._last_program_result = ProgramResult(
            outcome=ProgramOutcome.WRITE_OK_PENDING, message=msg,
            verified_fields=("ICCID", "IMSI"),
            written_only_fields=("Ki", "OPc"),
            skipped_fields=skipped)
        return True, msg

    # ------------------------------------------------------------------
    # pySim-shell write command builders (non-empty / SJA5 cards)
    # ------------------------------------------------------------------

    @staticmethod
    def _pysim_write_imsi(imsi: str) -> List[str]:
        """Commands to write IMSI via pySim-shell."""
        return [
            'select MF/ADF.USIM/EF.IMSI',
            f'update_binary_decoded \'{{"imsi": "{imsi}"}}\'',
        ]

    @staticmethod
    def _pysim_write_ki_opc(ki: str, opc: str) -> List[str]:
        """Commands to write Ki and OPc via pySim-shell."""
        import json as _json
        payload = _json.dumps({
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
    def _pysim_write_fplmn(fplmn_str: str) -> List[str]:
        """Commands to write FPLMN list via pySim-shell under ADF.USIM."""
        import json as _json
        plmns = [p.strip() for p in fplmn_str.split(';') if p.strip()]
        plmn_list = []
        for p in plmns:
            if len(p) in (5, 6):
                plmn_list.append({"mcc": p[:3], "mnc": p[3:]})
        payload = _json.dumps(plmn_list)
        return [
            'select MF',
            'select ADF.USIM',
            'select EF.FPLMN',
            f"update_binary_decoded '{payload}'",
        ]

    @staticmethod
    def _normalize_fplmn(fplmn_str: str) -> frozenset:
        """Normalise FPLMN string to a frozenset for order-independent comparison."""
        if not fplmn_str:
            return frozenset()
        return frozenset(
            p.strip().upper().replace('F', '').replace(':', '') for p in fplmn_str.replace(',', ';').split(';') if p.strip()
        )

    @staticmethod
    def _pysim_write_acc(acc: str) -> List[str]:
        """Commands to write ACC via pySim-shell."""
        acc_hex = acc.strip().lower().zfill(4)
        return [
            'select MF/ADF.USIM/EF.ACC',
            f'update_binary {acc_hex}',
        ]

    @staticmethod
    def _pysim_write_suci(suci_enabled: bool) -> List[str]:
        """Commands to set SUCI service flag via pySim-shell.

        Enables: activate service 124, deactivate service 125
        Disables: deactivate service 124, activate service 125
        """
        if suci_enabled:
            return [
                'select MF',
                'select ADF.USIM',
                'select EF.UST',
                'read_binary_decoded',
                'ust_service_activate 124',
                'ust_service_deactivate 125',
                'read_binary_decoded',
            ]
        else:
            return [
                'select MF',
                'select ADF.USIM',
                'select EF.UST',
                'read_binary_decoded',
                'ust_service_deactivate 124',
                'ust_service_activate 125',
                'read_binary_decoded',
            ]

    @staticmethod
    def _pysim_read_suci() -> List[str]:
        """Commands to read SUCI service states from EF.UST for verification."""
        return [
            'select MF',
            'select ADF.USIM',
            'select EF.UST',
            'read_binary_decoded',
        ]

    @staticmethod
    def _parse_suci_readback(output: str) -> bool:
        """Parse EF.UST read_binary_decoded output to extract SUCI service state.

        Returns True if service 124 is active AND service 125 is inactive.
        Returns False if parsing fails or services are not in expected state.
        """
        if not output:
            logger.info("[SUCI-PARSE] output is empty")
            return False
        try:
            import json as _json
            for line in output.splitlines():
                line = line.strip()
                if not line.startswith('{'):
                    continue
                data = _json.loads(line)
                if isinstance(data, dict):
                    service_124 = data.get(124) or data.get('124')
                    service_125 = data.get(125) or data.get('125')
                    logger.info("[SUCI-PARSE] service_124=%s service_125=%s", service_124, service_125)
                    if service_124 is not None and service_125 is not None:
                        result = bool(service_124) and not bool(service_125)
                        logger.info("[SUCI-PARSE] result: bool(124)=%s and not bool(125)=%s -> %s",
                                    bool(service_124), not bool(service_125), result)
                        return result
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("[SUCI-PARSE] parse error: %s", e)
            pass
        logger.warning("[SUCI-PARSE] no valid service data found, returning False")
        return False

    @staticmethod
    def _pysim_write_suci_calc_info(
            hnet_pubkey: str,
            prot_scheme: int = 1,
            routing_ind: str = "00",
            pubkey_id: int = 1
    ) -> List[str]:
        """Commands to write SUCI Calc Info via pySim-shell (SJA5 only).

        Writes hnet_pubkey_list with protection scheme and routing indicator.
        Includes a DF.5GS read_binary_decoded for verification.
        """
        import json as _json
        payload = _json.dumps({
            "prot_scheme_id_list": [
                {"priority": 0, "identifier": prot_scheme, "key_index": pubkey_id}
            ],
            "hnet_pubkey_list": [
                {"hnet_pubkey_identifier": pubkey_id, "hnet_pubkey": hnet_pubkey}
            ]
        })
        return [
            'select MF',
            'select ADF.USIM',
            'select DF.5GS',
            'select EF.SUCI_Calc_Info',
            f"update_binary_decoded '{payload}'",
            'read_binary_decoded',
            # Read DF.5GS for verification that SUCI_Calc_Info exists
            'select MF',
            'select ADF.USIM',
            'select DF.5GS',
            'read_binary_decoded',
        ]

    @staticmethod
    def _pysim_read_suci_calc_info() -> List[str]:
        """Commands to read SUCI Calc Info for verification (SJA5 only)."""
        return [
            'select MF',
            'select ADF.USIM',
            'select DF.5GS',
            'select EF.SUCI_Calc_Info',
            'read_binary_decoded',
        ]

    @staticmethod
    def _pysim_read_df5gs() -> List[str]:
        """Commands to read DF.5GS directory for verification (SJA5 only)."""
        return [
            'select MF',
            'select ADF.USIM',
            'select DF.5GS',
            'read_binary_decoded',
        ]

    @staticmethod
    def _parse_suci_calc_info(output: str) -> str:
        """Parse SUCI Calc Info read_binary_decoded output to extract hnet_pubkey.

        Returns the hnet_pubkey (hex string) if found, empty string otherwise.
        """
        if not output:
            return ""
        try:
            import json as _json
            # Try parsing the entire output as JSON first (multi-line)
            data = _json.loads(output)
            if isinstance(data, dict):
                pubkey_list = data.get('hnet_pubkey_list', [])
                if isinstance(pubkey_list, list) and len(pubkey_list) > 0:
                    return pubkey_list[0].get('hnet_pubkey', '')
            # Fallback: try line-by-line parsing for single-line JSON
            for line in output.splitlines():
                line = line.strip()
                if not line.startswith('{'):
                    continue
                data = _json.loads(line)
                if isinstance(data, dict):
                    pubkey_list = data.get('hnet_pubkey_list', [])
                    if isinstance(pubkey_list, list) and len(pubkey_list) > 0:
                        return pubkey_list[0].get('hnet_pubkey', '')
        except (ValueError, TypeError, KeyError):
            pass
        return ""

    @staticmethod
    def _parse_df5gs_readback(output: str) -> bool:
        """Parse DF.5GS read_binary_decoded output to verify directory exists.

        Returns True if DF.5GS structure is valid, False otherwise.
        """
        if not output:
            logger.warning("[DF.5GS-VERIFY] DF.5GS readback output is empty")
            return False
        try:
            import json as _json
            # Try parsing the entire output as JSON first (multi-line)
            data = _json.loads(output)
            if isinstance(data, dict) and 'file_identifier' in data:
                logger.info("[DF.5GS-VERIFY] DF.5GS structure is valid")
                return True
            # Fallback: try line-by-line parsing for single-line JSON
            for line in output.splitlines():
                line = line.strip()
                if not line.startswith('{'):
                    continue
                data = _json.loads(line)
                if isinstance(data, dict) and 'file_identifier' in data:
                    logger.info("[DF.5GS-VERIFY] DF.5GS structure is valid")
                    return True
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("[DF.5GS-VERIFY] parse error: %s", e)
        logger.warning("[DF.5GS-VERIFY] DF.5GS structure validation failed")
        return False

    def _program_nonempty_card(self, card_data: Dict[str, str],
                               changed: Dict[str, str]
                               ) -> Tuple[bool, str]:
        """Delta-write to a non-empty (SJA5/SJA2) card via pySim-shell.

        Attempts worker path first (lines 2096\u20132144; supports multiple fields).
        Legacy path (lines 2146+) writes IMSI, FPLMN, and SUCI.
        Ki/OPc and ACC are not programmable on non-empty cards.

        SUCI Programming (5G Privacy on SJA5):
          - SUCI field (bool): Enable/disable 5G SUCI privacy service table
            Activates EF.UST service 124, deactivates service 125 when true
          - HNET_PUBKEY field (hex): Home network public key for SUCI calculation
            Writes to DF.5GS/EF.SUCI_Calc_Info with protection scheme and key index
          - Optional SUCI_PROT_SCHEME (int, default 1): Protection scheme identifier
          - Optional SUCI_ROUTING_IND (str, default '00'): Routing indicator
          - Optional SUCI_PUBKEY_ID (int, default 1): Public key identifier

        Both SUCI service table and HNET_PUBKEY are written in a single pySim-shell
        session. Post-write verification is skipped (cryptographic keys are
        structurally unreadable and cause PCSC contention if verification attempted).
        """
        worker_result = self._try_worker_program_delta(changed)
        if worker_result is not None:
            w_ok, w_data = worker_result
            if not w_ok:
                return False, w_data  # terminal failure, _last_program_result already set
            # Worker APDUs succeeded. w_data is the list of written field names.
            # Run the same readback verification as the legacy pySim-shell path.
            written_fields = list(w_data)
            summary = ', '.join(written_fields)
            verify_data = {f: changed[f] for f in written_fields if f in changed}
            logger.info("Worker delta write OK (%s); running readback verification", summary)
            report = self._verify_written_fields(verify_data)

            if report.failed_fields:
                msg = (f"Programming succeeded but verification mismatch on: "
                       f"{', '.join(report.failed_fields)}")
                self._last_program_result = ProgramResult(
                    outcome=ProgramOutcome.WRITE_OK_VERIFICATION_FAILED,
                    message=msg,
                    verified_fields=tuple(report.verified_fields),
                    failed_fields=tuple(report.failed_fields),
                    written_only_fields=(),
                    skipped_fields=(),
                )
                return False, msg

            if report.verification_error is not None:
                msg = (f"Card programmed: {summary}\n"
                       "(Verification pending — read the card again to confirm.)")
                self._last_program_result = ProgramResult(
                    outcome=ProgramOutcome.WRITE_OK_PENDING,
                    message=msg,
                    written_only_fields=(),
                    skipped_fields=(),
                )
                return True, msg

            if report.readback_data:
                for k, v in report.readback_data.items():
                    self.card_info[k] = v
            msg = f"Card programmed and verified: {summary}"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_OK_VERIFIED,
                message=msg,
                verified_fields=tuple(report.verified_fields),
                written_only_fields=(),
                skipped_fields=(),
            )
            return True, msg

        commands: List[str] = []
        fields_written: List[str] = []

        if 'IMSI' in changed:
            commands.extend(self._pysim_write_imsi(changed['IMSI']))
            fields_written.append('IMSI')

        if 'FPLMN' in changed:
            commands.extend(self._pysim_write_fplmn(changed['FPLMN']))
            fields_written.append('FPLMN')

        # Track if SUCI is being enabled so we know to write HNET_PUBKEY
        suci_enabled = False
        if 'SUCI' in changed:
            # Write EF.UST service table: activate service 124 (SUCI enabled),
            # deactivate service 125 (legacy mode off). This enables 5G SUCI
            # privacy if the card also has HNET_PUBKEY configured.
            suci_enabled = changed['SUCI'].lower() in ('true', 'yes', '1', 'enabled')
            ust_commands = self._pysim_write_suci(suci_enabled)
            logger.info("[EF.UST-PROGRAM] SUCI=%s commands=%s", suci_enabled, ust_commands)
            commands.extend(ust_commands)
            fields_written.append('SUCI')

        # Write HNET_PUBKEY if: (1) it's in changed delta, OR (2) SUCI is being
        # enabled AND HNET_PUBKEY is present in the full data. This ensures the
        # key is written when SUCI is activated, even if the key wasn't changed.
        hnet_pubkey_in_data = changed.get('HNET_PUBKEY', '').strip() if 'HNET_PUBKEY' in changed else (
            card_data.get('HNET_PUBKEY', '').strip() if suci_enabled else ''
        )
        if hnet_pubkey_in_data and self.card_type == CardType.SJA5:
            # Write SUCI calculation parameters: home network public key and
            # protection scheme to DF.5GS/EF.SUCI_Calc_Info. Works alongside
            # EF.UST service table activation (SUCI field above) to enable
            # 5G SUCI privacy. Both writes execute in same pySim-shell session.
            prot_scheme = int(changed.get('SUCI_PROT_SCHEME', card_data.get('SUCI_PROT_SCHEME', 1)))
            routing_ind = changed.get('SUCI_ROUTING_IND', card_data.get('SUCI_ROUTING_IND', '00')).strip()
            pubkey_id = int(changed.get('SUCI_PUBKEY_ID', card_data.get('SUCI_PUBKEY_ID', 1)))
            commands.extend(self._pysim_write_suci_calc_info(
                hnet_pubkey_in_data, prot_scheme, routing_ind, pubkey_id))
            fields_written.append('HNET_PUBKEY')

        if not commands:
            msg = "No programmable fields changed"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.NO_CHANGES,
                message=msg,
            )
            return True, msg

        cmd_str = '\n'.join(commands)
        logger.info("Programming non-empty card via pySim-shell: fields=%s", fields_written)
        logger.info("pySim-shell commands (%d total):\n%s", len(commands), cmd_str)

        # Detailed logging of exact sequences for SUCI/HNET_PUBKEY
        if 'SUCI' in fields_written:
            logger.info("[SUCI-SEQUENCE] EF.UST programming sequence:")
            logger.info("[SUCI-SEQUENCE]   select MF")
            logger.info("[SUCI-SEQUENCE]   select ADF.USIM")
            logger.info("[SUCI-SEQUENCE]   select EF.UST")
            logger.info("[SUCI-SEQUENCE]   read_binary_decoded")
            logger.info("[SUCI-SEQUENCE]   ust_service_activate 124")
            logger.info("[SUCI-SEQUENCE]   ust_service_deactivate 125")
            logger.info("[SUCI-SEQUENCE]   read_binary_decoded")
        if 'HNET_PUBKEY' in fields_written:
            logger.info("[HNET_PUBKEY-SEQUENCE] DF.5GS/EF.SUCI_Calc_Info programming sequence:")
            logger.info("[HNET_PUBKEY-SEQUENCE]   select MF")
            logger.info("[HNET_PUBKEY-SEQUENCE]   select ADF.USIM")
            logger.info("[HNET_PUBKEY-SEQUENCE]   select DF.5GS")
            logger.info("[HNET_PUBKEY-SEQUENCE]   select EF.SUCI_Calc_Info")
            logger.info("[HNET_PUBKEY-SEQUENCE]   update_binary_decoded <payload with hnet_pubkey>")
            logger.info("[HNET_PUBKEY-SEQUENCE]   read_binary_decoded")

        # Release the in-process PCSC transport before spawning pySim-shell.
        # The worker holds an exclusive PCSC lock via _session["sl"]; without
        # releasing it the subprocess hits Sharing Violation (0x8010000B).
        # The watcher will re-detect the card naturally on its next poll.
        _wc = getattr(self, "_worker_client", None)
        if _wc is not None and _wc.is_ready():
            try:
                _wc.release_session()
                logger.info("[PCSC-RELEASE] in-process session released before pySim-shell")
            except Exception as _exc:
                logger.warning("[PCSC-RELEASE] release_session failed (non-fatal): %s", _exc)

        ok, stdout, stderr = self._run_pysim_shell(
            self._authenticated_adm1_hex, cmd_str, timeout=30)

        logger.info("[PROGRAM-SHELL] pySim-shell returned ok=%s stdout_len=%d stderr_len=%d",
                    ok, len(stdout or ''), len(stderr or ''))
        if 'SUCI' in fields_written or 'HNET_PUBKEY' in fields_written:
            # Log EF.UST and HNET_PUBKEY programming output in detail
            if stdout:
                logger.info("[PROGRAM-SHELL-SUCI] stdout (first 5000 chars):\n%s", stdout[:5000])
            if stderr:
                logger.info("[PROGRAM-SHELL-SUCI] stderr (first 5000 chars):\n%s", stderr[:5000])
            # Parse and log EF.UST read_binary_decoded output (service table state)
            if stdout and 'read_binary_decoded' in cmd_str.lower():
                # Extract all JSON blocks (EF.UST, DF.5GS/EF.SUCI_Calc_Info, and DF.5GS)
                lines = stdout.split('\n')
                json_blocks = []
                current_block = []
                for line in lines:
                    if line.strip().startswith('{'):
                        current_block = [line]
                    elif line.strip().endswith('}') and current_block:
                        current_block.append(line)
                        json_blocks.append('\n'.join(current_block))
                        current_block = []
                    elif current_block:
                        current_block.append(line)

                # Log EF.UST state and DF.5GS verification
                if json_blocks and 'HNET_PUBKEY' in fields_written:
                    # With HNET_PUBKEY: expect EF.UST, SUCI_Calc_Info read, and DF.5GS reads
                    if len(json_blocks) >= 3:
                        logger.info("[EF.UST-STATE] Service table state after write:\n%s", json_blocks[0][:1000])
                        logger.info("[HNET_PUBKEY-STATE] SUCI Calc Info state after write:\n%s", json_blocks[1][:1000])
                        # Verify hnet_pubkey is present in SUCI_Calc_Info
                        suci_calc_json = json_blocks[1]
                        if 'hnet_pubkey' in suci_calc_json.lower():
                            logger.info("[HNET_PUBKEY-VERIFY] HNET_PUBKEY successfully written to DF.5GS/EF.SUCI_Calc_Info")
                        # Verify DF.5GS structure
                        df5gs_json = json_blocks[-1]
                        self._parse_df5gs_readback(df5gs_json)
                        logger.info("[DF.5GS-STATE] DF.5GS directory state after write:\n%s", df5gs_json[:1000])
                    elif len(json_blocks) >= 2:
                        logger.info("[EF.UST-STATE] Service table state after write:\n%s", json_blocks[0][:1000])
                        logger.info("[HNET_PUBKEY-STATE] SUCI Calc Info state after write:\n%s", json_blocks[1][:1000])
                elif json_blocks:
                    logger.info("[EF.UST-STATE] Service table state after write:\n%s", json_blocks[-1][:1000])
            # Check for errors in EF.UST or SUCI_Calc_Info writes
            combined_lower = (stdout + stderr).lower() if (stdout or stderr) else ''
            if 'ef.ust' in combined_lower:
                logger.info("[EF.UST-DEBUG] pySim-shell processed EF.UST commands")
            if 'ust_service' in combined_lower:
                logger.info("[EF.UST-DEBUG] pySim-shell ust_service output detected")
            if 'df.5gs' in combined_lower or 'df5gs' in combined_lower:
                logger.info("[DF.5GS-DEBUG] pySim-shell processed DF.5GS commands")
            if 'read_binary_decoded' in combined_lower:
                logger.info("[EF.UST-DEBUG] pySim-shell read_binary_decoded output present (verifying state)")
            if 'error' in combined_lower or 'failed' in combined_lower or 'exception' in combined_lower:
                logger.warning("[PROGRAM-SHELL-SUCI] ERROR PATTERN DETECTED in output")
                # Additional detail for EF.UST failures
                if ('select ef.ust' in combined_lower or 'ust_service' in combined_lower or
                    '6a82' in combined_lower or '6a83' in combined_lower):
                    logger.warning("[EF.UST-ERROR] EF.UST/ust_service command failed with: %s",
                                 combined_lower[:500])
                # Additional detail for DF.5GS failures
                if ('select df.5gs' in combined_lower or 'df5gs' in combined_lower or
                    '6a82' in combined_lower):
                    logger.warning("[DF.5GS-ERROR] DF.5GS selection or command failed: %s",
                                 combined_lower[:500])

        if ok:
            summary = ', '.join(fields_written)
            verify_data = {f: changed[f] for f in fields_written}
            report = self._verify_written_fields(verify_data)

            if report.failed_fields:
                msg = (
                    f"Programming succeeded but verification mismatch on: "
                    f"{', '.join(report.failed_fields)}"
                )
                self._last_program_result = ProgramResult(
                    outcome=ProgramOutcome.WRITE_OK_VERIFICATION_FAILED,
                    message=msg,
                    verified_fields=tuple(report.verified_fields),
                    failed_fields=tuple(report.failed_fields),
                    written_only_fields=(),
                    skipped_fields=(),
                )
                return False, msg

            if report.verification_error is not None:
                msg = (
                    f"Card programmed: {summary}\n"
                    "(Verification pending — read the card again to confirm.)"
                )
                self._last_program_result = ProgramResult(
                    outcome=ProgramOutcome.WRITE_OK_PENDING,
                    message=msg,
                    written_only_fields=(),
                    skipped_fields=(),
                )
                return True, msg

            if report.readback_data:
                for k, v in report.readback_data.items():
                    self.card_info[k] = v
            msg = f"Card programmed and verified: {summary}"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_OK_VERIFIED,
                message=msg,
                verified_fields=tuple(report.verified_fields),
                written_only_fields=(),
                skipped_fields=(),
            )
            return True, msg

        combined = (stdout + '\n' + stderr).lower()
        # ADM1 auth failure detected in pySim-shell output (even with exit 0).
        # This is a safety guard: primary protection is authenticate() refusing
        # to set authenticated=True; this catches the residual case where the
        # -A flag auth attempt during programming itself fails.
        if 'failed to verify' in combined or 'tries left' in combined:
            remaining = self.check_adm1_retry_counter()
            remaining_msg = ""
            if remaining is not None:
                remaining_msg = f" ({remaining} attempt(s) remaining)"
                if remaining == 0:
                    self.card_blocked = True
            msg = (
                f"Programming ABORTED — ADM1 authentication failed.{remaining_msg} "
                f"3 wrong attempts = permanent card lock!"
            )
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_FAILED,
                message=msg,
                failed_fields=tuple(fields_written),
            )
            return False, msg

        if 'sw mismatch' in combined:
            error_detail = self._clean_pysim_error(stderr) if stderr else "write error"
            msg = f"Programming failed (write error): {error_detail}"
            self._last_program_result = ProgramResult(
                outcome=ProgramOutcome.WRITE_FAILED,
                message=msg,
                failed_fields=tuple(fields_written),
            )
            return False, msg

        error_msg = self._clean_pysim_error(stderr) if stderr else "Programming failed"
        msg = f"Programming failed: {error_msg}"
        self._last_program_result = ProgramResult(
            outcome=ProgramOutcome.WRITE_FAILED,
            message=msg,
            failed_fields=tuple(fields_written),
        )
        return False, msg

    _VERIFY_RETRIES = 2
    _VERIFY_DELAY_S = 1.0  # seconds between retries

    def _verify_written_fields(self, intended: Dict[str, str]) -> '_VerificationReport':
        """Classify a set of written fields via read-back.

        Ki, OPc, and HNET_PUBKEY are structurally unreadable — always placed in
        unreadable_fields when present in *intended*.  All other fields
        are verified via verify_after_program; results are binned into
        verified_fields, failed_fields, or verification_error.
        """
        _UNREADABLE = {'Ki', 'OPc', 'HNET_PUBKEY', 'SUCI'}
        unreadable = tuple(f for f in _UNREADABLE if f in intended)
        readable_intended = {k: v for k, v in intended.items() if k not in _UNREADABLE}

        if not readable_intended:
            return _VerificationReport(unreadable_fields=unreadable)

        ok, _msg, readback = self.verify_after_program(readable_intended)

        if not ok and not readback:
            return _VerificationReport(
                unreadable_fields=unreadable,
                verification_error=_msg,
            )

        verified: List[str] = []
        failed: List[str] = []
        for field, expected in readable_intended.items():
            actual = readback.get(field, '').strip()
            expected = expected.strip()
            if not expected:
                continue
            if actual and actual == expected:
                verified.append(field)
            elif actual and actual != expected:
                failed.append(field)
            else:
                failed.append(field)

        error: Optional[str] = None if ok else _msg
        return _VerificationReport(
            verified_fields=tuple(verified),
            failed_fields=tuple(failed),
            unreadable_fields=unreadable,
            verification_error=error,
            readback_data=readback if ok else {},
        )

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
        if self.cli_backend != CLIBackend.PYSIM:
            return True, "Verification not supported for this backend", {}

        import time
        last_mismatches: List[str] = []
        readback: Dict[str, str] = {}

        for attempt in range(1, self._VERIFY_RETRIES + 1):
            if attempt > 1:
                time.sleep(self._VERIFY_DELAY_S)
                logger.info("Verify attempt %d/%d", attempt, self._VERIFY_RETRIES)

            worker_fields = self._try_worker_readback_fields()
            if worker_fields is not None:
                print(f"DEBUG: readback from WORKER")
                logger.info("Verify read-back (attempt %d): using in-process worker", attempt)
                readback = worker_fields
            else:
                print(f"DEBUG: readback from PYSIM-READ")
                ok, stdout, stderr = self._run_cli('pySim-read.py', f'-p{self._pcsc_reader_index}')
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

            # Verify FPLMN when written — compare as order-independent sets
            if written_data.get('FPLMN'):
                expected_set = self._normalize_fplmn(written_data['FPLMN'])
                actual_set = self._normalize_fplmn(readback.get('FPLMN', ''))
                if expected_set != actual_set:
                    last_mismatches.append(
                        f"FPLMN: wrote {written_data['FPLMN']!r}, "
                        f"read back {readback.get('FPLMN', '(none)')!r}")

            # Verify SUCI when written — read EF.UST and check service states
            if written_data.get('SUCI'):
                expected_suci = written_data['SUCI'].lower() in ('true', 'yes', '1', 'enabled')
                logger.info("[SUCI-VERIFY] expected=%s", expected_suci)
                ok_suci, stdout_suci, stderr_suci = self._run_pysim_shell(
                    self._authenticated_adm1_hex, '\n'.join(self._pysim_read_suci()), timeout=10)
                logger.info("[SUCI-VERIFY] pySim-shell ok=%s stdout_len=%d stderr_len=%d",
                            ok_suci, len(stdout_suci or ''), len(stderr_suci or ''))
                if stdout_suci:
                    logger.info("[SUCI-VERIFY] stdout (first 300 chars): %s", stdout_suci[:300])
                if stderr_suci:
                    logger.info("[SUCI-VERIFY] stderr (first 300 chars): %s", stderr_suci[:300])
                if ok_suci and stdout_suci:
                    actual_suci = self._parse_suci_readback(stdout_suci)
                    logger.info("[SUCI-VERIFY] actual=%s", actual_suci)
                    if actual_suci != expected_suci:
                        last_mismatches.append(
                            f"SUCI: wrote {expected_suci}, read back {actual_suci}")
                        logger.warning("[SUCI-VERIFY] MISMATCH: expected %s but got %s", expected_suci, actual_suci)
                elif not ok_suci:
                    last_mismatches.append(
                        f"SUCI: verification read failed")
                    logger.warning("[SUCI-VERIFY] READ_FAILED: pySim-shell returned ok=False")

            if not last_mismatches:
                logger.info("Post-program verification OK: %s", readback)
                return True, "Verification OK", readback

        # All retries exhausted
        detail = '; '.join(last_mismatches)
        return False, (
            f"Programming commands sent but read-back verification FAILED "
            f"after {self._VERIFY_RETRIES} attempts.\n{detail}"
        ), readback

    def _try_worker_readback_fields(self) -> Optional[Dict[str, str]]:
        """Attempt in-process readback via the persistent worker.

        Returns a fields dict (ICCID, IMSI, SPN, ACC, FPLMN) on success, or
        None when the worker is unavailable, not ready, the env gate is unset,
        or the call fails for any reason.  Never mutates self.card_info.
        """
        if not _inprocess_enabled():
            logger.info("WORKER_DIAG readback: skip reason=env_off")
            return None
        client = getattr(self, "_worker_client", None)
        if client is None:
            logger.info("WORKER_DIAG readback: skip reason=no_client")
            return None
        try:
            if not client.is_ready():
                logger.info("WORKER_DIAG readback: skip reason=not_ready  last_error=%r",
                            getattr(client, "last_error", None))
                return None
        except Exception:
            return None
        if "detect_inprocess" not in self._get_worker_capabilities():
            logger.info("WORKER_DIAG readback: skip reason=missing_capability  caps=%r",
                        self._get_worker_capabilities())
            return None
        session_id = self._current_session_id
        card_gen = self._current_card_gen
        if session_id is None or card_gen is None:
            logger.info("WORKER_DIAG readback: skip reason=no_session  "
                        "session_id=%r  card_gen=%r", session_id, card_gen)
            return None
        logger.info("WORKER_DIAG readback: routing via worker  session_id=%r", session_id)
        pysim_path = self.cli_path or ""
        try:
            result = client.detect_inprocess(
                session_id=session_id,
                card_gen=card_gen,
                pysim_path=pysim_path,
                reader_index=self._pcsc_reader_index,
            )
        except Exception as exc:
            logger.debug("Worker readback failed: %s", exc)
            return None
        if not result.ok:
            return None
        return dict(result.fields) if result.fields else None

    def verify_card(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Verify card data matches expected values."""
        if not self.authenticated:
            return False, ["Not authenticated"]
        return True, []

    def get_remaining_attempts(self) -> Optional[int]:
        """Return remaining ADM1 auth attempts, or None if unknown."""
        return self._adm1_remaining_attempts

    def disconnect(self):
        self.authenticated = False
        self._authenticated_adm1_hex = None
        self._original_card_data = None
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

    def _read_public_fields_via_shell(self) -> None:
        """Enrich card_info with ACC, SPN, FPLMN read via pySim-shell.

        Only runs for non-blank cards (ICCID present). Per-field failures
        are silently ignored so the overall card detection is never blocked.
        """
        if not self.card_info.get('ICCID'):
            return
        commands = (
            'select ADF.USIM\n'
            'select EF.ACC\n'
            'read_binary_decoded --oneline\n'
            'select ADF.USIM\n'
            'select EF.SPN\n'
            'read_binary_decoded --oneline\n'
            'select ADF.USIM\n'
            'select EF.FPLMN\n'
            'read_binary_decoded --oneline\n'
        )
        # Brief settle after pySim-read released the reader
        time.sleep(0.3)
        _ok, stdout, _stderr = self._run_pysim_shell_safe(commands, timeout=15)
        if stdout:
            self._parse_shell_public_fields(stdout)

    def _parse_shell_public_fields(self, output: str) -> None:
        """Parse JSON lines from pySim-shell read_binary_decoded --oneline output.

        Identifies each field by its JSON structure:
          - dict with 'ACC0' key  → EF.ACC
          - dict with 'spn'  key  → EF.SPN
          - list               → EF.FPLMN
        """
        for line in output.splitlines():
            line = line.strip()
            if not (line.startswith('{') or line.startswith('[')):
                continue
            try:
                data = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and 'ACC0' in data:
                mask = 0
                for i in range(16):
                    if data.get(f'ACC{i}'):
                        mask |= (1 << i)
                self.card_info['ACC'] = f'{mask:04X}'
            elif isinstance(data, dict) and 'spn' in data:
                spn = data.get('spn', '')
                if spn:
                    self.card_info['SPN'] = spn
            elif isinstance(data, list):
                plmns = []
                for entry in data:
                    if entry is None:
                        continue
                    try:
                        plmns.append(f"{entry['mcc']}{entry['mnc'].zfill(2)}")
                    except (KeyError, TypeError, AttributeError):
                        continue
                if plmns:
                    self.card_info['FPLMN'] = ';'.join(plmns)

    def _parse_pysim_output(self, output: str):
        """Parse pySim-read output for card info.

        Delegates to pysim_parser.parse_pysim_output() and applies the
        result to self.card_info and self.card_type.
        """
        parsed = _parse_pysim_output_fn(output)
        for field in ('IMSI', 'ICCID', 'ACC', 'SPN', 'FPLMN'):
            if field in parsed:
                self.card_info[field] = parsed[field]
        ct_str = parsed.get('card_type_str', '')
        if ct_str:
            ct = self._PYSIM_CARD_TYPE_MAP.get(ct_str)
            if ct is not None:
                self.card_type = ct
                logger.info("pySim auto-detected card type: %s -> %s",
                            ct_str, ct.name)
