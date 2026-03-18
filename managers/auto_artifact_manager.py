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

    def save_batch_summary(self, records: list[dict[str, str]],
                           batch_results: list,
                           ) -> list[str]:
        """Write a batch summary CSV to all connected shares.

        Parameters
        ----------
        records :
            Card data dicts for successfully programmed cards (from
            ``get_programmed_records()``).
        batch_results :
            All ``CardResult`` objects from the batch (success and failure).

        Returns
        -------
        list[str]
            Paths where summaries were successfully saved.
        """
        if not self._ns:
            return []

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"batch_summary_{timestamp}.csv"

        # Build rows: one per batch result (both success and failure)
        fields = ["#", "ICCID", "IMSI", "Status", "Message", "Timestamp"]
        rows = []
        # Index successful records by their ICCID for easy lookup
        ok_by_iccid = {r.get("ICCID", ""): r for r in records}
        for r in batch_results:
            card = ok_by_iccid.get(r.iccid, {})
            rows.append({
                "#": r.index + 1,
                "ICCID": r.iccid,
                "IMSI": card.get("IMSI", ""),
                "Status": "OK" if r.success else "FAIL",
                "Message": r.message,
                "Timestamp": datetime.now().isoformat(),
            })

        saved_paths = []
        for label, mount_path in self._ns.get_active_mount_paths():
            artifact_dir = os.path.join(mount_path, AUTO_ARTIFACT_DIR)
            try:
                os.makedirs(artifact_dir, exist_ok=True)
                path = os.path.join(artifact_dir, filename)
                with open(path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=fields,
                                            extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
                saved_paths.append(path)
                logger.info("Batch summary saved: %s (%d rows)", path, len(rows))
            except OSError as exc:
                logger.warning("Failed to save batch summary to %s: %s",
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

    def get_previous_programming_info(self, iccid: str) -> Optional[dict[str, str]]:
        """Load the most recent artifact data for *iccid*.

        Returns a dict with at least ``IMSI``, ``programmed_at``, and the
        artifact file path (key ``_artifact_path``).  Returns ``None`` if
        no artifact exists.
        """
        paths = self.find_existing_artifacts(iccid)
        if not paths:
            return None

        # Pick the most recent file (lexicographic sort works because the
        # filename embeds a YYYYMMDD_HHMMSS timestamp).
        paths.sort(reverse=True)
        latest = paths[0]

        try:
            with open(latest, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    row["_artifact_path"] = latest
                    return dict(row)
        except (OSError, csv.Error) as exc:
            logger.warning("Could not read artifact %s: %s", latest, exc)

        return None
