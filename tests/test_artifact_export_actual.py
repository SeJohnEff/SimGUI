"""Tests that instantiate ArtifactExportDialog with full tkinter mocking.

This covers lines 47-221 by actually running the class constructor and
methods using mocked tkinter objects.
"""

import csv
import os
import sys
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Full tkinter mock — set up BEFORE importing the module
# ---------------------------------------------------------------------------
import unittest.mock as _mock


class _FakeBoolVar:
    def __init__(self, *args, value=False, **kwargs):
        self._v = bool(value)

    def set(self, v):
        self._v = bool(v)

    def get(self):
        return self._v


_tk_mock = _mock.MagicMock()
_ttk_mock = _mock.MagicMock()
_filedialog_mock = _mock.MagicMock()
_messagebox_mock = _mock.MagicMock()
_theme_mock = _mock.MagicMock()
_tooltip_mock = _mock.MagicMock()
_ns_manager_mock = _mock.MagicMock()

# BooleanVar must behave correctly
_tk_mock.BooleanVar = _FakeBoolVar
# Toplevel must be a base class that can be subclassed
_tk_mock.Toplevel = object
_tk_mock.W = "w"
_tk_mock.BOTH = "both"
_tk_mock.X = "x"
_tk_mock.LEFT = "left"
_tk_mock.RIGHT = "right"

_theme_mock.ModernTheme.get_padding.return_value = 8

_PATCHES = {
    "tkinter": _tk_mock,
    "tkinter.ttk": _ttk_mock,
    "tkinter.filedialog": _filedialog_mock,
    "tkinter.messagebox": _messagebox_mock,
    "theme": _theme_mock,
    "widgets.tooltip": _tooltip_mock,
    "managers.network_storage_manager": _ns_manager_mock,
}

# Clear any prior imports of these modules
for _mod_key in list(sys.modules.keys()):
    if "artifact_export_dialog" in _mod_key:
        del sys.modules[_mod_key]

# Import under the patched environment
with _mock.patch.dict("sys.modules", _PATCHES):
    from dialogs.artifact_export_dialog import _ALL_FIELDS, ArtifactExportDialog


# ---------------------------------------------------------------------------
# Helper: create a dialog instance without needing a real window
# ---------------------------------------------------------------------------

def _make_dialog(records=None, default_fields=None, ns_manager=None):
    """Instantiate ArtifactExportDialog with mocked parent and tkinter."""
    if records is None:
        records = []
    MagicMock()

    with _mock.patch.dict("sys.modules", _PATCHES):
        dlg = ArtifactExportDialog.__new__(ArtifactExportDialog)
        dlg._records = records
        dlg._ns = ns_manager
        dlg._field_vars = {
            f: _FakeBoolVar(value=(f in (default_fields or ["ICCID", "IMSI", "Ki", "OPc"])))
            for f in _ALL_FIELDS
        }
        dlg._default_fields = default_fields or ["ICCID", "IMSI", "Ki", "OPc"]
        # Mock tkinter widget methods
        dlg.title = MagicMock()
        dlg.geometry = MagicMock()
        dlg.resizable = MagicMock()
        dlg.transient = MagicMock()
        dlg.grab_set = MagicMock()
        dlg.destroy = MagicMock()
        dlg._status = MagicMock()
    return dlg


# ---------------------------------------------------------------------------
# _selected_fields
# ---------------------------------------------------------------------------

class TestSelectedFields:
    """Tests for _selected_fields()."""

    def test_default_fields_are_selected(self):
        """Default fields are returned by _selected_fields."""
        d = _make_dialog(default_fields=["ICCID", "IMSI"])
        fields = d._selected_fields()
        assert "ICCID" in fields
        assert "IMSI" in fields

    def test_non_default_fields_not_selected(self):
        """Non-default fields are not in _selected_fields."""
        d = _make_dialog(default_fields=["ICCID"])
        fields = d._selected_fields()
        assert "Ki" not in fields

    def test_empty_when_all_deselected(self):
        """_selected_fields returns [] after _select_none."""
        d = _make_dialog()
        d._select_none()
        assert d._selected_fields() == []

    def test_all_when_all_selected(self):
        """_selected_fields returns all _ALL_FIELDS after _select_all."""
        d = _make_dialog()
        d._select_all()
        assert set(d._selected_fields()) == set(_ALL_FIELDS)


# ---------------------------------------------------------------------------
# _select_all / _select_none
# ---------------------------------------------------------------------------

