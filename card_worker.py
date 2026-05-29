"""
Phase 0E bridge — CardWorker.

CardWorker is a thin in-process adapter that holds a CardProfile and exposes
the five card-agnostic operations used by higher-level callers.  It contains
NO card-type branches and NO subprocess/PCSC/CardWatcher integration.

This is a Phase 0 bridge only.  It exists so future callers can depend on a
stable, profile-agnostic interface without requiring any migration of existing
CardManager callers.  Phase 1 will wire CardWorker into CardManager; this file
must not be modified until that phase begins.
"""

from typing import Any, Dict, List, Optional, Tuple

from card_profiles.base import CardProfile
from card_profiles.factory import ProfileFactory


class CardWorker:
    """In-process bridge that delegates all operations to a CardProfile.

    Phase 0 bridge only — do not add card-type branches or subprocess calls.
    """

    def __init__(
        self,
        profile: Optional[CardProfile] = None,
        *,
        factory: Optional[ProfileFactory] = None,
        card_type: Optional[Any] = None,
        delegate: Optional[Any] = None,
    ) -> None:
        if profile is not None:
            self._profile = profile
        elif factory is not None and card_type is not None:
            self._profile = factory.create(card_type, delegate=delegate)
        else:
            raise ValueError(
                "Provide either a CardProfile instance or (factory + card_type)."
            )

    def read_fields(self) -> Dict[str, str]:
        return self._profile.read_fields()

    def check_retry_counter(self) -> Optional[int]:
        return self._profile.check_retry_counter()

    def authenticate(self, adm1: str) -> Tuple[bool, str]:
        return self._profile.authenticate(adm1)

    def program_fields(self, fields: Dict[str, str]) -> Tuple[bool, str]:
        return self._profile.program_fields(fields)

    def verify_fields(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        return self._profile.verify_fields(expected)
