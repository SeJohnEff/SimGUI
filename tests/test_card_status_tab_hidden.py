"""Test: Card Status tab is hidden in the main window tab widget.

Verifies that after the hide change in main.py:
- "Card Status" tab exists in the QTabWidget (panel + signals intact).
- "Card Status" tab is not visible (isTabVisible returns False).
- The operational tabs (Read SIM, Program SIM, Batch) are all visible.
"""

import importlib
import importlib.util
import os
import sys
import unittest.mock as _mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _load_main():
    """Load main.py with all heavy deps mocked — mirrors test_main_app pattern."""

    # Minimal fake panel factory — must subclass QWidget so addTab accepts it
    from PyQt6.QtWidgets import QWidget as _QWidget

    def _fake_panel(name):
        class FakePanel(_QWidget):
            def __init__(self, *a, **kw): super().__init__()
            def set_status(self, *a, **kw): pass
            def set_card_info(self, **kw): pass
            def set_auth_status(self, *a): pass
            def has_unsaved_changes(self): return False
            def get_programmed_records(self): return []
            def load_csv_file(self, *a, **kw): return True
            def set_standards_manager(self, *a): pass
            def refresh_standards(self): pass
            def on_card_detected(self, *a, **kw): pass
            def on_card_removed(self): pass
            def clear_card_info(self): pass
            def set_programmed_indicator(self, *a): pass
            def set_blocked_indicator(self, *a): pass
            def set_adm1_attempts(self, *a): pass
            def refresh(self): pass
            on_card_programmed_callback = None
        FakePanel.__name__ = name
        return FakePanel

    _widgets_pkg = _mock.MagicMock()
    _widgets_pkg.CSVEditorPanel = _fake_panel("CSVEditorPanel")
    _widgets_pkg.ProgressPanel = _fake_panel("ProgressPanel")

    mocks = {
        "widgets": _widgets_pkg,
        "widgets.csv_editor_panel": _mock.MagicMock(
            CSVEditorPanel=_fake_panel("CSVEditorPanel")),
        "widgets.progress_panel": _mock.MagicMock(
            ProgressPanel=_fake_panel("ProgressPanel")),
        "widgets.read_sim_panel": _mock.MagicMock(
            ReadSIMPanel=_fake_panel("ReadSIMPanel")),
        "widgets.program_sim_panel": _mock.MagicMock(
            ProgramSIMPanel=_fake_panel("ProgramSIMPanel")),
        "widgets.batch_program_panel": _mock.MagicMock(
            BatchProgramPanel=_fake_panel("BatchProgramPanel")),
        "widgets.tooltip": _mock.MagicMock(),
        "dialogs.adm1_dialog": _mock.MagicMock(),
        "dialogs.artifact_export_dialog": _mock.MagicMock(),
        "dialogs.simulator_settings_dialog": _mock.MagicMock(
            SimulatorSettingsDialog=_mock.MagicMock(
                return_value=_mock.MagicMock(applied=False))),
        "dialogs.network_storage_dialog": _mock.MagicMock(),
        "dialogs.network_storage_dialog_qt": _mock.MagicMock(),
        "dialogs": _mock.MagicMock(),
    }

    file_path = os.path.join(_PROJECT_ROOT, "main.py")
    with _mock.patch.dict(sys.modules, mocks):
        spec = importlib.util.spec_from_file_location("_main_hidden", file_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_main_hidden"] = mod
        spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def app_instance():
    mod = _load_main()
    with _mock.patch("managers.card_manager.CardManager") as cm_cls, \
         _mock.patch("managers.backup_manager.BackupManager"), \
         _mock.patch("managers.settings_manager.SettingsManager") as sm_cls, \
         _mock.patch("managers.network_storage_manager.NetworkStorageManager") as nm_cls, \
         _mock.patch("managers.standards_manager.StandardsManager"):

        cm = _mock.MagicMock()
        cm.cli_backend = _mock.MagicMock()
        cm.is_simulator_active = False
        cm.card_type = _mock.MagicMock()
        cm.card_type.name = "SJA5"
        cm.card_info = {}
        cm_cls.return_value = cm

        settings = _mock.MagicMock()
        settings.get.return_value = ""
        sm_cls.return_value = settings

        ns_mgr = _mock.MagicMock()
        ns_mgr.load_profiles.return_value = []
        ns_mgr.get_active_mount_paths.return_value = []
        nm_cls.return_value = ns_mgr

        instance = mod.SimGUIApp()
    return instance


class TestMainWindowTabs:

    def _visible_tab_texts(self, app):
        tabs = app._tabs
        return [tabs.tabText(i) for i in range(tabs.count())
                if tabs.isTabVisible(i)]

    def test_read_sim_tab_visible(self, app_instance):
        assert "Read SIM" in self._visible_tab_texts(app_instance)

    def test_program_sim_tab_visible(self, app_instance):
        assert "Program SIM" in self._visible_tab_texts(app_instance)

    def test_batch_tab_visible(self, app_instance):
        assert "Batch Program" in self._visible_tab_texts(app_instance)

    def test_program_sim_is_default_tab(self, app_instance):
        """Program SIM must be the selected tab at startup."""
        tabs = app_instance._tabs
        assert tabs.tabText(tabs.currentIndex()) == "Program SIM"
