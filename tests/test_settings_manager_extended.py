"""Extended tests for managers/settings_manager.py.

Targets missed lines: 72-73 (OSError path in save()).
"""

import os
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from managers.settings_manager import _DEFAULTS, SettingsManager


class TestSettingsManagerExtended:
    """Tests covering all branches in SettingsManager."""

    def test_save_ioerror_is_silently_caught(self, tmp_path):
        """save() catches OSError and logs instead of raising (lines 72-73)."""
        mgr = SettingsManager(path=str(tmp_path / "settings.json"))
        mgr.set("last_mcc_mnc", "310")
        # Make the directory un-writable to force an OSError on save
        with patch("builtins.open", side_effect=OSError("disk full")):
            # Should NOT raise — OSError is caught internally
            mgr.save()  # lines 72-73 executed

    def test_save_bad_directory_silently_fails(self, tmp_path):
        """save() to a path in /proc catches OSError without raising."""
        mgr = SettingsManager(path="/proc/cannot/settings.json")
        # Should not raise
        mgr.save()

    def test_defaults_loaded_when_file_missing(self, tmp_path):
        """When settings file doesn't exist, defaults are loaded."""
        path = str(tmp_path / "new_settings.json")
        mgr = SettingsManager(path=path)
        for k, v in _DEFAULTS.items():
            assert mgr.get(k) == v

    def test_load_bad_json_falls_back_to_defaults(self, tmp_path):
        """Corrupt JSON file causes fallback to defaults."""
        path = tmp_path / "bad.json"
        path.write_text("{not valid json}")
        mgr = SettingsManager(path=str(path))
        assert mgr.get("simulator_mode") == _DEFAULTS["simulator_mode"]

    def test_set_and_get_roundtrip(self, tmp_path):
        """set() stores a value that get() retrieves."""
        mgr = SettingsManager(path=str(tmp_path / "s.json"))
        mgr.set("last_mcc_mnc", "310210")
        assert mgr.get("last_mcc_mnc") == "310210"

    def test_get_unknown_key_returns_none(self, tmp_path):
        """get() returns None for a completely unknown key."""
        mgr = SettingsManager(path=str(tmp_path / "s.json"))
        assert mgr.get("nonexistent_key_xyz") is None

    def test_get_unknown_key_with_default(self, tmp_path):
        """get() returns the caller-supplied default for an unknown key."""
        mgr = SettingsManager(path=str(tmp_path / "s.json"))
        assert mgr.get("nonexistent_key_xyz", "fallback") == "fallback"

    def test_save_and_reload(self, tmp_path):
        """Values survive a save/reload cycle."""
        path = str(tmp_path / "persist.json")
        mgr = SettingsManager(path=path)
        mgr.set("last_spn", "TestSPN")
        mgr.save()

        mgr2 = SettingsManager(path=path)
        assert mgr2.get("last_spn") == "TestSPN"

    def test_default_path_uses_xdg_config_home(self, tmp_path, monkeypatch):
        """Default path respects XDG_CONFIG_HOME environment variable."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        mgr = SettingsManager()
        assert str(tmp_path) in mgr._path

    def test_simulator_mode_default_false(self, tmp_path):
        """simulator_mode defaults to False."""
        mgr = SettingsManager(path=str(tmp_path / "s.json"))
        assert mgr.get("simulator_mode") is False

    def test_last_batch_size_default(self, tmp_path):
        """last_batch_size defaults to 20."""
        mgr = SettingsManager(path=str(tmp_path / "s.json"))
        assert mgr.get("last_batch_size") == 20
