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
]

# Protected fields revealed after ADM1 auth + read
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

        # Step 1: Public info (shown after detect)
        pub_frame = ttk.LabelFrame(self, text="1. Public Card Info")
        pub_frame.pack(fill=tk.X, padx=pad, pady=(pad, pad // 2))

        self._pub_vars: dict[str, tk.StringVar] = {}
        for i, (key, label) in enumerate(_PUBLIC_DISPLAY):
            ttk.Label(pub_frame, text=f"{label}:").grid(
                row=i, column=0, sticky=tk.W, padx=pad, pady=1)
            var = tk.StringVar(value="\u2014")
            lbl = ttk.Label(pub_frame, textvariable=var, width=40, anchor=tk.W)
            lbl.grid(row=i, column=1, sticky=(tk.W, tk.E), padx=pad, pady=1)
            self._pub_vars[key] = var
        pub_frame.columnconfigure(1, weight=1)

        # Step 2: Authentication
        auth_frame = ttk.LabelFrame(self, text="2. ADM1 Authentication")
        auth_frame.pack(fill=tk.X, padx=pad, pady=pad // 2)

        auth_inner = ttk.Frame(auth_frame)
        auth_inner.pack(fill=tk.X, padx=pad, pady=pad)

        ttk.Label(auth_inner, text="ADM1:").pack(side=tk.LEFT)
        self._adm1_var = tk.StringVar()
        self._adm1_entry = ttk.Entry(
            auth_inner, textvariable=self._adm1_var, width=20, show="\u2022")
        self._adm1_entry.pack(side=tk.LEFT, padx=(4, 0))

        ttk.Button(auth_inner, text="Authenticate",
                   command=self._on_authenticate).pack(side=tk.LEFT, padx=(pad, 0))
        ttk.Button(auth_inner, text="ADM1 from CSV\u2026",
                   command=self._on_compare_browse).pack(side=tk.LEFT, padx=(pad, 0))

        self._auth_status = ttk.Label(auth_frame, text="", style="Small.TLabel")
        self._auth_status.pack(anchor=tk.W, padx=pad, pady=(0, pad))

        # Step 3: Protected data (revealed after auth + read)
        prot_frame = ttk.LabelFrame(self, text="3. Protected Data (after Read)")
        prot_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad // 2)

        self._prot_vars: dict[str, tk.StringVar] = {}
        for i, (key, label) in enumerate(_PROTECTED_DISPLAY):
            ttk.Label(prot_frame, text=f"{label}:").grid(
                row=i, column=0, sticky=tk.W, padx=pad, pady=1)
            var = tk.StringVar(value="\u2014")
            lbl = ttk.Label(prot_frame, textvariable=var, width=40, anchor=tk.W)
            lbl.grid(row=i, column=1, sticky=(tk.W, tk.E), padx=pad, pady=1)
            self._prot_vars[key] = var
        prot_frame.columnconfigure(1, weight=1)

        # Action row
        act = ttk.Frame(self)
        act.pack(fill=tk.X, padx=pad, pady=(pad // 2, pad))

        self._read_btn = ttk.Button(
            act, text="Read Card", command=self._on_read_card,
            state=tk.DISABLED, style="Accent.TButton")
        self._read_btn.pack(side=tk.LEFT)

        ttk.Button(act, text="Copy All", command=self._on_copy_all).pack(
            side=tk.LEFT, padx=(pad, 0))
        ttk.Button(act, text="Export CSV\u2026", command=self._on_export).pack(
            side=tk.LEFT, padx=(pad, 0))

        self._read_status = ttk.Label(act, text="", style="Small.TLabel")
        self._read_status.pack(side=tk.LEFT, padx=(pad, 0), fill=tk.X, expand=True)

    # ---- Refresh from external detect/mode changes ---------------------

    def refresh(self):
        """Called by main window when card status changes."""
        if self._cm.is_card_detected():
            pub = self._cm.read_public()
            if pub:
                self._public_data = pub
                for key, var in self._pub_vars.items():
                    var.set(pub.get(key, "\u2014"))
                self._detected_iccid = pub.get("iccid", "")
        else:
            for var in self._pub_vars.values():
                var.set("\u2014")
            self._public_data = {}
            self._detected_iccid = ""
            self._authenticated = False
            self._read_btn.configure(state=tk.DISABLED)

    # ---- Actions -------------------------------------------------------

    def _on_authenticate(self):
        adm1 = self._adm1_var.get().strip()
        if not adm1:
            self._auth_status.configure(text="Enter ADM1 key")
            return
        ok, msg = self._cm.authenticate(
            adm1, expected_iccid=self._detected_iccid or None)
        if ok:
            self._authenticated = True
            self._read_btn.configure(state=tk.NORMAL)
            self._auth_status.configure(text=msg)
        else:
            self._auth_status.configure(text=msg)

    def _on_compare_browse(self):
        """Browse for a CSV/EML to auto-fill ADM1 by matching ICCID."""
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
        if not self._authenticated:
            return
        ok, data = self._cm.read_card_full()
        if ok and data:
            self._protected_data = data
            for key, var in self._prot_vars.items():
                var.set(data.get(key, "\u2014"))
            # Store into shared state for other tabs
            combined = {}
            combined.update(self._public_data)
            combined.update(data)
            self._last_read_data.clear()
            self._last_read_data.update(combined)
            self._read_status.configure(text="Card read successfully")
        else:
            self._read_status.configure(
                text=data if isinstance(data, str) else "Read failed")

    def _on_copy_all(self):
        combined = {}
        combined.update(self._public_data)
        combined.update(self._protected_data)
        if not combined:
            return
        lines = [f"{k}: {v}" for k, v in combined.items() if v and v != "\u2014"]
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
