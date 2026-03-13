"""
Comprehensive tests for widget source code — uses importlib.util to load
source files directly, bypassing widgets/__init__.py which would pull in
all tkinter-heavy widgets.

Covers: widgets/card_status_panel.py, widgets/tooltip.py
"""
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest.mock as _mock


# ---------------------------------------------------------------------------
# Shared fake widget infrastructure
# ---------------------------------------------------------------------------

class _FakeWidget:
    """Minimal fake tkinter widget for tests."""

    def __init__(self, *a, **kw):
        self._cfg = {}

    def grid(self, **kw):
        pass

    def pack(self, **kw):
        pass

    def configure(self, **kw):
        self._cfg.update(kw)

    def delete(self, *a):
        pass

    def create_oval(self, *a, **kw):
        return 1

    def columnconfigure(self, col, **kw):
        pass

    def grid_remove(self):
        pass

    def after(self, delay, callback):
        return f"after_{id(callback)}"

    def after_cancel(self, id_):
        pass

    def bind(self, event, handler=None, add=None):
        pass

    def unbind(self, event):
        pass

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


class _FakeLabelFrame(_FakeWidget):
    pass


class _FakeVar:
    def __init__(self, *a, value="-", **kw):
        self._v = value

    def set(self, v):
        self._v = v

    def get(self):
        return self._v


def _make_tk_mocks():
    """Create proper fake tkinter modules."""
    _tk_mod = types.ModuleType("tkinter")
    _tk_mod.W = "w"
    _tk_mod.E = "e"
    _tk_mod.X = "x"
    _tk_mod.LEFT = "left"
    _tk_mod.SOLID = "solid"
    _tk_mod.HORIZONTAL = "horizontal"
    _tk_mod.Canvas = lambda *a, **kw: _FakeWidget()
    _tk_mod.StringVar = _FakeVar
    _tk_mod.TclError = Exception
    _tk_mod.Toplevel = lambda *a, **kw: _FakeWidget()
    _tk_mod.Label = lambda *a, **kw: _FakeWidget()
    _tk_mod.Event = object
    _tk_mod.Widget = _FakeWidget  # needed for type annotations

    _ttk_mod = types.ModuleType("tkinter.ttk")
    _ttk_mod.LabelFrame = _FakeLabelFrame
    _ttk_mod.Frame = lambda *a, **kw: _FakeWidget()
    _ttk_mod.Label = lambda *a, **kw: _FakeWidget()
    _ttk_mod.Entry = lambda *a, **kw: _FakeWidget()
    _ttk_mod.Button = lambda *a, **kw: _FakeWidget()
    _tk_mod.ttk = _ttk_mod

    return _tk_mod, _ttk_mod


def _load_module_from_file(file_path, module_name, extra_mocks=None):
    """Load a source file as a module with specified sys.modules overrides."""
    _tk_mod, _ttk_mod = _make_tk_mocks()

    _th = _mock.MagicMock()
    _th.ModernTheme.get_color.return_value = "#000000"
    _th.ModernTheme.get_padding.side_effect = lambda k: 8

    _tp_mod = types.ModuleType("widgets.tooltip")
    _tp_mod.add_tooltip = lambda w, t: None
    _tp_mod.Tooltip = lambda *a, **kw: None

    mocks = {
        "tkinter": _tk_mod,
        "tkinter.ttk": _ttk_mod,
        "theme": _th,
        "widgets.tooltip": _tp_mod,
    }
    if extra_mocks:
        mocks.update(extra_mocks)

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)

    with _mock.patch.dict(sys.modules, mocks):
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)

    return mod


# ---------------------------------------------------------------------------
# Tooltip tests
# ---------------------------------------------------------------------------

def _load_tooltip_module():
    """Load widgets/tooltip.py with mocked tkinter."""
    base = os.path.join(os.path.dirname(__file__), "..")
    path = os.path.join(base, "widgets", "tooltip.py")
    _tk_mod, _ttk_mod = _make_tk_mocks()

    # Override Toplevel to be a proper class we can track
    class _FakeToplevel(_FakeWidget):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._destroyed = False

        def destroy(self):
            self._destroyed = True

    _tk_mod.Toplevel = _FakeToplevel
    _tk_mod.Label = lambda *a, **kw: _FakeWidget()

    spec = importlib.util.spec_from_file_location("widgets.tooltip", path)
    mod = importlib.util.module_from_spec(spec)
    with _mock.patch.dict(sys.modules, {"tkinter": _tk_mod, "tkinter.ttk": _ttk_mod}):
        sys.modules["widgets.tooltip"] = mod
        spec.loader.exec_module(mod)

    return mod, _FakeToplevel


