"""
Program SIM Panel — Workflow 2.

Program a single SIM card. Data comes from manual entry or CSV selection.
Two-step flow: Authenticate → Program.  Card detection is automatic
via CardWatcher.  When a card is inserted, fields are auto-populated
from the IccidIndex if the card's ICCID is found in a loaded data file.

Layout uses a vertical PanedWindow so the operator can drag the divider
to give more space to the card-data fields or the CSV table.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from managers.card_manager import CardManager
from managers.csv_manager import SIM_DATA_FILETYPES, CSVManager
from theme import ModernTheme
from utils import get_browse_initial_dir
from widgets.tooltip import add_tooltip

# Fields shown in the form.  Tuple: (key, label, editable_when_csv)
_FORM_FIELDS = [
    ("ICCID", "ICCID", False),
    ("IMSI", "IMSI", True),
    ("Ki", "Ki", False),
    ("OPc", "OPc", False),
    ("ADM1", "ADM1", False),
    ("ACC", "ACC", True),
    ("SPN", "SPN", True),
    ("FPLMN", "FPLMN", True),
]


class ProgramSIMPanel(ttk.Frame):
    """Tab for programming a single SIM card."""

    def __init__(self, parent, card_manager: CardManager, *,
                 last_read_data: dict | None = None,
                 ns_manager=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._cm = card_manager
        self._ns_manager = ns_manager
        self._last_browse_dir: str | None = None
        self._csv = CSVManager()
        self._last_read_data = last_read_data if last_read_data is not None else {}
        self._mode_var = tk.StringVar(value="manual")
        self._field_vars: dict[str, tk.StringVar] = {}
        self._field_entries: dict[str, ttk.Entry] = {}
        self._step = 0  # 0=ready, 1=detected, 2=authenticated

        # Callback set by main.py for cross-tab sync
        self.on_csv_loaded_callback = None

        self._build_ui()
        self._on_mode_change()

    # ---- UI construction -----------------------------------------------

    def _build_ui(self):
        pad = ModernTheme.get_padding("medium")

        # Data source toggle — always visible at top
        src = ttk.Frame(self)
        src.pack(fill=tk.X, padx=pad, pady=(pad, pad // 2))
        ttk.Label(src, text="Data Source:").pack(side=tk.LEFT)
        _manual_rb = ttk.Radiobutton(src, text="Manual Entry", variable=self._mode_var,
                        value="manual", command=self._on_mode_change)
        _manual_rb.pack(side=tk.LEFT, padx=(pad, 0))
        add_tooltip(_manual_rb, "Enter card data by hand")
        _csv_rb = ttk.Radiobutton(src, text="From CSV", variable=self._mode_var,
                        value="csv", command=self._on_mode_change)
        _csv_rb.pack(side=tk.LEFT, padx=(pad, 0))
        add_tooltip(_csv_rb, "Load from file")
        _read_card_rb = ttk.Radiobutton(src, text="From Read Card", variable=self._mode_var,
                        value="read_card", command=self._on_mode_change)
        _read_card_rb.pack(side=tk.LEFT, padx=(pad, 0))
        add_tooltip(_read_card_rb, "Use data from last card read")

        # --- PanedWindow: top = Card Data + Actions, bottom = CSV table ---
        self._paned = tk.PanedWindow(
            self, orient=tk.VERTICAL, sashwidth=6, sashrelief=tk.RAISED,
            bg=ModernTheme.get_color("border"))
        self._paned.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, pad))

        # --- Top pane: Card Data + Actions ---
        top_pane = ttk.Frame(self._paned)

        # Form
        form_frame = ttk.LabelFrame(top_pane, text="Card Data")
        form_frame.pack(fill=tk.X, padx=0, pady=(0, pad // 2))

        _FIELD_TOOLTIPS = {
            "ICCID": "Integrated Circuit Card Identifier.\n19-20 digits. Example: 89999880000003010011",
            "IMSI": "International Mobile Subscriber Identity.\n6-15 digits. Example: 99988000301001",
            "Ki": "Authentication key (hex).\n32 hex characters. Example: E049AF7D...C03FD919",
            "OPc": "Operator key (hex).\n32 hex characters. Example: 9EB1A951...D4053A0E",
            "ADM1": "Admin key for card access.\n8 decimal digits or 16 hex chars.\n\u26a0 3 wrong attempts = permanent lock!",
            "ACC": "Access Control Class.\n4 hex digits. Example: 0001",
            "SPN": "Service Provider Name.\nExample: BOLIDEN",
            "FPLMN": "Forbidden PLMNs, semicolon-separated.\nExample: 24007;24024;24001;24008;24002",
        }

        for i, (key, label, _) in enumerate(_FORM_FIELDS):
            lbl = ttk.Label(form_frame, text=f"{label}:")
            lbl.grid(row=i, column=0, sticky=tk.W, padx=pad, pady=2)
            var = tk.StringVar()
            entry = ttk.Entry(form_frame, textvariable=var, width=40)
            entry.grid(row=i, column=1, sticky=(tk.W, tk.E), padx=pad, pady=2)
            self._field_vars[key] = var
            self._field_entries[key] = entry
            if key in _FIELD_TOOLTIPS:
                add_tooltip(lbl, _FIELD_TOOLTIPS[key])
                add_tooltip(entry, _FIELD_TOOLTIPS[key])
        form_frame.columnconfigure(1, weight=1)

        # Action buttons
        act = ttk.LabelFrame(top_pane, text="Actions")
        act.pack(fill=tk.X, padx=0, pady=pad // 2)

        btn_row = ttk.Frame(act)
        btn_row.pack(fill=tk.X, padx=pad, pady=pad)
        self._auth_btn = ttk.Button(
            btn_row, text="1. Authenticate", command=self._on_authenticate,
            state=tk.DISABLED)
        self._auth_btn.pack(side=tk.LEFT, padx=(0, pad))
        add_tooltip(self._auth_btn, "Verify the ADM1 key with the card")
        self._prog_btn = ttk.Button(
            btn_row, text="2. Program Card", command=self._on_program,
            state=tk.DISABLED, style="Accent.TButton")
        self._prog_btn.pack(side=tk.LEFT)
        add_tooltip(self._prog_btn, "Write all field values to the inserted SIM card")

        self._action_status = ttk.Label(act, text="Insert a SIM card...")
        self._action_status.pack(anchor=tk.W, padx=pad, pady=(0, pad))

        self._paned.add(top_pane, minsize=200)

        # --- Bottom pane: CSV Selection ---
        self._csv_pane = ttk.Frame(self._paned)

        self._csv_frame = ttk.LabelFrame(self._csv_pane, text="CSV Selection")
        self._csv_frame.pack(fill=tk.BOTH, expand=True)

        csv_bar = ttk.Frame(self._csv_frame)
        csv_bar.pack(fill=tk.X, padx=pad, pady=(pad, 0))
        self._csv_path_var = tk.StringVar()
        ttk.Entry(csv_bar, textvariable=self._csv_path_var,
                  state="readonly", width=40).pack(side=tk.LEFT, fill=tk.X, expand=True)
        _browse_csv_btn = ttk.Button(csv_bar, text="Browse...",
                   command=self._on_browse_csv)
        _browse_csv_btn.pack(side=tk.LEFT, padx=(pad, 0))
        add_tooltip(_browse_csv_btn, "Open a CSV or EML file with SIM card data")
        self._csv_count_lbl = ttk.Label(csv_bar, text="")
        self._csv_count_lbl.pack(side=tk.LEFT, padx=(pad, 0))

        # Filename label
        self._csv_filename_lbl = ttk.Label(self._csv_frame, text="",
                                           style="Small.TLabel")
        self._csv_filename_lbl.pack(anchor=tk.W, padx=pad, pady=(2, 0))

        # Tree + scrollbar in a container
        tree_container = ttk.Frame(self._csv_frame)
        tree_container.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        self._card_tree = ttk.Treeview(
            tree_container, columns=("iccid", "imsi", "adm1"),
            show="headings", height=5)
        self._card_tree.heading("iccid", text="ICCID")
        self._card_tree.heading("imsi", text="IMSI")
        self._card_tree.heading("adm1", text="ADM1")
        self._card_tree.column("iccid", width=180)
        self._card_tree.column("imsi", width=150)
        self._card_tree.column("adm1", width=100)

        tree_sb = ttk.Scrollbar(tree_container, orient=tk.VERTICAL,
                                command=self._card_tree.yview)
        self._card_tree.configure(yscrollcommand=tree_sb.set)
        self._card_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._card_tree.bind("<<TreeviewSelect>>", self._on_card_select)

        self._paned.add(self._csv_pane, minsize=100)

    # ---- mode switching ------------------------------------------------

    def _on_mode_change(self):
        mode = self._mode_var.get()
        is_csv = mode == "csv"
        is_read_card = mode == "read_card"

        # Show/hide the CSV pane in the PanedWindow
        if is_csv:
            if self._csv_pane not in [self._paned.panes()]:
                try:
                    self._paned.add(self._csv_pane, minsize=100)
                except tk.TclError:
                    pass  # already added
        else:
            try:
                self._paned.forget(self._csv_pane)
            except tk.TclError:
                pass  # already removed

        # All fields editable for manual and read_card modes
        for key, _, editable_csv in _FORM_FIELDS:
            state = "normal" if (not is_csv or editable_csv) else "readonly"
            self._field_entries[key].configure(state=state)

        if is_read_card:
            self._populate_from_read_card()

        self._reset_step()

    # ---- Read Card population ------------------------------------------

    # Map from lowercase read-data keys to form field keys
    _READ_KEY_MAP = {
        "iccid": "ICCID",
        "imsi": "IMSI",
        "ki": "Ki",
        "opc": "OPc",
        "adm1": "ADM1",
        "acc": "ACC",
        "spn": "SPN",
        "fplmn": "FPLMN",
    }

    def _populate_from_read_card(self):
        """Fill form fields from the shared last-read card data."""
        if not self._last_read_data:
            self._action_status.configure(
                text="No card data available — read a card first on the Read SIM tab",
                style="Warning.TLabel")
            return
        for read_key, form_key in self._READ_KEY_MAP.items():
            if form_key in self._field_vars:
                self._field_vars[form_key].set(
                    self._last_read_data.get(read_key, ""))
        self._action_status.configure(
            text="Fields populated from last read card",
            style="Success.TLabel")

    # ---- CSV -----------------------------------------------------------

    def _on_browse_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        kwargs = {"title": "Open SIM Data File", "filetypes": SIM_DATA_FILETYPES}
        if init_dir:
            kwargs["initialdir"] = init_dir
        path = filedialog.askopenfilename(**kwargs)
        if not path:
            return
        import os
        self._last_browse_dir = os.path.dirname(path)
        self.load_csv_file(path)

    def load_csv_file(self, path: str, *, _from_sync: bool = False) -> bool:
        """Load a CSV or EML file and refresh the card tree.

        Called by Browse button or by cross-tab sync from BatchProgramPanel.
        *_from_sync* prevents infinite callback loops.
        """
        try:
            if not self._csv.load_file(path):
                if not _from_sync:
                    messagebox.showerror("Error", f"No card data found in {path}")
                return False
        except ValueError as exc:
            if not _from_sync:
                messagebox.showerror("Import Error", str(exc))
            return False
        self._csv_path_var.set(path)
        import os
        self._csv_filename_lbl.configure(text=os.path.basename(path))
        self._csv_count_lbl.configure(
            text=f"({self._csv.get_card_count()} cards)")
        self._refresh_card_tree()
        # Cross-tab sync
        if not _from_sync and callable(self.on_csv_loaded_callback):
            self.on_csv_loaded_callback(path)
        return True

    def _refresh_card_tree(self):
        self._card_tree.delete(*self._card_tree.get_children())
        for i in range(self._csv.get_card_count()):
            card = self._csv.get_card(i)
            if card:
                self._card_tree.insert("", tk.END, iid=str(i), values=(
                    card.get("ICCID", ""),
                    card.get("IMSI", ""),
                    card.get("ADM1", ""),
                ))

    def _on_card_select(self, _event=None):
        sel = self._card_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        card = self._csv.get_card(idx)
        if not card:
            return
        for key, _, _ in _FORM_FIELDS:
            val = card.get(key, card.get(key.upper(), ""))
            # Also try OPC → OPc mapping
            if key == "OPc" and not val:
                val = card.get("OPC", "")
            self._field_vars[key].set(val)
        self._reset_step()

    # ---- 2-step flow (auto-detect replaces manual Detect) ---------------

    def _reset_step(self):
        self._step = 0
        self._auth_btn.configure(state=tk.DISABLED)
        self._prog_btn.configure(state=tk.DISABLED)
        self._action_status.configure(
            text="Insert a SIM card...", style="TLabel")

    def on_card_detected(self, iccid, card_data=None, file_path=None):
        """Called by CardWatcher (via main.py) when a card is auto-detected.

        If *card_data* is provided the form fields are auto-populated.
        """
        self._step = 1
        self._auth_btn.configure(state=tk.NORMAL)
        self._prog_btn.configure(state=tk.DISABLED)

        if card_data:
            # Auto-populate all form fields from the indexed data
            for key, _, _ in _FORM_FIELDS:
                val = card_data.get(key, card_data.get(key.upper(), ""))
                if key == "OPc" and not val:
                    val = card_data.get("OPC", "")
                self._field_vars[key].set(val)
            import os
            src = os.path.basename(file_path) if file_path else "index"
            self._action_status.configure(
                text=f"Card detected — data loaded from {src}",
                style="Success.TLabel")
        else:
            # Card found but not in index — just show ICCID
            self._field_vars["ICCID"].set(iccid)
            self._action_status.configure(
                text=f"Card detected (ICCID {iccid}) — not in index, enter data manually",
                style="Warning.TLabel")

    def on_card_removed(self):
        """Called by CardWatcher when the card is removed."""
        self._reset_step()
        for key, _, _ in _FORM_FIELDS:
            self._field_vars[key].set("")

    def _on_authenticate(self):
        if self._step < 1:
            return
        adm1 = self._field_vars["ADM1"].get().strip()
        if not adm1:
            self._action_status.configure(
                text="ADM1 is required", style="Warning.TLabel")
            return
        expected_iccid = self._field_vars["ICCID"].get().strip() or None
        ok, msg = self._cm.authenticate(
            adm1, expected_iccid=expected_iccid)
        if ok:
            self._step = 2
            self._prog_btn.configure(state=tk.NORMAL)
            self._action_status.configure(text=msg, style="Success.TLabel")
        else:
            self._action_status.configure(text=msg, style="Error.TLabel")

    def _on_program(self):
        if self._step < 2:
            return
        card_data = {k: self._field_vars[k].get().strip()
                     for k, _, _ in _FORM_FIELDS}
        ok, msg = self._cm.program_card(card_data)
        if ok:
            self._action_status.configure(text=msg, style="Success.TLabel")
            # Notify main.py so it can save auto-artifact
            if callable(getattr(self, 'on_card_programmed_callback', None)):
                self.on_card_programmed_callback(card_data)
        else:
            self._action_status.configure(text=msg, style="Error.TLabel")
