"""
Phase 1 — PersistentWorkerClient.

Spawns card_worker_process.py as a subprocess and communicates via JSON-lines.
No PCSC, no pySim, no card operations, no Qt, no managers.
Standard library only.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

_LOG = logging.getLogger(__name__)
_STDERR_LOG = logging.getLogger("card_worker.stderr")


class WorkerError(Exception):
    """Base for all worker exceptions."""


class WorkerStartError(WorkerError):
    """Worker process failed to start or did not emit ready banner in time."""


class WorkerTimeoutError(WorkerError):
    """No response received within the deadline."""
    def __init__(self, verb: str, timeout: float) -> None:
        self.verb = verb
        self.timeout = timeout
        super().__init__(f"Timeout waiting for {verb!r} response after {timeout}s")


class WorkerEOFError(WorkerError):
    """Worker stdout closed before a response was received."""


class WorkerCrashError(WorkerError):
    """Worker process exited with a non-zero return code."""
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        super().__init__(f"Worker crashed with return code {returncode}")


class WorkerProtocolError(WorkerError):
    """Worker returned data that is not valid JSON."""
    def __init__(self, raw: str) -> None:
        self.raw = raw
        super().__init__(f"Worker returned invalid JSON: {raw!r}")


@dataclass
class ProbeResult:
    """Typed result from a worker probe() call."""
    present: bool
    atr: Optional[str] = None
    card_gen: Optional[str] = None
    session_id: Optional[str] = None
    msg: Optional[str] = None
    error: Optional[str] = None


@dataclass
class DetectResult:
    """Typed result from a worker detect() or read_fields() call."""
    ok: bool
    card_type: Optional[str] = None
    blank: bool = False
    fields: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    card_gen: Optional[int] = None
    error: Optional[str] = None
    msg: Optional[str] = None


@dataclass
class AuthResult:
    """Typed result from a worker authenticate() call."""
    ok: bool
    deferred: bool = False
    error: Optional[str] = None
    msg: Optional[str] = None
    session_id: Optional[str] = None
    card_gen: Optional[int] = None


class PersistentWorkerClient:
    """Manages a single card_worker_process.py subprocess."""

    def __init__(
        self,
        worker_script: Optional[str] = None,
        start_timeout: float = 5.0,
    ) -> None:
        if worker_script is None:
            worker_script = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "card_worker_process.py"
            )
        self._script = worker_script
        self._start_timeout = start_timeout
        self._process: Optional[subprocess.Popen] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the worker process and wait for the ready banner."""
        self._process = subprocess.Popen(
            [sys.executable, self._script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Read the ready banner from stderr with a timeout.
        banner_line = self._readline_with_timeout(
            self._process.stderr, self._start_timeout
        )
        if banner_line is None:
            self._process.terminate()
            raise WorkerStartError("Worker did not emit ready banner in time")

        try:
            banner = json.loads(banner_line)
        except (json.JSONDecodeError, ValueError):
            self._process.terminate()
            raise WorkerStartError(f"Worker emitted non-JSON banner: {banner_line!r}")

        if banner.get("event") != "ready":
            self._process.terminate()
            raise WorkerStartError(f"Unexpected banner event: {banner!r}")

        # Start background stderr drain.
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True, name="worker-stderr-drain"
        )
        self._stderr_thread.start()

    def stop(self) -> None:
        """Send shutdown request; terminate if the process lingers."""
        if self._process is None:
            return
        try:
            self.send("shutdown", timeout=3.0)
        except WorkerError:
            pass
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._process.terminate()
        self._process = None

    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # ------------------------------------------------------------------
    # Sending requests
    # ------------------------------------------------------------------

    def send(
        self,
        verb: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        """Send one request and return the parsed response dict."""
        if self._process is None:
            raise WorkerStartError("not started")

        req_id = str(uuid.uuid4())
        request = {"id": req_id, "verb": verb}
        if params:
            request["params"] = params

        line = json.dumps(request) + "\n"

        with self._lock:
            try:
                self._process.stdin.write(line.encode())
                self._process.stdin.flush()
            except OSError as exc:
                raise WorkerEOFError() from exc

            raw = self._readline_with_timeout(self._process.stdout, timeout)

        if raw is None:
            if self._process.poll() is not None and self._process.returncode != 0:
                raise WorkerCrashError(self._process.returncode)
            if not self.is_alive():
                raise WorkerEOFError()
            raise WorkerTimeoutError(verb, timeout)

        if not raw.strip():
            raise WorkerEOFError()

        try:
            response = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raise WorkerProtocolError(raw)

        return response

    def probe(
        self,
        reader_index: int = 0,
        timeout: float = 2.0,
        request_timeout: Optional[float] = None,
    ) -> ProbeResult:
        """Probe for a card on *reader_index*. Returns a typed ProbeResult."""
        rt = request_timeout if request_timeout is not None else timeout + 1.0
        resp = self.send(
            "probe",
            params={"reader_index": reader_index, "timeout": timeout},
            timeout=rt,
        )
        result = resp.get("result") or {}
        if resp.get("ok"):
            if result.get("present"):
                return ProbeResult(
                    present=True,
                    atr=result.get("atr"),
                    card_gen=result.get("card_gen"),
                    session_id=result.get("session_id"),
                )
            else:
                return ProbeResult(
                    present=False,
                    msg=result.get("msg"),
                    card_gen=result.get("card_gen"),
                    session_id=result.get("session_id"),
                )
        else:
            return ProbeResult(
                present=False,
                error=resp.get("error"),
                msg=resp.get("msg"),
                card_gen=result.get("card_gen") if result else None,
                session_id=result.get("session_id") if result else None,
            )

    def detect(
        self,
        session_id: str,
        card_gen: int,
        pysim_path: str,
        reader_index: int = 0,
        timeout: float = 30.0,
        request_timeout: Optional[float] = None,
    ) -> DetectResult:
        """Run pySim-read on the card; returns a typed DetectResult."""
        rt = request_timeout if request_timeout is not None else timeout + 1.0
        resp = self.send(
            "detect",
            params={
                "session_id": session_id,
                "card_gen": card_gen,
                "pysim_path": pysim_path,
                "reader_index": reader_index,
                "timeout": timeout,
            },
            timeout=rt,
        )
        result = resp.get("result") or {}
        if resp.get("ok"):
            return DetectResult(
                ok=True,
                card_type=result.get("card_type"),
                blank=bool(result.get("blank", False)),
                fields=result.get("fields") or {},
                session_id=result.get("session_id"),
                card_gen=result.get("card_gen"),
            )
        return DetectResult(
            ok=False,
            error=resp.get("error"),
            msg=resp.get("msg"),
        )

    def authenticate(
        self,
        session_id: str,
        card_gen: int,
        adm1_hex: str,
        timeout: float = 15.0,
        request_timeout: Optional[float] = None,
    ) -> AuthResult:
        """Authenticate with ADM1; returns a typed AuthResult."""
        rt = request_timeout if request_timeout is not None else timeout + 1.0
        try:
            resp = self.send(
                "authenticate",
                params={
                    "session_id": session_id,
                    "card_gen": card_gen,
                    "adm1_hex": adm1_hex,
                    "timeout": timeout,
                },
                timeout=rt,
            )
        except (WorkerTimeoutError, WorkerEOFError, WorkerCrashError) as exc:
            return AuthResult(ok=False, error="WORKER_DEAD", msg=str(exc))
        result = resp.get("result") or {}
        if resp.get("ok"):
            return AuthResult(
                ok=True,
                deferred=bool(result.get("deferred", False)),
                session_id=result.get("session_id"),
                card_gen=result.get("card_gen"),
            )
        return AuthResult(
            ok=False,
            error=resp.get("error"),
            msg=resp.get("msg"),
        )

    def read_fields(
        self,
        session_id: str,
        card_gen: int,
        pysim_path: str,
        reader_index: int = 0,
        timeout: float = 30.0,
        request_timeout: Optional[float] = None,
    ) -> DetectResult:
        """Read card fields via pySim-read; returns a typed DetectResult."""
        rt = request_timeout if request_timeout is not None else timeout + 1.0
        resp = self.send(
            "read_fields",
            params={
                "session_id": session_id,
                "card_gen": card_gen,
                "pysim_path": pysim_path,
                "reader_index": reader_index,
                "timeout": timeout,
            },
            timeout=rt,
        )
        result = resp.get("result") or {}
        if resp.get("ok"):
            return DetectResult(
                ok=True,
                card_type=result.get("card_type"),
                blank=bool(result.get("blank", False)),
                fields=result.get("fields") or {},
                session_id=result.get("session_id"),
                card_gen=result.get("card_gen"),
            )
        return DetectResult(
            ok=False,
            error=resp.get("error"),
            msg=resp.get("msg"),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _readline_with_timeout(stream, timeout: float) -> Optional[str]:
        """Read one line from *stream* within *timeout* seconds. Returns None on timeout/EOF."""
        result: list = []
        done = threading.Event()

        def _reader():
            try:
                data = stream.readline()
                result.append(data.decode() if isinstance(data, bytes) else data)
            except OSError:
                result.append(None)
            finally:
                done.set()

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        fired = done.wait(timeout)
        if not fired:
            return None
        if not result or result[0] is None or result[0] == "":
            return None
        return result[0]

    def _drain_stderr(self) -> None:
        """Consume stderr lines and log them. Runs in a daemon thread."""
        try:
            for raw in self._process.stderr:
                line = raw.decode() if isinstance(raw, bytes) else raw
                _STDERR_LOG.debug("%s", line.rstrip())
        except OSError:
            pass