class TestTooltipActual:
    """Tests for widgets/tooltip.py that execute actual source code."""

    def test_tooltip_init_sets_attributes(self):
        """Tooltip.__init__ correctly initialises all attributes."""
        mod, _ = _load_tooltip_module()
        widget = _FakeWidget()
        tt = mod.Tooltip(widget, "Hello")
        assert tt.text == "Hello"
        assert tt._widget is widget
        assert tt._tip_window is None
        assert tt._after_id is None

    def test_tooltip_text_getter(self):
        """text property returns current text."""
        mod, _ = _load_tooltip_module()
        tt = mod.Tooltip(_FakeWidget(), "GetMe")
        assert tt.text == "GetMe"

    def test_tooltip_text_setter(self):
        """text property setter updates _text attribute."""
        mod, _ = _load_tooltip_module()
        tt = mod.Tooltip(_FakeWidget(), "Old")
        tt.text = "New"
        assert tt.text == "New"
        assert tt._text == "New"

    def test_tooltip_cancel_with_none_id(self):
        """_cancel is safe when _after_id is None."""
        mod, _ = _load_tooltip_module()
        tt = mod.Tooltip(_FakeWidget(), "tip")
        tt._cancel()  # should not raise
        assert tt._after_id is None

    def test_tooltip_cancel_clears_after_id(self):
        """_cancel calls after_cancel and sets _after_id to None."""
        mod, _ = _load_tooltip_module()
        cancelled = []
        widget = _FakeWidget()
        widget.after_cancel = lambda i: cancelled.append(i)
        tt = mod.Tooltip(widget, "tip")
        tt._after_id = "some_id"
        tt._cancel()
        assert tt._after_id is None
        assert "some_id" in cancelled

    def test_tooltip_schedule_sets_after_id(self):
        """_schedule stores the after() return value in _after_id."""
        mod, _ = _load_tooltip_module()
        widget = _FakeWidget()
        tt = mod.Tooltip(widget, "tip")
        event = _mock.MagicMock()
        event.x_root = 50
        event.y_root = 50
        tt._schedule(event)
        assert tt._after_id is not None

    def test_tooltip_on_enter_triggers_schedule(self):
        """_on_enter calls _schedule which sets _after_id."""
        mod, _ = _load_tooltip_module()
        widget = _FakeWidget()
        tt = mod.Tooltip(widget, "tip")
        event = _mock.MagicMock()
        event.x_root = 50
        event.y_root = 50
        tt._on_enter(event)
        assert tt._after_id is not None

    def test_tooltip_on_leave_cancels_scheduled(self):
        """_on_leave cancels a scheduled tip and clears after_id."""
        mod, _ = _load_tooltip_module()
        cancelled = []
        widget = _FakeWidget()
        widget.after_cancel = lambda i: cancelled.append(i)
        tt = mod.Tooltip(widget, "tip")
        tt._after_id = "existing_id"
        event = _mock.MagicMock()
        tt._on_leave(event)
        assert tt._after_id is None

    def test_tooltip_hide_no_window(self):
        """_hide does nothing gracefully when no tip window exists."""
        mod, _ = _load_tooltip_module()
        tt = mod.Tooltip(_FakeWidget(), "tip")
        tt._hide()  # must not raise
        assert tt._tip_window is None

    def test_tooltip_hide_destroys_window(self):
        """_hide destroys tip window and resets _tip_window to None."""
        mod, _ = _load_tooltip_module()
        tt = mod.Tooltip(_FakeWidget(), "tip")
        fake_tip = _FakeWidget()
        tt._tip_window = fake_tip
        tt._hide()
        assert tt._tip_window is None
        assert getattr(fake_tip, "_destroyed", False)

    def test_tooltip_show_when_already_visible(self):
        """_show returns immediately if tip is already shown."""
        mod, _ = _load_tooltip_module()
        tt = mod.Tooltip(_FakeWidget(), "tip")
        existing = _FakeWidget()
        tt._tip_window = existing
        event = _mock.MagicMock()
        event.x_root = 100
        event.y_root = 100
        tt._show(event)
        assert tt._tip_window is existing  # unchanged

    def test_tooltip_show_creates_toplevel(self):
        """_show creates a Toplevel window when none exists."""
        mod, FakeToplevel = _load_tooltip_module()
        tt = mod.Tooltip(_FakeWidget(), "Hello tooltip")
        event = _mock.MagicMock()
        event.x_root = 100
        event.y_root = 100
        tt._show(event)
        assert tt._tip_window is not None
        assert isinstance(tt._tip_window, FakeToplevel)

    def test_tooltip_show_adjusts_right_edge(self):
        """_show clamps x position when tooltip would overflow right."""
        mod, _ = _load_tooltip_module()
        widget = _FakeWidget()
        widget.winfo_screenwidth = lambda: 110  # small screen
        widget.winfo_reqwidth = lambda: 100
        tt = mod.Tooltip(widget, "tip")
        event = _mock.MagicMock()
        event.x_root = 100  # would place tip at 112, beyond 110
        event.y_root = 50
        tt._show(event)
        assert tt._tip_window is not None

    def test_tooltip_show_adjusts_bottom_edge(self):
        """_show clamps y position when tooltip would overflow bottom."""
        mod, _ = _load_tooltip_module()
        widget = _FakeWidget()
        widget.winfo_screenheight = lambda: 80
        widget.winfo_reqheight = lambda: 30
        tt = mod.Tooltip(widget, "tip")
        event = _mock.MagicMock()
        event.x_root = 50
        event.y_root = 75  # would overflow
        tt._show(event)
        assert tt._tip_window is not None

    def test_tooltip_destroy_cleans_up(self):
        """destroy() hides tip, cancels scheduled show, and unbinds events."""
        mod, _ = _load_tooltip_module()
        widget = _FakeWidget()
        tt = mod.Tooltip(widget, "tip")
        tt._after_id = "pending"
        tt.destroy()
        assert tt._after_id is None
        assert tt._tip_window is None

    def test_tooltip_destroy_with_visible_tip(self):
        """destroy() also destroys any currently visible tip window."""
        mod, _ = _load_tooltip_module()
        tt = mod.Tooltip(_FakeWidget(), "tip")
        fake = _FakeWidget()
        tt._tip_window = fake
        tt.destroy()
        assert tt._tip_window is None
        assert getattr(fake, "_destroyed", False)

    def test_add_tooltip_returns_tooltip_instance(self):
        """add_tooltip convenience function returns a Tooltip."""
        mod, _ = _load_tooltip_module()
        widget = _FakeWidget()
        result = mod.add_tooltip(widget, "the text")
        assert isinstance(result, mod.Tooltip)
        assert result.text == "the text"


