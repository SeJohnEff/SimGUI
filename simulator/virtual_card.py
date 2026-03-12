"""Virtual SIM card model for the simulator."""

from dataclasses import dataclass, field
from typing import Dict

# Public fields — readable without ADM1 authentication
PUBLIC_FIELDS = {
    "card_type", "iccid", "imsi", "acc", "msisdn", "mnc_length",
    "pin1", "puk1", "pin2", "puk2",
    "suci_protection_scheme", "suci_routing_indicator", "suci_hn_pubkey",
}

# Protected fields — require ADM1 authentication
PROTECTED_FIELDS = {
    "ki", "opc", "adm1",
    "kic1", "kid1", "kik1",
    "kic2", "kid2", "kik2",
    "kic3", "kid3", "kik3",
}


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
    pin2: str = ""
    puk2: str = ""
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
            "pin2": self.pin2,
            "puk2": self.puk2,
            "msisdn": self.msisdn,
            "mnc_length": self.mnc_length,
        }
        if self.card_type == "SJA5":
            data["suci_protection_scheme"] = self.suci_protection_scheme
            data["suci_routing_indicator"] = self.suci_routing_indicator
            data["suci_hn_pubkey"] = self.suci_hn_pubkey
        data.update(self.programmed_fields)
        return data

    def get_public_data(self) -> Dict[str, str]:
        """Return fields readable without authentication."""
        all_data = self.get_current_data()
        return {k: v for k, v in all_data.items() if k in PUBLIC_FIELDS}

    def get_protected_data(self) -> Dict[str, str]:
        """Return fields that require ADM1 authentication."""
        all_data = self.get_current_data()
        return {k: v for k, v in all_data.items() if k in PROTECTED_FIELDS}

    def reset(self):
        """Clear programming and auth state."""
        self.programmed_fields.clear()
        self.authenticated = False
        self.adm1_attempts_remaining = 3
        self.adm1_locked = False
