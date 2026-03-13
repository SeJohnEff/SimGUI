"""Simulator Settings Dialog."""

import tkinter as tk
from tkinter import filedialog, ttk

from theme import ModernTheme
from widgets.tooltip import add_tooltip


class SimulatorSettingsDialog:
    """Modal dialog for configuring simulator parameters."""

    def __init__(self, parent, settings):
        """Create the dialog.

        Args:
            parent: Parent tk widget.
            settings: SimulatorSettings instance to read/modify.
        """
        self._settings = settings
        self._applied = False

        self._dlg = tk.Toplevel(parent)
        self._dlg.title("Simulator Settings")
        self._dlg.transient(parent)
        self._dlg.resizable(False, False)
        self._dlg.grab_set()

        pad = ModernTheme.get_padding('medium')

        frame = ttk.Frame(self._dlg, padding=pad)
        frame.pack(fill=tk.BOTH, expand=True)

        # Card Data CSV
        ttk.Label(frame, text="Card Data CSV:",
                  style='Subheading.TLabel').grid(
            row=0, column=0, sticky=tk.W, pady=(0, 4))
        csv_row = ttk.Frame(frame)
        csv_row.grid(row=0, column=1, columnspan=2, sticky=tk.EW, pady=(0, 4))
        self._csv_var = tk.StringVar(value=settings.card_data_path or "")
        csv_entry = ttk.Entry(csv_row, textvariable=self._csv_var, width=30)
        csv_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        add_tooltip(csv_entry, "Path to a CSV file with card data for the simulator")
        _browse_csv_btn = ttk.Button(csv_row, text="Browse...",
                   command=self._browse_csv)
        _browse_csv_btn.pack(side=tk.LEFT, padx=(4, 0))
        add_tooltip(_browse_csv_btn, "Select a CSV file with SIM card profiles")

        # Operation Delay
        ttk.Label(frame, text="Operation Delay (ms):",
                  style='Subheading.TLabel').grid(
            row=1, column=0, sticky=tk.W, pady=(0, 4))
        self._delay_var = tk.IntVar(value=settings.delay_ms)
        self._delay_label = ttk.Label(frame, text=str(settings.delay_ms))
        self._delay_label.grid(row=1, column=2, padx=(4, 0))
        delay_scale = ttk.Scale(frame, from_=0, to=2000,
                                variable=self._delay_var, orient=tk.HORIZONTAL,
                                length=200,
                                command=lambda v: self._delay_label.configure(
                                    text=str(int(float(v)))))
        delay_scale.grid(row=1, column=1, sticky=tk.EW, pady=(0, 4))
        add_tooltip(delay_scale, "Artificial delay per operation (ms) — simulates real card timing")

        # Error Rate
        ttk.Label(frame, text="Error Rate (%):",
                  style='Subheading.TLabel').grid(
            row=2, column=0, sticky=tk.W, pady=(0, 4))
        self._error_var = tk.IntVar(value=int(settings.error_rate * 100))
        self._error_label = ttk.Label(
            frame, text=str(int(settings.error_rate * 100)))
        self._error_label.grid(row=2, column=2, padx=(4, 0))
        error_scale = ttk.Scale(frame, from_=0, to=50,
                                variable=self._error_var, orient=tk.HORIZONTAL,
                                length=200,
                                command=lambda v: self._error_label.configure(
                                    text=str(int(float(v)))))
        error_scale.grid(row=2, column=1, sticky=tk.EW, pady=(0, 4))
        add_tooltip(error_scale, "Probability of random failures — tests error handling")

        # Number of Cards
        ttk.Label(frame, text="Number of Cards:",
                  style='Subheading.TLabel').grid(
            row=3, column=0, sticky=tk.W, pady=(0, 4))
        self._num_var = tk.IntVar(value=settings.num_cards)
        num_spin = ttk.Spinbox(frame, from_=1, to=50, width=5,
                               textvariable=self._num_var)
        num_spin.grid(row=3, column=1, sticky=tk.W, pady=(0, 4))
        add_tooltip(num_spin, "Size of the virtual card deck")

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW,
                       pady=(pad, 0))
        _reset_btn = ttk.Button(btn_frame, text="Reset Defaults",
                   command=self._reset_defaults)
        _reset_btn.pack(side=tk.LEFT)
        add_tooltip(_reset_btn, "Restore all settings to factory defaults")
        _cancel_btn = ttk.Button(btn_frame, text="Cancel",
                   command=self._dlg.destroy)
        _cancel_btn.pack(side=tk.RIGHT, padx=(4, 0))
        add_tooltip(_cancel_btn, "Discard changes and close")
        _apply_btn = ttk.Button(btn_frame, text="Apply",
                   command=self._apply)
        _apply_btn.pack(side=tk.RIGHT)
        add_tooltip(_apply_btn, "Save settings and close")

        self._dlg.wait_window()

    def _browse_csv(self):
        fp = filedialog.askopenfilename(
            title="Select Card Data File",
            filetypes=[("SIM Data Files", "*.csv *.eml *.txt"),
                       ("CSV Files", "*.csv *.txt"),
                       ("Email Files", "*.eml"),
                       ("All files", "*.*")])
        if fp:
            self._csv_var.set(fp)

    def _reset_defaults(self):
        self._csv_var.set("")
        self._delay_var.set(500)
        self._delay_label.configure(text="500")
        self._error_var.set(0)
        self._error_label.configure(text="0")
        self._num_var.set(10)

    def _apply(self):
        csv_path = self._csv_var.get().strip() or None
        self._settings.card_data_path = csv_path
        self._settings.delay_ms = self._delay_var.get()
        self._settings.error_rate = self._error_var.get() / 100.0
        self._settings.num_cards = self._num_var.get()
        self._applied = True
        self._dlg.destroy()

    @property
    def applied(self) -> bool:
        return self._applied
