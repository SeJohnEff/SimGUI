"""Canonical per-card-type writable-field schema.

One definition of *which identity fields a card type is programmed with*, read
by every surface that must agree on it:

* the **GUI** (``widgets/program_sim_panel``) — which fields to show/enable and
  which to hide, so "what is shown is what is programmed";
* **programming** (``managers/card_manager`` gialersim routing) — the exact
  field set to write, with no delta;
* **verification** — which fields are confirmed by read-back vs. by USIM
  ``AUTHENTICATE``.

Because all three read the same object, they cannot drift. This mirrors the
capability schema in ``card_profiles/capabilities.py`` and the field tables in
``docs/reference/state-machine.md`` / ``docs/GIALERSIM_PROGRAMMING.md``.

Scope note (gialersim): the verified GRSIMWrite recipe writes ICCID, IMSI, Ki,
OPc and ACC only. SPN/FPLMN/HNET_PUBKEY are **excluded** — they are not part of
the verified APDU sequence, so the GUI does not offer them for a gialersim card.
(The GRSIMWrite trace does contain SPN ``6F46`` / FPLMN ``6F7B`` writes after
the DF switch on non-ADM files; adding them is a safe *separate* change, not
this one.)
"""

from dataclasses import dataclass
from typing import Tuple

from card_profiles.base import normalize_card_type


@dataclass(frozen=True)
class FieldSchema:
    """Which fields a card type is programmed with, and how each is verified.

    Attributes:
        written: fields the programmer writes to the card.
        hardcoded: fields whose value is fixed/built-in and not operator-supplied
            (e.g. gialersim ADM1 — presented automatically by the native path).
        verify_readback: written fields confirmable by reading them back.
        verify_authenticate: written fields confirmable only by USIM
            ``AUTHENTICATE`` (READ=NEVER keys — a ``9000`` write proves nothing).
        excluded: fields deliberately NOT offered for this card type (not in the
            verified recipe); the GUI hides them so shown == written.
    """
    written: Tuple[str, ...] = ()
    hardcoded: Tuple[str, ...] = ()
    verify_readback: Tuple[str, ...] = ()
    verify_authenticate: Tuple[str, ...] = ()
    excluded: Tuple[str, ...] = ()

    @property
    def required(self) -> Tuple[str, ...]:
        """Fields that must be present to program (everything verifiable)."""
        return self.verify_readback + self.verify_authenticate


# The verified gialersim recipe (see managers/gialersim.py and
# docs/GIALERSIM_PROGRAMMING.md). ADM1 is the fixed family key, presented by the
# native path — never operator-supplied. ACC defaults to 0001 when absent.
GIALERSIM_SCHEMA = FieldSchema(
    written=("ICCID", "IMSI", "Ki", "OPc", "ACC"),
    hardcoded=("ADM1",),
    verify_readback=("ICCID", "IMSI"),
    verify_authenticate=("Ki", "OPc"),
    excluded=("SPN", "FPLMN", "HNET_PUBKEY", "SUCI"),
)

# Non-gialersim (sysmocom SJA*/MAGIC/UNKNOWN) default: no per-type field hiding.
# The pySim paths are authoritative for what they write; this schema only tells
# the GUI not to hide anything, preserving today's behaviour for those cards.
DEFAULT_SCHEMA = FieldSchema(excluded=())


def fields_for(card_type) -> FieldSchema:
    """Return the :class:`FieldSchema` for *card_type* (enum/name/string)."""
    token = normalize_card_type(card_type)
    if token == "GIALERSIM":
        return GIALERSIM_SCHEMA
    return DEFAULT_SCHEMA
