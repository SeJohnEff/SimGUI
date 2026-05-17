#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimGUI - SIM Card Programming GUI

Main entry point using PyQt6. Builds the application window and wires
together managers, panels, and state management.
"""

from __future__ import annotations

import logging
import os
import sys
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

from managers.auto_artifact_manager import AutoArtifactManager
from managers.card_manager import CardManager, CLIBackend
from managers.card_watcher import CardWatcher
from managers.iccid_index import IccidIndex
from managers.network_storage_manager import NetworkStorageManager
from managers.settings_manager import SettingsManager
from managers.standards_manager import StandardsManager
from qt_theme import QtTheme
from state_manager import StateManager, CardState, AppMode, CardInfo
from utils import get_browse_initial_dir
from version import __version__
from widgets.card_status_panel import CardStatusPanel
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

    def __init__(self, ns_manager, iccid_index) -> None:
        super().__init__()
        self._ns_manager = ns_manager
        self._iccid_index = iccid_index

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

        mounts = self._ns_manager.get_active_mount_paths()
        self.mounts_updated.emit(mounts or [])

        for _label, mount_path in (mounts or []):
            try:
                self._iccid_index.scan_directory(mount_path)
            except Exception as exc:
                logger.warning("ICCID scan failed for %s: %s",
                               mount_path, exc)

        self.index_updated.emit()
        self.finished.emit()


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

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
        self._startup_worker_thread: Optional[QThread] = None

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
            self.state_manager.mode = AppMode.SIMULATOR
        else:
            self.state_manager.mode = AppMode.HARDWARE
            QTimer.singleShot(100, self._startup_detect_card)

        QTimer.singleShot(0, self._background_startup)

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
        """Create the main two-pane layout with status bar."""
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 0)

        # Splitter: left=card status, right=tabs
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: card status panel
        self._card_panel = CardStatusPanel(
            state_manager=self.state_manager)
        self._card_panel.setMaximumWidth(300)
        splitter.addWidget(self._card_panel)

        # Right: tab widget
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

        splitter.addWidget(self._tabs)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([205, 819])
        root_layout.addWidget(splitter)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("Ready")
        self._status_bar.addWidget(self._status_label, stretch=1)
        self._share_label = QLabel("")
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

        card_menu.addSeparator()

        hw_act = QAction("Hardware Mode", self)
        hw_act.setCheckable(True)
        hw_act.setChecked(True)
        hw_act.triggered.connect(self._on_mode_hardware)
        card_menu.addAction(hw_act)
        self._hw_act = hw_act

        sim_act = QAction("Simulator Mode", self)
        sim_act.setCheckable(True)
        sim_act.triggered.connect(self._on_mode_simulator)
        card_menu.addAction(sim_act)
        self._sim_act = sim_act

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
        self.state_manager.mode_changed.connect(self._on_mode_changed)

    def _on_status_changed(self, text: str) -> None:
        self._status_label.setText(text)

    def _on_card_state_changed(self, state: CardState) -> None:
        pass

    def _on_card_info_changed(self, info: CardInfo) -> None:
        pass

    def _on_share_status_changed(self, status) -> None:
        self._share_label.setText(status.display_text)
        if status.connected:
            self._share_label.setStyleSheet(f"color: {QtTheme.get_color('success')};")
        else:
            self._share_label.setStyleSheet("")

    def _on_mode_changed(self, mode: AppMode) -> None:
        prefix = "[SIM] " if mode == AppMode.SIMULATOR else ""
        text = f"{prefix}{'Simulator' if mode == AppMode.SIMULATOR else 'Hardware'} mode active"
        self.state_manager.status_text = text
        self._hw_act.setChecked(mode == AppMode.HARDWARE)
        self._sim_act.setChecked(mode == AppMode.SIMULATOR)

    # ---- CardWatcher → StateManager bridge ----------------------------

    def _wire_card_watcher(self) -> None:
        """Connect CardWatcher callbacks → StateManager mutations."""
        def on_detected(iccid, card_data, file_path):
            self.state_manager.card_state = CardState.DETECTED
            self.state_manager.update_card_info(
                iccid=iccid,
                imsi=card_data.get("IMSI", ""),
                acc=card_data.get("ACC", "-"),
                spn=card_data.get("SPN", "-"),
                fplmn=card_data.get("FPLMN", "-"),
                source_file=file_path,
                auth_status=False,
            )
            self.state_manager.status_text = f"Card detected: {iccid}"

        def on_unknown(iccid):
            if iccid:
                self.state_manager.card_state = CardState.DETECTED
                self.state_manager.status_text = f"Card: {iccid} (not in index)"
            else:
                self.state_manager.card_state = CardState.BLANK
                self.state_manager.status_text = "Blank card detected (no ICCID)"
            self.state_manager.update_card_info(
                iccid=iccid or "(blank)",
                auth_status=False,
            )

        def on_removed():
            self.state_manager.card_state = CardState.NO_CARD
            self.state_manager.clear_card_info()
            self.state_manager.status_text = "Card removed"

        def on_error(msg):
            self.state_manager.card_state = CardState.ERROR
            self.state_manager.report_error(msg)

        self._card_watcher.on_card_detected = on_detected
        self._card_watcher.on_card_unknown = on_unknown
        self._card_watcher.on_card_removed = on_removed
        self._card_watcher.on_error = on_error
        self._card_watcher.start()

    def _startup_detect_card(self) -> None:
        """Trigger initial card detection in hardware mode."""
        if self.state_manager.mode != AppMode.HARDWARE:
            return
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

        worker = BackgroundStartupWorker(self._ns_manager, self._iccid_index)
        self._startup_worker_thread = QThread()
        worker.moveToThread(self._startup_worker_thread)

        worker.toast_requested.connect(self._on_worker_toast)
        worker.status_requested.connect(self._on_worker_status)
        worker.mounts_updated.connect(self._on_worker_mounts)
        worker.index_updated.connect(self._on_worker_index_updated)
        worker.finished.connect(self._startup_worker_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._startup_worker_thread.finished.connect(self._on_thread_finished)

        self._startup_worker_thread.started.connect(worker.run)
        self._startup_worker_thread.start()

    def _on_worker_toast(self, msg: str, typ: str, dur: int) -> None:
        self.state_manager.request_toast(msg, typ, dur)

    def _on_worker_status(self, msg: str) -> None:
        self.state_manager.status_text = msg

    def _on_worker_mounts(self, mounts: list) -> None:
        self.state_manager.update_share_status(mounts)

    def _on_worker_index_updated(self) -> None:
        self.state_manager.notify_index_updated()

    def _on_thread_finished(self) -> None:
        self._startup_worker_thread = None

    # ---- Menu callbacks -----------------------------------------------

    def _on_open_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager)
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SIM Data File", init_dir or "",
            "CSV files (*.csv);;EML files (*.eml);;Text files (*.txt);;All files (*.*)")
        if path:
            self.state_manager.status_text = f"Loaded {path}"
            self._settings.set("last_csv_path", path)

    def _on_scan_directory(self):
        init_dir = get_browse_initial_dir(self._ns_manager)
        path = QFileDialog.getExistingDirectory(
            self, "Select directory with SIM data files", init_dir or "")
        if path:
            self.state_manager.status_text = f"Scanned {path}"

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

    def _on_mode_hardware(self):
        self.state_manager.mode = AppMode.HARDWARE

    def _on_mode_simulator(self):
        self.state_manager.mode = AppMode.SIMULATOR

    def _on_network_storage(self):
        self.state_manager.status_text = "Network Storage action"

    def _on_export_artifacts(self):
        self.state_manager.status_text = "Export Artifacts action"

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
