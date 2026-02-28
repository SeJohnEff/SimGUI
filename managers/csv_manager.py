#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV Manager - Load, edit, and save SIM card configuration CSV files.

Self-contained: works with plain CSV data, no dependency on the CLI tool.
"""

import csv
import os
from typing import Dict, List, Optional, Tuple


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
            print(f"Error loading CSV: {e}")
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
            print(f"Error saving CSV: {e}")
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
                # Merge any new columns
                for k in card_data:
                    if k not in self.columns:
                        self.columns.append(k)
                return True
            return False
        except Exception as e:
            print(f"Error loading card parameters: {e}")
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

    def validate_all(self) -> List[str]:
        """Return a list of human-readable validation errors."""
        errors: List[str] = []
        for i, card in enumerate(self.cards):
            row = i + 1
            imsi = card.get('IMSI', '')
            if imsi and (not imsi.isdigit() or not (6 <= len(imsi) <= 15)):
                errors.append(f"Row {row}: IMSI must be 6-15 digits")
            iccid = card.get('ICCID', '')
            if iccid and (not iccid.isdigit() or not (10 <= len(iccid) <= 20)):
                errors.append(f"Row {row}: ICCID must be 10-20 digits")
            ki = card.get('Ki', '')
            if ki:
                ki_clean = ki.replace(' ', '')
                if len(ki_clean) != 32 or not all(
                    c in '0123456789abcdefABCDEF' for c in ki_clean
                ):
                    errors.append(f"Row {row}: Ki must be 32 hex chars")
            opc = card.get('OPc', '')
            if opc:
                opc_clean = opc.replace(' ', '')
                if len(opc_clean) != 32 or not all(
                    c in '0123456789abcdefABCDEF' for c in opc_clean
                ):
                    errors.append(f"Row {row}: OPc must be 32 hex chars")
            adm1 = card.get('ADM1', '')
            if adm1 and len(adm1) != 8:
                errors.append(f"Row {row}: ADM1 must be 8 chars")
        return errors

    def validate_card(self, index: int) -> List[str]:
        """Validate a single card row."""
        if 0 <= index < len(self.cards):
            mgr = CSVManager()
            mgr.cards = [self.cards[index]]
            mgr.columns = self.columns
            return mgr.validate_all()
        return [f"Invalid index: {index}"]
