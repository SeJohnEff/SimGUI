"""
Network Storage Dialog — Configure and connect NFS / SMB shares.

Allows the user to create, edit, test, connect, and disconnect
network storage profiles.  Profiles are persisted across sessions.

UX principles:
- User enters plain hostname / IP — never ``smb://`` or ``nfs://``
- Server field is a combobox with history of previously used servers
- "Remember credentials" checkbox controls secure credential file
- All input is sanitised (protocol prefixes stripped automatically)
"""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from managers.network_storage_manager import (
    NetworkStorageManager,
    StorageProfile,
)
from theme import ModernTheme
from utils.network_scanner import (
    DiscoveredServer,
    list_smb_shares,
    scan_smb_servers,
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


def _sanitise_server(raw: str) -> str:
    """Strip protocol prefixes and trailing slashes from a server entry.

    Users might paste ``smb://nas.local/share`` or ``nfs://10.0.0.1/data``.
    We only want the hostname / IP part.
    """
    s = raw.strip()
    for prefix in ("smb://", "cifs://", "nfs://", "//"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    # If they pasted a full path, take only the first component
    s = s.split("/")[0]
    return s.strip()


def _sanitise_share(raw: str, protocol: str) -> str:
    """Clean up share / export path input."""
    s = raw.strip()
    if protocol == "smb":
        # Remove any leading slashes for SMB share name
        s = s.strip("/")
    else:
        # NFS: ensure leading slash
        if s and not s.startswith("/"):
            s = "/" + s
    return s


class NetworkStorageDialog(tk.Toplevel):
    """Modal dialog for managing network storage connections."""

    def __init__(self, parent, ns_manager: NetworkStorageManager):
        super().__init__(parent)
        self.title("Network Storage")
        self.geometry("620x680")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._ns = ns_manager
        self._profiles: list[StorageProfile] = ns_manager.load_profiles()
        self._current_idx: int | None = None
        self._field_vars: dict[str, tk.BooleanVar] = {}

        # Build server history from saved profiles
        self._server_history: list[str] = self._build_server_history()

        self._build_ui()
        self._refresh_profile_list()

        if self._profiles:
            self._profile_list.selection_set(0)
            self._on_profile_select(None)

    # ---- helpers -------------------------------------------------------

    def _build_server_history(self) -> list[str]:
        """Collect unique servers from saved profiles for the combobox."""
        seen = set()
        servers = []
        for p in self._profiles:
            s = p.server.strip()
            if s and s not in seen:
                seen.add(s)
                servers.append(s)
        return servers

    def _update_server_history(self, server: str):
        """Add a server to the history if not already present."""
        server = server.strip()
        if server and server not in self._server_history:
            self._server_history.append(server)
            self._server_combo["values"] = self._server_history

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

        # Server (combobox with history) + Scan button
        row += 1
        ttk.Label(form_inner, text="Server:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        self._server_var = tk.StringVar()
        self._server_combo = ttk.Combobox(
            form_inner, textvariable=self._server_var, width=28,
            values=self._server_history)
        self._server_combo.grid(
            row=row, column=1, sticky=tk.EW, pady=2, padx=(4, 0))
        # Sanitise on focus-out (strip smb:// etc.)
        self._server_combo.bind("<FocusOut>", self._on_server_focus_out)

        self._scan_btn = ttk.Button(
            form_inner, text="Scan Network", width=13,
            command=self._on_scan_network,
        )
        self._scan_btn.grid(row=row, column=2, sticky=tk.W, padx=(4, 0))

        # Hint below server
        ttk.Label(form_inner, text="Hostname or IP address (e.g. 192.168.1.10)",
                  style="Small.TLabel").grid(
            row=row + 1, column=1, columnspan=2, sticky=tk.W, padx=(4, 0))

        # Discovery results panel
        row += 2
        self._discovery_frame = ttk.LabelFrame(
            form_inner, text="Discovered Servers",
        )
        self._discovery_frame.grid(
            row=row, column=0, columnspan=3, sticky=tk.EW, pady=(2, 4),
        )
        self._discovery_tree = ttk.Treeview(
            self._discovery_frame, height=3, show="headings",
            columns=("name", "ip", "shares"),
        )
        self._discovery_tree.heading("name", text="Name")
        self._discovery_tree.heading("ip", text="IP Address")
        self._discovery_tree.heading("shares", text="Shares")
        self._discovery_tree.column("name", width=160)
        self._discovery_tree.column("ip", width=120)
        self._discovery_tree.column("shares", width=200)
        self._discovery_tree.pack(fill=tk.X, padx=4, pady=4)
        self._discovery_tree.bind(
            "<<TreeviewSelect>>", self._on_discovery_select,
        )
        self._discovered_servers: list[DiscoveredServer] = []
        # Hide the discovery panel initially
        self._discovery_frame.grid_remove()

        # Share
        row += 1
        self._share_label = ttk.Label(form_inner, text="Share name:")
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
                                      width=30, show="\u2022")
        self._pass_entry.grid(row=row, column=1, sticky=tk.EW,
                               pady=2, padx=(4, 0))
        # Remember credentials checkbox
        self._remember_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form_inner, text="Remember",
                        variable=self._remember_var).grid(
            row=row, column=2, sticky=tk.W, padx=(4, 0))

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

    # ---- Event handlers ------------------------------------------------

    def _on_server_focus_out(self, _event):
        """Sanitise server input when user leaves the field."""
        raw = self._server_var.get()
        clean = _sanitise_server(raw)
        if clean != raw:
            self._server_var.set(clean)

    def _on_scan_network(self):
        """Run SMB network discovery in a background thread."""
        self._scan_btn.configure(state=tk.DISABLED)
        self._status_label.configure(text="Scanning network...")
        self.update_idletasks()
        thread = threading.Thread(target=self._scan_worker, daemon=True)
        thread.start()

    def _scan_worker(self):
        """Background worker — runs scan_smb_servers, then schedules UI update."""
        servers = scan_smb_servers(timeout=10)
        # Fetch shares for each discovered server (best-effort)
        for srv in servers:
            if not srv.shares:
                srv.shares = list_smb_shares(srv.ip, timeout=5)
        self.after(0, self._scan_done, servers)

    def _scan_done(self, servers: list[DiscoveredServer]):
        """Update the UI with scan results (runs on main thread)."""
        self._scan_btn.configure(state=tk.NORMAL)
        self._discovered_servers = servers

        # Clear previous results
        for item in self._discovery_tree.get_children():
            self._discovery_tree.delete(item)

        if not servers:
            self._status_label.configure(text="No SMB servers found on network")
            self._discovery_frame.grid_remove()
            return

        self._discovery_frame.grid()
        for srv in servers:
            shares_str = ", ".join(srv.shares) if srv.shares else ""
            self._discovery_tree.insert(
                "", tk.END, values=(srv.hostname, srv.ip, shares_str),
            )
        self._status_label.configure(
            text=f"Found {len(servers)} server(s)",
        )

    def _on_discovery_select(self, _event):
        """Fill server/share fields from a selected discovered server."""
        sel = self._discovery_tree.selection()
        if not sel:
            return
        item = self._discovery_tree.item(sel[0])
        values = item.get("values", [])
        if not values:
            return
        hostname, ip, shares_str = values[0], values[1], values[2]
        # Prefer IP for reliability, but use hostname if available
        self._server_var.set(str(ip) if ip else str(hostname))
        # If there's exactly one share, fill the share field
        if shares_str:
            share_list = [s.strip() for s in str(shares_str).split(",")]
            if len(share_list) == 1:
                self._share_var.set(share_list[0])

    # ---- Profile list management ---------------------------------------

    def _refresh_profile_list(self):
        self._profile_list.delete(0, tk.END)
        for p in self._profiles:
            mounted = " \u2713" if self._ns.is_mounted(p) else ""
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
        # Remember checkbox: True if password was saved
        self._remember_var.set(bool(p.password))
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
            text="Share name:" if is_smb else "Export path:")

    def _update_connect_btn(self, profile: StorageProfile):
        if self._ns.is_mounted(profile):
            self._connect_btn.configure(text="Disconnect")
        else:
            self._connect_btn.configure(text="Connect")

    # ---- Actions -------------------------------------------------------

    def _form_to_profile(self) -> StorageProfile | None:
        """Read form into a StorageProfile (validates required fields)."""
        label = self._label_var.get().strip()
        server = _sanitise_server(self._server_var.get())
        proto = self._proto_var.get()
        share = _sanitise_share(self._share_var.get(), proto)

        if not label or not server or not share:
            messagebox.showwarning("Missing fields",
                                   "Name, Server, and Share are required.",
                                   parent=self)
            return None

        # If "Remember" is unchecked, don't persist the password
        password = self._pass_var.get() if self._remember_var.get() else ""

        fields = [f for f, v in self._field_vars.items() if v.get()]
        return StorageProfile(
            label=label,
            protocol=proto,
            server=server,
            share=share,
            username=self._user_var.get().strip(),
            password=password,
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
        self._update_server_history(p.server)
        self._ns.save_profiles(self._profiles)
        self._refresh_profile_list()
        self._status_label.configure(text="Profile saved")

    def _on_test(self):
        p = self._form_to_profile()
        if p is None:
            return
        # For testing, we need the password even if "Remember" is unchecked
        if not p.password:
            p.password = self._pass_var.get()
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
            # For mounting, always use the entered password
            # (even if "Remember" is unchecked)
            if not updated.password:
                updated.password = self._pass_var.get()
            self._profiles[self._current_idx] = updated
            self._update_server_history(updated.server)
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
