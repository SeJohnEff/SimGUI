"""
Program SIM Panel — Workflow 2.

Program a single SIM card. Data comes from manual entry or CSV selection.
Three-step guided flow: Detect → Authenticate → Program.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from managers.card_manager import CardManager
from managers.csv_manager import CSVManager
from theme import ModernTheme


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

    def __init__(self, parent, card_manager: CardManager, **kwargs):
        super().__init__(parent, **kwargs)
        self._cm = card_manager
        self._csv = CSVManager()
        self._mode_var = tk.StringVar(value="manual")
        self._field_vars: dict[str, tk.StringVar] = {}
        self._field_entries: dict[str, ttk.Entry] = {}
        self._step = 0  # 0=ready, 1=detected, 2=authenticated
        self._build_ui()
        self._on_mode_change()

    # ---- UI construction -----------------------------------------------

    def _build_ui(self):
        pad = ModernTheme.get_padding("medium")

        # Data source toggle
        src = ttk.Frame(self)
        src.pack(fill=tk.X, padx=pad, pady=(pad, pad // 2))
        ttk.Label(src, text="Data Source:").pack(side=tk.LEFT)
        ttk.Radiobutton(src, text="Manual Entry", variable=self._mode_var,
                        value="manual", command=self._on_mode_change
                        ).pack(side=tk.LEFT, padx=(pad, 0))
        ttk.Radiobutton(src, text="From CSV", variable=self._mode_var,
                        value="csv", command=self._on_mode_change
                        ).pack(side=tk.LEFT, padx=(pad, 0))

        # CSV selector (hidden when manual)
        self._csv_frame = ttk.LabelFrame(self, text="CSV Selection")
        self._csv_frame.pack(fill=tk.X, padx=pad, pady=pad // 2)

        csv_bar = ttk.Frame(self._csv_frame)
        csv_bar.pack(fill=tk.X, padx=pad, pady=(pad, 0))
        self._csv_path_var = tk.StringVar()
        ttk.Entry(csv_bar, textvariable=self._csv_path_var,
                  state="readonly", width=40).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(csv_bar, text="Browse...",
                   command=self._on_browse_csv).pack(side=tk.LEFT, padx=(pad, 0))
        self._csv_count_lbl = ttk.Label(csv_bar, text="")
        self._csv_count_lbl.pack(side=tk.LEFT, padx=(pad, 0))

        self._card_tree = ttk.Treeview(
            self._csv_frame, columns=("iccid", "imsi", "adm1"),
            show="headings", height=5)
        self._card_tree.heading("iccid", text="ICCID")
        self._card_tree.heading("imsi", text="IMSI")
        self._card_tree.heading("adm1", text="ADM1")
        self._card_tree.column("iccid", width=180)
        self._card_tree.column("imsi", width=150)
        self._card_tree.column("adm1", width=100)
        self._card_tree.pack(fill=tk.X, padx=pad, pady=pad)
        self._card_tree.bind("<<TreeviewSelect>>", self._on_card_select)

        # Form
        form_frame = ttk.LabelFrame(self, text="Card Data")
        form_frame.pack(fill=tk.X, padx=pad, pady=pad // 2)

        for i, (key, label, _) in enumerate(_FORM_FIELDS):
            ttk.Label(form_frame, text=f"{label}:").grid(
                row=i, column=0, sticky=tk.W, padx=pad, pady=2)
            var = tk.StringVar()
            entry = ttk.Entry(form_frame, textvariable=var, width=40)
            entry.grid(row=i, column=1, sticky=(tk.W, tk.E), padx=pad, pady=2)
            self._field_vars[key] = var
            self._field_entries[key] = entry
        form_frame.columnconfigure(1, weight=1)

        # Action buttons
        act = ttk.LabelFrame(self, text="Actions")
        act.pack(fill=tk.X, padx=pad, pady=pad // 2)

        btn_row = ttk.Frame(act)
        btn_row.pack(fill=tk.X, padx=pad, pady=pad)
        self._detect_btn = ttk.Button(
            btn_row, text="1. Detect Card", command=self._on_detect)
        self._detect_btn.pack(side=tk.LEFT, padx=(0, pad))
        self._auth_btn = ttk.Button(
            btn_row, text="2. Authenticate", command=self._on_authenticate,
            state=tk.DISABLED)
        self._auth_btn.pack(side=tk.LEFT, padx=(0, pad))
        self._prog_btn = ttk.Button(
            btn_row, text="3. Program Card", command=self._on_program,
            state=tk.DISABLED, style="Accent.TButton")
        self._prog_btn.pack(side=tk.LEFT)

        self._action_status = ttk.Label(act, text="Ready — insert card and detect")
        self._action_status.pack(anchor=tk.W, padx=pad, pady=(0, pad))

    # ---- mode switching ------------------------------------------------

    def _on_mode_change(self):
        is_csv = self._mode_var.get() == "csv"
        if is_csv:
            self._csv_frame.pack(fill=tk.X,
                                 padx=ModernTheme.get_padding("medium"),
                                 pady=ModernTheme.get_padding("medium") // 2)
        else:
            self._csv_frame.pack_forget()

        for key, _, editable_csv in _FORM_FIELDS:
            state = "normal" if (not is_csv or editable_csv) else "readonly"
            self._field_entries[key].configure(state=state)
        self._reset_step()

    # ---- CSV -----------------------------------------------------------

    def _on_browse_csv(self):
        path = filedialog.askopenfilename(
            title="Open CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        if not self._csv.load_csv(path):
            messagebox.showerror("Error", f"Failed to load {path}")
            return
        self._csv_path_var.set(path)
        self._csv_count_lbl.configure(
            text=f"({self._csv.get_card_count()} cards)")
        self._refresh_card_tree()

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

    # ---- 3-step flow ---------------------------------------------------

    def _reset_step(self):
        self._step = 0
        self._auth_btn.configure(state=tk.DISABLED)
        self._prog_btn.configure(state=tk.DISABLED)
        self._action_status.configure(
            text="Ready — insert card and detect", style="TLabel")

    def _on_detect(self):
        ok, msg = self._cm.detect_card()
        if ok:
            self._step = 1
            self._auth_btn.configure(state=tk.NORMAL)
            self._action_status.configure(text=msg, style="Success.TLabel")
        else:
            self._reset_step()
            self._action_status.configure(text=msg, style="Error.TLabel")

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
        else:
            self._action_status.configure(text=msg, style="Error.TLabel")
