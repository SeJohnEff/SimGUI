"""
ICCID and IMSI generation utilities.

Provides Luhn check-digit computation, IMSI/ICCID generation per the
Teleaura SIM PLMN Numbering Standard v2.0, and validation.
"""

# -- Teleaura Numbering Standard v2.0 constants ------------------------------

# Site Register — maps SSSS to DC Naming Standard site code
SITE_REGISTER = {
    "0001": {"code": "uk1", "country": "United Kingdom", "description": "Primary UK data centre / lab", "status": "Active"},
    "0002": {"code": "se1", "country": "Sweden", "description": "Primary Sweden data centre", "status": "Active"},
    "0003": {"code": "se2", "country": "Sweden", "description": "Sweden DR site", "status": "Active"},
    "0004": {"code": "au1", "country": "Australia", "description": "Primary Australia site", "status": "Reserved"},
}

# Reverse lookup: site code -> SSSS
SITE_CODE_TO_ID = {v["code"]: k for k, v in SITE_REGISTER.items()}

# SIM Types (T digit)
SIM_TYPES = {
    "0": "USIM",
    "1": "USIM+SUCI",
    "2": "eSIM",
    "9": "Test/Dev",
}

# FPLMN by country (determined by site's country, NOT encoded in IMSI)
FPLMN_BY_COUNTRY = {
    "United Kingdom": "23415;23410;23420;23430",
    "Sweden": "24007;24024;24001;24008;24002",
}


def get_fplmn_for_site(site_id: str) -> str:
    """Return the FPLMN string for a site based on its country."""
    site = SITE_REGISTER.get(site_id)
    if site:
        return FPLMN_BY_COUNTRY.get(site["country"], "")
    return ""


def compute_luhn_check(digits: str) -> str:
    """Compute Luhn check digit for an ICCID (without the check digit).

    Args:
        digits: The ICCID digits (typically 18-19 chars) *without* the
                trailing check digit.

    Returns:
        Single-character string: the Luhn check digit ('0'-'9').
    """
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - (total % 10)) % 10)


def validate_luhn(iccid: str) -> bool:
    """Validate that the last digit of *iccid* is a correct Luhn check digit."""
    if len(iccid) < 2 or not iccid.isdigit():
        return False
    return compute_luhn_check(iccid[:-1]) == iccid[-1]


def generate_imsi(mcc_mnc: str, site_id: str, sim_type: str, seq: int) -> str:
    """Generate an IMSI per Teleaura SIM PLMN Numbering Standard v2.0.

    IMSI = MCC+MNC(5) + SSSS(4) + T(1) + NNNNN(5) = 15 digits.

    Args:
        mcc_mnc: MCC+MNC string (e.g. "99988").
        site_id: 4-digit site ID from register (e.g. "0001").
        sim_type: 1-digit SIM type (e.g. "0" for USIM).
        seq: Sequence number (0-99999).

    Example:
        generate_imsi("99988", "0001", "0", 1) -> "999880001000001"
    """
    return f"{mcc_mnc}{site_id}{sim_type}{seq:05d}"


def generate_iccid(mcc_mnc: str, site_id: str, sim_type: str, seq: int) -> str:
    """Generate an ICCID per Teleaura SIM PLMN Numbering Standard v2.0.

    ICCID = 89 + MCC_MNC(5) + 00 + MSIN(10) + Luhn = 20 digits.
    Note: ICCID is normally factory-assigned. This is for preview only.
    """
    msin = f"{site_id}{sim_type}{seq:05d}"
    base = f"89{mcc_mnc}00{msin}"
    check = compute_luhn_check(base)
    return base + check
