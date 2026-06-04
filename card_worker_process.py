"""
Persistent worker process entry point.

Reads newline-delimited JSON from stdin, writes newline-delimited JSON to stdout.
No pySim, no Qt. smartcard is lazy-imported inside _smartcard_readers.
Top-level imports: sys, json, os only.
"""

import json
import logging
import os
import subprocess
import sys

# Redirect all logging to stderr before any lazy import can emit a log line.
# Without this, a logger writing to the root StreamHandler (which defaults to
# sys.stderr but may be reconfigured to sys.stdout in a PyInstaller bundle)
# can pollute the JSON-only stdout protocol channel.
logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)


class _JsonOnlyStdout:
    """Stdout wrapper that enforces the JSON-lines protocol.

    Any write() whose stripped content does not start with '{' is silently
    redirected to stderr so that banner/logging lines cannot corrupt the
    protocol channel.  JSON writes pass through to the real stdout unchanged.
    """

    def __init__(self, real: "sys.stdout") -> None:
        self._real = real

    def write(self, s: str) -> int:
        stripped = s.strip()
        if not stripped:
            # Swallow whitespace-only writes (bare \n etc.) — they corrupt the
            # JSON-lines protocol by causing readline() to return early.
            sys.stderr.write("[worker-stdout-guard-swallow] " + repr(s) + "\n")
            sys.stderr.flush()
            return len(s)
        if not stripped.startswith("{"):
            sys.stderr.write("[worker-stdout-guard] " + s)
            sys.stderr.flush()
            return len(s)
        return self._real.write(s)

    def flush(self) -> None:
        self._real.flush()

    def isatty(self) -> bool:
        return False

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._real.fileno()


_BASE_CAPABILITIES = ["ping", "status", "capabilities", "shutdown", "probe", "authenticate"]


def _inprocess_enabled() -> bool:
    """In-process pySim path is default-on; set SIMGUI_WORKER_INPROCESS=0 to disable."""
    return os.environ.get("SIMGUI_WORKER_INPROCESS") != "0"


def _setup_pysim_path() -> None:
    """In a PyInstaller bundle pySim data files land at sys._MEIPASS
    (Contents/Resources/), not Contents/Frameworks/.  Add both the pySim
    package directory and its site-packages to sys.path before any import.
    Mirrors the logic in CardManager._get_pysim_env()."""
    if not (getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")):
        return
    for subdir in ("pysim", "pysim-site-packages"):
        p = os.path.join(sys._MEIPASS, subdir)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)



def _capabilities() -> list:
    caps = list(_BASE_CAPABILITIES)
    if _inprocess_enabled():
        try:
            import card_worker_inproc as _inproc
            import pySim  # confirm pySim itself is importable, not just the wrapper
            caps.append("program_full")
            caps.append("detect_inprocess")
            if _inproc.delta_supported_fields():
                caps.append("program_delta")
                caps.append("program_delta_capabilities")
        except Exception:
            pass
    return caps


# Backwards-compatible alias for callers/tests that read the list directly.
_CAPABILITIES = _BASE_CAPABILITIES

# --- session state ---
_card_gen = 0
_session_id = None      # hex string; assigned on each new card insertion
_last_atr = None        # hex string of last seen ATR
_card_present = False   # True while card is seated

# --- session profile state ---
_session_profile = None
_session_pysim_path = ""
_session_reader_index = 0


class WorkerAuthDelegate:
    """Auth delegate for the active worker session."""

    def __init__(self, pysim_path, reader_index, is_gialersim=False):
        self.pysim_path = pysim_path
        self.reader_index = reader_index
        self.is_gialersim = is_gialersim

    def authenticate_adm(self, adm1_hex):
        if _inprocess_enabled():
            try:
                import card_worker_inproc as _inproc
                return _inproc.authenticate_inprocess(
                    adm1_hex, self.reader_index, self.is_gialersim
                )
            except Exception as exc:
                return (False, f"TRANSPORT_ERROR:{exc!r}")

        # Subprocess fallback — used when SIMGUI_WORKER_INPROCESS is not set.
        script = os.path.join(self.pysim_path, "pySim-shell.py")
        if not os.path.isfile(script):
            return (False, "TRANSPORT_ERROR:CLI_NOT_FOUND")
        try:
            proc = subprocess.run(
                [sys.executable, script, "-p", str(self.reader_index), "-A", adm1_hex],
                input="quit\n",
                text=True,
                capture_output=True,
                timeout=15.0,
            )
        except subprocess.TimeoutExpired as exc:
            return (False, f"TRANSPORT_ERROR:{exc}")
        except Exception as exc:
            return (False, f"TRANSPORT_ERROR:{exc}")
        combined = proc.stdout + proc.stderr
        if "6983" in combined:
            return (False, "CARD_BLOCKED:6983")
        if "6982" in combined or "SwMatchError" in combined:
            return (False, "AUTH_FAILED:6982")
        if proc.returncode != 0:
            return (False, f"TRANSPORT_ERROR:{combined.strip() or proc.returncode}")
        return (True, "")

    def read_card(self):
        raise NotImplementedError

    def check_retry_counter(self):
        raise NotImplementedError

    def program_fields(self, fields):
        raise NotImplementedError

    def verify_fields(self, expected):
        raise NotImplementedError


