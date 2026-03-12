"""
ICCID and IMSI generation utilities.

Provides Luhn check-digit computation, IMSI/ICCID generation from
structured numbering components, and validation.
"""


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


def generate_imsi(mcc_mnc: str, customer: str, sim_type: str, seq: int) -> str:
    """Generate an IMSI from structured components.

    IMSI = MCC+MNC + Customer Code + SIM Type Code + Sequence (3 digits).

    Example:
        generate_imsi("99988", "0003", "0100", 1) -> "99988000301001"
    """
    return f"{mcc_mnc}{customer}{sim_type}{seq:03d}"


def generate_iccid(mcc_mnc: str, customer: str, sim_type: str, seq: int) -> str:
    """Generate an ICCID with Luhn check digit.

    ICCID = 89 + MCC+MNC + 00000 + Customer + Type + Seq(3) + LuhnCheck.

    Example:
        generate_iccid("99988", "0003", "0100", 1)
        -> "89" + "99988" + "00000" + "0003" + "0100" + "001" + check
    """
    base = f"89{mcc_mnc}00000{customer}{sim_type}{seq:03d}"
    check = compute_luhn_check(base)
    return base + check
