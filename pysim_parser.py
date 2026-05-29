"""Standalone pySim-read output parser.

No dependencies on managers, widgets, PyQt, pySim, smartcard, or card profiles.
Returns a plain dict so callers can map fields to their own types.
"""

# Keys populated in the returned dict:
#   IMSI, ICCID, ACC, SPN, FPLMN  — str values from the output
#   card_type_str                  — lowercase auto-detected card type, e.g.
#                                    "sysmoisim-sja5", "gialersim", or "" if absent


def parse_pysim_output(output: str) -> dict:
    """Parse pySim-read stdout and return a plain dict of extracted fields.

    Handles multi-line FPLMN blocks, traceback noise, and case-insensitive keys.
    Returns an empty dict (with card_type_str="") for empty input.
    """
    result: dict = {"card_type_str": ""}
    fplmn_values: list = []
    in_fplmn_block = False

    for line in output.splitlines():
        if in_fplmn_block and line.startswith('\t'):
            if '# MCC:' in line and 'MNC:' in line:
                try:
                    mcc = line.split('MCC:')[1].split()[0].strip()
                    mnc = line.split('MNC:')[1].split()[0].strip()
                    fplmn_values.append(f"{mcc}{mnc.zfill(2)}")
                except (IndexError, ValueError):
                    pass
            continue
        else:
            in_fplmn_block = False

        if ':' not in line:
            continue

        stripped = line.strip()
        if stripped.startswith(('File "', 'Traceback', 'raise ')):
            continue

        key, _, val = line.partition(':')
        key = key.strip().upper()
        val = val.strip()

        if not val:
            if 'FPLMN' in key or 'FORBIDDEN' in key:
                in_fplmn_block = True
            continue

        if 'IMSI' in key:
            result['IMSI'] = val
        elif 'ICCID' in key:
            result['ICCID'] = val
        elif key == 'ACC' or 'ACCESS CONTROL' in key:
            result['ACC'] = val
        elif key == 'SPN' or 'SERVICE PROVIDER' in key:
            result['SPN'] = val
        elif 'FPLMN' in key or 'FORBIDDEN' in key:
            in_fplmn_block = True
        elif 'AUTODETECTED CARD TYPE' in key:
            result['card_type_str'] = val.lower()

    if fplmn_values:
        result['FPLMN'] = ';'.join(fplmn_values)

    return result
