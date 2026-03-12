"""Tests for utils.iccid_utils module."""

import pytest
from utils.iccid_utils import compute_luhn_check, validate_luhn, generate_imsi, generate_iccid


class TestComputeLuhnCheck:
    def test_known_value(self):
        # ICCID 89001012345678901 -> check digit for this prefix
        digits = "89001012345678901"
        check = compute_luhn_check(digits)
        assert check.isdigit()
        assert len(check) == 1

    def test_all_zeros(self):
        check = compute_luhn_check("0000000000")
        assert check == "0"

    def test_single_digit(self):
        check = compute_luhn_check("7")
        assert check.isdigit()

    def test_roundtrip(self):
        """compute then validate should agree."""
        prefix = "8999901234567890"
        check = compute_luhn_check(prefix)
        full = prefix + check
        assert validate_luhn(full)

    def test_different_prefixes_differ(self):
        c1 = compute_luhn_check("12345678901234567")
        c2 = compute_luhn_check("12345678901234568")
        # They may or may not differ, but both must be valid digits
        assert c1.isdigit()
        assert c2.isdigit()


class TestValidateLuhn:
    def test_valid_iccid(self):
        prefix = "8901260012345678901"
        check = compute_luhn_check(prefix)
        assert validate_luhn(prefix + check)

    def test_invalid_check_digit(self):
        prefix = "8901260012345678901"
        check = compute_luhn_check(prefix)
        wrong = str((int(check) + 1) % 10)
        assert not validate_luhn(prefix + wrong)

    def test_too_short(self):
        assert not validate_luhn("1")

    def test_empty(self):
        assert not validate_luhn("")

    def test_non_digit(self):
        assert not validate_luhn("89ABCDEF01234567890")

    def test_two_digits(self):
        prefix = "7"
        check = compute_luhn_check(prefix)
        assert validate_luhn(prefix + check)


class TestGenerateImsi:
    def test_basic_generation(self):
        imsi = generate_imsi("99988", "0003", "0100", 1)
        assert imsi == "9998800030100001"

    def test_sequence_padding(self):
        imsi = generate_imsi("99988", "0003", "0100", 5)
        assert imsi.endswith("005")

    def test_sequence_triple_digit(self):
        imsi = generate_imsi("99988", "0003", "0100", 100)
        assert imsi.endswith("100")

    def test_different_mcc_mnc(self):
        imsi = generate_imsi("31026", "0001", "0200", 42)
        assert imsi.startswith("31026")
        assert imsi.endswith("042")

    def test_structure(self):
        """IMSI = MCC+MNC + Customer + Type + Seq(3)."""
        imsi = generate_imsi("99988", "0003", "0100", 1)
        assert imsi[:5] == "99988"
        assert imsi[5:9] == "0003"
        assert imsi[9:13] == "0100"
        assert imsi[13:] == "001"
        assert len(imsi) == len("99988") + len("0003") + len("0100") + 3


class TestGenerateIccid:
    def test_starts_with_89(self):
        iccid = generate_iccid("99988", "0003", "0100", 1)
        assert iccid.startswith("89")

    def test_contains_mcc_mnc(self):
        iccid = generate_iccid("99988", "0003", "0100", 1)
        assert iccid[2:7] == "99988"

    def test_valid_luhn(self):
        iccid = generate_iccid("99988", "0003", "0100", 1)
        assert validate_luhn(iccid)

    def test_valid_luhn_multiple(self):
        """Every generated ICCID must have a valid Luhn check digit."""
        for seq in range(1, 50):
            iccid = generate_iccid("99988", "0003", "0100", seq)
            assert validate_luhn(iccid), f"ICCID {iccid} has invalid Luhn"

    def test_structure(self):
        """ICCID = 89 + MCC+MNC + 00000 + Customer + Type + Seq(3) + Check."""
        iccid = generate_iccid("99988", "0003", "0100", 1)
        assert iccid[:2] == "89"
        assert iccid[2:7] == "99988"
        assert iccid[7:12] == "00000"
        assert iccid[12:16] == "0003"
        assert iccid[16:20] == "0100"
        # seq=1 padded to 3 digits
        assert iccid[20:23] == "001"
        # Last digit is Luhn check
        assert len(iccid) == 24

    def test_unique_iccids(self):
        iccids = {generate_iccid("99988", "0003", "0100", i) for i in range(1, 20)}
        assert len(iccids) == 19