# ---------------------------------------------------------------------------
# CardStatusPanel tests
# ---------------------------------------------------------------------------

def _load_csp_module():
    """Load widgets/card_status_panel.py with mocked deps."""
    base = os.path.join(os.path.dirname(__file__), "..")
    path = os.path.join(base, "widgets", "card_status_panel.py")
    return _load_module_from_file(path, "widgets.card_status_panel")


def _make_fake_panel():
    """Create fake 'self' object for CardStatusPanel unbound method calls."""

    class FakePanel:
        on_detect_callback = None
        on_authenticate_callback = None

        def __init__(self):
            self._info_vars = {
                "card_type": _FakeVar("-"),
                "imsi": _FakeVar("-"),
                "iccid": _FakeVar("-"),
                "auth": _FakeVar("-"),
            }
            self.status_indicator = _FakeWidget()
            self.status_label = _FakeWidget()

    return FakePanel()


class TestCardStatusPanelMethods:
    """Tests for CardStatusPanel methods using actual source code via importlib."""

    def _csp(self):
        return _load_csp_module().CardStatusPanel

    def test_set_status_waiting(self):
        """set_status('waiting') updates the status label text."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_status(panel, "waiting", "Waiting for card...")
        assert panel.status_label._cfg.get("text") == "Waiting for card..."

    def test_set_status_detected(self):
        """set_status('detected') uses the accent color."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_status(panel, "detected", "Card detected")
        assert panel.status_label._cfg.get("text") == "Card detected"

    def test_set_status_authenticated(self):
        """set_status('authenticated') uses the success color."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_status(panel, "authenticated", "All good")
        assert panel.status_label._cfg.get("text") == "All good"

    def test_set_status_error(self):
        """set_status('error') uses the error color."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_status(panel, "error", "Something went wrong")
        assert panel.status_label._cfg.get("text") == "Something went wrong"

    def test_set_status_unknown_state(self):
        """set_status with unknown state falls back to disabled color."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_status(panel, "no_such_state", "Mystery")
        assert panel.status_label._cfg.get("text") == "Mystery"

    def test_set_status_default_message(self):
        """set_status without message arg uses empty string."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_status(panel, "waiting")
        assert panel.status_label._cfg.get("text") == ""

    def test_set_card_info_all_three(self):
        """set_card_info updates card_type, imsi, and iccid."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_card_info(panel, card_type="SJA5", imsi="001010123456789", iccid="8901234567890")
        assert panel._info_vars["card_type"].get() == "SJA5"
        assert panel._info_vars["imsi"].get() == "001010123456789"
        assert panel._info_vars["iccid"].get() == "8901234567890"

    def test_set_card_info_card_type_only(self):
        """set_card_info with only card_type leaves imsi and iccid unchanged."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_card_info(panel, card_type="SJA2")
        assert panel._info_vars["card_type"].get() == "SJA2"
        assert panel._info_vars["imsi"].get() == "-"
        assert panel._info_vars["iccid"].get() == "-"

    def test_set_card_info_imsi_only(self):
        """set_card_info with only imsi leaves others unchanged."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_card_info(panel, imsi="001010000000001")
        assert panel._info_vars["imsi"].get() == "001010000000001"
        assert panel._info_vars["card_type"].get() == "-"

    def test_set_card_info_iccid_only(self):
        """set_card_info with only iccid updates just iccid."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_card_info(panel, iccid="89012345678901234")
        assert panel._info_vars["iccid"].get() == "89012345678901234"

    def test_set_card_info_no_args(self):
        """set_card_info with all None does not change any fields."""
        csp = self._csp()
        panel = _make_fake_panel()
        panel._info_vars["card_type"].set("Preset")
        csp.set_card_info(panel)
        assert panel._info_vars["card_type"].get() == "Preset"

    def test_set_auth_status_true(self):
        """set_auth_status(True) sets auth to 'Yes'."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_auth_status(panel, True)
        assert panel._info_vars["auth"].get() == "Yes"

    def test_set_auth_status_false(self):
        """set_auth_status(False) sets auth to 'No'."""
        csp = self._csp()
        panel = _make_fake_panel()
        csp.set_auth_status(panel, False)
        assert panel._info_vars["auth"].get() == "No"

    def test_set_simulator_info_shows_with_existing_label(self):
        """set_simulator_info shows 'X of Y' text with existing _sim_label."""
        csp = self._csp()
        panel = _make_fake_panel()
        label = _FakeWidget()
        panel._sim_label = label
        csp.set_simulator_info(panel, card_index=2, total_cards=10)
        assert "3 of 10" in label._cfg.get("text", "")

    def test_set_simulator_info_first_card(self):
        """set_simulator_info with card_index=0 shows '1 of N'."""
        csp = self._csp()
        panel = _make_fake_panel()
        label = _FakeWidget()
        panel._sim_label = label
        csp.set_simulator_info(panel, card_index=0, total_cards=1)
        assert "1 of 1" in label._cfg.get("text", "")

    def test_set_simulator_info_none_calls_grid_remove(self):
        """set_simulator_info(None, None) calls grid_remove on the label."""
        csp = self._csp()
        panel = _make_fake_panel()
        removed = []
        label = _FakeWidget()
        label.grid_remove = lambda: removed.append(True)
        panel._sim_label = label
        csp.set_simulator_info(panel, card_index=None, total_cards=None)
        assert len(removed) == 1

    def test_set_simulator_info_creates_label(self):
        """set_simulator_info creates _sim_label attribute when absent."""
        csp = self._csp()
        panel = _make_fake_panel()
        # No _sim_label yet — the method should create one
        assert not hasattr(panel, "_sim_label")
        csp.set_simulator_info(panel, card_index=0, total_cards=3)
        assert hasattr(panel, "_sim_label")
