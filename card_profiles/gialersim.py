# Phase 0C: adapter scaffolding only — no runtime callers yet.
# authenticate() intentionally skips VERIFY: CHV 0x0C is not accessible via
# standard VERIFY APDU; sending CHV 0x0A burns retry attempts and bricks the card.

from typing import Callable, Dict, List, Optional, Tuple

from card_profiles.base import CardProfile


class GialerSIMProfile(CardProfile):
    """Thin delegating adapter for blank/gialersim cards.

    authenticate() never sends a VERIFY APDU. It stores ADM1 locally (or
    calls an injected store_adm callable) so pySim-prog can consume it later.
    check_retry_counter() returns None — the CHV 0x0C counter is not readable
    via standard APDU on these cards.
    """

    def __init__(
        self,
        delegate: object = None,
        callable_map: Optional[Dict[str, Callable]] = None,
        store_adm: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._stored_adm1: Optional[str] = None
        self._store_adm_fn = store_adm

        if callable_map is not None:
            self._read_fields_fn = callable_map["read_fields"]
            self._program_fields_fn = callable_map["program_fields"]
            self._verify_fields_fn = callable_map["verify_fields"]
        elif delegate is not None:
            self._read_fields_fn = delegate.read_card
            self._program_fields_fn = delegate.program_fields
            self._verify_fields_fn = delegate.verify_fields
        else:
            raise ValueError("GialerSIMProfile requires either delegate or callable_map")

    def read_fields(self) -> Dict[str, str]:
        return self._read_fields_fn()

    def check_retry_counter(self) -> Optional[int]:
        return None

    def authenticate(self, adm1: str) -> Tuple[bool, str]:
        if self._store_adm_fn is not None:
            self._store_adm_fn(adm1)
        else:
            self._stored_adm1 = adm1
        return (True, "ADM1 stored for programming")

    def program_fields(self, fields: Dict[str, str]) -> Tuple[bool, str]:
        return self._program_fields_fn(fields)

    def verify_fields(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        return self._verify_fields_fn(expected)
