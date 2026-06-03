"""
In-process pySim programming and detect for the persistent worker.

Lazy-imports pySim so normal CI (which may not have pySim installed) is unaffected.

Public entry points:
    authenticate_inprocess(adm1_hex, reader_index=0, is_gialersim=False) -> (ok: bool, msg: str)
    program_full(fields, adm1_hex, reader_index=0) -> (ok: bool, stdout: str, stderr: str)
    detect_inprocess(reader_index=0) -> dict  (detect schema, no subprocess)

Long-lived state (transport `sl`, command layer `scc`) is held on a module-level
session object so that the PCSC handle survives across requests — this is the
property that makes the in-process path measurably faster than per-card subprocess.

PIN1 / PUK1 are stripped defensively at the entry point; they are not programming
fields.

Test hook: tests may set ``_pysim_runtime`` to a fake object exposing the same
attributes used here, bypassing the real lazy import.
"""

from typing import Any, Dict, List, Optional, Tuple


_NOT_PROGRAMMING_FIELDS = ("PIN1", "PUK1")


_session: Dict[str, Any] = {"sl": None, "scc": None, "reader_index": None}
_pysim_runtime: Optional[Any] = None


# ---------------------------------------------------------------------------
# Delta writer registry — source-proven against pySim legacy cards.py
# update_imsi(imsi) -> sw  (SimCard, line 78)
# update_fplmn(list_of_plmn_str) -> sw  (UsimCard, line 269)
# ---------------------------------------------------------------------------

def _write_imsi(card: Any, value: str) -> str:
    return card.update_imsi(value)


def _write_fplmn(card: Any, value: str) -> str:
    plmns = [p.strip() for p in value.split(';') if p.strip()]
    return card.update_fplmn(plmns)


_DELTA_WRITERS: Dict[str, Any] = {
    "IMSI": _write_imsi,
    "FPLMN": _write_fplmn,
}


def delta_supported_fields() -> List[str]:
    """Return sorted list of field names the delta writer registry supports."""
    return sorted(_DELTA_WRITERS.keys())


