import pytest
from typing import Dict, List, Optional, Tuple

from card_profiles import CardProfile, CardProfileError, UnknownCardTypeError


class _ConcreteProfile(CardProfile):
    def read_fields(self) -> Dict[str, str]:
        return {"ICCID": "1234"}

    def check_retry_counter(self) -> Optional[int]:
        return 3

    def authenticate(self, adm1: str) -> Tuple[bool, str]:
        return True, "ok"

    def program_fields(self, fields: Dict[str, str]) -> Tuple[bool, str]:
        return True, "programmed"

    def verify_fields(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        return True, []


def test_card_profile_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        CardProfile()  # type: ignore[abstract]


def test_concrete_subclass_instantiates():
    p = _ConcreteProfile()
    assert isinstance(p, CardProfile)


def test_concrete_read_fields():
    assert _ConcreteProfile().read_fields() == {"ICCID": "1234"}


def test_concrete_check_retry_counter():
    assert _ConcreteProfile().check_retry_counter() == 3


def test_concrete_authenticate():
    ok, msg = _ConcreteProfile().authenticate("88888888")
    assert ok is True
    assert msg == "ok"


def test_concrete_program_fields():
    ok, msg = _ConcreteProfile().program_fields({"IMSI": "001010000000001"})
    assert ok is True


def test_concrete_verify_fields():
    ok, mismatches = _ConcreteProfile().verify_fields({"ICCID": "1234"})
    assert ok is True
    assert mismatches == []


def test_unknown_card_type_error_contains_type():
    err = UnknownCardTypeError("MAGIC_XL")
    assert "MAGIC_XL" in str(err)


def test_unknown_card_type_error_is_profile_error():
    assert issubclass(UnknownCardTypeError, CardProfileError)
