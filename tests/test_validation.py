"""Tests for utils.validation module."""

import pytest
from utils.validation import (
    validate_adm1, validate_imsi, validate_iccid,
    validate_hex_field, validate_card_data,
    validate_country_code, validate_site_index, validate_customer_id,
)


class TestValidateAdm1:
    def test_empty_is_ok(self):
        assert validate_adm1('') is None

    def test_8_decimal_digits(self):
        assert validate_adm1('12345678') is None

    def test_16_hex_chars(self):
        assert validate_adm1('4142434445464748') is None

    def test_16_hex_mixed_case(self):
        assert validate_adm1('abcdef0123456789') is None
        assert validate_adm1('ABCDEF0123456789') is None

    def test_too_short_decimal(self):
        assert validate_adm1('1234567') is not None

    def test_too_long_decimal(self):
        assert validate_adm1('123456789') is not None

    def test_non_digit_non_hex(self):
        assert validate_adm1('abcdefgh') is not None

    def test_wrong_length_hex(self):
        assert validate_adm1('ABCDEF012345678') is not None  # 15 chars


class TestValidateImsi:
    def test_empty_is_ok(self):
        assert validate_imsi('') is None

    def test_valid_15_digit(self):
        assert validate_imsi('001010123456789') is None

    def test_valid_6_digit(self):
        assert validate_imsi('123456') is None

    def test_too_short(self):
        assert validate_imsi('12345') is not None

    def test_too_long(self):
        assert validate_imsi('1234567890123456') is not None

    def test_non_digit(self):
        assert validate_imsi('12345678ABCDE') is not None


class TestValidateIccid:
    def test_empty_is_ok(self):
        assert validate_iccid('') is None

    def test_valid_20_digit(self):
        assert validate_iccid('89860012345678901234') is None

    def test_valid_10_digit(self):
        assert validate_iccid('8986001234') is None

    def test_too_short(self):
        assert validate_iccid('898600123') is not None

    def test_too_long(self):
        assert validate_iccid('898600123456789012345') is not None

    def test_non_digit(self):
        assert validate_iccid('89860012AB') is not None


class TestValidateHexField:
    def test_empty_is_ok(self):
        assert validate_hex_field('', 32, 'Ki') is None

    def test_valid_ki(self):
        assert validate_hex_field('A' * 32, 32, 'Ki') is None

    def test_wrong_length(self):
        assert validate_hex_field('A' * 31, 32, 'Ki') is not None

    def test_non_hex(self):
        assert validate_hex_field('G' * 32, 32, 'Ki') is not None

    def test_strips_spaces(self):
        val = 'AAAA BBBB CCCC DDDD EEEE FFFF 0000 1111'
        assert validate_hex_field(val, 32, 'Ki') is None


class TestValidateCardData:
    def test_valid_card(self, sample_card):
        assert validate_card_data(sample_card) == []

    def test_empty_card(self):
        assert validate_card_data({}) == []

    def test_invalid_imsi(self):
        errors = validate_card_data({'IMSI': 'bad'})
        assert any('IMSI' in e for e in errors)

    def test_invalid_ki(self):
        errors = validate_card_data({'Ki': 'short'})
        assert any('Ki' in e for e in errors)

    def test_multiple_errors(self):
        errors = validate_card_data({'IMSI': 'x', 'ICCID': 'y', 'ADM1': 'z'})
        assert len(errors) >= 3


class TestValidateCountryCode:
    def test_valid(self):
        assert validate_country_code("044") is None
        assert validate_country_code("001") is None

    def test_empty(self):
        assert validate_country_code("") is not None

    def test_too_short(self):
        assert validate_country_code("04") is not None

    def test_too_long(self):
        assert validate_country_code("0044") is not None

    def test_non_digit(self):
        assert validate_country_code("abc") is not None


class TestValidateSiteIndex:
    def test_valid(self):
        assert validate_site_index("001") is None
        assert validate_site_index("999") is None

    def test_empty(self):
        assert validate_site_index("") is not None

    def test_too_short(self):
        assert validate_site_index("01") is not None

    def test_too_long(self):
        assert validate_site_index("0001") is not None

    def test_non_digit(self):
        assert validate_site_index("abc") is not None


class TestValidateCustomerId:
    def test_valid(self):
        assert validate_customer_id("00") is None
        assert validate_customer_id("99") is None
        assert validate_customer_id("03") is None

    def test_empty(self):
        assert validate_customer_id("") is not None

    def test_too_short(self):
        assert validate_customer_id("0") is not None

    def test_too_long(self):
        assert validate_customer_id("000") is not None

    def test_non_digit(self):
        assert validate_customer_id("ab") is not None
