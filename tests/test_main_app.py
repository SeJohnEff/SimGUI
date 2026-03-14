"""
Tests for main.py — SimGUIApp class and helper functions.

The app is loaded via importlib with all tkinter and widget modules mocked,
so we can exercise the logic without a real display.
"""

import importlib
import importlib.util
import os
import sys
import types
from unittest import mock as _mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")


# ---------------------------------------------------------------------------
# Shared fake infra (minimal, same pattern as test_ui_instantiation.py)
# ---------------------------------------------------------------------------

class _FakeWidget:
    _cfg: dict = {}

    def __init__(self, *a, **kw):
        self._cfg = {}

    def pack(self, **kw): pass
    def pack_forget(self): pass
    def grid(self, **kw): pass
    def grid_columnconfigure(self, *a, **kw): pass
    def grid_rowconfigure(self, *a, **kw): pass
    def grid_remove(self): pass
    def configure(self, **kw): self._cfg.update(kw)
    def config(self, **kw): self._cfg.update(kw)
    def __setitem__(self, k, v): self._cfg[k] = v
    def __getitem__(self, k): return self._cfg.get(k, "")
    def bind(self, *a, **kw): pass
    def bind_all(self, *a, **kw): pass
    def winfo_exists(self): return True
    def winfo_width(self): return 1024
    def winfo_height(self): return 700
    def winfo_rootx(self): return 0
    def winfo_rooty(self): return 0
    def after(self, ms, func=None, *args):
        if func:
            func(*args)
    def delete(self, *a): pass
    def insert(self, *a, **kw): pass
    def focus_set(self): pass
    def destroy(self): pass
    def get_children(self): return []
    def selection(self): return []
    def update_idletasks(self): pass
    def columnconfigure(self, *a, **kw): pass
    def rowconfigure(self, *a, **kw): pass
    def protocol(self, *a, **kw): pass
    def geometry(self, *a): return "1024x700"
    def minsize(self, *a): pass
    def title(self, *a): pass
    def mainloop(self): pass
    def iconphoto(self, *a, **kw): pass
    def clipboard_clear(self): pass
    def clipboard_append(self, *a): pass
    def clipboard_get(self): return ""
    def select_present(self): return False
    def add(self, widget, **kw): pass
    def add_cascade(self, **kw): pass
    def add_command(self, **kw): pass
    def add_separator(self, **kw): pass
    def add_radiobutton(self, **kw): pass
    def entryconfigure(self, *a, **kw): pass
    def index(self, *a): return 4
    def place(self, **kw): pass
    def see(self, *a): pass


class _FakeVar:
    def __init__(self, *a, value=None, **kw):
        self._v = value if value is not None else ""

    def get(self):
        return self._v

    def set(self, v):
        self._v = v

    def trace_add(self, *a, **kw):
        pass


def _build_mocks():
    _tk = _mock.MagicMock()
    _ttk = _mock.MagicMock()

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
    _ttk.Scale = _FakeWidget

    _tk.Canvas = _FakeWidget
    _tk.Text = _FakeWidget
    _tk.Listbox = _FakeWidget
    _tk.Label = _FakeWidget
    _tk.Menu = _FakeWidget
    _tk.Tk = type("FakeTk", (_FakeWidget,), {})
    _tk.Toplevel = _FakeWidget
    _tk.PhotoImage = _FakeWidget

    _tk.StringVar = lambda *a, **kw: _FakeVar(**kw)
    _tk.BooleanVar = lambda *a, **kw: _FakeVar(value=kw.get('value', False))
    _tk.IntVar = lambda *a, **kw: _FakeVar(value=kw.get('value', 0))

    _tk.W = "w"; _tk.E = "e"; _tk.X = "x"; _tk.Y = "y"
    _tk.N = "n"; _tk.S = "s"; _tk.NW = "nw"; _tk.NE = "ne"
    _tk.LEFT = "left"; _tk.RIGHT = "right"; _tk.TOP = "top"
    _tk.BOTTOM = "bottom"; _tk.BOTH = "both"; _tk.END = "end"
    _tk.HORIZONTAL = "horizontal"; _tk.VERTICAL = "vertical"
    _tk.NORMAL = "normal"; _tk.DISABLED = "disabled"
    _tk.WORD = "word"; _tk.NONE = "none"
    _tk.SUNKEN = "sunken"; _tk.SOLID = "solid"
    _tk.INSERT = "insert"; _tk.SEL_FIRST = "sel.first"; _tk.SEL_LAST = "sel.last"
    _tk.TclError = Exception
    _tk.ttk = _ttk

    _th = _mock.MagicMock()
    _th.ModernTheme.get_color.return_value = "#000000"
    _th.ModernTheme.get_padding.side_effect = lambda k: 8
    _th.ModernTheme.get_font.return_value = ("Arial", 10)

    return _tk, _ttk, _th


