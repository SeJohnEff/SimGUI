#!/usr/bin/env python3
"""Offline USIM AUTHENTICATE self-check for gialersim Ki/OPc verification.

Reference implementation for ``TODO(gialersim-selfcheck)`` (see
``docs/TODO.md`` and ``docs/GIALERSIM_PROGRAMMING.md``).

Ki and OPc on gialersim cards are ``READ=NEVER``, so a programming ``UPDATE``
returning ``9000`` proves nothing. The only way to positively confirm the keys
committed is to make the card authenticate: compute ``RAND`` + ``AUTN`` from the
expected Ki/OPc (Milenage) and send a 3G USIM ``AUTHENTICATE`` (INS ``88``,
P2 ``81``) in ADF_USIM.

    'DB ...'  success        -> MAC verified: keys correct
    'DC ...'  sync failure   -> MAC verified: keys correct (SQN out of range)
    9862/6300 auth error     -> keys wrong

A sync failure still proves the key, so the result is independent of SQN state.
Milenage is self-tested against 3GPP TS 35.208 Test Set 1 before every run; if
the self-test fails the script aborts and no conclusion is drawn.

This is READ-ONLY apart from advancing the card's SQN counter.

**No secrets are embedded in this file.** Supply the expected Ki/OPc at runtime,
either directly (``--ki``/``--opc``) or from an operator-managed CSV that is NOT
committed to this repository (``--csv``). The CSV must have ``IMSI``, ``Ki`` and
``OPc`` columns (``OLD_IMSI`` optional — Ki survives an IMSI rewrite, so a card
still carrying its factory IMSI is matched via that column too).

Usage::

    # Verify a single known key pair against the inserted card:
    python tools/auth_validate_harness.py [reader] --ki <32 hex> --opc <32 hex>

    # Look the card's IMSI up in a local (uncommitted) CSV of known keys:
    python tools/auth_validate_harness.py [reader] --csv /path/to/known_keys.csv

Requires ``pyscard`` and ``pycryptodome`` (``Cryptodome``/``Crypto``). Run with
the pySim venv, e.g. ``~/projects/SimGUI/.venv-pysim/bin/python``.
"""

import csv
import sys

try:
    from Cryptodome.Cipher import AES
except ImportError:
    from Crypto.Cipher import AES

from smartcard.CardConnection import CardConnection
from smartcard.System import readers
from smartcard.util import toHexString

RAND = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
AMF = bytes.fromhex("8000")

C = [bytes(15) + bytes([v]) for v in (0, 1, 2, 4, 8)]
R = (64, 0, 32, 64, 96)


def _rot(x, r):
    r //= 8
    return x[r:] + x[:r]


def _xor(a, b):
    return bytes(i ^ j for i, j in zip(a, b))


def _e(k, d):
    return AES.new(k, AES.MODE_ECB).encrypt(d)


def milenage(k, opc, rand, sqn, amf):
    temp = _e(k, _xor(rand, opc))
    in1 = sqn + amf + sqn + amf
    out1 = _xor(_e(k, _xor(_xor(temp, _rot(_xor(in1, opc), R[0])), C[0])), opc)
    out2 = _xor(_e(k, _xor(_rot(_xor(temp, opc), R[1]), C[1])), opc)
    return out1[:8], out2[8:16], out2[:6]


def selftest():
    """Milenage self-test against 3GPP TS 35.208 Test Set 1."""
    mac, res, ak = milenage(
        bytes.fromhex("465b5ce8b199b49faa5f0a2ee238a6bc"),
        bytes.fromhex("cd63cb71954a9f4e48a5994e37a02baf"),
        bytes.fromhex("23553cbe9637a89d218ae64dae47bf35"),
        bytes.fromhex("ff9bb4d0b607"), bytes.fromhex("b9b9"))
    if (mac.hex() != "4a9ffac354dfafb3" or res.hex() != "a54211d5e3ba50bf"
            or ak.hex() != "aa689c648370"):
        sys.exit("ABORT: Milenage self-test FAILED.")
    print("Milenage self-test OK\n")


