"""Tests for the BatchProgramPanel widget — CSV layout and error messages."""

import os
import tkinter as tk
from unittest.mock import patch

import pytest

from managers.card_manager import CardManager
from managers.settings_manager import SettingsManager
from widgets.batch_program_panel import BatchProgramPanel

# Skip all tests when no display is available (headless CI)
pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="No DISPLAY — headless environment"
)


@pytest.fixture
def root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def panel(root, tmp_path):
    settings = SettingsManager(path=str(tmp_path / "settings.json"))
    cm = CardManager()
    cm.enable_simulator()
    p = BatchProgramPanel(root, cm, settings)
    p.pack()
    root.update_idletasks()
    return p


class TestSourceChangeLayout:
    """Verify sections appear in correct visual order when switching sources."""

    def test_csv_section_visible_when_csv_selected(self, panel):
        panel._source_var.set("csv")
        panel._on_source_change()
        panel.winfo_toplevel().update_idletasks()
        assert panel._csv_section.winfo_manager() == "pack"

    def test_gen_section_hidden_when_csv_selected(self, panel):
        panel._source_var.set("csv")
        panel._on_source_change()
        panel.winfo_toplevel().update_idletasks()
        assert panel._gen_section.winfo_manager() == ""

    def test_gen_section_visible_when_generate_selected(self, panel):
        panel._source_var.set("generate")
        panel._on_source_change()
        panel.winfo_toplevel().update_idletasks()
        assert panel._gen_section.winfo_manager() == "pack"

    def test_csv_section_hidden_when_generate_selected(self, panel):
        panel._source_var.set("generate")
        panel._on_source_change()
        panel.winfo_toplevel().update_idletasks()
        assert panel._csv_section.winfo_manager() == ""

    def test_csv_section_appears_before_preview(self, panel):
        """CSV section must pack before the preview frame in the pack order."""
        panel._source_var.set("csv")
        panel._on_source_change()
        panel.winfo_toplevel().update_idletasks()
        children = panel.pack_slaves()
        csv_idx = children.index(panel._csv_section)
        preview_idx = children.index(panel._preview_frame)
        assert csv_idx < preview_idx

    def test_gen_section_appears_before_preview(self, panel):
        panel._source_var.set("generate")
        panel._on_source_change()
        panel.winfo_toplevel().update_idletasks()
        children = panel.pack_slaves()
        gen_idx = children.index(panel._gen_section)
        preview_idx = children.index(panel._preview_frame)
        assert gen_idx < preview_idx

    def test_switching_back_and_forth_preserves_order(self, panel):
        """Switching csv → generate → csv must still show csv_section above preview."""
        for _ in range(3):
            panel._source_var.set("csv")
            panel._on_source_change()
            panel._source_var.set("generate")
            panel._on_source_change()
        panel._source_var.set("csv")
        panel._on_source_change()
        panel.winfo_toplevel().update_idletasks()
        children = panel.pack_slaves()
        csv_idx = children.index(panel._csv_section)
        preview_idx = children.index(panel._preview_frame)
        assert csv_idx < preview_idx


class TestStartErrorMessages:
    """Verify _on_start() shows context-specific error messages."""

    @patch("widgets.batch_program_panel.messagebox")
    def test_csv_no_file_loaded(self, mock_mb, panel):
        panel._source_var.set("csv")
        panel._csv_path_var.set("")
        panel._preview_data = []
        panel._on_start()
        mock_mb.showinfo.assert_called_once_with(
            "Nothing to do", "Load a CSV file first using Browse.")

    @patch("widgets.batch_program_panel.messagebox")
    def test_csv_file_loaded_but_empty(self, mock_mb, panel):
        panel._source_var.set("csv")
        panel._csv_path_var.set("/some/file.csv")
        panel._preview_data = []
        panel._on_start()
        mock_mb.showinfo.assert_called_once_with(
            "Nothing to do", "The loaded CSV file has no cards.")

    @patch("widgets.batch_program_panel.messagebox")
    def test_generate_no_preview(self, mock_mb, panel):
        panel._source_var.set("generate")
        panel._preview_data = []
        panel._on_start()
        mock_mb.showinfo.assert_called_once_with(
            "Nothing to do", "Preview the batch first.")

    @patch("widgets.batch_program_panel.messagebox")
    def test_no_error_when_preview_data_exists(self, mock_mb, panel):
        panel._preview_data = [{"IMSI": "123", "ICCID": "456", "ADM1": "abc"}]
        panel._on_start()
        mock_mb.showinfo.assert_not_called()
