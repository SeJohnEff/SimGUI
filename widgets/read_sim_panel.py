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
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from managers.card_manager import CardManager
from theme import ModernTheme
from utils import get_browse_initial_dir
from widgets.tooltip import add_tooltip

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

    def __init__(self, parent, card_manager: CardManager, *,
                 last_read_data: dict | None = None,
                 ns_manager=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._cm = card_manager
        self._ns_manager = ns_manager
        self._last_browse_dir: str | None = None
        self._last_read_data = last_read_data if last_read_data is not None else {}
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

        self._pub_vars: dict[str, tk.StringVar] = {}
        self._pub_entries: dict[str, ttk.Entry] = {}
        for i, (key, label) in enumerate(_PUBLIC_DISPLAY):
            row, col = divmod(i, 2)
            ttk.Label(pub_grid, text=f"{label}:").grid(
                row=row, column=col * 2, sticky=tk.W, pady=2, padx=(0, 4))
            var = tk.StringVar(value="-")
            entry = ttk.Entry(pub_grid, textvariable=var,
                              state="readonly", style="Copyable.TEntry")
            entry.grid(row=row, column=col * 2 + 1, sticky=(tk.W, tk.E),
                       pady=2, padx=(0, pad * 2))
            self._pub_vars[key] = var
            self._pub_entries[key] = entry

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
        add_tooltip(self._auth_btn, "Enter ADM1 key to unlock protected fields (Ki, OPc, etc.)")

        self._csv_adm_btn = ttk.Button(
            auth_inner, text="Load ADM1 from CSV...",
            command=self._on_load_adm1_csv)
        self._csv_adm_btn.grid(row=1, column=1, sticky=tk.W, padx=pad, pady=2)
        add_tooltip(self._csv_adm_btn, "Load ADM1 from a CSV/EML file matching this card's ICCID")

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
        add_tooltip(self._read_btn, "Read all accessible data from the inserted card")
        self._read_btn.configure(state=tk.DISABLED)
        self._read_status = ttk.Label(prot_top, text="Authenticate first")
        self._read_status.pack(side=tk.LEFT, padx=(pad, 0))

        prot_grid = ttk.Frame(prot_frame)
        prot_grid.pack(fill=tk.X, padx=pad, pady=pad)

        self._prot_vars: dict[str, tk.StringVar] = {}
        self._prot_entries: dict[str, ttk.Entry] = {}
        for i, (key, label) in enumerate(_PROTECTED_DISPLAY):
            row, col = divmod(i, 2)
            ttk.Label(prot_grid, text=f"{label}:").grid(
                row=row, column=col * 2, sticky=tk.W, pady=2, padx=(0, 4))
            var = tk.StringVar(value="-")
            entry = ttk.Entry(prot_grid, textvariable=var,
                              state="readonly", style="Copyable.TEntry")
            entry.grid(row=row, column=col * 2 + 1, sticky=(tk.W, tk.E),
                       pady=2, padx=(0, pad * 2))
            self._prot_vars[key] = var
            self._prot_entries[key] = entry

        prot_grid.columnconfigure(1, weight=1)
        prot_grid.columnconfigure(3, weight=1)

        # --- Bottom action buttons ---
        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, padx=pad, pady=(0, pad))
        self._copy_btn = ttk.Button(
            btn_row, text="Copy All to Clipboard", command=self._on_copy)
        self._copy_btn.pack(side=tk.LEFT, padx=(0, pad))
        add_tooltip(self._copy_btn, "Copy all card data to clipboard")
        self._export_btn = ttk.Button(
            btn_row, text="Export to CSV...", command=self._on_export)
        self._export_btn.pack(side=tk.LEFT)
        add_tooltip(self._export_btn, "Export card data as a JSON file")

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
        for var in self._prot_vars.values():
            var.set("-")

        # Read public data
        pub = self._cm.read_public_data()
        if pub:
            self._public_data = pub
            self._detected_iccid = pub.get("iccid", "")
            for key, var in self._pub_vars.items():
                val = pub.get(key, "")
                var.set(val if val else "-")
            # Store public data in shared state for Program SIM tab
            self._update_shared_read_data()
        else:
            self._public_data = {}
            self._detected_iccid = ""
            for var in self._pub_vars.values():
                var.set("-")
            # Clear shared state when no card
            self._last_read_data.clear()

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
        from managers.csv_manager import SIM_DATA_FILETYPES
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        kwargs = {"title": "Select ADM1 Data File", "filetypes": SIM_DATA_FILETYPES}
        if init_dir:
            kwargs["initialdir"] = init_dir
        path = filedialog.askopenfilename(**kwargs)
        if not path:
            return
        self._last_browse_dir = os.path.dirname(path)
        adm1 = self._lookup_adm1_in_file(path, self._detected_iccid)
        if adm1:
            self._adm1_var.set(adm1)
            self._auth_status.configure(
                text="ADM1 loaded from CSV (matched ICCID)")
        else:
            self._auth_status.configure(
                text="No matching ICCID found in CSV")

    @staticmethod
    def _lookup_adm1_in_file(path: str, iccid: str) -> str:
        """Search *path* (CSV or EML) for a row whose ICCID matches, return its ADM1."""
        try:
            if path.lower().endswith(".eml"):
                from utils.eml_parser import parse_eml_file
                cards, _ = parse_eml_file(path)
                for card in cards:
                    if card.get("ICCID", "").strip() == iccid:
                        return card.get("ADM1", "").strip()
            else:
                with open(path, "r", newline="", encoding="utf-8-sig") as fh:
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
        for key, var in self._prot_vars.items():
            val = data.get(key, "")
            var.set(val if val else "-")
        # Update shared state with protected fields
        self._update_shared_read_data()

    def _update_shared_read_data(self):
        """Merge public + protected data into the shared last_read_data dict."""
        self._last_read_data.clear()
        self._last_read_data.update(self._public_data)
        self._last_read_data.update(self._protected_data)

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
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        save_kwargs = {
            "title": "Export Card Data", "defaultextension": ".csv",
            "filetypes": [("CSV files", "*.csv"), ("All files", "*.*")],
        }
        if init_dir:
            save_kwargs["initialdir"] = init_dir
        path = filedialog.asksaveasfilename(**save_kwargs)
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