def _load_main():
    """Load main.py with all dependencies mocked."""
    _tk, _ttk, _th = _build_mocks()

    for k in list(sys.modules.keys()):
        if (k.startswith("widgets") or k.startswith("dialogs")) and "test_" not in k:
            del sys.modules[k]

    _widgets_pkg = types.ModuleType("widgets")
    _widgets_pkg.__path__ = [os.path.join(_PROJECT_ROOT, "widgets")]
    _dialogs_pkg = types.ModuleType("dialogs")
    _dialogs_pkg.__path__ = [os.path.join(_PROJECT_ROOT, "dialogs")]

    # Mock all widget panels as fake classes
    def _fake_panel_class(name):
        class FakePanel(_FakeWidget):
            def __init__(self, *a, **kw):
                super().__init__()
                self.on_csv_loaded_callback = None
                self.on_detect_callback = None
                self.on_authenticate_callback = None
                self._tree = _FakeWidget()
                self._tree.selection = lambda: []
                self._tree.index = lambda item: 0
            def get_csv_manager(self):
                mgr = _mock.MagicMock()
                mgr.load_file.return_value = True
                mgr.save_csv.return_value = True
                mgr.get_card.return_value = {"ICCID": "89001"}
                return mgr
            def _refresh_table(self): pass
            def refresh(self): pass
            def set_status(self, *a, **kw): pass
            def set_card_info(self, **kw): pass
            def set_auth_status(self, *a): pass
            def set_simulator_info(self, *a): pass
            def has_unsaved_changes(self): return False
            def get_programmed_records(self): return []
            def load_csv_file(self, *a, **kw): return True
            def set_standards_manager(self, *a): pass
            def refresh_standards(self): pass
            def on_card_detected(self, *a, **kw): pass
            def on_card_removed(self): pass
            def clear_card_info(self): pass
            def set_programmed_indicator(self, *a): pass
            on_card_programmed_callback = None
        FakePanel.__name__ = name
        return FakePanel

    _card_panel_mock = _mock.MagicMock()
    _card_panel_mock.CardStatusPanel = _fake_panel_class("CardStatusPanel")

    _csv_panel_mock = _mock.MagicMock()
    _csv_panel_mock.CSVEditorPanel = _fake_panel_class("CSVEditorPanel")

    _prog_panel_mock = _mock.MagicMock()
    _prog_panel_mock.ProgressPanel = _fake_panel_class("ProgressPanel")

    _read_panel_mock = _mock.MagicMock()
    _read_panel_mock.ReadSIMPanel = _fake_panel_class("ReadSIMPanel")

    _program_panel_mock = _mock.MagicMock()
    _program_panel_mock.ProgramSIMPanel = _fake_panel_class("ProgramSIMPanel")

    _batch_panel_mock = _mock.MagicMock()
    _batch_panel_mock.BatchProgramPanel = _fake_panel_class("BatchProgramPanel")

    # Mock dialogs
    _adm1_dlg = _mock.MagicMock()
    _adm1_dlg.ADM1Dialog.return_value.get_adm1.return_value = ("12345678", False)

    _artifact_dlg = _mock.MagicMock()
    _sim_settings_dlg = _mock.MagicMock()
    _sim_settings_dlg.SimulatorSettingsDialog.return_value.applied = False

    _ns_dlg = _mock.MagicMock()

    mocks = {
        "tkinter": _tk,
        "tkinter.ttk": _ttk,
        "tkinter.filedialog": _mock.MagicMock(),
        "tkinter.messagebox": _mock.MagicMock(),
        "theme": _th,
        "widgets": _widgets_pkg,
        "widgets.tooltip": _mock.MagicMock(),
        "dialogs": _dialogs_pkg,
        "widgets.card_status_panel": _card_panel_mock,
        "widgets.csv_editor_panel": _csv_panel_mock,
        "widgets.progress_panel": _prog_panel_mock,
        "widgets.read_sim_panel": _read_panel_mock,
        "widgets.program_sim_panel": _program_panel_mock,
        "widgets.batch_program_panel": _batch_panel_mock,
        "dialogs.adm1_dialog": _adm1_dlg,
        "dialogs.artifact_export_dialog": _artifact_dlg,
        "dialogs.simulator_settings_dialog": _sim_settings_dlg,
        "dialogs.network_storage_dialog": _ns_dlg,
    }

    file_path = os.path.join(_PROJECT_ROOT, "main.py")
    with _mock.patch.dict(sys.modules, mocks):
        spec = importlib.util.spec_from_file_location("main_module", file_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["main_module"] = mod
        spec.loader.exec_module(mod)
    return mod


def _make_app(mod):
    """Create a SimGUIApp instance, patching managers to avoid real I/O."""
    with _mock.patch("managers.card_manager.CardManager") as cm_cls, \
         _mock.patch("managers.backup_manager.BackupManager"), \
         _mock.patch("managers.settings_manager.SettingsManager") as sm_cls, \
         _mock.patch("managers.network_storage_manager.NetworkStorageManager") as nm_cls, \
         _mock.patch("managers.standards_manager.StandardsManager"):

        cm = _mock.MagicMock()
        cm.cli_backend = _mock.MagicMock()
        cm.is_simulator_active = False
        cm.card_type = _mock.MagicMock()
        cm.card_type.name = "USIM"
        cm.card_info = {"IMSI": "99988", "ICCID": "89001"}
        cm.detect_card.return_value = (True, "Card detected")
        cm.authenticate.return_value = (True, "Authenticated")
        cm.get_remaining_attempts.return_value = 3
        cm.get_simulator_info.return_value = None
        cm.read_public_data.return_value = None
        cm_cls.return_value = cm

        settings = _mock.MagicMock()
        settings.get.return_value = ""
        sm_cls.return_value = settings

        ns_mgr = _mock.MagicMock()
        ns_mgr.load_profiles.return_value = []
        ns_mgr.get_active_mount_paths.return_value = []
        nm_cls.return_value = ns_mgr

        app = mod.SimGUIApp()
        return app, cm, settings, ns_mgr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSimGUIAppInstantiation:
    def test_module_loads(self):
        mod = _load_main()
        assert hasattr(mod, "SimGUIApp")

    def test_instantiation(self):
        mod = _load_main()
        app, cm, settings, ns = _make_app(mod)
        assert app is not None

    def test_has_required_attributes(self):
        mod = _load_main()
        app, cm, settings, ns = _make_app(mod)
        assert hasattr(app, "_card_manager")
        assert hasattr(app, "_settings")
        assert hasattr(app, "_ns_manager")
        assert hasattr(app, "last_read_data")
        assert isinstance(app.last_read_data, dict)


class TestSimGUIAppCallbacks:
    def _get_app(self):
        mod = _load_main()
        return _make_app(mod)

    def test_on_detect_card_success(self):
        app, cm, settings, ns = self._get_app()
        cm.detect_card.return_value = (True, "Card detected")
        cm.get_simulator_info.return_value = None
        app._on_detect_card()

    def test_on_detect_card_failure(self):
        app, cm, settings, ns = self._get_app()
        cm.detect_card.return_value = (False, "No card")
        cm.get_simulator_info.return_value = None
        app._on_detect_card()

    def test_on_detect_card_with_sim_info(self):
        app, cm, settings, ns = self._get_app()
        cm.detect_card.return_value = (True, "SIM detected")
        cm.is_simulator_active = True
        cm.get_simulator_info.return_value = {"current_index": 0, "total_cards": 5}
        app._on_detect_card()

    def test_on_authenticate_no_adm1(self):
        app, cm, settings, ns = self._get_app()
        import sys
        mod_mocks = sys.modules.get("dialogs.adm1_dialog")
        if mod_mocks:
            mod_mocks.ADM1Dialog.return_value.get_adm1.return_value = (None, False)
        app._on_authenticate()

    def test_on_authenticate_success(self):
        app, cm, settings, ns = self._get_app()
        import sys
        mod_mocks = sys.modules.get("dialogs.adm1_dialog")
        if mod_mocks:
            mod_mocks.ADM1Dialog.return_value.get_adm1.return_value = ("12345678", False)
        cm.authenticate.return_value = (True, "Authenticated")
        cm.is_simulator_active = False
        app._on_authenticate()

    def test_on_authenticate_failure(self):
        app, cm, settings, ns = self._get_app()
        import sys
        mod_mocks = sys.modules.get("dialogs.adm1_dialog")
        if mod_mocks:
            mod_mocks.ADM1Dialog.return_value.get_adm1.return_value = ("12345678", False)
        cm.authenticate.return_value = (False, "Wrong key")
        cm.is_simulator_active = False
        app._on_authenticate()

    def test_on_authenticate_iccid_mismatch(self):
        app, cm, settings, ns = self._get_app()
        import sys
        mod_mocks = sys.modules.get("dialogs.adm1_dialog")
        if mod_mocks:
            mod_mocks.ADM1Dialog.return_value.get_adm1.return_value = ("12345678", False)
        cm.authenticate.return_value = (False, "ICCID mismatch: expected 89001")
        cm.is_simulator_active = False
        app._on_authenticate()

    def test_get_expected_iccid_no_selection(self):
        app, cm, settings, ns = self._get_app()
        app._csv_panel._tree.selection = lambda: []
        result = app._get_expected_iccid()
        assert result is None

    def test_get_expected_iccid_with_selection(self):
        app, cm, settings, ns = self._get_app()
        app._csv_panel._tree.selection = lambda: ["item0"]
        app._csv_panel._tree.index = lambda item: 0
        mgr = _mock.MagicMock()
        mgr.get_card.return_value = {"ICCID": "89001"}
        app._csv_panel.get_csv_manager = lambda: mgr
        result = app._get_expected_iccid()
        assert result == "89001"

    def test_get_expected_iccid_exception(self):
        app, cm, settings, ns = self._get_app()
        app._csv_panel.get_csv_manager = _mock.MagicMock(side_effect=Exception("oops"))
        result = app._get_expected_iccid()
        assert result is None

    def test_on_mode_change_to_simulator(self):
        app, cm, settings, ns = self._get_app()
        app._mode_var.set("simulator")
        cm.get_simulator_info.return_value = None
        cm.detect_card.return_value = (True, "Virtual card")
        app._on_mode_change()

    def test_on_mode_change_to_hardware(self):
        app, cm, settings, ns = self._get_app()
        app._mode_var.set("hardware")
        app._on_mode_change()

    def test_update_sim_menu_state_normal(self):
        app, cm, settings, ns = self._get_app()
        import sys
        import tkinter as tk
        app._update_sim_menu_state("normal")

    def test_update_sim_menu_state_disabled(self):
        app, cm, settings, ns = self._get_app()
        app._update_sim_menu_state("disabled")

    def test_on_next_virtual_card_not_active(self):
        app, cm, settings, ns = self._get_app()
        cm.is_simulator_active = False
        app._on_next_virtual_card()
        cm.next_virtual_card.assert_not_called()

    def test_on_next_virtual_card_active(self):
        app, cm, settings, ns = self._get_app()
        cm.is_simulator_active = True
        cm.next_virtual_card.return_value = (1, 5)
        cm.detect_card.return_value = (True, "Virtual card")
        cm.get_simulator_info.return_value = None
        app._on_next_virtual_card()

    def test_on_next_virtual_card_no_result(self):
        app, cm, settings, ns = self._get_app()
        cm.is_simulator_active = True
        cm.next_virtual_card.return_value = None
        app._on_next_virtual_card()

    def test_on_previous_virtual_card_not_active(self):
        app, cm, settings, ns = self._get_app()
        cm.is_simulator_active = False
        app._on_previous_virtual_card()

    def test_on_previous_virtual_card_active(self):
        app, cm, settings, ns = self._get_app()
        cm.is_simulator_active = True
        cm.previous_virtual_card.return_value = (0, 5)
        cm.detect_card.return_value = (True, "Virtual card")
        cm.get_simulator_info.return_value = None
        app._on_previous_virtual_card()

    def test_on_simulator_settings_not_active(self):
        app, cm, settings, ns = self._get_app()
        cm.is_simulator_active = False
        app._on_simulator_settings()

    def test_on_simulator_settings_active(self):
        app, cm, settings, ns = self._get_app()
        cm.is_simulator_active = True
        sim = _mock.MagicMock()
        sim.settings.num_cards = 10
        cm._simulator = sim
        import sys
        mod_mocks = sys.modules.get("dialogs.simulator_settings_dialog")
        if mod_mocks:
            inst = mod_mocks.SimulatorSettingsDialog.return_value
            inst.applied = True
            inst.applied.__bool__ = lambda self: True
        app._on_simulator_settings()

    def test_on_reset_simulator_not_active(self):
        app, cm, settings, ns = self._get_app()
        cm.is_simulator_active = False
        app._on_reset_simulator()

    def test_on_reset_simulator_active(self):
        app, cm, settings, ns = self._get_app()
        cm.is_simulator_active = True
        sim = _mock.MagicMock()
        cm._simulator = sim
        cm.detect_card.return_value = (True, "Reset done")
        cm.get_simulator_info.return_value = None
        app._on_reset_simulator()

    def test_on_network_storage(self):
        app, cm, settings, ns = self._get_app()
        app._on_network_storage()

    def test_on_export_artifacts_no_records(self):
        app, cm, settings, ns = self._get_app()
        app._batch_panel.get_programmed_records = _mock.MagicMock(return_value=[])
        app.last_read_data = {}
        ns.load_profiles.return_value = []
        app._on_export_artifacts()

    def test_on_export_artifacts_with_last_read(self):
        app, cm, settings, ns = self._get_app()
        app._batch_panel.get_programmed_records = _mock.MagicMock(return_value=[])
        app.last_read_data = {"ICCID": "89001", "IMSI": "99988"}
        ns.load_profiles.return_value = []
        app._on_export_artifacts()

    def test_on_export_artifacts_with_batch_records(self):
        app, cm, settings, ns = self._get_app()
        app._batch_panel.get_programmed_records = _mock.MagicMock(
            return_value=[{"ICCID": "89001"}, {"ICCID": "89002"}]
        )
        ns.load_profiles.return_value = []
        app._on_export_artifacts()

    def test_on_export_artifacts_with_profiles(self):
        app, cm, settings, ns = self._get_app()
        app._batch_panel.get_programmed_records = _mock.MagicMock(
            return_value=[{"ICCID": "89001"}]
        )
        prof = _mock.MagicMock()
        prof.export_fields = ["ICCID", "IMSI"]
        ns.load_profiles.return_value = [prof]
        app._on_export_artifacts()

    def test_on_about(self):
        app, cm, settings, ns = self._get_app()
        app._on_about()

    def test_on_close_no_unsaved(self):
        app, cm, settings, ns = self._get_app()
        app._csv_panel.has_unsaved_changes = False
        settings.get.return_value = "1024x700"
        app._on_close()

    def test_on_open_csv_no_path(self):
        app, cm, settings, ns = self._get_app()
        import sys
        sys.modules["tkinter.filedialog"].askopenfilename.return_value = ""
        app._on_open_csv()

    def test_on_open_csv_success(self):
        app, cm, settings, ns = self._get_app()
        import sys
        sys.modules["tkinter.filedialog"].askopenfilename.return_value = "/fake/cards.csv"
        mgr = _mock.MagicMock()
        mgr.load_file.return_value = True
        app._csv_panel.get_csv_manager = lambda: mgr
        app._on_open_csv()

    def test_on_open_csv_no_data(self):
        app, cm, settings, ns = self._get_app()
        import sys
        sys.modules["tkinter.filedialog"].askopenfilename.return_value = "/fake/cards.csv"
        mgr = _mock.MagicMock()
        mgr.load_file.return_value = False
        app._csv_panel.get_csv_manager = lambda: mgr
        app._on_open_csv()

    def test_on_open_csv_value_error(self):
        app, cm, settings, ns = self._get_app()
        import sys
        sys.modules["tkinter.filedialog"].askopenfilename.return_value = "/bad/file.csv"
        mgr = _mock.MagicMock()
        mgr.load_file.side_effect = ValueError("bad format")
        app._csv_panel.get_csv_manager = lambda: mgr
        app._on_open_csv()

    def test_on_save_csv_no_path(self):
        app, cm, settings, ns = self._get_app()
        import sys
        sys.modules["tkinter.filedialog"].asksaveasfilename.return_value = ""
        app._on_save_csv()

    def test_on_save_csv_success(self):
        app, cm, settings, ns = self._get_app()
        import sys
        sys.modules["tkinter.filedialog"].asksaveasfilename.return_value = "/fake/out.csv"
        mgr = _mock.MagicMock()
        mgr.save_csv.return_value = True
        app._csv_panel.get_csv_manager = lambda: mgr
        app._on_save_csv()

    def test_on_save_csv_failure(self):
        app, cm, settings, ns = self._get_app()
        import sys
        sys.modules["tkinter.filedialog"].asksaveasfilename.return_value = "/fake/out.csv"
        mgr = _mock.MagicMock()
        mgr.save_csv.return_value = False
        app._csv_panel.get_csv_manager = lambda: mgr
        app._on_save_csv()

    def test_on_close_unsaved_cancel(self):
        app, cm, settings, ns = self._get_app()
        app._csv_panel.has_unsaved_changes = True
        import sys
        sys.modules["tkinter.messagebox"].askyesnocancel.return_value = None
        app._on_close()

    def test_on_close_unsaved_save(self):
        app, cm, settings, ns = self._get_app()
        app._csv_panel.has_unsaved_changes = True
        import sys
        sys.modules["tkinter.messagebox"].askyesnocancel.return_value = True
        sys.modules["tkinter.filedialog"].asksaveasfilename.return_value = ""
        app._on_close()

    def test_on_close_unsaved_discard(self):
        app, cm, settings, ns = self._get_app()
        app._csv_panel.has_unsaved_changes = True
        import sys
        sys.modules["tkinter.messagebox"].askyesnocancel.return_value = False
        settings.get.return_value = "1024x700"
        app._on_close()

    def test_build_menu(self):
        mod = _load_main()
        app, cm, settings, ns = _make_app(mod)
        # Ensure the menu was built (attributes exist)
        assert hasattr(app, "_card_menu")
        assert hasattr(app, "_sim_menu_start")

    def test_bind_shortcuts(self):
        mod = _load_main()
        app, cm, settings, ns = _make_app(mod)
        # Should not raise
        app._bind_shortcuts()

    def test_simulator_mode_restored(self):
        """Test instantiation when simulator_mode is True in settings."""
        mod = _load_main()
        with _mock.patch("managers.card_manager.CardManager") as cm_cls, \
             _mock.patch("managers.backup_manager.BackupManager"), \
             _mock.patch("managers.settings_manager.SettingsManager") as sm_cls, \
             _mock.patch("managers.network_storage_manager.NetworkStorageManager") as nm_cls:

            cm = _mock.MagicMock()
            cm.cli_backend = _mock.MagicMock()
            cm.is_simulator_active = False
            cm.card_type = _mock.MagicMock()
            cm.card_type.name = "USIM"
            cm.card_info = {}
            cm.detect_card.return_value = (True, "Virtual card")
            cm.get_remaining_attempts.return_value = 3
            cm.get_simulator_info.return_value = {"current_index": 0, "total_cards": 5}
            cm_cls.return_value = cm

            settings = _mock.MagicMock()
            def _get(key, default=""):
                if key == "simulator_mode":
                    return True
                if key == "window_geometry":
                    return ""
                return default
            settings.get.side_effect = _get
            sm_cls.return_value = settings

            ns_mgr = _mock.MagicMock()
            ns_mgr.load_profiles.return_value = []
            nm_cls.return_value = ns_mgr

            app = mod.SimGUIApp()
            assert app is not None

    def test_no_cli_backend_forces_simulator(self):
        """Test that missing CLI backend triggers simulator mode."""
        mod = _load_main()
        with _mock.patch("managers.card_manager.CardManager") as cm_cls, \
             _mock.patch("managers.backup_manager.BackupManager"), \
             _mock.patch("managers.settings_manager.SettingsManager") as sm_cls, \
             _mock.patch("managers.network_storage_manager.NetworkStorageManager") as nm_cls:

            import sys

            # Get the CLIBackend enum from the real managers module
            from managers.card_manager import CLIBackend

            cm = _mock.MagicMock()
            cm.cli_backend = CLIBackend.NONE  # triggers simulator mode
            cm.is_simulator_active = False
            cm.card_type = _mock.MagicMock()
            cm.card_type.name = "USIM"
            cm.card_info = {}
            cm.detect_card.return_value = (True, "Virtual card")
            cm.get_remaining_attempts.return_value = 3
            cm.get_simulator_info.return_value = None
            cm_cls.return_value = cm

            settings = _mock.MagicMock()
            settings.get.return_value = ""
            sm_cls.return_value = settings

            ns_mgr = _mock.MagicMock()
            ns_mgr.load_profiles.return_value = []
            nm_cls.return_value = ns_mgr

            app = mod.SimGUIApp()
            assert app is not None

    def test_window_geometry_restored(self):
        """Test that a saved window geometry is applied."""
        mod = _load_main()
        with _mock.patch("managers.card_manager.CardManager") as cm_cls, \
             _mock.patch("managers.backup_manager.BackupManager"), \
             _mock.patch("managers.settings_manager.SettingsManager") as sm_cls, \
             _mock.patch("managers.network_storage_manager.NetworkStorageManager") as nm_cls:

            cm = _mock.MagicMock()
            cm.cli_backend = _mock.MagicMock()
            cm.is_simulator_active = False
            cm.card_type = _mock.MagicMock()
            cm.card_type.name = "USIM"
            cm.card_info = {}
            cm.detect_card.return_value = (False, "No card")
            cm.get_remaining_attempts.return_value = 3
            cm.get_simulator_info.return_value = None
            cm_cls.return_value = cm

            settings = _mock.MagicMock()
            def _get(key, default=""):
                if key == "window_geometry":
                    return "800x600+100+100"
                return default
            settings.get.side_effect = _get
            sm_cls.return_value = settings

            ns_mgr = _mock.MagicMock()
            ns_mgr.load_profiles.return_value = []
            nm_cls.return_value = ns_mgr

            app = mod.SimGUIApp()
            assert app is not None
