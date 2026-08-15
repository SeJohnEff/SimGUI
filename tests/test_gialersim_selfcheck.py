"""Tests for the offline USIM AUTHENTICATE self-check (gialersim_selfcheck.py).

The self-check is the only positive confirmation that gialersim Ki/OPc committed
(they are READ=NEVER). These tests lock the verdict mapping and the Milenage
self-test that guards it. Loaded by file path so the framework-free module is
exercised without importing the Qt-bound managers package.
"""

import importlib.util
import os

_HERE = os.path.dirname(__file__)
_MOD = os.path.join(_HERE, "..", "managers", "gialersim_selfcheck.py")
_spec = importlib.util.spec_from_file_location("gialersim_selfcheck", _MOD)
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

KI = "16CEF06C82FDAF5C4E703FF3F30717E7"
OPC = "E84F2946118E672B6707D5C3308D712D"


class FakeConn:
    """Emulates the APDUs verify_keys sends.

    SELECT (A4) -> 9000; READ RECORD (B2) -> 6A83 (no EF_DIR -> default AID);
    AUTHENTICATE (88) -> the configured response. ``select_aid_sw`` overrides the
    SELECT-by-AID (P1=04) status word to exercise the "can't select" path.
    """

    def __init__(self, auth_response, select_aid_sw=(0x90, 0x00)):
        self.auth_response = auth_response
        self.select_aid_sw = select_aid_sw

    def transmit(self, apdu):
        ins, p1 = apdu[1], apdu[2]
        if ins == 0xA4 and p1 == 0x04 and apdu[3] == 0x04:
            return [], self.select_aid_sw[0], self.select_aid_sw[1]
        if ins == 0xA4:
            return [], 0x90, 0x00
        if ins == 0xB2:
            return [], 0x6A, 0x83
        if ins == 0x88:
            return self.auth_response
        return [], 0x90, 0x00


class TestSelftest:
    def test_milenage_self_test_passes(self):
        assert sc.selftest() is True

    def test_milenage_known_vector(self):
        # 3GPP TS 35.208 Test Set 1.
        mac, res, ak = sc.milenage(
            bytes.fromhex("465b5ce8b199b49faa5f0a2ee238a6bc"),
            bytes.fromhex("cd63cb71954a9f4e48a5994e37a02baf"),
            bytes.fromhex("23553cbe9637a89d218ae64dae47bf35"),
            bytes.fromhex("ff9bb4d0b607"), bytes.fromhex("b9b9"))
        assert mac.hex() == "4a9ffac354dfafb3"
        assert res.hex() == "a54211d5e3ba50bf"
        assert ak.hex() == "aa689c648370"


class TestVerdict:
    def test_db_success_is_verified(self):
        verdict, _ = sc.verify_keys(
            FakeConn(([0xDB, 0x08] + [0] * 8, 0x90, 0x00)), KI, OPC)
        assert verdict is True

    def test_dc_sync_failure_is_verified(self):
        # Sync failure still proves the MAC (checked before SQN freshness).
        verdict, _ = sc.verify_keys(
            FakeConn(([0xDC, 0x0E] + [0] * 14, 0x90, 0x00)), KI, OPC)
        assert verdict is True

    def test_9862_is_wrong_keys(self):
        verdict, detail = sc.verify_keys(FakeConn(([], 0x98, 0x62)), KI, OPC)
        assert verdict is False
        assert "9862" in detail

    def test_select_adf_failure_is_unknown(self):
        verdict, _ = sc.verify_keys(
            FakeConn(([], 0x90, 0x00), select_aid_sw=(0x6A, 0x82)), KI, OPC)
        assert verdict is None

    def test_bad_hex_is_unknown(self):
        verdict, _ = sc.verify_keys(FakeConn(([], 0x90, 0x00)), "ZZ", OPC)
        assert verdict is None

    def test_short_key_is_unknown(self):
        verdict, _ = sc.verify_keys(FakeConn(([], 0x90, 0x00)), "AABB", OPC)
        assert verdict is None
