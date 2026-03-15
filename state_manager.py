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
from typing import Any, Optional

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


class AppMode(Enum):
    """Hardware vs. simulator mode."""
    HARDWARE = "hardware"
    SIMULATOR = "simulator"


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


@dataclass
class SimulatorInfo:
    """Virtual card position when in simulator mode."""
    current_index: int = 0
    total_cards: int = 0
    active: bool = False


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
    mode_changed(AppMode)
        Hardware ↔ Simulator toggle.
    status_changed(str)
        Status bar text update.
    share_status_changed(ShareStatus)
        Network share mount/unmount.
    csv_path_changed(str)
        Active CSV file changed.
    simulator_info_changed(SimulatorInfo)
        Virtual card index updated.
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
    mode_changed = pyqtSignal(object)              # AppMode
    status_changed = pyqtSignal(str)
    share_status_changed = pyqtSignal(object)      # ShareStatus
    csv_path_changed = pyqtSignal(str)
    simulator_info_changed = pyqtSignal(object)    # SimulatorInfo
    batch_running_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)
    toast_requested = pyqtSignal(str, str, int)    # msg, level, duration
    card_programmed = pyqtSignal(dict)
    iccid_index_updated = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        # Internal state
        self._card_state = CardState.NO_CARD
        self._card_info = CardInfo()
        self._mode = AppMode.HARDWARE
        self._status_text = "Ready"
        self._share_status = ShareStatus()
        self._csv_path = ""
        self._simulator_info = SimulatorInfo()
        self._batch_running = False

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

    # -- mode ---------------------------------------------------------------

    @property
    def mode(self) -> AppMode:
        return self._mode

    @mode.setter
    def mode(self, value: AppMode) -> None:
        if self._mode is value:
            return
        self._mode = value
        self.mode_changed.emit(value)
        logger.debug("mode → %s", value.value)

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
        mount_paths: list[tuple[str, str]] | None = None,
    ) -> None:
        """Refresh share status from the active mount list.

        Parameters
        ----------
        mount_paths :
            List of ``(label, path)`` tuples from
            ``NetworkStorageManager.get_active_mount_paths()``.
            Pass ``None`` or ``[]`` when no shares are connected.
        """
        mounts = mount_paths or []
        new = ShareStatus(
            connected=bool(mounts),
            labels=[label for label, _path in mounts],
            mount_paths=list(mounts),
        )
        # Only emit if something actually changed
        if (new.connected != self._share_status.connected
                or new.labels != self._share_status.labels):
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

    # -- simulator_info -----------------------------------------------------

    @property
    def simulator_info(self) -> SimulatorInfo:
        return self._simulator_info

    def update_simulator_info(
        self,
        current_index: int | None = None,
        total_cards: int | None = None,
        active: bool | None = None,
    ) -> None:
        """Update simulator info and emit if changed."""
        changed = False
        if current_index is not None and self._simulator_info.current_index != current_index:
            self._simulator_info.current_index = current_index
            changed = True
        if total_cards is not None and self._simulator_info.total_cards != total_cards:
            self._simulator_info.total_cards = total_cards
            changed = True
        if active is not None and self._simulator_info.active != active:
            self._simulator_info.active = active
            changed = True
        if changed:
            self.simulator_info_changed.emit(self._simulator_info)

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

    def notify_card_programmed(self, card_data: dict) -> None:
        """Emit the card_programmed signal for auto-artifact saving."""
        self.card_programmed.emit(card_data)

    def notify_index_updated(self) -> None:
        """Emit the iccid_index_updated signal after a rescan."""
        self.iccid_index_updated.emit()
