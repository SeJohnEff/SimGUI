from typing import Any, Optional

from card_profiles.base import CardProfile, UnknownCardTypeError, normalize_card_type
from card_profiles.gialersim import GialerSIMProfile
from card_profiles.sja5 import SJA5Profile

_SJA5_NAMES = {"SJA5", "SJA2", "SYSMO", "SYSMOISIM"}
_GIALERSIM_NAMES = {"GIALERSIM"}


class ProfileFactory:
    def create(self, card_type: Any, delegate: Optional[Any] = None, **kwargs: Any) -> CardProfile:
        token = normalize_card_type(card_type)
        if token in _GIALERSIM_NAMES:
            return GialerSIMProfile(delegate=delegate, **kwargs)
        if token in _SJA5_NAMES or token.startswith("SJA") or "SYSMO" in token:
            return SJA5Profile(delegate=delegate, **kwargs)
        raise UnknownCardTypeError(str(card_type))