def send(conn, apdu):
    apdu = list(apdu)
    data, sw1, sw2 = conn.transmit(apdu)
    if sw1 == 0x61:
        data, sw1, sw2 = conn.transmit([0x00, 0xC0, 0x00, 0x00, sw2])
    elif sw1 == 0x6C:
        data, sw1, sw2 = conn.transmit(apdu[:-1] + [sw2])
    return bytes(data), sw1, sw2


def swap(h):
    return "".join(h[i + 1] + h[i] for i in range(0, len(h), 2))


def read_imsi(conn):
    send(conn, [0x00, 0xA4, 0x00, 0x04, 0x02, 0x3F, 0x00])
    _, s1, s2 = send(conn, [0x00, 0xA4, 0x00, 0x04, 0x02, 0x7F, 0x20])
    if (s1, s2) != (0x90, 0x00):
        return None
    _, s1, s2 = send(conn, [0x00, 0xA4, 0x00, 0x04, 0x02, 0x6F, 0x07])
    if (s1, s2) != (0x90, 0x00):
        return None
    data, s1, s2 = send(conn, [0x00, 0xB0, 0x00, 0x00, 0x09])
    if (s1, s2) != (0x90, 0x00) or not data:
        return None
    ln = data[0]
    return swap(data[1:1 + ln].hex())[1:]


def find_aid(conn):
    send(conn, [0x00, 0xA4, 0x00, 0x04, 0x02, 0x3F, 0x00])
    _, s1, s2 = send(conn, [0x00, 0xA4, 0x00, 0x04, 0x02, 0x2F, 0x00])
    if (s1, s2) != (0x90, 0x00):
        return None
    for rec in range(1, 9):
        data, s1, s2 = send(conn, [0x00, 0xB2, rec, 0x04, 0x00])
        if (s1, s2) != (0x90, 0x00) or not data:
            continue
        i = 0
        while i + 1 < len(data):
            tag, ln = data[i], data[i + 1]
            if tag == 0x61:
                inner = data[i + 2:i + 2 + ln]
                j = 0
                while j + 1 < len(inner):
                    t2, l2 = inner[j], inner[j + 1]
                    if t2 == 0x4F:
                        return inner[j + 2:j + 2 + l2]
                    j += 2 + l2
            i += 2 + ln
    return None


def _load_csv_candidates(path):
    """Load (imsi_or_label, Ki, OPc) rows from an operator-supplied CSV.

    Expected columns (case-insensitive): IMSI, Ki, OPc, and optionally OLD_IMSI.
    Rows missing Ki/OPc are skipped. This file is provided at runtime and must
    NOT be committed — it carries live card secrets.
    """
    out = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {(c or "").strip().lower(): c for c in (reader.fieldnames or [])}
        need = ("imsi", "ki", "opc")
        missing = [c for c in need if c not in cols]
        if missing:
            sys.exit("CSV %s missing column(s): %s" % (path, ", ".join(missing)))
        for row in reader:
            ki = (row.get(cols["ki"]) or "").replace(" ", "").upper()
            opc = (row.get(cols["opc"]) or "").replace(" ", "").upper()
            imsi = (row.get(cols["imsi"]) or "").strip()
            old = (row.get(cols.get("old_imsi", "")) or "").strip() if "old_imsi" in cols else ""
            if len(ki) != 32 or len(opc) != 32:
                continue
            out.append((imsi, old, ki, opc))
    return out


def _parse_cli():
    """Parse argv. Returns (positionals, ki, opc, csv_path)."""
    argv = sys.argv[1:]
    pos, ki, opc, csv_path = [], None, None, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--ki" and i + 1 < len(argv):
            ki = argv[i + 1].replace(" ", "").upper(); i += 2
        elif a == "--opc" and i + 1 < len(argv):
            opc = argv[i + 1].replace(" ", "").upper(); i += 2
        elif a == "--csv" and i + 1 < len(argv):
            csv_path = argv[i + 1]; i += 2
        elif a in ("-h", "--help"):
            print(__doc__); sys.exit(0)
        else:
            pos.append(a); i += 1
    for name, v in (("--ki", ki), ("--opc", opc)):
        if v is not None and len(v) != 32:
            sys.exit("%s must be 32 hex chars (got %d)" % (name, len(v)))
    if (ki is None) != (opc is None):
        sys.exit("Supply both --ki and --opc, or neither.")
    return pos, ki, opc, csv_path


