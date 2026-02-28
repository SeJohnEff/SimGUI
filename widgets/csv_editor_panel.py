#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV Editor Panel Widget - Treeview-based CSV table editor"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from theme import ModernTheme
from managers.csv_manager import CSVManager


class CSVEditorPanel(ttk.Frame):
    """Panel for editing CSV card configurations"""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._csv_manager = CSVManager()
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
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind('<Double-1>', self._on_cell_edit)

        self._refresh_table()

    def get_csv_manager(self) -> CSVManager:
        return self._csv_manager

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        cols = self._csv_manager.columns
        self.tree['columns'] = cols
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, minwidth=60)
        for i, card in enumerate(self._csv_manager.cards):
            values = [card.get(c, '') for c in cols]
            self.tree.insert('', tk.END, iid=str(i), values=values)
        self.count_label.configure(text=f"{self._csv_manager.get_card_count()} cards")

    def _on_load_csv(self):
        fp = filedialog.askopenfilename(
            title="Load CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if fp and self._csv_manager.load_csv(fp):
            self._refresh_table()

    def _on_save_csv(self):
        fp = filedialog.asksaveasfilename(
            title="Save CSV", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if fp:
            self._csv_manager.save_csv(fp)

    def _on_add_row(self):
        self._csv_manager.add_card()
        self._refresh_table()

    def _on_delete_row(self):
        sel = self.tree.selection()
        if sel:
            idx = int(sel[0])
            self._csv_manager.remove_card(idx)
            self._refresh_table()

    def _on_validate(self):
        errors = self._csv_manager.validate_all()
        if errors:
            messagebox.showwarning("Validation", "\n".join(errors))
        else:
            messagebox.showinfo("Validation", "All rows valid!")

    def _on_cell_edit(self, event):
        item = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not item or not col_id:
            return
        col_idx = int(col_id.replace('#', '')) - 1
        col_name = self._csv_manager.columns[col_idx]
        old_val = self._csv_manager.cards[int(item)].get(col_name, '')

        # Inline edit popup
        x, y, w, h = self.tree.bbox(item, col_id)
        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, old_val)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def _save(e=None):
            self._csv_manager.update_card(int(item), col_name, entry.get())
            entry.destroy()
            self._refresh_table()

        entry.bind('<Return>', _save)
        entry.bind('<FocusOut>', _save)
        entry.bind('<Escape>', lambda e: entry.destroy())
