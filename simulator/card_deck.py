"""Card deck generation for the simulator."""

import hashlib
from typing import List

from simulator.virtual_card import VirtualCard


def generate_deck(count: int = 10) -> List[VirtualCard]:
    """Generate a deck of virtual SIM cards with realistic sequential data."""
    cards: List[VirtualCard] = []
    for i in range(count):
        idx = i + 1
        # Determine card type: first 70% SJA2, rest SJA5
        sja5_start = max(1, int(count * 0.7) + 1)
        card_type = "SJA5" if idx >= sja5_start else "SJA2"

        iccid = f"8988211000000000{idx:03d}"
        imsi = f"001010000000{idx:04d}"
        adm1 = f"{60969280 + idx}"

        # Deterministic Ki and OPc from index
        ki = hashlib.sha256(f"ki-{idx}".encode()).hexdigest()[:32]
        opc = hashlib.sha256(f"opc-{idx}".encode()).hexdigest()[:32]

        card = VirtualCard(
            card_type=card_type,
            iccid=iccid,
            imsi=imsi,
            ki=ki,
            opc=opc,
            adm1=adm1,
        )

        if card_type == "SJA5":
            card.suci_protection_scheme = "profile_b"
            card.suci_routing_indicator = "0xff"
            card.suci_hn_pubkey = hashlib.sha256(
                f"hn-pubkey-{idx}".encode()
            ).hexdigest()[:64]

        cards.append(card)
    return cards
