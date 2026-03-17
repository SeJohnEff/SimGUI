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

# Column name normalization: lowercase key -> internal name
_COLUMN_NORMALIZE = {
    'adm': 'ADM1',
    'ki': 'Ki',
    'opc': 'OPc',
}

# File dialog filter for SIM data files
SIM_DATA_FILETYPES = [
    ("SIM Data Files", "*.csv *.eml *.txt"),
    ("CSV Files", "*.csv *.txt"),
    ("Email Files", "*.eml"),
    ("All files", "*.*"),
]


def _normalize_column(name: str) -> str:
    """Normalize a column name to internal standard."""
    key = name.strip().lower()
    if key in _COLUMN_NORMALIZE:
        return _COLUMN_NORMALIZE[key]
    return name.strip().upper()


class CSVManager:
    """Manage CSV data for batch SIM card programming"""

    def __init__(self):
        self.cards: List[Dict[str, str]] = []
        self.columns: List[str] = list(STANDARD_COLUMNS)
        self.filepath: Optional[str] = None

    # ---- I/O -----------------------------------------------------------

    def load_file(self, filepath: str) -> bool:
        """Load card data from CSV, TXT, or EML file.

        Auto-detects format by extension. For ``.eml`` files, delegates
        to the EML parser and normalises field names to internal standard.

        Returns True on success, False on failure.
        Raises ValueError for EML parse errors (caller should show to user).
        """
        if filepath.lower().endswith(".eml"):
            return self._load_eml(filepath)
        return self.load_csv(filepath)

    def _load_eml(self, filepath: str) -> bool:
        """Load card data from a sysmocom .eml file."""
        from utils.eml_parser import parse_eml_file
        # Let ValueError propagate — caller shows it to the user
        cards, meta = parse_eml_file(filepath)
        if not cards:
            return False
        # Normalise field names from EML to internal standard
        normalised_cards = []
        all_cols_ordered: list[str] = []
        for card in cards:
            new_card = {}
            for k, v in card.items():
                norm_key = _normalize_column(k)
                new_card[norm_key] = v
                if norm_key not in all_cols_ordered:
                    all_cols_ordered.append(norm_key)
            normalised_cards.append(new_card)
        self.columns = all_cols_ordered
        self.cards = normalised_cards
        self.filepath = filepath
        self._eml_metadata = meta
        return True

    def load_csv(self, filepath: str) -> bool:
        """Load card configurations from a CSV or whitespace-delimited file.

        Auto-detects the format: tries comma-separated first, falls back
        to whitespace-delimited if the CSV parse yields only one column.
        Column names are normalized to internal standard (ADM→ADM1, KI→Ki, OPC→OPc).
        """
        try:
            with open(filepath, 'r', newline='', encoding='utf-8-sig') as f:
                content = f.read()
            if not content.strip():
                return False

            # Try comma-separated first
            lines = content.splitlines()
            header_fields = lines[0].split(',')
            if len(header_fields) > 1:
                # Comma-separated CSV
                import io
                reader = csv.DictReader(io.StringIO(content))
                if reader.fieldnames is None:
                    return False
                raw_columns = list(reader.fieldnames)
                raw_cards = [dict(row) for row in reader]
            else:
                # Fall back to whitespace-delimited
                raw_columns, raw_cards = self._parse_whitespace(lines)
                if not raw_columns:
                    return False

            # Normalize column names
            col_map = {old: _normalize_column(old) for old in raw_columns}
            self.columns = [col_map[c] for c in raw_columns]
            self.cards = [
                {col_map.get(k, k): v for k, v in card.items()}
                for card in raw_cards
            ]
            self.filepath = filepath
            return True
        except Exception as e:
            logger.error("Error loading CSV: %s", e)
            return False

    @staticmethod
    def _parse_whitespace(lines: List[str]) -> Tuple[List[str], List[Dict[str, str]]]:
        """Parse whitespace-delimited SIM data lines into columns and card dicts.

        Handles files with empty columns (e.g. empty MSISDN) where
        consecutive spaces represent a blank field.  First tries
        ``str.split()`` (collapses all whitespace).  When the field
        count is too low, retries with ``str.split(' ')`` which
        preserves empty strings between consecutive spaces.
        """
        non_blank = [ln for ln in lines if ln.strip()]
        if not non_blank:
            return [], []
        headers = non_blank[0].split()
        n_headers = len(headers)
        cards: List[Dict[str, str]] = []
        for line in non_blank[1:]:
            fields = line.split()
            if len(fields) == n_headers:
                cards.append(dict(zip(headers, fields)))
            elif len(fields) < n_headers:
                # Retry: split on single space to preserve empty fields
                fields_single = line.split(' ')
                # Strip leading/trailing empties (from leading/trailing spaces)
                while fields_single and fields_single[0] == '':
                    fields_single.pop(0)
                while fields_single and fields_single[-1] == '':
                    fields_single.pop()
                if len(fields_single) == n_headers:
                    cards.append(dict(zip(headers, fields_single)))
        return headers, cards

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
