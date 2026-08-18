#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Central application state with Qt signal emissions.

The StateManager owns **all** mutable UI-visible state.  Every property
setter emits a typed Qt signal so widgets can subscribe without coupling
to each other.  Thread-safe: Qt auto-queues cross-thread signal emissions
to the receiver's event loop.

Design principles
-----------------
* Managers layer (card_manager, csv_manager, …) stays framework-free.
* StateManager wraps managers and translates their callbacks into signals.
* Widgets read state via properties; they never import each other.
* Only the MainWindow (or a thin controller) writes to StateManager.

Usage (Phase 1+)::

    from PyQt6.QtWidgets import QApplication
    from state_manager import StateManager

    app = QApplication([])
    sm = StateManager()

    # Subscribe
    sm.card_state_changed.connect(my_panel.on_card_state)
    sm.status_changed.connect(status_bar.setText)

    # Mutate — signal fires automatically
    sm.card_state = "detected"
    sm.status_text = "Card detected: 8946..."
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Union, Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums for strongly-typed state
# ---------------------------------------------------------------------------

class CardState(Enum):
    """Possible states of the card reader slot."""
    NO_CARD = auto()       # Reader empty — waiting for insertion
    DETECTED = auto()      # Card present, ICCID read, not yet authenticated
    AUTHENTICATED = auto() # ADM1 verified
    ERROR = auto()         # Reader / communication error
    BLANK = auto()         # Card present but no ICCID (factory-blank)
    NOT_POWERED = auto()   # Card physically present but not powered; re-seat required


class ProgramOutcome(Enum):
    """Result of a single programming attempt.

    Canonical vocabulary defined in docs/reference/state-machine.md
    (Programming Outcome States). Independent of CardState.
    """
    IDLE = auto()
    NO_CHANGES = auto()
    ICCID_MISMATCH = auto()
    ADM1_LOCKED = auto()
    ADM1_AUTH_FAILED = auto()
    WRITE_FAILED = auto()
    WRITE_OK_VERIFIED = auto()
    WRITE_OK_PENDING = auto()
    WRITE_OK_VERIFICATION_FAILED = auto()
    # Writes completed but key verification could NOT be run (crypto backend
    # missing, self-test failed, transport error, or check skipped). This is a
    # FAILURE state, distinct from WRITE_OK_VERIFICATION_FAILED (keys proven
    # wrong): here we simply do not know, and fail-closed policy forbids
    # reporting an unverified card as programmed. See docs/reference/
    # state-machine.md (Programming Outcome States) and the gialersim self-check.
    VERIFY_UNAVAILABLE = auto()


@dataclass(frozen=True)
class ProgramResult:
    """Immutable result of a single programming attempt."""
    outcome: ProgramOutcome = ProgramOutcome.IDLE
    message: str = ""
    verified_fields: tuple[str, ...] = ()
    written_only_fields: tuple[str, ...] = ()
    skipped_fields: tuple[str, ...] = ()
    failed_fields: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Lightweight data containers
# ---------------------------------------------------------------------------

@dataclass
class CardInfo:
    """Snapshot of the currently inserted card's identity fields."""
    iccid: str = ""
    imsi: str = ""
    acc: str = "-"
    spn: str = "-"
    fplmn: str = "-"
    card_type: str = ""
    source_file: str = ""
    auth_status: bool = False
    already_programmed: bool = False

    def clear(self) -> None:
        """Reset all fields to defaults (card removed)."""
        self.iccid = ""
        self.imsi = ""
        self.acc = "-"
        self.spn = "-"
        self.fplmn = "-"
        self.card_type = ""
        self.source_file = ""
        self.auth_status = False
        self.already_programmed = False

    def to_dict(self) -> dict[str, str]:
        """Return a plain dict for backward compatibility."""
        return {
            "ICCID": self.iccid,
            "IMSI": self.imsi,
            "ACC": self.acc,
            "SPN": self.spn,
            "FPLMN": self.fplmn,
            "card_type": self.card_type,
            "source_file": self.source_file,
        }


@dataclass
class ShareStatus:
    """Current network share connection state."""
    connected: bool = False
    labels: list[str] = field(default_factory=list)
    mount_paths: list[tuple[str, str]] = field(default_factory=list)
    error_text: str = ""   # explicit failure message; takes precedence over generic "No network storage connected"

    @property
    def display_text(self) -> str:
        if not self.connected:
            return ""
        return f"\u25cf NAS: {', '.join(self.labels)}"

    @property
    def tooltip_text(self) -> str:
        if not self.connected:
            return "No network share connected"
        return "\n".join(
            f"{label}: {path}" for label, path in self.mount_paths)


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------

