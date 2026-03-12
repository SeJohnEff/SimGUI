#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimGUI - SIM Card Programming GUI

Main entry point. Builds the application window and wires together
widgets, managers, and dialogs.
"""

import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from theme import ModernTheme
from managers.card_manager import CardManager
from managers.csv_manager import CSVManager
from managers.backup_manager import BackupManager
from widgets.card_status_panel import CardStatusPanel
from widgets.csv_editor_panel import CSVEditorPanel
from widgets.progress_panel import ProgressPanel
from dialogs.adm1_dialog import ADM1Dialog

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


class SimGUIApp:
    """Main application class."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SimGUI - SIM Card Programmer")
        self.root.geometry("1024x700")
        self.root.minsize(800, 500)

        ModernTheme.apply_theme(self.root)

        # Managers
        self._card_manager = CardManager()
        self._backup_manager = BackupManager()

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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

        # Right panel: notebook with CSV editor and progress tabs
        notebook = ttk.Notebook(container)
        notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

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

    # ---- Callbacks --------------------------------------------------------

    def _on_open_csv(self):
        fp = filedialog.askopenfilename(
            title="Open CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if fp:
            mgr = self._csv_panel.get_csv_manager()
            if mgr.load_csv(fp):
                self._csv_panel._refresh_table()
                self._status_var.set(f"Loaded {fp}")
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
        self._status_var.set(msg)

    def _on_authenticate(self):
        remaining = self._card_manager.get_remaining_attempts()
        dlg = ADM1Dialog(self.root, remaining_attempts=remaining or 3)
        adm1, force = dlg.get_adm1()
        if adm1 is None:
            return
        ok, msg = self._card_manager.authenticate(adm1, force=force)
        if ok:
            self._card_panel.set_status("authenticated", msg)
            self._card_panel.set_auth_status(True)
        else:
            self._card_panel.set_status("error", msg)
            self._card_panel.set_auth_status(False)
        self._status_var.set(msg)

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
