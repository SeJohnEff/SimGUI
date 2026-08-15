"""Offline USIM AUTHENTICATE self-check for gialersim Ki/OPc.

Ki and OPc are ``READ=NEVER``, so a programming ``9000`` proves nothing (pySim's
broken path returned ``9000`` on every key write yet the SIM failed Milenage
auth). The only way to *positively* confirm the keys committed is to make the
card authenticate against the expected Ki/OPc — offline, no network:

  1. Compute ``RAND`` + ``AUTN`` from the expected Ki/OPc via Milenage.
  2. Send the card a 3G USIM ``AUTHENTICATE`` (INS ``88``, P2 ``81``) in ADF_USIM.
  3. ``DB…`` (success) or ``DC…`` (sync failure) → the card's MAC verified
     against the keys → **keys correct**. ``9862`` / ``6300`` → keys wrong.

A sync failure still proves the key: the MAC is checked before the SQN freshness
check, so the result is independent of the card's sequence counter.

Milenage is self-tested against 3GPP TS 35.208 Test Set 1 before every check; if
the self-test fails, the check reports "could not determine" rather than a
possibly-false verdict. This mirrors ``tools/auth_validate_harness.py``, which
validated the method on hardware.

Framework-free (no Qt). ``pycryptodome`` (``Cryptodome``/``Crypto``) is imported
lazily so a missing crypto backend degrades to "not checked", never a crash.
"""

