"""Card-type capability schema — the single source of truth for UI-facing
per-card-type behaviour.

The UI must never re-derive "does this card support SUCI?" or "is the ADM key
hardcoded?" with scattered ``if gialersim`` checks — those rules live here, once,
as a declarative table keyed by card type. Tabs/widgets read a
:class:`CardCapabilities` for the detected card type and render accordingly
(schema-driven surfaces; see the architecture notes in CLAUDE.md).

This mirrors the per-card-type table in ``docs/reference/state-machine.md``.
It describes *capabilities* only — the authoritative programming/auth routing
still lives in ``managers/card_manager.py`` (``program_card``) and the actual
gialersim ADM key/APDU recipe in ``managers/gialersim.py``.
"""

from dataclasses import dataclass

from card_profiles.base import normalize_card_type


@dataclass(frozen=True)
class CardCapabilities:
    """Declarative, UI-facing capabilities of a card type.

    Attributes:
        adm1_hardcoded: The ADM key is fixed/built-in and presented
            automatically, so the operator never supplies it. The ADM1 field is
            shown greyed with a "Hardcoded" hint and its value is not used.
            (gialersim: the fixed family key at ref 0x0C — see
            ``managers/gialersim.py``.)
        supports_suci: The card can perform 5G SUCI concealment. When False the
            SUCI control is forced off and disabled, and programming never
            enables SUCI regardless of CSV/default.
        programming: How the card is programmed — documentation of the routing
            that ``CardManager.program_card`` performs. Not a switch the UI
            reads; the router is authoritative.
    """
    adm1_hardcoded: bool = False
    supports_suci: bool = True
    programming: str = "pysim"


# Keyed by normalized card-type token (see ``normalize_card_type``).
# Aligned with the CardType table in docs/reference/state-machine.md.
_CAPABILITIES = {
    "GIALERSIM": CardCapabilities(
        adm1_hardcoded=True, supports_suci=False, programming="native"),
    "SJA5": CardCapabilities(
        adm1_hardcoded=False, supports_suci=True, programming="pysim-shell"),
    "SJA2": CardCapabilities(
        adm1_hardcoded=False, supports_suci=True, programming="pysim-shell"),
    "MAGIC": CardCapabilities(
        adm1_hardcoded=False, supports_suci=True, programming="pysim-shell"),
}

# Conservative fallback for UNKNOWN / unrecognised types: a normal editable
# ADM1 field and SUCI available (never silently hide a capability we're unsure
# about; the operator stays in control).
DEFAULT_CAPABILITIES = CardCapabilities()


def capabilities_for(card_type) -> CardCapabilities:
    """Return the :class:`CardCapabilities` for *card_type* (enum/name/string).

    Falls back to :data:`DEFAULT_CAPABILITIES` for anything not in the table,
    including the sysmocom ``SJA*`` family beyond the named entries.
    """
    token = normalize_card_type(card_type)
    if token in _CAPABILITIES:
        return _CAPABILITIES[token]
    if token.startswith("SJA") or "SYSMO" in token:
        return _CAPABILITIES["SJA5"]
    return DEFAULT_CAPABILITIES
