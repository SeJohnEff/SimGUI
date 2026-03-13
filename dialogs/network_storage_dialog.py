"""
Network Storage Dialog — Configure and connect NFS / SMB shares.

Allows the user to create, edit, test, connect, and disconnect
network storage profiles.  Profiles are persisted across sessions.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from theme import ModernTheme
from managers.network_storage_manager import (
    NetworkStorageManager,
    StorageProfile,
)


_ALL_EXPORT_FIELDS = [
    "ICCID", "IMSI", "Ki", "OPc", "ADM1",
    "PIN1", "PIN2", "PUK1", "PUK2",
    "ACC", "MSISDN", "MNC Length",
    "KIC1", "KID1", "KIK1",
    "KIC2", "KID2", "KIK2",
    "KIC3", "KID3", "KIK3",
    "SUCI Scheme", "SUCI Routing Ind.", "SUCI HN PubKey",
]


class NetworkStorageDialog(tk.Toplevel):
    """Modal dialog for managing network storage connections."""

    def __init__(self, parent, ns_manager: NetworkStorageManager):
        super().__init__(parent)
        self.title("Network Storage")
        self.geometry("620x560")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._ns = ns_manager
        self._profiles: list[StorageProfile] = ns_manager.load_profiles()
        self._current_idx: int | None = None
        self._field_vars: dict[str, tk.BooleanVar] = {}

        self._build_ui()
        self._refresh_profile_list()

        if self._profiles:
            self._profile_list.selection_set(0)
            self._on_profile_select(None)

    # ---- UI construction -----------------------------------------------

    def _build_ui(self):
        pad = ModernTheme.get_padding("medium")

        # Top: profile list + add/remove buttons
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=pad, pady=(pad, 0))

        ttk.Label(top, text="Saved connections:",
                  style="Subheading.TLabel").pack(side=tk.LEFT)

        btn_row = ttk.Frame(top)
        btn_row.pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Add", width=6,
                   command=self._on_add).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Remove", width=8,
                   command=self._on_remove).pack(side=tk.LEFT, padx=2)

        self._profile_list = tk.Listbox(self, height=4,
                                         exportselection=False)
        self._profile_list.pack(fill=tk.X, padx=pad, pady=(4, pad))
        self._profile_list.bind("<<ListboxSelect>>", self._on_profile_select)

        # Middle: connection details form
        form = ttk.LabelFrame(self, text="Connection Details")
        form.pack(fill=tk.X, padx=pad, pady=(0, pad))
        form_inner = ttk.Frame(form)
        form_inner.pack(fill=tk.X, padx=pad, pady=pad)

        row = 0
        # Label
        ttk.Label(form_inner, text="Name:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        self._label_var = tk.StringVar()
        ttk.Entry(form_inner, textvariable=self._label_var, width=30).grid(
            row=row, column=1, columnspan=2, sticky=tk.EW, pady=2, padx=(4, 0))

        # Protocol
        row += 1
        ttk.Label(form_inner, text="Protocol:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        self._proto_var = tk.StringVar(value="smb")
        proto_frame = ttk.Frame(form_inner)
        proto_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=2,
                         padx=(4, 0))
        ttk.Radiobutton(proto_frame, text="SMB / CIFS",
                        variable=self._proto_var, value="smb",
                        command=self._on_proto_change).pack(side=tk.LEFT)
        ttk.Radiobutton(proto_frame, text="NFS",
                        variable=self._proto_var, value="nfs",
                        command=self._on_proto_change).pack(side=tk.LEFT,
                                                            padx=(pad, 0))

        # Server
        row += 1
        ttk.Label(form_inner, text="Server:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        self._server_var = tk.StringVar()
        ttk.Entry(form_inner, textvariable=self._server_var, width=30).grid(
            row=row, column=1, columnspan=2, sticky=tk.EW, pady=2, padx=(4, 0))

        # Share
        row += 1
        self._share_label = ttk.Label(form_inner, text="Share:")
        self._share_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self._share_var = tk.StringVar()
        ttk.Entry(form_inner, textvariable=self._share_var, width=30).grid(
            row=row, column=1, columnspan=2, sticky=tk.EW, pady=2, padx=(4, 0))

        # Username (SMB only)
        row += 1
        self._user_label = ttk.Label(form_inner, text="Username:")
        self._user_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self._user_var = tk.StringVar()
        self._user_entry = ttk.Entry(form_inner, textvariable=self._user_var,
                                      width=30)
        self._user_entry.grid(row=row, column=1, columnspan=2, sticky=tk.EW,
                               pady=2, padx=(4, 0))

        # Password (SMB only)
        row += 1
        self._pass_label = ttk.Label(form_inner, text="Password:")
        self._pass_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self._pass_var = tk.StringVar()
        self._pass_entry = ttk.Entry(form_inner, textvariable=self._pass_var,
                                      width=30, show="•")
        self._pass_entry.grid(row=row, column=1, columnspan=2, sticky=tk.EW,
                               pady=2, padx=(4, 0))

        # Domain (SMB only)
        row += 1
        self._domain_label = ttk.Label(form_inner, text="Domain:")
        self._domain_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self._domain_var = tk.StringVar()
        self._domain_entry = ttk.Entry(form_inner,
                                        textvariable=self._domain_var,
                                        width=30)
        self._domain_entry.grid(row=row, column=1, columnspan=2, sticky=tk.EW,
                                 pady=2, padx=(4, 0))

        # Export sub-directory
        row += 1
        ttk.Label(form_inner, text="Artifact folder:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        self._export_dir_var = tk.StringVar(value="artifacts")
        ttk.Entry(form_inner, textvariable=self._export_dir_var,
                  width=30).grid(
            row=row, column=1, columnspan=2, sticky=tk.EW, pady=2,
            padx=(4, 0))

        form_inner.columnconfigure(1, weight=1)

        # Export fields selection
        fields_frame = ttk.LabelFrame(self, text="Artifact Export Fields")
        fields_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, pad))
        fields_inner = ttk.Frame(fields_frame)
        fields_inner.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        for i, fname in enumerate(_ALL_EXPORT_FIELDS):
            var = tk.BooleanVar(value=fname in ("ICCID", "IMSI", "Ki", "OPc"))
            self._field_vars[fname] = var
            r, c = divmod(i, 4)
            ttk.Checkbutton(fields_inner, text=fname,
                            variable=var).grid(
                row=r, column=c, sticky=tk.W, padx=(0, pad), pady=1)

        # Bottom action buttons
        actions = ttk.Frame(self)
        actions.pack(fill=tk.X, padx=pad, pady=(0, pad))

        self._status_label = ttk.Label(actions, text="", style="Small.TLabel")
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(actions, text="Test", width=8,
                   command=self._on_test).pack(side=tk.LEFT, padx=2)
        self._connect_btn = ttk.Button(actions, text="Connect", width=10,
                                        command=self._on_connect)
        self._connect_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text="Save", width=8,
                   command=self._on_save).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text="Close", width=8,
                   command=self.destroy).pack(side=tk.LEFT, padx=2)

    # ---- Profile list management ---------------------------------------

    def _refresh_profile_list(self):
        self._profile_list.delete(0, tk.END)
        for p in self._profiles:
            mounted = " ✓" if self._ns.is_mounted(p) else ""
            self._profile_list.insert(tk.END,
                                       f"{p.label} ({p.protocol}){mounted}")

    def _on_profile_select(self, _event):
        sel = self._profile_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self._current_idx = idx
        p = self._profiles[idx]
        self._label_var.set(p.label)
        self._proto_var.set(p.protocol)
        self._server_var.set(p.server)
        self._share_var.set(p.share)
        self._user_var.set(p.username)
        self._pass_var.set(p.password)
        self._domain_var.set(p.domain)
        self._export_dir_var.set(p.export_subdir)
        for fname, var in self._field_vars.items():
            var.set(fname in p.export_fields)
        self._update_connect_btn(p)
        self._on_proto_change()

    def _on_add(self):
        p = StorageProfile(label=f"Connection {len(self._profiles) + 1}")
        self._profiles.append(p)
        self._refresh_profile_list()
        self._profile_list.selection_clear(0, tk.END)
        self._profile_list.selection_set(len(self._profiles) - 1)
        self._on_profile_select(None)

    def _on_remove(self):
        if self._current_idx is None:
            return
        p = self._profiles[self._current_idx]
        if self._ns.is_mounted(p):
            self._ns.unmount(p)
        self._profiles.pop(self._current_idx)
        self._current_idx = None
        self._ns.save_profiles(self._profiles)
        self._refresh_profile_list()

    def _on_proto_change(self):
        is_smb = self._proto_var.get() == "smb"
        state = tk.NORMAL if is_smb else tk.DISABLED
        self._user_entry.configure(state=state)
        self._pass_entry.configure(state=state)
        self._domain_entry.configure(state=state)
        self._share_label.configure(
            text="Share:" if is_smb else "Export path:")

    def _update_connect_btn(self, profile: StorageProfile):
        if self._ns.is_mounted(profile):
            self._connect_btn.configure(text="Disconnect")
        else:
            self._connect_btn.configure(text="Connect")

    # ---- Actions -------------------------------------------------------

    def _form_to_profile(self) -> StorageProfile | None:
        """Read form into a StorageProfile (validates required fields)."""
        label = self._label_var.get().strip()
        server = self._server_var.get().strip()
        share = self._share_var.get().strip()
        if not label or not server or not share:
            messagebox.showwarning("Missing fields",
                                   "Name, Server, and Share are required.",
                                   parent=self)
            return None
        fields = [f for f, v in self._field_vars.items() if v.get()]
        return StorageProfile(
            label=label,
            protocol=self._proto_var.get(),
            server=server,
            share=share,
            username=self._user_var.get().strip(),
            password=self._pass_var.get(),
            domain=self._domain_var.get().strip(),
            export_subdir=self._export_dir_var.get().strip() or "artifacts",
            export_fields=fields,
        )

    def _on_save(self):
        p = self._form_to_profile()
        if p is None:
            return
        if self._current_idx is not None:
            self._profiles[self._current_idx] = p
        else:
            self._profiles.append(p)
        self._ns.save_profiles(self._profiles)
        self._refresh_profile_list()
        self._status_label.configure(text="Profile saved")

    def _on_test(self):
        p = self._form_to_profile()
        if p is None:
            return
        self._status_label.configure(text="Testing connection...")
        self.update_idletasks()
        ok, msg = self._ns.test_connection(p)
        self._status_label.configure(text=msg[:80])
        if not ok:
            messagebox.showwarning("Connection Test", msg, parent=self)

    def _on_connect(self):
        if self._current_idx is None:
            return
        p = self._profiles[self._current_idx]

        if self._ns.is_mounted(p):
            ok, msg = self._ns.unmount(p)
            self._status_label.configure(text=msg[:80])
        else:
            # Save form first
            updated = self._form_to_profile()
            if updated is None:
                return
            self._profiles[self._current_idx] = updated
            self._ns.save_profiles(self._profiles)
            p = updated

            self._status_label.configure(text="Mounting...")
            self.update_idletasks()
            ok, msg = self._ns.mount(p)
            self._status_label.configure(text=msg[:80])
            if not ok:
                messagebox.showerror("Mount Failed", msg, parent=self)

        self._refresh_profile_list()
        self._update_connect_btn(self._profiles[self._current_idx])
