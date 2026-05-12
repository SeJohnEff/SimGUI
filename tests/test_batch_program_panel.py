"""Tests for the BatchProgramPanel widget — CSV layout and error messages."""

import os
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
def panel(qtbot, tmp_path):
    settings = SettingsManager(path=str(tmp_path / "settings.json"))
    cm = CardManager()
    cm.enable_simulator()
    p = BatchProgramPanel(None, cm, settings)
    qtbot.addWidget(p)
    return p


class TestSourceChangeLayout:
    """Verify sections appear in correct visual order when switching sources."""

    def test_csv_section_visible_when_csv_selected(self, panel, qtbot):
        panel._source_var = "csv"
        panel._on_source_change()
        qtbot.wait(50)
        assert panel._csv_group.isVisible()

    def test_gen_section_hidden_when_csv_selected(self, panel, qtbot):
        panel._source_var = "csv"
        panel._on_source_change()
        qtbot.wait(50)
        assert not panel._gen_group.isVisible()

    def test_gen_section_visible_when_generate_selected(self, panel, qtbot):
        panel._source_var = "generate"
        panel._on_source_change()
        qtbot.wait(50)
        assert panel._gen_group.isVisible()

    def test_csv_section_hidden_when_generate_selected(self, panel, qtbot):
        panel._source_var = "generate"
        panel._on_source_change()
        qtbot.wait(50)
        assert not panel._csv_group.isVisible()

    def test_csv_section_appears_before_preview(self, panel, qtbot):
        """CSV section must be laid out before the preview frame."""
        panel._source_var = "csv"
        panel._on_source_change()
        qtbot.wait(50)
        main_layout = panel.layout()
        csv_idx = main_layout.indexOf(panel._csv_group)
        preview_idx = main_layout.indexOf(panel._preview_frame)
        assert csv_idx < preview_idx

    def test_gen_section_appears_before_preview(self, panel, qtbot):
        panel._source_var = "generate"
        panel._on_source_change()
        qtbot.wait(50)
        main_layout = panel.layout()
        gen_idx = main_layout.indexOf(panel._gen_group)
        preview_idx = main_layout.indexOf(panel._preview_frame)
        assert gen_idx < preview_idx

    def test_switching_back_and_forth_preserves_order(self, panel, qtbot):
        """Switching csv → generate → csv must still show csv_section above preview."""
        for _ in range(3):
            panel._source_var = "csv"
            panel._on_source_change()
            panel._source_var = "generate"
            panel._on_source_change()
        panel._source_var = "csv"
        panel._on_source_change()
        qtbot.wait(50)
        main_layout = panel.layout()
        csv_idx = main_layout.indexOf(panel._csv_group)
        preview_idx = main_layout.indexOf(panel._preview_frame)
        assert csv_idx < preview_idx


class TestStartErrorMessages:
    """Verify _on_start() shows context-specific error messages."""

    @patch("widgets.batch_program_panel.messagebox")
    def test_csv_no_file_loaded(self, mock_mb, panel):
        panel._source_var = "csv"
        panel._csv_path_entry.setText("")
        panel._preview_data = []
        panel._on_start()
        mock_mb.showinfo.assert_called_once_with(
            "Nothing to do", "Load a CSV file first using Browse.")

    @patch("widgets.batch_program_panel.messagebox")
    def test_csv_file_loaded_but_empty(self, mock_mb, panel):
        panel._source_var = "csv"
        panel._csv_path_entry.setText("/some/file.csv")
        panel._preview_data = []
        panel._on_start()
        mock_mb.showinfo.assert_called_once_with(
            "Nothing to do", "The loaded CSV file has no cards.")

    @patch("widgets.batch_program_panel.messagebox")
    def test_generate_no_preview(self, mock_mb, panel):
        panel._source_var = "generate"
        panel._preview_data = []
        panel._on_start()
        mock_mb.showinfo.assert_called_once_with(
            "Nothing to do", "Preview the batch first.")

    @patch("widgets.batch_program_panel.messagebox")
    def test_no_error_when_preview_data_exists(self, mock_mb, panel):
        panel._preview_data = [{"IMSI": "123", "ICCID": "456", "ADM1": "abc"}]
        with patch.object(panel._batch_mgr, 'start'):
            panel._on_start()
        mock_mb.showinfo.assert_not_called()
