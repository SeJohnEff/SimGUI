import pytest
from card_profiles.sja5 import SJA5Profile


def _make_profile(**overrides):
    defaults = {
        "read_fields": lambda: {"ICCID": "1234567890123456789"},
        "check_retry_counter": lambda: 3,
        "authenticate": lambda adm1: (True, "ok"),
        "program_fields": lambda fields: (True, "programmed"),
        "verify_fields": lambda expected: (True, []),
    }
    defaults.update(overrides)
    return SJA5Profile(callable_map=defaults)


def test_read_fields_delegates_and_returns_dict():
    profile = _make_profile(read_fields=lambda: {"ICCID": "abc"})
    result = profile.read_fields()
    assert result == {"ICCID": "abc"}
    assert isinstance(result, dict)


def test_check_retry_counter_delegates_and_returns_int():
    profile = _make_profile(check_retry_counter=lambda: 5)
    result = profile.check_retry_counter()
    assert result == 5


def test_check_retry_counter_can_return_none():
    profile = _make_profile(check_retry_counter=lambda: None)
    result = profile.check_retry_counter()
    assert result is None


def test_authenticate_delegates_adm1_and_returns_tuple():
    received = []

    def fake_auth(adm1):
        received.append(adm1)
        return (True, "authenticated")

    profile = _make_profile(authenticate=fake_auth)
    ok, msg = profile.authenticate("deadbeef")
    assert ok is True
    assert msg == "authenticated"
    assert received == ["deadbeef"]


def test_authenticate_failure_path():
    profile = _make_profile(authenticate=lambda adm1: (False, "wrong key"))
    ok, msg = profile.authenticate("bad")
    assert ok is False
    assert "wrong" in msg


def test_program_fields_delegates_fields_and_returns_tuple():
    received = []

    def fake_program(fields):
        received.append(fields)
        return (True, "done")

    profile = _make_profile(program_fields=fake_program)
    fields = {"IMSI": "001010000000001", "Ki": "aa" * 16}
    ok, msg = profile.program_fields(fields)
    assert ok is True
    assert received == [fields]


def test_program_fields_failure_path():
    profile = _make_profile(program_fields=lambda f: (False, "error"))
    ok, msg = profile.program_fields({})
    assert ok is False


def test_verify_fields_delegates_expected_and_returns_tuple():
    received = []

    def fake_verify(expected):
        received.append(expected)
        return (True, [])

    profile = _make_profile(verify_fields=fake_verify)
    expected = {"IMSI": "001010000000001"}
    ok, mismatches = profile.verify_fields(expected)
    assert ok is True
    assert mismatches == []
    assert received == [expected]


def test_verify_fields_mismatch_path():
    profile = _make_profile(verify_fields=lambda e: (False, ["IMSI"]))
    ok, mismatches = profile.verify_fields({"IMSI": "wrong"})
    assert ok is False
    assert "IMSI" in mismatches


def test_requires_delegate_or_callable_map():
    with pytest.raises((ValueError, TypeError)):
        SJA5Profile()


def test_no_card_type_branching_in_sja5_profile():
    # SJA5Profile must not branch on card_type internally.
    # If card_type were consulted, different types would produce different results
    # from identical callable maps — which should never happen.
    cm = {
        "read_fields": lambda: {"x": "1"},
        "check_retry_counter": lambda: 1,
        "authenticate": lambda a: (True, ""),
        "program_fields": lambda f: (True, ""),
        "verify_fields": lambda e: (True, []),
    }
    p1 = SJA5Profile(callable_map=cm, card_type="SJA5")
    p2 = SJA5Profile(callable_map=cm, card_type="OTHER")
    assert p1.read_fields() == p2.read_fields()
    assert p1.check_retry_counter() == p2.check_retry_counter()
    assert p1.authenticate("k") == p2.authenticate("k")
    assert p1.program_fields({}) == p2.program_fields({})
    assert p1.verify_fields({}) == p2.verify_fields({})
