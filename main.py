#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimGUI - SIM Card Programming GUI

Main entry point using PyQt6. Builds the application window and wires
together managers, panels, and state management.
"""

from __future__ import annotations

import csv
import logging
import os
import sys
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QSplitter,
    QTabWidget,
    QLabel,
    QStatusBar,
    QFileDialog,
    QMessageBox,
)

from managers.auto_artifact_manager import AutoArtifactManager, DEFAULT_ARTIFACT_FIELDS
from managers.card_manager import CardManager, CLIBackend
from managers.card_watcher import CardWatcher
from managers.iccid_index import IccidIndex
from managers.network_storage_manager import NetworkStorageManager
from managers.settings_manager import SettingsManager
from managers.standards_manager import StandardsManager
from qt_theme import QtTheme
from state_manager import StateManager, CardState, CardInfo
from utils import get_browse_initial_dir
from version import __version__
from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
from widgets.read_sim_panel import ReadSIMPanel
from widgets.program_sim_panel import ProgramSIMPanel
from widgets.batch_program_panel import BatchProgramPanel
from widgets.csv_editor_panel import CSVEditorPanel
from widgets.progress_panel import ProgressPanel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background Worker (Qt-style async)
# ---------------------------------------------------------------------------

class BackgroundStartupWorker(QObject):
    """Worker for async startup tasks; runs in dedicated thread."""

    finished = pyqtSignal()
    toast_requested = pyqtSignal(str, str, int)
    status_requested = pyqtSignal(str)
    mounts_updated = pyqtSignal(list)
    index_updated = pyqtSignal()

    def __init__(self, ns_manager, iccid_index, standards_mgr=None) -> None:
        super().__init__()
        self._ns_manager = ns_manager
        self._iccid_index = iccid_index
        self._standards_mgr = standards_mgr

    def run(self) -> None:
        """Execute startup tasks and emit signals."""
        try:
            results = self._ns_manager.reconnect_saved()
        except Exception as exc:
            logger.warning("Auto-reconnect failed: %s", exc)
            results = []

        if results:
            ok_labels = [label for label, ok, _ in results if ok]
            if ok_labels:
                names = ", ".join(ok_labels)
                self.toast_requested.emit(
                    f"Network share reconnected: {names}",
                    "success", 5000)
                self.status_requested.emit(
                    f"Network share connected: {names}")
            failed = [(lbl, msg) for lbl, ok, msg in results if not ok]
            if failed:
                names = ", ".join(lbl for lbl, _ in failed)
                self.toast_requested.emit(
                    f"Network share reconnect failed: {names}",
                    "error", 8000)

        # Adopt shares mounted externally or left from a prior session
        try:
            self._ns_manager.sync_os_mounts()
        except Exception as exc:
            logger.warning("sync_os_mounts failed: %s", exc)

        mounts = self._ns_manager.get_active_mount_paths()
        self.mounts_updated.emit(mounts or [])

        for label, mount_path in (mounts or []):
            try:
                result = self._iccid_index.scan_directory(mount_path)
                logger.info("Startup ICCID scan [%s]: %d cards in %d file(s), "
                            "%d skipped, %d error(s)",
                            label, result.total_cards, result.files_scanned,
                            result.files_skipped, len(result.errors))
                for err in result.errors:
                    logger.warning("Scan error [%s]: %s", label, err)
            except Exception as exc:
                logger.warning("ICCID scan failed for %s: %s",
                               mount_path, exc)
            if self._standards_mgr:
                try:
                    self._standards_mgr.load_from_directory(mount_path)
                except Exception as exc:
                    logger.warning("Standards load failed for %s: %s",
                                   mount_path, exc)

        self.index_updated.emit()
        self.finished.emit()


class _ScanSharesWorker(QObject):
    """Lightweight worker: scan share directories and reload standards."""

    index_updated = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, mounts, iccid_index, standards_mgr=None) -> None:
        super().__init__()
        self._mounts = mounts
        self._iccid_index = iccid_index
        self._standards_mgr = standards_mgr

    def run(self) -> None:
        for label, mount_path in self._mounts:
            try:
                result = self._iccid_index.scan_directory(mount_path)
                index_size = self._iccid_index.stats.get("total_cards", "?")
                logger.info("ICCID rescan [%s] path=%s: %d cards in %d file(s), "
                            "%d skipped, %d error(s); index total=%s",
                            label, mount_path, result.total_cards, result.files_scanned,
                            result.files_skipped, len(result.errors), index_size)
                for err in result.errors:
                    logger.warning("Scan error [%s]: %s", label, err)
            except Exception as exc:
                logger.exception("ICCID scan failed for %s: %s", mount_path, exc)
            if self._standards_mgr:
                try:
                    self._standards_mgr.load_from_directory(mount_path)
                except Exception as exc:
                    logger.warning("Standards load failed for %s: %s",
                                   mount_path, exc)
        logger.info("_ScanSharesWorker: emitting index_updated")
        self.index_updated.emit()
        self.finished.emit()


# ---------------------------------------------------------------------------
# CardWatcher → main-thread relay
# ---------------------------------------------------------------------------

class _CardWatcherRelay(QObject):
    """Routes CardWatcher callbacks from background thread to main thread.

    CardWatcher fires callbacks on its polling thread (a plain threading.Thread).
    Emitting a Qt signal from a non-Qt thread and receiving it in the main thread
    uses an automatic QueuedConnection, so handler code always runs on the main
    thread and is safe to touch Qt widgets.
    """
    card_detected  = pyqtSignal(str, object, object)  # iccid, card_data, file_path
    card_unknown   = pyqtSignal(str)                   # iccid (may be empty)
    reader_ready   = pyqtSignal()
    card_removed   = pyqtSignal()
    error_occurred = pyqtSignal(str)                   # message


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

_NOT_POWERED_TEXT = "Card not powered - re-seat the SIM in the reader"

# Substrings in pySim-mapped error messages that indicate a not-powered condition.
_NOT_POWERED_PATTERNS = (
    "card not powered",
    "re-seat the sim",
)


def _map_watcher_error(
    state_manager: "StateManager",
    msg: str,
    current_state: "CardState",
    card_physically_present: bool,
) -> None:
    """Map a CardWatcher error to StateManager card_state + status_text.

    NOT_POWERED: card is physically present but not electrically powered/readable.
    Detected by 'card not powered' or 're-seat' substrings in the error message.
    Sets card_state = NOT_POWERED and canonical status_text.

    ERROR: reader absent or PCSC communication failure with no card present.
    Sets card_state = ERROR and status_text = msg when the reader is genuinely
    absent ('No smart-card reader' in msg) or when no card has been physically
    confirmed present.

    Guard: if a card is physically in the reader (DETECTED/BLANK/AUTHENTICATED,
    or _card_present=True), transient PCSC errors do NOT demote the state to
    ERROR — preserving the card-present display during programming windows.

    Always calls report_error to log the message regardless of state change.
    """
    msg_lower = msg.lower()
    is_not_powered = any(p in msg_lower for p in _NOT_POWERED_PATTERNS)
    if is_not_powered:
        state_manager.card_state = CardState.NOT_POWERED
        state_manager.status_text = _NOT_POWERED_TEXT
        state_manager.report_error(msg)
        return

    is_no_reader = "No smart-card reader" in msg
    if is_no_reader or (
        current_state
        not in (CardState.BLANK, CardState.DETECTED, CardState.AUTHENTICATED,
                CardState.NOT_POWERED)
        and not card_physically_present
    ):
        state_manager.card_state = CardState.ERROR
        state_manager.status_text = msg
    state_manager.report_error(msg)


class SimGUIApp(QMainWindow):
    """Main application window using PyQt6."""

    def __init__(self) -> None:
        super().__init__()

        # ---- Window setup ------------------------------------------------
        git_hash = self._get_git_hash()
        title = f"SimGUI {__version__}"
        if git_hash:
            title += f" ({git_hash})"
        title += " — SIM Card Programmer"
        self.setWindowTitle(title)
        self.resize(1024, 700)
        self.setMinimumSize(800, 500)

        # Window icon
        assets_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "assets")
        icon_path = os.path.join(assets_dir, "simgui-256.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # ---- State manager -----------------------------------------------
        self.state_manager = StateManager(self)

        # ---- Managers (framework-independent) ----------------------------
        self._card_manager = CardManager()
        self._settings = SettingsManager()
        self._ns_manager = NetworkStorageManager(self._settings)
        self._iccid_index = IccidIndex()
        self._auto_artifact = AutoArtifactManager(self._ns_manager)
        self._standards_mgr = StandardsManager()
        self._card_watcher = CardWatcher(
            self._card_manager, self._iccid_index, poll_interval=1.5)

        # Shared state
        self.last_read_data: dict[str, str] = {}
        self._last_programmed_card: Optional[dict] = None
        self._startup_worker_thread: Optional[QThread] = None
        self._startup_worker: Optional[QObject] = None
        self._rescan_timer: Optional[QTimer] = None
        self._active_mounts: list = []

        # ---- Build UI ----
        self._build_menu()
        self._build_layout()
        self._connect_signals()
        self._wire_card_watcher()

        # Restore window geometry
        geom = self._settings.get("window_geometry", "")
        if geom:
            try:
                parts = geom.split('x')
                if len(parts) == 2:
                    w, h = int(parts[0]), int(parts[1])
                    self.resize(w, h)
            except (ValueError, AttributeError):
                pass

        # ---- Startup sequence ----
        if self._card_manager.cli_backend == CLIBackend.NONE:
            self.state_manager.status_text = (
                "pySim not found. Install pySim and restart the application."
            )
        else:
            QTimer.singleShot(100, self._startup_detect_card)

        QTimer.singleShot(0, self._background_startup)

        # Periodic background rescan: refresh ICCID index every 5 minutes
        # while shares are connected, so cards inserted after startup are
        # found without requiring a manual "Scan Directory" or app restart.
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setInterval(5 * 60 * 1000)  # 5 min
        self._rescan_timer.timeout.connect(self._rescan_shares_background)
        self._rescan_timer.start()

    @staticmethod
    def _get_git_hash() -> str:
        """Return short git commit hash, or empty string if unavailable."""
        import subprocess as _sp
        app_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            r = _sp.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=3,
                cwd=app_dir,
            )
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception:
            pass
        build_file = os.path.join(app_dir, "BUILD")
        try:
            with open(build_file, "r") as fh:
                return fh.read().strip()
        except OSError:
            pass
        return ""

    # ---- Layout -------------------------------------------------------

    def _build_layout(self) -> None:
        """Create the main tab layout with status bar."""
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 0)

        # Tab widget
        self._tabs = QTabWidget()

        self._read_panel = ReadSIMPanel(
            self._tabs,
            card_manager=self._card_manager,
            state_manager=self.state_manager,
            last_read_data=self.last_read_data,
            ns_manager=self._ns_manager,
            card_watcher=self._card_watcher)
        self._tabs.addTab(self._read_panel, "Read SIM")

        self._program_panel = ProgramSIMPanel(
            self._tabs,
            card_manager=self._card_manager,
            state_manager=self.state_manager,
            last_read_data=self.last_read_data,
            ns_manager=self._ns_manager,
            card_watcher=self._card_watcher)
        self._program_panel.on_card_programmed_callback = self._on_card_programmed
        self._tabs.addTab(self._program_panel, "Program SIM")

        self._batch_panel = BatchProgramPanel(
            self._tabs,
            card_manager=self._card_manager,
            state_manager=self.state_manager,
            settings=self._settings,
            ns_manager=self._ns_manager,
            card_watcher=self._card_watcher,
            iccid_index=self._iccid_index,
            auto_artifact_manager=self._auto_artifact)
        self._batch_panel.set_standards_manager(self._standards_mgr)
        self._tabs.addTab(self._batch_panel, "Batch Program")

        self._csv_panel = CSVEditorPanel(
            self._tabs,
            state_manager=self.state_manager,
            ns_manager=self._ns_manager)
        self._tabs.addTab(self._csv_panel, "CSV Editor")

        self._progress_panel = ProgressPanel(
            self._tabs,
            state_manager=self.state_manager)
        self._tabs.addTab(self._progress_panel, "Progress")

        self._tabs.setCurrentWidget(self._program_panel)
        root_layout.addWidget(self._tabs)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("Ready")
        self._status_bar.addWidget(self._status_label, stretch=1)
        self._share_label = QLabel("No network storage connected")
        self._share_label.setStyleSheet("color: #D4860A;")
        self._status_bar.addPermanentWidget(self._share_label)

    # ---- Menu bar ---------------------------------------------------

    def _build_menu(self) -> None:
        """Create the menu bar."""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")

        open_act = QAction("Open CSV...", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._on_open_csv)
        file_menu.addAction(open_act)

        scan_act = QAction("Scan Directory...", self)
        scan_act.setShortcut("Ctrl+D")
        scan_act.triggered.connect(self._on_scan_directory)
        file_menu.addAction(scan_act)

        save_act = QAction("Save CSV...", self)
        save_act.setShortcut("Ctrl+S")
        save_act.triggered.connect(self._on_save_csv)
        file_menu.addAction(save_act)

        file_menu.addSeparator()

        ns_act = QAction("Network Storage...", self)
        ns_act.triggered.connect(self._on_network_storage)
        file_menu.addAction(ns_act)

        export_act = QAction("Export Artifacts...", self)
        export_act.triggered.connect(self._on_export_artifacts)
        file_menu.addAction(export_act)

        file_menu.addSeparator()

        exit_act = QAction("Exit", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        # Card menu
        card_menu = menu_bar.addMenu("&Card")

        detect_act = QAction("Detect Card", self)
        detect_act.triggered.connect(self._on_detect_card)
        card_menu.addAction(detect_act)

        auth_act = QAction("Authenticate...", self)
        auth_act.triggered.connect(self._on_authenticate)
        card_menu.addAction(auth_act)


        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

    # ---- Signal connections -------------------------------------------

    def _connect_signals(self) -> None:
        """Subscribe UI elements to StateManager signals."""
        self.state_manager.status_changed.connect(self._on_status_changed)
        self.state_manager.card_state_changed.connect(self._on_card_state_changed)
        self.state_manager.card_info_changed.connect(self._on_card_info_changed)
        self.state_manager.share_status_changed.connect(self._on_share_status_changed)
        self.state_manager.iccid_index_updated.connect(self._on_index_updated)

    def _on_status_changed(self, text: str) -> None:
        self._status_label.setText(text)

    def _on_card_state_changed(self, state: CardState) -> None:
        pass

    def _on_card_info_changed(self, info: CardInfo) -> None:
        pass

    def _on_share_status_changed(self, status) -> None:
        if status.connected:
            if status.mount_paths:
                parts = [f"● {label} ({path})" for label, path in status.mount_paths]
                self._share_label.setText(" | ".join(parts))
            else:
                self._share_label.setText(status.display_text)
            self._share_label.setStyleSheet(f"color: {QtTheme.get_color('success')};")
        else:
            # Show explicit error text (e.g. reconnect failure) when set;
            # otherwise show the generic disconnected indicator.
            text = getattr(status, "error_text", "") or "No network storage connected"
            self._share_label.setText(text)
            self._share_label.setStyleSheet("color: #D4860A;")

    # ---- CardWatcher → StateManager bridge ----------------------------

    def _wire_card_watcher(self) -> None:
        """Connect CardWatcher callbacks → StateManager mutations via Qt relay.

        CardWatcher fires callbacks on a background threading.Thread.  Direct
        Qt widget access from that thread is illegal (QTextDocument child
        creation warning).  The relay object lives in the main thread; emitting
        its signals from the background thread uses Qt's automatic
        QueuedConnection so every handler runs safely on the main thread.
        """
        relay = _CardWatcherRelay(self)
        self._watcher_relay = relay  # keep alive

        def on_detected(iccid, card_data, file_path):
            self.state_manager.card_state = CardState.DETECTED
            # Merge pySim-read data with CSV data: CSV wins when both have a value;
            # pySim-read fills in fields the CSV omits (IMSI, ACC, SPN, FPLMN).
            raw = self._card_manager.card_info or {}
            self.state_manager.update_card_info(
                iccid=iccid,
                imsi=card_data.get("IMSI", "") or raw.get("IMSI", ""),
                acc=card_data.get("ACC") or raw.get("ACC", "-"),
                spn=card_data.get("SPN") or raw.get("SPN", "-"),
                fplmn=card_data.get("FPLMN") or raw.get("FPLMN", "-"),
                source_file=file_path,
                auth_status=False,
            )
            self.state_manager.status_text = f"Card detected: {iccid}"
            self._program_panel.on_card_detected(iccid, card_data, file_path)

        def on_unknown(iccid):
            if iccid:
                self.state_manager.card_state = CardState.DETECTED
                self.state_manager.status_text = f"Card: {iccid} (not in index)"
            else:
                self.state_manager.card_state = CardState.BLANK
                self.state_manager.status_text = "Blank card detected (no ICCID)"
            raw = self._card_manager.card_info or {}
            self.state_manager.update_card_info(
                iccid=iccid or "(blank)",
                imsi=raw.get("IMSI", ""),
                acc=raw.get("ACC", "-"),
                spn=raw.get("SPN", "-"),
                fplmn=raw.get("FPLMN", "-"),
                auth_status=False,
            )
            self._program_panel.on_card_detected(iccid, None, None)

        def on_reader_ready():
            self.state_manager.card_state = CardState.NO_CARD
            self.state_manager.status_text = "Reader connected — insert a SIM card"

        def on_removed():
            self.state_manager.card_state = CardState.NO_CARD
            self.state_manager.clear_card_info()
            self.state_manager.status_text = "Card removed"

        def on_error(msg):
            _map_watcher_error(
                self.state_manager, msg,
                self.state_manager.card_state,
                self._card_watcher._card_present,
            )

        # Connect relay signals to handlers with explicit QueuedConnection.
        # This guarantees handlers execute on the main thread's event loop
        # regardless of which thread emits the signal.
        relay.card_detected.connect(on_detected, Qt.ConnectionType.QueuedConnection)
        relay.card_unknown.connect(on_unknown, Qt.ConnectionType.QueuedConnection)
        relay.reader_ready.connect(on_reader_ready, Qt.ConnectionType.QueuedConnection)
        relay.card_removed.connect(on_removed, Qt.ConnectionType.QueuedConnection)
        relay.error_occurred.connect(on_error, Qt.ConnectionType.QueuedConnection)

        # Watcher callbacks are now just signal emitters — no Qt object access.
        self._card_watcher.on_card_detected = relay.card_detected.emit
        self._card_watcher.on_card_unknown  = relay.card_unknown.emit
        self._card_watcher.on_reader_ready  = relay.reader_ready.emit
        self._card_watcher.on_card_removed  = relay.card_removed.emit
        self._card_watcher.on_error         = relay.error_occurred.emit
        self._card_watcher.start()

    def _startup_detect_card(self) -> None:
        """Trigger initial card detection."""
        if self._card_manager.cli_backend == CLIBackend.NONE:
            return
        try:
            self._card_watcher._check_once()
        except Exception as exc:
            logger.warning("Startup card detection failed: %s", exc)

    def _background_startup(self) -> None:
        """Launch slow startup tasks in a dedicated worker thread."""
        if self._startup_worker_thread is not None:
            return

        worker = BackgroundStartupWorker(
            self._ns_manager, self._iccid_index, self._standards_mgr)
        self._startup_worker_thread = QThread()
        worker.moveToThread(self._startup_worker_thread)

        worker.toast_requested.connect(self._on_worker_toast)
        worker.status_requested.connect(self._on_worker_status)
        worker.mounts_updated.connect(self._on_worker_mounts)
        worker.index_updated.connect(self._on_worker_index_updated)
        worker.finished.connect(self._startup_worker_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._startup_worker_thread.finished.connect(self._on_thread_finished)

        self._startup_worker = worker  # keep strong ref so GC doesn't collect before thread fires
        self._startup_worker_thread.started.connect(worker.run)
        self._startup_worker_thread.start()

    def _on_worker_toast(self, msg: str, typ: str, dur: int) -> None:
        self.state_manager.request_toast(msg, typ, dur)

    def _on_worker_status(self, msg: str) -> None:
        self.state_manager.status_text = msg

    def _on_worker_mounts(self, mounts: list) -> None:
        self._active_mounts = mounts or []
        self.state_manager.update_share_status(mounts)

    def _on_worker_index_updated(self) -> None:
        self._card_watcher.index = self._iccid_index
        logger.info("Index refreshed: watcher.index is iccid_index=%s",
                    self._card_watcher.index is self._iccid_index)
        self.state_manager.notify_index_updated()
        self._batch_panel.refresh_standards()

    def _on_thread_finished(self) -> None:
        self._startup_worker_thread = None
        self._startup_worker = None

    # ---- Menu callbacks -----------------------------------------------

    def _on_open_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager)
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SIM Data File", init_dir or "",
            "CSV files (*.csv);;EML files (*.eml);;Text files (*.txt);;All files (*.*)")
        if path:
            self._program_panel.load_csv_file(path)
            self.state_manager.status_text = f"Loaded {path}"
            self._settings.set("last_csv_path", path)

    def _on_scan_directory(self):
        init_dir = get_browse_initial_dir(self._ns_manager)
        path = QFileDialog.getExistingDirectory(
            self, "Select directory with SIM data files", init_dir or "")
        if path:
            result = self._iccid_index.scan_directory(path)
            self._standards_mgr.load_from_directory(path)
            self._batch_panel.refresh_standards()
            self.state_manager.status_text = (
                f"Scanned: {result.total_cards} cards in {result.files_scanned} file(s)")
            self.state_manager.notify_index_updated()

    def _on_save_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV", init_dir or "", "CSV files (*.csv);;All files (*.*)")
        if path:
            self.state_manager.status_text = f"Saved {path}"

    def _on_detect_card(self):
        self.state_manager.status_text = "Detecting card..."

    def _on_authenticate(self):
        self.state_manager.status_text = "Authenticate action"

    def _on_network_storage(self):
        """Open the Network Storage configuration dialog."""
        dlg = NetworkStorageDialogQt(self, self._ns_manager)
        dlg.exec()
        # Rescan any newly mounted shares for SIM data and standards
        self._rescan_shares_background()

    def _rescan_shares_background(self) -> None:
        """Scan all mounted share directories in a background thread."""
        try:
            self._ns_manager.sync_os_mounts()
        except Exception as exc:
            logger.warning("sync_os_mounts failed: %s", exc)
        mounts = self._ns_manager.get_active_mount_paths()
        logger.info("_rescan_shares_background: %d active mount(s): %s",
                    len(mounts or []), mounts)
        if mounts:
            self._active_mounts = mounts
            self.state_manager.update_share_status(mounts)
        if not mounts:
            return
        worker = _ScanSharesWorker(mounts, self._iccid_index, self._standards_mgr)
        self._rescan_worker = worker  # keep strong ref so GC doesn't collect before thread fires
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.index_updated.connect(self._on_worker_index_updated)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)
        logger.info("_rescan_shares_background: starting worker for %d mount(s)", len(mounts))
        thread.start()

    def _on_index_updated(self) -> None:
        """When the ICCID index refreshes, try to autofill if card already in reader."""
        if self.state_manager.card_state not in (
                CardState.DETECTED, CardState.AUTHENTICATED):
            logger.info("_on_index_updated: skipped (state=%s)",
                        self.state_manager.card_state)
            return
        iccid = self.state_manager.card_info.iccid
        if not iccid or iccid == "(blank)":
            logger.info("_on_index_updated: skipped (iccid=%r)", iccid)
            return
        card_data = self._iccid_index.load_card(iccid)
        logger.info("_on_index_updated: ICCID=%s found=%s", iccid, card_data is not None)
        if card_data:
            entry = self._iccid_index.lookup(iccid)
            file_path = entry.file_path if entry else None
            self._program_panel.on_card_detected(iccid, card_data, file_path)
            src = os.path.basename(file_path) if file_path else "index"
            self.state_manager.status_text = (
                f"Card data loaded from {src}: {iccid}")

    def _on_card_programmed(self, card_data: dict) -> list:
        """Store last programmed card, save artifact, and return saved paths."""
        self._last_programmed_card = card_data
        self.state_manager.notify_card_programmed(card_data)
        return self._auto_artifact.save_card_artifact(card_data)

    def _on_export_artifacts(self):
        if not self._last_programmed_card:
            QMessageBox.information(
                self, "Export Artifacts",
                "No recently programmed SIM found.\n"
                "Program a SIM card first, then use File → Export Artifacts.")
            return

        iccid = self._last_programmed_card.get("ICCID", "unknown")
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Artifact CSV",
            f"sim_artifact_{iccid}.csv",
            "CSV Files (*.csv);;All Files (*)")

        if not filename:
            return

        row = {f: self._last_programmed_card.get(
                   f, self._last_programmed_card.get(f.upper(), ""))
               for f in DEFAULT_ARTIFACT_FIELDS}
        row["programmed_at"] = datetime.now().isoformat()
        try:
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
                writer.writeheader()
                writer.writerow(row)
            QMessageBox.information(
                self, "Export Complete", f"Artifact saved to:\n{filename}")
        except OSError as exc:
            QMessageBox.warning(
                self, "Export Error", f"Could not write file:\n{exc}")

    def _on_about(self):
        QMessageBox.information(
            self, "About SimGUI",
            f"SimGUI — SIM Card Programming GUI\n"
            f"Version {__version__}\n\n"
            f"A lightweight GUI wrapper for pySim.\n\n"
            f"https://github.com/SeJohnEff/SimGUI")

    # ---- Window close -------------------------------------------------

    def closeEvent(self, event) -> None:
        self._card_watcher.stop()
        self._shutdown_worker()
        self._settings.set("window_geometry",
                           f"{self.width()}x{self.height()}")
        self._settings.save()
        self._ns_manager.unmount_all()
        event.accept()

    def _shutdown_worker(self) -> None:
        if self._startup_worker_thread is not None:
            self._startup_worker_thread.quit()
            self._startup_worker_thread.wait()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = QApplication(sys.argv)
    QtTheme.apply(app)
    window = SimGUIApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
