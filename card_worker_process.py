"""
Phase 1 — persistent worker process entry point.

Reads newline-delimited JSON from stdin, writes newline-delimited JSON to stdout.
No PCSC, no pySim, no card operations, no Qt.
Allowed imports: sys, json, os only.
"""

import json
import os
import sys


_CAPABILITIES = ["ping", "status", "capabilities", "shutdown"]


def _write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


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