def program_delta(
    changed: Dict[str, str],
    adm1_hex: str,
    reader_index: int = 0,
    card_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Write only the fields in *changed* in-process using the long-lived session.

    Returns a dict with keys: ok, write_started, written_fields, failed_fields, error.
    Never falls back — caller must not retry via subprocess if write_started=True.
    Never logs ADM1 value.
    """
    result: Dict[str, Any] = {
        "ok": False,
        "write_started": False,
        "written_fields": [],
        "failed_fields": [],
        "error": None,
    }

    # Reject unsupported fields before touching the card.
    unsupported = [k for k in changed if k not in _DELTA_WRITERS]
    if unsupported:
        result["error"] = "UNSUPPORTED_FIELDS"
        result["unsupported_fields"] = unsupported
        return result

    if not changed:
        result["ok"] = True
        result["error"] = "NO_CHANGES"
        return result

    rt = _load_pysim()
    _ensure_session(rt, reader_index)
    scc = _session["scc"]

    ct = card_type or "auto"
    card = rt.card_detect(ct, scc)
    if card is None:
        result["error"] = "NO_CARD"
        return result

    # Authenticate before writes.
    scc.verify_chv(0x0A, adm1_hex)

    result["write_started"] = True
    for field, value in changed.items():
        try:
            sw = _DELTA_WRITERS[field](card, value)
            if sw == "9000":
                result["written_fields"].append(field)
            else:
                result["failed_fields"].append(field)
                result["error"] = f"SW_{field}={sw}"
        except Exception as exc:
            result["failed_fields"].append(field)
            result["error"] = f"{field}:{type(exc).__name__}"

    result["ok"] = len(result["failed_fields"]) == 0
    return result


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


def preload() -> Tuple[bool, str]:
    """Import pySim symbols without opening a card or mutating session state.

    Returns (ok, error_message). Called by the worker process on the "preload" verb.
    """
    try:
        _load_pysim()
        return True, ""
    except PysimImportError as exc:
        return False, str(exc)


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


def authenticate_inprocess(
    adm1_hex: str,
    reader_index: int = 0,
    is_gialersim: bool = False,
) -> Tuple[bool, str]:
    """Verify ADM1 using the long-lived scc session. No subprocess.

    Gialersim cards skip VERIFY (CHV 0x0A would fail with 6f00 and burn an
    attempt). Returns a DEFERRED sentinel so the caller stores ADM1 for
    pySim-prog without touching the card.
    """
    if is_gialersim:
        return True, "DEFERRED:gialersim"

    rt = _load_pysim()
    try:
        _ensure_session(rt, reader_index)
        _session["scc"].verify_chv(0x0A, adm1_hex)
        return True, ""
    except Exception as exc:
        s = str(exc)
        if "6983" in s:
            return False, "CARD_BLOCKED:6983"
        if "6982" in s or "SwMatchError" in s:
            return False, "AUTH_FAILED:6982"
        return False, f"TRANSPORT_ERROR:{exc!r}"


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


def detect_inprocess(reader_index: int = 0) -> dict:
    """Detect card and read public fields in-process (no subprocess).

    Uses the long-lived sl/scc session. Returns a dict matching the
    detect/read_fields protocol schema so CardManager needs no schema changes.

    Never reads Ki, OPc, ADM1, PIN, PUK — public EFs only.
    Unreadable fields are omitted or set to "".
    """
    result: Dict[str, Any] = {
        "ok": False,
        "blank": False,
        "card_type": "",
        "fields": {},
        "stdout": "",
        "stderr": "",
        "worker_error": False,
        "error": None,
    }

    # PysimImportError is allowed to propagate — caller maps it to PYSIM_IMPORT_FAILED.
    rt = _load_pysim()

    try:
        _ensure_session(rt, reader_index)
        scc = _session["scc"]
        card = rt.card_detect("auto", scc)
        if card is None:
            result["error"] = "NO_CARD"
            return result

        card_type_str = getattr(card, "name", "") or ""
        result["card_type"] = card_type_str

        fields: Dict[str, str] = {}

        # ICCID
        try:
            iccid_val, sw = card.read_iccid()
            if sw == "9000" and iccid_val:
                fields["ICCID"] = iccid_val
        except Exception:
            pass

        # IMSI
        try:
            imsi_val, sw = card.read_imsi()
            if sw == "9000" and imsi_val:
                fields["IMSI"] = imsi_val
        except Exception:
            pass

        # SPN
        try:
            spn_result, sw = card.read_spn()
            if sw == "9000" and spn_result:
                fields["SPN"] = spn_result[0] if isinstance(spn_result, (list, tuple)) else str(spn_result)
        except Exception:
            pass

        # ACC — read_binary returns raw hex; store as-is for CardManager
        try:
            acc_raw, sw = card.read_binary("ACC")
            if sw == "9000" and acc_raw:
                fields["ACC"] = acc_raw
        except Exception:
            pass

        # FPLMN — UsimCard.read_fplmn returns (formatted_str, sw)
        try:
            fplmn_val, sw = card.read_fplmn()
            if sw == "9000" and fplmn_val:
                fields["FPLMN"] = fplmn_val
        except Exception:
            pass

        blank = (card_type_str == "gialersim") or (
            not fields.get("ICCID") and not fields.get("IMSI")
        )

        result["ok"] = True
        result["blank"] = blank
        result["fields"] = fields
        return result

    except Exception as exc:
        # Map no-card / PCSC-connect errors to NO_CARD so the watcher
        # treats them as "no card present" rather than an error state.
        # pySim raises NoCardException (and smartcard raises NoCardException
        # or CardConnectionException) when the reader is empty or the
        # transport connect fails because no card is seated.
        exc_name = type(exc).__name__
        exc_str = str(exc)
        _no_card_signals = (
            "NoCardException",
            "CardConnectionException",
            "No card",
            "No smart card",
            "unable to connect",
            "no card",
        )
        is_no_card = exc_name in ("NoCardException", "CardConnectionException") or any(
            s.lower() in exc_str.lower() for s in _no_card_signals
        )
        if is_no_card:
            # Drop the broken session so the next poll opens a fresh one
            # (pySim PCSC transport is not reusable after a connect failure).
            reset_session()
            result["error"] = "NO_CARD"
            return result
        result["error"] = "DETECT_FAILED"
        result["stderr"] = f"{exc_name}: {exc_str}"
        return result
