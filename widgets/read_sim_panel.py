"""
Read SIM Panel — Workflow 1.

Reads all accessible data from an inserted SIM card.
Public fields (ICCID, card type) are shown without authentication.
Protected fields are revealed after the user provides ADM1 and
clicking "Read Card".

Detection is handled by the shared Card Status panel (left side).
This tab observes the card manager state — call refresh() after
a detect/mode change from the main window.
"""

import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from managers.card_manager import CardManager
from theme import ModernTheme


class ReadSIMPanel(ttk.Frame):
    """Tab that guides the user through reading a SIM card."""

    def __init__(self, parent, card_manager: CardManager, **kwargs):
        super().__init__(parent, **kwargs)
        self._cm = card_manager
        self._card_data: dict = {}
        self._detected_iccid: str = ""
        self._authenticated: bool = False
        self._build_ui()

    # ---- UI construction -----------------------------------------------

    def _build_ui(self):
        pad = ModernTheme.get_padding("medium")

        # --- Public fields (populated when card is detected via Card Status panel) ---
        pub = ttk.LabelFrame(self, text="Public Fields (no auth required)")
        pub.pack(fill=tk.X, padx=pad, pady=(pad, pad // 2))

        inner = ttk.Frame(pub)
        inner.pack(fill=tk.X, padx=pad, pady=pad)
        ttk.Label(inner, text="ICCID:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self._pub_iccid = ttk.Label(inner, text="— detect card from Card Status panel")
        self._pub_iccid.grid(row=0, column=1, sticky=tk.W, padx=(pad, 0), pady=2)
        ttk.Label(inner, text="Card Type:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self._pub_type = ttk.Label(inner, text="-")
        self._pub_type.grid(row=1, column=1, sticky=tk.W, padx=(pad, 0), pady=2)

        # --- ADM1 + Authenticate ---
        auth_frame = ttk.LabelFrame(self, text="Authentication")
        auth_frame.pack(fill=tk.X, padx=pad, pady=pad // 2)

        auth_inner = ttk.Frame(auth_frame)
        auth_inner.pack(fill=tk.X, padx=pad, pady=pad)

        ttk.Label(auth_inner, text="ADM1:").grid(
            row=0, column=0, sticky=tk.W, pady=2)
        self._adm1_var = tk.StringVar()
        self._adm1_entry = ttk.Entry(
            auth_inner, textvariable=self._adm1_var, width=20)
        self._adm1_entry.grid(row=0, column=1, sticky=tk.W, padx=pad, pady=2)
        self._auth_btn = ttk.Button(
            auth_inner, text="Authenticate", command=self._on_authenticate)
        self._auth_btn.grid(row=0, column=2, padx=(0, pad), pady=2)

        self._csv_adm_btn = ttk.Button(
            auth_inner, text="Load ADM1 from CSV...",
            command=self._on_load_adm1_csv)
        self._csv_adm_btn.grid(row=1, column=1, sticky=tk.W, padx=pad, pady=2)

        self._auth_status = ttk.Label(
            auth_inner, text="Enter ADM1 to authenticate")
        self._auth_status.grid(row=2, column=0, columnspan=3,
                               sticky=tk.W, pady=(pad, 0))

        # --- Read Card button (enabled after auth) ---
        read_frame = ttk.LabelFrame(self, text="Read Card Data")
        read_frame.pack(fill=tk.X, padx=pad, pady=pad // 2)

        read_inner = ttk.Frame(read_frame)
        read_inner.pack(fill=tk.X, padx=pad, pady=pad)

        self._read_btn = ttk.Button(
            read_inner, text="Read Card", command=self._on_read_card)
        self._read_btn.pack(side=tk.LEFT)
        self._read_btn.configure(state=tk.DISABLED)
        self._read_status = ttk.Label(read_inner, text="Authenticate first")
        self._read_status.pack(side=tk.LEFT, padx=(pad, 0))

        # --- All card data tree ---
        data_frame = ttk.LabelFrame(self, text="Card Contents")
        data_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad // 2)

        self._data_tree = ttk.Treeview(
            data_frame, columns=("value",), show="tree headings", height=10)
        self._data_tree.heading("#0", text="Field")
        self._data_tree.heading("value", text="Value")
        self._data_tree.column("#0", width=120, stretch=False)
        self._data_tree.column("value", width=300)
        sb = ttk.Scrollbar(data_frame, orient=tk.VERTICAL,
                           command=self._data_tree.yview)
        self._data_tree.configure(yscrollcommand=sb.set)
        self._data_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                             padx=(pad, 0), pady=pad)
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, pad), pady=pad)

        # --- Bottom action buttons ---
        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, padx=pad, pady=(0, pad))
        self._copy_btn = ttk.Button(
            btn_row, text="Copy All to Clipboard", command=self._on_copy)
        self._copy_btn.pack(side=tk.LEFT, padx=(0, pad))
        self._export_btn = ttk.Button(
            btn_row, text="Export to CSV...", command=self._on_export)
        self._export_btn.pack(side=tk.LEFT)

    # ---- public interface (called by main.py) --------------------------

    def refresh(self):
        """Update public fields from the current card manager state.

        Call this after a card detect or mode change from the main window.
        """
        iccid = self._cm.read_iccid() or ""
        self._detected_iccid = iccid

        if iccid:
            self._pub_iccid.configure(text=iccid)
            self._pub_type.configure(text=self._cm.card_type.name)
        else:
            self._pub_iccid.configure(
                text="— detect card from Card Status panel")
            self._pub_type.configure(text="-")

        # Reset auth state when card changes
        self._authenticated = False
        self._read_btn.configure(state=tk.DISABLED)
        self._read_status.configure(text="Authenticate first")
        self._card_data = {}
        self._data_tree.delete(*self._data_tree.get_children())

    # ---- actions -------------------------------------------------------

    def _on_authenticate(self):
        adm1 = self._adm1_var.get().strip()
        if not adm1:
            self._auth_status.configure(text="Please enter ADM1")
            return
        if not self._detected_iccid:
            self._auth_status.configure(
                text="No card detected — use Detect Card in the left panel")
            return
        ok, msg = self._cm.authenticate(
            adm1, expected_iccid=self._detected_iccid or None)
        if ok:
            self._auth_status.configure(text=msg)
            self._authenticated = True
            self._read_btn.configure(state=tk.NORMAL)
            self._read_status.configure(text="Ready to read")
        else:
            self._auth_status.configure(text=msg)
            self._authenticated = False
            self._read_btn.configure(state=tk.DISABLED)
            if "ICCID mismatch" in msg:
                messagebox.showwarning("ICCID Mismatch", msg)

    def _on_load_adm1_csv(self):
        if not self._detected_iccid:
            messagebox.showinfo(
                "Detect First",
                "Please detect a card first (via Card Status panel) "
                "so the ICCID is known.")
            return
        path = filedialog.askopenfilename(
            title="Select CSV with ADM1 data",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        adm1 = self._lookup_adm1_in_csv(path, self._detected_iccid)
        if adm1:
            self._adm1_var.set(adm1)
            self._auth_status.configure(
                text=f"ADM1 loaded from CSV (matched ICCID)")
        else:
            self._auth_status.configure(
                text="No matching ICCID found in CSV")

    @staticmethod
    def _lookup_adm1_in_csv(csv_path: str, iccid: str) -> str:
        """Search *csv_path* for a row whose ICCID matches, return its ADM1."""
        try:
            with open(csv_path, "r", newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    if row.get("ICCID", "").strip() == iccid:
                        return row.get("ADM1", "").strip()
        except Exception:
            pass
        return ""

    def _on_read_card(self):
        """Read all fields from the card after authentication."""
        if not self._authenticated:
            self._read_status.configure(text="Not authenticated")
            return
        data = self._cm.read_card_data()
        if data is None:
            self._read_status.configure(text="Failed to read card data")
            return
        self._card_data = data
        self._read_status.configure(
            text=f"Read {len(data)} fields successfully")
        self._populate_data_tree(data)

    def _populate_data_tree(self, data: dict):
        self._data_tree.delete(*self._data_tree.get_children())
        display_order = [
            "iccid", "imsi", "ki", "opc", "acc",
            "pin1", "puk1", "pin2", "puk2",
            "mnc_length", "msisdn",
        ]
        shown = set()
        for key in display_order:
            if key in data:
                self._data_tree.insert(
                    "", tk.END, text=key.upper(), values=(data[key],))
                shown.add(key)
        for key, val in sorted(data.items()):
            if key not in shown and key != "card_type":
                self._data_tree.insert(
                    "", tk.END, text=key.upper(), values=(val,))

    def _on_copy(self):
        if not self._card_data:
            return
        lines = [f"{k.upper()}: {v}" for k, v in self._card_data.items()]
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)

    def _on_export(self):
        if not self._card_data:
            return
        path = filedialog.asksaveasfilename(
            title="Export Card Data", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            keys = list(self._card_data.keys())
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=keys)
                writer.writeheader()
                writer.writerow(self._card_data)
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))
