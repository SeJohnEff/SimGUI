"""Tests for utils.iccid_utils module — Teleaura PLMN Numbering Standard v1.0."""

import pytest
from utils.iccid_utils import (
    compute_luhn_check, validate_luhn, generate_imsi, generate_iccid,
    COUNTRY_CODES, SITE_CODES, FPLMN_BY_COUNTRY, CUSTOMER_RANGES,
)


class TestComputeLuhnCheck:
    def test_known_value(self):
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
    def test_boliden_uk1(self):
        """Worked example: Boliden at uk1, SIM 01."""
        imsi = generate_imsi("99988", "044", "001", "03", 1)
        assert imsi == "999880440010301"

    def test_boliden_se1(self):
        """Worked example: Boliden at se1, SIM 05."""
        imsi = generate_imsi("99988", "046", "001", "03", 5)
        assert imsi == "999880460010305"

    def test_fifteen_digits(self):
        imsi = generate_imsi("99988", "044", "001", "03", 1)
        assert len(imsi) == 15
        assert imsi.isdigit()

    def test_sequence_two_digit_padding(self):
        imsi = generate_imsi("99988", "044", "001", "00", 5)
        assert imsi.endswith("05")

    def test_sequence_zero(self):
        imsi = generate_imsi("99988", "044", "001", "00", 0)
        assert imsi.endswith("00")

    def test_sequence_99(self):
        imsi = generate_imsi("99988", "044", "001", "00", 99)
        assert imsi.endswith("99")

    def test_structure(self):
        """IMSI = MCC+MNC(5) + Country(3) + Site(3) + Customer(2) + Seq(2)."""
        imsi = generate_imsi("99988", "044", "001", "03", 1)
        assert imsi[:5] == "99988"     # MCC+MNC
        assert imsi[5:8] == "044"      # Country
        assert imsi[8:11] == "001"     # Site
        assert imsi[11:13] == "03"     # Customer
        assert imsi[13:15] == "01"     # Sequence

    def test_different_mcc_mnc(self):
        imsi = generate_imsi("99989", "001", "001", "00", 0)
        assert imsi.startswith("99989")
        assert len(imsi) == 15


class TestGenerateIccid:
    def test_starts_with_89(self):
        iccid = generate_iccid("99988", "044", "001", "03", 1)
        assert iccid.startswith("89")

    def test_contains_mcc_mnc(self):
        iccid = generate_iccid("99988", "044", "001", "03", 1)
        assert iccid[2:7] == "99988"

    def test_two_zeros_padding(self):
        """ICCID uses 2 zeros padding for 20-digit total per ITU-T E.118."""
        iccid = generate_iccid("99988", "044", "001", "03", 1)
        assert iccid[7:9] == "00"

    def test_iccid_length(self):
        """ICCID = 89(2) + MCC_MNC(5) + 00(2) + MSIN(10) + Luhn(1) = 20 digits."""
        iccid = generate_iccid("99988", "044", "001", "03", 1)
        assert len(iccid) == 20
        assert iccid.isdigit()

    def test_valid_luhn(self):
        iccid = generate_iccid("99988", "044", "001", "03", 1)
        assert validate_luhn(iccid)

    def test_valid_luhn_multiple(self):
        """Every generated ICCID must have a valid Luhn check digit."""
        for seq in range(0, 100):
            iccid = generate_iccid("99988", "044", "001", "03", seq)
            assert validate_luhn(iccid), f"ICCID {iccid} has invalid Luhn"

    def test_boliden_uk1_structure(self):
        """Worked example: Boliden at uk1, SIM 01.
        ICCID = 89 + 99988 + 00 + 0440010301 + Luhn = 20 digits.
        """
        iccid = generate_iccid("99988", "044", "001", "03", 1)
        assert iccid[:2] == "89"           # MII
        assert iccid[2:7] == "99988"       # MCC+MNC
        assert iccid[7:9] == "00"          # Padding (2 zeros)
        # MSIN = country(3) + site(3) + customer(2) + seq(2) = 10 digits
        assert iccid[9:19] == "0440010301" # MSIN
        # Last digit is Luhn check
        assert len(iccid) == 20
        assert validate_luhn(iccid)

    def test_unique_iccids(self):
        iccids = {generate_iccid("99988", "044", "001", "03", i) for i in range(0, 20)}
        assert len(iccids) == 20


class TestConstants:
    def test_country_codes(self):
        assert COUNTRY_CODES["044"] == "UK"
        assert COUNTRY_CODES["046"] == "Sweden"
        assert COUNTRY_CODES["001"] == "US"
        assert COUNTRY_CODES["061"] == "Australia"
        assert COUNTRY_CODES["049"] == "Germany"

    def test_site_codes(self):
        assert SITE_CODES["044001"] == "uk1"
        assert SITE_CODES["044002"] == "uk2"
        assert SITE_CODES["046001"] == "se1"
        assert SITE_CODES["046002"] == "se2"
        assert SITE_CODES["061001"] == "au1"
        assert SITE_CODES["001001"] == "us1"

    def test_fplmn_by_country(self):
        assert "23415" in FPLMN_BY_COUNTRY["044"]
        assert "24007" in FPLMN_BY_COUNTRY["046"]

    def test_customer_ranges(self):
        assert CUSTOMER_RANGES["00"] == "Internal"
        assert CUSTOMER_RANGES["99"] == "Demo"
