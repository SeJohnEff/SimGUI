"""Tests for managers.settings_manager module."""

import json
import os
import tempfile

import pytest

from managers.settings_manager import _DEFAULTS, SettingsManager


@pytest.fixture
def settings_path():
    """Provide a temporary file path for settings, cleaned up after test."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # start with no file
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def settings(settings_path):
    """Return a SettingsManager using a temp path."""
    return SettingsManager(path=settings_path)


class TestSettingsDefaults:
    def test_defaults_loaded_when_no_file(self, settings):
        for key, default_val in _DEFAULTS.items():
            assert settings.get(key) == default_val

    def test_get_unknown_key_returns_none(self, settings):
        assert settings.get("nonexistent_key") is None

    def test_get_with_explicit_default(self, settings):
        assert settings.get("nonexistent_key", "fallback") == "fallback"


class TestSettingsGetSet:
    def test_set_and_get(self, settings):
        settings.set("last_mcc_mnc", "99988")
        assert settings.get("last_mcc_mnc") == "99988"

    def test_set_int(self, settings):
        settings.set("last_batch_size", 50)
        assert settings.get("last_batch_size") == 50

    def test_set_bool(self, settings):
        settings.set("simulator_mode", True)
        assert settings.get("simulator_mode") is True

    def test_overwrite(self, settings):
        settings.set("last_spn", "Alpha")
        settings.set("last_spn", "Beta")
        assert settings.get("last_spn") == "Beta"


class TestSettingsPersistence:
    def test_save_and_reload(self, settings_path):
        sm1 = SettingsManager(path=settings_path)
        sm1.set("last_mcc_mnc", "31026")
        sm1.set("last_batch_size", 100)
        sm1.save()

        sm2 = SettingsManager(path=settings_path)
        assert sm2.get("last_mcc_mnc") == "31026"
        assert sm2.get("last_batch_size") == 100

    def test_save_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "a", "b", "c", "settings.json")
            sm = SettingsManager(path=nested)
            sm.set("last_spn", "TestNet")
            sm.save()
            assert os.path.isfile(nested)

    def test_load_corrupted_file(self, settings_path):
        with open(settings_path, "w") as fh:
            fh.write("{invalid json")
        sm = SettingsManager(path=settings_path)
        # Should fall back to defaults
        assert sm.get("last_batch_size") == _DEFAULTS["last_batch_size"]

    def test_save_preserves_extra_keys(self, settings_path):
        sm1 = SettingsManager(path=settings_path)
        sm1.set("custom_key", "custom_value")
        sm1.save()

        sm2 = SettingsManager(path=settings_path)
        assert sm2.get("custom_key") == "custom_value"


class TestSettingsLoadFromExisting:
    def test_load_existing_file(self, settings_path):
        data = {"last_mcc_mnc": "46001", "last_batch_size": 42}
        with open(settings_path, "w") as fh:
            json.dump(data, fh)

        sm = SettingsManager(path=settings_path)
        assert sm.get("last_mcc_mnc") == "46001"
        assert sm.get("last_batch_size") == 42
        # Keys not in file should return defaults
        assert sm.get("last_spn") == _DEFAULTS["last_spn"]
