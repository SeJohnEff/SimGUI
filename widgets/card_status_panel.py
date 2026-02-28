#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Card Status Panel Widget"""

import tkinter as tk
from tkinter import ttk
from theme import ModernTheme


class CardStatusPanel(ttk.LabelFrame):
    """Panel showing card detection and status"""

    def __init__(self, parent, **kwargs):
        padding = ModernTheme.get_padding('medium')
        super().__init__(parent, text="Card Status", padding=padding, **kwargs)
        self.on_detect_callback = None
        self.on_authenticate_callback = None
        self._create_widgets()
        self.set_status("waiting", "Waiting for card...")

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
                       ('ICCID:', 'iccid'), ('Auth:', 'auth')]
        self._info_vars = {}
        for i, (label_text, key) in enumerate(info_labels, start=1):
            ttk.Label(self, text=label_text, style='Subheading.TLabel').grid(
                row=i, column=0, sticky=tk.W, padx=(0, pad_s), pady=2)
            var = tk.StringVar(value='-')
            lbl = ttk.Label(self, textvariable=var)
            lbl.grid(row=i, column=1, sticky=tk.W, pady=2)
            self._info_vars[key] = var

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=len(info_labels) + 1, column=0, columnspan=2,
                       sticky=(tk.W, tk.E), pady=(pad_m, 0))
        ttk.Button(btn_frame, text="Detect Card",
                   command=lambda: self.on_detect_callback and self.on_detect_callback()
                   ).pack(side=tk.LEFT, padx=(0, pad_s))
        ttk.Button(btn_frame, text="Authenticate",
                   command=lambda: self.on_authenticate_callback and self.on_authenticate_callback()
                   ).pack(side=tk.LEFT)

    def set_status(self, state, message=""):
        colors = {
            'waiting': ModernTheme.get_color('warning'),
            'detected': ModernTheme.get_color('accent'),
            'authenticated': ModernTheme.get_color('success'),
            'error': ModernTheme.get_color('error'),
        }
        color = colors.get(state, ModernTheme.get_color('disabled'))
        self.status_indicator.delete('all')
        self.status_indicator.create_oval(2, 2, 10, 10, fill=color, outline=color)
        self.status_label.configure(text=message)

    def set_card_info(self, card_type=None, imsi=None, iccid=None):
        if card_type:
            self._info_vars['card_type'].set(card_type)
        if imsi:
            self._info_vars['imsi'].set(imsi)
        if iccid:
            self._info_vars['iccid'].set(iccid)

    def set_auth_status(self, authenticated):
        self._info_vars['auth'].set('Yes' if authenticated else 'No')
