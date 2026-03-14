"""Selectable-text info / error dialog.

Replaces ``tkinter.messagebox.showinfo`` / ``showerror`` with a dialog
where the user can select and copy all text (Ctrl+C).  Standard
messageboxes render text as a non-selectable label, which makes it
impossible to copy error messages or version strings.
"""

import tkinter as tk
from tkinter import ttk


class InfoDialog(tk.Toplevel):
    """Modal dialog with selectable, copyable text content."""

    def __init__(self, parent, *, title: str, message: str,
                 level: str = "info"):
        """
        Parameters
        ----------
        parent : tk widget
            Parent window.
        title : str
            Dialog title bar text.
        message : str
            Body text (supports newlines).
        level : str
            ``"info"`` or ``"error"`` — only affects the icon.
        """
        super().__init__(parent)
        self.title(title)
        try:
            self.transient(parent)
            self.grab_set()
            self.resizable(True, True)
        except (tk.TclError, AttributeError):
            pass  # graceful in test / mock environments

        # --- Body ---
        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        # Read-only Text widget so the user can select & copy
        text = tk.Text(body, wrap=tk.WORD, relief=tk.FLAT,
                       borderwidth=0, highlightthickness=0,
                       font=("TkDefaultFont",),
                       padx=8, pady=8)
        text.insert("1.0", message)
        text.configure(state=tk.DISABLED)  # read-only but selectable
        # Match background to frame
        try:
            bg = body.winfo_toplevel().cget("bg")
            text.configure(background=bg)
        except (tk.TclError, AttributeError):
            pass
        text.pack(fill=tk.BOTH, expand=True)

        # Size to content (approximate)
        lines = message.count("\n") + 1
        max_line_len = max((len(line) for line in message.split("\n")),
                           default=40)
        width = min(max(max_line_len + 4, 40), 80)
        height = min(max(lines + 1, 4), 20)
        text.configure(width=width, height=height)

        # --- Button row ---
        btn_frame = ttk.Frame(self, padding=(16, 0, 16, 12))
        btn_frame.pack(fill=tk.X)

        copy_btn = ttk.Button(btn_frame, text="Copy All",
                              command=lambda: self._copy_all(message))
        copy_btn.pack(side=tk.LEFT)

        ok_btn = ttk.Button(btn_frame, text="OK",
                            command=self.destroy, width=10)
        ok_btn.pack(side=tk.RIGHT)
        ok_btn.focus_set()

        # Close on Enter or Escape
        self.bind("<Return>", lambda e: self.destroy())
        self.bind("<Escape>", lambda e: self.destroy())

        # Centre on parent
        try:
            self.update_idletasks()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
            self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except (tk.TclError, AttributeError):
            pass

    def _copy_all(self, text: str):
        """Copy all text to the system clipboard."""
        self.clipboard_clear()
        self.clipboard_append(text)


def show_info(parent, title: str, message: str):
    """Show an info dialog with selectable text.  Blocks until closed."""
    dlg = InfoDialog(parent, title=title, message=message, level="info")
    try:
        parent.wait_window(dlg)
    except (tk.TclError, AttributeError):
        pass


def show_error(parent, title: str, message: str):
    """Show an error dialog with selectable text.  Blocks until closed."""
    dlg = InfoDialog(parent, title=title, message=message, level="error")
    try:
        parent.wait_window(dlg)
    except (tk.TclError, AttributeError):
        pass
