"""Native gialersim card personalisation — no pySim.

**Why this module exists.**  pySim's ``GialerSim`` class does not work on these
cards.  It writes Ki and OPc using UICC class (``CLA=00``, SELECT ``P2=04``),
gets ``9000`` on every APDU, and produces a SIM that fails authentication with
**MAC failure (9862)**.  ICCID/IMSI/ACC *do* write, so nothing in the logs
signals a problem — only the keys are silently unusable.

Two independent defects, both fatal, both fixed here:

1. **Wrong class byte.**  These cards only *commit* key writes in **GSM class**
   (``CLA=A0``, SELECT ``P2=00``).  In UICC class the ``UPDATE`` returns ``9000``
   and is discarded.
2. **Missing algorithm configuration.**  Ki alone is not enough: ``EF 2FE5`` and
   ``EF 2FE6`` bind an algorithm to the key set.  Without them ``AUTHENTICATE``
   fails no matter how correct the Ki is.

The APDU recipe below was recovered by USB-capturing a working GRSIMWrite
session (see ``docs/GIALERSIM_PROGRAMMING.md``) and verified on hardware
(2026-08-13).  It is deliberately faithful to that capture: **do not reorder
the steps and do not re-select a DF between steps 2 and 6** — selecting a DF
drops the ADM security state on these cards, so every ADM-gated write after it
would silently fail.

**ADM key.**  The credential presented at ref ``0x0C`` is the fixed key
``84796153`` — this is a property of the card family, *not* the ADM1 from the
CSV.  (``88888888`` is the *contents* of key file ``0B00``, written verbatim in
step 2; it is not a credential to present.)

**Verification.**  Ki and OPc are ``READ=NEVER`` (EF_ARR record ``0x13``); a
``9000`` on the write proves nothing.  ICCID and IMSI are read back here as a
sanity check, but the only real confirmation that the keys committed is an
offline USIM ``AUTHENTICATE`` — tracked as ``TODO(gialersim-selfcheck)`` in
``docs/TODO.md``.  Do NOT treat ``9000`` on a Ki write as success.

This module has zero Qt imports and talks to the card via pyscard directly,
exactly as ``card_manager`` already does for the ADM1 retry counter.
"""

import logging
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Fixed personalisation ADM presented at key reference 0x0C.  NOT the CSV ADM1.
ADM_ASCII = "84796153"
ADM_CHV = 0x0C

# PIN / ADM key-definition files, verbatim from the GRSIMWrite USB capture.
# GRSIMWrite rewrites these before touching Ki/OPc; on a virgin card the key
# writes do not commit without them.  Do not "clean up" these payloads — they
# are copied byte-for-byte from a known-good session.
#   31323334          = "1234"      (PIN)
#   3838383838383838  = "88888888"  (ADM key stored at reference 0x0B)
_KEYFILES: List[Tuple[str, str]] = [
    ("0100", "000000" "31323334" "FFFFFFFF" "8383" "3838383838383838" "8A8A"),
    ("0200", "010000" "31323334" "FFFFFFFF" "8383" "3838383838383838" "8A8A"),
    ("0B00", "010000" "3838383838383838" "8A8A"),
]

# Algorithm / key-set configuration (EF 2FE5, EF 2FE6) — the piece pySim omits.
# 2FE6 is five 17-byte records; the leading byte varies (40/00/20/40/60, believed
# an algorithm selector) and the trailing byte steps 00,01,02,04,08 (believed a
# key-set index).  Verbatim from the capture; not minimised.
_ALGO_2FE5 = "081C2A0001"
_ALGO_2FE6_RECORDS: List[Tuple[int, str]] = [
    (1, "40" + "00" * 15 + "00"),
    (2, "00" + "00" * 15 + "01"),
    (3, "20" + "00" * 15 + "02"),
    (4, "40" + "00" * 15 + "04"),
    (5, "60" + "00" * 15 + "08"),
]

ProgressFn = Callable[[str], None]


class GialerSimError(Exception):
    """A gialersim personalisation step failed.

    Raised on any non-9000 status for a recipe step.  The card is left in a
    partially-written state; the caller must surface this as a write failure,
    never as success.
    """


# --------------------------------------------------------------------------- #
# Encoding helpers (pure — unit-testable without a card)
# --------------------------------------------------------------------------- #

def swap_nibbles(hexstr: str) -> str:
    """Swap adjacent nibbles of every byte (GSM BCD ordering).

    ``"1234"`` -> ``"2143"``.  Input length must be even.
    """
    if len(hexstr) % 2:
        raise ValueError("swap_nibbles needs an even-length hex string")
    return "".join(hexstr[i + 1] + hexstr[i] for i in range(0, len(hexstr), 2))


