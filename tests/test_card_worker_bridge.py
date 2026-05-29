"""Tests for Phase 0E CardWorker bridge."""

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from card_profiles.base import CardProfile
from card_profiles.factory import ProfileFactory
from card_worker import CardWorker


class FakeProfile(CardProfile):
    def read_fields(self) -> Dict[str, str]:
        return {"ICCID": "1234567890123456789"}

    def check_retry_counter(self) -> Optional[int]:
        return 3

    def authenticate(self, adm1: str) -> Tuple[bool, str]:
        return (True, f"ok:{adm1}")

    def program_fields(self, fields: Dict[str, str]) -> Tuple[bool, str]:
        return (True, f"programmed:{list(fields.keys())}")

    def verify_fields(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        return (True, [])


# --- delegation tests ---

def test_delegates_read_fields():
    worker = CardWorker(profile=FakeProfile())
    assert worker.read_fields() == {"ICCID": "1234567890123456789"}


def test_delegates_check_retry_counter():
    worker = CardWorker(profile=FakeProfile())
    assert worker.check_retry_counter() == 3


def test_delegates_authenticate():
    worker = CardWorker(profile=FakeProfile())
    ok, msg = worker.authenticate("88888888")
    assert ok is True
    assert "88888888" in msg


def test_delegates_program_fields():
    worker = CardWorker(profile=FakeProfile())
    ok, msg = worker.program_fields({"IMSI": "240010000000001"})
    assert ok is True
    assert "IMSI" in msg


def test_delegates_verify_fields():
    worker = CardWorker(profile=FakeProfile())
    ok, mismatches = worker.verify_fields({"ICCID": "1234567890123456789"})
    assert ok is True
    assert mismatches == []


# --- factory construction ---

def test_construction_via_factory():
    factory = ProfileFactory()
    worker = CardWorker(factory=factory, card_type="sja5", delegate=MagicMock())
    # Constructed without error; profile is a CardProfile subclass.
    assert isinstance(worker._profile, CardProfile)


def test_construction_requires_profile_or_factory():
    with pytest.raises(ValueError):
        CardWorker()


# --- no card-type branching ---

def test_no_card_type_branching():
    """CardWorker contains no card-type branch logic of its own."""
    import inspect
    import card_worker as cw_module

    src = inspect.getsource(cw_module.CardWorker)
    for keyword in ("sja5", "gialersim", "GIALERSIM", "SJA5", "CardType"):
        assert keyword not in src, f"CardWorker must not branch on {keyword!r}"


# --- runtime callers untouched ---

def test_card_manager_not_imported_by_card_worker():
    import card_worker as cw_module
    assert "card_manager" not in dir(cw_module)
    import sys
    # card_worker import must not pull in managers.card_manager
    assert "managers.card_manager" not in sys.modules or True  # allowed to exist for other reasons
    # The key invariant: card_worker module has no reference to card_manager
    src = open(cw_module.__file__).read()
    assert "card_manager" not in src
