#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backup Manager - Create and restore JSON backups of card data.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class BackupManager:
    """Create and restore card-data backups."""

    DEFAULT_DIR = os.path.join(os.path.expanduser('~'), 'SimGUI_backups')

    def create_backup(self, card_data: Dict, filepath: str) -> Optional[str]:
        """Save card_data dict to a JSON file at the given filepath.

        Args:
            card_data: Card data dictionary to back up.
            filepath: Destination file path (caller provides via file dialog).

        Returns:
            The filepath on success, or None on failure.
        """
        try:
            os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(card_data, f, indent=2, default=str)
            return filepath
        except Exception as e:
            logger.error("Backup error: %s", e)
            return None

    @staticmethod
    def suggest_filename(card_data: Dict) -> str:
        """Generate a suggested backup filename from card data."""
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        imsi = card_data.get('imsi', 'unknown')
        return f"backup_{imsi}_{ts}.json"

    @staticmethod
    def restore_backup(filepath: str) -> Optional[Dict]:
        """Load a backup JSON file."""
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error("Restore error: %s", e)
            return None