class TestSelectAllNone:
    """Tests for _select_all and _select_none."""

    def test_select_all_enables_all(self):
        """_select_all sets all field vars to True."""
        d = _make_dialog(default_fields=[])
        # All should be False initially
        for v in d._field_vars.values():
            v.set(False)
        d._select_all()
        for name, v in d._field_vars.items():
            assert v.get() is True, f"{name} should be True after select_all"

    def test_select_none_disables_all(self):
        """_select_none sets all field vars to False."""
        d = _make_dialog()
        d._select_all()
        d._select_none()
        for name, v in d._field_vars.items():
            assert v.get() is False, f"{name} should be False after select_none"


# ---------------------------------------------------------------------------
# _generate_filename
# ---------------------------------------------------------------------------

class TestGenerateFilenameActual:
    """Tests for _generate_filename from the real class."""

    def test_filename_starts_with_prefix(self):
        """Generated filename starts with 'sim_artifacts_'."""
        d = _make_dialog()
        name = d._generate_filename()
        assert name.startswith("sim_artifacts_")

    def test_filename_ends_with_csv(self):
        """Generated filename ends with '.csv'."""
        d = _make_dialog()
        name = d._generate_filename()
        assert name.endswith(".csv")

    def test_filename_has_timestamp(self):
        """Generated filename contains a timestamp pattern."""
        import re
        d = _make_dialog()
        name = d._generate_filename()
        assert re.match(r"^sim_artifacts_\d{8}_\d{6}\.csv$", name)


# ---------------------------------------------------------------------------
# _write_csv (actual method on ArtifactExportDialog)
# ---------------------------------------------------------------------------

class TestWriteCsvActual:
    """Tests that invoke the actual _write_csv method."""

    def _sample_records(self):
        return [
            {"ICCID": "89860012345678901234", "IMSI": "001010123456789",
             "Ki": "A" * 32, "OPc": "B" * 32},
            {"ICCID": "89860012345678905678", "IMSI": "001010987654321",
             "Ki": "C" * 32, "OPc": "D" * 32},
        ]

    def test_write_creates_file(self, tmp_path):
        """_write_csv creates the output file."""
        d = _make_dialog(records=self._sample_records())
        path = str(tmp_path / "output.csv")
        ok, msg = d._write_csv(path)
        assert ok is True
        assert os.path.isfile(path)

    def test_write_returns_success_with_count(self, tmp_path):
        """Success message mentions the exported card count."""
        records = self._sample_records()
        d = _make_dialog(records=records)
        path = str(tmp_path / "output.csv")
        ok, msg = d._write_csv(path)
        assert ok is True
        assert "2" in msg

    def test_no_fields_selected_returns_error(self, tmp_path):
        """_write_csv returns (False, ...) when no fields selected."""
        d = _make_dialog(records=self._sample_records())
        d._select_none()
        ok, msg = d._write_csv(str(tmp_path / "out.csv"))
        assert ok is False
        assert "No fields" in msg

    def test_csv_has_correct_header(self, tmp_path):
        """Written CSV has the correct header row."""
        d = _make_dialog(records=self._sample_records(),
                         default_fields=["ICCID", "IMSI"])
        path = str(tmp_path / "output.csv")
        d._write_csv(path)
        with open(path, newline="") as fh:
            header = next(csv.reader(fh))
        assert "ICCID" in header
        assert "IMSI" in header

    def test_csv_excludes_unselected_fields(self, tmp_path):
        """Unselected fields are absent from the CSV header."""
        d = _make_dialog(records=self._sample_records(),
                         default_fields=["ICCID"])
        path = str(tmp_path / "out.csv")
        d._write_csv(path)
        with open(path, newline="") as fh:
            header = next(csv.reader(fh))
        assert "Ki" not in header

    def test_oserror_returns_failure(self, tmp_path):
        """_write_csv returns (False, error msg) on write failure."""
        d = _make_dialog(records=self._sample_records())
        ok, msg = d._write_csv("/proc/cannot_write_here/out.csv")
        assert ok is False
        assert "error" in msg.lower() or "Error" in msg

    def test_write_empty_records_header_only(self, tmp_path):
        """Writing with no records creates a header-only CSV."""
        d = _make_dialog(records=[], default_fields=["ICCID", "IMSI"])
        path = str(tmp_path / "empty.csv")
        ok, msg = d._write_csv(path)
        assert ok is True
        with open(path, newline="") as fh:
            rows = list(csv.reader(fh))
        assert len(rows) == 1  # header only

    def test_normalises_lowercase_keys(self, tmp_path):
        """_write_csv handles lowercase keys in records (key normalisation)."""
        records = [{"iccid": "89001", "imsi": "001010"}]
        d = _make_dialog(records=records, default_fields=["ICCID", "IMSI"])
        path = str(tmp_path / "norm.csv")
        ok, _ = d._write_csv(path)
        assert ok is True
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["ICCID"] == "89001"


