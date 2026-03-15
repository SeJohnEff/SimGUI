#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimGUI - SIM Card Programming GUI

Main entry point. Builds the application window and wires together
widgets, managers, and dialogs.
"""

import logging
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dialogs.adm1_dialog import ADM1Dialog
from dialogs.artifact_export_dialog import ArtifactExportDialog
from dialogs.load_card_file_dialog import LoadCardFileDialog
from dialogs.network_storage_dialog import NetworkStorageDialog
from dialogs.simulator_settings_dialog import SimulatorSettingsDialog
from managers.auto_artifact_manager import AutoArtifactManager
from managers.backup_manager import BackupManager
from managers.card_manager import CardManager, CLIBackend
from managers.card_watcher import CardWatcher
from managers.csv_manager import SIM_DATA_FILETYPES
from managers.iccid_index import IccidIndex
from managers.network_storage_manager import NetworkStorageManager
from managers.settings_manager import SettingsManager
from managers.standards_manager import StandardsManager
from theme import ModernTheme
from utils import get_browse_initial_dir
from version import __version__
from widgets.batch_program_panel import BatchProgramPanel
from widgets.card_status_panel import CardStatusPanel
from widgets.csv_editor_panel import CSVEditorPanel
from widgets.program_sim_panel import ProgramSIMPanel
from widgets.progress_panel import ProgressPanel
from widgets.read_sim_panel import ReadSIMPanel
from widgets.info_dialog import show_error as show_error_dialog
from widgets.info_dialog import show_info as show_info_dialog
from widgets.toast import show_toast
from widgets.tooltip import add_tooltip, hide_all_tooltips

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


class SimGUIApp:
    """Main application class."""

    def __init__(self):
        self.root = tk.Tk(className="simgui")
        self._git_hash = self._get_git_hash()
        title = f"SimGUI {__version__}"
        if self._git_hash:
            title += f" ({self._git_hash})"
        title += " — SIM Card Programmer"
        self.root.title(title)
        self.root.geometry("1024x700")
        self.root.minsize(800, 500)

        # Load multiple icon sizes so the WM picks the best match for
        # taskbar, title-bar, and alt-tab.  The first image is the
        # "default" size; extras are alternates.
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        icon_sizes = ["simgui-256.png", "simgui-128.png", "simgui-64.png",
                      "simgui-48.png", "simgui-32.png", "simgui-16.png"]
        icons = []
        for name in icon_sizes:
            p = os.path.join(assets_dir, name)
            if os.path.exists(p):
                icons.append(tk.PhotoImage(file=p))
        if icons:
            self.root.iconphoto(True, *icons)
            self._icons = icons          # prevent garbage collection

        ModernTheme.apply_theme(self.root)

        # Ensure Ctrl+V paste works everywhere (Linux workaround)
        def _global_paste(event):
            try:
                widget = event.widget
                if not isinstance(widget, (tk.Entry, ttk.Entry, ttk.Combobox)):
                    return
                text = widget.clipboard_get()
                text = ''.join(ch for ch in text if ch.isprintable())
                try:
                    if widget.select_present():
                        widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                except (tk.TclError, AttributeError):
                    pass
                widget.insert(tk.INSERT, text)
                return 'break'
            except tk.TclError:
                pass

        self.root.bind_all('<Control-v>', _global_paste)
        self.root.bind_all('<Control-V>', _global_paste)

        # Managers
        self._card_manager = CardManager()
        self._backup_manager = BackupManager()
        self._settings = SettingsManager()
        self._ns_manager = NetworkStorageManager(self._settings)
        self._iccid_index = IccidIndex()
        self._auto_artifact = AutoArtifactManager(self._ns_manager)
        self._standards_mgr = StandardsManager()
        self._card_watcher = CardWatcher(
            self._card_manager, self._iccid_index, poll_interval=1.5)

        # Mode variable: "hardware" or "simulator"
        self._mode_var = tk.StringVar(value="hardware")

        # Shared state: last card data read from Read SIM tab
        self.last_read_data: dict[str, str] = {}

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()
        self._wire_card_watcher()

        # Restore window geometry
        geom = self._settings.get("window_geometry", "")
        if geom:
            self.root.geometry(geom)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Decide initial mode.
        # If a real CLI backend (pySim) is available, always start in
        # hardware mode regardless of what was saved — the user shouldn't
        # have to remember to switch modes every launch.
        if self._card_manager.cli_backend == CLIBackend.NONE:
            # No pySim / no CLI tool — simulator is the only option
            self._mode_var.set("simulator")
            self._on_mode_change()
        else:
            # Hardware Mode — a real backend is available.
            self._mode_var.set("hardware")
            self._settings.set("simulator_mode", False)
            # Trigger an initial card detection after 100 ms so that a card
            # already inserted before the app started is detected immediately
            # rather than waiting for the first CardWatcher poll cycle.
            self.root.after(100, self._startup_detect_card)

        # Warn once if passwordless sudo mount is not configured
        self._check_sudo_mount_permissions()

        # Auto-reconnect network shares from previous session
        self._auto_reconnect_shares()

        # Scan index from connected shares
        self._rescan_iccid_index()

        # Show persistent share indicator
        self._refresh_share_indicator()

    @staticmethod
    def _get_git_hash() -> str:
        """Return short git commit hash, or empty string if unavailable.

        Tries git first (for development), then falls back to the BUILD
        file that is baked at release time (for installed copies).
        """
        app_dir = os.path.dirname(os.path.abspath(__file__))
        import subprocess as _sp
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
        # Fallback: BUILD file written at release time
        build_file = os.path.join(app_dir, "BUILD")
        try:
            with open(build_file, "r") as fh:
                return fh.read().strip()
        except OSError:
            pass
        return ""

    # ---- Layout -----------------------------------------------------------

    def _build_layout(self):
        """Create the main two-pane layout with status bar."""
        container = ttk.Frame(self.root)
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        # Left panel: card status
        self._card_panel = CardStatusPanel(container)
        self._card_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        self._card_panel.on_detect_callback = self._on_detect_card
        self._card_panel.on_authenticate_callback = self._on_authenticate

        # Right panel: notebook with workflow tabs
        notebook = ttk.Notebook(container)
        notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._notebook = notebook

        # Mount indicator — floats in the empty space right of the tab bar.
        # Uses place() so it overlays the notebook's top-right corner
        # without affecting the pack layout.
        self._mount_indicator = tk.Canvas(
            notebook, width=20, height=20,
            highlightthickness=0, borderwidth=0,
        )
        # place() in top-right corner; repositioned on resize
        self._mount_indicator.place(relx=1.0, x=-28, y=3, anchor="ne")
        notebook.bind("<Configure>", self._reposition_mount_indicator)
        self._draw_mount_icon(connected=False)
        self._mount_tooltip_text = ""
        add_tooltip(self._mount_indicator, "No network share connected")

        # Workflow tabs
        self._read_panel = ReadSIMPanel(
            notebook, self._card_manager,
            last_read_data=self.last_read_data,
            ns_manager=self._ns_manager)
        notebook.add(self._read_panel, text="Read SIM")

        self._program_panel = ProgramSIMPanel(
            notebook, self._card_manager,
            last_read_data=self.last_read_data,
            ns_manager=self._ns_manager)
        notebook.add(self._program_panel, text="Program SIM")

        self._batch_panel = BatchProgramPanel(
            notebook, self._card_manager, self._settings,
            ns_manager=self._ns_manager)
        self._batch_panel.set_standards_manager(self._standards_mgr)
        notebook.add(self._batch_panel, text="Batch Program")

        # Cross-tab CSV sync: browsing in one tab updates the other
        self._program_panel.on_csv_loaded_callback = (
            lambda path: self._batch_panel.load_csv_file(path, _from_sync=True)
        )
        self._batch_panel.on_csv_loaded_callback = (
            lambda path: self._program_panel.load_csv_file(path, _from_sync=True)
        )

        # Auto-artifact callback: save artifact after programming
        self._program_panel.on_card_programmed_callback = (
            self._on_card_programmed
        )

        self._csv_panel = CSVEditorPanel(notebook, ns_manager=self._ns_manager)
        notebook.add(self._csv_panel, text="CSV Editor")

        self._progress_panel = ProgressPanel(notebook)
        notebook.add(self._progress_panel, text="Progress")

        # Status bar (left = status text, right = share indicator)
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self._status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(
            status_frame, textvariable=self._status_var,
            style='Small.TLabel', relief=tk.SUNKEN, anchor=tk.W,
            padding=(8, 2),
        )
        status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Persistent network-share indicator (right side of status bar)
        self._share_indicator_var = tk.StringVar(value="")
        self._share_indicator = ttk.Label(
            status_frame, textvariable=self._share_indicator_var,
            style='Small.TLabel', relief=tk.SUNKEN, anchor=tk.E,
            padding=(8, 2),
        )
        self._share_indicator.pack(side=tk.RIGHT)

    # ---- Menu bar ---------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open CSV...", command=self._on_open_csv,
                              accelerator="Ctrl+O")
        file_menu.add_command(label="Scan Directory...",
                              command=self._on_scan_directory,
                              accelerator="Ctrl+D")
        file_menu.add_command(label="Save CSV...", command=self._on_save_csv,
                              accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Network Storage...",
                              command=self._on_network_storage)
        file_menu.add_command(label="Export Artifacts...",
                              command=self._on_export_artifacts)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close,
                              accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=file_menu)

        card_menu = tk.Menu(menubar, tearoff=0)
        card_menu.add_command(label="Detect Card", command=self._on_detect_card)
        card_menu.add_command(label="Authenticate...", command=self._on_authenticate)
        card_menu.add_separator()
        card_menu.add_radiobutton(label="Hardware Mode",
                                  variable=self._mode_var, value="hardware",
                                  command=self._on_mode_change)
        card_menu.add_radiobutton(label="Simulator Mode",
                                  variable=self._mode_var, value="simulator",
                                  command=self._on_mode_change)
        card_menu.add_separator()
        self._card_menu = card_menu
        self._sim_menu_start = card_menu.index(tk.END) + 1
        card_menu.add_command(label="Next Virtual Card",
                              command=self._on_next_virtual_card,
                              accelerator="Ctrl+N")
        card_menu.add_command(label="Previous Virtual Card",
                              command=self._on_previous_virtual_card,
                              accelerator="Ctrl+P")
        card_menu.add_command(label="Simulator Settings...",
                              command=self._on_simulator_settings)
        card_menu.add_command(label="Reset Simulator",
                              command=self._on_reset_simulator)
        menubar.add_cascade(label="Card", menu=card_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._on_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    # ---- Keyboard shortcuts -----------------------------------------------

    def _bind_shortcuts(self):
        self.root.bind_all('<Control-o>', lambda e: self._on_open_csv())
        self.root.bind_all('<Control-d>', lambda e: self._on_scan_directory())
        self.root.bind_all('<Control-s>', lambda e: self._on_save_csv())
        self.root.bind_all('<Control-q>', lambda e: self._on_close())
        self.root.bind_all('<Control-n>', lambda e: self._on_next_virtual_card())
        self.root.bind_all('<Control-p>', lambda e: self._on_previous_virtual_card())

    # ---- CardWatcher wiring -----------------------------------------------

    def _wire_card_watcher(self):
        """Connect CardWatcher callbacks to the UI.

        All callbacks arrive from the watcher thread, so each uses
        ``root.after(0, ...)`` to dispatch onto the Tk main thread.
        """
        def on_detected(iccid, card_data, file_path):
            self.root.after(0, self._on_auto_card_detected,
                           iccid, card_data, file_path)

        def on_unknown(iccid):
            self.root.after(0, self._on_auto_card_unknown, iccid)

        def on_removed():
            self.root.after(0, self._on_auto_card_removed)

        def on_error(msg):
            self.root.after(0, self._on_auto_card_error, msg)

        self._card_watcher.on_card_detected = on_detected
        self._card_watcher.on_card_unknown = on_unknown
        self._card_watcher.on_card_removed = on_removed
        self._card_watcher.on_error = on_error
        self._card_watcher.start()

    def _startup_detect_card(self):
        """Trigger an initial card detection at startup for Hardware Mode.

        Called once via ``root.after(100, ...)`` so the UI is fully
        initialised before the detection runs.  Delegates to the
        CardWatcher so callbacks fire and UI updates identically to a
        live insertion.

        Also checks whether a USB smart-card reader is reachable.  When
        pySim returns a reader error the user gets a warning dialog.
        """
        if self._mode_var.get() != "hardware":
            return
        if self._card_manager.cli_backend == CLIBackend.NONE:
            return
        # Run the watcher check — it calls detect_card() internally
        # and fires the correct callbacks (detected / unknown / removed).
        try:
            self._card_watcher._check_once()
        except Exception as exc:
            logger.warning("Startup card detection failed: %s", exc)
        # If the watcher didn't find a card, check if it's a reader issue
        if not self._card_watcher._card_present:
            ok, msg = self._card_manager.detect_card()
            if not ok and self._is_reader_error(msg):
                self._show_no_reader_warning(msg)

    # ---- Reader & index helpers -------------------------------------------

    _READER_ERROR_KEYWORDS = (
        "no reader", "no pc/sc", "pcsc", "reader not found",
        "scard", "could not connect", "no smart card",
        "service not available", "establish_context",
    )

    def _is_reader_error(self, msg: str) -> bool:
        """Return True if *msg* looks like a missing-reader error."""
        lower = msg.lower()
        return any(kw in lower for kw in self._READER_ERROR_KEYWORDS)

    def _show_no_reader_warning(self, detail: str = ""):
        """Show a popup warning about missing USB smart-card reader."""
        body = (
            "No USB smart-card reader detected.\n\n"
            "Please check:\n"
            "  \u2022 Reader is plugged in (and passed through to the VM)\n"
            "  \u2022 PC/SC service is running: sudo systemctl start pcscd\n"
            "  \u2022 Reader appears in: pcsc_scan\n"
        )
        if detail:
            body += f"\nDetail: {detail}"
        messagebox.showwarning("No Card Reader", body)
        self._card_panel.set_status("error", "No card reader detected")
        self._status_var.set("No card reader — check USB connection")

    def _check_sudo_mount_permissions(self):
        """Warn the user at startup if passwordless sudo mount is not set up.

        Only shows the warning when saved profiles exist (i.e. the user
        actually uses network shares).  Runs the check in a thread so
        the UI isn't blocked.
        """
        profiles = self._ns_manager.load_profiles()
        if not profiles:
            return  # no shares configured, nothing to warn about

        import threading

        def _check():
            ok = self._ns_manager.check_sudo_mount()
            if not ok:
                self.root.after(0, self._show_sudo_warning)

        threading.Thread(target=_check, daemon=True).start()

    def _show_sudo_warning(self):
        """Display a one-time warning about missing sudo mount permissions."""
        show_toast(
            self.root,
            "Network mounts may fail — run 'sudo simgui-setup-mount' "
            "in a terminal to fix",
            level="warning",
            duration=10_000,
        )

    def _auto_reconnect_shares(self):
        """Reconnect network shares that were connected last session."""
        results = self._ns_manager.reconnect_saved()
        if not results:
            return

        ok_labels = [label for label, ok, _ in results if ok]
        fail_items = [(label, msg) for label, ok, msg in results if not ok]

        if ok_labels:
            names = ", ".join(ok_labels)
            show_toast(
                self.root,
                f"Network share reconnected: {names}",
                level="success",
                duration=5000,
            )
            self._status_var.set(f"Network share connected: {names}")

        for label, msg in fail_items:
            show_toast(
                self.root,
                f"Could not reconnect \"{label}\": {msg}",
                level="warning",
                duration=8000,
            )
            logger.warning("Auto-reconnect failed: %s — %s", label, msg)

    # ---- Mount indicator (tab-bar icon) ---------------------------------

    def _draw_mount_icon(self, connected: bool = False):
        """Draw a small HDD/network-storage icon on the mount indicator canvas.

        Green fill when a share is connected, grey when disconnected.
        """
        c = self._mount_indicator
        c.delete("all")
        fill = "#2e7d32" if connected else "#999999"
        outline = "#1b5e20" if connected else "#666666"
        # Stylised HDD: rounded rectangle body
        c.create_rectangle(2, 5, 18, 17, fill=fill, outline=outline, width=1)
        # Activity LED dot
        led = "#81c784" if connected else "#cccccc"
        c.create_oval(13, 12, 16, 15, fill=led, outline="")
        # Platter lines
        line_col = "#ffffff" if connected else "#b0b0b0"
        c.create_line(5, 9, 11, 9, fill=line_col)
        c.create_line(5, 12, 11, 12, fill=line_col)

    def _reposition_mount_indicator(self, _event=None):
        """Keep the mount indicator pinned to the top-right of the notebook."""
        self._mount_indicator.place(relx=1.0, x=-28, y=3, anchor="ne")

    def _refresh_share_indicator(self):
        """Update both the status-bar text and the tab-bar icon."""
        mounts = self._ns_manager.get_active_mount_paths()
        if mounts:
            labels = [label for label, _path in mounts]
            paths = [f"{label}: {path}" for label, path in mounts]
            self._share_indicator_var.set(
                f"\u25cf NAS: {', '.join(labels)}")
            self._share_indicator.configure(foreground="#2e7d32")
            # Tab-bar icon: green + tooltip with mount paths
            self._draw_mount_icon(connected=True)
            tooltip_text = "\n".join(paths)
            self._update_mount_tooltip(tooltip_text)
        else:
            self._share_indicator_var.set("")
            self._share_indicator.configure(foreground="")
            self._draw_mount_icon(connected=False)
            self._update_mount_tooltip("No network share connected")

    def _update_mount_tooltip(self, text: str):
        """Replace the tooltip on the mount indicator canvas."""
        if hasattr(self, "_mount_indicator_tooltip"):
            self._mount_indicator_tooltip.destroy()
        self._mount_indicator_tooltip = add_tooltip(
            self._mount_indicator, text)

    def _rescan_iccid_index(self):
        """Scan all connected shares for ICCID data files and standards."""
        mount_dirs = []
        for _label, mount_path in self._ns_manager.get_active_mount_paths():
            mount_dirs.append(mount_path)
            try:
                result = self._iccid_index.scan_directory(mount_path)
                if result.total_cards > 0:
                    logger.info("ICCID index: scanned %s — %d cards in %d files",
                                mount_path, result.total_cards,
                                result.files_scanned)
            except Exception as exc:
                logger.warning("ICCID index scan failed for %s: %s",
                              mount_path, exc)
        # Reload standards from all mounted shares
        loaded = self._standards_mgr.reload_from_directories(mount_dirs)
        if loaded:
            logger.info("Standards: loaded from %d share(s)", loaded)
        self._batch_panel.refresh_standards()

    def _check_already_programmed(self, iccid: str) -> bool:
        """Check artifact dir for prior programming and show a popup if found.

        Returns True if the card was previously programmed.
        """
        if not iccid:
            return False
        prev = self._auto_artifact.get_previous_programming_info(iccid)
        if prev is None:
            return False
        prev_imsi = prev.get("IMSI", "unknown")
        prev_time = prev.get("programmed_at", "unknown")
        prev_file = os.path.basename(prev.get("_artifact_path", ""))
        show_info_dialog(
            self.root,
            "Already Programmed",
            f"This card has been programmed before.\n\n"
            f"ICCID: {iccid}\n"
            f"Previous IMSI: {prev_imsi}\n"
            f"Programmed at: {prev_time}\n"
            f"Artifact: {prev_file}\n\n"
            f"You can continue \u2014 this is just an informational warning.",
        )
        return True

    def _on_auto_card_detected(self, iccid, card_data, file_path):
        """Card inserted and matched in index (runs on main thread)."""
        hw = self._card_manager.card_info  # live data read from card
        self._card_panel.set_status("detected", f"Card detected: {iccid}")
        self._card_panel.set_card_info(
            imsi=hw.get("IMSI") or card_data.get("IMSI"),
            iccid=iccid,
            acc=hw.get("ACC", card_data.get("ACC", "-")),
            spn=hw.get("SPN", card_data.get("SPN", "-")),
            fplmn=hw.get("FPLMN", card_data.get("FPLMN", "-")),
            source_file=file_path,
        )
        self._card_panel.set_auth_status(False)
        # Check if already programmed — show popup warning with previous IMSI
        already = self._check_already_programmed(iccid)
        self._card_panel.set_programmed_indicator(already)
        # Auto-populate Program SIM tab
        self._program_panel.on_card_detected(iccid, card_data, file_path)
        # Sync the Read SIM tab (public fields)
        self._read_panel.refresh()
        self._status_var.set(f"Card detected: {iccid}")

    def _on_auto_card_unknown(self, iccid):
        """Card inserted but not in index (runs on main thread).

        Opens a unified file-picker dialog with network share access
        so the user can locate the card's data file in one step.
        If *iccid* is empty the card is completely blank.
        """
        if iccid:
            status_msg = f"Card: {iccid} (not in index)"
        else:
            status_msg = "Blank card detected (no ICCID)"
        self._card_panel.set_status("detected", status_msg)
        hw = self._card_manager.card_info  # live data read from card
        self._card_panel.set_card_info(
            imsi=hw.get("IMSI", "-"),
            iccid=iccid or "(blank)",
            acc=hw.get("ACC", "-"),
            spn=hw.get("SPN", "-"),
            fplmn=hw.get("FPLMN", "-"),
            source_file=None,
        )
        self._card_panel.set_auth_status(False)

        # Check if already programmed even though not in the ICCID index
        already = self._check_already_programmed(iccid)
        self._card_panel.set_programmed_indicator(already)

        self._program_panel.on_card_detected(iccid)
        # Sync the Read SIM tab — card_info has ICCID/IMSI from detect
        self._read_panel.refresh()
        self._status_var.set(status_msg)

        if not iccid:
            # Blank card — nothing to look up, skip the file dialog
            return

        # Open the unified file-picker with network share access
        hide_all_tooltips()
        self._load_file_for_unknown_card(iccid)

    def _load_file_for_unknown_card(self, iccid: str):
        """Open the unified file picker (local + network shares).

        The dialog may return either:
        * A *directory* path (user clicked "Use This Share") — we scan it.
        * A *file* path (user clicked "Browse Local\u2026") — we scan its
          parent directory.
        """
        init_dir = get_browse_initial_dir(self._ns_manager)
        dlg = LoadCardFileDialog(
            self.root, iccid, self._ns_manager,
            initial_dir=init_dir,
        )
        self.root.wait_window(dlg)

        # User may have connected a new share inside the dialog
        self._refresh_share_indicator()

        fp = dlg.selected_path
        if not fp:
            return

        scan_dir = fp if os.path.isdir(fp) else os.path.dirname(fp)

        try:
            result = self._iccid_index.scan_directory(scan_dir)
            logger.info("Re-scanned %s: %d cards in %d files",
                        scan_dir, result.total_cards,
                        result.files_scanned)
        except Exception as exc:
            show_error_dialog(self.root, "Scan Error", str(exc))
            return
        # Re-check this ICCID in the refreshed index
        entry = self._iccid_index.lookup(iccid)
        if entry:
            card_data = self._iccid_index.load_card(iccid)
            if card_data:
                self._on_auto_card_detected(iccid, card_data, entry.file_path)
                self._status_var.set(
                    f"Card found in {os.path.basename(entry.file_path)}")
                return
        show_info_dialog(
            self.root,
            "Not Found",
            f"ICCID {iccid} was not found in the scanned directory.\n\n"
            f"Scanned: {scan_dir}\n"
            "Make sure the directory contains a data file for this card.")

    def _on_auto_card_removed(self):
        """Card removed (runs on main thread)."""
        self._card_panel.set_status("waiting", "Insert a SIM card...")
        self._card_panel.clear_card_info()
        self._program_panel.on_card_removed()
        self._read_panel.refresh()  # Clear Read SIM fields
        self._status_var.set("Card removed")

    def _on_auto_card_error(self, msg):
        """CardWatcher error (runs on main thread)."""
        logger.warning("CardWatcher error: %s", msg)
        if self._is_reader_error(msg):
            self._card_panel.set_status("error", "No card reader detected")
            self._status_var.set("No card reader — check USB connection")

    def _on_card_programmed(self, card_data):
        """Called after successful card programming — save auto-artifact."""
        try:
            paths = self._auto_artifact.save_card_artifact(card_data)
            if paths:
                import os
                names = [os.path.basename(p) for p in paths]
                self._status_var.set(f"Artifact saved: {', '.join(names)}")
                logger.info("Auto-artifact saved: %s", paths)
        except Exception as exc:
            logger.warning("Auto-artifact save failed: %s", exc)

    # ---- Callbacks --------------------------------------------------------

    def _on_open_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager)
        kwargs = {"title": "Open SIM Data File", "filetypes": SIM_DATA_FILETYPES}
        if init_dir:
            kwargs["initialdir"] = init_dir
        fp = filedialog.askopenfilename(**kwargs)
        if not fp:
            return
        mgr = self._csv_panel.get_csv_manager()
        try:
            if mgr.load_file(fp):
                self._csv_panel._refresh_table()
                self._status_var.set(f"Loaded {fp}")
                self._settings.set("last_csv_path", fp)
            else:
                show_error_dialog(self.root, "Error",
                                  f"No card data found in {fp}")
        except ValueError as exc:
            show_error_dialog(self.root, "Import Error", str(exc))

    def _on_scan_directory(self):
        """Let the user pick a directory and scan it for SIM data files.

        Defaults to the network share mount point if one is connected.
        Recursively scans all subdirectories for .csv/.eml/.txt files.
        """
        init_dir = get_browse_initial_dir(self._ns_manager)
        chosen = filedialog.askdirectory(
            title="Select directory with SIM data files",
            initialdir=init_dir or None,
            mustexist=True,
        )
        if not chosen:
            return

        self._status_var.set(f"Scanning {chosen}...")
        self.root.update_idletasks()

        try:
            result = self._iccid_index.scan_directory(chosen)
        except Exception as exc:
            show_error_dialog(self.root, "Scan Error", str(exc))
            return

        if result.total_cards > 0:
            show_toast(
                self.root,
                f"Found {result.total_cards} cards in "
                f"{result.files_scanned} files",
                level="success",
                duration=5000,
            )
            self._status_var.set(
                f"Scanned {chosen}: {result.total_cards} cards in "
                f"{result.files_scanned} files")
        else:
            show_toast(
                self.root,
                f"No SIM data found in {os.path.basename(chosen)}",
                level="warning",
                duration=5000,
            )
            self._status_var.set(
                f"No SIM data found in {chosen}")

        if result.errors:
            logger.warning("Scan errors in %s: %s", chosen, result.errors)

    def _on_save_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager)
        kwargs = {
            "title": "Save CSV", "defaultextension": ".csv",
            "filetypes": [("CSV files", "*.csv"), ("All files", "*.*")],
        }
        if init_dir:
            kwargs["initialdir"] = init_dir
        fp = filedialog.asksaveasfilename(**kwargs)
        if fp:
            mgr = self._csv_panel.get_csv_manager()
            if mgr.save_csv(fp):
                self._status_var.set(f"Saved {fp}")
            else:
                show_error_dialog(self.root, "Error",
                                  f"Failed to save {fp}")

    def _on_detect_card(self):
        ok, msg = self._card_manager.detect_card()
        if ok:
            self._card_panel.set_status("detected", msg)
            info = self._card_manager.card_info
            self._card_panel.set_card_info(
                card_type=self._card_manager.card_type.name,
                imsi=info.get('IMSI'),
                iccid=info.get('ICCID'),
                acc=info.get('ACC', '-'),
                spn=info.get('SPN', '-'),
                fplmn=info.get('FPLMN', '-'),
            )
        else:
            self._card_panel.set_status("error", msg)
        prefix = "[SIM] " if self._card_manager.is_simulator_active else ""
        self._status_var.set(f"{prefix}{msg}")
        # Update virtual card indicator
        sim_info = self._card_manager.get_simulator_info()
        if sim_info:
            self._card_panel.set_simulator_info(
                sim_info["current_index"], sim_info["total_cards"])
        else:
            self._card_panel.set_simulator_info(None, None)
        # Sync the Read SIM tab
        self._read_panel.refresh()

    def _on_authenticate(self):
        remaining = self._card_manager.get_remaining_attempts()
        dlg = ADM1Dialog(self.root, remaining_attempts=remaining or 3)
        adm1, force = dlg.get_adm1()
        if adm1 is None:
            return
        expected_iccid = self._get_expected_iccid()
        ok, msg = self._card_manager.authenticate(
            adm1, force=force, expected_iccid=expected_iccid)
        if ok:
            self._card_panel.set_status("authenticated", msg)
            self._card_panel.set_auth_status(True)
        else:
            self._card_panel.set_status("error", msg)
            self._card_panel.set_auth_status(False)
            if "ICCID mismatch" in msg:
                messagebox.showwarning("ICCID Mismatch", msg)
        prefix = "[SIM] " if self._card_manager.is_simulator_active else ""
        self._status_var.set(f"{prefix}{msg}")

    def _get_expected_iccid(self):
        """Get ICCID from the currently selected CSV row, if any."""
        try:
            mgr = self._csv_panel.get_csv_manager()
            tree = self._csv_panel._tree
            selection = tree.selection()
            if not selection:
                return None
            item = selection[0]
            idx = tree.index(item)
            card = mgr.get_card(idx)
            return card.get("ICCID") if card else None
        except Exception:
            return None

    def _on_mode_change(self):
        """Handle switching between hardware and simulator mode."""
        mode = self._mode_var.get()
        if mode == "simulator":
            self._card_watcher.pause()  # Don't poll during simulation
            self._card_manager.enable_simulator()
            self._update_sim_menu_state(tk.NORMAL)
            self._status_var.set("[SIM] Simulator mode active")
            # Auto-detect the first virtual card
            self._on_detect_card()
        else:
            self._card_manager.disable_simulator()
            self._update_sim_menu_state(tk.DISABLED)
            self._card_panel.set_simulator_info(None, None)
            # Clear all simulator state from UI
            self._card_panel.set_status("waiting", "Insert a SIM card...")
            self._card_panel.clear_card_info()
            self._program_panel.on_card_removed()
            self._read_panel.refresh()
            self._card_watcher.resume()  # Resume hardware polling
            self._status_var.set("Hardware mode active")
            # Check for reader and attempt initial card detection
            self.root.after(100, self._startup_detect_card)
        self._settings.set("simulator_mode", mode == "simulator")

    def _update_sim_menu_state(self, state):
        """Enable or disable simulator-only menu items."""
        for i in range(self._sim_menu_start,
                       self._sim_menu_start + 4):
            try:
                self._card_menu.entryconfigure(i, state=state)
            except tk.TclError:
                pass

    def _on_next_virtual_card(self):
        if not self._card_manager.is_simulator_active:
            return
        result = self._card_manager.next_virtual_card()
        if result:
            idx, total = result
            self._card_panel.set_simulator_info(idx, total)
            self._on_detect_card()

    def _on_previous_virtual_card(self):
        if not self._card_manager.is_simulator_active:
            return
        result = self._card_manager.previous_virtual_card()
        if result:
            idx, total = result
            self._card_panel.set_simulator_info(idx, total)
            self._on_detect_card()

    def _on_simulator_settings(self):
        if not self._card_manager.is_simulator_active:
            return
        sim = self._card_manager._simulator
        old_count = sim.settings.num_cards
        dlg = SimulatorSettingsDialog(self.root, sim.settings)
        if dlg.applied and sim.settings.num_cards != old_count:
            sim.reset()
            self._on_detect_card()

    def _on_reset_simulator(self):
        if not self._card_manager.is_simulator_active:
            return
        self._card_manager._simulator.reset()
        self._on_detect_card()
        self._status_var.set("[SIM] Simulator reset")

    def _on_network_storage(self):
        """Open the network storage connection dialog."""
        dlg = NetworkStorageDialog(self.root, self._ns_manager)
        self.root.wait_window(dlg)
        # Rescan after dialog closes — shares may have been mounted/unmounted
        self._rescan_iccid_index()
        self._refresh_share_indicator()

    def _on_export_artifacts(self):
        """Open the artifact export dialog with data from the last batch run."""
        # Collect records: prefer batch panel results, fall back to read data
        records = []
        try:
            records = self._batch_panel.get_programmed_records()
        except (AttributeError, Exception):
            pass
        if not records and self.last_read_data:
            records = [self.last_read_data]
        if not records:
            show_info_dialog(
                self.root,
                "No Data",
                "No programming results to export.\n\n"
                "Run a batch program or read a card first.")
            return
        # Get default fields from first connected profile, if any
        default_fields = None
        profiles = self._ns_manager.load_profiles()
        if profiles:
            default_fields = profiles[0].export_fields
        ArtifactExportDialog(self.root, records, self._ns_manager,
                             default_fields)

    def _on_about(self):
        version_line = f"Version {__version__}"
        if self._git_hash:
            version_line += f"  (commit {self._git_hash})"

        show_info_dialog(
            self.root,
            "About SimGUI",
            f"SimGUI — SIM Card Programming GUI\n"
            f"{version_line}\n\n"
            f"A lightweight GUI wrapper for pySim.\n\n"
            f"https://github.com/SeJohnEff/SimGUI",
        )

    def _on_close(self):
        if self._csv_panel.has_unsaved_changes:
            answer = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?")
            if answer is None:
                return  # Cancel
            if answer:
                self._on_save_csv()
        self._card_watcher.stop()
        self._settings.set("window_geometry", self.root.geometry())
        self._settings.save()
        self._ns_manager.unmount_all()
        self.root.destroy()

    # ---- Run --------------------------------------------------------------

    def run(self):
        """Start the main event loop."""
        self.root.mainloop()


def main():
    app = SimGUIApp()
    app.run()


if __name__ == '__main__':
    main()
