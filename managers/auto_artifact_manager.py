"""
Auto-Artifact Manager — Automatically save one CSV per programmed card.

After each successful ``program_card()`` while a network share is
connected, this manager writes a single-row CSV to the
``auto-artifact/`` directory on the share.

File naming: ``{ICCID}_{YYYYMMDD_HHMMSS}.csv``

The directory is created automatically on first write.  One file per
card gives a complete audit trail with no operator action required.
"""

import csv
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Default fields to include in auto-artifacts
DEFAULT_ARTIFACT_FIELDS = [
    "ICCID", "IMSI", "Ki", "OPc", "ADM1",
    "ACC", "SPN", "FPLMN",
    "PIN1", "PUK1", "PIN2", "PUK2",
]

AUTO_ARTIFACT_DIR = "auto-artifact"


class AutoArtifactManager:
    """Writes per-card artifact CSVs to network shares.

    Parameters
    ----------
    ns_manager :
        The ``NetworkStorageManager`` instance (for finding mount paths).
    """

    def __init__(self, ns_manager=None):
        self._ns = ns_manager

    def save_card_artifact(self, card_data: dict[str, str],
                           *, fields: Optional[list[str]] = None,
                           extra_meta: Optional[dict[str, str]] = None,
                           ) -> list[str]:
        """Write an artifact CSV for a single card to all connected shares.

        Parameters
        ----------
        card_data :
            Full card data dict (keys like ICCID, IMSI, Ki, ...).
        fields :
            Which fields to include.  Defaults to ``DEFAULT_ARTIFACT_FIELDS``.
        extra_meta :
            Extra key-value pairs to add (e.g. programmed_at, source_file).

        Returns
        -------
        list[str]
            Paths where artifacts were successfully saved.
        """
        if not self._ns:
            return []

        iccid = card_data.get("ICCID", "").strip()
        if not iccid:
            logger.warning("Cannot save artifact: no ICCID in card data")
            return []

        fields = fields or DEFAULT_ARTIFACT_FIELDS
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{iccid}_{timestamp}.csv"

        # Build the row
        row = {}
        for f in fields:
            # Try exact key, then uppercase, then lowercase
            row[f] = card_data.get(f, card_data.get(f.upper(),
                                   card_data.get(f.lower(), "")))
        # Add timestamp and extra metadata
        row["programmed_at"] = datetime.now().isoformat()
        if extra_meta:
            row.update(extra_meta)

        all_fields = list(row.keys())
        saved_paths = []

        # Write to every connected share
        for label, mount_path in self._ns.get_active_mount_paths():
            artifact_dir = os.path.join(mount_path, AUTO_ARTIFACT_DIR)
            try:
                os.makedirs(artifact_dir, exist_ok=True)
                path = os.path.join(artifact_dir, filename)
                with open(path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=all_fields,
                                            extrasaction="ignore")
                    writer.writeheader()
                    writer.writerow(row)
                saved_paths.append(path)
                logger.info("Auto-artifact saved: %s", path)
            except OSError as exc:
                logger.warning("Failed to save auto-artifact to %s: %s",
                             artifact_dir, exc)

        return saved_paths

    def find_existing_artifacts(self, iccid: str) -> list[str]:
        """Find existing auto-artifact files for a given ICCID.

        Returns a list of file paths across all connected shares.
        """
        if not self._ns:
            return []

        found = []
        prefix = f"{iccid}_"
        for _label, mount_path in self._ns.get_active_mount_paths():
            artifact_dir = os.path.join(mount_path, AUTO_ARTIFACT_DIR)
            if not os.path.isdir(artifact_dir):
                continue
            try:
                for fname in os.listdir(artifact_dir):
                    if fname.startswith(prefix) and fname.endswith(".csv"):
                        found.append(os.path.join(artifact_dir, fname))
            except OSError:
                continue
        return found

    def was_already_programmed(self, iccid: str) -> bool:
        """Check if an auto-artifact already exists for this ICCID."""
        return bool(self.find_existing_artifacts(iccid))
