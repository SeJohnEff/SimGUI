"""
Toast notification — non-blocking overlay that auto-dismisses.

Usage::

    from widgets.toast import show_toast
    show_toast(root, "Share connected: NAS on 192.168.1.10")
    show_toast(root, "Mount failed: timeout", level="error", duration=6000)

Levels: ``"info"`` (default), ``"success"``, ``"warning"``, ``"error"``.
"""

import tkinter as tk

# Colour palette per level
_COLOURS = {
    "info":    {"bg": "#2563EB", "fg": "#FFFFFF"},  # Blue
    "success": {"bg": "#16A34A", "fg": "#FFFFFF"},  # Green
    "warning": {"bg": "#D97706", "fg": "#FFFFFF"},  # Amber
    "error":   {"bg": "#DC2626", "fg": "#FFFFFF"},  # Red
}

_ICON = {
    "info":    "\u2139",   # ℹ
    "success": "\u2714",   # ✔
    "warning": "\u26A0",   # ⚠
    "error":   "\u2718",   # ✘
}


def show_toast(parent: tk.Misc, message: str, *,
               level: str = "info",
               duration: int = 4000) -> tk.Toplevel:
    """Show a non-blocking toast notification anchored to *parent*.

    Parameters
    ----------
    parent :
        The root or toplevel window.
    message :
        Text to display.
    level :
        ``"info"``, ``"success"``, ``"warning"``, or ``"error"``.
    duration :
        Milliseconds before the toast auto-dismisses.

    Returns the Toplevel widget (for testing).
    """
    colours = _COLOURS.get(level, _COLOURS["info"])
    icon = _ICON.get(level, "")

    toast = tk.Toplevel(parent)
    toast.overrideredirect(True)
    toast.attributes("-topmost", True)
    toast.configure(bg=colours["bg"])

    # Build content
    frame = tk.Frame(toast, bg=colours["bg"], padx=12, pady=8)
    frame.pack(fill=tk.BOTH, expand=True)

    text = f"{icon}  {message}" if icon else message
    label = tk.Label(
        frame, text=text,
        bg=colours["bg"], fg=colours["fg"],
        font=("", 10), anchor=tk.W,
        wraplength=400, justify=tk.LEFT,
    )
    label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # Dismiss button (×)
    close_btn = tk.Label(
        frame, text="\u2715", cursor="hand2",
        bg=colours["bg"], fg=colours["fg"],
        font=("", 12, "bold"), padx=6,
    )
    close_btn.pack(side=tk.RIGHT)
    close_btn.bind("<Button-1>", lambda _: _dismiss(toast))

    # Position: top-right of parent window, with a small offset
    parent.update_idletasks()
    try:
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
    except tk.TclError:
        px, py, pw = 100, 100, 800

    toast.update_idletasks()
    tw = toast.winfo_reqwidth()
    x = px + pw - tw - 16
    y = py + 8
    toast.geometry(f"+{max(0, x)}+{max(0, y)}")

    # Auto-dismiss after duration
    toast._dismiss_id = toast.after(duration, lambda: _dismiss(toast))

    return toast


def _dismiss(toast: tk.Toplevel):
    """Destroy the toast safely."""
    try:
        if toast.winfo_exists():
            toast.destroy()
    except tk.TclError:
        pass
