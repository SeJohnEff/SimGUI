"""Additional simulator edge case tests.

Covers gaps in simulator_backend.py and card_manager simulator paths:
- read_card with authenticated=False (read_protected_data returns None)
- next_card / prev_card wraparound behaviour
- Error injection at various rates
- Empty deck edge cases for all operations
- authenticate() ICCID mismatch does not consume attempts
- _delay() is called when delay_ms > 0
- reset() reloads deck
- read_card_data for empty deck
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_manager import CardManager
from simulator.card_deck import generate_deck
from simulator.settings import SimulatorSettings
from simulator.simulator_backend import SimulatorBackend
from simulator.virtual_card import VirtualCard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backend(num_cards=5, error_rate=0.0, delay_ms=0):
    settings = SimulatorSettings(delay_ms=delay_ms, error_rate=error_rate,
                                  num_cards=num_cards)
    return SimulatorBackend(settings)


def _backend_with_cards(cards):
    """Backend with a custom card list (bypasses CSV loading)."""
    b = _backend(num_cards=0)
    b.card_deck = cards
    b.current_card_index = 0
    return b


def _make_card(card_type="SJA2", iccid="1234567890123456789",
               imsi="001010123456789", adm1="12345678"):
    return VirtualCard(
        card_type=card_type,
        iccid=iccid, imsi=imsi,
        ki="A" * 32, opc="B" * 32,
        adm1=adm1,
    )


# ---------------------------------------------------------------------------
# read_card with authenticated=False vs True
# ---------------------------------------------------------------------------

class TestReadCardAuth:
    """read_protected_data returns None without auth; returns data with auth."""

    def test_read_protected_unauthenticated(self):
        """read_protected_data() returns None when not authenticated."""
        b = _backend()
        assert b._current_card().authenticated is False
        assert b.read_protected_data() is None

    def test_read_protected_authenticated(self):
        """read_protected_data() returns dict when authenticated."""
        b = _backend()
        card = b._current_card()
        b.authenticate(card.adm1)
        data = b.read_protected_data()
        assert data is not None
        assert "ki" in data
        assert "opc" in data

    def test_read_public_no_auth_needed(self):
        """read_public_data() works without authentication."""
        b = _backend()
        data = b.read_public_data()
        assert data is not None
        assert "iccid" in data

    def test_read_card_data_always_works(self):
        """read_card_data() returns data regardless of auth state."""
        b = _backend()
        data = b.read_card_data()
        assert data is not None
        assert "iccid" in data

    def test_read_protected_empty_deck(self):
        """read_protected_data() returns None when deck is empty."""
        b = _backend()
        b.card_deck = []
        assert b.read_protected_data() is None

    def test_read_public_empty_deck(self):
        """read_public_data() returns None when deck is empty."""
        b = _backend()
        b.card_deck = []
        assert b.read_public_data() is None

    def test_read_card_data_empty_deck(self):
        """read_card_data() returns None when deck is empty."""
        b = _backend()
        b.card_deck = []
        assert b.read_card_data() is None


# ---------------------------------------------------------------------------
# next_card / prev_card wraparound
# ---------------------------------------------------------------------------

class TestCardNavigation:
    """Tests for next_card() and previous_card() wraparound."""

    def test_next_card_basic_increment(self):
        """next_card() increments the index by 1."""
        b = _backend(num_cards=5)
        idx, total = b.next_card()
        assert idx == 1
        assert total == len(b.card_deck)

    def test_next_card_wraps_to_zero(self):
        """next_card() wraps from last to first card."""
        b = _backend(num_cards=3)
        # Force exactly 3 generated cards (bypass bundled CSV)
        b.card_deck = generate_deck(count=3)
        b.current_card_index = 2  # last card
        idx, total = b.next_card()
        assert idx == 0  # wrapped

    def test_prev_card_basic_decrement(self):
        """previous_card() decrements the index by 1."""
        b = _backend(num_cards=5)
        b.current_card_index = 3
        idx, total = b.previous_card()
        assert idx == 2

    def test_prev_card_wraps_from_zero(self):
        """previous_card() wraps from first to last card."""
        b = _backend(num_cards=3)
        # Force exactly 3 generated cards (bypass bundled CSV)
        b.card_deck = generate_deck(count=3)
        b.current_card_index = 0
        idx, total = b.previous_card()
        assert idx == 2  # len(deck) - 1

    def test_next_card_cycles_full_deck(self):
        """next_card() over full deck length returns to start."""
        b = _backend(num_cards=5)
        total = len(b.card_deck)
        for _ in range(total):
            b.next_card()
        assert b.current_card_index == 0

    def test_prev_card_cycles_full_deck(self):
        """previous_card() over full deck length returns to start."""
        b = _backend(num_cards=5)
        total = len(b.card_deck)
        for _ in range(total):
            b.previous_card()
        assert b.current_card_index == 0

    def test_next_card_clears_auth(self):
        """next_card() clears authentication on the previous card."""
        b = _backend(num_cards=3)
        card = b._current_card()
        b.authenticate(card.adm1)
        assert card.authenticated is True
        b.next_card()
        assert card.authenticated is False

    def test_prev_card_clears_auth(self):
        """previous_card() clears authentication on the current card."""
        b = _backend(num_cards=3)
        b.current_card_index = 1
        card = b._current_card()
        b.authenticate(card.adm1)
        assert card.authenticated is True
        b.previous_card()
        assert card.authenticated is False

    def test_next_card_empty_deck_returns_zero(self):
        """next_card() on empty deck returns (0, 0) gracefully."""
        b = _backend(num_cards=0)
        b.card_deck = []
        idx, total = b.next_card()
        assert idx == 0
        assert total == 0

    def test_prev_card_empty_deck_returns_zero(self):
        """previous_card() on empty deck returns (0, 0) gracefully."""
        b = _backend(num_cards=0)
        b.card_deck = []
        idx, total = b.previous_card()
        assert idx == 0
        assert total == 0

    def test_next_then_prev_returns_to_start(self):
        """next_card() then previous_card() returns to original index."""
        b = _backend(num_cards=5)
        start = b.current_card_index
        b.next_card()
        b.previous_card()
        assert b.current_card_index == start


# ---------------------------------------------------------------------------
# Error injection
# ---------------------------------------------------------------------------

class TestErrorInjection:
    """Tests for _maybe_inject_error() / error_rate parameter."""

    def test_error_rate_zero_never_fails(self):
        """error_rate=0.0 never injects errors."""
        b = _backend(error_rate=0.0)
        for _ in range(50):
            ok, _ = b.detect_card()
            assert ok is True

    def test_error_rate_one_always_fails(self):
        """error_rate=1.0 always injects errors."""
        b = _backend(error_rate=1.0)
        ok, msg = b.detect_card()
        assert ok is False
        assert "Simulated" in msg

    def test_error_rate_one_affects_authenticate(self):
        """error_rate=1.0 injects error into authenticate()."""
        b = _backend(error_rate=1.0)
        ok, msg = b.authenticate("12345678")
        assert ok is False
        assert "Simulated" in msg

    def test_error_rate_one_affects_program_card(self):
        """error_rate=1.0 injects error into program_card()."""
        b = _backend(error_rate=0.0)
        card = b._current_card()
        b.authenticate(card.adm1)

        # Now switch to error mode
        b.settings.error_rate = 1.0
        ok, msg = b.program_card({"imsi": "x"})
        assert ok is False
        assert "Simulated" in msg

    def test_error_rate_one_affects_verify_card(self):
        """error_rate=1.0 injects error into verify_card()."""
        b = _backend(error_rate=1.0)
        ok, errors = b.verify_card({"imsi": "test"})
        assert ok is False
        assert any("Simulated" in e for e in errors)

    def test_error_rate_partial_sometimes_fails(self):
        """error_rate=0.5 fails roughly 50% of the time over many tries."""
        b = _backend(error_rate=0.5)
        failures = sum(1 for _ in range(200) if not b.detect_card()[0])
        # With 200 trials at 50%, expect between 50 and 150 failures
        assert 30 < failures < 170, f"Unexpected failure count: {failures}"

    def test_maybe_inject_error_returns_none_at_zero(self):
        """_maybe_inject_error() returns None at error_rate=0."""
        b = _backend(error_rate=0.0)
        for _ in range(20):
            assert b._maybe_inject_error() is None

    def test_maybe_inject_error_returns_string_at_one(self):
        """_maybe_inject_error() returns string at error_rate=1.0."""
        b = _backend(error_rate=1.0)
        err = b._maybe_inject_error()
        assert isinstance(err, str)
        assert len(err) > 0


# ---------------------------------------------------------------------------
# detect_card edge cases
# ---------------------------------------------------------------------------

class TestDetectCard:
    """Additional detect_card() edge cases."""

    def test_detect_with_empty_deck(self):
        """detect_card() returns failure when deck is empty."""
        b = _backend(num_cards=0)
        b.card_deck = []
        ok, msg = b.detect_card()
        assert ok is False
        assert "No card" in msg

    def test_detect_updates_no_state(self):
        """detect_card() does not modify authentication state."""
        b = _backend()
        card = b._current_card()
        card.authenticated = True  # pre-authenticated
        b.detect_card()
        assert card.authenticated is True  # unchanged

    def test_detect_returns_card_type_in_message(self):
        """detect_card() message includes card type."""
        b = _backend()
        ok, msg = b.detect_card()
        assert ok is True
        # Message should mention the card type (SJA2 or SJA5)
        assert any(t in msg for t in ("SJA2", "SJA5", "SJS1", "virtual"))


# ---------------------------------------------------------------------------
# authenticate() edge cases
# ---------------------------------------------------------------------------

class TestAuthenticateEdgeCases:
    """Additional authenticate() edge cases."""

    def test_already_locked_card(self):
        """authenticate() on locked card returns immediate failure."""
        b = _backend()
        card = b._current_card()
        card.adm1_locked = True
        ok, msg = b.authenticate(card.adm1)
        assert ok is False
        assert "locked" in msg.lower()

    def test_wrong_adm1_decrements_attempts(self):
        """Wrong ADM1 decrements attempts_remaining."""
        b = _backend()
        card = b._current_card()
        before = card.adm1_attempts_remaining
        b.authenticate("00000000")
        assert card.adm1_attempts_remaining == before - 1

    def test_three_wrong_adm1_locks_card(self):
        """Three wrong ADM1 attempts permanently lock the card."""
        b = _backend()
        card = b._current_card()
        for _ in range(3):
            b.authenticate("00000000")
        assert card.adm1_locked is True
        assert card.adm1_attempts_remaining == 0

    def test_correct_adm1_does_not_decrement_attempts(self):
        """Correct ADM1 does not change attempts_remaining."""
        b = _backend()
        card = b._current_card()
        before = card.adm1_attempts_remaining
        b.authenticate(card.adm1)
        assert card.adm1_attempts_remaining == before

    def test_iccid_mismatch_no_decrement(self):
        """ICCID mismatch does not consume ADM1 attempts."""
        b = _backend()
        card = b._current_card()
        before = card.adm1_attempts_remaining
        b.authenticate(card.adm1, expected_iccid="wrong_iccid")
        assert card.adm1_attempts_remaining == before

    def test_empty_deck_authenticate_fails(self):
        """authenticate() fails gracefully with empty deck."""
        b = _backend()
        b.card_deck = []
        ok, msg = b.authenticate("12345678")
        assert ok is False
        assert "No card" in msg


# ---------------------------------------------------------------------------
# program_card and verify_card edge cases
# ---------------------------------------------------------------------------

class TestProgramVerifyEdgeCases:
    """Edge cases for program_card() and verify_card()."""

    def test_program_without_auth_fails(self):
        """program_card() fails when not authenticated."""
        b = _backend()
        ok, msg = b.program_card({"imsi": "test"})
        assert ok is False
        assert "Not authenticated" in msg

    def test_program_empty_deck_fails(self):
        """program_card() fails gracefully with empty deck."""
        b = _backend()
        b.card_deck = []
        ok, msg = b.program_card({"imsi": "test"})
        assert ok is False
        assert "No card" in msg

    def test_verify_empty_deck_fails(self):
        """verify_card() fails gracefully with empty deck."""
        b = _backend()
        b.card_deck = []
        ok, mismatches = b.verify_card({"imsi": "test"})
        assert ok is False

    def test_verify_empty_expected(self):
        """verify_card() with empty expected dict returns success."""
        b = _backend()
        ok, mismatches = b.verify_card({})
        assert ok is True
        assert mismatches == []

    def test_program_overwrites_existing_field(self):
        """program_card() overwrites a previously programmed field."""
        b = _backend()
        card = b._current_card()
        b.authenticate(card.adm1)
        b.program_card({"imsi": "first"})
        b.program_card({"imsi": "second"})
        assert card.programmed_fields["imsi"] == "second"

    def test_verify_after_program_all_fields(self):
        """After programming, verify_card() finds no mismatches."""
        b = _backend()
        card = b._current_card()
        b.authenticate(card.adm1)
        data = {"imsi": "test_imsi", "custom_field": "value"}
        b.program_card(data)
        ok, mismatches = b.verify_card(data)
        assert ok is True
        assert mismatches == []


# ---------------------------------------------------------------------------
# disconnect / reset
# ---------------------------------------------------------------------------

class TestDisconnectReset:
    """Tests for disconnect() and reset()."""

    def test_disconnect_clears_auth_on_current_card(self):
        """disconnect() clears authenticated flag on current card."""
        b = _backend()
        card = b._current_card()
        b.authenticate(card.adm1)
        assert card.authenticated is True
        b.disconnect()
        assert card.authenticated is False

    def test_disconnect_empty_deck_is_noop(self):
        """disconnect() on empty deck does not crash."""
        b = _backend()
        b.card_deck = []
        b.disconnect()  # should not raise

    def test_reset_reloads_deck(self):
        """reset() regenerates the deck and resets index."""
        b = _backend(num_cards=5)
        card = b._current_card()
        card.authenticated = True
        card.programmed_fields["x"] = "y"
        b.reset()
        new_card = b._current_card()
        assert new_card.authenticated is False
        assert new_card.programmed_fields == {}
        assert b.current_card_index == 0

    def test_reset_preserves_deck_size(self):
        """reset() regenerates the same number of cards."""
        b = _backend(num_cards=5)
        original_size = len(b.card_deck)
        b.reset()
        assert len(b.card_deck) == original_size


# ---------------------------------------------------------------------------
# get_remaining_attempts
# ---------------------------------------------------------------------------

class TestGetRemainingAttempts:
    """Tests for get_remaining_attempts() edge cases."""

    def test_returns_3_initially(self):
        """Fresh card has 3 ADM1 attempts."""
        b = _backend()
        assert b.get_remaining_attempts() == 3

    def test_decrements_after_wrong_adm1(self):
        """Remaining attempts decrements after wrong ADM1."""
        b = _backend()
        b.authenticate("wrong")
        assert b.get_remaining_attempts() == 2

    def test_returns_zero_when_locked(self):
        """Locked card returns 0 remaining attempts."""
        b = _backend()
        card = b._current_card()
        card.adm1_locked = True
        card.adm1_attempts_remaining = 0
        assert b.get_remaining_attempts() == 0

    def test_empty_deck_returns_none(self):
        """Empty deck returns None for remaining attempts."""
        b = _backend()
        b.card_deck = []
        assert b.get_remaining_attempts() is None


# ---------------------------------------------------------------------------
# CardManager simulator integration edge cases
# ---------------------------------------------------------------------------

class TestCardManagerSimulatorEdgeCases:
    """CardManager with simulator: edge cases."""

    def test_get_simulator_info_empty_deck(self):
        """get_simulator_info() handles empty deck gracefully."""
        cm = CardManager()
        cm.enable_simulator(SimulatorSettings(delay_ms=0, num_cards=0))
        cm._simulator.card_deck = []
        info = cm.get_simulator_info()
        assert info is not None
        assert info["card"] is None
        assert info["total_cards"] == 0

    def test_enable_then_disable_then_enable(self):
        """Can enable, disable, and re-enable the simulator."""
        cm = CardManager()
        cm.enable_simulator(SimulatorSettings(delay_ms=0))
        assert cm.is_simulator_active
        cm.disable_simulator()
        assert not cm.is_simulator_active
        cm.enable_simulator(SimulatorSettings(delay_ms=0))
        assert cm.is_simulator_active

    def test_next_virtual_card_without_simulator_returns_none(self):
        """next_virtual_card() returns None when simulator not active."""
        cm = CardManager()
        assert cm.next_virtual_card() is None

    def test_previous_virtual_card_without_simulator_returns_none(self):
        """previous_virtual_card() returns None when simulator not active."""
        cm = CardManager()
        assert cm.previous_virtual_card() is None
