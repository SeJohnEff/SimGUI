"""Simulator backend — drop-in replacement for CLI-based card operations."""

import logging
import random
import time
from typing import Dict, List, Optional, Tuple

from simulator.card_deck import generate_deck
from simulator.settings import SimulatorSettings
from simulator.virtual_card import VirtualCard

logger = logging.getLogger(__name__)


class SimulatorBackend:
    """In-memory SIM card simulator that mirrors the CardManager interface."""

    def __init__(self, settings: Optional[SimulatorSettings] = None):
        self.settings = settings or SimulatorSettings()
        self.card_deck: List[VirtualCard] = generate_deck(self.settings.num_cards)
        self.current_card_index: int = 0

    # ---- helpers -----------------------------------------------------------

    def _current_card(self) -> Optional[VirtualCard]:
        if not self.card_deck:
            return None
        return self.card_deck[self.current_card_index]

    def _delay(self):
        if self.settings.delay_ms > 0:
            time.sleep(self.settings.delay_ms / 1000)

    def _maybe_inject_error(self) -> Optional[str]:
        if self.settings.error_rate > 0 and random.random() < self.settings.error_rate:
            return "Simulated random error"
        return None

    # ---- card operations ---------------------------------------------------

    def detect_card(self) -> Tuple[bool, str]:
        """Detect the currently 'inserted' virtual card."""
        self._delay()
        err = self._maybe_inject_error()
        if err:
            return False, err

        card = self._current_card()
        if card is None:
            return False, "No card in reader"

        return True, (
            f"Card detected — sysmoISIM-{card.card_type} (virtual)"
        )

    def authenticate(self, adm1: str, force: bool = False) -> Tuple[bool, str]:
        """Authenticate with ADM1 key against the virtual card."""
        self._delay()
        err = self._maybe_inject_error()
        if err:
            return False, err

        card = self._current_card()
        if card is None:
            return False, "No card in reader"

        if card.adm1_locked:
            return False, "Card permanently locked — no ADM1 attempts remaining"

        if card.adm1 == adm1:
            card.authenticated = True
            return True, "Authentication successful (virtual)"

        # Wrong ADM1
        card.adm1_attempts_remaining -= 1
        if card.adm1_attempts_remaining <= 0:
            card.adm1_locked = True
            return False, "Wrong ADM1 — card is now permanently locked"
        return False, (
            f"Wrong ADM1 — {card.adm1_attempts_remaining} attempt(s) remaining"
        )

    def program_card(self, card_data: Dict[str, str]) -> Tuple[bool, str]:
        """Write fields to the virtual card's programmed_fields."""
        self._delay()
        err = self._maybe_inject_error()
        if err:
            return False, err

        card = self._current_card()
        if card is None:
            return False, "No card in reader"
        if not card.authenticated:
            return False, "Not authenticated"

        card.programmed_fields.update(card_data)
        return True, f"Programmed {len(card_data)} field(s) (virtual)"

    def verify_card(self, expected: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Compare current card data against expected values."""
        self._delay()
        err = self._maybe_inject_error()
        if err:
            return False, [err]

        card = self._current_card()
        if card is None:
            return False, ["No card in reader"]

        current = card.get_current_data()
        mismatches: List[str] = []
        for key, val in expected.items():
            actual = current.get(key, "")
            if actual != val:
                mismatches.append(
                    f"{key}: expected '{val}', got '{actual}'"
                )
        if mismatches:
            return False, mismatches
        return True, []

    def read_card_data(self) -> Optional[Dict[str, str]]:
        """Return the virtual card's current data."""
        card = self._current_card()
        if card is None:
            return None
        return card.get_current_data()

    def get_remaining_attempts(self) -> Optional[int]:
        """Return remaining ADM1 attempts for the current card."""
        card = self._current_card()
        if card is None:
            return None
        return card.adm1_attempts_remaining

    def next_card(self) -> Tuple[int, int]:
        """Advance to the next virtual card. Returns (new_index, total)."""
        if self.card_deck:
            old = self._current_card()
            if old:
                old.authenticated = False
            self.current_card_index = (
                (self.current_card_index + 1) % len(self.card_deck)
            )
        return self.current_card_index, len(self.card_deck)

    def previous_card(self) -> Tuple[int, int]:
        """Go to the previous virtual card. Returns (new_index, total)."""
        if self.card_deck:
            old = self._current_card()
            if old:
                old.authenticated = False
            self.current_card_index = (
                (self.current_card_index - 1) % len(self.card_deck)
            )
        return self.current_card_index, len(self.card_deck)

    def disconnect(self):
        """Clear auth state on the current card."""
        card = self._current_card()
        if card:
            card.authenticated = False

    def reset(self):
        """Regenerate the entire deck."""
        self.card_deck = generate_deck(self.settings.num_cards)
        self.current_card_index = 0
