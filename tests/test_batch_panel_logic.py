"""
Tests for batch_program_panel.py pure functions and progress_panel.py logic.

These tests load the actual source modules with mocked tkinter/deps and call
real logic to maximize coverage without needing a display.
"""
import importlib.util
import os
import sys
import threading
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import unittest.mock as _mock

# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _make_base_mocks():
    """Create minimal fake tkinter/ttk modules."""
    _tk = types.ModuleType("tkinter")
    _tk.W = "w"; _tk.E = "e"; _tk.X = "x"; _tk.LEFT = "left"
    _tk.RIGHT = "right"; _tk.BOTH = "both"; _tk.END = "end"
    _tk.NORMAL = "normal"; _tk.DISABLED = "disabled"
    _tk.HORIZONTAL = "horizontal"; _tk.VERTICAL = "vertical"
    _tk.N = "n"; _tk.S = "s"
    _tk.StringVar = lambda *a, **kw: MagicMock()
    _tk.IntVar = lambda *a, **kw: MagicMock()
    _tk.BooleanVar = lambda *a, value=False, **kw: MagicMock()
    _tk.DoubleVar = lambda *a, **kw: MagicMock()
    _tk.Canvas = lambda *a, **kw: MagicMock()
    _tk.Text = lambda *a, **kw: MagicMock()
    _tk.Widget = object
    _tk.Event = object
    _tk.TclError = Exception
    _tk.Toplevel = lambda *a, **kw: MagicMock()
    _tk.Label = lambda *a, **kw: MagicMock()
    _tk.Frame = lambda *a, **kw: MagicMock()
    _tk.filedialog = MagicMock()
    _tk.messagebox = MagicMock()

    _ttk = types.ModuleType("tkinter.ttk")
    class _FakeFrame:
        def __init__(self, *a, **kw): pass
        def pack(self, **kw): pass
        def grid(self, **kw): pass
        def configure(self, **kw): pass
        def columnconfigure(self, *a, **kw): pass
        def rowconfigure(self, *a, **kw): pass
    _ttk.Frame = _FakeFrame
    class _FakeLF(_FakeFrame): pass
    _ttk.LabelFrame = _FakeLF
    _ttk.Label = lambda *a, **kw: MagicMock()
    _ttk.Entry = lambda *a, **kw: MagicMock()
    _ttk.Button = lambda *a, **kw: MagicMock()
    _ttk.Combobox = lambda *a, **kw: MagicMock()
    _ttk.Progressbar = lambda *a, **kw: MagicMock()
    _ttk.Scrollbar = lambda *a, **kw: MagicMock()
    _ttk.Treeview = lambda *a, **kw: MagicMock()
    _ttk.Spinbox = lambda *a, **kw: MagicMock()
    _ttk.Checkbutton = lambda *a, **kw: MagicMock()
    _ttk.Notebook = lambda *a, **kw: MagicMock()
    _ttk.Separator = lambda *a, **kw: MagicMock()
    _ttk.Style = lambda *a, **kw: MagicMock()
    _tk.ttk = _ttk

    return _tk, _ttk


def _load_batch_module():
    """Load widgets/batch_program_panel.py with all deps mocked."""
    base = os.path.join(os.path.dirname(__file__), "..")
    path = os.path.join(base, "widgets", "batch_program_panel.py")

    _tk, _ttk = _make_base_mocks()
    _theme = MagicMock()
    _theme.ModernTheme.get_color.return_value = "#000"
    _theme.ModernTheme.get_padding.return_value = 4

    # Stub out heavy dependencies
    _mocks = {
        "tkinter": _tk,
        "tkinter.ttk": _ttk,
        "tkinter.filedialog": MagicMock(),
        "tkinter.messagebox": MagicMock(),
        "theme": _theme,
        "widgets.tooltip": MagicMock(),
        "managers.batch_manager": MagicMock(),
        "managers.card_manager": MagicMock(),
        "managers.csv_manager": MagicMock(),
        "managers.settings_manager": MagicMock(),
        "utils": MagicMock(),
        "utils.iccid_utils": MagicMock(),
    }

    spec = importlib.util.spec_from_file_location("widgets.batch_program_panel", path)
    mod = importlib.util.module_from_spec(spec)
    with _mock.patch.dict(sys.modules, _mocks):
        sys.modules["widgets.batch_program_panel"] = mod
        spec.loader.exec_module(mod)

    return mod


# ---------------------------------------------------------------------------
# Tests for apply_imsi_override
# ---------------------------------------------------------------------------

