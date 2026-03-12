"""Comprehensive tests for the SIM programmer simulator."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from simulator.virtual_card import VirtualCard
from simulator.card_deck import generate_deck
from simulator.simulator_backend import SimulatorBackend
from simulator.settings import SimulatorSettings
from managers.card_manager import CardManager


# ---------------------------------------------------------------------------
# TestVirtualCard
# ---------------------------------------------------------------------------

class TestVirtualCard:
    def test_creation(self):
        card = VirtualCard(
            card_type="SJA2", iccid="1234", imsi="5678",
            ki="A" * 32, opc="B" * 32, adm1="60969281",
        )
        assert card.card_type == "SJA2"
        assert card.adm1_attempts_remaining == 3
        assert card.authenticated is False
        assert card.programmed_fields == {}

    def test_get_current_data_no_overrides(self):
        card = VirtualCard(
            card_type="SJA2", iccid="1234", imsi="5678",
            ki="A" * 32, opc="B" * 32, adm1="60969281",
        )
        data = card.get_current_data()
        assert data["iccid"] == "1234"
        assert data["imsi"] == "5678"
        assert data["ki"] == "A" * 32

    def test_get_current_data_with_overrides(self):
        card = VirtualCard(
            card_type="SJA2", iccid="1234", imsi="5678",
            ki="A" * 32, opc="B" * 32, adm1="60969281",
        )
        card.programmed_fields["imsi"] = "9999"
        data = card.get_current_data()
        assert data["imsi"] == "9999"  # overridden
        assert data["iccid"] == "1234"  # original

    def test_get_current_data_sja5_fields(self):
        card = VirtualCard(
            card_type="SJA5", iccid="1234", imsi="5678",
            ki="A" * 32, opc="B" * 32, adm1="60969281",
            suci_protection_scheme="profile_b",
            suci_routing_indicator="0xff",
            suci_hn_pubkey="C" * 64,
        )
        data = card.get_current_data()
        assert data["suci_protection_scheme"] == "profile_b"
        assert data["suci_hn_pubkey"] == "C" * 64

    def test_reset(self):
        card = VirtualCard(
            card_type="SJA2", iccid="1234", imsi="5678",
            ki="A" * 32, opc="B" * 32, adm1="60969281",
        )
        card.authenticated = True
        card.adm1_attempts_remaining = 1
        card.adm1_locked = True
        card.programmed_fields["imsi"] = "9999"
        card.reset()
        assert card.authenticated is False
        assert card.adm1_attempts_remaining == 3
        assert card.adm1_locked is False
        assert card.programmed_fields == {}


# ---------------------------------------------------------------------------
# TestCardDeck
# ---------------------------------------------------------------------------

class TestCardDeck:
    def test_default_count(self):
        deck = generate_deck()
        assert len(deck) == 10

    def test_custom_count(self):
        deck = generate_deck(count=5)
        assert len(deck) == 5

    def test_unique_iccids(self):
        deck = generate_deck()
        iccids = [c.iccid for c in deck]
        assert len(set(iccids)) == len(iccids)

    def test_unique_imsis(self):
        deck = generate_deck()
        imsis = [c.imsi for c in deck]
        assert len(set(imsis)) == len(imsis)

    def test_unique_ki(self):
        deck = generate_deck()
        kis = [c.ki for c in deck]
        assert len(set(kis)) == len(kis)

    def test_card_type_mix(self):
        deck = generate_deck(count=10)
        types = [c.card_type for c in deck]
        assert "SJA2" in types
        assert "SJA5" in types

    def test_sja5_has_suci_fields(self):
        deck = generate_deck(count=10)
        sja5_cards = [c for c in deck if c.card_type == "SJA5"]
        assert len(sja5_cards) > 0
        for card in sja5_cards:
            assert card.suci_protection_scheme != ""
            assert card.suci_hn_pubkey != ""

    def test_deterministic(self):
        deck1 = generate_deck(count=5)
        deck2 = generate_deck(count=5)
        for c1, c2 in zip(deck1, deck2):
            assert c1.ki == c2.ki
            assert c1.opc == c2.opc


# ---------------------------------------------------------------------------
# TestSimulatorBackend
# ---------------------------------------------------------------------------

class TestSimulatorBackend:
    @pytest.fixture
    def backend(self):
        settings = SimulatorSettings(delay_ms=0, error_rate=0.0, num_cards=5)
        return SimulatorBackend(settings)

    def test_detect_card_success(self, backend):
        ok, msg = backend.detect_card()
        assert ok is True
        assert "virtual" in msg.lower()

    def test_detect_card_empty_deck(self):
        settings = SimulatorSettings(delay_ms=0, num_cards=0)
        b = SimulatorBackend(settings)
        b.card_deck = []
        ok, msg = b.detect_card()
        assert ok is False
        assert "No card" in msg

    def test_authenticate_correct_adm1(self, backend):
        card = backend._current_card()
        ok, msg = backend.authenticate(card.adm1)
        assert ok is True
        assert card.authenticated is True

    def test_authenticate_wrong_adm1(self, backend):
        ok, msg = backend.authenticate("00000000")
        assert ok is False
        card = backend._current_card()
        assert card.adm1_attempts_remaining == 2
        assert card.authenticated is False

    def test_authenticate_empty_adm1(self, backend):
        ok, msg = backend.authenticate("")
        assert ok is False

    def test_authenticate_lockout(self, backend):
        card = backend._current_card()
        for _ in range(3):
            backend.authenticate("00000000")
        assert card.adm1_locked is True
        assert card.adm1_attempts_remaining == 0
        # Even correct ADM1 fails after lockout
        ok, msg = backend.authenticate(card.adm1)
        assert ok is False
        assert "locked" in msg.lower()

    def test_program_card_success(self, backend):
        card = backend._current_card()
        backend.authenticate(card.adm1)
        ok, msg = backend.program_card({"imsi": "999"})
        assert ok is True
        assert card.programmed_fields["imsi"] == "999"

    def test_program_card_unauthenticated(self, backend):
        ok, msg = backend.program_card({"imsi": "999"})
        assert ok is False
        assert "Not authenticated" in msg

    def test_verify_card_match(self, backend):
        card = backend._current_card()
        backend.authenticate(card.adm1)
        backend.program_card({"imsi": "test_imsi"})
        ok, mismatches = backend.verify_card({"imsi": "test_imsi"})
        assert ok is True
        assert mismatches == []

    def test_verify_card_mismatch(self, backend):
        card = backend._current_card()
        ok, mismatches = backend.verify_card({"imsi": "wrong_value"})
        assert ok is False
        assert len(mismatches) > 0

    def test_read_card_data(self, backend):
        data = backend.read_card_data()
        assert data is not None
        assert "iccid" in data
        assert "imsi" in data

    def test_get_remaining_attempts(self, backend):
        attempts = backend.get_remaining_attempts()
        assert attempts == 3

    def test_next_card_wraps(self, backend):
        total = len(backend.card_deck)
        for _ in range(total):
            backend.next_card()
        assert backend.current_card_index == 0

    def test_previous_card_wraps(self, backend):
        idx, total = backend.previous_card()
        assert idx == total - 1

    def test_next_previous_cycling(self, backend):
        start = backend.current_card_index
        backend.next_card()
        backend.previous_card()
        assert backend.current_card_index == start

    def test_disconnect_clears_auth(self, backend):
        card = backend._current_card()
        backend.authenticate(card.adm1)
        assert card.authenticated is True
        backend.disconnect()
        assert card.authenticated is False

    def test_reset_regenerates_deck(self, backend):
        old_iccid = backend._current_card().iccid
        backend._current_card().programmed_fields["x"] = "y"
        backend.reset()
        # Deck is fresh — same deterministic iccid but no programmed fields
        assert backend._current_card().iccid == old_iccid
        assert backend._current_card().programmed_fields == {}
        assert backend.current_card_index == 0

    def test_error_injection_always_fails(self):
        settings = SimulatorSettings(delay_ms=0, error_rate=1.0, num_cards=5)
        b = SimulatorBackend(settings)
        ok, msg = b.detect_card()
        assert ok is False
        assert "Simulated" in msg

    def test_error_injection_never_fails(self):
        settings = SimulatorSettings(delay_ms=0, error_rate=0.0, num_cards=5)
        b = SimulatorBackend(settings)
        # Run many times — should never fail
        for _ in range(20):
            ok, _ = b.detect_card()
            assert ok is True


# ---------------------------------------------------------------------------
# TestCardManagerSimulator
# ---------------------------------------------------------------------------

class TestCardManagerSimulator:
    @pytest.fixture
    def mgr(self):
        return CardManager()

    def test_enable_simulator(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        assert mgr.is_simulator_active is True

    def test_disable_simulator(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        mgr.disable_simulator()
        assert mgr.is_simulator_active is False

    def test_is_simulator_active_default(self, mgr):
        assert mgr.is_simulator_active is False

    def test_detect_delegates_to_simulator(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        ok, msg = mgr.detect_card()
        assert ok is True
        assert "virtual" in msg.lower()

    def test_authenticate_delegates_to_simulator(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        card = mgr._simulator._current_card()
        ok, msg = mgr.authenticate(card.adm1)
        assert ok is True

    def test_program_delegates_to_simulator(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        card = mgr._simulator._current_card()
        mgr.authenticate(card.adm1)
        ok, msg = mgr.program_card({"imsi": "test"})
        assert ok is True

    def test_verify_delegates_to_simulator(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        card = mgr._simulator._current_card()
        mgr.authenticate(card.adm1)
        mgr.program_card({"imsi": "test"})
        ok, mismatches = mgr.verify_card({"imsi": "test"})
        assert ok is True

    def test_read_delegates_to_simulator(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        data = mgr.read_card_data()
        assert data is not None

    def test_remaining_attempts_delegates(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        assert mgr.get_remaining_attempts() == 3

    def test_disconnect_delegates(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        card = mgr._simulator._current_card()
        mgr.authenticate(card.adm1)
        mgr.disconnect()
        assert card.authenticated is False

    def test_next_virtual_card(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        result = mgr.next_virtual_card()
        assert result is not None
        assert result[0] == 1

    def test_previous_virtual_card(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        result = mgr.previous_virtual_card()
        assert result is not None

    def test_virtual_card_noop_without_simulator(self, mgr):
        assert mgr.next_virtual_card() is None
        assert mgr.previous_virtual_card() is None

    def test_get_simulator_info(self, mgr):
        mgr.enable_simulator(SimulatorSettings(delay_ms=0))
        info = mgr.get_simulator_info()
        assert info is not None
        assert "current_index" in info
        assert "total_cards" in info
        assert info["card"] is not None

    def test_get_simulator_info_without_simulator(self, mgr):
        assert mgr.get_simulator_info() is None

    def test_operations_use_cli_when_disabled(self, mgr):
        """Without simulator, operations fall back to CLI path (which is None in tests)."""
        ok, msg = mgr.detect_card()
        assert ok is False  # No CLI tool available in test env
