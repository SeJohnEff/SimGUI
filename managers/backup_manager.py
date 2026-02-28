#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backup Manager - Create and restore JSON backups of card data.
"""

import json
import os
from datetime import datetime
from tkinter import filedialog
from typing import Dict, Optional


class BackupManager:
    """Create and restore card-data backups."""

    DEFAULT_DIR = os.path.join(os.path.expanduser('~'), 'SimGUI_backups')

    def create_backup(self, card_data: Dict, card_manager=None) -> Optional[str]:
        """Save card_data dict to a timestamped JSON file."""
        os.makedirs(self.DEFAULT_DIR, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        imsi = card_data.get('imsi', 'unknown')
        filename = f"backup_{imsi}_{ts}.json"
        filepath = filedialog.asksaveasfilename(
            title="Save Backup",
            initialdir=self.DEFAULT_DIR,
            initialfile=filename,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filepath:
            return None
        try:
            with open(filepath, 'w') as f:
                json.dump(card_data, f, indent=2, default=str)
            return filepath
        except Exception as e:
            print(f"Backup error: {e}")
            return None

    @staticmethod
    def restore_backup(filepath: str) -> Optional[Dict]:
        """Load a backup JSON file."""
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Restore error: {e}")
            return None
