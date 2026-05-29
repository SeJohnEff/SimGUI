"""
Card Watcher — Background thread that polls for card insert/remove.

Eliminates the manual "Detect Card" button.  When a card is inserted,
the watcher reads the ICCID (no authentication required) and emits
events so the UI can auto-populate fields.

Detection uses a two-tier approach:
  1. Fast PC/SC probe (probe_card_presence) — checks ATR only, ~100 ms.
     Used for every poll cycle to detect insert/remove instantly.
  2. Full pySim-read (detect_card) — reads ICCID, IMSI, etc.
     Called once when a new card is detected (ATR changes).

Events (callbacks):
  on_reading()
      Card ATR detected; about to read card data (before pySim-read blocks).
      Fired immediately, before on_card_detected/on_card_unknown.
  on_card_detected(iccid, card_data, file_path)
      Card inserted, matched in index.  *card_data* is the full profile.
  on_card_unknown(iccid)
      Card inserted but ICCID not found in any indexed file.
  on_card_removed()
      Card was removed from the reader.
  on_reader_ready()
      Reader is connected but no card is inserted.  Fired every poll
      cycle while this state persists — the UI handler must be idempotent.
  on_error(message)
      Reader communication error (no reader connected).

Thread safety:
  All callbacks are invoked from the watcher thread.  The UI must
  use ``root.after(0, ...)`` to dispatch to the main thread.
"""

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Reset pyscard roughly every 10 seconds (7 polls at 1.5s interval) when
# no reader is detected, to handle stale PC/SC context or pcscd becoming available.
_NO_READER_RESET_AFTER = 7


