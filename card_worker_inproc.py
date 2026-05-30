"""
In-process pySim programming prototype for the persistent worker.

Phase 1 spike: feature-flagged, isolated from the main JSON dispatch loop.
Lazy-imports pySim so normal CI (which may not have pySim installed) is unaffected.

Public entry point:
    program_full(fields, adm1_hex, reader_index=0) -> (ok: bool, stdout: str, stderr: str)

Long-lived state (transport `sl`, command layer `scc`) is held on a module-level
session object so that the PCSC handle survives across requests — this is the
property that makes the in-process path measurably faster than per-card subprocess.

PIN1 / PUK1 are stripped defensively at the entry point; they are not programming
fields.

Test hook: tests may set ``_pysim_runtime`` to a fake object exposing the same
attributes used here, bypassing the real lazy import.
"""

from typing import Any, Dict, Optional, Tuple


_NOT_PROGRAMMING_FIELDS = ("PIN1", "PUK1")


_session: Dict[str, Any] = {"sl": None, "scc": None, "reader_index": None}
_pysim_runtime: Optional[Any] = None


class PysimImportError(RuntimeError):
    """Raised when pySim cannot be imported in the worker process."""


class _Runtime:
    """Container for the lazy-imported pySim entry points."""
    init_reader = None
    SimCardCommands = None
    card_detect = None


class _Opts:
    """Minimal stand-in for the argparse Namespace pySim's init_reader expects."""
    pcsc_dev = 0
    modem_dev = None
    modem_baud = 115200
    osmocon_sock = None


def _load_pysim() -> Any:
    """Lazy-import pySim; cached on the module.

    Returns an object exposing ``init_reader``, ``SimCardCommands``, ``card_detect``.
    Tests may pre-set ``_pysim_runtime`` to bypass real imports.
    """
    global _pysim_runtime
    if _pysim_runtime is not None:
        return _pysim_runtime
    try:
        from pySim.transport import init_reader  # type: ignore
        from pySim.commands import SimCardCommands  # type: ignore
        from pySim.legacy.cards import card_detect  # type: ignore
    except Exception as exc:
        raise PysimImportError(str(exc))

    rt = _Runtime()
    rt.init_reader = init_reader
    rt.SimCardCommands = SimCardCommands
    rt.card_detect = card_detect
    _pysim_runtime = rt
    return rt


def _ensure_session(rt: Any, reader_index: int) -> None:
    """Open the PCSC transport on first use, or reuse it across requests."""
    if _session["sl"] is not None and _session["reader_index"] == reader_index:
        return

    opts = _Opts()
    opts.pcsc_dev = reader_index
    sl = rt.init_reader(opts)
    _session["sl"] = sl
    _session["scc"] = rt.SimCardCommands(transport=sl)
    _session["reader_index"] = reader_index


def reset_session() -> None:
    """Drop the held PCSC transport. Used by tests and on worker shutdown."""
    _session["sl"] = None
    _session["scc"] = None
    _session["reader_index"] = None


def _build_cp(fields: Dict[str, str], adm1_hex: str) -> Dict[str, Any]:
    """Build the pySim ``cp`` parameter dict from a SimGUI field dict.

    Only fields relevant to full provisioning are mapped. Unknown fields are
    ignored. ADM1 is included for the underlying card.program() call.
    """
    cp: Dict[str, Any] = {}
    mapping = {
        "ICCID": "iccid", "IMSI": "imsi", "Ki": "ki", "OPc": "opc",
        "ACC": "acc", "SPN": "name", "MCC": "mcc", "MNC": "mnc",
        "SMSP": "smsp", "PIN1": None, "PUK1": None,
    }
    for src, dst in mapping.items():
        if dst is None:
            continue
        v = fields.get(src)
        if v:
            cp[dst] = v
    cp["adm1"] = adm1_hex
    return cp


def program_full(
    fields: Dict[str, str],
    adm1_hex: str,
    reader_index: int = 0,
) -> Tuple[bool, str, str]:
    """Run full provisioning in-process. Returns (ok, stdout, stderr).

    stdout is a short human-readable log; stderr carries the exception repr
    on failure. The contract mirrors ``CardManager._run_pysim_prog`` so that a
    future production phase can swap implementations without changing callers.
    """
    safe_fields = {k: v for k, v in fields.items() if k not in _NOT_PROGRAMMING_FIELDS}

    # PysimImportError is allowed to propagate — the JSON handler maps it to a
    # distinct protocol error code (PYSIM_IMPORT_FAILED), not stderr.
    rt = _load_pysim()

    try:
        _ensure_session(rt, reader_index)
        scc = _session["scc"]
        card = rt.card_detect("gialersim", scc)
        if card is None:
            return False, "", "card_detect returned None"
        cp = _build_cp(safe_fields, adm1_hex)
        card.program(cp)
        return True, f"programmed fields={sorted(safe_fields.keys())}", ""
    except Exception as exc:
        return False, "", f"{type(exc).__name__}: {exc}"
