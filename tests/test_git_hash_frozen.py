"""Verify _get_git_hash() behaviour in frozen (PyInstaller) and dev modes."""
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
        monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent", raising=False)
        with mock.patch("subprocess.run") as mock_run:
            _main.SimGUIApp._get_git_hash()
        mock_run.assert_not_called()

    def test_frozen_reads_githash_from_meipass(self, monkeypatch, tmp_path):
        """sys.frozen=True + GITHASH at sys._MEIPASS → returns trimmed content."""
        (tmp_path / "GITHASH").write_text("abc1234\n")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert _main.SimGUIApp._get_git_hash() == "abc1234"

    def test_frozen_missing_githash_returns_empty(self, monkeypatch, tmp_path):
        """sys.frozen=True + no GITHASH file → returns empty string, no exception."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert _main.SimGUIApp._get_git_hash() == ""

    def test_frozen_uses_meipass_not_file(self, monkeypatch, tmp_path):
        """sys._MEIPASS is used, not __file__, in frozen mode.

        GITHASH only exists under sys._MEIPASS; __file__ points elsewhere.
        The function must find the hash via _MEIPASS, proving it does not
        fall back to dirname(__file__).
        """
        meipass_dir = tmp_path / "meipass"
        meipass_dir.mkdir()
        (meipass_dir / "GITHASH").write_text("deadbeef\n")

        other_dir = tmp_path / "other"
        other_dir.mkdir()
        # Deliberately no GITHASH in other_dir

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
        monkeypatch.setattr(_main, "__file__", str(other_dir / "main.py"))

        assert _main.SimGUIApp._get_git_hash() == "deadbeef"

    def test_frozen_meipass_missing_falls_back_gracefully(self, monkeypatch, tmp_path):
        """If sys._MEIPASS is absent (edge case), falls back without crashing."""
        (tmp_path / "GITHASH").write_text("fallback\n")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        # Remove _MEIPASS if present
        if hasattr(sys, "_MEIPASS"):
            monkeypatch.delattr(sys, "_MEIPASS")
        # Point __file__ at tmp_path so the fallback finds GITHASH there
        monkeypatch.setattr(_main, "__file__", str(tmp_path / "main.py"))
        # Should return the hash via fallback, not raise
        result = _main.SimGUIApp._get_git_hash()
        assert result == "fallback"
