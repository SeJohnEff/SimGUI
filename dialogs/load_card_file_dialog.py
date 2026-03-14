"""
Load Card File Dialog — Unified file picker for unknown-card flow.

When a card is detected that is not in any indexed file, this dialog
replaces the old two-step flow (Yes/No messagebox → separate filedialog)
with a single window that offers:

  1. One-click access to each connected network share.
  2. A "Browse Local…" button for the standard OS file picker.
  3. A "Connect Network Share…" button that opens the Network Storage
     dialog inline, then refreshes the share list.

This keeps the user in a single workflow: card detected → find the file →
done.
"""

import logging
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Optional

from theme import ModernTheme
from widgets.tooltip import add_tooltip

logger = logging.getLogger(__name__)

# Supported filetypes (must match SIM_DATA_FILETYPES in main.py)
_SIM_FILETYPES = [
    ("SIM Data Files", "*.csv *.eml *.txt"),
    ("CSV files", "*.csv"),
    ("EML files", "*.eml"),
    ("All files", "*.*"),
]


class LoadCardFileDialog(tk.Toplevel):
    """Modal dialog for locating a data file for an unknown card.

    Parameters
    ----------
    parent :
        The parent window (usually the main SimGUI window).
    iccid :
        The ICCID of the detected card.
    ns_manager :
        The :class:`NetworkStorageManager` instance for share access.
    initial_dir :
        Default directory for the local file browser (optional).

    After the dialog closes, read :attr:`selected_path` for the chosen
    file path, or ``None`` if the user cancelled.
    """

    def __init__(self, parent, iccid: str, ns_manager, *,
                 initial_dir: Optional[str] = None):
        super().__init__(parent)
        self.title("Load Card Data File")
        self.geometry("520x380")
        self.minsize(420, 300)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._iccid = iccid
        self._ns = ns_manager
        self._initial_dir = initial_dir
        self.selected_path: Optional[str] = None

        self._build_ui()

        # Centre on parent
        self.update_idletasks()
        if parent.winfo_viewable():
            x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
            self.geometry(f"+{max(0, x)}+{max(0, y)}")

    # ---- UI construction -----------------------------------------------

    def _build_ui(self):
        pad = ModernTheme.get_padding("medium")

        # ── Card info banner ──────────────────────────────────────────────
        banner = ttk.Frame(self)
        banner.pack(fill=tk.X, padx=pad, pady=(pad, 0))

        ttk.Label(
            banner,
            text="Card not in index",
            style="Subheading.TLabel",
        ).pack(anchor=tk.W)

        ttk.Label(
            banner,
            text=f"ICCID: {self._iccid}",
        ).pack(anchor=tk.W, pady=(2, 0))

        ttk.Label(
            banner,
            text="Select a data file (CSV / EML) containing this card:",
            style="Small.TLabel",
        ).pack(anchor=tk.W, pady=(4, 0))

        ttk.Separator(self).pack(fill=tk.X, padx=pad, pady=(pad, 0))

        # ── Network shares section ────────────────────────────────────────
        shares_frame = ttk.LabelFrame(self, text="Network Shares")
        shares_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(pad, 0))

        # Scrollable container for share buttons
        self._shares_canvas = tk.Canvas(shares_frame, highlightthickness=0,
                                        height=100)
        self._shares_vscroll = ttk.Scrollbar(
            shares_frame, orient=tk.VERTICAL,
            command=self._shares_canvas.yview)
        self._shares_canvas.configure(
            yscrollcommand=self._shares_vscroll.set)
        self._shares_inner = ttk.Frame(self._shares_canvas)
        self._shares_canvas_id = self._shares_canvas.create_window(
            (0, 0), window=self._shares_inner, anchor="nw")

        self._shares_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._shares_vscroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._shares_inner.bind(
            "<Configure>",
            lambda _: self._shares_canvas.configure(
                scrollregion=self._shares_canvas.bbox("all")),
        )
        self._shares_canvas.bind(
            "<Configure>",
            lambda e: self._shares_canvas.itemconfig(
                self._shares_canvas_id, width=e.width),
        )

        self._populate_shares()

        # ── Bottom buttons ────────────────────────────────────────────
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=pad, pady=pad)

        # Connect new share button on the left
        connect_btn = ttk.Button(
            btn_frame, text="Connect Network Share\u2026",
            command=self._on_connect_share,
        )
        connect_btn.pack(side=tk.LEFT)
        add_tooltip(connect_btn,
                    "Open the Network Storage dialog to connect a new share")

        # Cancel on the right
        cancel_btn = ttk.Button(
            btn_frame, text="Cancel", command=self._on_cancel,
        )
        cancel_btn.pack(side=tk.RIGHT, padx=(4, 0))

        # Browse local in the middle-right
        local_btn = ttk.Button(
            btn_frame, text="Browse Local\u2026",
            command=self._on_browse_local,
        )
        local_btn.pack(side=tk.RIGHT)
        add_tooltip(local_btn, "Open the standard file browser")

    def _populate_shares(self):
        """Fill the shares section with buttons for each mounted share."""
        # Clear existing widgets
        for w in self._shares_inner.winfo_children():
            w.destroy()

        mounts = self._ns.get_active_mount_paths() if self._ns else []

        if not mounts:
            ttk.Label(
                self._shares_inner,
                text="No network shares connected.\n"
                     "Use \"Connect Network Share\u2026\" below to add one,\n"
                     "or \"Browse Local\u2026\" to pick a file from this computer.",
                style="Small.TLabel",
                justify=tk.CENTER,
            ).pack(expand=True, pady=20)
            return

        pad = ModernTheme.get_padding("small")

        for label, mount_path in mounts:
            row = ttk.Frame(self._shares_inner)
            row.pack(fill=tk.X, padx=pad, pady=(pad, 0))

            # Share label + path
            info = ttk.Frame(row)
            info.pack(side=tk.LEFT, fill=tk.X, expand=True)

            ttk.Label(info, text=label,
                      font=("", 0, "bold")).pack(anchor=tk.W)
            ttk.Label(info, text=mount_path,
                      style="Small.TLabel").pack(anchor=tk.W)

            # Browse button
            browse_btn = ttk.Button(
                row, text="Browse\u2026",
                command=lambda mp=mount_path: self._on_browse_share(mp),
            )
            browse_btn.pack(side=tk.RIGHT, padx=(pad, 0))
            add_tooltip(browse_btn,
                        f"Browse files on \"{label}\"")

    # ---- Event handlers ------------------------------------------------

    def _on_browse_share(self, mount_path: str):
        """Open file dialog starting at the given network mount."""
        fp = filedialog.askopenfilename(
            title="Select Card Data File",
            initialdir=mount_path,
            filetypes=_SIM_FILETYPES,
            parent=self,
        )
        if fp:
            self.selected_path = fp
            self.destroy()

    def _on_browse_local(self):
        """Open the standard OS file browser."""
        kwargs = {
            "title": "Select Card Data File",
            "filetypes": _SIM_FILETYPES,
            "parent": self,
        }
        if self._initial_dir:
            kwargs["initialdir"] = self._initial_dir
        fp = filedialog.askopenfilename(**kwargs)
        if fp:
            self.selected_path = fp
            self.destroy()

    def _on_connect_share(self):
        """Open the Network Storage dialog, then refresh shares."""
        try:
            from dialogs.network_storage_dialog import NetworkStorageDialog
            dlg = NetworkStorageDialog(self, self._ns)
            self.wait_window(dlg)
        except Exception as exc:
            logger.warning("Failed to open NetworkStorageDialog: %s", exc)
        # Refresh the share list — user may have connected a new one
        self._populate_shares()

    def _on_cancel(self):
        self.selected_path = None
        self.destroy()