class TestApplyImsiOverride:
    """Tests for the pure function apply_imsi_override."""

    def setup_method(self):
        self.mod = _load_batch_module()

    def test_single_card_default_seq(self):
        """Single card gets base + '00001' as IMSI."""
        cards = [{"ICCID": "12345", "Ki": "aabb"}]
        result = self.mod.apply_imsi_override(cards, "0010100000")
        assert result[0]["IMSI"] == "001010000000001"
        assert result[0]["ICCID"] == "12345"  # untouched

    def test_multiple_cards_sequential(self):
        """Multiple cards get sequential IMSI values."""
        cards = [{"ICCID": f"card{i}"} for i in range(3)]
        result = self.mod.apply_imsi_override(cards, "0010100000", start_seq=1)
        assert result[0]["IMSI"] == "001010000000001"
        assert result[1]["IMSI"] == "001010000000002"
        assert result[2]["IMSI"] == "001010000000003"

    def test_custom_start_seq(self):
        """Custom start_seq offsets the sequence number."""
        cards = [{"ICCID": "abc"}, {"ICCID": "def"}]
        result = self.mod.apply_imsi_override(cards, "0010100000", start_seq=10)
        assert result[0]["IMSI"] == "001010000000010"
        assert result[1]["IMSI"] == "001010000000011"

    def test_returns_copies_not_originals(self):
        """Original card dicts are not mutated."""
        original = {"ICCID": "99", "IMSI": "original"}
        result = self.mod.apply_imsi_override([original], "0010100000")
        assert original["IMSI"] == "original"
        assert result[0]["IMSI"] != "original"

    def test_empty_input(self):
        """Empty input list returns empty list."""
        result = self.mod.apply_imsi_override([], "0010100000")
        assert result == []

    def test_preserves_all_other_fields(self):
        """All other fields besides IMSI are preserved."""
        card = {"ICCID": "111", "Ki": "aabbcc", "OPc": "ddeeff", "ADM1": "12345678"}
        result = self.mod.apply_imsi_override([card], "0010100000")
        assert result[0]["Ki"] == "aabbcc"
        assert result[0]["OPc"] == "ddeeff"
        assert result[0]["ADM1"] == "12345678"

    def test_five_digit_seq_padding(self):
        """Sequence is zero-padded to 5 digits."""
        cards = [{"ICCID": "x"}]
        result = self.mod.apply_imsi_override(cards, "0010100000", start_seq=5)
        assert result[0]["IMSI"].endswith("00005")

    def test_large_seq_number(self):
        """Large sequence number (5 digits) is appended correctly."""
        cards = [{"ICCID": "x"}]
        result = self.mod.apply_imsi_override(cards, "0010100000", start_seq=99999)
        assert result[0]["IMSI"].endswith("99999")

    def test_hundred_cards(self):
        """100 cards all get unique IMSIs."""
        cards = [{"ICCID": str(i)} for i in range(100)]
        result = self.mod.apply_imsi_override(cards, "0010100000", start_seq=1)
        imsis = [r["IMSI"] for r in result]
        assert len(set(imsis)) == 100


# ---------------------------------------------------------------------------
# Tests for apply_range_filter
# ---------------------------------------------------------------------------

class TestApplyRangeFilter:
    """Tests for the pure function apply_range_filter."""

    def setup_method(self):
        self.mod = _load_batch_module()

    def _cards(self, n):
        return [{"ICCID": str(i), "idx": i} for i in range(n)]

    def test_full_range(self):
        """With start=1 and count=N returns all cards."""
        cards = self._cards(5)
        result = self.mod.apply_range_filter(cards, start=1, count=5)
        assert len(result) == 5

    def test_partial_range_from_start(self):
        """start=1 count=3 returns first 3."""
        cards = self._cards(5)
        result = self.mod.apply_range_filter(cards, start=1, count=3)
        assert len(result) == 3
        assert result[0]["idx"] == 0
        assert result[2]["idx"] == 2

    def test_partial_range_mid(self):
        """start=2 count=2 returns cards at index 1 and 2."""
        cards = self._cards(5)
        result = self.mod.apply_range_filter(cards, start=2, count=2)
        assert len(result) == 2
        assert result[0]["idx"] == 1
        assert result[1]["idx"] == 2

    def test_start_beyond_list(self):
        """start beyond list length returns empty list."""
        cards = self._cards(3)
        result = self.mod.apply_range_filter(cards, start=10, count=2)
        assert result == []

    def test_count_zero(self):
        """count=0 returns empty list."""
        cards = self._cards(5)
        result = self.mod.apply_range_filter(cards, start=1, count=0)
        assert result == []

    def test_start_zero_treated_as_one(self):
        """start=0 is clamped to 0-based index 0 (first card)."""
        cards = self._cards(3)
        result = self.mod.apply_range_filter(cards, start=0, count=2)
        assert result[0]["idx"] == 0

    def test_count_truncated_at_end(self):
        """count exceeding remaining cards returns all remaining."""
        cards = self._cards(3)
        result = self.mod.apply_range_filter(cards, start=2, count=100)
        assert len(result) == 2
        assert result[0]["idx"] == 1

    def test_returns_copies(self):
        """Returns shallow copies, not original dict references."""
        cards = self._cards(2)
        result = self.mod.apply_range_filter(cards, start=1, count=2)
        result[0]["ICCID"] = "changed"
        assert cards[0]["ICCID"] == "0"  # original unchanged

    def test_empty_input(self):
        """Empty input list returns empty list."""
        result = self.mod.apply_range_filter([], start=1, count=5)
        assert result == []

    def test_single_last_card(self):
        """Can select just the last card."""
        cards = self._cards(5)
        result = self.mod.apply_range_filter(cards, start=5, count=1)
        assert len(result) == 1
        assert result[0]["idx"] == 4


