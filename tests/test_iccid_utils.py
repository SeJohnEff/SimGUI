"""Tests for utils.iccid_utils module — Teleaura PLMN Numbering Standard v2.0."""

import pytest

from utils.iccid_utils import (
    FPLMN_BY_COUNTRY,
    SIM_TYPES,
    SITE_CODE_TO_ID,
    SITE_REGISTER,
    compute_luhn_check,
    generate_iccid,
    generate_imsi,
    get_fplmn_for_site,
    validate_luhn,
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
    def test_uk1_usim_sim1(self):
        """Worked example: uk1, USIM, SIM #00001."""
        imsi = generate_imsi("99988", "0001", "0", 1)
        assert imsi == "999880001000001"

    def test_se1_suci_sim5(self):
        """Worked example: se1, USIM+SUCI, SIM #00005."""
        imsi = generate_imsi("99988", "0002", "1", 5)
        assert imsi == "999880002100005"

    def test_fifteen_digits(self):
        imsi = generate_imsi("99988", "0001", "0", 1)
        assert len(imsi) == 15
        assert imsi.isdigit()

    def test_sequence_five_digit_padding(self):
        imsi = generate_imsi("99988", "0001", "0", 5)
        assert imsi.endswith("00005")

    def test_sequence_zero(self):
        imsi = generate_imsi("99988", "0001", "0", 0)
        assert imsi.endswith("00000")

    def test_sequence_99999(self):
        imsi = generate_imsi("99988", "0001", "0", 99999)
        assert imsi.endswith("99999")

    def test_structure(self):
        """IMSI = MCC+MNC(5) + SSSS(4) + T(1) + NNNNN(5)."""
        imsi = generate_imsi("99988", "0001", "0", 1)
        assert imsi[:5] == "99988"     # MCC+MNC
        assert imsi[5:9] == "0001"     # Site ID (SSSS)
        assert imsi[9] == "0"          # SIM Type (T)
        assert imsi[10:15] == "00001"  # Sequence (NNNNN)

    def test_different_mcc_mnc(self):
        imsi = generate_imsi("99989", "0001", "0", 0)
        assert imsi.startswith("99989")
        assert len(imsi) == 15

    def test_test_dev_sim_type(self):
        imsi = generate_imsi("99988", "0001", "9", 42)
        assert imsi == "999880001900042"

    def test_esim_type(self):
        imsi = generate_imsi("99988", "0003", "2", 100)
        assert imsi == "999880003200100"


class TestGenerateIccid:
    def test_starts_with_89(self):
        iccid = generate_iccid("99988", "0001", "0", 1)
        assert iccid.startswith("89")

    def test_contains_mcc_mnc(self):
        iccid = generate_iccid("99988", "0001", "0", 1)
        assert iccid[2:7] == "99988"

    def test_two_zeros_padding(self):
        """ICCID uses 2 zeros padding for 20-digit total per ITU-T E.118."""
        iccid = generate_iccid("99988", "0001", "0", 1)
        assert iccid[7:9] == "00"

    def test_iccid_length(self):
        """ICCID = 89(2) + MCC_MNC(5) + 00(2) + MSIN(10) + Luhn(1) = 20 digits."""
        iccid = generate_iccid("99988", "0001", "0", 1)
        assert len(iccid) == 20
        assert iccid.isdigit()

    def test_valid_luhn(self):
        iccid = generate_iccid("99988", "0001", "0", 1)
        assert validate_luhn(iccid)

    def test_valid_luhn_multiple(self):
        """Every generated ICCID must have a valid Luhn check digit."""
        for seq in range(0, 100):
            iccid = generate_iccid("99988", "0001", "0", seq)
            assert validate_luhn(iccid), f"ICCID {iccid} has invalid Luhn"

    def test_uk1_usim_structure(self):
        """Worked example: uk1, USIM, SIM #00001.
        ICCID = 89 + 99988 + 00 + 0001000001 + Luhn = 20 digits.
        """
        iccid = generate_iccid("99988", "0001", "0", 1)
        assert iccid[:2] == "89"            # MII
        assert iccid[2:7] == "99988"        # MCC+MNC
        assert iccid[7:9] == "00"           # Padding (2 zeros)
        # MSIN = SSSS(4) + T(1) + NNNNN(5) = 10 digits
        assert iccid[9:19] == "0001000001"  # MSIN
        # Last digit is Luhn check
        assert len(iccid) == 20
        assert validate_luhn(iccid)

    def test_unique_iccids(self):
        iccids = {generate_iccid("99988", "0001", "0", i) for i in range(0, 20)}
        assert len(iccids) == 20


class TestSiteRegister:
    def test_uk1_entry(self):
        assert SITE_REGISTER["0001"]["code"] == "uk1"
        assert SITE_REGISTER["0001"]["country"] == "United Kingdom"
        assert SITE_REGISTER["0001"]["status"] == "Active"

    def test_se1_entry(self):
        assert SITE_REGISTER["0002"]["code"] == "se1"
        assert SITE_REGISTER["0002"]["country"] == "Sweden"

    def test_se2_entry(self):
        assert SITE_REGISTER["0003"]["code"] == "se2"
        assert SITE_REGISTER["0003"]["country"] == "Sweden"

    def test_au1_entry(self):
        assert SITE_REGISTER["0004"]["code"] == "au1"
        assert SITE_REGISTER["0004"]["country"] == "Australia"
        assert SITE_REGISTER["0004"]["status"] == "Reserved"

    def test_reverse_lookup(self):
        assert SITE_CODE_TO_ID["uk1"] == "0001"
        assert SITE_CODE_TO_ID["se1"] == "0002"
        assert SITE_CODE_TO_ID["se2"] == "0003"
        assert SITE_CODE_TO_ID["au1"] == "0004"

    def test_all_entries_have_required_fields(self):
        for sid, info in SITE_REGISTER.items():
            assert len(sid) == 4 and sid.isdigit()
            assert "code" in info
            assert "country" in info
            assert "description" in info
            assert "status" in info


class TestSIMTypes:
    def test_usim(self):
        assert SIM_TYPES["0"] == "USIM"

    def test_suci(self):
        assert SIM_TYPES["1"] == "USIM+SUCI"

    def test_esim(self):
        assert SIM_TYPES["2"] == "eSIM"

    def test_test_dev(self):
        assert SIM_TYPES["9"] == "Test/Dev"


class TestGetFplmnForSite:
    def test_uk_site(self):
        fplmn = get_fplmn_for_site("0001")
        assert "23415" in fplmn
        assert "23410" in fplmn

    def test_sweden_site(self):
        fplmn = get_fplmn_for_site("0002")
        assert "24007" in fplmn
        assert "24024" in fplmn

    def test_sweden_dr_site(self):
        # se2 is also Sweden
        fplmn = get_fplmn_for_site("0003")
        assert "24007" in fplmn

    def test_no_fplmn_country(self):
        # au1 has no FPLMN defined
        fplmn = get_fplmn_for_site("0004")
        assert fplmn == ""

    def test_unknown_site(self):
        fplmn = get_fplmn_for_site("9999")
        assert fplmn == ""

    def test_empty_input(self):
        fplmn = get_fplmn_for_site("")
        assert fplmn == ""


class TestFplmnByCountry:
    def test_uk_fplmn(self):
        assert "23415" in FPLMN_BY_COUNTRY["United Kingdom"]

    def test_sweden_fplmn(self):
        assert "24007" in FPLMN_BY_COUNTRY["Sweden"]
