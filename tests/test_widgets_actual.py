"""DEPRECATED: Tests that execute actual widget source code with mocked tkinter.

PyQt6 Migration: This test file was written for tkinter widgets. The app has
migrated to PyQt6, but this test file uses tkinter mocking which is incompatible.

Tests are skipped pending refactoring to use proper PyQt6 testing patterns.
See test_batch_program_panel.py for the new PyQt6 test pattern.
"""

import os
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skip(reason="tkinter mocking incompatible with PyQt6 migration")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest.mock as _mock

# ---------------------------------------------------------------------------
# Tooltip tests — import real tooltip module (no tk needed at import time)
# ---------------------------------------------------------------------------

class _FakeWidget:
    """Fake tkinter widget that stores config and bindings."""

    def __init__(self, *a, **kw):
        self._cfg = {}
        self._bindings = {}
        self._after_id = None
        self._destroyed = False

    def after(self, delay, callback):
        return f"after_{id(callback)}"

    def after_cancel(self, id_):
        pass

    def bind(self, event, handler=None, add=None):
        if handler:
            self._bindings[event] = handler

    def unbind(self, event):
        self._bindings.pop(event, None)

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def wm_overrideredirect(self, v=None):
        pass

    def wm_geometry(self, s=None):
        pass

    def update_idletasks(self):
        pass

    def winfo_reqwidth(self):
        return 100

    def winfo_reqheight(self):
        return 30

    def destroy(self):
        self._destroyed = True

    def pack(self, **kw):
        pass


class _FakeToplevel(_FakeWidget):
    pass


class _FakeLabel(_FakeWidget):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._text = kw.get("text", "")


# ---------------------------------------------------------------------------
# Tooltip actual tests
# ---------------------------------------------------------------------------

class TestTooltipActual:
    """Tests for widgets/tooltip.py that execute the actual source code."""

    def _get_tooltip(self):
        """Import the real Tooltip class with tkinter mocked at Toplevel level."""
        _tk = _mock.MagicMock()
        _tk.Toplevel = _FakeToplevel
        _tk.LEFT = "left"
        _tk.SOLID = "solid"
        _tk.Label = lambda *a, **kw: _FakeLabel(*a, **kw)

        for k in list(sys.modules.keys()):
            if k == "widgets.tooltip":
                del sys.modules[k]

        with _mock.patch.dict(sys.modules, {"tkinter": _tk}):
            from widgets.tooltip import Tooltip, add_tooltip
        return Tooltip, add_tooltip, _tk

    def test_tooltip_text_getter(self):
        """Tooltip.text property returns the text."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello world")
        assert t.text == "Hello world"

    def test_tooltip_text_setter(self):
        """Tooltip.text setter updates the text."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello")
        t.text = "Updated"
        assert t.text == "Updated"

    def test_tooltip_on_leave_cancels_and_hides(self):
        """_on_leave cancels pending show and hides tooltip."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello")
        t._after_id = "fake_id"
        t._on_leave(MagicMock())
        assert t._after_id is None

    def test_tooltip_hide_destroys_window(self):
        """_hide() destroys the tip window."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello")
        fake_tw = _FakeWidget()
        t._tip_window = fake_tw
        t._hide()
        assert t._tip_window is None
        assert fake_tw._destroyed is True

    def test_tooltip_cancel_with_id(self):
        """_cancel() cancels the after callback."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello")
        t._after_id = "some_id"
        t._cancel()
        assert t._after_id is None

    def test_tooltip_cancel_without_id(self):
        """_cancel() when no after_id does nothing."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello")
        t._cancel()  # should not raise

    def test_tooltip_show_already_visible_noop(self):
        """_show() returns early if tooltip already visible."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello")
        fake_tw = _FakeWidget()
        t._tip_window = fake_tw
        fake_event = MagicMock()
        fake_event.x_root = 100
        fake_event.y_root = 100
        t._show(fake_event)
        assert t._tip_window is fake_tw  # unchanged

    def test_tooltip_show_creates_window(self):
        """_show() creates a tooltip window when called."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello")
        assert t._tip_window is None
        fake_event = MagicMock()
        fake_event.x_root = 100
        fake_event.y_root = 100
        t._show(fake_event)
        assert t._tip_window is not None

    def test_tooltip_destroy_cleans_up(self):
        """destroy() hides the window and unbinds events."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello")
        t.destroy()
        assert t._tip_window is None

    def test_tooltip_on_enter_schedules(self):
        """_on_enter schedules a show via after."""
        Tooltip, _, _ = self._get_tooltip()
        widget = _FakeWidget()
        t = Tooltip(widget, "Hello")
        fake_event = MagicMock()
        t._on_enter(fake_event)
        # after_id should be set (either real or fake)
        assert t._after_id is not None

    def test_add_tooltip_returns_tooltip(self):
        """add_tooltip() returns a Tooltip instance."""
        Tooltip, add_tooltip, _ = self._get_tooltip()
        widget = _FakeWidget()
        result = add_tooltip(widget, "Some text")
        assert isinstance(result, Tooltip)


# ---------------------------------------------------------------------------
# Validation — cover missed line 108
# ---------------------------------------------------------------------------

class TestValidationLine108:
    """Cover utils/validation.py line 108."""

    def test_validate_customer_id_2_digits(self):
        """validate_customer_id accepts exactly 2 digits."""
        from utils.validation import validate_customer_id
        assert validate_customer_id("12") is None

    def test_validate_customer_id_00(self):
        """validate_customer_id accepts '00'."""
        from utils.validation import validate_customer_id
        assert validate_customer_id("00") is None

    def test_validate_customer_id_99(self):
        """validate_customer_id accepts '99'."""
        from utils.validation import validate_customer_id
        assert validate_customer_id("99") is None

    def test_validate_customer_id_too_long(self):
        """validate_customer_id rejects 3 digits."""
        from utils.validation import validate_customer_id
        assert validate_customer_id("123") is not None

    def test_validate_customer_id_non_digit(self):
        """validate_customer_id rejects non-digit chars."""
        from utils.validation import validate_customer_id
        assert validate_customer_id("ab") is not None