class StateManager(QObject):
    """Central state store with Qt signal emissions.

    Every public property has a corresponding ``<name>_changed`` signal.
    Setting a property to the same value is a no-op (no signal emitted).

    Signals
    -------
    card_state_changed(CardState)
        Card reader state transitions.
    card_info_changed(CardInfo)
        Any card identity field changed (ICCID, IMSI, …).
    status_changed(str)
        Status bar text update.
    share_status_changed(ShareStatus)
        Network share mount/unmount.
    csv_path_changed(str)
        Active CSV file changed.
    batch_running_changed(bool)
        Batch programming started/stopped.
    error_occurred(str)
        Non-fatal error message for toast/popup display.
    toast_requested(str, str, int)
        Request a toast notification: (message, level, duration_ms).
    card_programmed(dict)
        A card was successfully programmed — payload is the card data dict.
    iccid_index_updated()
        The ICCID index was rescanned.
    """

    # -- Signals ------------------------------------------------------------
    card_state_changed = pyqtSignal(object)       # CardState
    card_info_changed = pyqtSignal(object)         # CardInfo
    card_identified = pyqtSignal(object)           # CardType — fired on the
    #   UNKNOWN→known identity edge only (never on removal / de-identify).
    status_changed = pyqtSignal(str)
    share_status_changed = pyqtSignal(object)      # ShareStatus
    csv_path_changed = pyqtSignal(str)
    batch_running_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)
    toast_requested = pyqtSignal(str, str, int)    # msg, level, duration
    card_programmed = pyqtSignal(dict)
    program_result_changed = pyqtSignal(object)  # ProgramResult
    iccid_index_updated = pyqtSignal()
    verify_availability_changed = pyqtSignal(bool)  # key-verification available?

    def __init__(self, parent: Optional[QObject]= None) -> None:
        super().__init__(parent)

        # Internal state
        self._card_state = CardState.NO_CARD
        self._card_info = CardInfo()
        self._card_type = None            # authoritative card identity (CardType)
        self._status_text = "Ready"
        self._share_status = ShareStatus()
        self._csv_path = ""
        self._batch_running = False

        # Session-scoped one-shot notice registry: makes "show this at most once
        # per application session" a structural property (see claim_once) rather
        # than a boolean flag bolted onto a widget.
        self._fired_notices: set[str] = set()

        # Key-verification capability (offline USIM AUTHENTICATE self-check).
        # Determined by a startup self-test; when False, fail-closed policy
        # disables gialersim programming unless the operator opts in explicitly.
        self._keys_verification_available = True
        self._allow_unverified_programming = False

    # -- card_state ---------------------------------------------------------

    @property
    def card_state(self) -> CardState:
        return self._card_state

    @card_state.setter
    def card_state(self, value: CardState) -> None:
        if self._card_state is value:
            return
        self._card_state = value
        self.card_state_changed.emit(value)
        logger.debug("card_state → %s", value.name)

    # -- card_info ----------------------------------------------------------

    @property
    def card_info(self) -> CardInfo:
        return self._card_info

    def update_card_info(self, **kwargs: Any) -> None:
        """Update one or more CardInfo fields and emit the signal.

        Only emits if at least one field actually changed.
        """
        changed = False
        for key, value in kwargs.items():
            if not hasattr(self._card_info, key):
                raise AttributeError(
                    f"CardInfo has no field '{key}'")
            if getattr(self._card_info, key) != value:
                setattr(self._card_info, key, value)
                changed = True
        if changed:
            self.card_info_changed.emit(self._card_info)

    def clear_card_info(self) -> None:
        """Reset card info to defaults (card removed) and emit."""
        self._card_info.clear()
        self.card_info_changed.emit(self._card_info)

    # -- card_type (authoritative identity) ---------------------------------

    @property
    def card_type(self):
        """The authoritative detected card identity (a ``CardType`` enum).

        This is the single source of truth for card-type-driven UI (SUCI
        support, hardcoded ADM1, field schema). Widgets must read this, not
        ``CardManager.card_type`` — the manager's copy is an internal working
        value that is not reset on removal, which is exactly what caused the
        SUCI popup to fire on a removed card.
        """
        return self._card_type

    @card_type.setter
    def card_type(self, value) -> None:
        if self._card_type is value:
            return
        self._card_type = value
        # Fire the "identified" edge only when we transition INTO a known type.
        # Clearing to UNKNOWN/None on removal is a de-identify, not an identify,
        # so it must not drive identity-triggered notifications (e.g. the
        # SUCI-unsupported dialog must never appear on card removal).
        name = getattr(value, "name", None)
        if name and name != "UNKNOWN":
            self.card_identified.emit(value)
            logger.debug("card_identified → %s", name)

    # -- session one-shot notices -------------------------------------------

    def claim_once(self, notice_id: str) -> bool:
        """Return True the first time *notice_id* is claimed this session.

        Structural "once per session" primitive: the first caller for a given
        id gets True (and should show the notice); every later caller gets
        False. The registry lives for the process/session, so callers need no
        local flag. Reset only by starting a new session.
        """
        if notice_id in self._fired_notices:
            return False
        self._fired_notices.add(notice_id)
        return True

    # -- key-verification capability / fail-closed override -----------------

    @property
    def keys_verification_available(self) -> bool:
        return self._keys_verification_available

    @keys_verification_available.setter
    def keys_verification_available(self, value: bool) -> None:
        value = bool(value)
        if self._keys_verification_available == value:
            return
        self._keys_verification_available = value
        self.verify_availability_changed.emit(value)

    @property
    def allow_unverified_programming(self) -> bool:
        return self._allow_unverified_programming

    @allow_unverified_programming.setter
    def allow_unverified_programming(self, value: bool) -> None:
        value = bool(value)
        if self._allow_unverified_programming == value:
            return
        self._allow_unverified_programming = value
        # Reuse the same signal so the panel re-evaluates the pre-gate when the
        # operator toggles the override.
        self.verify_availability_changed.emit(self._keys_verification_available)

    # -- status_text --------------------------------------------------------

    @property
    def status_text(self) -> str:
        return self._status_text

    @status_text.setter
    def status_text(self, value: str) -> None:
        if self._status_text == value:
            return
        self._status_text = value
        self.status_changed.emit(value)

    # -- share_status -------------------------------------------------------

    @property
    def share_status(self) -> ShareStatus:
        return self._share_status

    def update_share_status(
        self,
        mount_paths: Optional[list[tuple[str, str]]] = None,
        error: str = "",
    ) -> None:
        """Refresh share status from the active mount list.

        Parameters
        ----------
        mount_paths :
            List of ``(label, path)`` tuples from
            ``NetworkStorageManager.get_active_mount_paths()``.
            Pass ``None`` or ``[]`` when no shares are connected.
        error :
            Optional explicit error message (e.g. reconnect failure text).
            When set, the UI shows this instead of the generic disconnected
            indicator, so a specific failure reason remains visible.
        """
        mounts = mount_paths or []
        new = ShareStatus(
            connected=bool(mounts),
            labels=[label for label, _path in mounts],
            mount_paths=list(mounts),
            error_text=error,
        )
        # Only emit if something actually changed
        if (new.connected != self._share_status.connected
                or new.labels != self._share_status.labels
                or new.error_text != self._share_status.error_text):
            self._share_status = new
            self.share_status_changed.emit(new)

    # -- csv_path -----------------------------------------------------------

    @property
    def csv_path(self) -> str:
        return self._csv_path

    @csv_path.setter
    def csv_path(self, value: str) -> None:
        if self._csv_path == value:
            return
        self._csv_path = value
        self.csv_path_changed.emit(value)

    # -- batch_running ------------------------------------------------------

    @property
    def batch_running(self) -> bool:
        return self._batch_running

    @batch_running.setter
    def batch_running(self, value: bool) -> None:
        if self._batch_running is value:
            return
        self._batch_running = value
        self.batch_running_changed.emit(value)

    # -- Convenience methods ------------------------------------------------

    def request_toast(
        self, message: str, level: str = "info", duration_ms: int = 5000,
    ) -> None:
        """Emit a toast request for the UI layer to display."""
        self.toast_requested.emit(message, level, duration_ms)

    def report_error(self, message: str) -> None:
        """Emit a non-fatal error for UI display."""
        self.error_occurred.emit(message)
        logger.warning("StateManager error: %s", message)

    def notify_card_programmed(self, card_data: dict, result: "ProgramResult") -> None:
        """Emit programming signals.

        program_result_changed fires for every outcome.
        card_programmed fires only for WRITE_OK_VERIFIED.
        """
        self.program_result_changed.emit(result)
        if result.outcome == ProgramOutcome.WRITE_OK_VERIFIED:
            self.card_programmed.emit(card_data)

    def notify_index_updated(self) -> None:
        """Emit the iccid_index_updated signal after a rescan."""
        self.iccid_index_updated.emit()
