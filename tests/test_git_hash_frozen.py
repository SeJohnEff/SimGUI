"""Verify _get_git_hash() never invokes git when running as a frozen/packaged app."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as _main  # noqa: E402


class TestGetGitHashFrozen:
    """_get_git_hash() contract for the packaged (PyInstaller frozen) app."""

    def test_frozen_skips_subprocess(self, monkeypatch):
        """sys.frozen=True must prevent any subprocess.run call."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        with mock.patch("subprocess.run") as mock_run:
            _main.SimGUIApp._get_git_hash()
        mock_run.assert_not_called()

    def test_frozen_reads_githash_file(self, monkeypatch, tmp_path):
        """sys.frozen=True + GITHASH file present → returns trimmed file content."""
        (tmp_path / "GITHASH").write_text("abc1234\n")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        # Point the function's __file__ lookup at tmp_path
        monkeypatch.setattr(_main, "__file__", str(tmp_path / "main.py"))
        assert _main.SimGUIApp._get_git_hash() == "abc1234"

    def test_frozen_missing_githash_returns_empty(self, monkeypatch, tmp_path):
        """sys.frozen=True + no GITHASH file → returns empty string, no exception."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(_main, "__file__", str(tmp_path / "main.py"))
        assert _main.SimGUIApp._get_git_hash() == ""
