"""Tests for the BatchProgramPanel widget — CSV loading and batch execution."""

import os
from unittest.mock import MagicMock, patch

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


class TestPanelInitialization:
    """Verify BatchProgramPanel initializes correctly."""

    def test_panel_instantiates(self, panel):
        assert panel is not None
        assert isinstance(panel, BatchProgramPanel)

    def test_initial_source_is_generate(self, panel):
        assert panel._source_var == "generate"

    def test_preview_data_starts_empty(self, panel):
        assert panel._preview_data == []

    def test_all_csv_cards_starts_empty(self, panel):
        assert panel._all_csv_cards == []


class TestCSVFileLoading:
    """Verify CSV file loading updates widget state."""

    def test_load_csv_updates_path_entry(self, panel, tmp_path, qtbot):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("ICCID,IMSI,Ki,OPc,ADM1\n")
        csv_file.write_text("8988601234567890123,310410123456789,0123456789abcdef0123456789abcdef,fedcba9876543210fedcba9876543210,88888888\n")

        ok = panel.load_csv_file(str(csv_file))
        qtbot.wait(50)

        assert ok is True
        assert panel._csv_path_entry.text() == str(csv_file)

    def test_load_csv_updates_count_label(self, panel, tmp_path, qtbot):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("ICCID,IMSI,Ki,OPc,ADM1\n")
        csv_file.write_text("8988601234567890123,310410123456789,0123456789abcdef0123456789abcdef,fedcba9876543210fedcba9876543210,88888888\n")
        csv_file.write_text("8988601234567890124,310410123456790,0123456789abcdef0123456789abcdef,fedcba9876543210fedcba9876543210,88888888\n")

        panel.load_csv_file(str(csv_file))
        qtbot.wait(50)

        assert "(2 cards)" in panel._csv_count_lbl.text()

    def test_load_nonexistent_csv_fails(self, panel, qtbot):
        ok = panel.load_csv_file("/nonexistent/file.csv")
        assert ok is False


class TestBatchStart:
    """Verify _on_start() behavior with preview data."""

    def test_start_with_preview_data_calls_batch_manager(self, panel):
        panel._preview_data = [{"IMSI": "123", "ICCID": "456", "ADM1": "abc"}]
        with patch.object(panel._batch_mgr, 'start') as mock_start:
            panel._on_start()
            mock_start.assert_called_once_with(panel._preview_data)

    def test_start_with_preview_data_enables_controls(self, panel):
        panel._preview_data = [{"IMSI": "123", "ICCID": "456", "ADM1": "abc"}]
        with patch.object(panel._batch_mgr, 'start'):
            panel._on_start()

        assert panel._start_btn.isEnabled() is False
        assert panel._pause_btn.isEnabled() is True
        assert panel._skip_btn.isEnabled() is True
        assert panel._abort_btn.isEnabled() is True

    def test_start_without_preview_data_calls_preview(self, panel):
        panel._preview_data = []
        with patch.object(panel, '_on_preview') as mock_preview:
            with patch.object(panel._batch_mgr, 'start'):
                panel._on_start()
            mock_preview.assert_called()


class TestBatchControls:
    """Verify batch control buttons are wired correctly."""

    def test_pause_button_calls_pause(self, panel):
        with patch.object(panel._batch_mgr, 'pause') as mock_pause:
            panel._on_pause()
            mock_pause.assert_called_once()

    def test_skip_button_calls_skip(self, panel):
        with patch.object(panel._batch_mgr, 'skip_card') as mock_skip:
            panel._on_skip()
            mock_skip.assert_called_once()

    def test_abort_button_calls_stop(self, panel):
        with patch.object(panel._batch_mgr, 'stop') as mock_stop:
            panel._on_abort()
            mock_stop.assert_called_once()


class TestProgressCallbacks:
    """Verify batch manager callbacks update UI."""

    def test_on_progress_updates_bar(self, panel):
        panel._on_progress(25, 100, "Test")
        assert panel._progress_bar.value() == 25
        assert panel._progress_bar.maximum() == 100

    def test_on_card_result_appends_log(self, panel):
        initial_text = panel._log_text.toPlainText()
        panel._on_card_result("8988601234567890123", True, "OK")
        final_text = panel._log_text.toPlainText()
        assert "8988601234567890123" in final_text
        assert final_text != initial_text

    def test_on_batch_completed_resets_controls(self, panel):
        panel._start_btn.setEnabled(False)
        panel._pause_btn.setEnabled(True)
        panel._on_batch_completed(10, 9, 1)
        assert panel._start_btn.isEnabled() is True
        assert panel._pause_btn.isEnabled() is False