class CardWatcher:
    """Background polling thread for card detection.

    Parameters
    ----------
    card_manager :
        The shared ``CardManager`` instance.
    iccid_index :
        Optional ``IccidIndex`` for auto-matching.  Can be set later
        via the ``index`` property.
    poll_interval :
        Seconds between polls (default 1.5).
    """

    def __init__(self, card_manager, iccid_index=None, *,
                 poll_interval: float = 1.5,
                 worker_client=None):
        self._cm = card_manager
        self._index = iccid_index
        self._poll_interval = poll_interval
        self._worker_client = worker_client
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False
        # Lock held while a poll is in progress.  pause() acquires it
        # to guarantee the reader is idle before returning.
        self._poll_lock = threading.Lock()

        # Last known state
        self._last_iccid: Optional[str] = None
        self._last_atr: Optional[str] = None
        self._card_present: bool = False
        # Debounce counter: blank gialersim cards can cause intermittent
        # "No card in reader" from the PCSC probe after pySim-read releases
        # the reader.  Require two consecutive absent-probes before declaring
        # removal for blank cards (last_iccid is None) — this tolerates one
        # transient PCSC failure without resetting the UI to "Insert SIM".
        self._no_card_streak: int = 0
        # Whether pyscard fast probe is available
        self._probe_available: Optional[bool] = None
        # ATR → ICCID cache for just-programmed cards.  When we program
        # an empty card and verify the write, we cache the mapping so
        # that re-insertion of the same card (same ATR) is recognised
        # immediately without relying on pySim-read succeeding.
        self._atr_iccid_cache: dict[str, str] = {}
        # Counter for "no reader" condition — after N consecutive polls
        # without a reader, force pyscard re-initialization to handle
        # stale PC/SC context or pcscd becoming available.
        self._no_reader_poll_count: int = 0
        # Set True when _read_and_notify() fires on_error so the next poll
        # retries the read even if the ATR is unchanged (same-ATR re-seat).
        self._last_read_failed: bool = False
        # Dedup key for worker probe path — opaque card_gen token from ProbeResult.
        self._last_card_gen: Optional[str] = None

        # Callbacks (set by UI layer)
        self.on_card_detected: Optional[
            Callable[[str, dict, str], None]] = None
        self.on_card_unknown: Optional[Callable[[str], None]] = None
        self.on_card_removed: Optional[Callable[[], None]] = None
        self.on_reader_ready: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_reading: Optional[Callable[[], None]] = None

    @property
    def index(self):
        return self._index

    @index.setter
    def index(self, value):
        self._index = value

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def paused(self) -> bool:
        return self._paused

    def start(self):
        """Start the background polling thread."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._paused = False
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="CardWatcher")
        self._thread.start()
        logger.info("CardWatcher started (interval=%.1fs)", self._poll_interval)

    def stop(self):
        """Stop the polling thread gracefully."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None
        self._last_iccid = None
        self._last_atr = None
        self._card_present = False
        self._no_card_streak = 0
        self._last_read_failed = False
        logger.info("CardWatcher stopped")

    def pause(self):
        """Pause polling (e.g. during programming).

        BLOCKS until any in-flight poll completes.  This guarantees
        the PC/SC reader is idle and not held by the watcher when
        this method returns — critical for avoiding 6f00 errors on
        USB readers (especially VM passthrough).
        """
        self._paused = True
        # Wait for any in-flight poll to release the reader.
        self._poll_lock.acquire()
        self._poll_lock.release()
        logger.debug("CardWatcher paused (reader idle)")

    def resume(self):
        """Resume polling after pause."""
        self._paused = False
        logger.debug("CardWatcher resumed")

    def paused_context(self):
        """Context manager that pauses polling for the duration of a block.

        Usage::

            with watcher.paused_context():
                # CardWatcher is paused here
                card_manager.authenticate(...)
                card_manager.program_card(...)
            # CardWatcher automatically resumes

        Safe to nest — only the outermost ``with`` actually resumes.
        Safe to call even if the watcher is already paused or not running.
        """
        return _PausedContext(self)

    def register_programmed_card(self, iccid: str) -> None:
        """Cache ATR→ICCID for a just-programmed card.

        Call this after a successful programming + verification cycle so
        that re-inserting the same card (same ATR) is recognised without
        relying on pySim-read.  Also updates ``_last_iccid`` so the next
        poll doesn't re-trigger the new-card flow.
        """
        if self._last_atr and iccid:
            self._atr_iccid_cache[self._last_atr] = iccid
            self._last_iccid = iccid
            logger.info("Cached ATR→ICCID: %s → %s", self._last_atr, iccid)

    def _poll_loop(self):
        """Main polling loop — runs on background thread."""
        while not self._stop_event.is_set():
            if not self._paused:
                with self._poll_lock:
                    # Re-check after acquiring the lock — pause() may
                    # have been called while we were waiting.
                    if self._paused:
                        pass  # skip this cycle
                    else:
                        try:
                            self._check_once()
                        except Exception as exc:
                            logger.error("CardWatcher poll error: %s", exc)
                            if self.on_error:
                                try:
                                    self.on_error(str(exc))
                                except Exception:
                                    pass

            self._stop_event.wait(self._poll_interval)

    def _check_once(self):
        """Single poll iteration.

        Uses the fast PC/SC probe first.  Falls back to the full
        detect_card() only if the fast probe is not available or
        when a new card needs to be identified.
        """
        if self._worker_client is not None:
            self._check_once_worker()
            return

        # Try fast probe first
        if self._probe_available is not False:
            present, probe_msg = self._cm.probe_card_presence()
            if probe_msg == 'NO_PYSCARD':
                # pyscard not installed — disable fast probe, use slow path
                self._probe_available = False
                logger.info("CardWatcher: pyscard not available, using slow polling")
            else:
                self._probe_available = True
                self._handle_probe_result(present, probe_msg)
                return

        # Slow path: use full detect_card (pySim-read)
        self._check_once_slow()

    def _handle_probe_result(self, present: bool, msg: str):
        """Process the result of a fast PC/SC probe.

        probe_card_presence returns three distinct states:
          (True,  atr_hex)                  → card in reader
          (False, 'No card in reader')      → reader connected, no card
          (False, 'No smart-card reader..') → no reader connected
          (False, other error)              → reader error
        """
        if present:
            # Card is in reader — reset removal debounce and no-reader counter
            if not hasattr(self, "_no_card_streak"):
                self._no_card_streak = 0
            if not hasattr(self, "_no_reader_poll_count"):
                self._no_reader_poll_count = 0
            self._no_card_streak = 0
            self._no_reader_poll_count = 0
            atr = msg
            if not self._card_present or atr != self._last_atr or self._last_read_failed:
                self._card_present = True
                self._last_atr = atr
                logger.info("CardWatcher: card present (ATR=%s), reading...", atr)
                # Signal UI that we're about to read the card (immediate feedback)
                if self.on_reading:
                    try:
                        self.on_reading()
                    except Exception:
                        pass
                self._read_and_notify()
            # Otherwise same card still present — do nothing

        elif msg == 'No card in reader':
            # Reader connected but no card
            if self._card_present:
                if self._last_iccid is None:
                    # Last card was blank (no ICCID) — require two consecutive
                    # absent probes before declaring removal.  Blank gialersim
                    # cards can cause a transient "No card" from the PCSC
                    # probe right after pySim-read releases the reader.
                    if not hasattr(self, "_no_card_streak"):
                        self._no_card_streak = 0
                    self._no_card_streak += 1
                    if self._no_card_streak < 2:
                        return
                # Card confirmed removed
                self._no_card_streak = 0
                self._card_present = False
                self._last_iccid = None
                self._last_atr = None
                self._last_read_failed = False
                if not hasattr(self, "_atr_iccid_cache"):
                    self._atr_iccid_cache = {}
                self._atr_iccid_cache.clear()
                logger.info("CardWatcher: card removed")
                if self.on_card_removed:
                    try:
                        self.on_card_removed()
                    except Exception:
                        pass
            else:
                # Reader idle — notify UI to show "Insert a SIM card..."
                if self.on_reader_ready:
                    try:
                        self.on_reader_ready()
                    except Exception:
                        pass

        else:
            # No reader connected or transient PCSC error.
            # Only 'No smart-card reader' means the reader hardware is gone.
            # Other errors (CardConnectionException, PC/SC error, etc.) are
            # transient — they can occur while pySim-read is releasing the reader
            # and do NOT mean the card was removed.
            is_no_reader = 'No smart-card reader' in msg
            if self._card_present and not is_no_reader:
                # Transient error — card is still physically present.
                # Preserve _card_present so the next 'No card in reader' probe
                # correctly fires on_card_removed via the blank-card debounce path.
                if self.on_error:
                    try:
                        self.on_error(msg)
                    except Exception:
                        pass
                return
            if self._card_present:
                self._card_present = False
                self._last_iccid = None
                self._last_atr = None
                self._last_read_failed = False
                if not hasattr(self, "_atr_iccid_cache"):
                    self._atr_iccid_cache = {}
                self._atr_iccid_cache.clear()
            # Periodic pyscard reset: every ~10 seconds when no reader detected,
            # force re-initialization in case PC/SC context is stale or pcscd
            # just became available.
            if not hasattr(self, "_no_reader_poll_count"):
                self._no_reader_poll_count = 0
            self._no_reader_poll_count += 1
            if self._no_reader_poll_count >= _NO_READER_RESET_AFTER:
                self._no_reader_poll_count = 0
                try:
                    self._cm.reset_pyscard()
                    logger.debug("Reset pyscard context (no reader detected)")
                except Exception:
                    pass
            if self.on_error:
                try:
                    self.on_error(msg)
                except Exception:
                    pass

    def _read_and_notify(self):
        """Do a full pySim-read and fire the appropriate callback.

        If pySim-read fails or returns no ICCID but we have a cached
        ATR→ICCID mapping (from a prior programming+verification), use
        the cached ICCID instead of declaring the card blank.
        """
        ok, msg = self._cm.detect_card()
        if ok:
            iccid = self._cm.read_iccid()
            if iccid:
                self._last_read_failed = False
                self._last_iccid = iccid
                self._handle_new_card(iccid)
                return

        # pySim-read failed or returned no ICCID.  Check the ATR cache
        # in case this is a just-programmed card being re-inserted.
        cached_iccid = self._atr_iccid_cache.get(self._last_atr)
        if cached_iccid:
            self._last_read_failed = False
            logger.info("CardWatcher: using cached ICCID %s for ATR %s",
                        cached_iccid, self._last_atr)
            self._last_iccid = cached_iccid
            self._handle_new_card(cached_iccid)
            return

        # Distinguish failure reason before classifying the card.
        if not ok:
            # Transport/protocol failure — the card's contents are unknown, not blank.
            # PCSC confirmed the card is physically present (ATR was read), but
            # pySim-read could not communicate with it (e.g. T0 protocol mismatch,
            # CardConnectionException).  This is a READ_ERROR, not BLANK.
            # Calling on_card_unknown here would incorrectly set BLANK state.
            self._last_read_failed = True
            logger.warning("CardWatcher: card present but pySim-read failed: %s", msg)
            if self.on_error:
                try:
                    self.on_error(msg)
                except Exception:
                    pass
            return

        # ok=True but no ICCID → card was contacted successfully and is
        # genuinely blank/unprogrammed (gialersim).  Signal BLANK state.
        self._last_read_failed = False
        self._last_iccid = None
        if self.on_card_unknown:
            try:
                self.on_card_unknown("")
            except Exception:
                pass

    def _check_once_worker(self):
        """Poll iteration using worker probe path."""
        from card_worker_client import WorkerTimeoutError, WorkerEOFError, WorkerCrashError

        try:
            result = self._worker_client.probe()
        except WorkerTimeoutError as exc:
            if self.on_error:
                try:
                    self.on_error(str(exc))
                except Exception:
                    pass
            return
        except (WorkerEOFError, WorkerCrashError) as exc:
            if self.on_error:
                try:
                    self.on_error(str(exc))
                except Exception:
                    pass
            return

        if result.error == 'PROBE_TIMEOUT':
            if self.on_error:
                try:
                    self.on_error(result.msg or 'PROBE_TIMEOUT')
                except Exception:
                    pass
            return

        if result.present:
            new_gen = result.card_gen
            old_gen = self._last_card_gen
            if (self._card_present
                    and new_gen is not None
                    and new_gen == old_gen
                    and not self._last_read_failed):
                return
            # New non-None card_gen means a different card session even if ATR is
            # unchanged — clear _last_atr so _handle_probe_result triggers a fresh read.
            if new_gen is not None and new_gen != old_gen:
                self._last_atr = None
            self._last_card_gen = new_gen
            self._handle_probe_result(True, result.atr or "")
        else:
            self._last_card_gen = None
            self._handle_probe_result(False, result.msg or 'No card in reader')

    def _check_once_slow(self):
        """Slow polling path — full pySim-read every cycle."""
        ok, msg = self._cm.detect_card()

        if ok:
            self._no_card_streak = 0
            iccid = self._cm.read_iccid()
            if iccid and iccid != self._last_iccid:
                # New card detected (with readable ICCID)
                self._last_iccid = iccid
                self._card_present = True
                self._handle_new_card(iccid)
            elif not iccid and not self._card_present:
                # Card detected but no ICCID (blank card) — first time
                self._card_present = True
                self._last_iccid = None
                if self.on_card_unknown:
                    try:
                        self.on_card_unknown("")
                    except Exception:
                        pass
        else:
            if self._card_present:
                if self._last_iccid is None:
                    # Blank card — require confirmation before declaring removal
                    if not hasattr(self, "_no_card_streak"):
                        self._no_card_streak = 0
                    self._no_card_streak += 1
                    if self._no_card_streak < 2:
                        return
                # Card was removed or became unreachable
                self._no_card_streak = 0
                self._last_iccid = None
                self._card_present = False
                if not hasattr(self, "_atr_iccid_cache"):
                    self._atr_iccid_cache = {}
                self._atr_iccid_cache.clear()
                if self.on_card_removed:
                    try:
                        self.on_card_removed()
                    except Exception:
                        pass
            else:
                # No card was previously present.  Fire on_error so the UI
                # reflects the actual state (reader missing, tool missing,
                # etc.) rather than remaining at the initial display
                # indefinitely.  Mirrors _handle_probe_result which always
                # fires on_error in the no-reader / error case.
                if self.on_error:
                    try:
                        self.on_error(msg)
                    except Exception:
                        pass

    def _handle_new_card(self, iccid: str):
        """Process a newly detected card."""
        if self._index:
            logger.info(
                "CardWatcher lookup: iccid=%r len=%d index_id=%d scanned_dirs=%s",
                iccid, len(iccid), id(self._index), self._index.scanned_dirs,
            )
            try:
                logger.info("CardWatcher lookup: index.stats=%s", self._index.stats)
            except Exception as _stats_exc:
                logger.info("CardWatcher lookup: index.stats raised %s", _stats_exc)
            # Refresh stale files before lookup — CSV may have been replaced
            # since the last scan (changed ADM1, new file, deleted file).
            # rescan_if_stale is a fast mtime check; it only re-parses changed files.
            for d in self._index.scanned_dirs:
                self._index.rescan_if_stale(d)
            entry = self._index.lookup(iccid)
            logger.info(
                "CardWatcher lookup: lookup(%r) → entry=%s file_path=%s",
                iccid,
                "hit" if entry else "miss",
                getattr(entry, "file_path", None),
            )
            if entry:
                # Found in index — load full card data
                card_data = self._index.load_card(iccid)
                logger.info(
                    "CardWatcher lookup: load_card(%r) → found=%s",
                    iccid, bool(card_data),
                )
                if card_data and self.on_card_detected:
                    try:
                        self.on_card_detected(
                            iccid, card_data, entry.file_path)
                    except Exception:
                        pass
                    return

        # Card not in index (or no index configured)
        logger.info(
            "CardWatcher lookup: emitting on_card_unknown(%r) "
            "(has_index=%s index_id=%s)",
            iccid,
            bool(self._index),
            id(self._index) if self._index else None,
        )
        if self.on_card_unknown:
            try:
                self.on_card_unknown(iccid)
            except Exception:
                pass


class _PausedContext:
    """Nestable context manager for :meth:`CardWatcher.paused_context`.

    Tracks nesting depth so that only the outermost ``with`` block
    actually resumes the watcher.  This prevents an inner block from
    prematurely resuming polling while an outer block is still running
    pySim operations.
    """

    def __init__(self, watcher: CardWatcher):
        self._watcher = watcher

    def __enter__(self):
        # Track nesting depth on the watcher instance
        depth = getattr(self._watcher, '_pause_depth', 0)
        self._watcher._pause_depth = depth + 1
        if depth == 0:
            self._watcher.pause()
        return self._watcher

    def __exit__(self, exc_type, exc_val, exc_tb):
        depth = getattr(self._watcher, '_pause_depth', 1)
        self._watcher._pause_depth = max(0, depth - 1)
        if self._watcher._pause_depth == 0:
            self._watcher.resume()
        return False  # Don't suppress exceptions
