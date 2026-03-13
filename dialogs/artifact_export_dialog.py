"""
Artifact Export Dialog — Save programming results to local or network storage.

After a batch programming run, this dialog lets the user choose which
fields to include in the export CSV and where to save it.  If a network
share is connected, it is offered as a quick destination alongside local
file browse.
"""

import csv
import os
import tkinter as tk
from datetime import datetime
from tkinter import ttk, filedialog, messagebox

from theme import ModernTheme
from managers.network_storage_manager import NetworkStorageManager

_ALL_FIELDS = [
    "ICCID", "IMSI", "Ki", "OPc", "ADM1",
    "PIN1", "PIN2", "PUK1", "PUK2",
    "ACC", "MSISDN", "MNC Length",
    "KIC1", "KID1", "KIK1",
    "KIC2", "KID2", "KIK2",
    "KIC3", "KID3", "KIK3",
    "SUCI Scheme", "SUCI Routing Ind.", "SUCI HN PubKey",
]


class ArtifactExportDialog(tk.Toplevel):
    """Modal dialog for exporting programming artifacts."""

    def __init__(self, parent, records: list[dict],
                 ns_manager: NetworkStorageManager | None = None,
                 default_fields: list[str] | None = None):
        """
        Parameters
        ----------
        records : list[dict]
            Card data dicts from the programming run.
        ns_manager :
            Optional network storage manager (for quick-save to share).
        default_fields :
            Which fields to pre-select.  Falls back to ICCID/IMSI/Ki/OPc.
        """
        super().__init__(parent)
        self.title("Export Programming Artifacts")
        self.geometry("480x460")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._records = records
        self._ns = ns_manager
        self._field_vars: dict[str, tk.BooleanVar] = {}
        self._default_fields = default_fields or [
            "ICCID", "IMSI", "Ki", "OPc"]

        self._build_ui()

    def _build_ui(self):
        pad = ModernTheme.get_padding("medium")

        ttk.Label(self, text=f"{len(self._records)} card(s) to export",
                  style="Subheading.TLabel").pack(
            padx=pad, pady=(pad, 4), anchor=tk.W)

        # Field selection
        fields_frame = ttk.LabelFrame(self, text="Select fields to include")
        fields_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, pad))
        fields_inner = ttk.Frame(fields_frame)
        fields_inner.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        for i, fname in enumerate(_ALL_FIELDS):
            var = tk.BooleanVar(
                value=fname in self._default_fields)
            self._field_vars[fname] = var
            r, c = divmod(i, 3)
            ttk.Checkbutton(fields_inner, text=fname,
                            variable=var).grid(
                row=r, column=c, sticky=tk.W, padx=(0, pad), pady=1)

        # Select all / none
        sel_row = ttk.Frame(fields_frame)
        sel_row.pack(fill=tk.X, padx=pad, pady=(0, pad))
        ttk.Button(sel_row, text="Select All",
                   command=self._select_all).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(sel_row, text="Select None",
                   command=self._select_none).pack(side=tk.LEFT)

        # Destination
        dest_frame = ttk.LabelFrame(self, text="Save to")
        dest_frame.pack(fill=tk.X, padx=pad, pady=(0, pad))
        dest_inner = ttk.Frame(dest_frame)
        dest_inner.pack(fill=tk.X, padx=pad, pady=pad)

        ttk.Button(dest_inner, text="Browse local...",
                   command=self._save_local).pack(
            side=tk.LEFT, padx=(0, pad))

        # Network share quick-save buttons
        if self._ns:
            for label, mount_path in self._ns.get_active_mount_paths():
                ttk.Button(
                    dest_inner,
                    text=f"Save to {label}",
                    command=lambda mp=mount_path, lbl=label: self._save_network(
                        mp, lbl),
                ).pack(side=tk.LEFT, padx=(0, pad))

        if not (self._ns and self._ns.get_active_mount_paths()):
            ttk.Label(dest_inner, text="No network shares connected",
                      style="Small.TLabel").pack(side=tk.LEFT)

        # Status / close
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=pad, pady=(0, pad))
        self._status = ttk.Label(bottom, text="", style="Small.TLabel")
        self._status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(bottom, text="Close",
                   command=self.destroy).pack(side=tk.RIGHT)

    # ---- Helpers -------------------------------------------------------

    def _selected_fields(self) -> list[str]:
        return [f for f in _ALL_FIELDS if self._field_vars[f].get()]

    def _select_all(self):
        for v in self._field_vars.values():
            v.set(True)

    def _select_none(self):
        for v in self._field_vars.values():
            v.set(False)

    def _generate_filename(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"sim_artifacts_{ts}.csv"

    def _write_csv(self, path: str) -> tuple[bool, str]:
        """Write selected fields to CSV.  Returns (ok, message)."""
        fields = self._selected_fields()
        if not fields:
            return False, "No fields selected"

        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields,
                                        extrasaction="ignore")
                writer.writeheader()
                for rec in self._records:
                    # Normalise keys to match _ALL_FIELDS casing
                    normalised = {}
                    key_map = {k.upper(): k for k in rec}
                    for f in fields:
                        normalised[f] = rec.get(f, rec.get(f.upper(),
                                                rec.get(f.lower(), "")))
                    writer.writerow(normalised)
            return True, f"Exported {len(self._records)} card(s) to {path}"
        except OSError as exc:
            return False, f"Write error: {exc}"

    # ---- Save actions --------------------------------------------------

    def _save_local(self):
        fields = self._selected_fields()
        if not fields:
            messagebox.showwarning("No fields",
                                   "Select at least one field to export.",
                                   parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save Artifacts",
            initialfile=self._generate_filename(),
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        ok, msg = self._write_csv(path)
        self._status.configure(text=msg[:80])
        if not ok:
            messagebox.showerror("Export Error", msg, parent=self)

    def _save_network(self, mount_path: str, label: str):
        fields = self._selected_fields()
        if not fields:
            messagebox.showwarning("No fields",
                                   "Select at least one field to export.",
                                   parent=self)
            return

        # Find the profile's export_subdir
        subdir = "artifacts"
        if self._ns:
            for prof in self._ns.load_profiles():
                if prof.label == label:
                    subdir = prof.export_subdir
                    break

        dest_dir = os.path.join(mount_path, subdir)
        path = os.path.join(dest_dir, self._generate_filename())

        ok, msg = self._write_csv(path)
        self._status.configure(text=msg[:80])
        if ok:
            messagebox.showinfo("Export Complete",
                                f"Saved to:\n{path}", parent=self)
        else:
            messagebox.showerror("Export Error", msg, parent=self)
