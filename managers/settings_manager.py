"""
Settings Manager — Persistent JSON configuration for SimGUI.

Stores user preferences at ``~/.config/simgui/settings.json``
(respects ``XDG_CONFIG_HOME``).
"""

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "last_mcc_mnc": "",
    "last_customer_code": "",
    "last_sim_type_code": "",
    "last_spn": "",
    "last_language": "",
    "last_fplmn": "",
    "last_csv_path": "",
    "last_batch_size": 20,
    "window_geometry": "",
    "simulator_mode": False,
}


class SettingsManager:
    """Read/write a JSON config file, with sensible defaults."""

    def __init__(self, path: Optional[str] = None):
        if path is not None:
            self._path = path
        else:
            config_home = os.environ.get(
                "XDG_CONFIG_HOME", os.path.expanduser("~/.config")
            )
            self._path = os.path.join(config_home, "simgui", "settings.json")
        self._data: dict = {}
        self.load()

    def get(self, key: str, default: Any = None) -> Any:
        """Return a setting value, falling back to *default* then built-in defaults."""
        if default is None:
            default = _DEFAULTS.get(key)
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a key — changes are in-memory until :meth:`save` is called."""
        self._data[key] = value

    def load(self) -> None:
        """Load settings from disk (silently uses defaults when file is absent)."""
        if not os.path.isfile(self._path):
            self._data = dict(_DEFAULTS)
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load settings from %s: %s", self._path, exc)
            self._data = dict(_DEFAULTS)

    def save(self) -> None:
        """Persist current settings to disk, creating directories if needed."""
        directory = os.path.dirname(self._path)
        try:
            os.makedirs(directory, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
        except OSError as exc:
            logger.error("Failed to save settings to %s: %s", self._path, exc)
