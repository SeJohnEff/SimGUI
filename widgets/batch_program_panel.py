"""
Batch Program Panel — Workflow 3.

Program multiple SIM cards sequentially.
Data comes from a CSV or from an auto-generated IMSI/ICCID sequence.
"""

import csv
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from managers.batch_manager import BatchManager, BatchState, CardResult
from managers.card_manager import CardManager
from managers.csv_manager import SIM_DATA_FILETYPES, CSVManager
from managers.settings_manager import SettingsManager
from theme import ModernTheme
from utils import get_browse_initial_dir
from utils.iccid_utils import (
    FPLMN_BY_COUNTRY,
    ISSUER_IDS,
    SIM_TYPES,
    SITE_REGISTER,
    generate_iccid,
    generate_imsi,
    get_fplmn_for_site,
)
from widgets.tooltip import add_tooltip


def apply_imsi_override(cards: list[dict[str, str]], imsi_base: str,
                        start_seq: int = 1) -> list[dict[str, str]]:
    """Return copies of *cards* with IMSI replaced by base + 5-digit seq.

    Args:
        cards: List of card data dicts.
        imsi_base: First 10 digits of the IMSI (MCC+MNC + SSSS + T).
        start_seq: Sequence number for the first card (default 1).

    Returns:
        New list of card dicts — ICCID and all other fields are untouched.
    """
    result: list[dict[str, str]] = []
    for i, card in enumerate(cards):
        new_card = dict(card)
        new_card["IMSI"] = f"{imsi_base}{(start_seq + i):05d}"
        result.append(new_card)
    return result


def apply_range_filter(cards: list[dict[str, str]], start: int,
                       count: int) -> list[dict[str, str]]:
    """Return a slice of *cards* using 1-based *start* and *count*.

    Args:
        cards: Full list of card data dicts.
        start: 1-based start row.
        count: Number of cards to include.

    Returns:
        Sublist (shallow copies of dicts).
    """
    idx = max(start - 1, 0)
    return [dict(c) for c in cards[idx:idx + count]]


