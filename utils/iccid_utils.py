"""
ICCID and IMSI generation utilities.

Provides Luhn check-digit computation, IMSI/ICCID generation per the
Teleaura SIM PLMN Numbering Standard v1.0, and validation.
"""

# -- Teleaura Numbering Standard constants ----------------------------------

COUNTRY_CODES = {
    "044": "UK",
    "046": "Sweden",
    "001": "US",
    "061": "Australia",
    "049": "Germany",
}

SITE_CODES = {
    "044001": "uk1",
    "044002": "uk2",
    "046001": "se1",
    "046002": "se2",
    "061001": "au1",
    "001001": "us1",
}

FPLMN_BY_COUNTRY = {
    "044": "23415;23410;23420;23430",
    "046": "24007;24024;24001;24008;24002",
}

CUSTOMER_RANGES = {
    "00": "Internal",
    "01-79": "Enterprise",
    "80-89": "IoT",
    "90-98": "Partners",
    "99": "Demo",
}


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


def generate_imsi(mcc_mnc: str, country_code: str, site_index: str,
                  customer_id: str, seq: int) -> str:
    """Generate an IMSI per Teleaura SIM PLMN Numbering Standard.

    IMSI = MCC+MNC(5) + Country(3) + Site(3) + Customer(2) + Seq(2) = 15 digits.

    Example:
        generate_imsi("99988", "044", "001", "03", 1) -> "999880440010301"
    """
    return f"{mcc_mnc}{country_code}{site_index}{customer_id}{seq:02d}"


def generate_iccid(mcc_mnc: str, country_code: str, site_index: str,
                   customer_id: str, seq: int) -> str:
    """Generate an ICCID per Teleaura SIM PLMN Numbering Standard.

    ICCID = 89 + MCC_MNC(5) + 0000 + MSIN(10) + Luhn = 20 digits.

    Example:
        generate_iccid("99988", "044", "001", "03", 1)
        -> "89" + "99988" + "0000" + "0440010301" + check = 20 digits
    """
    msin = f"{country_code}{site_index}{customer_id}{seq:02d}"
    base = f"89{mcc_mnc}0000{msin}"
    check = compute_luhn_check(base)
    return base + check
