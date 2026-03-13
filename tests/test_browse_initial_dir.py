"""Tests for get_browse_initial_dir — smart initial directory for file dialogs."""

import os
import tempfile
from unittest.mock import MagicMock

from utils import get_browse_initial_dir


class TestGetBrowseInitialDir:
    """Tests for the browse initial directory helper."""

    def test_no_args_returns_none(self):
        """No manager, no last_dir → None (tkinter default)."""
        assert get_browse_initial_dir() is None

    def test_no_manager_no_last_dir(self):
        """Explicit None for both → None."""
        assert get_browse_initial_dir(ns_manager=None, last_dir=None) is None

    def test_last_dir_exists(self):
        """last_dir that exists on disk → returned as-is."""
        with tempfile.TemporaryDirectory() as td:
            result = get_browse_initial_dir(last_dir=td)
            assert result == td

    def test_last_dir_missing(self):
        """last_dir that doesn't exist → falls through."""
        result = get_browse_initial_dir(last_dir="/nonexistent/path/xyz")
        assert result is None

    def test_last_dir_takes_priority_over_mount(self):
        """last_dir (existing) beats an active mount."""
        with tempfile.TemporaryDirectory() as td:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = [
                ("NAS", "/tmp/simgui-mounts/NAS"),
            ]
            result = get_browse_initial_dir(ns_manager=ns, last_dir=td)
            assert result == td

    def test_mount_used_when_no_last_dir(self):
        """No last_dir, one active mount → mount path returned."""
        with tempfile.TemporaryDirectory() as mount_path:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = [
                ("NAS", mount_path),
            ]
            result = get_browse_initial_dir(ns_manager=ns)
            assert result == mount_path

    def test_mount_used_when_last_dir_missing(self):
        """last_dir doesn't exist, active mount available → mount returned."""
        with tempfile.TemporaryDirectory() as mount_path:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = [
                ("NAS", mount_path),
            ]
            result = get_browse_initial_dir(
                ns_manager=ns, last_dir="/nonexistent/dir",
            )
            assert result == mount_path

    def test_first_mount_returned_when_multiple(self):
        """Multiple active mounts → first one is returned."""
        with tempfile.TemporaryDirectory() as mp1, \
             tempfile.TemporaryDirectory() as mp2:
            ns = MagicMock()
            ns.get_active_mount_paths.return_value = [
                ("NAS1", mp1),
                ("NAS2", mp2),
            ]
            result = get_browse_initial_dir(ns_manager=ns)
            assert result == mp1

    def test_no_active_mounts(self):
        """Manager exists but no mounts active → None."""
        ns = MagicMock()
        ns.get_active_mount_paths.return_value = []
        result = get_browse_initial_dir(ns_manager=ns)
        assert result is None

    def test_empty_last_dir_string(self):
        """Empty string for last_dir → treated as not set."""
        assert get_browse_initial_dir(last_dir="") is None

    def test_last_dir_is_file_not_directory(self):
        """last_dir points to a file, not a directory → falls through."""
        with tempfile.NamedTemporaryFile() as tf:
            result = get_browse_initial_dir(last_dir=tf.name)
            # os.path.isdir returns False for files
            assert result is None
