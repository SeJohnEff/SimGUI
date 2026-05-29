from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple


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
