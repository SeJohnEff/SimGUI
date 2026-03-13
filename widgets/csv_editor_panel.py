#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV Editor Panel Widget - Treeview-based CSV table editor"""

import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from managers.csv_manager import SIM_DATA_FILETYPES, CSVManager
from theme import ModernTheme
from utils import get_browse_initial_dir

logger = logging.getLogger(__name__)


class CSVEditorPanel(ttk.Frame):
    """Panel for editing CSV card configurations"""

    def __init__(self, parent, *, ns_manager=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._csv_manager = CSVManager()
        self._ns_manager = ns_manager
        self._last_browse_dir: str | None = None
        self._unsaved_changes = False
        self._create_widgets()

    def _create_widgets(self):
        pad = ModernTheme.get_padding('small')

        # Toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, pady=(0, pad))
        ttk.Button(toolbar, text="Load CSV", command=self._on_load_csv).pack(side=tk.LEFT, padx=(0, pad))
        ttk.Button(toolbar, text="Save CSV", command=self._on_save_csv).pack(side=tk.LEFT, padx=(0, pad))
        ttk.Button(toolbar, text="Add Row", command=self._on_add_row).pack(side=tk.LEFT, padx=(0, pad))
        ttk.Button(toolbar, text="Delete Row", command=self._on_delete_row).pack(side=tk.LEFT, padx=(0, pad))
        ttk.Button(toolbar, text="Validate", command=self._on_validate).pack(side=tk.LEFT)

        self.count_label = ttk.Label(toolbar, text="0 cards", style='Small.TLabel')
        self.count_label.pack(side=tk.RIGHT)

        # Treeview
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, show='headings', selectmode='browse')
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        # Status bar
        self._status = ttk.Label(self, text="", style='Small.TLabel')
        self._status.pack(fill=tk.X, pady=(pad, 0))

    def get_csv_manager(self):
        return self._csv_manager

    def _refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        cols = self._csv_manager.get_columns()
        self.tree['columns'] = cols
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, minwidth=60)
        for i, card in enumerate(self._csv_manager.cards):
            values = [card.get(c, '') for c in cols]
            self.tree.insert('', tk.END, iid=str(i), values=values)
        self.count_label.configure(text=f"{self._csv_manager.get_card_count()} cards")

    def _on_load_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        kwargs = {"title": "Load SIM Data File", "filetypes": SIM_DATA_FILETYPES}
        if init_dir:
            kwargs["initialdir"] = init_dir
        fp = filedialog.askopenfilename(**kwargs)
        if not fp:
            return
        import os
        self._last_browse_dir = os.path.dirname(fp)
        try:
            if self._csv_manager.load_file(fp):
                self._refresh_table()
                self._unsaved_changes = False
            else:
                messagebox.showerror("Load Error",
                                     f"No card data found in {fp}")
        except ValueError as exc:
            messagebox.showerror("Import Error", str(exc))

    def _on_save_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        kwargs = {
            "title": "Save CSV", "defaultextension": ".csv",
            "filetypes": [("CSV files", "*.csv"), ("All files", "*.*")],
        }
        if init_dir:
            kwargs["initialdir"] = init_dir
        fp = filedialog.asksaveasfilename(**kwargs)
        if fp:
            if self._csv_manager.save_csv(fp):
                self._unsaved_changes = False
                messagebox.showinfo("Save", f"CSV saved to {fp}")
            else:
                messagebox.showerror("Save Error", "Failed to save CSV file.")

    def _on_add_row(self):
        self._csv_manager.add_empty_card()
        self._refresh_table()
        self._unsaved_changes = True

    def _on_delete_row(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._csv_manager.delete_card(idx)
        self._refresh_table()
        self._unsaved_changes = True

    def _on_validate(self):
        errors = self._csv_manager.validate_all()
        if errors:
            msg = "\n".join(errors[:20])
            if len(errors) > 20:
                msg += f"\n... and {len(errors) - 20} more"
            messagebox.showwarning("Validation", msg)
        else:
            messagebox.showinfo("Validation", "All cards valid.")

    def _on_cell_edit(self, row, col, value):
        self._csv_manager.update_card(row, col, value)
        self._unsaved_changes = True

    def has_unsaved_changes(self):
        return self._unsaved_changes

    def get_card_count(self):
        return self._csv_manager.get_card_count()

    def get_cards(self):
        return self._csv_manager.cards
