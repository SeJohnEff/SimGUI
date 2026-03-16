#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Card Status Panel Widget

Shows the current card state.  Card detection is handled automatically
by :class:`CardWatcher` — there is no manual "Detect Card" button.
"""

import tkinter as tk
from tkinter import ttk

from theme import ModernTheme
from widgets.tooltip import add_tooltip


class CardStatusPanel(ttk.LabelFrame):
    """Panel showing card detection and status"""

    def __init__(self, parent, **kwargs):
        padding = ModernTheme.get_padding('medium')
        super().__init__(parent, text="Card Status", padding=padding, **kwargs)
        self.on_detect_callback = None
        self.on_authenticate_callback = None
        self._create_widgets()
        self.set_status("waiting", "Insert a SIM card...")

    def _create_widgets(self):
        pad_s = ModernTheme.get_padding('small')
        pad_m = ModernTheme.get_padding('medium')

        # Status row
        status_frame = ttk.Frame(self)
        status_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, pad_m))
        ttk.Label(status_frame, text="Status:", style='Subheading.TLabel').pack(
            side=tk.LEFT, padx=(0, pad_s))
        self.status_indicator = tk.Canvas(status_frame, width=12, height=12,
                                          bg=ModernTheme.get_color('panel_bg'),
                                          highlightthickness=0)
        self.status_indicator.pack(side=tk.LEFT, padx=(0, pad_s))
        self.status_label = ttk.Label(status_frame, text="")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Card info rows
        info_labels = [('Card Type:', 'card_type'), ('IMSI:', 'imsi'),
                       ('ICCID:', 'iccid'), ('ACC:', 'acc'),
                       ('SPN:', 'spn'), ('FPLMN:', 'fplmn'),
                       ('Auth:', 'auth'), ('ADM1 Left:', 'adm1_attempts'),
                       ('Source:', 'source_file')]
        self._info_vars = {}
        for i, (label_text, key) in enumerate(info_labels, start=1):
            ttk.Label(self, text=label_text, style='Subheading.TLabel').grid(
                row=i, column=0, sticky=tk.W, padx=(0, pad_s), pady=2)
            var = tk.StringVar(value='-')
            entry = ttk.Entry(self, textvariable=var,
                              state="readonly", style="Copyable.TEntry")
            entry.grid(row=i, column=1, sticky=(tk.W, tk.E), pady=2)
            self._info_vars[key] = var

        self.columnconfigure(1, weight=1)

        # Already-programmed indicator (hidden by default)
        self._programmed_label = ttk.Label(
            self, text="", style='Small.TLabel')

        self._num_info_rows = len(info_labels)

        # Buttons — no "Detect Card", detection is automatic
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=self._num_info_rows + 1, column=0, columnspan=2,
                       sticky=(tk.W, tk.E), pady=(pad_m, 0))
        # Rows after buttons: +2 = blocked banner, +3 = programmed,
        # +4 = simulator label
        _auth_btn = ttk.Button(btn_frame, text="Authenticate",
                   command=lambda: self.on_authenticate_callback and self.on_authenticate_callback())
        _auth_btn.pack(side=tk.LEFT)
        add_tooltip(_auth_btn, "Enter ADM1 to authenticate")

    def set_status(self, state, message=""):
        colors = {
            'waiting': ModernTheme.get_color('warning'),
            'detected': ModernTheme.get_color('accent'),
            'authenticated': ModernTheme.get_color('success'),
            'error': ModernTheme.get_color('error'),
            'blocked': '#CC0000',  # deep red for blocked
        }
        color = colors.get(state, ModernTheme.get_color('disabled'))
        self.status_indicator.delete('all')
        self.status_indicator.create_oval(2, 2, 10, 10, fill=color, outline=color)
        self.status_label.configure(text=message)

    def set_card_info(self, card_type=None, imsi=None, iccid=None,
                       acc=None, spn=None, fplmn=None,
                       source_file=None):
        if card_type is not None:
            self._info_vars['card_type'].set(card_type)
        if imsi is not None:
            self._info_vars['imsi'].set(imsi)
        if iccid is not None:
            self._info_vars['iccid'].set(iccid)
        if acc is not None:
            self._info_vars['acc'].set(acc)
        if spn is not None:
            self._info_vars['spn'].set(spn)
        if fplmn is not None:
            self._info_vars['fplmn'].set(fplmn)
        if source_file is not None:
            import os
            self._info_vars['source_file'].set(
                os.path.basename(source_file) if source_file else '-')

    def set_auth_status(self, authenticated):
        self._info_vars['auth'].set('Yes' if authenticated else 'No')

    def set_adm1_attempts(self, remaining):
        """Update the ADM1 remaining attempts display."""
        if remaining is None:
            self._info_vars['adm1_attempts'].set('-')
        elif remaining == 0:
            self._info_vars['adm1_attempts'].set('BLOCKED (0)')
        elif remaining <= 1:
            self._info_vars['adm1_attempts'].set(f'{remaining} (DANGER!)')
        else:
            self._info_vars['adm1_attempts'].set(str(remaining))

    def set_blocked_indicator(self, is_blocked):
        """Show or hide the 'CARD BLOCKED' banner."""
        if not hasattr(self, '_blocked_label'):
            self._blocked_label = tk.Label(
                self, text="\u26d4 CARD BLOCKED \u2014 Cannot be programmed",
                bg='#CC0000', fg='white',
                font=('TkDefaultFont', 10, 'bold'),
                padx=8, pady=4, anchor='w')
        if is_blocked:
            self._blocked_label.grid(
                row=self._num_info_rows + 2, column=0, columnspan=2,
                sticky=(tk.W, tk.E), pady=(8, 0))
        else:
            self._blocked_label.grid_remove()

    def set_programmed_indicator(self, already_programmed):
        """Show or hide the 'already programmed' warning."""
        if already_programmed:
            self._programmed_label.configure(
                text="\u26a0 Already programmed (artifact exists)")
            self._programmed_label.grid(
                row=self._num_info_rows + 3, column=0, columnspan=2,
                sticky=tk.W, pady=(4, 0))
        else:
            self._programmed_label.grid_remove()

    def clear_card_info(self):
        """Reset all info fields to defaults (card removed)."""
        for var in self._info_vars.values():
            var.set('-')
        self._programmed_label.grid_remove()
        if hasattr(self, '_blocked_label'):
            self._blocked_label.grid_remove()

    def set_simulator_info(self, card_index, total_cards):
        """Show or hide the virtual card indicator below the buttons."""
        if not hasattr(self, '_sim_label'):
            self._sim_label = ttk.Label(self, text="", style='Small.TLabel')
        if card_index is not None and total_cards is not None:
            self._sim_label.configure(
                text=f"Virtual card {card_index + 1} of {total_cards}")
            self._sim_label.grid(row=self._num_info_rows + 4, column=0,
                                 columnspan=2, sticky=tk.W, pady=(4, 0))
        else:
            self._sim_label.grid_remove()
