"""Simulator backend — drop-in replacement for CLI-based card operations."""

import logging
import os
import random
import time
from typing import Dict, List, Optional, Tuple

from simulator.card_deck import generate_deck, load_from_csv
from simulator.settings import SimulatorSettings
from simulator.virtual_card import VirtualCard

logger = logging.getLogger(__name__)

# Bundled test data: 20 real sysmoISIM-SJA5 card profiles from sysmocom
_BUNDLED_CSV = os.path.join(
    os.path.dirname(__file__), "data", "sysmocom_test_cards.csv"
)


class SimulatorBackend:
    """In-memory SIM card simulator that mirrors the CardManager interface."""

    def __init__(self, settings: Optional[SimulatorSettings] = None,
                 csv_path: Optional[str] = None):
        self.settings = settings or SimulatorSettings()
        self.card_deck: List[VirtualCard] = self._load_deck(csv_path)
        self.current_card_index: int = 0

    def _load_deck(self, csv_path: Optional[str] = None) -> List[VirtualCard]:
        """Load cards from CSV (explicit path, settings path, or bundled), fallback to generate."""
        path = csv_path or self.settings.card_data_path
        if path and os.path.isfile(path):
            try:
                return load_from_csv(path)
            except Exception:
                logger.warning("Failed to load CSV %s, falling back to bundled data", path)

        # Try bundled CSV
        if os.path.isfile(_BUNDLED_CSV):
            try:
                return load_from_csv(_BUNDLED_CSV)
            except Exception:
                logger.warning("Failed to load bundled CSV, generating deck")

        return generate_deck(self.settings.num_cards)

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

    def authenticate(self, adm1: str, force: bool = False,
                     expected_iccid: Optional[str] = None) -> Tuple[bool, str]:
        """Authenticate with ADM1 key against the virtual card."""
        self._delay()
        err = self._maybe_inject_error()
        if err:
            return False, err

        card = self._current_card()
        if card is None:
            return False, "No card in reader"

        # ICCID cross-verification safety check
        if expected_iccid is not None and card.iccid != expected_iccid:
            return False, (
                f"ICCID mismatch! Card ICCID: {card.iccid} does not match "
                f"expected: {expected_iccid}. Wrong card or wrong data row. "
                f"Authentication aborted to prevent card lockout."
            )

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
        self.card_deck = self._load_deck()
        self.current_card_index = 0
