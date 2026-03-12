#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV Manager - Load, edit, and save SIM card configuration CSV files.

Self-contained: works with plain CSV data, no dependency on the CLI tool.
"""

import csv
import logging
import os
from typing import Dict, List, Optional, Tuple

from utils.validation import validate_card_data

logger = logging.getLogger(__name__)

# Standard CSV columns for SIM card programming
STANDARD_COLUMNS = [
    'ICCID', 'IMSI', 'Ki', 'OPc', 'ADM1',
    'MNC_LENGTH', 'ALGO_2G', 'ALGO_3G', 'ALGO_4G5G',
    'USE_OPC', 'HPLMN',
]


class CSVManager:
    """Manage CSV data for batch SIM card programming"""

    def __init__(self):
        self.cards: List[Dict[str, str]] = []
        self.columns: List[str] = list(STANDARD_COLUMNS)
        self.filepath: Optional[str] = None

    # ---- I/O -----------------------------------------------------------

    def load_csv(self, filepath: str) -> bool:
        """Load card configurations from a CSV file."""
        try:
            with open(filepath, 'r', newline='', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    return False
                self.columns = list(reader.fieldnames)
                self.cards = [dict(row) for row in reader]
            self.filepath = filepath
            return True
        except Exception as e:
            logger.error("Error loading CSV: %s", e)
            return False

    def save_csv(self, filepath: str) -> bool:
        """Save card configurations to a CSV file."""
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.columns,
                                        extrasaction='ignore')
                writer.writeheader()
                writer.writerows(self.cards)
            self.filepath = filepath
            return True
        except Exception as e:
            logger.error("Error saving CSV: %s", e)
            return False

    def load_card_parameters_file(self, filepath: str) -> bool:
        """Load a card-parameters.txt file (key=value format)."""
        try:
            card_data: Dict[str, str] = {}
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, _, value = line.partition('=')
                        card_data[key.strip()] = value.strip()
            if card_data:
                self.cards.append(card_data)
                for k in card_data:
                    if k not in self.columns:
                        self.columns.append(k)
                return True
            return False
        except Exception as e:
            logger.error("Error loading card parameters: %s", e)
            return False

    # ---- Card access ---------------------------------------------------

    def get_card_count(self) -> int:
        return len(self.cards)

    def get_card(self, index: int) -> Optional[Dict[str, str]]:
        if 0 <= index < len(self.cards):
            return self.cards[index]
        return None

    def add_card(self, card_data: Optional[Dict[str, str]] = None):
        """Add a new card row (empty or pre-filled)."""
        if card_data is None:
            card_data = {col: '' for col in self.columns}
        self.cards.append(card_data)

    def remove_card(self, index: int) -> bool:
        if 0 <= index < len(self.cards):
            self.cards.pop(index)
            return True
        return False

    def update_card(self, index: int, key: str, value: str) -> bool:
        if 0 <= index < len(self.cards):
            self.cards[index][key] = value
            return True
        return False

    # ---- Validation ----------------------------------------------------

    @staticmethod
    def _validate_card_data(card: Dict[str, str], row_label: str) -> List[str]:
        """Validate a single card's data using shared validation.

        Args:
            card: Card data dict.
            row_label: Label for error messages (e.g. "Row 3").

        Returns:
            List of error strings.
        """
        raw_errors = validate_card_data(card)
        return [f"{row_label}: {err}" for err in raw_errors]

    def validate_all(self) -> List[str]:
        """Return a list of human-readable validation errors."""
        errors: List[str] = []
        for i, card in enumerate(self.cards):
            errors.extend(self._validate_card_data(card, f"Row {i + 1}"))
        return errors

    def validate_card(self, index: int) -> List[str]:
        """Validate a single card row."""
        if 0 <= index < len(self.cards):
            return self._validate_card_data(self.cards[index], f"Row {index + 1}")
        return [f"Invalid index: {index}"]