# ---------------------------------------------------------------------------
# Tests for ProgressPanel logic (fake self approach)
# ---------------------------------------------------------------------------

class TestProgressPanelLogic:
    """Tests for ProgressPanel using real PyQt6 widgets."""

    def test_set_progress_basic(self, qtbot):
        """set_progress updates bar value and percentage label."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.set_progress(50, 100, label="Working")
        qtbot.wait(50)
        assert panel._progress_bar.value() == 50
        assert "50%" in panel._percent_label.text()

    def test_set_progress_zero_maximum(self, qtbot):
        """set_progress with maximum=0 shows 0% without division error."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.set_progress(0, 0)
        qtbot.wait(50)
        assert "0%" in panel._percent_label.text()

    def test_set_progress_with_label(self, qtbot):
        """set_progress with label param updates progress label text."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.set_progress(25, 100, label="Loading...")
        qtbot.wait(50)
        assert panel._progress_label.text() == "Loading..."

    def test_set_progress_without_label(self, qtbot):
        """set_progress without label does not update progress_label."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        original_text = panel._progress_label.text()
        panel.set_progress(25, 100)
        qtbot.wait(50)
        assert panel._progress_label.text() == original_text

    def test_set_progress_skipped_when_widget_gone(self, qtbot):
        """set_progress does nothing when widget is destroyed."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.deleteLater()
        qtbot.wait(50)
        panel.set_progress(99, 100)
        qtbot.wait(50)
        assert panel._progress_bar.value() == 0

    def test_set_indeterminate_running(self, qtbot):
        """set_indeterminate(running=True) switches to indeterminate mode."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.set_indeterminate(running=True)
        qtbot.wait(50)
        assert panel._progress_bar.maximum() == 0

    def test_set_indeterminate_stopped(self, qtbot):
        """set_indeterminate(running=False) switches back to determinate."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.set_indeterminate(running=False)
        qtbot.wait(50)
        assert panel._progress_bar.maximum() == 100

    def test_set_indeterminate_skipped_when_gone(self, qtbot):
        """set_indeterminate skipped when widget does not exist."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.deleteLater()
        qtbot.wait(50)
        original_max = panel._progress_bar.maximum()
        panel.set_indeterminate(running=True)
        qtbot.wait(50)
        assert panel._progress_bar.maximum() == original_max

    def test_log_appends_message(self, qtbot):
        """log() appends a timestamped message to the log text."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.log("Test event")
        qtbot.wait(50)
        assert "Test event" in panel._log_text.toPlainText()

    def test_log_skipped_when_gone(self, qtbot):
        """log() does nothing when widget does not exist."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        original_text = panel._log_text.toPlainText()
        panel.deleteLater()
        qtbot.wait(50)
        panel.log("Should not appear")
        qtbot.wait(50)
        assert panel._log_text.toPlainText() == original_text

    def test_clear_log_empties_text(self, qtbot):
        """clear_log() removes all content from log text widget."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.log("existing content")
        qtbot.wait(50)
        panel.clear_log()
        qtbot.wait(50)
        assert panel._log_text.toPlainText() == ""

    def test_clear_log_skipped_when_gone(self, qtbot):
        """clear_log() does nothing when widget does not exist."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.log("keep this")
        qtbot.wait(50)
        original_text = panel._log_text.toPlainText()
        panel.deleteLater()
        qtbot.wait(50)
        panel.clear_log()
        qtbot.wait(50)
        assert panel._log_text.toPlainText() == original_text

    def test_reset_clears_cancel_event(self, qtbot):
        """reset() clears the cancel event and resets UI."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel._cancel_event.set()
        panel.reset()
        qtbot.wait(50)
        assert not panel._cancel_event.is_set()

    def test_reset_sets_idle_text(self, qtbot):
        """reset() sets progress label back to 'Idle'."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.reset()
        qtbot.wait(50)
        assert panel._progress_label.text() == "Idle"

    def test_reset_skipped_when_gone(self, qtbot):
        """reset() skips UI update when widget is gone."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel._cancel_event.set()
        panel.deleteLater()
        qtbot.wait(50)
        panel.reset()
        qtbot.wait(50)
        assert not panel._cancel_event.is_set()

    def test_cancel_sets_event(self, qtbot):
        """cancel() sets the cancel event."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        assert not panel._cancel_event.is_set()
        panel.cancel()
        qtbot.wait(50)
        assert panel._cancel_event.is_set()

    def test_cancelled_property_false(self, qtbot):
        """cancelled property returns False when not cancelled."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        assert panel.cancelled is False

    def test_cancelled_property_true(self, qtbot):
        """cancelled property returns True after cancel()."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel._cancel_event.set()
        assert panel.cancelled is True

    def test_set_progress_full(self, qtbot):
        """set_progress at 100% shows 100%."""
        from widgets.progress_panel import ProgressPanel
        panel = ProgressPanel()
        qtbot.addWidget(panel)
        panel.set_progress(100, 100, label="Done")
        qtbot.wait(50)
        assert "100%" in panel._percent_label.text()
        assert panel._progress_label.text() == "Done"
