"""Tests that execute actual widget source code with mocked tkinter.

Uses the 'unbound method with fake self' pattern to call actual source lines.
"""

import os
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

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


# ---------------------------------------------------------------------------
# CardStatusPanel logic tests
# ---------------------------------------------------------------------------

class TestCardStatusPanelMethods:
    """Tests for CardStatusPanel methods using fake self."""

    def _make_fake_panel(self):
        """Create a fake self that has all the attributes CardStatusPanel methods use."""

        class FakePanel:
            on_detect_callback = None
            on_authenticate_callback = None

            class _FakeVar:
                def __init__(self):
                    self._v = "-"

                def set(self, v):
                    self._v = v

                def get(self):
                    return self._v

            def __init__(self):
                self._info_vars = {
                    "card_type": self._FakeVar(),
                    "imsi": self._FakeVar(),
                    "iccid": self._FakeVar(),
                    "acc": self._FakeVar(),
                    "spn": self._FakeVar(),
                    "fplmn": self._FakeVar(),
                    "auth": self._FakeVar(),
                    "source_file": self._FakeVar(),
                }
                self._num_info_rows = 8
                self.status_indicator = _FakeWidget()
                self.status_indicator.delete = lambda *a: None
                self.status_indicator.create_oval = lambda *a, **kw: 1
                self.status_label = _FakeWidget()
                self.status_label.configure = lambda **kw: None

        return FakePanel()

    def _get_csp_class(self):
        """Import CardStatusPanel with mocked tkinter via importlib."""
        import importlib
        import importlib.util
        import types

        _tk = _mock.MagicMock()
        _ttk = _mock.MagicMock()
        _ttk.LabelFrame = _FakeWidget  # base class
        _ttk.Frame = lambda *a, **kw: _FakeWidget()
        _ttk.Label = lambda *a, **kw: _FakeWidget()
        _ttk.Entry = lambda *a, **kw: _FakeWidget()
        _ttk.Button = lambda *a, **kw: _FakeWidget()
        _tk.Canvas = lambda *a, **kw: _FakeWidget()
        _tk.StringVar = lambda *a, **kw: _mock.MagicMock()
        _tk.W = "w"
        _tk.E = "e"
        _tk.X = "x"
        _tk.LEFT = "left"
        # CRITICAL: 'from tkinter import ttk' resolves to _tk.ttk, not _ttk.
        _tk.ttk = _ttk

        _th = _mock.MagicMock()
        _th.ModernTheme.get_color.return_value = "#000000"
        _th.ModernTheme.get_padding.side_effect = lambda k: 8
        _tp = _mock.MagicMock()

        # Remove ALL cached widget modules to prevent MagicMock leaking
        for k in list(sys.modules.keys()):
            if k.startswith("widgets") and "test_" not in k:
                del sys.modules[k]

        # Create a real module for 'widgets' package to prevent
        # MagicMock attribute access from hijacking submodule imports.
        _widgets_pkg = types.ModuleType("widgets")
        _widgets_pkg.__path__ = [
            os.path.join(os.path.dirname(__file__), "..", "widgets")
        ]

        with _mock.patch.dict(sys.modules, {
            "tkinter": _tk, "tkinter.ttk": _ttk,
            "theme": _th,
            "widgets": _widgets_pkg, "widgets.tooltip": _tp,
        }):
            spec = importlib.util.spec_from_file_location(
                "widgets.card_status_panel",
                os.path.join(os.path.dirname(__file__), "..", "widgets", "card_status_panel.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules["widgets.card_status_panel"] = mod
            spec.loader.exec_module(mod)
            CardStatusPanel = mod.CardStatusPanel
        return CardStatusPanel

    def test_set_status_waiting(self):
        """set_status('waiting') executes the method."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()
        _th = _mock.MagicMock()
        _th.ModernTheme.get_color.return_value = "#FF9500"
        with _mock.patch.dict(sys.modules, {"theme": _th}):
            csp.set_status(panel, "waiting", "Waiting for card...")

    def test_set_status_authenticated(self):
        """set_status('authenticated') executes."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()
        _th = _mock.MagicMock()
        _th.ModernTheme.get_color.return_value = "#34C759"
        with _mock.patch.dict(sys.modules, {"theme": _th}):
            csp.set_status(panel, "authenticated", "OK")

    def test_set_status_error(self):
        """set_status('error') executes."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()
        csp.set_status(panel, "error", "Error!")

    def test_set_status_unknown_state(self):
        """set_status with unknown state uses disabled color."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()
        csp.set_status(panel, "unknown_state", "msg")

    def test_set_card_info(self):
        """set_card_info updates the info vars."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()
        csp.set_card_info(panel, card_type="SJA5", imsi="001010", iccid="89001")
        assert panel._info_vars["card_type"].get() == "SJA5"
        assert panel._info_vars["imsi"].get() == "001010"

    def test_set_card_info_partial(self):
        """set_card_info with only card_type updates just that field."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()
        csp.set_card_info(panel, card_type="SJA2")
        assert panel._info_vars["card_type"].get() == "SJA2"
        # imsi unchanged
        assert panel._info_vars["imsi"].get() == "-"

    def test_set_auth_status_true(self):
        """set_auth_status(True) sets auth to 'Yes'."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()
        csp.set_auth_status(panel, True)
        assert panel._info_vars["auth"].get() == "Yes"

    def test_set_auth_status_false(self):
        """set_auth_status(False) sets auth to 'No'."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()
        csp.set_auth_status(panel, False)
        assert panel._info_vars["auth"].get() == "No"

    def test_set_simulator_info(self):
        """set_simulator_info creates label and shows virtual card info."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()

        # Need to add label infrastructure to the fake panel
        label = _FakeWidget()
        label.configure = lambda **kw: label._cfg.update(kw)
        label.grid = lambda **kw: None
        label.grid_remove = lambda: None

        # Pre-create _sim_label so the `if not hasattr` branch is skipped
        panel._sim_label = label
        csp.set_simulator_info(panel, card_index=2, total_cards=10)
        assert "3 of 10" in label._cfg.get("text", "")

    def test_set_simulator_info_none_removes(self):
        """set_simulator_info(None, None) calls grid_remove."""
        csp = self._get_csp_class()
        panel = self._make_fake_panel()
        removed = []
        label = _FakeWidget()
        label.configure = lambda **kw: None
        label.grid = lambda **kw: None
        label.grid_remove = lambda: removed.append(True)
        panel._sim_label = label
        csp.set_simulator_info(panel, card_index=None, total_cards=None)
        assert len(removed) == 1
