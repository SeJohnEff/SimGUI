"""Tests for the card-type capability schema (card_profiles/capabilities.py).

The schema is the single source of truth for UI-facing per-card-type behaviour
(SUCI support, hardcoded ADM1). These tests lock the rules that the UI renders
from, so a scattered ``if gialersim`` check can never drift from them.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from card_profiles import CardCapabilities, DEFAULT_CAPABILITIES, capabilities_for
from card_profiles.base import normalize_card_type
from managers.card_manager import CardType


class TestNormalize:
    def test_enum_name_string_all_agree(self):
        assert (normalize_card_type(CardType.GIALERSIM)
                == normalize_card_type("gialersim")
                == normalize_card_type("GIALERSIM")
                == "GIALERSIM")

    def test_strips_separators(self):
        assert normalize_card_type("sysmoISIM-SJA5") == "SYSMOISIMSJA5"


class TestGialerSimCapabilities:
    def test_gialersim_hardcoded_adm_and_no_suci(self):
        for ct in (CardType.GIALERSIM, "gialersim", "GIALERSIM"):
            caps = capabilities_for(ct)
            assert caps.adm1_hardcoded is True
            assert caps.supports_suci is False
            assert caps.programming == "native"


class TestSysmocomCapabilities:
    def test_sja5_editable_adm_and_suci(self):
        for ct in (CardType.SJA5, CardType.SJA2, "sysmoISIM-SJA5"):
            caps = capabilities_for(ct)
            assert caps.adm1_hardcoded is False
            assert caps.supports_suci is True

    def test_unknown_sja_family_falls_back_to_sja5(self):
        caps = capabilities_for("SJA9-future")
        assert caps.adm1_hardcoded is False
        assert caps.supports_suci is True


class TestDefault:
    def test_unknown_type_is_conservative_default(self):
        caps = capabilities_for(CardType.UNKNOWN)
        assert caps == DEFAULT_CAPABILITIES
        # Never silently hide a capability we're unsure about.
        assert caps.adm1_hardcoded is False
        assert caps.supports_suci is True

    def test_garbage_input_is_default(self):
        assert capabilities_for("totally-unknown-thing") == DEFAULT_CAPABILITIES

    def test_capabilities_are_immutable(self):
        import dataclasses
        import pytest
        caps = capabilities_for(CardType.GIALERSIM)
        with pytest.raises(dataclasses.FrozenInstanceError):
            caps.supports_suci = True
