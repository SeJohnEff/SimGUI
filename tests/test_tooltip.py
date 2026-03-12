"""Tests for the Tooltip widget."""

import os
import tkinter as tk

import pytest

from widgets.tooltip import Tooltip, add_tooltip

# Skip all tests in this module when no display is available (headless CI)
pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="No DISPLAY — headless environment"
)


@pytest.fixture
def root():
    """Create and teardown a Tk root window."""
    root = tk.Tk()
    root.withdraw()  # hide window during tests
    yield root
    root.destroy()


@pytest.fixture
def label(root):
    """A simple label widget to attach tooltips to."""
    lbl = tk.Label(root, text="hover me")
    lbl.pack()
    return lbl


class TestTooltipCreation:
    def test_tooltip_stores_text(self, label):
        tip = Tooltip(label, "Hello\nWorld")
        assert tip.text == "Hello\nWorld"

    def test_add_tooltip_returns_tooltip(self, label):
        tip = add_tooltip(label, "Some text")
        assert isinstance(tip, Tooltip)
        assert tip.text == "Some text"

    def test_text_property_setter(self, label):
        tip = Tooltip(label, "original")
        tip.text = "updated"
        assert tip.text == "updated"


class TestTooltipShowHide:
    def test_show_creates_toplevel(self, label):
        tip = Tooltip(label, "test tip")
        # Simulate an enter event
        event = _fake_event(label, x_root=100, y_root=100)
        tip._show(event)
        assert tip._tip_window is not None
        assert tip._tip_window.winfo_exists()
        tip._hide()

    def test_hide_destroys_toplevel(self, label):
        tip = Tooltip(label, "test tip")
        event = _fake_event(label, x_root=100, y_root=100)
        tip._show(event)
        assert tip._tip_window is not None
        tip._hide()
        assert tip._tip_window is None

    def test_double_show_does_not_create_two(self, label):
        tip = Tooltip(label, "test tip")
        event = _fake_event(label, x_root=100, y_root=100)
        tip._show(event)
        first_window = tip._tip_window
        tip._show(event)
        assert tip._tip_window is first_window

    def test_hide_when_not_shown_is_safe(self, label):
        tip = Tooltip(label, "test tip")
        tip._hide()  # should not raise

    def test_destroy_cleans_up(self, label):
        tip = Tooltip(label, "test tip")
        event = _fake_event(label, x_root=100, y_root=100)
        tip._show(event)
        tip.destroy()
        assert tip._tip_window is None


class TestTooltipText:
    def test_multiline_text(self, label):
        text = "Line 1\nLine 2\nLine 3"
        tip = Tooltip(label, text)
        assert tip.text == text

    def test_unicode_text(self, label):
        text = "\u26a0 Warning: 3 wrong attempts = lock!"
        tip = Tooltip(label, text)
        assert tip.text == text


def _fake_event(widget, x_root=0, y_root=0):
    """Create a minimal fake event object for tooltip positioning."""
    event = type("Event", (), {})()
    event.x_root = x_root
    event.y_root = y_root
    event.widget = widget
    return event
