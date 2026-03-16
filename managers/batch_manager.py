"""
Batch Manager — State machine for sequential batch-programming of SIM cards.

Drives the detect → authenticate → program → verify cycle for each card
in a batch, supporting pause / skip / abort controls.
"""

import logging
import threading
from enum import Enum, auto
from typing import Callable, Dict, List, Optional

from managers.card_manager import CardManager

logger = logging.getLogger(__name__)


class BatchState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    WAITING_FOR_CARD = auto()
    COMPLETED = auto()
    ABORTED = auto()


class CardResult:
    """Outcome for a single card in the batch."""

    __slots__ = ("index", "iccid", "success", "message")

    def __init__(self, index: int, iccid: str, success: bool, message: str):
        self.index = index
        self.iccid = iccid
        self.success = success
        self.message = message


class BatchManager:
    """Manage the batch-programming state machine.

    All heavy work runs on a background thread.  UI callbacks are invoked
    on that thread — the caller must marshal to the main thread (e.g. via
    ``widget.after(0, …)``).
    """

    def __init__(self, card_manager: CardManager, card_watcher=None):
        self._cm = card_manager
        self._card_watcher = card_watcher
        self.state: BatchState = BatchState.IDLE
        self.results: List[CardResult] = []
        self._batch_data: List[Dict[str, str]] = []
        self._current_index: int = 0
        self._thread: Optional[threading.Thread] = None

        # Events
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused
        self._skip_event = threading.Event()
        self._abort_event = threading.Event()
        self._card_ready_event = threading.Event()

        # Callbacks — set by the UI
        self.on_progress: Optional[Callable[[int, int, str], None]] = None
        self.on_card_result: Optional[Callable[[CardResult], None]] = None
        self.on_waiting_for_card: Optional[Callable[[int, str], None]] = None
        self.on_completed: Optional[Callable[[], None]] = None

    # ---- public control -----------------------------------------------

    def start(self, batch_data: List[Dict[str, str]]) -> None:
        """Begin batch processing *batch_data* (list of card dicts).

        Each dict must contain at least ``ICCID`` and ``ADM1``.
        """
        if self.state == BatchState.RUNNING:
            return
        self._batch_data = list(batch_data)
        self._current_index = 0
        self.results = []
        self._abort_event.clear()
        self._skip_event.clear()
        self._pause_event.set()
        self.state = BatchState.RUNNING
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        if self.state == BatchState.RUNNING:
            self._pause_event.clear()
            self.state = BatchState.PAUSED

    def resume(self) -> None:
        if self.state == BatchState.PAUSED:
            self.state = BatchState.RUNNING
            self._pause_event.set()

    def skip(self) -> None:
        self._skip_event.set()
        self._card_ready_event.set()  # unblock waiting

    def abort(self) -> None:
        self._abort_event.set()
        self._pause_event.set()  # unblock if paused
        self._card_ready_event.set()  # unblock if waiting
        self.state = BatchState.ABORTED

    def card_ready(self) -> None:
        """Signal that the user has inserted the next card."""
        self._card_ready_event.set()

    @property
    def total(self) -> int:
        return len(self._batch_data)

    @property
    def current(self) -> int:
        return self._current_index

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.success)

    # ---- internal thread -----------------------------------------------

    def _run(self) -> None:
        simulator_mode = self._cm.is_simulator_active

        for i, card_data in enumerate(self._batch_data):
            self._current_index = i

            if self._abort_event.is_set():
                break

            # Wait while paused
            self._pause_event.wait()
            if self._abort_event.is_set():
                break

            iccid = card_data.get("ICCID", "?")
            adm1 = card_data.get("ADM1", "")

            # --- prompt for card insertion (or auto-advance in simulator) ---
            if simulator_mode and i > 0:
                self._cm.next_virtual_card()
            elif not simulator_mode:
                self.state = BatchState.WAITING_FOR_CARD
                self._card_ready_event.clear()
                if self.on_waiting_for_card:
                    self.on_waiting_for_card(i, iccid)
                self._card_ready_event.wait()
                if self._abort_event.is_set():
                    break
                if self._skip_event.is_set():
                    self._skip_event.clear()
                    self.results.append(CardResult(i, iccid, False, "Skipped"))
                    if self.on_card_result:
                        self.on_card_result(self.results[-1])
                    continue
                self.state = BatchState.RUNNING

            if self.on_progress:
                self.on_progress(i, len(self._batch_data), f"Processing card {i + 1}")

            # Pause card watcher during programming to avoid reader
            # contention (probes during pySim calls cause false
            # 'card removed' events).
            if self._card_watcher:
                self._card_watcher.pause()
            try:
                result = self._process_one(i, card_data, iccid, adm1)
            finally:
                if self._card_watcher:
                    self._card_watcher.resume()
            self.results.append(result)
            if self.on_card_result:
                self.on_card_result(result)

        if not self._abort_event.is_set():
            self.state = BatchState.COMPLETED
        if self.on_completed:
            self.on_completed()

    def _process_one(self, index: int, card_data: Dict[str, str],
                     iccid: str, adm1: str) -> CardResult:
        """Detect → authenticate → program → verify one card."""
        # 1. Detect
        ok, msg = self._cm.detect_card()
        if not ok:
            return CardResult(index, iccid, False, f"Detect failed: {msg}")

        # 2. Verify ICCID
        card_iccid = self._cm.read_iccid()
        if card_iccid and card_iccid != iccid:
            return CardResult(
                index, iccid, False,
                f"ICCID mismatch: expected {iccid}, got {card_iccid}")

        # 3. Authenticate
        # In batch mode we trust the CSV-provided ADM1 key — force past
        # low-retry-counter safety because the ICCID was already cross-
        # checked above and the key comes from a known-good data source.
        ok, msg = self._cm.authenticate(
            adm1, force=True, expected_iccid=iccid)
        if not ok:
            return CardResult(index, iccid, False, f"Auth failed: {msg}")

        # 4. Program
        ok, msg = self._cm.program_card(card_data)
        if not ok:
            return CardResult(index, iccid, False, f"Program failed: {msg}")

        # 5. Verify
        ok, mismatches = self._cm.verify_card(card_data)
        if not ok:
            detail = "; ".join(mismatches) if mismatches else "verification failed"
            return CardResult(index, iccid, False, f"Verify failed: {detail}")

        return CardResult(index, iccid, True, "Programmed successfully")
