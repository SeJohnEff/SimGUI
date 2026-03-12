"""Virtual SIM card model for the simulator."""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class VirtualCard:
    """In-memory representation of a SIM card."""

    # Identity
    card_type: str  # "SJA2" or "SJA5"
    iccid: str
    imsi: str

    # Keys
    ki: str
    opc: str
    adm1: str

    # State
    adm1_attempts_remaining: int = 3
    adm1_locked: bool = False
    authenticated: bool = False

    # Additional fields
    acc: str = "0001"
    pin1: str = "1234"
    puk1: str = "12345678"
    msisdn: str = ""
    mnc_length: str = "02"

    # SUCI fields (SJA5 only)
    suci_protection_scheme: str = ""
    suci_routing_indicator: str = ""
    suci_hn_pubkey: str = ""

    # Programming history
    programmed_fields: Dict[str, str] = field(default_factory=dict)

    def get_current_data(self) -> Dict[str, str]:
        """Return original fields merged with programmed overrides."""
        data = {
            "card_type": self.card_type,
            "iccid": self.iccid,
            "imsi": self.imsi,
            "ki": self.ki,
            "opc": self.opc,
            "acc": self.acc,
            "pin1": self.pin1,
            "puk1": self.puk1,
            "msisdn": self.msisdn,
            "mnc_length": self.mnc_length,
        }
        if self.card_type == "SJA5":
            data["suci_protection_scheme"] = self.suci_protection_scheme
            data["suci_routing_indicator"] = self.suci_routing_indicator
            data["suci_hn_pubkey"] = self.suci_hn_pubkey
        data.update(self.programmed_fields)
        return data

    def reset(self):
        """Clear programming and auth state."""
        self.programmed_fields.clear()
        self.authenticated = False
        self.adm1_attempts_remaining = 3
        self.adm1_locked = False
