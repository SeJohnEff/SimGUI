"""
Persistent worker process entry point.

Reads newline-delimited JSON from stdin, writes newline-delimited JSON to stdout.
No pySim, no Qt. smartcard is lazy-imported inside _smartcard_readers.
Top-level imports: sys, json, os only.
"""

import json
import os
import sys


_CAPABILITIES = ["ping", "status", "capabilities", "shutdown", "probe"]

# --- session state ---
_card_gen = 0
_session_id = None      # hex string; assigned on each new card insertion
_last_atr = None        # hex string of last seen ATR
_card_present = False   # True while card is seated


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

    p = params or {}
    reader_index = p.get("reader_index", 0)
    timeout = p.get("timeout", 2.0)

    readers = _smartcard_readers()
    if not readers or reader_index >= len(readers):
        _card_present = False
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
        _write({"id": req_id, "ok": True, "present": False, "msg": "No card in reader"})
        return

    # Card present — only increment card_gen on absent → present transition
    atr_hex = bytes(result["atr"]).hex()
    if not _card_present:
        _card_gen += 1
        _session_id = os.urandom(8).hex()
        _last_atr = atr_hex
        _card_present = True

    _write({
        "id": req_id,
        "ok": True,
        "present": True,
        "atr": _last_atr,
        "card_gen": _card_gen,
        "session_id": _session_id,
    })


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
