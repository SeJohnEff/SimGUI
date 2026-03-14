"""
Card Watcher — Background thread that polls for card insert/remove.

Eliminates the manual "Detect Card" button.  When a card is inserted,
the watcher reads the ICCID (no authentication required) and emits
events so the UI can auto-populate fields.

Events (callbacks):
  on_card_detected(iccid, card_data, file_path)
      Card inserted, matched in index.  *card_data* is the full profile.
  on_card_unknown(iccid)
      Card inserted but ICCID not found in any indexed file.
  on_card_removed()
      Card was removed from the reader.
  on_error(message)
      Reader communication error.

Thread safety:
  All callbacks are invoked from the watcher thread.  The UI must
  use ``root.after(0, ...)`` to dispatch to the main thread.
"""

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


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
                 poll_interval: float = 1.5):
        self._cm = card_manager
        self._index = iccid_index
        self._poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False

        # Last known ICCID (to detect changes)
        self._last_iccid: Optional[str] = None

        # Callbacks (set by UI layer)
        self.on_card_detected: Optional[
            Callable[[str, dict, str], None]] = None
        self.on_card_unknown: Optional[Callable[[str], None]] = None
        self.on_card_removed: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

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
        logger.info("CardWatcher stopped")

    def pause(self):
        """Pause polling (e.g. during programming)."""
        self._paused = True

    def resume(self):
        """Resume polling after pause."""
        self._paused = False

    def _poll_loop(self):
        """Main polling loop — runs on background thread."""
        while not self._stop_event.is_set():
            if not self._paused:
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
        """Single poll iteration."""
        ok, msg = self._cm.detect_card()

        if ok:
            iccid = self._cm.read_iccid()
            if iccid and iccid != self._last_iccid:
                # New card detected
                self._last_iccid = iccid
                self._handle_new_card(iccid)
            # If same ICCID, do nothing (card still present)
        else:
            if self._last_iccid is not None:
                # Card was removed
                self._last_iccid = None
                if self.on_card_removed:
                    try:
                        self.on_card_removed()
                    except Exception:
                        pass

    def _handle_new_card(self, iccid: str):
        """Process a newly detected card."""
        if self._index:
            entry = self._index.lookup(iccid)
            if entry:
                # Found in index — load full card data
                card_data = self._index.load_card(iccid)
                if card_data and self.on_card_detected:
                    try:
                        self.on_card_detected(
                            iccid, card_data, entry.file_path)
                    except Exception:
                        pass
                    return

        # Card not in index (or no index configured)
        if self.on_card_unknown:
            try:
                self.on_card_unknown(iccid)
            except Exception:
                pass
