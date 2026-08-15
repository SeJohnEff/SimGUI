from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


def normalize_card_type(card_type: Any) -> str:
    """Normalize a card type (``CardType`` enum, name, or string) to a token.

    Single normalization used by both the profile factory and the capability
    schema, so ``CardType.GIALERSIM``, ``"gialersim"`` and ``"GIALERSIM"`` all
    map to the same key.
    """
    raw = card_type.name if hasattr(card_type, "name") else str(card_type)
    return raw.upper().replace("-", "").replace("_", "").replace(" ", "")


class CardProfileError(Exception):
    pass


class UnknownCardTypeError(CardProfileError):
    def __init__(self, card_type: str) -> None:
        self.card_type = card_type
        super().__init__(f"Unknown card type: {card_type!r}")


class CardProfile(ABC):
    @abstractmethod
    def read_fields(self) -> Dict[str, str]:
        ...

    @abstractmethod
    def check_retry_counter(self) -> Optional[int]:
        ...

    @abstractmethod
    def authenticate(self, adm1: str) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def program_fields(self, fields: Dict[str, str]) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def verify_fields(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        ...
