"""
Shared validation utilities for SIM card data.

ADM1 keys can be in two formats:
- ≤8 ASCII characters (e.g. "88888888") — the human-readable form,
  identical to what you type in ``verify_adm 88888888``.
- 16 hexadecimal characters (e.g. "3838383838383838") — the raw 8-byte
  key in hex notation, as stored in some delivery files.
"""

import re
from typing import List, Optional

# Patterns
_ADM1_DECIMAL_RE = re.compile(r'^\d{8}$')
_ADM1_HEX_RE = re.compile(r'^[0-9a-fA-F]{16}$')
_HEX_RE = re.compile(r'^[0-9a-fA-F]+$')


def validate_adm1(value: str) -> Optional[str]:
    """Validate an ADM1 key.

    Returns None if valid, or an error message string.
    Accepts ≤8 ASCII characters or 16 hex characters.
    """
    if not value:
        return None  # empty is OK (field may be optional)
    # 16 hex chars = raw key in hex notation
    if _ADM1_HEX_RE.match(value):
        return None
    # ≤8 printable ASCII chars = human-readable key
    if len(value) <= 8 and all(32 <= ord(c) <= 126 for c in value):
        return None
    return "ADM1 must be ≤8 ASCII characters or 16 hex characters"


def validate_imsi(value: str) -> Optional[str]:
    """Validate an IMSI. Returns None if valid, or an error message."""
    if not value:
        return None
    if not value.isdigit():
        return "IMSI must contain only digits"
    if not (6 <= len(value) <= 15):
        return "IMSI must be 6-15 digits"
    return None


def validate_iccid(value: str) -> Optional[str]:
    """Validate an ICCID. Returns None if valid, or an error message."""
    if not value:
        return None
    if not value.isdigit():
        return "ICCID must contain only digits"
    if not (10 <= len(value) <= 20):
        return "ICCID must be 10-20 digits"
    return None


def validate_hex_field(value: str, expected_len: int, field_name: str) -> Optional[str]:
    """Validate a hex field (Ki, OPc, etc.). Returns None if valid."""
    if not value:
        return None
    clean = value.replace(' ', '')
    if len(clean) != expected_len:
        return f"{field_name} must be {expected_len} hex characters"
    if not _HEX_RE.match(clean):
        return f"{field_name} must contain only hex characters"
    return None


def validate_country_code(value: str) -> Optional[str]:
    """Validate a 3-digit country code. Returns None if valid, or an error message."""
    if not value:
        return "Country code is required"
    if not value.isdigit() or len(value) != 3:
        return "Country code must be exactly 3 digits"
    return None


def validate_site_index(value: str) -> Optional[str]:
    """Validate a 3-digit site index. Returns None if valid, or an error message."""
    if not value:
        return "Site index is required"
    if not value.isdigit() or len(value) != 3:
        return "Site index must be exactly 3 digits"
    return None


def validate_customer_id(value: str) -> Optional[str]:
    """Validate a 2-digit customer ID (00-99). Returns None if valid, or an error message."""
    if not value:
        return "Customer ID is required"
    if not value.isdigit() or len(value) != 2:
        return "Customer ID must be exactly 2 digits (00-99)"
    return None


def validate_card_data(card: dict) -> List[str]:
    """Validate a single card data dict. Returns list of error strings."""
    errors: List[str] = []
    err = validate_imsi(card.get('IMSI', ''))
    if err:
        errors.append(err)
    err = validate_iccid(card.get('ICCID', ''))
    if err:
        errors.append(err)
    err = validate_hex_field(card.get('Ki', ''), 32, 'Ki')
    if err:
        errors.append(err)
    err = validate_hex_field(card.get('OPc', ''), 32, 'OPc')
    if err:
        errors.append(err)
    err = validate_adm1(card.get('ADM1', ''))
    if err:
        errors.append(err)
    return errors
