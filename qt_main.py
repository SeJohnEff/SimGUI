#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimGUI Qt entry point — Phase 0 stub.

This is the future ``main.py`` replacement.  During the migration
period both entry points coexist:

* ``python main.py``    → current tkinter UI (production)
* ``python qt_main.py`` → PyQt6 UI (work-in-progress)

Phase 0 proves the architecture:
  - StateManager ↔ signal wiring
  - QtTheme stylesheet
  - Manager layer integration (unchanged)
  - CardWatcher → StateManager → UI signal chain

The actual widget panels are still stubs (plain QLabel placeholders).
They will be replaced in Phases 1–3.
"""

from __future__ import annotations

import logging
import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from managers.card_manager import CardManager, CLIBackend
from managers.card_watcher import CardWatcher
from managers.csv_manager import CSVManager
from managers.iccid_index import IccidIndex
from managers.network_storage_manager import NetworkStorageManager
from managers.settings_manager import SettingsManager
from managers.standards_manager import StandardsManager
from managers.auto_artifact_manager import AutoArtifactManager
from qt_theme import QtTheme
from state_manager import AppMode, CardInfo, CardState, StateManager
from version import __version__

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Placeholder panels (replaced in Phases 1–3)
# ---------------------------------------------------------------------------

class _PlaceholderPanel(QWidget):
    """Temporary stub for tabs not yet migrated."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(f"{title}\n(migration in progress)")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("role", "small")
        layout.addWidget(label)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class QtSimGUIApp(QMainWindow):
    """PyQt6 main window — Phase 0 skeleton.

    Wires the StateManager to managers and placeholder panels.
    """

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
        self.state = StateManager(self)

        # ---- Managers (unchanged — framework-independent) ----------------
        self._card_manager = CardManager()
        self._settings = SettingsManager()
        self._ns_manager = NetworkStorageManager(self._settings)
        self._iccid_index = IccidIndex()
        self._auto_artifact = AutoArtifactManager(self._ns_manager)
        self._standards_mgr = StandardsManager()
        self._card_watcher = CardWatcher(
            self._card_manager, self._iccid_index, poll_interval=1.5)

        # ---- Build UI ----------------------------------------------------
        self._build_menu()
        self._build_layout()
        self._connect_signals()
        self._wire_card_watcher()

        # ---- Startup sequence --------------------------------------------
        if self._card_manager.cli_backend == CLIBackend.NONE:
            self.state.mode = AppMode.SIMULATOR
        else:
            self.state.mode = AppMode.HARDWARE
            # Trigger initial card detection after 100ms
            QTimer.singleShot(100, self._startup_detect_card)

        # Background startup (network I/O) via QTimer to keep GUI snappy
        QTimer.singleShot(0, self._background_startup)

    # ---- Layout -----------------------------------------------------------

    def _build_layout(self) -> None:
        """Create the main two-pane layout with status bar."""
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 0)

        # Splitter: left=card status, right=tabs
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: card status placeholder
        self._card_panel = _PlaceholderPanel("Card Status")
        self._card_status_label = self._card_panel.findChild(QLabel)
        splitter.addWidget(self._card_panel)

        # Right: tab widget
        self._tabs = QTabWidget()
        self._tabs.addTab(_PlaceholderPanel("Read SIM"), "Read SIM")
        self._tabs.addTab(_PlaceholderPanel("Program SIM"), "Program SIM")
        self._tabs.addTab(_PlaceholderPanel("Batch Program"), "Batch Program")
        self._tabs.addTab(_PlaceholderPanel("CSV Editor"), "CSV Editor")
        self._tabs.addTab(_PlaceholderPanel("Progress"), "Progress")
        splitter.addWidget(self._tabs)

        splitter.setStretchFactor(0, 0)  # card panel: fixed width
        splitter.setStretchFactor(1, 1)  # tabs: expand
        splitter.setSizes([220, 780])
        root_layout.addWidget(splitter)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("Ready")
        self._status_bar.addWidget(self._status_label, stretch=1)
        self._share_label = QLabel("")
        self._status_bar.addPermanentWidget(self._share_label)

    # ---- Menu bar ---------------------------------------------------------

    def _build_menu(self) -> None:
        """Create the menu bar (actions are stubs for Phase 0)."""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")

        open_act = QAction("Open CSV...", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(lambda: self.state.status_text.__class__)  # stub
        file_menu.addAction(open_act)

        scan_act = QAction("Scan Directory...", self)
        scan_act.setShortcut("Ctrl+D")
        file_menu.addAction(scan_act)

        save_act = QAction("Save CSV...", self)
        save_act.setShortcut("Ctrl+S")
        file_menu.addAction(save_act)

        file_menu.addSeparator()

        ns_act = QAction("Network Storage...", self)
        file_menu.addAction(ns_act)

        export_act = QAction("Export Artifacts...", self)
        file_menu.addAction(export_act)

        file_menu.addSeparator()

        exit_act = QAction("Exit", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        # Card menu
        card_menu = menu_bar.addMenu("&Card")

        detect_act = QAction("Detect Card", self)
        card_menu.addAction(detect_act)

        auth_act = QAction("Authenticate...", self)
        card_menu.addAction(auth_act)

        card_menu.addSeparator()

        hw_act = QAction("Hardware Mode", self)
        hw_act.setCheckable(True)
        hw_act.setChecked(True)
        card_menu.addAction(hw_act)

        sim_act = QAction("Simulator Mode", self)
        sim_act.setCheckable(True)
        card_menu.addAction(sim_act)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        about_act = QAction("About", self)
        help_menu.addAction(about_act)

    # ---- Signal connections -----------------------------------------------

    def _connect_signals(self) -> None:
        """Subscribe UI elements to StateManager signals."""
        self.state.status_changed.connect(self._on_status_changed)
        self.state.card_state_changed.connect(self._on_card_state_changed)
        self.state.card_info_changed.connect(self._on_card_info_changed)
        self.state.share_status_changed.connect(self._on_share_status_changed)
        self.state.mode_changed.connect(self._on_mode_changed)

    def _on_status_changed(self, text: str) -> None:
        self._status_label.setText(text)

    def _on_card_state_changed(self, state: CardState) -> None:
        """Update card panel when state changes."""
        if self._card_status_label:
            label_map = {
                CardState.NO_CARD: "Insert a SIM card...",
                CardState.DETECTED: "Card detected",
                CardState.AUTHENTICATED: "Authenticated",
                CardState.ERROR: "Error",
                CardState.BLANK: "Blank card detected",
            }
            self._card_status_label.setText(
                f"Card Status\n{label_map.get(state, str(state))}")

    def _on_card_info_changed(self, info: CardInfo) -> None:
        """Update card panel fields."""
        if self._card_status_label:
            lines = ["Card Status"]
            if info.iccid:
                lines.append(f"ICCID: {info.iccid}")
            if info.imsi:
                lines.append(f"IMSI: {info.imsi}")
            self._card_status_label.setText("\n".join(lines))

    def _on_share_status_changed(self, status) -> None:
        self._share_label.setText(status.display_text)
        if status.connected:
            self._share_label.setStyleSheet(f"color: {QtTheme.get_color('success')};")
        else:
            self._share_label.setStyleSheet("")

    def _on_mode_changed(self, mode: AppMode) -> None:
        prefix = "[SIM] " if mode == AppMode.SIMULATOR else ""
        self.state.status_text = f"{prefix}{'Simulator' if mode == AppMode.SIMULATOR else 'Hardware'} mode active"

    # ---- CardWatcher → StateManager bridge --------------------------------

    def _wire_card_watcher(self) -> None:
        """Connect CardWatcher callbacks → StateManager mutations.

        CardWatcher fires from a background thread.  Qt signals
        auto-marshal to the main thread, so no ``after(0, ...)`` needed.
        """
        def on_detected(iccid, card_data, file_path):
            self.state.card_state = CardState.DETECTED
            self.state.update_card_info(
                iccid=iccid,
                imsi=card_data.get("IMSI", ""),
                acc=card_data.get("ACC", "-"),
                spn=card_data.get("SPN", "-"),
                fplmn=card_data.get("FPLMN", "-"),
                source_file=file_path,
                auth_status=False,
            )
            self.state.status_text = f"Card detected: {iccid}"

        def on_unknown(iccid):
            if iccid:
                self.state.card_state = CardState.DETECTED
                self.state.status_text = f"Card: {iccid} (not in index)"
            else:
                self.state.card_state = CardState.BLANK
                self.state.status_text = "Blank card detected (no ICCID)"
            self.state.update_card_info(
                iccid=iccid or "(blank)",
                auth_status=False,
            )

        def on_removed():
            self.state.card_state = CardState.NO_CARD
            self.state.clear_card_info()
            self.state.status_text = "Card removed"

        def on_error(msg):
            self.state.card_state = CardState.ERROR
            self.state.report_error(msg)

        self._card_watcher.on_card_detected = on_detected
        self._card_watcher.on_card_unknown = on_unknown
        self._card_watcher.on_card_removed = on_removed
        self._card_watcher.on_error = on_error
        self._card_watcher.start()

    def _startup_detect_card(self) -> None:
        """Trigger initial card detection in hardware mode."""
        if self.state.mode != AppMode.HARDWARE:
            return
        if self._card_manager.cli_backend == CLIBackend.NONE:
            return
        try:
            self._card_watcher._check_once()
        except Exception as exc:
            logger.warning("Startup card detection failed: %s", exc)

    def _background_startup(self) -> None:
        """Run slow startup tasks in a worker thread.

        Uses QThread-style approach: run in Python thread, update
        StateManager (signals auto-marshal to UI thread).
        """
        import threading

        def _run():
            # 1. Reconnect saved shares
            try:
                results = self._ns_manager.reconnect_saved()
            except Exception as exc:
                logger.warning("Auto-reconnect failed: %s", exc)
                results = []

            if results:
                ok_labels = [label for label, ok, _ in results if ok]
                if ok_labels:
                    names = ", ".join(ok_labels)
                    self.state.request_toast(
                        f"Network share reconnected: {names}",
                        "success", 5000)
                    self.state.status_text = f"Network share connected: {names}"

            # 2. Refresh share status
            mounts = self._ns_manager.get_active_mount_paths()
            self.state.update_share_status(mounts)

            # 3. Scan ICCID index
            for _label, mount_path in (mounts or []):
                try:
                    self._iccid_index.scan_directory(mount_path)
                except Exception as exc:
                    logger.warning("ICCID scan failed for %s: %s",
                                   mount_path, exc)
            self.state.notify_index_updated()

        threading.Thread(target=_run, daemon=True).start()

    # ---- Window close -----------------------------------------------------

    def closeEvent(self, event) -> None:
        self._card_watcher.stop()
        self._settings.set("window_geometry",
                           f"{self.width()}x{self.height()}")
        self._settings.save()
        self._ns_manager.unmount_all()
        event.accept()

    # ---- Helpers ----------------------------------------------------------

    @staticmethod
    def _get_git_hash() -> str:
        """Return short git commit hash, or empty string."""
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = QApplication(sys.argv)
    QtTheme.apply(app)
    window = QtSimGUIApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
