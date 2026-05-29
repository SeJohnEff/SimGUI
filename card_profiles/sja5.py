# Phase 0B: adapter scaffolding only — no runtime callers yet.
# Method names in the callable map document the intended CardManager API surface.
# If a delegate method does not exist, the constructor will raise AttributeError
# at instantiation time rather than silently at call time.

from typing import Callable, Dict, List, Optional, Tuple

from card_profiles.base import CardProfile


class SJA5Profile(CardProfile):
    """Thin delegating adapter for sysmoISIM-SJA5 cards.

    Accepts a callable map so that Phase 0B does not force CardManager
    inspection. The map keys correspond to the five CardProfile operations.
    """

    def __init__(
        self,
        delegate: object = None,
        card_type: Optional[str] = None,
        callable_map: Optional[Dict[str, Callable]] = None,
    ) -> None:
        self._card_type = card_type
        if callable_map is not None:
            self._read_fields_fn = callable_map["read_fields"]
            self._check_retry_fn = callable_map["check_retry_counter"]
            self._authenticate_fn = callable_map["authenticate"]
            self._program_fields_fn = callable_map["program_fields"]
            self._verify_fields_fn = callable_map["verify_fields"]
        elif delegate is not None:
            self._read_fields_fn = delegate.read_card
            self._check_retry_fn = delegate.check_retry_counter
            self._authenticate_fn = delegate.authenticate_adm
            self._program_fields_fn = delegate.program_fields
            self._verify_fields_fn = delegate.verify_fields
        else:
            raise ValueError("SJA5Profile requires either delegate or callable_map")

    def read_fields(self) -> Dict[str, str]:
        return self._read_fields_fn()

    def check_retry_counter(self) -> Optional[int]:
        return self._check_retry_fn()

    def authenticate(self, adm1: str) -> Tuple[bool, str]:
        return self._authenticate_fn(adm1)

    def program_fields(self, fields: Dict[str, str]) -> Tuple[bool, str]:
        return self._program_fields_fn(fields)

    def verify_fields(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        return self._verify_fields_fn(expected)