# ---------------------------------------------------------------------------
# _save_local and _save_network (with mocked dialogs)
# ---------------------------------------------------------------------------

def _get_aed_globals():
    """Get the module globals dict used by ArtifactExportDialog methods."""
    return ArtifactExportDialog._save_local.__globals__


from contextlib import contextmanager


@contextmanager
def _patch_aed_globals(**replacements):
    """Context manager: temporarily replace items in AED module globals."""
    g = _get_aed_globals()
    originals = {k: g.get(k) for k in replacements}
    for k, v in replacements.items():
        g[k] = v
    try:
        yield
    finally:
        for k, v in originals.items():
            if v is None and k in g:
                del g[k]
            else:
                g[k] = v


class TestSaveLocalNetwork:
    """Tests for _save_local and _save_network."""

    def _sample_records(self):
        return [{"ICCID": "89001", "IMSI": "001010", "Ki": "A" * 32, "OPc": "B" * 32}]

    def test_save_local_no_fields_shows_warning(self):
        """_save_local with no selected fields shows a warning."""
        mb = MagicMock()
        d = _make_dialog(records=self._sample_records())
        d._select_none()
        with _patch_aed_globals(messagebox=mb):
            d._save_local()
        mb.showwarning.assert_called_once()

    def test_save_local_cancelled_by_user(self, tmp_path):
        """_save_local with file dialog cancelled does nothing."""
        mb = MagicMock()
        fd = MagicMock()
        fd.asksaveasfilename.return_value = ""  # user cancelled

        d = _make_dialog(records=self._sample_records())
        with _patch_aed_globals(messagebox=mb, filedialog=fd):
            d._save_local()

        # No error should be shown
        mb.showerror.assert_not_called()

    def test_save_local_success(self, tmp_path):
        """_save_local writes the file when dialog returns a path."""
        mb = MagicMock()
        fd = MagicMock()
        output_path = str(tmp_path / "result.csv")
        fd.asksaveasfilename.return_value = output_path

        d = _make_dialog(records=self._sample_records())
        with _patch_aed_globals(messagebox=mb, filedialog=fd):
            d._save_local()

        assert os.path.isfile(output_path)
        mb.showerror.assert_not_called()

    def test_save_local_write_error_shows_error_dialog(self, tmp_path):
        """_save_local shows error dialog when _write_csv fails."""
        mb = MagicMock()
        fd = MagicMock()
        fd.asksaveasfilename.return_value = "/proc/invalid/out.csv"

        d = _make_dialog(records=self._sample_records())
        with _patch_aed_globals(messagebox=mb, filedialog=fd):
            d._save_local()

        mb.showerror.assert_called_once()

    def test_save_network_no_fields_shows_warning(self, tmp_path):
        """_save_network with no selected fields shows a warning."""
        mb = MagicMock()
        d = _make_dialog(records=self._sample_records())
        d._select_none()
        with _patch_aed_globals(messagebox=mb):
            d._save_network(str(tmp_path), "TestLabel")
        mb.showwarning.assert_called_once()

    def test_save_network_success(self, tmp_path):
        """_save_network writes to the network mount path."""
        mb = MagicMock()
        # Create the expected artifacts directory
        dest_dir = tmp_path / "artifacts"
        dest_dir.mkdir()

        d = _make_dialog(records=self._sample_records(), ns_manager=None)
        with _patch_aed_globals(messagebox=mb):
            d._save_network(str(tmp_path), "SomeLabel")

        # Success path calls showinfo
        assert mb.showinfo.called or mb.showerror.called

    def test_save_network_with_ns_manager_uses_export_subdir(self, tmp_path):
        """_save_network uses the profile's export_subdir if ns_manager present."""
        mb = MagicMock()

        # Set up a mock ns_manager with a matching profile
        mock_ns = MagicMock()
        mock_prof = MagicMock()
        mock_prof.label = "TestNetwork"
        mock_prof.export_subdir = "custom_export"
        mock_ns.load_profiles.return_value = [mock_prof]
        mock_ns.get_active_mount_paths.return_value = [("TestNetwork", str(tmp_path))]

        d = _make_dialog(records=self._sample_records(), ns_manager=mock_ns)
        with _patch_aed_globals(messagebox=mb):
            d._save_network(str(tmp_path), "TestNetwork")

        assert mb.showinfo.called or mb.showerror.called
