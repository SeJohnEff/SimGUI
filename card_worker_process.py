"""
Persistent worker process entry point.

Reads newline-delimited JSON from stdin, writes newline-delimited JSON to stdout.
No pySim, no Qt. smartcard is lazy-imported inside _smartcard_readers.
Top-level imports: sys, json, os only.
"""

import json
import os
import subprocess
import sys


_CAPABILITIES = ["ping", "status", "capabilities", "shutdown", "probe", "detect", "read_fields"]

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
    """Stub delegate wired to the active worker session. authenticate_adm deferred to Phase 3A-5."""

    def __init__(self, pysim_path, reader_index):
        self.pysim_path = pysim_path
        self.reader_index = reader_index

    def authenticate_adm(self, adm1_hex):
        raise NotImplementedError

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
    except Exception:
        return []


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
        if _card_present:
            _card_present = False
            _session_profile = None
            _session_pysim_path = ""
            _session_reader_index = 0
        _write({"id": req_id, "ok": True, "present": False, "msg": "No card in reader"})
        return

    # Card present — only increment card_gen on absent → present transition
    atr_hex = bytes(result["atr"]).hex()
    if not _card_present:
        _card_gen += 1
        _session_id = os.urandom(8).hex()
        _last_atr = atr_hex
        _card_present = True
        _session_profile = None
        _session_pysim_path = ""
        _session_reader_index = 0

    _write({
        "id": req_id,
        "ok": True,
        "present": True,
        "atr": _last_atr,
        "card_gen": _card_gen,
        "session_id": _session_id,
    })


def _handle_detect(req_id, params):
    p = params or {}
    session_id = p.get("session_id")
    card_gen = p.get("card_gen")

    if session_id != _session_id or card_gen != _card_gen:
        _write({"id": req_id, "ok": False, "error": "STALE_SESSION"})
        return

    pysim_path = p.get("pysim_path", "")
    if not pysim_path:
        _write({"id": req_id, "ok": False, "error": "CLI_NOT_FOUND"})
        return

    cli = os.path.join(pysim_path, "pySim-read.py")
    if not os.path.isfile(cli):
        _write({"id": req_id, "ok": False, "error": "CLI_NOT_FOUND"})
        return

    timeout = p.get("timeout", 30)
    reader_index = p.get("reader_index", 0)

    try:
        proc = subprocess.run(
            [sys.executable, cli, "-p", str(reader_index)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _write({"id": req_id, "ok": False, "error": "CARD_UNRESPONSIVE"})
        return

    from pysim_parser import parse_pysim_output
    try:
        fields = parse_pysim_output(proc.stdout)
    except Exception:
        _write({"id": req_id, "ok": False, "error": "PARSE_FAILED"})
        return

    card_type = fields.get("card_type_str", "")
    has_iccid = bool(fields.get("ICCID", "").strip())
    has_imsi = bool(fields.get("IMSI", "").strip())
    blank = (card_type == "gialersim") or (not has_iccid and not has_imsi)

    if proc.returncode != 0 and not card_type and not has_iccid and not has_imsi:
        _write({"id": req_id, "ok": False, "error": "DETECT_FAILED"})
        return

    global _session_profile, _session_pysim_path, _session_reader_index
    try:
        from card_profiles import ProfileFactory
        _session_profile = ProfileFactory().create(card_type, delegate=WorkerAuthDelegate(pysim_path, reader_index))
        _session_pysim_path = pysim_path
        _session_reader_index = reader_index
    except Exception:
        _session_profile = None
        _session_pysim_path = ""
        _session_reader_index = 0

    _write({"id": req_id, "ok": True, "blank": blank, "fields": fields})


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
        _write({"id": req_id, "ok": True, "result": _CAPABILITIES})
    elif verb == "shutdown":
        _write({"id": req_id, "ok": True})
        return False
    elif verb == "probe":
        _handle_probe(req_id, req.get("params"))
    elif verb in ("detect", "read_fields"):
        _handle_detect(req_id, req.get("params"))
    else:
        _write({"id": req_id, "ok": False, "error": "unknown_verb", "verb": verb})

    return True


def main() -> None:
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
