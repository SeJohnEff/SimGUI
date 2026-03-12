"""Card deck generation for the simulator."""

import csv
import hashlib
import logging
from typing import List

from simulator.virtual_card import VirtualCard

logger = logging.getLogger(__name__)


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


def load_from_csv(csv_path: str) -> List[VirtualCard]:
    """Load virtual cards from a CSV file.

    Expected columns: IMSI, ICCID, ACC, PIN1, PUK1, PIN2, PUK2,
    Ki, OPC, ADM1 (plus optional KIC/KID/KIK columns which are ignored).
    """
    cards: List[VirtualCard] = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            card = VirtualCard(
                card_type="SJA5",
                iccid=row.get("ICCID", ""),
                imsi=row.get("IMSI", ""),
                ki=row.get("Ki", ""),
                opc=row.get("OPC", ""),
                adm1=row.get("ADM1", ""),
                acc=row.get("ACC", "0001"),
                pin1=row.get("PIN1", "1234"),
                puk1=row.get("PUK1", "12345678"),
                pin2=row.get("PIN2", ""),
                puk2=row.get("PUK2", ""),
            )
            cards.append(card)
    logger.info("Loaded %d cards from %s", len(cards), csv_path)
    return cards
