"""
Standards Manager — centralised canonical values from a network share.

Reads ``standards.json`` from the root of each mounted network share to
provide canonical lists of SPN, LI, and other enumerable SIM fields.
This prevents inconsistencies such as "Boliden" / "BOLIDEN" / "böliden"
entering the SIM data.

File format (``standards.json``)::

    {
        "version": 1,
        "spn": ["BOLIDEN", "FISKARHEDEN", "TELEAURA"],
        "li": ["EN", "SV", "FI"]
    }

The manager merges values from all mounted shares (de-duplicated,
preserving case from the file).  If no share is mounted or the file is
absent the lists are empty and the UI falls back to free-text entry.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

STANDARDS_FILENAME = "standards.json"
SUPPORTED_VERSION = 1


class StandardsManager:
    """Load and cache canonical field values from network shares."""

    def __init__(self) -> None:
        self._spn_values: list[str] = []
        self._li_values: list[str] = []
        self._loaded_paths: list[str] = []  # paths successfully loaded

    # -- Public properties ------------------------------------------------

    @property
    def spn_values(self) -> list[str]:
        """Canonical SPN values (case-exact as in the file)."""
        return list(self._spn_values)

    @property
    def li_values(self) -> list[str]:
        """Canonical LI values (case-exact as in the file)."""
        return list(self._li_values)

    @property
    def has_standards(self) -> bool:
        """True if at least one standards file has been loaded."""
        return bool(self._loaded_paths)

    @property
    def loaded_paths(self) -> list[str]:
        """Paths of all successfully loaded standards files."""
        return list(self._loaded_paths)

    # -- Loading ----------------------------------------------------------

    def load_from_directory(self, directory: str) -> bool:
        """Try to load ``standards.json`` from *directory*.

        Returns True if a valid standards file was found and loaded.
        Values are **merged** with any previously loaded standards
        (duplicates removed, preserving original case and order).
        """
        path = os.path.join(directory, STANDARDS_FILENAME)
        if not os.path.isfile(path):
            logger.debug("No standards file at %s", path)
            return False

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Failed to read standards file %s: %s", path, exc)
            return False

        if not isinstance(data, dict):
            logger.warning("Standards file %s is not a JSON object", path)
            return False

        version = data.get("version", 1)
        if version > SUPPORTED_VERSION:
            logger.warning(
                "Standards file %s has version %s (supported: %s) — "
                "loading anyway, unknown keys will be ignored",
                path, version, SUPPORTED_VERSION,
            )

        # Merge SPN values (de-duplicate, preserve case from file)
        new_spn = _parse_string_list(data.get("spn"))
        self._spn_values = _merge_unique(self._spn_values, new_spn)

        # Merge LI values
        new_li = _parse_string_list(data.get("li"))
        self._li_values = _merge_unique(self._li_values, new_li)

        self._loaded_paths.append(path)
        logger.info(
            "Loaded standards from %s: %d SPN, %d LI values",
            path, len(new_spn), len(new_li),
        )
        return True

    def clear(self) -> None:
        """Remove all loaded standards (e.g. when shares are unmounted)."""
        self._spn_values.clear()
        self._li_values.clear()
        self._loaded_paths.clear()

    def reload_from_directories(self, directories: list[str]) -> int:
        """Clear and re-load from a list of mount-point directories.

        Returns the number of standards files successfully loaded.
        """
        self.clear()
        count = 0
        for d in directories:
            if self.load_from_directory(d):
                count += 1
        return count

    # -- Validation -------------------------------------------------------

    def is_valid_spn(self, value: str) -> bool:
        """Check if *value* is in the canonical SPN list (case-exact)."""
        return value in self._spn_values

    def is_valid_li(self, value: str) -> bool:
        """Check if *value* is in the canonical LI list (case-exact)."""
        return value in self._li_values

    def suggest_spn(self, value: str) -> Optional[str]:
        """Find the canonical SPN matching *value* case-insensitively.

        Returns the canonical form if found, else None.
        Useful for auto-correcting "boliden" → "BOLIDEN".
        """
        lower = value.lower()
        for v in self._spn_values:
            if v.lower() == lower:
                return v
        return None

    def suggest_li(self, value: str) -> Optional[str]:
        """Find the canonical LI matching *value* case-insensitively."""
        lower = value.lower()
        for v in self._li_values:
            if v.lower() == lower:
                return v
        return None

    # -- Serialisation (for creating a template file) ---------------------

    @staticmethod
    def create_template(path: str, *,
                        spn: Optional[list[str]] = None,
                        li: Optional[list[str]] = None) -> None:
        """Write a template ``standards.json`` at *path*.

        Useful for bootstrapping a new share.
        """
        data = {
            "version": SUPPORTED_VERSION,
            "spn": spn or ["EXAMPLE_PROVIDER"],
            "li": li or ["EN"],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")


# -- Module-level helpers ------------------------------------------------

def _parse_string_list(raw) -> list[str]:
    """Safely extract a list[str] from a JSON value."""
    if not isinstance(raw, list):
        return []
    return [str(v).strip() for v in raw if isinstance(v, str) and v.strip()]


def _merge_unique(existing: list[str], new: list[str]) -> list[str]:
    """Merge *new* into *existing*, de-duplicating (case-exact)."""
    seen: set[str] = set(existing)
    merged = list(existing)
    for v in new:
        if v not in seen:
            seen.add(v)
            merged.append(v)
    return merged
