"""Tests for widgets.toast — non-blocking overlay notifications."""

import pytest


def _require_display():
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        return root
    except Exception:
        pytest.skip("No display available")


class TestShowToast:
    def test_creates_toplevel(self):
        import tkinter as tk
        root = _require_display()
        try:
            from widgets.toast import show_toast
            toast = show_toast(root, "Hello", duration=100)
            assert toast.winfo_exists()
            toast.destroy()
        finally:
            root.destroy()

    def test_levels(self):
        import tkinter as tk
        root = _require_display()
        try:
            from widgets.toast import show_toast
            for level in ("info", "success", "warning", "error"):
                t = show_toast(root, f"Level: {level}", level=level, duration=100)
                assert t.winfo_exists()
                t.destroy()
        finally:
            root.destroy()

    def test_dismiss_button(self):
        import tkinter as tk
        root = _require_display()
        try:
            from widgets.toast import show_toast, _dismiss
            toast = show_toast(root, "Test dismiss", duration=60000)
            assert toast.winfo_exists()
            _dismiss(toast)
            assert not toast.winfo_exists()
        finally:
            root.destroy()

    def test_dismiss_already_destroyed(self):
        """Dismissing an already-destroyed toast should not raise."""
        import tkinter as tk
        root = _require_display()
        try:
            from widgets.toast import show_toast, _dismiss
            toast = show_toast(root, "Gone", duration=60000)
            toast.destroy()
            _dismiss(toast)  # Should not raise
        finally:
            root.destroy()

    def test_default_selected_path_none(self):
        """Toast returns a Toplevel."""
        import tkinter as tk
        root = _require_display()
        try:
            from widgets.toast import show_toast
            toast = show_toast(root, "msg")
            assert isinstance(toast, tk.Toplevel)
            toast.destroy()
        finally:
            root.destroy()
