"""Phase 0C tests for GialerSIMProfile — adapter behavior only, no pySim logic."""
import inspect

import pytest

from card_profiles.gialersim import GialerSIMProfile


def _make_callable_map(
    read_return=None,
    program_return=None,
    verify_return=None,
):
    read_return = read_return if read_return is not None else {"ICCID": ""}
    program_return = program_return if program_return is not None else (True, "ok")
    verify_return = verify_return if verify_return is not None else (True, [])
    return {
        "read_fields": lambda: read_return,
        "program_fields": lambda fields: program_return,
        "verify_fields": lambda expected: verify_return,
    }


# ---------------------------------------------------------------------------
# 1. read_fields delegates and returns dict
# ---------------------------------------------------------------------------

def test_read_fields_delegates_and_returns_dict():
    expected = {"ICCID": "", "IMSI": "", "ACC": "ffff"}
    profile = GialerSIMProfile(callable_map=_make_callable_map(read_return=expected))
    result = profile.read_fields()
    assert result == expected
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 2. check_retry_counter returns None by default
# ---------------------------------------------------------------------------

def test_check_retry_counter_returns_none():
    profile = GialerSIMProfile(callable_map=_make_callable_map())
    assert profile.check_retry_counter() is None


def test_check_retry_counter_returns_none_even_with_store_adm():
    called = []
    profile = GialerSIMProfile(
        callable_map=_make_callable_map(),
        store_adm=lambda adm1: called.append(adm1),
    )
    assert profile.check_retry_counter() is None


# ---------------------------------------------------------------------------
# 3. authenticate stores ADM1 and returns success without VERIFY delegate
# ---------------------------------------------------------------------------

def test_authenticate_stores_adm1_locally():
    profile = GialerSIMProfile(callable_map=_make_callable_map())
    ok, msg = profile.authenticate("88888888")
    assert ok is True
    assert "ADM1" in msg or "stored" in msg
    assert profile._stored_adm1 == "88888888"


def test_authenticate_returns_tuple_bool_str():
    profile = GialerSIMProfile(callable_map=_make_callable_map())
    result = profile.authenticate("88888888")
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], bool)
    assert isinstance(result[1], str)


def test_authenticate_does_not_call_any_delegate():
    """Callable map has no 'authenticate' key — if profile tried to delegate it would KeyError."""
    profile = GialerSIMProfile(callable_map=_make_callable_map())
    # Must not raise — there is intentionally no authenticate callable in the map
    ok, _ = profile.authenticate("88888888")
    assert ok is True


# ---------------------------------------------------------------------------
# 4. authenticate uses injected store_adm callable if provided
# ---------------------------------------------------------------------------

def test_authenticate_calls_store_adm_callable():
    received = []
    profile = GialerSIMProfile(
        callable_map=_make_callable_map(),
        store_adm=lambda adm1: received.append(adm1),
    )
    ok, _ = profile.authenticate("3838383838383838")
    assert ok is True
    assert received == ["3838383838383838"]


def test_authenticate_with_store_adm_does_not_set_stored_adm1():
    received = []
    profile = GialerSIMProfile(
        callable_map=_make_callable_map(),
        store_adm=lambda adm1: received.append(adm1),
    )
    profile.authenticate("88888888")
    assert profile._stored_adm1 is None


# ---------------------------------------------------------------------------
# 5. program_fields delegates to programming callable
# ---------------------------------------------------------------------------

def test_program_fields_delegates():
    fields = {"IMSI": "240011234567890", "Ki": "aabbccdd" * 4}
    received = []

    def fake_program(f):
        received.append(f)
        return (True, "programmed")

    cmap = _make_callable_map()
    cmap["program_fields"] = fake_program
    profile = GialerSIMProfile(callable_map=cmap)
    ok, msg = profile.program_fields(fields)
    assert ok is True
    assert received == [fields]


def test_program_fields_propagates_failure():
    cmap = _make_callable_map(program_return=(False, "write error"))
    profile = GialerSIMProfile(callable_map=cmap)
    ok, msg = profile.program_fields({})
    assert ok is False
    assert "error" in msg.lower()


# ---------------------------------------------------------------------------
# 6. verify_fields delegates and returns tuple
# ---------------------------------------------------------------------------

def test_verify_fields_delegates():
    expected = {"IMSI": "240011234567890"}
    received = []

    def fake_verify(e):
        received.append(e)
        return (True, [])

    cmap = _make_callable_map()
    cmap["verify_fields"] = fake_verify
    profile = GialerSIMProfile(callable_map=cmap)
    ok, mismatches = profile.verify_fields(expected)
    assert ok is True
    assert mismatches == []
    assert received == [expected]


def test_verify_fields_propagates_mismatches():
    cmap = _make_callable_map(verify_return=(False, ["IMSI mismatch"]))
    profile = GialerSIMProfile(callable_map=cmap)
    ok, mismatches = profile.verify_fields({"IMSI": "wrong"})
    assert ok is False
    assert "IMSI mismatch" in mismatches


# ---------------------------------------------------------------------------
# 7. No card-type branching or pySim logic in GialerSIMProfile
# ---------------------------------------------------------------------------

def test_no_platform_or_pysim_imports():
    import card_profiles.gialersim as mod
    source = inspect.getsource(mod)
    # Check for actual imports of forbidden modules, not word occurrences in comments
    for forbidden in ("sys.platform", "import subprocess", "import pySim", "from pySim",
                      "import pysim", "from pysim", "import os\n", "import os "):
        assert forbidden not in source, f"Forbidden import found: {forbidden!r}"


def test_no_card_type_branching_in_source():
    import card_profiles.gialersim as mod
    source = inspect.getsource(mod)
    for branch_kw in ("CardType", "if card_type", "SJA5", "SJA2", "MAGIC"):
        assert branch_kw not in source, f"Card-type branch found: {branch_kw!r}"


def test_delegate_path_also_works():
    class FakeDelegate:
        def read_card(self):
            return {"ACC": "ffff"}

        def program_fields(self, fields):
            return (True, "ok")

        def verify_fields(self, expected):
            return (True, [])

    profile = GialerSIMProfile(delegate=FakeDelegate())
    assert profile.read_fields() == {"ACC": "ffff"}
    assert profile.check_retry_counter() is None
    ok, _ = profile.authenticate("88888888")
    assert ok is True


def test_requires_delegate_or_callable_map():
    with pytest.raises(ValueError):
        GialerSIMProfile()