def encode_iccid(iccid: str) -> str:
    """Encode a 19-digit ICCID to the 10-byte EF.ICCID hex (swapped, f-padded)."""
    if not iccid.isdigit():
        raise ValueError("ICCID must be decimal digits")
    padded = iccid + "f" if len(iccid) % 2 else iccid
    return swap_nibbles(padded)


def encode_imsi(imsi: str) -> str:
    """Encode a 15-digit IMSI to the 9-byte EF.IMSI hex (length + parity + swap).

    Layout: ``LL`` (length byte) || nibble-swapped(parity-digit || IMSI), where
    the parity digit is ``9`` for an odd-length IMSI, ``1`` for even.
    """
    if not imsi.isdigit():
        raise ValueError("IMSI must be decimal digits")
    parity = "9" if len(imsi) % 2 else "1"
    body = swap_nibbles(parity + imsi)
    return "%02x" % (len(body) // 2) + body


# --------------------------------------------------------------------------- #
# GSM-class (CLA=A0) APDU primitives
# --------------------------------------------------------------------------- #
#
# These cards answer SELECT with ``9FXX`` (not ``61XX``); we follow with a GET
# RESPONSE ``A0 C0 00 00 XX``.  ``6CXX`` means "wrong Le, expected XX" — resend
# with the corrected length.  Any other non-9000 is fatal for a recipe step.

def _transmit(conn, apdu: List[int]) -> Tuple[bytes, int, int]:
    data, sw1, sw2 = conn.transmit(apdu)
    if sw1 in (0x9F, 0x61):
        data, sw1, sw2 = conn.transmit([0xA0, 0xC0, 0x00, 0x00, sw2])
    elif sw1 == 0x6C:
        data, sw1, sw2 = conn.transmit(apdu[:-1] + [sw2])
    return bytes(data), sw1, sw2


def _step(conn, apdu: List[int], label: str) -> bytes:
    """Transmit *apdu*; raise GialerSimError unless the card answers 9000."""
    data, sw1, sw2 = _transmit(conn, apdu)
    if (sw1, sw2) != (0x90, 0x00):
        raise GialerSimError(
            "%s failed: SW=%02X%02X" % (label, sw1, sw2)
        )
    return data


def _select(conn, fid: str, label: str) -> bytes:
    return _step(conn, [0xA0, 0xA4, 0x00, 0x00, 0x02]
                 + list(bytes.fromhex(fid)), "SELECT %s" % label)


def _update_binary(conn, hexdata: str, label: str) -> bytes:
    body = list(bytes.fromhex(hexdata))
    return _step(conn, [0xA0, 0xD6, 0x00, 0x00, len(body)] + body, label)


def _read_binary(conn, length: int) -> bytes:
    # Read-back sanity check only; non-fatal, so bypass _step.
    data, _sw1, _sw2 = _transmit(conn, [0xA0, 0xB0, 0x00, 0x00, length])
    return data


# --------------------------------------------------------------------------- #
# The recipe
# --------------------------------------------------------------------------- #

def program_connection(
    conn,
    *,
    iccid: str,
    imsi: str,
    ki: str,
    opc: str,
    acc: str = "0001",
    adm_ascii: str = ADM_ASCII,
    on_progress: Optional[ProgressFn] = None,
) -> Tuple[bool, bool]:
    """Personalise a gialersim card over an already-open connection *conn*.

    Executes steps 1-7 of the verified recipe in order, all in GSM class, with
    no DF reselect between steps 2 and 6.  Raises :class:`GialerSimError` on the
    first non-9000 status of any recipe step (the card is then left partially
    written — the caller must treat this as a write failure).

    Args:
        conn: a live pyscard ``CardConnection`` (already connected, T=0).
        iccid: 19-digit ICCID.
        imsi:  15-digit IMSI.
        ki:    32 hex chars (16 bytes).
        opc:   32 hex chars (16 bytes) — written as ``01`` || OPc.
        acc:   4 hex chars (2 bytes).  Defaults to ``0001``.
        adm_ascii: 8-char ADM presented at ref 0x0C.  Do not pass the CSV ADM1;
            the fixed family key ``84796153`` is correct and is the default.
        on_progress: optional callback invoked with a short label per step.

    Returns:
        ``(iccid_readback_ok, imsi_readback_ok)`` — read-back sanity flags for
        the two readable fields.  Ki/OPc are READ=NEVER and cannot be confirmed
        here; a ``9000`` write does NOT prove they committed.
    """
    ki = ki.strip().lower()
    opc = opc.strip().lower()
    if len(ki) != 32:
        raise ValueError("Ki must be 32 hex chars (16 bytes)")
    if len(opc) != 32:
        raise ValueError("OPc must be 32 hex chars (16 bytes)")
    if len(imsi) != 15:
        raise ValueError("IMSI must be 15 digits")
    if len(iccid) != 19:
        raise ValueError("ICCID must be 19 digits")
    acc = (acc or "0001").strip()
    if len(acc) != 4:
        raise ValueError("ACC must be 4 hex chars (2 bytes)")

    icc_enc = encode_iccid(iccid)
    imsi_enc = encode_imsi(imsi)

    def progress(msg: str) -> None:
        logger.info("gialersim: %s", msg)
        if on_progress is not None:
            on_progress(msg)

    # --- Step 1: VERIFY ADM (no SELECT MF first — MF is implicitly current) ---
    # The fixed family key at ref 0x0C.  verify_chv semantics: a wrong key here
    # would burn an attempt, but 84796153 is the correct, hardcoded value.
    progress("VERIFY ADM (ref 0x0C)")
    _step(conn, [0xA0, 0x20, 0x00, ADM_CHV, 0x08]
          + [ord(c) for c in adm_ascii], "VERIFY ADM")

    # --- Steps 2-6 MUST run with MF current; never re-select a DF here. ---
    # Selecting any DF drops the ADM security state on these cards, after which
    # every ADM-gated UPDATE below returns 9000 but is silently discarded.

    # Step 2: key-definition files (verbatim).
    progress("key-definition files (0100, 0200, 0B00)")
    for fid, payload in _KEYFILES:
        _select(conn, fid, fid)
        _update_binary(conn, payload, "UPDATE %s" % fid)

    # Step 3: Ki.
    progress("Ki -> MF/0001")
    _select(conn, "0001", "EF.Ki")
    _update_binary(conn, ki, "UPDATE Ki")

    # Step 4: OPc (01 prefix).
    progress("OPc -> MF/6002")
    _select(conn, "6002", "EF.OPc")
    _update_binary(conn, "01" + opc, "UPDATE OPc")

    # Step 5: algorithm / key-set config — the piece pySim omits.
    progress("algorithm config (2FE5, 2FE6)")
    _select(conn, "2FE5", "EF.2FE5")
    _update_binary(conn, _ALGO_2FE5, "UPDATE 2FE5")
    _select(conn, "2FE6", "EF.2FE6")
    for rec, payload in _ALGO_2FE6_RECORDS:
        body = list(bytes.fromhex(payload))
        _step(conn, [0xA0, 0xDC, rec, 0x04, len(body)] + body,
              "UPDATE 2FE6 rec %d" % rec)

    # Step 6: ICCID (still MF, still no reselect).
    progress("ICCID -> MF/2FE2")
    _select(conn, "2FE2", "EF.ICCID")
    _update_binary(conn, icc_enc, "UPDATE ICCID")

    # --- Step 7: now safe to descend into DF_GSM (no further ADM needed). ---
    progress("IMSI -> MF/7F20/6F07")
    _select(conn, "3F00", "MF")
    _select(conn, "7F20", "DF_GSM")
    _select(conn, "6F07", "EF.IMSI")
    _update_binary(conn, imsi_enc, "UPDATE IMSI")

    progress("ACC -> MF/7F20/6F78")
    _select(conn, "6F78", "EF.ACC")
    _update_binary(conn, acc, "UPDATE ACC")

    # --- Read-back sanity check (ICCID + IMSI only). ---
    progress("read-back ICCID/IMSI")
    _select(conn, "3F00", "MF")
    _select(conn, "2FE2", "EF.ICCID")
    iccid_ok = _read_binary(conn, 10).hex() == icc_enc

    _select(conn, "3F00", "MF")
    _select(conn, "7F20", "DF_GSM")
    _select(conn, "6F07", "EF.IMSI")
    imsi_ok = _read_binary(conn, 9).hex() == imsi_enc

    logger.info(
        "gialersim: read-back ICCID %s, IMSI %s "
        "(Ki/OPc are READ=NEVER — confirm via offline AUTHENTICATE)",
        "MATCH" if iccid_ok else "MISMATCH",
        "MATCH" if imsi_ok else "MISMATCH",
    )
    return iccid_ok, imsi_ok


def program_reader(reader, **kwargs) -> Tuple[bool, bool]:
    """Open a T=0 GSM-class session to *reader* and run :func:`program_connection`.

    Owns the connect/disconnect around a single ADM session — the whole recipe
    must run without a reset, so this cannot be split into per-APDU connections.
    T=0 is preferred (GSM class answers SELECT with ``9FXX`` under T=0);
    falls back to T=1 only if T=0 cannot be negotiated.

    ``**kwargs`` are forwarded verbatim to :func:`program_connection`.
    """
    from smartcard.CardConnection import CardConnection

    conn = reader.createConnection()
    for proto, name in ((CardConnection.T0_protocol, "T=0"),
                        (CardConnection.T1_protocol, "T=1")):
        try:
            conn.connect(proto)
            logger.info("gialersim: connected with %s", name)
            break
        except Exception:
            continue
    else:
        raise GialerSimError("could not connect to card (T=0/T=1 both failed)")
    try:
        return program_connection(conn, **kwargs)
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