def main():
    selftest()
    pos, cli_ki, cli_opc, csv_path = _parse_cli()
    idx = int(pos[0]) if pos else 0

    rlist = readers()
    if not rlist:
        sys.exit("No PC/SC readers found.")
    print("Using: %s" % rlist[idx])
    conn = rlist[idx].createConnection()
    # Force T=0 first. Plain connect() may negotiate T=1, after which every
    # transmit fails with 0x80100016 on these cards.
    for proto, name in ((CardConnection.T0_protocol, "T=0"),
                        (CardConnection.T1_protocol, "T=1"),
                        (None, "default")):
        try:
            conn.connect(proto) if proto is not None else conn.connect()
            print("Connected with %s" % name)
            break
        except Exception as exc:
            print("  %s failed: %s" % (name, exc))
    else:
        sys.exit("Could not connect with any protocol.")
    print("ATR: %s" % toHexString(conn.getATR()))

    imsi = read_imsi(conn)
    print("Card IMSI: %s" % (imsi or "<unreadable>"))

    # Build the candidate list. --ki/--opc (if supplied) goes first, then any
    # rows loaded from the operator CSV. No keys are embedded in this file.
    cands = []          # list of (label, ki_hex, opc_hex)
    expect = None
    if cli_ki and cli_opc:
        cands.append(("--ki/--opc (supplied)", cli_ki, cli_opc))
        expect = "supplied"
        print("Testing the Ki/OPc supplied on the command line.")
    if csv_path:
        rows = _load_csv_candidates(csv_path)
        print("Loaded %d key row(s) from %s" % (len(rows), csv_path))
        for new_i, old_i, ki, opc in rows:
            cands.append((new_i or "<no-imsi>", ki, opc))
            if imsi and imsi in (new_i, old_i):
                expect = new_i or "<no-imsi>"
                print("  -> card IMSI matches a CSV row; it must MATCH")
    if not cands:
        sys.exit("No candidates. Supply --ki/--opc and/or --csv <known_keys.csv>.")
    print()

    aid = find_aid(conn) or bytes.fromhex("A0000000871002")
    print("USIM AID: %s" % aid.hex().upper())
    _, s1, s2 = send(conn, [0x00, 0xA4, 0x04, 0x04, len(aid)] + list(aid))
    if (s1, s2) != (0x90, 0x00):
        sys.exit("Could not select ADF_USIM (%02X%02X)." % (s1, s2))
    print()

    print("%-24s %-10s %s" % ("CANDIDATE", "SW", "VERDICT"))
    print("-" * 60)
    hit = None
    for n, (label, ki_hex, opc_hex) in enumerate(cands):
        k = bytes.fromhex(ki_hex)
        opc = bytes.fromhex(opc_hex)
        sqn = (0x20 * (n + 1)).to_bytes(6, "big")
        mac, exp_res, ak = milenage(k, opc, RAND, sqn, AMF)
        autn = _xor(sqn, ak) + AMF + mac
        apdu = ([0x00, 0x88, 0x00, 0x81, 0x22, 0x10] + list(RAND)
                + [0x10] + list(autn) + [0x00])
        data, s1, s2 = send(conn, apdu)
        sw = "%02X%02X" % (s1, s2)
        if data and data[0] == 0xDB:
            res = data[2:2 + data[1]]
            verdict = "MATCH" + ("" if res == exp_res else " (RES differs!)")
            hit = label
        elif data and data[0] == 0xDC:
            verdict = "MATCH (sync failure - MAC ok)"
            hit = label
        else:
            verdict = "no"
        mark = "  <- card's own IMSI" if label == imsi else ""
        print("%-24s %-10s %s%s" % (label, sw, verdict, mark))

    print("\n" + "=" * 60)
    if hit:
        print("VERIFIED - the card authenticated against key set '%s'." % hit)
        print("The Ki/OPc on the card match; programming committed correctly.")
    elif expect:
        print("FAILED - a card whose Ki/OPc we know did NOT verify.")
        print("The keys on the card do not match the expected values.")
    else:
        print("Inconclusive - none of the supplied candidates matched.")
        print("Re-run with the correct --ki/--opc or --csv for this card.")
    print("=" * 60)


if __name__ == "__main__":
    main()
