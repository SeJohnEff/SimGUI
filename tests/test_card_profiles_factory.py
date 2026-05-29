import pytest
from card_profiles.factory import ProfileFactory
from card_profiles.base import UnknownCardTypeError
from card_profiles.sja5 import SJA5Profile
from card_profiles.gialersim import GialerSIMProfile


def _noop(*_a, **_kw):
    return {}


_SJA5_MAP = {
    "read_fields": _noop,
    "check_retry_counter": _noop,
    "authenticate": _noop,
    "program_fields": _noop,
    "verify_fields": _noop,
}

_GIALERSIM_MAP = {
    "read_fields": _noop,
    "program_fields": _noop,
    "verify_fields": _noop,
}


@pytest.fixture
def factory():
    return ProfileFactory()


def test_string_SJA5_creates_sja5_profile(factory):
    assert isinstance(factory.create("SJA5", callable_map=_SJA5_MAP), SJA5Profile)


def test_enum_like_SJA5_creates_sja5_profile(factory):
    class FakeEnum:
        name = "SJA5"
    assert isinstance(factory.create(FakeEnum(), callable_map=_SJA5_MAP), SJA5Profile)


def test_sysmoisim_sja5_string_creates_sja5_profile(factory):
    assert isinstance(factory.create("sysmoISIM-SJA5", callable_map=_SJA5_MAP), SJA5Profile)


def test_string_GIALERSIM_upper_creates_gialersim_profile(factory):
    assert isinstance(factory.create("GIALERSIM", callable_map=_GIALERSIM_MAP), GialerSIMProfile)


def test_string_gialersim_lower_creates_gialersim_profile(factory):
    assert isinstance(factory.create("gialersim", callable_map=_GIALERSIM_MAP), GialerSIMProfile)


def test_unknown_type_raises_unknown_card_type_error(factory):
    with pytest.raises(UnknownCardTypeError) as exc_info:
        factory.create("MAGIC")
    assert "MAGIC" in str(exc_info.value)


def test_unknown_type_error_message_includes_value(factory):
    with pytest.raises(UnknownCardTypeError) as exc_info:
        factory.create("totally-unknown-type")
    assert "totally-unknown-type" in str(exc_info.value)


def test_factory_is_sole_selection_point():
    import card_profiles.factory as fm
    import inspect
    src = inspect.getsource(fm)
    assert "SJA5Profile" in src
    assert "GialerSIMProfile" in src


def test_no_manager_imports_in_factory():
    import card_profiles.factory as fm
    import inspect
    src = inspect.getsource(fm)
    assert "managers" not in src
    assert "card_manager" not in src
    assert "CardManager" not in src
