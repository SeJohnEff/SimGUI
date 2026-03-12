"""
Batch Program Panel — Workflow 3.

Program multiple SIM cards sequentially.
Data comes from a CSV or from an auto-generated IMSI/ICCID sequence.
"""

import csv
import tkinter as tk
from datetime import datetime
from tkinter import ttk, filedialog, messagebox

from managers.batch_manager import BatchManager, BatchState, CardResult
from managers.card_manager import CardManager
from managers.csv_manager import CSVManager
from managers.settings_manager import SettingsManager
from theme import ModernTheme
from utils.iccid_utils import generate_iccid, generate_imsi
from widgets.tooltip import add_tooltip


class BatchProgramPanel(ttk.Frame):
    """Tab for batch-programming multiple SIM cards."""

    def __init__(self, parent, card_manager: CardManager,
                 settings: SettingsManager, **kwargs):
        super().__init__(parent, **kwargs)
        self._cm = card_manager
        self._settings = settings
        self._batch_mgr = BatchManager(card_manager)
        self._csv = CSVManager()
        self._preview_data: list[dict[str, str]] = []

        self._source_var = tk.StringVar(value="generate")
        self._adm1_source_var = tk.StringVar(value="csv")

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
        csv_bar.pack(fill=tk.X, padx=pad, pady=pad)
        self._csv_path_var = tk.StringVar()
        ttk.Entry(csv_bar, textvariable=self._csv_path_var,
                  state="readonly", width=40).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(csv_bar, text="Browse...",
                   command=self._on_browse_csv).pack(side=tk.LEFT, padx=(pad, 0))
        self._csv_count_lbl = ttk.Label(csv_bar, text="")
        self._csv_count_lbl.pack(side=tk.LEFT, padx=(pad, 0))

        # ---------- Generate Sequence section ----------
        self._gen_section = ttk.LabelFrame(self, text="Batch Template")

        _FIELD_TOOLTIPS = {
            "mcc_mnc": "Mobile Country Code + Mobile Network Code.\nExample: 99988 (MCC=999, MNC=88)",
            "customer": "4-digit customer identifier.\nExample: 0003 (Boliden)",
            "sim_type": "4-digit SIM card type code.\nExample: 0100 (SYSMOCOM)",
            "start": "First sequence number in the batch.\nExample: 1 \u2192 sequence 001",
            "count": "Number of SIM cards to generate.\nExample: 20 \u2192 generates 001 to 020",
            "spn": "Service Provider Name stored on the SIM.\nExample: BOLIDEN",
            "language": "ISO 639-1 language code for the SIM.\nExample: EN (English), SV (Swedish)",
            "fplmn": "Forbidden PLMNs, semicolon-separated.\nExample: 24007;24024;24001;24008;24002",
        }

        fields = [
            ("mcc_mnc", "MCC+MNC:", "last_mcc_mnc", 10),
            ("customer", "Customer Code:", "last_customer_code", 10),
            ("sim_type", "SIM Type Code:", "last_sim_type_code", 10),
            ("start", "Start Number:", None, 6),
            ("count", "Count:", "last_batch_size", 6),
            ("spn", "SPN:", "last_spn", 20),
            ("language", "Language:", "last_language", 6),
            ("fplmn", "FPLMN:", "last_fplmn", 40),
        ]
        self._gen_vars: dict[str, tk.StringVar] = {}
        inner = ttk.Frame(self._gen_section)
        inner.pack(fill=tk.X, padx=pad, pady=pad)
        for i, (key, label, _, width) in enumerate(fields):
            lbl = ttk.Label(inner, text=label)
            lbl.grid(row=i, column=0, sticky=tk.W, padx=(0, pad), pady=2)
            var = tk.StringVar()
            entry = ttk.Entry(inner, textvariable=var, width=width)
            entry.grid(row=i, column=1, sticky=tk.W, pady=2)
            self._gen_vars[key] = var
            if key in _FIELD_TOOLTIPS:
                add_tooltip(lbl, _FIELD_TOOLTIPS[key])
                add_tooltip(entry, _FIELD_TOOLTIPS[key])
        self._gen_vars["start"].set("1")
        self._gen_vars["count"].set("20")

        # ADM1 source
        adm_row = ttk.Frame(self._gen_section)
        adm_row.pack(fill=tk.X, padx=pad, pady=(0, pad))
        adm1_lbl = ttk.Label(adm_row, text="ADM1 Source:")
        adm1_lbl.pack(side=tk.LEFT)
        add_tooltip(adm1_lbl,
                    "ADM1 key for card authentication.\n"
                    "'Same for all': one ADM1 for entire batch.\n"
                    "'From CSV file': per-card ADM1 from data file.\n"
                    "\u26a0 3 wrong attempts = permanent lock!")
        ttk.Radiobutton(adm_row, text="Same for all:", variable=self._adm1_source_var,
                        value="uniform").pack(side=tk.LEFT, padx=(pad, 0))
        self._uniform_adm1_var = tk.StringVar()
        self._uniform_adm1_entry = ttk.Entry(
            adm_row, textvariable=self._uniform_adm1_var, width=12)
        self._uniform_adm1_entry.pack(side=tk.LEFT, padx=(4, pad))
        ttk.Radiobutton(adm_row, text="From CSV file:",
                        variable=self._adm1_source_var, value="csv"
                        ).pack(side=tk.LEFT)
        self._adm_csv_path_var = tk.StringVar()
        ttk.Button(adm_row, text="Browse...",
                   command=self._on_browse_adm_csv).pack(side=tk.LEFT, padx=(pad, 0))

        # Preview button
        ttk.Button(self._gen_section, text="Preview Batch",
                   command=self._on_preview).pack(anchor=tk.W, padx=pad, pady=(0, pad))

        # ---------- Preview table ----------
        self._preview_frame = ttk.LabelFrame(self, text="Batch Preview")
        self._preview_tree = ttk.Treeview(
            self._preview_frame,
            columns=("imsi", "iccid", "spn", "adm1"),
            show="headings", height=8)
        self._preview_tree.heading("imsi", text="IMSI")
        self._preview_tree.heading("iccid", text="ICCID")
        self._preview_tree.heading("spn", text="SPN")
        self._preview_tree.heading("adm1", text="ADM1")
        self._preview_tree.column("imsi", width=140)
        self._preview_tree.column("iccid", width=180)
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
        self._pause_btn = ttk.Button(
            exec_inner, text="Pause", command=self._on_pause, state=tk.DISABLED)
        self._pause_btn.pack(side=tk.LEFT, padx=(0, pad))
        self._skip_btn = ttk.Button(
            exec_inner, text="Skip Card", command=self._on_skip, state=tk.DISABLED)
        self._skip_btn.pack(side=tk.LEFT, padx=(0, pad))
        self._abort_btn = ttk.Button(
            exec_inner, text="Abort Batch", command=self._on_abort, state=tk.DISABLED)
        self._abort_btn.pack(side=tk.LEFT)

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

    # ---- source toggle --------------------------------------------------

    def _on_source_change(self):
        pad = ModernTheme.get_padding("medium")
        is_csv = self._source_var.get() == "csv"
        if is_csv:
            self._gen_section.pack_forget()
            self._csv_section.pack(fill=tk.X, padx=pad, pady=pad // 2)
        else:
            self._csv_section.pack_forget()
            self._gen_section.pack(fill=tk.X, padx=pad, pady=pad // 2)
        self._preview_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad // 2)
        self._exec_frame.pack(fill=tk.X, padx=pad, pady=pad // 2)
        self._summary_frame.pack_forget()

    # ---- CSV loading ---------------------------------------------------

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
        self._preview_data = []
        for i in range(self._csv.get_card_count()):
            card = self._csv.get_card(i)
            if card:
                self._preview_data.append(dict(card))
        self._refresh_preview()

    def _on_browse_adm_csv(self):
        path = filedialog.askopenfilename(
            title="Select ADM1 CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self._adm_csv_path_var.set(path)

    # ---- preview -------------------------------------------------------

    def _on_preview(self):
        try:
            mcc_mnc = self._gen_vars["mcc_mnc"].get().strip()
            customer = self._gen_vars["customer"].get().strip()
            sim_type = self._gen_vars["sim_type"].get().strip()
            start = int(self._gen_vars["start"].get().strip())
            count = int(self._gen_vars["count"].get().strip())
            spn = self._gen_vars["spn"].get().strip()
            language = self._gen_vars["language"].get().strip()
            fplmn = self._gen_vars["fplmn"].get().strip()
        except ValueError:
            messagebox.showerror("Error", "Start and Count must be integers")
            return

        if not mcc_mnc or not customer or not sim_type:
            messagebox.showerror("Error",
                                 "MCC+MNC, Customer Code, and SIM Type Code are required")
            return

        # Load ADM1 from CSV if applicable
        adm1_map: dict[str, str] = {}
        uniform_adm1 = ""
        if self._adm1_source_var.get() == "uniform":
            uniform_adm1 = self._uniform_adm1_var.get().strip()
        elif self._adm_csv_path_var.get():
            adm1_map = self._load_adm1_csv(self._adm_csv_path_var.get())

        self._preview_data = []
        for seq in range(start, start + count):
            imsi = generate_imsi(mcc_mnc, customer, sim_type, seq)
            iccid = generate_iccid(mcc_mnc, customer, sim_type, seq)
            adm1 = uniform_adm1 or adm1_map.get(iccid, "")
            self._preview_data.append({
                "IMSI": imsi,
                "ICCID": iccid,
                "SPN": spn,
                "FPLMN": fplmn,
                "ADM1": adm1,
                "ACC": "0001",
                "LI": language,
            })
        self._refresh_preview()
        self._save_settings()

    def _refresh_preview(self):
        self._preview_tree.delete(*self._preview_tree.get_children())
        for i, row in enumerate(self._preview_data):
            self._preview_tree.insert("", tk.END, iid=str(i), values=(
                row.get("IMSI", ""),
                row.get("ICCID", ""),
                row.get("SPN", ""),
                row.get("ADM1", ""),
            ))

    @staticmethod
    def _load_adm1_csv(path: str) -> dict[str, str]:
        """Load a CSV and return {ICCID: ADM1} mapping."""
        mapping: dict[str, str] = {}
        try:
            with open(path, "r", newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    iccid = row.get("ICCID", "").strip()
                    adm1 = row.get("ADM1", "").strip()
                    if iccid and adm1:
                        mapping[iccid] = adm1
        except Exception:
            pass
        return mapping

    # ---- batch execution -----------------------------------------------

    def _on_start(self):
        if not self._preview_data:
            messagebox.showinfo("Nothing to do", "Preview the batch first.")
            return
        self._log_clear()
        self._start_btn.configure(state=tk.DISABLED)
        self._pause_btn.configure(state=tk.NORMAL)
        self._skip_btn.configure(state=tk.NORMAL)
        self._abort_btn.configure(state=tk.NORMAL)
        self._summary_frame.pack_forget()
        self._batch_mgr.start(self._preview_data)

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
        path = filedialog.asksaveasfilename(
            title="Export Results", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
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

    # ---- settings persistence ------------------------------------------

    def _load_settings(self):
        for key, skey in [
            ("mcc_mnc", "last_mcc_mnc"),
            ("customer", "last_customer_code"),
            ("sim_type", "last_sim_type_code"),
            ("spn", "last_spn"),
            ("language", "last_language"),
            ("fplmn", "last_fplmn"),
        ]:
            val = self._settings.get(skey, "")
            if val and key in self._gen_vars:
                self._gen_vars[key].set(str(val))
        batch_size = self._settings.get("last_batch_size", 20)
        if batch_size:
            self._gen_vars["count"].set(str(batch_size))

    def _save_settings(self):
        for key, skey in [
            ("mcc_mnc", "last_mcc_mnc"),
            ("customer", "last_customer_code"),
            ("sim_type", "last_sim_type_code"),
            ("spn", "last_spn"),
            ("language", "last_language"),
            ("fplmn", "last_fplmn"),
        ]:
            self._settings.set(skey, self._gen_vars[key].get().strip())
        try:
            self._settings.set(
                "last_batch_size", int(self._gen_vars["count"].get().strip()))
        except ValueError:
            pass
