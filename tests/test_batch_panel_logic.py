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

def _load_progress_module():
    """Load widgets/progress_panel.py with mocked tkinter."""
    base = os.path.join(os.path.dirname(__file__), "..")
    path = os.path.join(base, "widgets", "progress_panel.py")

    _tk, _ttk = _make_base_mocks()

    class _FakeFr:
        def __init__(self, *a, **kw): pass
        def pack(self, **kw): pass
        def grid(self, **kw): pass
        def configure(self, **kw): pass

    _ttk.Frame = _FakeFr

    _mocks = {
        "tkinter": _tk,
        "tkinter.ttk": _ttk,
        "widgets.tooltip": MagicMock(),
    }

    spec = importlib.util.spec_from_file_location("widgets.progress_panel", path)
    mod = importlib.util.module_from_spec(spec)
    with _mock.patch.dict(sys.modules, _mocks):
        sys.modules["widgets.progress_panel"] = mod
        spec.loader.exec_module(mod)

    return mod


class TestProgressPanelLogic:
    """Tests for ProgressPanel using fake self pattern to hit actual code."""

    def _make_fake_pp(self):
        """Create a fake ProgressPanel self with all required attributes."""
        import threading

        class FakePP:
            def __init__(self):
                self._cancel_event = threading.Event()
                self._after_calls = []

                class FakeBar:
                    def __init__(self):
                        self._cfg = {}
                        self._mode = "determinate"
                        self._value = 0
                    def __setitem__(self, k, v):
                        self._cfg[k] = v
                    def __getitem__(self, k):
                        return self._cfg.get(k, None)
                    def configure(self, **kw):
                        self._cfg.update(kw)
                    def start(self, ms): pass
                    def stop(self): pass

                class FakeLabel:
                    def __init__(self):
                        self._cfg = {}
                    def configure(self, **kw):
                        self._cfg.update(kw)

                class FakeText:
                    def __init__(self):
                        self._content = ""
                        self._cfg = {}
                    def configure(self, **kw):
                        self._cfg.update(kw)
                    def insert(self, pos, text):
                        self._content += text
                    def delete(self, start, end):
                        self._content = ""
                    def see(self, pos): pass

                self._progress_bar = FakeBar()
                self._progress_label = FakeLabel()
                self._percent_label = FakeLabel()
                self._log_text = FakeText()
                self._exists = True

            def winfo_exists(self):
                return self._exists

            def after(self, delay, fn):
                self._after_calls.append(fn)
                fn()  # execute immediately for testing

        return FakePP()

    def test_set_progress_basic(self):
        """set_progress updates bar value and percentage label."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        mod.ProgressPanel.set_progress(pp, 50, 100, label="Working")
        assert pp._progress_bar._cfg.get("value") == 50
        assert "50%" in pp._percent_label._cfg.get("text", "")

    def test_set_progress_zero_maximum(self):
        """set_progress with maximum=0 shows 0% without division error."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        mod.ProgressPanel.set_progress(pp, 0, 0)
        assert "0%" in pp._percent_label._cfg.get("text", "")

    def test_set_progress_with_label(self):
        """set_progress with label param updates progress label text."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        mod.ProgressPanel.set_progress(pp, 25, 100, label="Loading...")
        assert pp._progress_label._cfg.get("text") == "Loading..."

    def test_set_progress_without_label(self):
        """set_progress without label does not update progress_label."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        pp._progress_label._cfg["text"] = "Original"
        mod.ProgressPanel.set_progress(pp, 25, 100)
        # label should not be overwritten
        assert pp._progress_label._cfg.get("text") == "Original"

    def test_set_progress_skipped_when_widget_gone(self):
        """set_progress does nothing when winfo_exists() returns False."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        pp._exists = False
        mod.ProgressPanel.set_progress(pp, 99, 100)
        # Value should not have been set
        assert pp._progress_bar._cfg.get("value") is None

    def test_set_indeterminate_running(self):
        """set_indeterminate(running=True) switches to indeterminate mode."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        mod.ProgressPanel.set_indeterminate(pp, running=True)
        assert pp._progress_bar._cfg.get("mode") == "indeterminate"

    def test_set_indeterminate_stopped(self):
        """set_indeterminate(running=False) switches back to determinate."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        mod.ProgressPanel.set_indeterminate(pp, running=False)
        assert pp._progress_bar._cfg.get("mode") == "determinate"

    def test_set_indeterminate_skipped_when_gone(self):
        """set_indeterminate skipped when widget does not exist."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        pp._exists = False
        mod.ProgressPanel.set_indeterminate(pp, running=True)
        assert pp._progress_bar._cfg.get("mode") is None

    def test_log_appends_message(self):
        """log() appends a timestamped message to the log text."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        mod.ProgressPanel.log(pp, "Test event")
        assert "Test event" in pp._log_text._content

    def test_log_skipped_when_gone(self):
        """log() does nothing when widget does not exist."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        pp._exists = False
        mod.ProgressPanel.log(pp, "Should not appear")
        assert pp._log_text._content == ""

    def test_clear_log_empties_text(self):
        """clear_log() removes all content from log text widget."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        pp._log_text._content = "existing content"
        mod.ProgressPanel.clear_log(pp)
        assert pp._log_text._content == ""

    def test_clear_log_skipped_when_gone(self):
        """clear_log() does nothing when widget does not exist."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        pp._exists = False
        pp._log_text._content = "keep this"
        mod.ProgressPanel.clear_log(pp)
        assert pp._log_text._content == "keep this"

    def test_reset_clears_cancel_event(self):
        """reset() clears the cancel event and resets UI."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        pp._cancel_event.set()
        mod.ProgressPanel.reset(pp)
        assert not pp._cancel_event.is_set()

    def test_reset_sets_idle_text(self):
        """reset() sets progress label back to 'Idle'."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        mod.ProgressPanel.reset(pp)
        assert pp._progress_label._cfg.get("text") == "Idle"

    def test_reset_skipped_when_gone(self):
        """reset() skips UI update when widget is gone."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        pp._exists = False
        pp._cancel_event.set()
        mod.ProgressPanel.reset(pp)
        assert not pp._cancel_event.is_set()  # Event is cleared regardless

    def test_cancel_sets_event(self):
        """cancel() sets the cancel event."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        # Add log method to fake panel so cancel() can call it
        pp.log = lambda msg: None
        assert not pp._cancel_event.is_set()
        mod.ProgressPanel.cancel(pp)
        assert pp._cancel_event.is_set()

    def test_cancelled_property_false(self):
        """cancelled property returns False when not cancelled."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        assert mod.ProgressPanel.cancelled.fget(pp) is False

    def test_cancelled_property_true(self):
        """cancelled property returns True after cancel()."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        pp._cancel_event.set()
        assert mod.ProgressPanel.cancelled.fget(pp) is True

    def test_set_progress_full(self):
        """set_progress at 100% shows 100%."""
        mod = _load_progress_module()
        pp = self._make_fake_pp()
        mod.ProgressPanel.set_progress(pp, 100, 100, label="Done")
        assert "100%" in pp._percent_label._cfg.get("text", "")
        assert pp._progress_label._cfg.get("text") == "Done"
