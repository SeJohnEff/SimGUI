"""Comprehensive tests for widget and dialog methods using importlib-based mock loading.

Uses a reusable helper to load any module with mocked tkinter, allowing
us to test actual source methods on fake `self` objects without a real
display server.
"""

import csv
import importlib
import importlib.util
import os
import sys
import tempfile
import types
from datetime import datetime
from unittest import mock as _mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")


class _FakeWidget:
    """Minimal widget stand-in that absorbs all tkinter calls."""
    _cfg: dict = {}

    def __init__(self, *a, **kw):
        self._cfg = {}

    def pack(self, **kw): pass
    def grid(self, **kw): pass
    def grid_columnconfigure(self, *a, **kw): pass
    def grid_rowconfigure(self, *a, **kw): pass
    def grid_remove(self): pass
    def configure(self, **kw): self._cfg.update(kw)
    def config(self, **kw): self._cfg.update(kw)
    def bind(self, *a, **kw): pass
    def winfo_exists(self): return True
    def after(self, ms, func): func()
    def delete(self, *a): pass
    def insert(self, *a, **kw): pass
    def create_oval(self, *a, **kw): return 1
    def focus_set(self): pass
    def destroy(self): pass
    def get_children(self): return []
    def see(self, *a): pass
    def update_idletasks(self): pass
    def columnconfigure(self, *a, **kw): pass
    def rowconfigure(self, *a, **kw): pass


class _FakeVar:
    """Stand-in for tk.StringVar / tk.BooleanVar."""
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v

    def trace_add(self, *a, **kw):
        pass


def _build_mocks():
    """Create the standard set of mocked tkinter modules."""
    _tk = _mock.MagicMock()
    _ttk = _mock.MagicMock()
    # All ttk widget types must be real classes (not lambdas) so they
    # can be used as base classes in 'class Foo(ttk.Frame):' etc.
    _ttk.LabelFrame = _FakeWidget
    _ttk.Frame = _FakeWidget
    _ttk.Label = _FakeWidget
    _ttk.Entry = _FakeWidget
    _ttk.Button = _FakeWidget
    _ttk.Checkbutton = _FakeWidget
    _ttk.Radiobutton = _FakeWidget
    _ttk.Combobox = _FakeWidget
    _ttk.Spinbox = _FakeWidget
    _ttk.Treeview = _FakeWidget
    _ttk.Scrollbar = _FakeWidget
    _ttk.Progressbar = _FakeWidget
    _ttk.Separator = _FakeWidget
    _ttk.Notebook = _FakeWidget
    _tk.Canvas = _FakeWidget
    _tk.Text = _FakeWidget
    _tk.StringVar = _FakeVar
    _tk.BooleanVar = type("_FakeBoolVar", (_FakeVar,), {"__init__": lambda self, *a, **kw: _FakeVar.__init__(self, False)})
    _tk.IntVar = type("_FakeIntVar", (_FakeVar,), {"__init__": lambda self, *a, **kw: _FakeVar.__init__(self, 0)})
    _tk.W = "w"; _tk.E = "e"; _tk.X = "x"; _tk.Y = "y"
    _tk.N = "n"; _tk.S = "s"; _tk.NW = "nw"; _tk.NE = "ne"
    _tk.LEFT = "left"; _tk.RIGHT = "right"; _tk.TOP = "top"
    _tk.BOTTOM = "bottom"; _tk.BOTH = "both"; _tk.END = "end"
    _tk.HORIZONTAL = "horizontal"; _tk.VERTICAL = "vertical"
    _tk.NORMAL = "normal"; _tk.DISABLED = "disabled"
    _tk.WORD = "word"; _tk.NONE = "none"
    _tk.Toplevel = _FakeWidget
    # 'from tkinter import ttk' resolves to _tk.ttk
    _tk.ttk = _ttk

    _th = _mock.MagicMock()
    _th.ModernTheme.get_color.return_value = "#000000"
    _th.ModernTheme.get_padding.side_effect = lambda k: 8
    _tp = _mock.MagicMock()

    return _tk, _ttk, _th, _tp


def _load_module(module_rel_path: str, module_name: str, extra_mocks: dict | None = None):
    """Load a module with mocked tkinter using importlib.

    Args:
        module_rel_path: Path relative to project root (e.g. "widgets/card_status_panel.py").
        module_name: Module name to register (e.g. "widgets.card_status_panel").
        extra_mocks: Additional modules to mock in sys.modules.

    Returns:
        The loaded module.
    """
    _tk, _ttk, _th, _tp = _build_mocks()

    # Remove cached widget/dialog modules
    for k in list(sys.modules.keys()):
        if (k.startswith("widgets") or k.startswith("dialogs")) and "test_" not in k:
            del sys.modules[k]

    # Create real packages for 'widgets' and 'dialogs'
    _widgets_pkg = types.ModuleType("widgets")
    _widgets_pkg.__path__ = [os.path.join(_PROJECT_ROOT, "widgets")]
    _dialogs_pkg = types.ModuleType("dialogs")
    _dialogs_pkg.__path__ = [os.path.join(_PROJECT_ROOT, "dialogs")]

    mocks = {
        "tkinter": _tk,
        "tkinter.ttk": _ttk,
        "tkinter.filedialog": _mock.MagicMock(),
        "tkinter.messagebox": _mock.MagicMock(),
        "theme": _th,
        "widgets": _widgets_pkg,
        "widgets.tooltip": _tp,
        "dialogs": _dialogs_pkg,
    }
    if extra_mocks:
        mocks.update(extra_mocks)

    file_path = os.path.join(_PROJECT_ROOT, module_rel_path)
    with _mock.patch.dict(sys.modules, mocks):
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    return mod


