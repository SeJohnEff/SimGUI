"""
Reusable Tooltip widget for tkinter.

Shows a small popup with help text when the mouse hovers over a widget.
Supports multi-line text and automatic edge-of-screen repositioning.
"""

import tkinter as tk


class Tooltip:
    """Hover tooltip that appears after a short delay near the cursor."""

    _DELAY_MS = 500
    _BG = "#ffffe0"
    _BORDER = "#999999"
    _OFFSET_X = 12
    _OFFSET_Y = 10

    def __init__(self, widget: tk.Widget, text: str):
        self._widget = widget
        self._text = text
        self._tip_window: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value

    def _on_enter(self, event: tk.Event):
        self._schedule(event)

    def _on_leave(self, _event: tk.Event):
        self._cancel()
        self._hide()

    def _schedule(self, event: tk.Event):
        self._cancel()
        self._after_id = self._widget.after(
            self._DELAY_MS, lambda: self._show(event))

    def _cancel(self):
        if self._after_id is not None:
            self._widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self, event: tk.Event):
        if self._tip_window is not None:
            return
        x = event.x_root + self._OFFSET_X
        y = event.y_root + self._OFFSET_Y

        tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        self._tip_window = tw

        label = tk.Label(
            tw, text=self._text, justify=tk.LEFT,
            background=self._BG,
            foreground="#000000",
            relief=tk.SOLID, borderwidth=1,
            font=("TkDefaultFont", 9),
            padx=6, pady=4,
        )
        label.pack()

        # Adjust position to stay on-screen
        tw.update_idletasks()
        tip_w = tw.winfo_reqwidth()
        tip_h = tw.winfo_reqheight()
        screen_w = self._widget.winfo_screenwidth()
        screen_h = self._widget.winfo_screenheight()

        if x + tip_w > screen_w:
            x = screen_w - tip_w - 4
        if y + tip_h > screen_h:
            y = event.y_root - tip_h - 4

        tw.wm_geometry(f"+{x}+{y}")

    def _hide(self):
        if self._tip_window is not None:
            self._tip_window.destroy()
            self._tip_window = None

    def destroy(self):
        """Unbind events and remove any visible tooltip."""
        self._cancel()
        self._hide()
        try:
            self._widget.unbind("<Enter>")
            self._widget.unbind("<Leave>")
            self._widget.unbind("<ButtonPress>")
        except tk.TclError:
            pass


def add_tooltip(widget: tk.Widget, text: str) -> Tooltip:
    """Convenience helper — attach a tooltip to *widget* and return it."""
    return Tooltip(widget, text)
