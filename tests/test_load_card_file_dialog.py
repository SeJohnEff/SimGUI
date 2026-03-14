"""Tests for dialogs.load_card_file_dialog — unified file picker for unknown cards."""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module import (no display required for these tests)
# ---------------------------------------------------------------------------

def _import_module():
    """Import the dialog module, skipping if tkinter is unavailable."""
    try:
        import tkinter as tk
        # Ensure we can create a Tk instance (headless envs may fail)
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except Exception:
        pytest.skip("No display available")
    from dialogs.load_card_file_dialog import LoadCardFileDialog, _SIM_FILETYPES
    return LoadCardFileDialog, _SIM_FILETYPES


# ---------------------------------------------------------------------------
# Unit tests for module-level constants
# ---------------------------------------------------------------------------

class TestModuleLevelConstants:
    def test_sim_filetypes_is_list(self):
        _, filetypes = _import_module()
        assert isinstance(filetypes, list)
        assert len(filetypes) >= 3

    def test_sim_filetypes_includes_csv(self):
        _, filetypes = _import_module()
        patterns = [ft[1] for ft in filetypes]
        assert any("csv" in p for p in patterns)

    def test_sim_filetypes_includes_eml(self):
        _, filetypes = _import_module()
        patterns = [ft[1] for ft in filetypes]
        assert any("eml" in p for p in patterns)


# ---------------------------------------------------------------------------
# Dialog construction tests
# ---------------------------------------------------------------------------

class TestDialogConstruction:
    def test_dialog_creates_with_no_mounts(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = []
            dlg = LoadCardFileDialog(root, "8949440000001672706", ns)
            assert dlg.selected_path is None
            assert dlg._iccid == "8949440000001672706"
            dlg.destroy()
        finally:
            root.destroy()

    def test_dialog_creates_with_mounts(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = [
                ("NAS Share", "/tmp/simgui-mounts/NAS_Share"),
            ]
            dlg = LoadCardFileDialog(root, "89001234", ns)
            assert dlg.selected_path is None
            dlg.destroy()
        finally:
            root.destroy()

    def test_dialog_title(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = []
            dlg = LoadCardFileDialog(root, "ICCID123", ns)
            assert dlg.title() == "Load Card Data File"
            dlg.destroy()
        finally:
            root.destroy()

    def test_dialog_with_none_ns_manager(self):
        """ns_manager=None should not crash."""
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            dlg = LoadCardFileDialog(root, "ICCID123", None)
            assert dlg.selected_path is None
            dlg.destroy()
        finally:
            root.destroy()


# ---------------------------------------------------------------------------
# Cancel behaviour
# ---------------------------------------------------------------------------

class TestCancel:
    def test_cancel_sets_none(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = []
            dlg = LoadCardFileDialog(root, "ICCID123", ns)
            dlg._on_cancel()
            assert dlg.selected_path is None
        finally:
            root.destroy()


# ---------------------------------------------------------------------------
# Browse local behaviour
# ---------------------------------------------------------------------------

class TestBrowseLocal:
    def test_browse_local_sets_path(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = []
            dlg = LoadCardFileDialog(root, "ICCID123", ns,
                                     initial_dir="/tmp")
            with patch("dialogs.load_card_file_dialog.filedialog") as mock_fd:
                mock_fd.askopenfilename.return_value = "/tmp/test.csv"
                dlg._on_browse_local()
            assert dlg.selected_path == "/tmp/test.csv"
        finally:
            root.destroy()

    def test_browse_local_cancel(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = []
            dlg = LoadCardFileDialog(root, "ICCID123", ns)
            with patch("dialogs.load_card_file_dialog.filedialog") as mock_fd:
                mock_fd.askopenfilename.return_value = ""
                dlg._on_browse_local()
            assert dlg.selected_path is None
        finally:
            root.destroy()


# ---------------------------------------------------------------------------
# Browse share behaviour
# ---------------------------------------------------------------------------

class TestBrowseShare:
    def test_browse_share_sets_path(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = [
                ("NAS", "/mnt/nas"),
            ]
            dlg = LoadCardFileDialog(root, "ICCID123", ns)
            with patch("dialogs.load_card_file_dialog.filedialog") as mock_fd:
                mock_fd.askopenfilename.return_value = "/mnt/nas/batch.csv"
                dlg._on_browse_share("/mnt/nas")
            assert dlg.selected_path == "/mnt/nas/batch.csv"
        finally:
            root.destroy()


# ---------------------------------------------------------------------------
# Populate shares
# ---------------------------------------------------------------------------

class TestPopulateShares:
    def test_populate_with_multiple_mounts(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = [
                ("Share A", "/mnt/a"),
                ("Share B", "/mnt/b"),
            ]
            dlg = LoadCardFileDialog(root, "ICCID123", ns)
            # Should have child widgets for both shares
            children = dlg._shares_inner.winfo_children()
            # At least 2 row frames (one per share)
            assert len(children) >= 2
            dlg.destroy()
        finally:
            root.destroy()

    def test_populate_no_mounts_shows_message(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = []
            dlg = LoadCardFileDialog(root, "ICCID123", ns)
            children = dlg._shares_inner.winfo_children()
            # Should have a single label with the "no shares" message
            assert len(children) == 1
            dlg.destroy()
        finally:
            root.destroy()


# ---------------------------------------------------------------------------
# Connect share flow
# ---------------------------------------------------------------------------

class TestConnectShare:
    def test_connect_share_refreshes_list(self):
        LoadCardFileDialog, _ = _import_module()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = []
            dlg = LoadCardFileDialog(root, "ICCID123", ns)

            # Simulate: after the NetworkStorageDialog closes, a share appears
            original_populate = dlg._populate_shares
            populate_called = []

            def track_populate():
                populate_called.append(True)
                original_populate()

            dlg._populate_shares = track_populate

            with patch("dialogs.load_card_file_dialog.NetworkStorageDialog"):
                dlg._on_connect_share()

            assert len(populate_called) >= 1
            dlg.destroy()
        finally:
            root.destroy()
