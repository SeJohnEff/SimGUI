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
from tkinter import ttk, filedialog, messagebox

from theme import ModernTheme
from managers.card_manager import CardManager, CLIBackend
from managers.csv_manager import CSVManager
from managers.backup_manager import BackupManager
from managers.settings_manager import SettingsManager
from widgets.card_status_panel import CardStatusPanel
from widgets.csv_editor_panel import CSVEditorPanel
from widgets.progress_panel import ProgressPanel
from widgets.read_sim_panel import ReadSIMPanel
from widgets.program_sim_panel import ProgramSIMPanel
from widgets.batch_program_panel import BatchProgramPanel
from dialogs.adm1_dialog import ADM1Dialog
from dialogs.simulator_settings_dialog import SimulatorSettingsDialog

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


class SimGUIApp:
    """Main application class."""

    def __init__(self):
        self.root = tk.Tk(className="simgui")
        self.root.title("SimGUI - SIM Card Programmer")
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

        # Managers
        self._card_manager = CardManager()
        self._backup_manager = BackupManager()
        self._settings = SettingsManager()

        # Mode variable: "hardware" or "simulator"
        self._mode_var = tk.StringVar(value="hardware")

        # Shared state: last card data read from Read SIM tab
        self.last_read_data: dict[str, str] = {}

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()

        # Restore window geometry
        geom = self._settings.get("window_geometry", "")
        if geom:
            self.root.geometry(geom)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Restore simulator mode from settings
        if self._settings.get("simulator_mode", False):
            self._mode_var.set("simulator")
            self._on_mode_change()
        elif self._card_manager.cli_backend == CLIBackend.NONE:
            self._mode_var.set("simulator")
            self._on_mode_change()

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

        # Workflow tabs
        self._read_panel = ReadSIMPanel(
            notebook, self._card_manager,
            last_read_data=self.last_read_data)
        notebook.add(self._read_panel, text="Read SIM")

        self._program_panel = ProgramSIMPanel(
            notebook, self._card_manager,
            last_read_data=self.last_read_data)
        notebook.add(self._program_panel, text="Program SIM")

        self._batch_panel = BatchProgramPanel(
            notebook, self._card_manager, self._settings)
        notebook.add(self._batch_panel, text="Batch Program")

        # Cross-tab CSV sync: browsing in one tab updates the other
        self._program_panel.on_csv_loaded_callback = (
            lambda path: self._batch_panel.load_csv_file(path, _from_sync=True)
        )
        self._batch_panel.on_csv_loaded_callback = (
            lambda path: self._program_panel.load_csv_file(path, _from_sync=True)
        )

        self._csv_panel = CSVEditorPanel(notebook)
        notebook.add(self._csv_panel, text="CSV Editor")

        self._progress_panel = ProgressPanel(notebook)
        notebook.add(self._progress_panel, text="Progress")

        # Status bar
        self._status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self.root, textvariable=self._status_var,
            style='Small.TLabel', relief=tk.SUNKEN, anchor=tk.W,
            padding=(8, 2),
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ---- Menu bar ---------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open CSV...", command=self._on_open_csv,
                              accelerator="Ctrl+O")
        file_menu.add_command(label="Save CSV...", command=self._on_save_csv,
                              accelerator="Ctrl+S")
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
        self.root.bind_all('<Control-s>', lambda e: self._on_save_csv())
        self.root.bind_all('<Control-q>', lambda e: self._on_close())
        self.root.bind_all('<Control-n>', lambda e: self._on_next_virtual_card())
        self.root.bind_all('<Control-p>', lambda e: self._on_previous_virtual_card())

    # ---- Callbacks --------------------------------------------------------

    def _on_open_csv(self):
        fp = filedialog.askopenfilename(
            title="Open SIM Data File",
            filetypes=[("SIM Data Files", "*.csv *.txt"), ("All files", "*.*")])
        if fp:
            mgr = self._csv_panel.get_csv_manager()
            if mgr.load_csv(fp):
                self._csv_panel._refresh_table()
                self._status_var.set(f"Loaded {fp}")
                self._settings.set("last_csv_path", fp)
            else:
                messagebox.showerror("Error", f"Failed to load {fp}")

    def _on_save_csv(self):
        fp = filedialog.asksaveasfilename(
            title="Save CSV", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if fp:
            mgr = self._csv_panel.get_csv_manager()
            if mgr.save_csv(fp):
                self._status_var.set(f"Saved {fp}")
            else:
                messagebox.showerror("Error", f"Failed to save {fp}")

    def _on_detect_card(self):
        ok, msg = self._card_manager.detect_card()
        if ok:
            self._card_panel.set_status("detected", msg)
            info = self._card_manager.card_info
            self._card_panel.set_card_info(
                card_type=self._card_manager.card_type.name,
                imsi=info.get('IMSI'),
                iccid=info.get('ICCID'),
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
            self._card_manager.enable_simulator()
            self._update_sim_menu_state(tk.NORMAL)
            self._status_var.set("[SIM] Simulator mode active")
            # Auto-detect the first virtual card
            self._on_detect_card()
        else:
            self._card_manager.disable_simulator()
            self._update_sim_menu_state(tk.DISABLED)
            self._card_panel.set_simulator_info(None, None)
            self._status_var.set("Hardware mode active")
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

    def _on_about(self):
        messagebox.showinfo(
            "About SimGUI",
            "SimGUI - SIM Card Programming GUI\n\n"
            "A lightweight GUI wrapper for sysmo-usim-tool and pySim.\n"
            "https://github.com/SeJohnEff/SimGUI",
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
        self._settings.set("window_geometry", self.root.geometry())
        self._settings.save()
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