# ==============================================================================
# Tests for widgets/batch_program_panel.py — standalone functions
# ==============================================================================

class TestBatchProgramPanelFunctions:
    """Test apply_imsi_override and apply_range_filter (already imported at module level)."""

    def test_apply_imsi_override_basic(self):
        from widgets.batch_program_panel import apply_imsi_override
        cards = [{"IMSI": "old1", "ICCID": "89001"}, {"IMSI": "old2", "ICCID": "89002"}]
        result = apply_imsi_override(cards, "9998800010", start_seq=1)
        assert result[0]["IMSI"] == "999880001000001"
        assert result[1]["IMSI"] == "999880001000002"
        assert result[0]["ICCID"] == "89001"  # untouched

    def test_apply_imsi_override_custom_start(self):
        from widgets.batch_program_panel import apply_imsi_override
        cards = [{"IMSI": "old", "ICCID": "89001"}]
        result = apply_imsi_override(cards, "9998800010", start_seq=50)
        assert result[0]["IMSI"] == "999880001000050"

    def test_apply_imsi_override_preserves_other_fields(self):
        from widgets.batch_program_panel import apply_imsi_override
        cards = [{"IMSI": "old", "ICCID": "89001", "Ki": "AAAA", "SPN": "Test"}]
        result = apply_imsi_override(cards, "9998800010")
        assert result[0]["Ki"] == "AAAA"
        assert result[0]["SPN"] == "Test"

    def test_apply_range_filter_from_start(self):
        from widgets.batch_program_panel import apply_range_filter
        cards = [{"IMSI": str(i)} for i in range(10)]
        result = apply_range_filter(cards, 1, 3)
        assert len(result) == 3
        assert result[0]["IMSI"] == "0"

    def test_apply_range_filter_offset(self):
        from widgets.batch_program_panel import apply_range_filter
        cards = [{"IMSI": str(i)} for i in range(10)]
        result = apply_range_filter(cards, 5, 3)
        assert len(result) == 3
        assert result[0]["IMSI"] == "4"

    def test_apply_range_filter_beyond_end(self):
        from widgets.batch_program_panel import apply_range_filter
        cards = [{"IMSI": str(i)} for i in range(5)]
        result = apply_range_filter(cards, 3, 100)
        assert len(result) == 3  # only 3 cards left from index 2

    def test_apply_range_filter_zero_start(self):
        from widgets.batch_program_panel import apply_range_filter
        cards = [{"IMSI": "a"}, {"IMSI": "b"}]
        result = apply_range_filter(cards, 0, 1)
        assert len(result) == 1
        assert result[0]["IMSI"] == "a"

    def test_apply_range_filter_empty_cards(self):
        from widgets.batch_program_panel import apply_range_filter
        result = apply_range_filter([], 1, 10)
        assert result == []


# ==============================================================================
# _load_adm1_csv was removed — ADM1 now always comes from the vendor data file.


# ==============================================================================
# Tests for dialogs/artifact_export_dialog.py — _write_csv method
# ==============================================================================

