"""
Read SIM Panel — Workflow 1.

Reads all accessible data from an inserted SIM card.
Public fields (ICCID, IMSI, ACC, etc.) are shown without authentication.
Protected fields (Ki, OPc, OTA keys) are revealed after ADM1 auth
and clicking "Read Card".

Detection is handled by the shared Card Status panel (left side).
This tab observes the card manager state — call refresh() after
a detect/mode change from the main window.
"""

import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from managers.card_manager import CardManager
from theme import ModernTheme


# Display order and labels for public fields
_PUBLIC_DISPLAY = [
    ("iccid", "ICCID"),
    ("imsi", "IMSI"),
    ("acc", "ACC"),
    ("msisdn", "MSISDN"),
    ("mnc_length", "MNC Length"),
    ("pin1", "PIN1"),
    ("puk1", "PUK1"),
    ("pin2", "PIN2"),
    ("puk2", "PUK2"),
    ("suci_protection_scheme", "SUCI Scheme"),
    ("suci_routing_indicator", "SUCI Routing Ind."),
    ("suci_hn_pubkey", "SUCI HN PubKey"),
]

# Display order and labels for protected fields
_PROTECTED_DISPLAY = [
    ("ki", "Ki"),
    ("opc", "OPc"),
    ("adm1", "ADM1"),
    ("kic1", "KIC1"),
    ("kid1", "KID1"),
    ("kik1", "KIK1"),
    ("kic2", "KIC2"),
    ("kid2", "KID2"),
    ("kik2", "KIK2"),
    ("kic3", "KIC3"),
    ("kid3", "KID3"),
    ("kik3", "KIK3"),
]


class ReadSIMPanel(ttk.Frame):
    """Tab that guides the user through reading a SIM card."""

    def __init__(self, parent, card_manager: CardManager, **kwargs):
        super().__init__(parent, **kwargs)
        self._cm = card_manager
        self._public_data: dict = {}
        self._protected_data: dict = {}
        self._detected_iccid: str = ""
        self._authenticated: bool = False
        self._build_ui()

    # ---- UI construction -----------------------------------------------

    def _build_ui(self):
        pad = ModernTheme.get_padding("medium")

        # --- Public Fields grid ---
        pub_frame = ttk.LabelFrame(self, text="Public Fields (no auth required)")
        pub_frame.pack(fill=tk.X, padx=pad, pady=(pad, pad // 2))

        pub_grid = ttk.Frame(pub_frame)
        pub_grid.pack(fill=tk.X, padx=pad, pady=pad)

        self._pub_labels: dict[str, ttk.Label] = {}
        for i, (key, label) in enumerate(_PUBLIC_DISPLAY):
            row, col = divmod(i, 2)
            ttk.Label(pub_grid, text=f"{label}:").grid(
                row=row, column=col * 2, sticky=tk.W, pady=2, padx=(0, 4))
            val_lbl = ttk.Label(pub_grid, text="-")
            val_lbl.grid(row=row, column=col * 2 + 1, sticky=tk.W,
                         pady=2, padx=(0, pad * 2))
            self._pub_labels[key] = val_lbl

        # Make value columns expand
        pub_grid.columnconfigure(1, weight=1)
        pub_grid.columnconfigure(3, weight=1)

        # --- Authentication section ---
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

        # --- Protected Fields section ---
        prot_frame = ttk.LabelFrame(self, text="Protected Fields (requires ADM1)")
        prot_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad // 2)

        prot_top = ttk.Frame(prot_frame)
        prot_top.pack(fill=tk.X, padx=pad, pady=(pad, 0))

        self._read_btn = ttk.Button(
            prot_top, text="Read Card", command=self._on_read_card)
        self._read_btn.pack(side=tk.LEFT)
        self._read_btn.configure(state=tk.DISABLED)
        self._read_status = ttk.Label(prot_top, text="Authenticate first")
        self._read_status.pack(side=tk.LEFT, padx=(pad, 0))

        prot_grid = ttk.Frame(prot_frame)
        prot_grid.pack(fill=tk.X, padx=pad, pady=pad)

        self._prot_labels: dict[str, ttk.Label] = {}
        for i, (key, label) in enumerate(_PROTECTED_DISPLAY):
            row, col = divmod(i, 2)
            ttk.Label(prot_grid, text=f"{label}:").grid(
                row=row, column=col * 2, sticky=tk.W, pady=2, padx=(0, 4))
            val_lbl = ttk.Label(prot_grid, text="-")
            val_lbl.grid(row=row, column=col * 2 + 1, sticky=tk.W,
                         pady=2, padx=(0, pad * 2))
            self._prot_labels[key] = val_lbl

        prot_grid.columnconfigure(1, weight=1)
        prot_grid.columnconfigure(3, weight=1)

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
        # Reset auth / protected state when card changes
        self._authenticated = False
        self._read_btn.configure(state=tk.DISABLED)
        self._read_status.configure(text="Authenticate first")
        self._protected_data = {}
        for lbl in self._prot_labels.values():
            lbl.configure(text="-")

        # Read public data
        pub = self._cm.read_public_data()
        if pub:
            self._public_data = pub
            self._detected_iccid = pub.get("iccid", "")
            for key, lbl in self._pub_labels.items():
                val = pub.get(key, "")
                lbl.configure(text=val if val else "-")
        else:
            self._public_data = {}
            self._detected_iccid = ""
            for lbl in self._pub_labels.values():
                lbl.configure(text="-")

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
        """Read protected fields from the card after authentication."""
        if not self._authenticated:
            self._read_status.configure(text="Not authenticated")
            return
        data = self._cm.read_protected_data()
        if data is None:
            self._read_status.configure(text="Failed to read card data")
            return
        self._protected_data = data
        self._read_status.configure(
            text=f"Read {len(data)} protected field(s)")
        for key, lbl in self._prot_labels.items():
            val = data.get(key, "")
            lbl.configure(text=val if val else "-")

    def _on_copy(self):
        combined = {}
        combined.update(self._public_data)
        combined.update(self._protected_data)
        if not combined:
            return
        lines = [f"{k.upper()}: {v}" for k, v in combined.items()]
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)

    def _on_export(self):
        combined = {}
        combined.update(self._public_data)
        combined.update(self._protected_data)
        if not combined:
            return
        path = filedialog.asksaveasfilename(
            title="Export Card Data", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            keys = list(combined.keys())
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=keys)
                writer.writeheader()
                writer.writerow(combined)
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))