def _write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _smartcard_readers():
    """Return list of smart-card readers. Lazy-imports smartcard; returns [] on any error."""
    try:
        from smartcard.System import readers as _readers
        return list(_readers())
    except Exception as exc:
        import sys as _sys
        _sys.stderr.write(f"[SMARTCARD_ERR] {type(exc).__name__}: {exc}\n")
        _sys.stderr.flush()
        return []


def _reset_inprocess_session_if_available(reason: str) -> None:
    """Reset the in-process pySim transport on card lifecycle transitions.

    Lazy-imports card_worker_inproc; never raises outward. Safe to call
    whether or not SIMGUI_WORKER_INPROCESS is set.
    """
    try:
        import card_worker_inproc as _inproc
        _inproc.reset_session()
    except Exception:
        pass


def _handle_probe(req_id, params):
    global _card_gen, _session_id, _last_atr, _card_present
    global _session_profile, _session_pysim_path, _session_reader_index

    p = params or {}
    reader_index = p.get("reader_index", 0)
    timeout = p.get("timeout", 2.0)

    readers = _smartcard_readers()
    if not readers or reader_index >= len(readers):
        _card_present = False
        _session_profile = None
        _session_pysim_path = ""
        _session_reader_index = 0
        _write({"id": req_id, "ok": True, "present": False, "msg": "No smart-card reader detected"})
        return

    reader = readers[reader_index]
    result = {}
    exc_box = []

    def _connect():
        try:
            conn = reader.createConnection()
            conn.connect()
            result["atr"] = conn.getATR()
        except Exception as exc:
            exc_box.append(exc)

    import threading
    t = threading.Thread(target=_connect, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        _write({"id": req_id, "ok": False, "error": "PROBE_TIMEOUT"})
        return

    if exc_box or "atr" not in result:
        if exc_box:
            sys.stderr.write(
                f"[PROBE_CONNECT_ERR] {type(exc_box[0]).__name__}: {exc_box[0]}\n"
            )
            sys.stderr.flush()
        if _card_present:
            _card_present = False
            _session_profile = None
            _session_pysim_path = ""
            _session_reader_index = 0
            _reset_inprocess_session_if_available("card_removed")
        _write({"id": req_id, "ok": True, "present": False, "msg": "No card in reader"})
        return

    # Card present — only increment card_gen on absent → present transition
    atr_raw = result["atr"]  # may be [] on some readers; treat as present
    if not atr_raw:
        sys.stderr.write("[PROBE_EMPTY_ATR] card connected but getATR() returned []\n")
        sys.stderr.flush()
    atr_hex = bytes(atr_raw).hex()
    if not _card_present:
        _card_gen += 1
        _session_id = os.urandom(8).hex()
        _last_atr = atr_hex
        _card_present = True
        _session_profile = None
        _session_pysim_path = ""
        _session_reader_index = 0
        _reset_inprocess_session_if_available("new_card_generation")

    _write({
        "id": req_id,
        "ok": True,
        "present": True,
        "atr": _last_atr,
        "card_gen": _card_gen,
        "session_id": _session_id,
    })


def _detect_error(req_id, error, worker_error, stdout="", stderr=""):
    _write({
        "id": req_id, "ok": False, "blank": False, "card_type": "",
        "fields": {}, "stdout": stdout, "stderr": stderr,
        "worker_error": worker_error, "error": error,
    })


def _handle_authenticate(req_id, params):
    p = params or {}
    session_id = p.get("session_id")
    card_gen = p.get("card_gen")

    if session_id != _session_id or card_gen != _card_gen:
        _write({"id": req_id, "ok": False, "error": "STALE_SESSION"})
        return

    if _session_profile is None:
        _write({"id": req_id, "ok": False, "error": "NO_PROFILE"})
        return

    adm1_hex = p.get("adm1_hex")
    if not adm1_hex:
        _write({"id": req_id, "ok": False, "error": "INVALID_REQUEST"})
        return

    ok, msg = _session_profile.authenticate(adm1_hex)

    if ok:
        deferred = msg.startswith("DEFERRED") if msg else False
        _write({
            "id": req_id,
            "ok": True,
            "result": {
                "session_id": _session_id,
                "card_gen": _card_gen,
                "deferred": deferred,
            },
        })
        return

    if msg and msg.startswith("CARD_BLOCKED"):
        error = "CARD_BLOCKED"
    elif msg and msg.startswith("TRANSPORT_ERROR"):
        error = "TRANSPORT_ERROR"
    else:
        error = "AUTH_FAILED"

    _write({"id": req_id, "ok": False, "error": error, "msg": msg})


def _handle_detect_inprocess(req_id, params):
    """In-process card detect — no subprocess. Gated by SIMGUI_WORKER_INPROCESS=1."""
    if not _inprocess_enabled():
        _write({"id": req_id, "ok": False, "error": "INPROCESS_DISABLED", "worker_error": True})
        return

    p = params or {}
    reader_index = p.get("reader_index", 0)

    try:
        import card_worker_inproc as _inproc
    except Exception as exc:
        _write({"id": req_id, "ok": False, "error": "PYSIM_IMPORT_FAILED",
                "msg": str(exc), "worker_error": True})
        return

    try:
        resp = _inproc.detect_inprocess(reader_index)
    except _inproc.PysimImportError as exc:
        _write({"id": req_id, "ok": False, "error": "PYSIM_IMPORT_FAILED",
                "msg": str(exc), "worker_error": True})
        return
    except Exception as exc:
        _write({"id": req_id, "ok": False, "error": "DETECT_FAILED",
                "msg": str(exc), "worker_error": False})
        return

    _write({
        "id": req_id,
        "ok": bool(resp.get("ok")),
        "blank": bool(resp.get("blank")),
        "card_type": resp.get("card_type", ""),
        "fields": resp.get("fields", {}),
        "stdout": resp.get("stdout", ""),
        "stderr": resp.get("stderr", ""),
        "worker_error": bool(resp.get("worker_error")),
        "error": resp.get("error"),
        "msg": resp.get("msg"),
        # Include worker-level session tracking so client can pass correct
        # session_id/card_gen back on authenticate/program calls.
        "session_id": _session_id if resp.get("ok") else None,
        "card_gen": _card_gen if resp.get("ok") else None,
    })


def _handle_program_full(req_id, params):
    """In-process full-provisioning prototype. Gated by SIMGUI_WORKER_INPROCESS=1."""
    if not _inprocess_enabled():
        _write({"id": req_id, "ok": False, "error": "INPROCESS_DISABLED", "worker_error": True})
        return

    p = params or {}
    fields = p.get("fields")
    adm1_hex = p.get("adm1_hex")
    if not isinstance(fields, dict) or not isinstance(adm1_hex, str) or not adm1_hex:
        _write({"id": req_id, "ok": False, "error": "INVALID_REQUEST", "worker_error": True})
        return

    reader_index = p.get("reader_index", 0)

    try:
        import card_worker_inproc as _inproc
    except Exception as exc:
        _write({"id": req_id, "ok": False, "error": "PYSIM_IMPORT_FAILED", "msg": str(exc), "worker_error": True})
        return

    try:
        ok, stdout, stderr = _inproc.program_full(fields, adm1_hex, reader_index)
    except _inproc.PysimImportError as exc:
        _write({"id": req_id, "ok": False, "error": "PYSIM_IMPORT_FAILED", "msg": str(exc), "worker_error": True})
        return

    _write({"id": req_id, "ok": bool(ok), "stdout": stdout, "stderr": stderr, "worker_error": False})


def _handle_program_delta(req_id, params):
    """In-process delta-write for non-empty cards. Gated by SIMGUI_WORKER_INPROCESS=1."""
    if not _inprocess_enabled():
        _write({"id": req_id, "ok": False, "error": "INPROCESS_DISABLED", "worker_error": True})
        return

    p = params or {}
    changed = p.get("changed")
    adm1_hex = p.get("adm1_hex")
    if not isinstance(changed, dict) or not isinstance(adm1_hex, str) or not adm1_hex:
        _write({"id": req_id, "ok": False, "error": "INVALID_REQUEST", "worker_error": True})
        return

    # Session staleness guard.
    req_session_id = p.get("session_id")
    req_card_gen = p.get("card_gen")
    if req_session_id is not None and req_session_id != _session_id:
        _write({"id": req_id, "ok": False, "error": "STALE_SESSION",
                "write_started": False, "worker_error": True})
        return
    if req_card_gen is not None and req_card_gen != _card_gen:
        _write({"id": req_id, "ok": False, "error": "STALE_CARD_GEN",
                "write_started": False, "worker_error": True})
        return

    reader_index = p.get("reader_index", 0)
    card_type = p.get("card_type")

    try:
        import card_worker_inproc as _inproc
    except Exception as exc:
        _write({"id": req_id, "ok": False, "error": "PYSIM_IMPORT_FAILED",
                "msg": str(exc), "worker_error": True})
        return

    try:
        res = _inproc.program_delta(changed, adm1_hex, reader_index, card_type)
    except _inproc.PysimImportError as exc:
        _write({"id": req_id, "ok": False, "error": "PYSIM_IMPORT_FAILED",
                "msg": str(exc), "worker_error": True})
        return
    except Exception as exc:
        _write({"id": req_id, "ok": False, "error": f"WORKER_EXCEPTION:{type(exc).__name__}",
                "write_started": False, "worker_error": True})
        return

    _write({
        "id": req_id,
        "ok": bool(res.get("ok")),
        "write_started": bool(res.get("write_started")),
        "written_fields": res.get("written_fields", []),
        "failed_fields": res.get("failed_fields", []),
        "error": res.get("error"),
        "worker_error": False,
    })


def _handle_program_delta_capabilities(req_id):
    try:
        import card_worker_inproc as _inproc
        fields = _inproc.delta_supported_fields()
    except Exception:
        fields = []
    _write({"id": req_id, "ok": True, "result": fields})


def _handle(line: str) -> bool:
    """Parse one request line and write one response. Returns False to stop."""
    try:
        req = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        _write({"id": None, "ok": False, "error": "parse_error", "raw": line.rstrip("\n")})
        return True

    req_id = req.get("id")
    verb = req.get("verb", "")

    if verb == "ping":
        _write({"id": req_id, "ok": True, "result": "pong"})
    elif verb == "status":
        _write({"id": req_id, "ok": True, "result": {"status": "idle", "pid": os.getpid()}})
    elif verb == "capabilities":
        _write({"id": req_id, "ok": True, "result": _capabilities()})
    elif verb == "shutdown":
        _write({"id": req_id, "ok": True})
        return False
    elif verb == "probe":
        _handle_probe(req_id, req.get("params"))
    elif verb == "authenticate":
        _handle_authenticate(req_id, req.get("params"))
    elif verb == "preload":
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            _diag_pysim_dir = os.path.join(sys._MEIPASS, "pysim")
            _diag_site_pkgs = os.path.join(sys._MEIPASS, "pysim-site-packages")
            logging.warning(
                "WORKER_PRELOAD_DIAG frozen=True meipass=%r pysim_exists=%r "
                "site_pkgs_exists=%r sys.path=%r",
                sys._MEIPASS,
                os.path.isdir(_diag_pysim_dir),
                os.path.isdir(_diag_site_pkgs),
                sys.path,
            )
        else:
            logging.warning("WORKER_PRELOAD_DIAG frozen=False sys.path=%r", sys.path)
        if _inprocess_enabled():
            try:
                import card_worker_inproc as _inproc
                ok, err = _inproc.preload()
                if ok:
                    _write({"id": req_id, "ok": True, "result": {"inprocess": True}})
                else:
                    _write({"id": req_id, "ok": False, "error": "PRELOAD_FAILED", "msg": err})
            except Exception as exc:
                import traceback
                traceback.print_exc(file=sys.stderr)
                _write({"id": req_id, "ok": False, "error": "PRELOAD_FAILED", "msg": str(exc)})
        else:
            _write({"id": req_id, "ok": True, "result": {"inprocess": False}})
    elif verb == "program_full":
        _handle_program_full(req_id, req.get("params"))
    elif verb == "detect_inprocess":
        _handle_detect_inprocess(req_id, req.get("params"))
    elif verb == "program_delta":
        _handle_program_delta(req_id, req.get("params"))
    elif verb == "program_delta_capabilities":
        _handle_program_delta_capabilities(req_id)
    else:
        _write({"id": req_id, "ok": False, "error": "unknown_verb", "verb": verb})

    return True


def main() -> None:
    _setup_pysim_path()
    sys.stdout = _JsonOnlyStdout(sys.stdout)
    banner = json.dumps({"event": "ready", "pid": os.getpid()})
    sys.stderr.write(banner + "\n")
    sys.stderr.flush()

    for line in sys.stdin:
        if not line.strip():
            continue
        if not _handle(line):
            break


if __name__ == "__main__":
    main()
