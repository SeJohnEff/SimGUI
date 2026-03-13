"""
Network Storage Dialog — Configure and connect NFS / SMB shares.

Allows the user to create, edit, test, connect, and disconnect
network storage profiles.  Profiles are persisted across sessions.

UX flow:
  1. Fill in the form (or pick a discovered server).
  2. Click **Save & Connect** — profile is saved and mounted in one step.
  3. To tweak an existing profile, select it, edit, click **Update** or
     **Save & Connect** again.

UX principles:
- User enters plain hostname / IP — never ``smb://`` or ``nfs://``
- Server field is a combobox with history of previously used servers
- "Remember credentials" checkbox controls secure credential file
- All input is sanitised (protocol prefixes stripped automatically)
- No phantom profiles — "New" just clears the form, nothing is persisted
  until the user explicitly saves.
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


def _auto_name(server: str, share: str, protocol: str) -> str:
    """Generate a human-friendly profile name from server + share."""
    if server and share:
        return f"{share} on {server} ({protocol.upper()})"
    if server:
        return f"{server} ({protocol.upper()})"
    return "New connection"


class NetworkStorageDialog(tk.Toplevel):
    """Modal dialog for managing network storage connections."""

    def __init__(self, parent, ns_manager: NetworkStorageManager):
        super().__init__(parent)
        self.title("Network Storage")
        self.geometry("640x760")
        self.minsize(580, 500)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._ns = ns_manager
        self._profiles: list[StorageProfile] = ns_manager.load_profiles()
        self._current_idx: int | None = None
        self._field_vars: dict[str, tk.BooleanVar] = {}
        self._tooltip_win: tk.Toplevel | None = None
        self._dirty: bool = False  # True when form has unsaved changes

        # Build server history from saved profiles
        self._server_history: list[str] = self._build_server_history()

        self._build_ui()
        self._refresh_profile_list()

        if self._profiles:
            self._profile_list.selection_set(0)
            self._on_profile_select(None)
        else:
            # First-time: form is blank, ready to fill
            self._enter_new_mode()

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

        # --- Scrollable container for the entire dialog body ---
        self._canvas = tk.Canvas(self, highlightthickness=0)
        self._vscroll = ttk.Scrollbar(self, orient=tk.VERTICAL,
                                       command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vscroll.set)
        self._vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._body = ttk.Frame(self._canvas)
        self._body_id = self._canvas.create_window(
            (0, 0), window=self._body, anchor="nw")

        # Resize the inner frame with the canvas width
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._body.bind("<Configure>", self._on_body_configure)
        # Mouse-wheel scrolling (Linux + Windows + macOS)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind_all("<Button-4>", self._on_mousewheel)
        self._canvas.bind_all("<Button-5>", self._on_mousewheel)

        # ── Saved connections ──────────────────────────────────────────
        top = ttk.Frame(self._body)
        top.pack(fill=tk.X, padx=pad, pady=(pad, 0))

        ttk.Label(top, text="Saved connections:",
                  style="Subheading.TLabel").pack(side=tk.LEFT)

        btn_row = ttk.Frame(top)
        btn_row.pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="New", width=6,
                   command=self._on_new).pack(side=tk.LEFT, padx=2)
        self._remove_btn = ttk.Button(btn_row, text="Remove", width=8,
                                       command=self._on_remove)
        self._remove_btn.pack(side=tk.LEFT, padx=2)

        self._profile_list = tk.Listbox(self._body, height=4,
                                         exportselection=False)
        self._profile_list.pack(fill=tk.X, padx=pad, pady=(4, pad))
        self._profile_list.bind("<<ListboxSelect>>", self._on_profile_select)

        # ── Connection Details form ────────────────────────────────────
        form = ttk.LabelFrame(self._body, text="Connection Details")
        form.pack(fill=tk.X, padx=pad, pady=(0, pad))
        form_inner = ttk.Frame(form)
        form_inner.pack(fill=tk.X, padx=pad, pady=pad)

        row = 0
        # Name (auto-generated if left blank)
        ttk.Label(form_inner, text="Name:").grid(
            row=row, column=0, sticky=tk.W, pady=2)
        self._label_var = tk.StringVar()
        ttk.Entry(form_inner, textvariable=self._label_var, width=30).grid(
            row=row, column=1, columnspan=2, sticky=tk.EW, pady=2, padx=(4, 0))
        ttk.Label(form_inner, text="(auto-generated if blank)",
                  style="Small.TLabel").grid(
            row=row + 1, column=1, columnspan=2, sticky=tk.W, padx=(4, 0))

        # Protocol
        row += 2
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
        # Container for treeview + scrollbars
        tree_container = ttk.Frame(self._discovery_frame)
        tree_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._discovery_tree = ttk.Treeview(
            tree_container, height=3, show="headings",
            columns=("name", "ip", "shares"),
        )
        self._discovery_tree.heading("name", text="Name")
        self._discovery_tree.heading("ip", text="IP Address")
        self._discovery_tree.heading("shares", text="Shares")
        self._discovery_tree.column("name", width=140, minwidth=80)
        self._discovery_tree.column("ip", width=120, minwidth=80)
        self._discovery_tree.column("shares", width=300, minwidth=120)

        # Vertical scrollbar
        tree_vscroll = ttk.Scrollbar(
            tree_container, orient=tk.VERTICAL,
            command=self._discovery_tree.yview)
        self._discovery_tree.configure(yscrollcommand=tree_vscroll.set)

        # Horizontal scrollbar for long share lists
        tree_hscroll = ttk.Scrollbar(
            tree_container, orient=tk.HORIZONTAL,
            command=self._discovery_tree.xview)
        self._discovery_tree.configure(xscrollcommand=tree_hscroll.set)

        self._discovery_tree.grid(row=0, column=0, sticky="nsew")
        tree_vscroll.grid(row=0, column=1, sticky="ns")
        tree_hscroll.grid(row=1, column=0, sticky="ew")
        tree_container.columnconfigure(0, weight=1)
        tree_container.rowconfigure(0, weight=1)

        self._discovery_tree.bind(
            "<<TreeviewSelect>>", self._on_discovery_select,
        )
        # Tooltip on hover over truncated shares
        self._discovery_tree.bind("<Motion>", self._on_tree_motion)
        self._discovery_tree.bind("<Leave>", self._hide_tooltip)
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

        # ── Export fields selection ────────────────────────────────────
        fields_frame = ttk.LabelFrame(self._body, text="Artifact Export Fields")
        fields_frame.pack(fill=tk.X, padx=pad, pady=(0, pad))
        fields_inner = ttk.Frame(fields_frame)
        fields_inner.pack(fill=tk.X, padx=pad, pady=pad)

        for i, fname in enumerate(_ALL_EXPORT_FIELDS):
            var = tk.BooleanVar(value=fname in ("ICCID", "IMSI", "Ki", "OPc"))
            self._field_vars[fname] = var
            r, c = divmod(i, 4)
            ttk.Checkbutton(fields_inner, text=fname,
                            variable=var).grid(
                row=r, column=c, sticky=tk.W, padx=(0, pad), pady=1)

        # ── Bottom action buttons ──────────────────────────────────────
        actions = ttk.Frame(self._body)
        actions.pack(fill=tk.X, padx=pad, pady=(0, pad))

        self._status_label = ttk.Label(actions, text="", style="Small.TLabel")
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(actions, text="Test", width=8,
                   command=self._on_test).pack(side=tk.LEFT, padx=2)

        self._connect_btn = ttk.Button(actions, text="Save && Connect",
                                        width=14,
                                        command=self._on_connect)
        self._connect_btn.pack(side=tk.LEFT, padx=2)

        self._update_btn = ttk.Button(actions, text="Save", width=8,
                                       command=self._on_save)
        self._update_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(actions, text="Close", width=8,
                   command=self.destroy).pack(side=tk.LEFT, padx=2)

    # ---- Lifecycle -------------------------------------------------------

    def destroy(self):
        """Unbind global scroll events before destroying."""
        self._hide_tooltip()
        try:
            self._canvas.unbind_all("<MouseWheel>")
            self._canvas.unbind_all("<Button-4>")
            self._canvas.unbind_all("<Button-5>")
        except tk.TclError:
            pass
        super().destroy()

    # ---- Scroll helpers --------------------------------------------------

    def _on_canvas_configure(self, event):
        """Keep the inner frame width matched to the canvas."""
        self._canvas.itemconfig(self._body_id, width=event.width)

    def _on_body_configure(self, _event):
        """Update scrollregion when the body frame changes size."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_mousewheel(self, event):
        """Scroll the canvas with the mouse wheel."""
        # Linux uses Button-4/5, Windows/macOS use MouseWheel
        if event.num == 4:
            self._canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(3, "units")
        else:
            # Windows / macOS
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ---- Tooltip helpers -------------------------------------------------

    def _on_tree_motion(self, event):
        """Show a tooltip with the full shares text when hovering."""
        tree = self._discovery_tree
        row_id = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not row_id or col != "#3":  # Only tooltip on the Shares column
            self._hide_tooltip()
            return
        item = tree.item(row_id)
        shares_text = str(item.get("values", ["", "", ""])[2])
        if not shares_text or len(shares_text) < 25:
            self._hide_tooltip()
            return
        # Show tooltip near cursor
        x = event.x_root + 12
        y = event.y_root + 12
        if self._tooltip_win and self._tooltip_win.winfo_exists():
            label = self._tooltip_win.winfo_children()[0]
            label.configure(text=shares_text)
            self._tooltip_win.geometry(f"+{x}+{y}")
        else:
            self._tooltip_win = tw = tk.Toplevel(self)
            tw.wm_overrideredirect(True)
            tw.geometry(f"+{x}+{y}")
            lbl = tk.Label(
                tw, text=shares_text, background="#ffffe0",
                relief="solid", borderwidth=1, padx=6, pady=3,
                wraplength=400, justify=tk.LEFT,
            )
            lbl.pack()

    def _hide_tooltip(self, _event=None):
        if self._tooltip_win and self._tooltip_win.winfo_exists():
            self._tooltip_win.destroy()
        self._tooltip_win = None

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

    # ---- Mode management -----------------------------------------------

    def _enter_new_mode(self):
        """Switch to 'new profile' mode: clear form, deselect list."""
        self._current_idx = None
        self._profile_list.selection_clear(0, tk.END)
        self._clear_form()
        self._update_button_states()

    def _clear_form(self):
        """Reset all form fields to defaults."""
        self._label_var.set("")
        self._proto_var.set("smb")
        self._server_var.set("")
        self._share_var.set("")
        self._user_var.set("")
        self._pass_var.set("")
        self._domain_var.set("")
        self._export_dir_var.set("artifacts")
        self._remember_var.set(True)
        for fname, var in self._field_vars.items():
            var.set(fname in ("ICCID", "IMSI", "Ki", "OPc"))
        self._on_proto_change()
        self._status_label.configure(text="")

    def _update_button_states(self):
        """Update button labels/states based on whether editing or new."""
        editing = self._current_idx is not None
        if editing:
            p = self._profiles[self._current_idx]
            mounted = self._ns.is_mounted(p)
            self._update_btn.configure(text="Update", state=tk.NORMAL)
            self._remove_btn.configure(state=tk.NORMAL)
            self._connect_btn.configure(
                text="Disconnect" if mounted else "Save && Connect")
        else:
            self._update_btn.configure(text="Save New", state=tk.NORMAL)
            self._remove_btn.configure(state=tk.DISABLED)
            self._connect_btn.configure(text="Save && Connect")

    # ---- Profile list management ---------------------------------------

    def _refresh_profile_list(self):
        prev_idx = self._current_idx
        self._profile_list.delete(0, tk.END)
        for p in self._profiles:
            mounted = " \u2713" if self._ns.is_mounted(p) else ""
            self._profile_list.insert(tk.END,
                                       f"{p.label} ({p.protocol}){mounted}")
        # Restore selection if still valid
        if prev_idx is not None and prev_idx < len(self._profiles):
            self._profile_list.selection_set(prev_idx)

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
        self._on_proto_change()
        self._update_button_states()
        self._status_label.configure(text="")

    def _on_new(self):
        """Clear the form for a fresh connection (no phantom profile)."""
        self._enter_new_mode()
        self._status_label.configure(text="Fill in details for a new connection")

    def _on_remove(self):
        if self._current_idx is None:
            return
        p = self._profiles[self._current_idx]
        name = p.label or "this connection"
        if not messagebox.askyesno(
                "Remove Connection",
                f"Remove \"{name}\"?\n\nThis will also disconnect if mounted.",
                parent=self):
            return
        if self._ns.is_mounted(p):
            self._ns.unmount(p)
        self._profiles.pop(self._current_idx)
        self._ns.save_profiles(self._profiles)
        self._enter_new_mode()
        self._refresh_profile_list()
        self._status_label.configure(text=f"Removed \"{name}\"")

    def _on_proto_change(self):
        is_smb = self._proto_var.get() == "smb"
        state = tk.NORMAL if is_smb else tk.DISABLED
        self._user_entry.configure(state=state)
        self._pass_entry.configure(state=state)
        self._domain_entry.configure(state=state)
        self._share_label.configure(
            text="Share name:" if is_smb else "Export path:")

    # ---- Actions -------------------------------------------------------

    def _form_to_profile(self) -> StorageProfile | None:
        """Read form into a StorageProfile (validates required fields).

        If the Name field is blank, auto-generates one from server + share.
        """
        server = _sanitise_server(self._server_var.get())
        proto = self._proto_var.get()
        share = _sanitise_share(self._share_var.get(), proto)
        label = self._label_var.get().strip()

        if not server or not share:
            messagebox.showwarning("Missing fields",
                                   "Server and Share are required.",
                                   parent=self)
            return None

        # Auto-generate name if blank
        if not label:
            label = _auto_name(server, share, proto)
            self._label_var.set(label)

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

    def _save_profile(self) -> StorageProfile | None:
        """Save or update the current profile from the form.

        Returns the saved profile on success, None on validation failure.
        Creates a new profile if _current_idx is None, otherwise updates.
        """
        p = self._form_to_profile()
        if p is None:
            return None

        if self._current_idx is not None:
            # Update existing
            self._profiles[self._current_idx] = p
        else:
            # Check for duplicate (same server + share + protocol)
            for existing in self._profiles:
                if (existing.server == p.server
                        and existing.share == p.share
                        and existing.protocol == p.protocol):
                    if not messagebox.askyesno(
                            "Duplicate Connection",
                            f"A connection to {p.share} on {p.server} "
                            f"already exists (\"{existing.label}\").\n\n"
                            "Save as a new connection anyway?",
                            parent=self):
                        return None
                    break
            # Append new
            self._profiles.append(p)
            self._current_idx = len(self._profiles) - 1

        self._update_server_history(p.server)
        self._ns.save_profiles(self._profiles)
        self._refresh_profile_list()
        self._update_button_states()
        return p

    def _on_save(self):
        p = self._save_profile()
        if p is None:
            return
        action = "updated" if self._current_idx is not None else "saved"
        self._status_label.configure(text=f"\"{p.label}\" {action}")

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
        # If currently connected, disconnect
        if (self._current_idx is not None
                and self._ns.is_mounted(self._profiles[self._current_idx])):
            p = self._profiles[self._current_idx]
            ok, msg = self._ns.unmount(p)
            self._status_label.configure(text=msg[:80])
            self._refresh_profile_list()
            self._update_button_states()
            return

        # Save first (creates new or updates existing)
        p = self._save_profile()
        if p is None:
            return

        # For mounting, always use the entered password
        # (even if "Remember" is unchecked)
        if not p.password:
            p.password = self._pass_var.get()

        self._status_label.configure(text="Mounting...")
        self.update_idletasks()
        ok, msg = self._ns.mount(p)
        self._status_label.configure(text=msg[:80])
        if not ok:
            messagebox.showerror("Mount Failed", msg, parent=self)

        self._refresh_profile_list()
        self._update_button_states()