class BatchProgramPanel(ttk.Frame):
    """Tab for batch-programming multiple SIM cards."""

    def __init__(self, parent, card_manager: CardManager,
                 settings: SettingsManager, *,
                 ns_manager=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._cm = card_manager
        self._settings = settings
        self._ns_manager = ns_manager
        self._last_browse_dir: str | None = None
        self._batch_mgr = BatchManager(card_manager)
        self._csv = CSVManager()
        self._all_csv_cards: list[dict[str, str]] = []  # all rows from CSV
        self._preview_data: list[dict[str, str]] = []

        self._source_var = tk.StringVar(value="generate")
        self._standards_mgr = None  # Set by main.py via set_standards_manager()

        # Callback set by main.py for cross-tab sync
        self.on_csv_loaded_callback = None
        self.on_file_browsed_callback = None  # Called after file browse dialog closes

        # Wire callbacks
        self._batch_mgr.on_progress = self._on_progress
        self._batch_mgr.on_card_result = self._on_card_result
        self._batch_mgr.on_waiting_for_card = self._on_waiting_for_card
        self._batch_mgr.on_completed = self._on_batch_completed

        self._build_ui()
        self._load_settings()
        self._on_source_change()

    # ---- UI construction -----------------------------------------------

    def _build_ui(self):
        pad = ModernTheme.get_padding("medium")

        # Source toggle
        src_row = ttk.Frame(self)
        src_row.pack(fill=tk.X, padx=pad, pady=(pad, pad // 2))
        ttk.Label(src_row, text="Data Source:").pack(side=tk.LEFT)
        ttk.Radiobutton(src_row, text="Load CSV", variable=self._source_var,
                        value="csv", command=self._on_source_change
                        ).pack(side=tk.LEFT, padx=(pad, 0))
        ttk.Radiobutton(src_row, text="Generate Sequence",
                        variable=self._source_var, value="generate",
                        command=self._on_source_change
                        ).pack(side=tk.LEFT, padx=(pad, 0))

        # ---------- CSV section ----------
        self._csv_section = ttk.LabelFrame(self, text="CSV File")
        csv_bar = ttk.Frame(self._csv_section)
        csv_bar.pack(fill=tk.X, padx=pad, pady=(pad, 0))
        self._csv_path_var = tk.StringVar()
        ttk.Entry(csv_bar, textvariable=self._csv_path_var,
                  state="readonly", width=40).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        _browse_csv_btn = ttk.Button(csv_bar, text="Browse...",
                   command=self._on_browse_csv)
        _browse_csv_btn.pack(side=tk.LEFT, padx=(pad, 0))
        add_tooltip(_browse_csv_btn, "Open a CSV or EML file with SIM card data")
        self._csv_count_lbl = ttk.Label(csv_bar, text="")
        self._csv_count_lbl.pack(side=tk.LEFT, padx=(pad, 0))

        # Filename label
        self._csv_filename_lbl = ttk.Label(self._csv_section, text="",
                                           style="Small.TLabel")
        self._csv_filename_lbl.pack(anchor=tk.W, padx=pad, pady=(2, 0))

        # -- Range selection row --
        range_row = ttk.Frame(self._csv_section)
        range_row.pack(fill=tk.X, padx=pad, pady=(pad // 2, 0))
        ttk.Label(range_row, text="Start Row:").pack(side=tk.LEFT)
        self._range_start_var = tk.StringVar(value="1")
        self._range_start_spin = ttk.Spinbox(
            range_row, textvariable=self._range_start_var,
            from_=1, to=9999, width=6, command=self._on_range_change)
        self._range_start_spin.pack(side=tk.LEFT, padx=(4, pad))
        self._range_start_spin.bind("<Return>", lambda e: self._on_range_change())
        add_tooltip(self._range_start_spin,
                    "1-based row to start from in the CSV.\n"
                    "Example: 5 = start from the 5th card.")

        ttk.Label(range_row, text="Count:").pack(side=tk.LEFT)
        self._range_count_var = tk.StringVar(value="0")
        self._range_count_spin = ttk.Spinbox(
            range_row, textvariable=self._range_count_var,
            from_=0, to=9999, width=6, command=self._on_range_change)
        self._range_count_spin.pack(side=tk.LEFT, padx=(4, pad))
        self._range_count_spin.bind("<Return>", lambda e: self._on_range_change())
        add_tooltip(self._range_count_spin,
                    "Number of cards to program.\n"
                    "0 = all remaining cards from start row.")

        self._range_info_lbl = ttk.Label(range_row, text="")
        self._range_info_lbl.pack(side=tk.LEFT, padx=(pad, 0))

        # -- IMSI Override row --
        imsi_row = ttk.Frame(self._csv_section)
        imsi_row.pack(fill=tk.X, padx=pad, pady=(pad // 2, pad))
        self._imsi_override_var = tk.BooleanVar(value=False)
        self._imsi_override_chk = ttk.Checkbutton(
            imsi_row, text="Override IMSI base:",
            variable=self._imsi_override_var,
            command=self._on_range_change)
        self._imsi_override_chk.pack(side=tk.LEFT)
        add_tooltip(self._imsi_override_chk,
                    "Replace the IMSI for each card with a custom base\n"
                    "+ 5-digit sequence number (00001, 00002, 00003...).\n"
                    "ICCID is never modified.")
        self._imsi_base_var = tk.StringVar()
        self._imsi_base_entry = ttk.Entry(
            imsi_row, textvariable=self._imsi_base_var, width=16)
        self._imsi_base_entry.pack(side=tk.LEFT, padx=(4, pad))
        self._imsi_base_entry.bind("<Return>", lambda e: self._on_range_change())
        add_tooltip(self._imsi_base_entry,
                    "First 10 digits of the IMSI.\n"
                    "The last 5 digits (sequence) are auto-generated.\n"
                    "Example: 9998800010")
        ttk.Button(imsi_row, text="Apply",
                   command=self._on_range_change).pack(side=tk.LEFT)

        # ---------- Generate Sequence section ----------
        self._gen_section = ttk.LabelFrame(self, text="Batch Template")

        _FIELD_TOOLTIPS = {
            "mcc_mnc": "Mobile Country Code + Mobile Network Code.\nExample: 99988 (MCC=999, MNC=88)",
            "site": (
                "Site from the Teleaura Site Register.\n"
                "Select from dropdown or type a 4-digit site ID.\n"
                "Example: 0001 = uk1, 0002 = se1"
            ),
            "sim_type": (
                "SIM type digit.\n"
                "Select from dropdown or type a digit (0-9).\n"
                "0=USIM, 1=USIM+SUCI, 2=eSIM, 9=Test/Dev"
            ),
            "start": "First SIM sequence number (0-99999).\nExample: 1 \u2192 SIM 00001",
            "count": "Number of SIMs to generate (max 100000).\nExample: 20 \u2192 SIMs 00001 to 00020",
            "spn": (
                "Service Provider Name (EF_SPN 6F46).\n"
                "Select from standards list or type a custom value.\n"
                "Values loaded from standards.json on the network share."
            ),
            "li": (
                "Language Indicator (EF_LI 6F05).\n"
                "ISO 639-1 code — e.g. EN (English), SV (Swedish).\n"
                "Values loaded from standards.json on the network share."
            ),
            "fplmn": "Forbidden PLMNs, semicolon-separated.\nAuto-populated from site's country, editable.\nExample: 24007;24024;24001;24008;24002",
        }

        self._gen_vars: dict[str, tk.StringVar] = {}
        inner = ttk.Frame(self._gen_section)
        inner.pack(fill=tk.X, padx=pad, pady=pad)

        row_idx = 0

        # MCC+MNC entry
        lbl = ttk.Label(inner, text="MCC+MNC:")
        lbl.grid(row=row_idx, column=0, sticky=tk.W, padx=(0, pad), pady=2)
        var = tk.StringVar()
        entry = ttk.Entry(inner, textvariable=var, width=10)
        entry.grid(row=row_idx, column=1, sticky=tk.W, pady=2)
        self._gen_vars["mcc_mnc"] = var
        add_tooltip(lbl, _FIELD_TOOLTIPS["mcc_mnc"])
        add_tooltip(entry, _FIELD_TOOLTIPS["mcc_mnc"])
        row_idx += 1

        # Site combobox
        lbl = ttk.Label(inner, text="Site:")
        lbl.grid(row=row_idx, column=0, sticky=tk.W, padx=(0, pad), pady=2)
        site_values = [
            f"{sid} — {info['code']} ({info['country']})"
            for sid, info in SITE_REGISTER.items()
        ]
        self._site_var = tk.StringVar()
        self._site_combo = ttk.Combobox(
            inner, textvariable=self._site_var,
            values=site_values, width=30)
        self._site_combo.grid(row=row_idx, column=1, sticky=tk.W, pady=2)
        self._gen_vars["site"] = self._site_var
        self._site_combo.bind("<<ComboboxSelected>>", self._on_site_change)
        self._site_combo.bind("<FocusOut>", self._on_site_change)
        add_tooltip(lbl, _FIELD_TOOLTIPS["site"])
        add_tooltip(self._site_combo, _FIELD_TOOLTIPS["site"])
        row_idx += 1

        # SIM Type combobox
        lbl = ttk.Label(inner, text="SIM Type:")
        lbl.grid(row=row_idx, column=0, sticky=tk.W, padx=(0, pad), pady=2)
        sim_type_values = [
            f"{k} — {v}" for k, v in SIM_TYPES.items()
        ]
        self._sim_type_var = tk.StringVar()
        self._sim_type_combo = ttk.Combobox(
            inner, textvariable=self._sim_type_var,
            values=sim_type_values, width=20)
        self._sim_type_combo.grid(row=row_idx, column=1, sticky=tk.W, pady=2)
        self._gen_vars["sim_type"] = self._sim_type_var
        add_tooltip(lbl, _FIELD_TOOLTIPS["sim_type"])
        add_tooltip(self._sim_type_combo, _FIELD_TOOLTIPS["sim_type"])
        row_idx += 1

        # Start Sequence spinbox
        lbl = ttk.Label(inner, text="Start Sequence:")
        lbl.grid(row=row_idx, column=0, sticky=tk.W, padx=(0, pad), pady=2)
        var = tk.StringVar(value="1")
        spinbox = ttk.Spinbox(inner, textvariable=var, from_=0, to=99999, width=8)
        spinbox.grid(row=row_idx, column=1, sticky=tk.W, pady=2)
        self._gen_vars["start"] = var
        add_tooltip(lbl, _FIELD_TOOLTIPS["start"])
        add_tooltip(spinbox, _FIELD_TOOLTIPS["start"])
        row_idx += 1

        # Count spinbox
        lbl = ttk.Label(inner, text="Count:")
        lbl.grid(row=row_idx, column=0, sticky=tk.W, padx=(0, pad), pady=2)
        var = tk.StringVar(value="20")
        spinbox = ttk.Spinbox(inner, textvariable=var, from_=1, to=100000, width=8)
        spinbox.grid(row=row_idx, column=1, sticky=tk.W, pady=2)
        self._gen_vars["count"] = var
        add_tooltip(lbl, _FIELD_TOOLTIPS["count"])
        add_tooltip(spinbox, _FIELD_TOOLTIPS["count"])
        row_idx += 1

        # SPN combobox (validated against standards.json)
        lbl = ttk.Label(inner, text="SPN:")
        lbl.grid(row=row_idx, column=0, sticky=tk.W, padx=(0, pad), pady=2)
        self._spn_var = tk.StringVar()
        self._spn_combo = ttk.Combobox(
            inner, textvariable=self._spn_var, width=20)
        self._spn_combo.grid(row=row_idx, column=1, sticky=tk.W, pady=2)
        self._gen_vars["spn"] = self._spn_var
        add_tooltip(lbl, _FIELD_TOOLTIPS["spn"])
        add_tooltip(self._spn_combo, _FIELD_TOOLTIPS["spn"])
        row_idx += 1

        # LI (Language Indicator) combobox (validated against standards.json)
        lbl = ttk.Label(inner, text="LI (Language):")
        lbl.grid(row=row_idx, column=0, sticky=tk.W, padx=(0, pad), pady=2)
        self._li_var = tk.StringVar(value="EN")
        self._li_combo = ttk.Combobox(
            inner, textvariable=self._li_var, width=6)
        self._li_combo.grid(row=row_idx, column=1, sticky=tk.W, pady=2)
        self._gen_vars["li"] = self._li_var
        add_tooltip(lbl, _FIELD_TOOLTIPS["li"])
        add_tooltip(self._li_combo, _FIELD_TOOLTIPS["li"])
        row_idx += 1

        # FPLMN entry
        lbl = ttk.Label(inner, text="FPLMN:")
        lbl.grid(row=row_idx, column=0, sticky=tk.W, padx=(0, pad), pady=2)
        var = tk.StringVar()
        entry = ttk.Entry(inner, textvariable=var, width=40)
        entry.grid(row=row_idx, column=1, sticky=tk.W, pady=2)
        self._gen_vars["fplmn"] = var
        add_tooltip(lbl, _FIELD_TOOLTIPS["fplmn"])
        add_tooltip(entry, _FIELD_TOOLTIPS["fplmn"])

        # ADM1 note — ADM1 comes from the loaded data file (auto-read)
        adm_note = ttk.Label(
            self._gen_section,
            text="ADM1 comes from the data file loaded during auto-read.",
            style="Small.TLabel")
        adm_note.pack(anchor=tk.W, padx=pad, pady=(0, pad))
        add_tooltip(adm_note,
                    "ADM1 key is per-card and sourced from the vendor data "
                    "file (.eml / .csv / .txt).\n"
                    "\u26a0 3 wrong attempts = permanent lock!")

        # Preview button
        ttk.Button(self._gen_section, text="Preview Batch",
                   command=self._on_preview).pack(anchor=tk.W, padx=pad, pady=(0, pad))

        # ---------- Preview table ----------
        self._preview_frame = ttk.LabelFrame(self, text="Batch Preview")
        self._preview_tree = ttk.Treeview(
            self._preview_frame,
            columns=("imsi", "iccid", "site_code", "spn", "adm1"),
            show="headings", height=8)
        self._preview_tree.heading("imsi", text="IMSI")
        self._preview_tree.heading("iccid", text="ICCID")
        self._preview_tree.heading("site_code", text="Site Code")
        self._preview_tree.heading("spn", text="SPN")
        self._preview_tree.heading("adm1", text="ADM1")
        self._preview_tree.column("imsi", width=140)
        self._preview_tree.column("iccid", width=180)
        self._preview_tree.column("site_code", width=70)
        self._preview_tree.column("spn", width=80)
        self._preview_tree.column("adm1", width=90)
        sb = ttk.Scrollbar(self._preview_frame, orient=tk.VERTICAL,
                           command=self._preview_tree.yview)
        self._preview_tree.configure(yscrollcommand=sb.set)
        self._preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                padx=(pad, 0), pady=pad)
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, pad), pady=pad)

        # ---------- Execution section ----------
        self._exec_frame = ttk.LabelFrame(self, text="Batch Execution")
        exec_inner = ttk.Frame(self._exec_frame)
        exec_inner.pack(fill=tk.X, padx=pad, pady=pad)

        self._start_btn = ttk.Button(
            exec_inner, text="Start Batch", style="Accent.TButton",
            command=self._on_start)
        self._start_btn.pack(side=tk.LEFT, padx=(0, pad))
        add_tooltip(self._start_btn, "Begin programming all selected cards sequentially")
        self._pause_btn = ttk.Button(
            exec_inner, text="Pause", command=self._on_pause, state=tk.DISABLED)
        self._pause_btn.pack(side=tk.LEFT, padx=(0, pad))
        add_tooltip(self._pause_btn, "Pause or resume the current batch operation")
        self._skip_btn = ttk.Button(
            exec_inner, text="Skip Card", command=self._on_skip, state=tk.DISABLED)
        self._skip_btn.pack(side=tk.LEFT, padx=(0, pad))
        add_tooltip(self._skip_btn, "Skip the current card and continue with the next")
        self._abort_btn = ttk.Button(
            exec_inner, text="Abort Batch", command=self._on_abort, state=tk.DISABLED)
        self._abort_btn.pack(side=tk.LEFT)
        add_tooltip(self._abort_btn, "Cancel the current batch operation")

        # Progress bar
        self._progress_bar = ttk.Progressbar(
            self._exec_frame, orient=tk.HORIZONTAL, mode="determinate")
        self._progress_bar.pack(fill=tk.X, padx=pad, pady=(0, pad // 2))
        self._progress_lbl = ttk.Label(self._exec_frame, text="Idle")
        self._progress_lbl.pack(anchor=tk.W, padx=pad)

        # Card-ready button (for hardware mode prompts)
        self._card_ready_btn = ttk.Button(
            self._exec_frame, text="Card Inserted — Continue",
            command=self._on_card_ready, state=tk.DISABLED)
        self._card_ready_btn.pack(anchor=tk.W, padx=pad, pady=pad // 2)

        # Log
        self._log_text = tk.Text(
            self._exec_frame, height=8, state=tk.DISABLED, wrap=tk.WORD)
        log_sb = ttk.Scrollbar(self._exec_frame, orient=tk.VERTICAL,
                               command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                            padx=(pad, 0), pady=(0, pad))
        log_sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, pad), pady=(0, pad))

        # Summary / export (shown after completion)
        self._summary_frame = ttk.Frame(self)
        self._summary_lbl = ttk.Label(self._summary_frame, text="")
        self._summary_lbl.pack(side=tk.LEFT, padx=(0, pad))
        ttk.Button(self._summary_frame, text="Export Results CSV...",
                   command=self._on_export_results).pack(side=tk.LEFT)

    # ---- site change auto-population ------------------------------------

    def _on_site_change(self, *_args):
        """Auto-populate FPLMN when site selection changes."""
        selected = self._site_var.get()
        if not selected:
            return
        site_id = selected.split()[0]  # e.g. "0001"
        fplmn = get_fplmn_for_site(site_id)
        if fplmn:
            self._gen_vars["fplmn"].set(fplmn)

    # ---- standards management -------------------------------------------

    def set_standards_manager(self, mgr) -> None:
        """Inject the :class:`StandardsManager` (called by main.py)."""
        self._standards_mgr = mgr
        self.refresh_standards()

    def refresh_standards(self) -> None:
        """Refresh SPN / LI combobox values from the standards manager."""
        mgr = self._standards_mgr
        if mgr and mgr.has_standards:
            self._spn_combo["values"] = mgr.spn_values
            self._li_combo["values"] = mgr.li_values
        else:
            self._spn_combo["values"] = []
            self._li_combo["values"] = []

    def _validate_standards_field(self, value: str, field_name: str) -> bool:
        """Check *value* against the standards file for *field_name*.

        If the value is not in the canonical list and a standards file is
        loaded, asks the user to confirm.  Returns True to proceed.
        """
        mgr = self._standards_mgr
        if not mgr or not mgr.has_standards:
            return True  # No standards loaded — allow anything

        if field_name == "spn":
            if mgr.is_valid_spn(value):
                return True
            suggestion = mgr.suggest_spn(value)
        elif field_name == "li":
            if mgr.is_valid_li(value):
                return True
            suggestion = mgr.suggest_li(value)
        else:
            return True

        # Build confirmation message
        label = "SPN" if field_name == "spn" else "LI"
        msg = (f'"{value}" is not in the standards file.\n\n')
        if suggestion:
            msg += (f'Did you mean "{suggestion}"?\n'
                    f'Click No to use the canonical value, '
                    f'or Yes to use "{value}" as-is.')
            answer = messagebox.askyesno(
                f"Non-standard {label}", msg, icon="warning")
            if not answer:
                # Auto-correct to canonical form
                if field_name == "spn":
                    self._spn_var.set(suggestion)
                elif field_name == "li":
                    self._li_var.set(suggestion)
                return True  # proceed with corrected value
            return True  # user chose to keep their value

        msg += (f'The standards file contains: '
                f'{", ".join(mgr.spn_values if field_name == "spn" else mgr.li_values)}\n\n'
                f'Use "{value}" anyway?')
        return messagebox.askyesno(
            f"Non-standard {label}", msg, icon="warning")

    # ---- source toggle --------------------------------------------------

    def _on_source_change(self):
        pad = ModernTheme.get_padding("medium")
        is_csv = self._source_var.get() == "csv"
        # Unpack ALL dynamic sections first to guarantee correct ordering
        self._csv_section.pack_forget()
        self._gen_section.pack_forget()
        self._preview_frame.pack_forget()
        self._exec_frame.pack_forget()
        self._summary_frame.pack_forget()
        # Re-pack in the correct visual order
        if is_csv:
            self._csv_section.pack(fill=tk.X, padx=pad, pady=pad // 2)
        else:
            self._gen_section.pack(fill=tk.X, padx=pad, pady=pad // 2)
        self._preview_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad // 2)
        self._exec_frame.pack(fill=tk.X, padx=pad, pady=pad // 2)

    # ---- CSV loading ---------------------------------------------------

    def _on_browse_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        kwargs = {"title": "Open SIM Data File", "filetypes": SIM_DATA_FILETYPES}
        if init_dir:
            kwargs["initialdir"] = init_dir
        path = filedialog.askopenfilename(**kwargs)
        # Notify main.py that a file dialog has closed
        if callable(self.on_file_browsed_callback):
            self.on_file_browsed_callback()
        if not path:
            return
        import os
        self._last_browse_dir = os.path.dirname(path)
        self.load_csv_file(path)

    def load_csv_file(self, path: str, *, _from_sync: bool = False) -> bool:
        """Load a CSV or EML file and refresh the preview.

        Called by Browse button or by cross-tab sync from ProgramSIMPanel.
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
        n = self._csv.get_card_count()
        self._csv_count_lbl.configure(text=f"({n} cards)")
        # Store all cards and reset range
        self._all_csv_cards = []
        for i in range(n):
            card = self._csv.get_card(i)
            if card:
                self._all_csv_cards.append(dict(card))
        self._range_start_var.set("1")
        self._range_count_var.set("0")
        self._apply_csv_filters()
        # Cross-tab sync
        if not _from_sync and callable(self.on_csv_loaded_callback):
            self.on_csv_loaded_callback(path)
        return True

    def _on_range_change(self):
        """Called when start row, count, or IMSI override changes."""
        self._apply_csv_filters()

    def _apply_csv_filters(self):
        """Rebuild _preview_data from _all_csv_cards with range + IMSI override."""
        if not self._all_csv_cards:
            self._preview_data = []
            self._range_info_lbl.configure(text="")
            self._refresh_preview()
            return

        total = len(self._all_csv_cards)

        # Parse range
        try:
            start = max(1, int(self._range_start_var.get()))
        except ValueError:
            start = 1
        try:
            count = max(0, int(self._range_count_var.get()))
        except ValueError:
            count = 0
        if count == 0:
            count = total - (start - 1)

        # Apply range filter
        filtered = apply_range_filter(self._all_csv_cards, start, count)

        # Apply IMSI override if enabled
        if self._imsi_override_var.get():
            base = self._imsi_base_var.get().strip()
            if len(base) == 10 and base.isdigit():
                filtered = apply_imsi_override(filtered, base, start_seq=start)

        self._preview_data = filtered
        actual = len(filtered)
        end_row = start + actual - 1 if actual else start
        self._range_info_lbl.configure(
            text=f"Rows {start}–{end_row} of {total} ({actual} cards)")
        self._refresh_preview()

    # ---- preview -------------------------------------------------------

    def _on_preview(self):
        try:
            mcc_mnc = self._gen_vars["mcc_mnc"].get().strip()
            start = int(self._gen_vars["start"].get().strip())
            count = int(self._gen_vars["count"].get().strip())
            spn = self._gen_vars["spn"].get().strip()
            li = self._gen_vars["li"].get().strip()
            fplmn = self._gen_vars["fplmn"].get().strip()
        except ValueError:
            messagebox.showerror("Error", "Start and Count must be integers")
            return

        # Extract site_id from combo selection
        site_sel = self._site_var.get()
        if not site_sel:
            messagebox.showerror("Error", "Please select a Site")
            return
        site_id = site_sel.split()[0]

        # Extract sim_type from combo selection
        sim_type_sel = self._sim_type_var.get()
        if not sim_type_sel:
            messagebox.showerror("Error", "Please select a SIM Type")
            return
        sim_type = sim_type_sel.split()[0]

        if not mcc_mnc:
            messagebox.showerror("Error", "MCC+MNC is required")
            return

        # Validate SPN and LI against standards file
        if spn and not self._validate_standards_field(spn, "spn"):
            return
        # Re-read SPN in case it was auto-corrected by the validator
        spn = self._gen_vars["spn"].get().strip()

        if li and not self._validate_standards_field(li, "li"):
            return
        li = self._gen_vars["li"].get().strip()

        # Resolve site code for display
        site_info = SITE_REGISTER.get(site_id, {})
        site_code = site_info.get("code", "")

        self._preview_data = []
        for seq in range(start, start + count):
            imsi = generate_imsi(mcc_mnc, site_id, sim_type, seq)
            # v2.1: ICCID uses E.164 country code + issuer ID
            cc_e164 = site_info.get("country_code_e164", "00")
            issuer_id = ISSUER_IDS.get(mcc_mnc, "988")
            iccid = generate_iccid(cc_e164, issuer_id, site_id, sim_type, seq)
            self._preview_data.append({
                "IMSI": imsi,
                "ICCID": iccid,
                "SITE_CODE": site_code,
                "SPN": spn,
                "FPLMN": fplmn,
                "ADM1": "",  # Comes from data file during auto-read
                "ACC": "0001",
                "LI": li,
            })
        self._refresh_preview()
        self._save_settings()

    def _refresh_preview(self):
        self._preview_tree.delete(*self._preview_tree.get_children())
        for i, row in enumerate(self._preview_data):
            self._preview_tree.insert("", tk.END, iid=str(i), values=(
                row.get("IMSI", ""),
                row.get("ICCID", ""),
                row.get("SITE_CODE", ""),
                row.get("SPN", ""),
                row.get("ADM1", ""),
            ))

    # ---- batch execution -----------------------------------------------

    def _on_start(self):
        if not self._preview_data:
            is_csv = self._source_var.get() == "csv"
            if is_csv and not self._csv_path_var.get():
                msg = "Load a CSV file first using Browse."
            elif is_csv:
                msg = "The loaded CSV file has no cards."
            else:
                msg = "Preview the batch first."
            messagebox.showinfo("Nothing to do", msg)
            return

        # Check for duplicate artifacts on connected network shares
        if not self._check_duplicate_artifacts():
            return  # user cancelled

        self._log_clear()
        self._start_btn.configure(state=tk.DISABLED)
        self._pause_btn.configure(state=tk.NORMAL)
        self._skip_btn.configure(state=tk.NORMAL)
        self._abort_btn.configure(state=tk.NORMAL)
        self._summary_frame.pack_forget()
        self._batch_mgr.start(self._preview_data)

    def _check_duplicate_artifacts(self) -> bool:
        """Warn if any batch ICCIDs already have artifacts on a share.

        Returns True to proceed, False to cancel.
        """
        if not self._ns_manager:
            return True

        iccids = [c.get("ICCID", "") for c in self._preview_data
                  if c.get("ICCID")]
        if not iccids:
            return True

        profiles = self._ns_manager.load_profiles()
        all_dupes: list[tuple[str, list[str]]] = []  # (share_label, iccids)

        for prof in profiles:
            if not self._ns_manager.is_mounted(prof):
                continue
            dupes = self._ns_manager.find_duplicate_iccids(prof, iccids)
            if dupes:
                all_dupes.append((prof.label, dupes))

        if not all_dupes:
            return True

        # Build warning message
        lines = []
        total = 0
        for label, dupes in all_dupes:
            total += len(dupes)
            lines.append(f"  {label}: {len(dupes)} card(s)")
            # Show first few ICCIDs
            for d in dupes[:3]:
                lines.append(f"    - {d}")
            if len(dupes) > 3:
                lines.append(f"    ... and {len(dupes) - 3} more")

        msg = (f"{total} card(s) in this batch already have artifacts "
               f"on the network share:\n\n" +
               "\n".join(lines) +
               "\n\nProgramming again may create duplicates.\n"
               "Continue anyway?")

        return messagebox.askyesno("Duplicate Artifacts Found", msg)

    def _on_pause(self):
        if self._batch_mgr.state == BatchState.PAUSED:
            self._batch_mgr.resume()
            self._pause_btn.configure(text="Pause")
        else:
            self._batch_mgr.pause()
            self._pause_btn.configure(text="Resume")

    def _on_skip(self):
        self._batch_mgr.skip()

    def _on_abort(self):
        self._batch_mgr.abort()

    def _on_card_ready(self):
        self._batch_mgr.card_ready()
        self._card_ready_btn.configure(state=tk.DISABLED)

    # ---- batch callbacks (called from worker thread) -------------------

    def _on_progress(self, current: int, total: int, msg: str):
        def _do():
            if not self.winfo_exists():
                return
            self._progress_bar["maximum"] = total
            self._progress_bar["value"] = current
            self._progress_lbl.configure(
                text=f"Card {current + 1} of {total} — {msg}")
        self.after(0, _do)

    def _on_card_result(self, result: CardResult):
        def _do():
            if not self.winfo_exists():
                return
            icon = "OK" if result.success else "FAIL"
            self._log(f"Card {result.index + 1} [{icon}]: {result.message}")
        self.after(0, _do)

    def _on_waiting_for_card(self, index: int, iccid: str):
        def _do():
            if not self.winfo_exists():
                return
            self._progress_lbl.configure(
                text=f"Insert card #{index + 1} (expected ICCID: {iccid})")
            self._card_ready_btn.configure(state=tk.NORMAL)
        self.after(0, _do)

    def _on_batch_completed(self):
        def _do():
            if not self.winfo_exists():
                return
            s = self._batch_mgr.success_count
            f = self._batch_mgr.fail_count
            t = self._batch_mgr.total
            self._progress_bar["value"] = t
            self._progress_lbl.configure(text="Batch complete")
            self._log(f"Batch finished: {s}/{t} successful, {f} failed")
            self._start_btn.configure(state=tk.NORMAL)
            self._pause_btn.configure(state=tk.DISABLED, text="Pause")
            self._skip_btn.configure(state=tk.DISABLED)
            self._abort_btn.configure(state=tk.DISABLED)
            self._card_ready_btn.configure(state=tk.DISABLED)
            self._summary_lbl.configure(
                text=f"Result: {s}/{t} successful, {f} failed")
            pad = ModernTheme.get_padding("medium")
            self._summary_frame.pack(fill=tk.X, padx=pad, pady=(0, pad))
        self.after(0, _do)

    # ---- log helpers ---------------------------------------------------

    def _log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] {message}\n")
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _log_clear(self):
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state=tk.DISABLED)

    # ---- export --------------------------------------------------------

    def _on_export_results(self):
        if not self._batch_mgr.results:
            return
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        kwargs = {
            "title": "Export Results", "defaultextension": ".csv",
            "filetypes": [("CSV files", "*.csv"), ("All files", "*.*")],
        }
        if init_dir:
            kwargs["initialdir"] = init_dir
        path = filedialog.asksaveasfilename(**kwargs)
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["#", "ICCID", "Result", "Message"])
                for r in self._batch_mgr.results:
                    writer.writerow([
                        r.index + 1, r.iccid,
                        "OK" if r.success else "FAIL", r.message])
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    # ---- public API (used by main.py for artifact export) ---------------

    def get_programmed_records(self) -> list[dict[str, str]]:
        """Return card data dicts for successfully programmed cards.

        Matches batch results (by index) back to the preview data that
        was sent for programming.  Only returns cards that succeeded.
        """
        if not self._batch_mgr.results or not self._preview_data:
            return []
        ok_indices = {r.index for r in self._batch_mgr.results if r.success}
        return [self._preview_data[i] for i in sorted(ok_indices)
                if i < len(self._preview_data)]

    # ---- settings persistence ------------------------------------------

    def _load_settings(self):
        # MCC+MNC
        val = self._settings.get("last_mcc_mnc", "")
        if val:
            self._gen_vars["mcc_mnc"].set(str(val))

        # Site — match by site_id prefix
        last_site = self._settings.get("last_site", "")
        if last_site:
            for i, (sid, info) in enumerate(SITE_REGISTER.items()):
                if sid == last_site:
                    self._site_combo.current(i)
                    break

        # SIM Type — match by type digit prefix
        last_sim_type = self._settings.get("last_sim_type", "")
        if last_sim_type:
            sim_type_keys = list(SIM_TYPES.keys())
            if last_sim_type in sim_type_keys:
                self._sim_type_combo.current(sim_type_keys.index(last_sim_type))

        # SPN, LI, FPLMN
        for key, skey, fallback_skey in [
            ("spn", "last_spn", None),
            ("li", "last_li", "last_language"),  # migrate from old key
            ("fplmn", "last_fplmn", None),
        ]:
            val = self._settings.get(skey, "")
            if not val and fallback_skey:
                val = self._settings.get(fallback_skey, "")
            if val and key in self._gen_vars:
                self._gen_vars[key].set(str(val))

        batch_size = self._settings.get("last_batch_size", 20)
        if batch_size:
            self._gen_vars["count"].set(str(batch_size))

    def _save_settings(self):
        self._settings.set("last_mcc_mnc", self._gen_vars["mcc_mnc"].get().strip())

        # Save site_id (first token from combo)
        site_sel = self._site_var.get()
        if site_sel:
            self._settings.set("last_site", site_sel.split()[0])

        # Save sim_type digit (first token from combo)
        sim_type_sel = self._sim_type_var.get()
        if sim_type_sel:
            self._settings.set("last_sim_type", sim_type_sel.split()[0])

        for key, skey in [
            ("spn", "last_spn"),
            ("li", "last_li"),
            ("fplmn", "last_fplmn"),
        ]:
            self._settings.set(skey, self._gen_vars[key].get().strip())
        try:
            self._settings.set(
                "last_batch_size", int(self._gen_vars["count"].get().strip()))
        except ValueError:
            pass