import logging
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Fixed challenge/context. Any RAND works; the SQN only affects DB-vs-DC (both
# prove the MAC), so its exact value is irrelevant to the verdict.
_RAND = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
_AMF = bytes.fromhex("8000")
_SQN = bytes.fromhex("000000000020")

# Default USIM AID (application identifier) if EF_DIR can't be read.
_DEFAULT_USIM_AID = bytes.fromhex("A0000000871002")

# Milenage rotation/constant tables.
_C = [bytes(15) + bytes([v]) for v in (0, 1, 2, 4, 8)]
_R = (64, 0, 32, 64, 96)


def _rot(x: bytes, r: int) -> bytes:
    r //= 8
    return x[r:] + x[:r]


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(i ^ j for i, j in zip(a, b))


def _aes(key: bytes, data: bytes) -> bytes:
    try:
        from Cryptodome.Cipher import AES
    except ImportError:
        from Crypto.Cipher import AES
    return AES.new(key, AES.MODE_ECB).encrypt(data)


def milenage(k: bytes, opc: bytes, rand: bytes, sqn: bytes,
             amf: bytes) -> Tuple[bytes, bytes, bytes]:
    """Milenage f1/f2/f5. Returns (MAC-A, RES, AK)."""
    temp = _aes(k, _xor(rand, opc))
    in1 = sqn + amf + sqn + amf
    out1 = _xor(_aes(k, _xor(_xor(temp, _rot(_xor(in1, opc), _R[0])), _C[0])), opc)
    out2 = _xor(_aes(k, _xor(_rot(_xor(temp, opc), _R[1]), _C[1])), opc)
    return out1[:8], out2[8:16], out2[:6]


def selftest() -> bool:
    """Milenage self-test against 3GPP TS 35.208 Test Set 1.

    Returns True on success, False if the crypto backend is missing or the
    vectors don't match (in which case no card verdict should be trusted).
    """
    try:
        mac, res, ak = milenage(
            bytes.fromhex("465b5ce8b199b49faa5f0a2ee238a6bc"),
            bytes.fromhex("cd63cb71954a9f4e48a5994e37a02baf"),
            bytes.fromhex("23553cbe9637a89d218ae64dae47bf35"),
            bytes.fromhex("ff9bb4d0b607"), bytes.fromhex("b9b9"))
    except Exception as exc:  # noqa: BLE001 — missing crypto, etc.
        logger.warning("gialersim self-check: Milenage unavailable (%s)", exc)
        return False
    ok = (mac.hex() == "4a9ffac354dfafb3"
          and res.hex() == "a54211d5e3ba50bf"
          and ak.hex() == "aa689c648370")
    if not ok:
        logger.error("gialersim self-check: Milenage self-test FAILED")
    return ok


# --------------------------------------------------------------------------- #
# APDU exchange (UICC class 00 — AUTHENTICATE is a 3G/USIM command)
# --------------------------------------------------------------------------- #

def _send(conn, apdu: List[int]) -> Tuple[bytes, int, int]:
    data, sw1, sw2 = conn.transmit(apdu)
    if sw1 == 0x61:
        data, sw1, sw2 = conn.transmit([0x00, 0xC0, 0x00, 0x00, sw2])
    elif sw1 == 0x6C:
        data, sw1, sw2 = conn.transmit(apdu[:-1] + [sw2])
    return bytes(data), sw1, sw2


def _find_usim_aid(conn) -> bytes:
    """Read EF_DIR (MF/2F00) for the USIM AID; fall back to the default."""
    try:
        _send(conn, [0x00, 0xA4, 0x00, 0x04, 0x02, 0x3F, 0x00])
        _, s1, s2 = _send(conn, [0x00, 0xA4, 0x00, 0x04, 0x02, 0x2F, 0x00])
        if (s1, s2) != (0x90, 0x00):
            return _DEFAULT_USIM_AID
        for rec in range(1, 9):
            data, s1, s2 = _send(conn, [0x00, 0xB2, rec, 0x04, 0x00])
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
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_USIM_AID


def verify_keys(conn, ki_hex: str, opc_hex: str) -> Tuple[Optional[bool], str]:
    """Confirm the card holds *ki_hex*/*opc_hex* via USIM AUTHENTICATE.

    Runs on an already-open card connection. Returns ``(verdict, detail)``:

    * ``(True, ...)``  — card authenticated (DB success or DC sync failure);
      the MAC verified, so the Ki/OPc on the card are correct.
    * ``(False, ...)`` — card rejected auth (e.g. 9862); keys are WRONG.
    * ``(None, ...)``  — could not determine (no crypto, select failed, etc.);
      the caller should leave the write "pending", not fail it.
    """
    if not selftest():
        return None, "Milenage self-test unavailable — cannot verify keys"
    try:
        ki = bytes.fromhex(ki_hex.strip())
        opc = bytes.fromhex(opc_hex.strip())
    except ValueError:
        return None, "invalid Ki/OPc hex"
    if len(ki) != 16 or len(opc) != 16:
        return None, "Ki/OPc must be 16 bytes"

    try:
        aid = _find_usim_aid(conn)
        _, s1, s2 = _send(conn, [0x00, 0xA4, 0x04, 0x04, len(aid)] + list(aid))
        if (s1, s2) != (0x90, 0x00):
            return None, "could not select ADF_USIM (%02X%02X)" % (s1, s2)

        mac, _res, ak = milenage(ki, opc, _RAND, _SQN, _AMF)
        autn = _xor(_SQN, ak) + _AMF + mac
        apdu = ([0x00, 0x88, 0x00, 0x81, 0x22, 0x10] + list(_RAND)
                + [0x10] + list(autn) + [0x00])
        data, s1, s2 = _send(conn, apdu)

        if data and data[0] == 0xDB:
            return True, "AUTHENTICATE success (DB) — MAC verified"
        if data and data[0] == 0xDC:
            return True, "AUTHENTICATE sync failure (DC) — MAC verified"
        return False, "AUTHENTICATE rejected (SW=%02X%02X) — keys do not match" % (s1, s2)
    except Exception as exc:  # noqa: BLE001 — transport error, treat as unknown
        return None, "self-check error: %s" % exc


def verify_keys_on_reader(reader, ki_hex: str, opc_hex: str, *,
                          connect_retries: int = 4, retry_delay: float = 0.5
                          ) -> Tuple[Optional[bool], str]:
    """Open a T=0 session to *reader* and run :func:`verify_keys`.

    Connect is retried (macOS PCSC settle after the programming session closed).
    Returns the same ``(verdict, detail)`` contract as :func:`verify_keys`; a
    connect that never succeeds yields ``(None, ...)`` so the caller keeps the
    write pending rather than failing it.
    """
    from smartcard.CardConnection import CardConnection

    conn = None
    last_exc: Optional[Exception] = None
    for attempt in range(1, connect_retries + 1):
        for proto in (CardConnection.T0_protocol, CardConnection.T1_protocol):
            candidate = reader.createConnection()
            try:
                candidate.connect(proto)
                conn = candidate
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                try:
                    candidate.disconnect()
                except Exception:
                    pass
        if conn is not None:
            break
        if attempt < connect_retries:
            time.sleep(retry_delay)

    if conn is None:
        return None, "self-check could not connect (%s)" % last_exc
    try:
        return verify_keys(conn, ki_hex, opc_hex)
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
