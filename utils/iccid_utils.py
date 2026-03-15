"""
ICCID and IMSI generation utilities.

Provides Luhn check-digit computation, IMSI/ICCID generation per the
Teleaura SIM PLMN Numbering Standard v2.0, and validation.
"""

# -- Teleaura Numbering Standard v2.0 constants ------------------------------

# Site Register — maps SSSS to DC Naming Standard site code
# country_code_e164 is the E.164 country dialling code (NOT MCC).
SITE_REGISTER = {
    "0001": {"code": "uk1", "country": "United Kingdom", "country_code_e164": "44", "description": "Primary UK data centre / lab", "status": "Active"},
    "0002": {"code": "se1", "country": "Sweden", "country_code_e164": "46", "description": "Primary Sweden data centre", "status": "Active"},
    "0003": {"code": "se2", "country": "Sweden", "country_code_e164": "46", "description": "Sweden DR site", "status": "Active"},
    "0004": {"code": "au1", "country": "Australia", "country_code_e164": "61", "description": "Primary Australia site", "status": "Reserved"},
}

# Issuer IDs per PLMN (maps MCC+MNC to 3-digit issuer ID for ICCID)
ISSUER_IDS = {
    "99988": "988",  # Teleaura Production Networks
    "99989": "989",  # Teleaura Lab / Test Networks
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


def generate_iccid(country_code_e164: str, issuer_id: str,
                   site_id: str, sim_type: str, seq: int) -> str:
    """Generate an ICCID per Teleaura SIM PLMN Numbering Standard v2.1.

    Format (20 digits):
        89(2) + CC(2) + III(3) + 00(2, padding) + SSSS(4) + T(1) + NNNNN(5) + Luhn(1)
        = 19 base + 1 check = 20 digits total

    The country code comes from the site's physical location (44=UK,
    46=SE), NOT from the MCC.  The issuer ID comes from the PLMN
    config (988=production, 989=lab).  The 2-digit padding '00'
    ensures the ICCID reaches 20 digits per ITU-T E.118.

    Args:
        country_code_e164: 2-digit E.164 country code (e.g. '44', '46').
        issuer_id: 3-digit issuer ID (e.g. '988', '989').
        site_id: 4-digit site ID from register (e.g. '0001').
        sim_type: 1-digit SIM type (e.g. '0' for USIM).
        seq: Sequence number (0-99999).

    Returns:
        20-digit ICCID string with Luhn check digit.

    Example:
        generate_iccid('44', '988', '0001', '0', 1)
        -> '89449880000010000018'  (89+44+988+00+0001+0+00001+Luhn)
    """
    cc = country_code_e164.zfill(2)[:2]  # ensure 2 digits
    iii = issuer_id.zfill(3)[:3]         # ensure 3 digits
    ssss = site_id.zfill(4)[:4]          # ensure 4 digits
    base = f"89{cc}{iii}00{ssss}{sim_type}{seq:05d}"
    # base = 2+2+3+2+4+1+5 = 19 digits
    check = compute_luhn_check(base)
    return base + check


def generate_iccid_legacy(mcc_mnc: str, site_id: str,
                          sim_type: str, seq: int) -> str:
    """Legacy ICCID generation (v2.0, deprecated).

    ICCID = 89 + MCC_MNC(5) + 00 + MSIN(10) + Luhn = 20 digits.
    Kept for backward compatibility.
    """
    msin = f"{site_id}{sim_type}{seq:05d}"
    base = f"89{mcc_mnc}00{msin}"
    check = compute_luhn_check(base)
    return base + check