class TestArtifactExportWriteCsv:
    """Test the _write_csv method using a minimal fake self."""

    def _make_dialog(self, records, selected_fields):
        """Create a fake dialog object with just the attributes _write_csv needs."""
        mod = _load_module("dialogs/artifact_export_dialog.py",
                           "dialogs.artifact_export_dialog")
        cls = mod.ArtifactExportDialog

        class FakeDialog:
            _records = records
            _field_vars = {}

        d = FakeDialog()
        for f in mod._ALL_FIELDS:
            d._field_vars[f] = _FakeVar(f in selected_fields)
        # Bind the unbound _write_csv and _selected_fields
        d._selected_fields = lambda: selected_fields
        d._write_csv = lambda path: cls._write_csv(d, path)
        return d

    def test_write_csv_success(self, tmp_path):
        records = [
            {"ICCID": "89001", "IMSI": "001010", "Ki": "AA" * 16},
            {"ICCID": "89002", "IMSI": "001011", "Ki": "BB" * 16},
        ]
        d = self._make_dialog(records, ["ICCID", "IMSI", "Ki"])
        out = str(tmp_path / "export.csv")
        ok, msg = d._write_csv(out)
        assert ok
        assert "2 card" in msg
        # Verify file content
        with open(out) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["ICCID"] == "89001"

    def test_write_csv_no_fields(self, tmp_path):
        d = self._make_dialog([{"ICCID": "89001"}], [])
        out = str(tmp_path / "export.csv")
        ok, msg = d._write_csv(out)
        assert not ok
        assert "No fields" in msg

    def test_write_csv_creates_dirs(self, tmp_path):
        records = [{"ICCID": "89001"}]
        d = self._make_dialog(records, ["ICCID"])
        out = str(tmp_path / "sub" / "dir" / "export.csv")
        ok, msg = d._write_csv(out)
        assert ok
        assert os.path.exists(out)

    def test_generate_filename_format(self):
        mod = _load_module("dialogs/artifact_export_dialog.py",
                           "dialogs.artifact_export_dialog")

        class FakeDialog:
            pass

        d = FakeDialog()
        d._generate_filename = lambda: mod.ArtifactExportDialog._generate_filename(d)
        name = d._generate_filename()
        assert name.startswith("sim_artifacts_")
        assert name.endswith(".csv")


# ==============================================================================
# Tests for widgets/progress_panel.py methods
# ==============================================================================

class TestProgressPanelMethods:
    """Test ProgressPanel methods with importlib loading."""

    def _load_panel(self):
        return _load_module("widgets/progress_panel.py", "widgets.progress_panel")

    def test_module_loads(self):
        mod = self._load_panel()
        assert hasattr(mod, "ProgressPanel")

    def test_class_has_expected_methods(self):
        mod = self._load_panel()
        cls = mod.ProgressPanel
        for method in ["set_progress", "reset", "log", "clear_log", "cancel", "cancelled"]:
            assert hasattr(cls, method), f"Missing method: {method}"


# ==============================================================================
# Tests for widgets/csv_editor_panel.py — logic methods
# ==============================================================================

class TestCsvEditorPanelMethods:
    def _load_panel(self):
        return _load_module("widgets/csv_editor_panel.py", "widgets.csv_editor_panel")

    def test_module_loads(self):
        mod = self._load_panel()
        assert hasattr(mod, "CSVEditorPanel")

    def test_has_unsaved_changes(self):
        mod = self._load_panel()
        assert hasattr(mod.CSVEditorPanel, "has_unsaved_changes")

    def test_get_csv_manager(self):
        mod = self._load_panel()
        assert hasattr(mod.CSVEditorPanel, "get_csv_manager")


# ==============================================================================
# Tests for widgets/read_sim_panel.py — _lookup_adm1_in_file (static method)
# ==============================================================================

class TestReadSimPanelLookup:
    def test_lookup_found(self, tmp_path):
        mod = _load_module("widgets/read_sim_panel.py", "widgets.read_sim_panel")
        csv_file = tmp_path / "adm.csv"
        csv_file.write_text("ICCID,ADM1\n89001,AABBCCDD\n89002,11223344\n")
        result = mod.ReadSIMPanel._lookup_adm1_in_file(str(csv_file), "89001")
        assert result == "AABBCCDD"

    def test_lookup_not_found(self, tmp_path):
        mod = _load_module("widgets/read_sim_panel.py", "widgets.read_sim_panel")
        csv_file = tmp_path / "adm.csv"
        csv_file.write_text("ICCID,ADM1\n89001,AABBCCDD\n")
        result = mod.ReadSIMPanel._lookup_adm1_in_file(str(csv_file), "89999")
        assert result == ""

    def test_lookup_missing_file(self):
        mod = _load_module("widgets/read_sim_panel.py", "widgets.read_sim_panel")
        result = mod.ReadSIMPanel._lookup_adm1_in_file("/nonexistent/file.csv", "89001")
        assert result == ""


# ==============================================================================
# Tests for main.py — _get_expected_iccid logic
# ==============================================================================

class TestMainHelpers:
    def _load_main(self):
        return _load_module("main.py", "main_module", extra_mocks={
            "widgets.card_status_panel": _mock.MagicMock(),
            "widgets.csv_editor_panel": _mock.MagicMock(),
            "widgets.progress_panel": _mock.MagicMock(),
            "widgets.read_sim_panel": _mock.MagicMock(),
            "widgets.program_sim_panel": _mock.MagicMock(),
            "widgets.batch_program_panel": _mock.MagicMock(),
            "dialogs.adm1_dialog": _mock.MagicMock(),
            "dialogs.artifact_export_dialog": _mock.MagicMock(),
            "dialogs.simulator_settings_dialog": _mock.MagicMock(),
            "dialogs.network_storage_dialog": _mock.MagicMock(),
        })

    def test_module_loads(self):
        mod = self._load_main()
        assert hasattr(mod, "SimGUIApp")
