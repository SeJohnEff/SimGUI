"""SIM Standard loader — reads ``sim-standard.json`` from network shares.

Provides the single source of truth for PLMN configuration, site
register, SIM types, FPLMN lists, numbering rules, and allocation
tracking.  Falls back to built-in defaults (matching Teleaura v2.1)
when no standard file is found on any share.

The standard file is placed at the root of each network share:

    /mnt/nas-sim/sim-standard.json

The app loads and merges standards from all connected shares on
startup and when shares are (re)connected.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

STANDARD_FILENAME = "sim-standard.json"
SUPPORTED_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PLMNConfig:
    """One PLMN entry (e.g. 999/88)."""
    mcc_mnc: str           # e.g. "99988"
    mcc: str               # e.g. "999"
    mnc: str               # e.g. "88"
    mnc_length: int         # 2 or 3
    purpose: str
    issuer_id: str          # e.g. "988" for production, "989" for lab
    status: str             # "active" or "reserved"


@dataclass
class SiteConfig:
    """One site from the register."""
    site_id: str            # e.g. "0001"
    code: str               # e.g. "uk1"
    country: str            # e.g. "United Kingdom"
    country_code_e164: str  # e.g. "44"
    description: str
    status: str             # "active" or "reserved"


@dataclass
class SIMTypeConfig:
    """One SIM type entry."""
    type_digit: str         # e.g. "0"
    name: str               # e.g. "USIM"
    description: str


@dataclass
class AllocationEntry:
    """One allocation range within a site."""
    site_id: str
    sim_type: str
    customer: str
    range_start: int
    range_end: int
    notes: str = ""


@dataclass
class SIMStandard:
    """Complete parsed SIM standard configuration."""

    # Document metadata
    title: str = ""
    revision: str = ""
    date: str = ""
    scope: str = ""

    # PLMNs keyed by mcc_mnc string
    plmns: dict[str, PLMNConfig] = field(default_factory=dict)
    default_plmn: str = "99988"

    # Site register keyed by SSSS
    sites: dict[str, SiteConfig] = field(default_factory=dict)

    # SIM types keyed by T digit
    sim_types: dict[str, SIMTypeConfig] = field(default_factory=dict)

    # FPLMN lists keyed by country name
    fplmn_by_country: dict[str, list[str]] = field(default_factory=dict)

    # Profile defaults
    default_li: str = "EN"
    default_hplmn: str = "99988"
    default_ehplmn: list[str] = field(default_factory=lambda: ["99988", "99989"])
    default_spn: str = ""
    adm1_empty_cards: str = "3838383838383838"

    # Key generation config
    key_method: str = "random"
    key_note: str = ""

    # SPN / LI canonical lists (for dropdowns)
    spn_values: list[str] = field(default_factory=list)
    li_values: list[str] = field(default_factory=list)

    # Allocation register
    allocations: dict[str, list[AllocationEntry]] = field(default_factory=dict)

    # Source tracking
    loaded_from: list[str] = field(default_factory=list)

    # --- Convenience lookups -------------------------------------------------

    def get_site(self, site_id: str) -> Optional[SiteConfig]:
        """Look up a site by its 4-digit ID."""
        return self.sites.get(site_id)

    def get_site_by_code(self, code: str) -> Optional[SiteConfig]:
        """Look up a site by its DC naming code (e.g. 'uk1')."""
        for site in self.sites.values():
            if site.code == code:
                return site
        return None

    def get_plmn(self, mcc_mnc: str) -> Optional[PLMNConfig]:
        """Look up a PLMN by MCC+MNC string."""
        return self.plmns.get(mcc_mnc)

    def get_default_plmn(self) -> Optional[PLMNConfig]:
        """Return the default PLMN config."""
        return self.plmns.get(self.default_plmn)

    def get_fplmn_for_site(self, site_id: str) -> str:
        """Return semicolon-separated FPLMN string for a site's country."""
        site = self.sites.get(site_id)
        if site:
            fplmns = self.fplmn_by_country.get(site.country, [])
            return ";".join(fplmns)
        return ""

    def get_issuer_id(self, mcc_mnc: str) -> str:
        """Return the 3-digit issuer ID for a PLMN."""
        plmn = self.plmns.get(mcc_mnc)
        return plmn.issuer_id if plmn else "988"

    def get_country_code(self, site_id: str) -> str:
        """Return the E.164 country code for a site (e.g. '44')."""
        site = self.sites.get(site_id)
        return site.country_code_e164 if site else "00"

    def get_next_sequence(self, site_code: str, sim_type: str) -> int:
        """Find the next available sequence number from allocations.

        Returns the sequence number after the highest allocated range
        for the given site code and SIM type.  Returns 1 if no
        allocations exist yet.
        """
        allocs = self.allocations.get(site_code, [])
        max_end = 0
        for a in allocs:
            if a.sim_type == sim_type and a.range_end > max_end:
                max_end = a.range_end
        return max_end + 1 if max_end > 0 else 1

    def get_active_sites(self) -> list[SiteConfig]:
        """Return only active sites (not reserved)."""
        return [s for s in self.sites.values()
                if s.status.lower() == "active"]

    def get_active_plmns(self) -> list[PLMNConfig]:
        """Return only active PLMNs."""
        return [p for p in self.plmns.values()
                if p.status.lower() == "active"]

    @property
    def is_loaded(self) -> bool:
        """True if a standard file has been loaded (vs. pure defaults)."""
        return bool(self.loaded_from)


# ---------------------------------------------------------------------------
# Built-in defaults (Teleaura v2.1)
# ---------------------------------------------------------------------------

def _builtin_standard() -> SIMStandard:
    """Return a SIMStandard populated with hardcoded Teleaura v2.1 defaults.

    Used as fallback when no sim-standard.json is found on any share.
    """
    std = SIMStandard(
        title="Teleaura SIM & PLMN Numbering Standard",
        revision="2.1 (built-in)",
        scope="Teleaura UK and all sub-networks",
    )

    std.plmns = {
        "99988": PLMNConfig(
            mcc_mnc="99988", mcc="999", mnc="88", mnc_length=2,
            purpose="Teleaura Production Networks",
            issuer_id="988", status="active",
        ),
        "99989": PLMNConfig(
            mcc_mnc="99989", mcc="999", mnc="89", mnc_length=2,
            purpose="Teleaura Lab / Test Networks",
            issuer_id="989", status="active",
        ),
    }
    std.default_plmn = "99988"

    std.sites = {
        "0001": SiteConfig("0001", "uk1", "United Kingdom", "44",
                           "Primary UK data centre / lab", "active"),
        "0002": SiteConfig("0002", "se1", "Sweden", "46",
                           "Primary Sweden data centre", "active"),
        "0003": SiteConfig("0003", "se2", "Sweden", "46",
                           "Sweden DR site", "active"),
        "0004": SiteConfig("0004", "au1", "Australia", "61",
                           "Primary Australia site", "reserved"),
    }

    std.sim_types = {
        "0": SIMTypeConfig("0", "USIM", "Standard physical SIM (2FF/3FF/4FF)"),
        "1": SIMTypeConfig("1", "USIM+SUCI", "5G SUCI privacy SIM (SYSMOCOM-sourced)"),
        "2": SIMTypeConfig("2", "eSIM", "eUICC remote provisioning (MFF2)"),
        "9": SIMTypeConfig("9", "Test/Dev", "Lab and development cards"),
    }

    std.fplmn_by_country = {
        "United Kingdom": ["23415", "23410", "23420", "23430"],
        "Sweden": ["24007", "24024", "24001", "24008", "24002"],
    }

    std.adm1_empty_cards = "3838383838383838"
    std.key_method = "random"
    std.key_note = (
        "Ki and OPc are generated as cryptographically random 128-bit values. "
        "Future option: derive OPc from a master OP key using MILENAGE."
    )

    std.spn_values = ["BOLIDEN", "TELEAURA", "FISKARHEDEN"]
    std.li_values = ["EN", "SV", "FI"]

    return std


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------

def _parse_standard(data: dict, source_path: str) -> SIMStandard:
    """Parse a sim-standard.json dict into a SIMStandard."""
    std = SIMStandard()
    std.loaded_from = [source_path]

    # Document metadata
    doc = data.get("document", {})
    std.title = doc.get("title", "")
    std.revision = doc.get("revision", "")
    std.date = doc.get("date", "")
    std.scope = doc.get("scope", "")

    # PLMNs
    for mcc_mnc, info in data.get("plmns", {}).items():
        std.plmns[mcc_mnc] = PLMNConfig(
            mcc_mnc=mcc_mnc,
            mcc=info.get("mcc", mcc_mnc[:3]),
            mnc=info.get("mnc", mcc_mnc[3:]),
            mnc_length=int(info.get("mnc_length", 2)),
            purpose=info.get("purpose", ""),
            issuer_id=info.get("issuer_id", "988"),
            status=info.get("status", "active"),
        )
    std.default_plmn = data.get("default_plmn", "99988")

    # Sites
    for site_id, info in data.get("sites", {}).items():
        std.sites[site_id] = SiteConfig(
            site_id=site_id,
            code=info.get("code", ""),
            country=info.get("country", ""),
            country_code_e164=info.get("country_code_e164", "00"),
            description=info.get("description", ""),
            status=info.get("status", "active"),
        )

    # SIM types
    for t_digit, info in data.get("sim_types", {}).items():
        std.sim_types[t_digit] = SIMTypeConfig(
            type_digit=t_digit,
            name=info.get("name", ""),
            description=info.get("description", ""),
        )

    # FPLMN
    for country, plmns in data.get("fplmn_by_country", {}).items():
        if isinstance(plmns, list):
            std.fplmn_by_country[country] = plmns
        elif isinstance(plmns, str):
            std.fplmn_by_country[country] = [p.strip() for p in plmns.split(";")]

    # Profile defaults
    profile = data.get("sim_profile_defaults", {})
    std.default_li = profile.get("li", "EN")
    std.default_hplmn = profile.get("hplmn", "99988")
    std.default_ehplmn = profile.get("ehplmn", ["99988", "99989"])
    std.default_spn = profile.get("spn", "")
    std.adm1_empty_cards = profile.get("adm1_empty_cards", "3838383838383838")

    # Key generation
    keygen = data.get("key_generation", {})
    std.key_method = keygen.get("method", "random")
    std.key_note = keygen.get("note", "")

    # SPN / LI lists
    std.spn_values = data.get("spn_values", [])
    std.li_values = data.get("li_values", [])

    # Allocations
    for site_code, entries in data.get("allocations", {}).items():
        alloc_list = []
        for entry in entries:
            alloc_list.append(AllocationEntry(
                site_id=entry.get("site_id", ""),
                sim_type=entry.get("sim_type", "0"),
                customer=entry.get("customer", ""),
                range_start=int(entry.get("range_start", 0)),
                range_end=int(entry.get("range_end", 0)),
                notes=entry.get("notes", ""),
            ))
        std.allocations[site_code] = alloc_list

    return std


def _merge_standards(base: SIMStandard, overlay: SIMStandard) -> SIMStandard:
    """Merge overlay into base (overlay wins on conflicts)."""
    # PLMNs: overlay wins
    for k, v in overlay.plmns.items():
        base.plmns[k] = v
    if overlay.default_plmn:
        base.default_plmn = overlay.default_plmn

    # Sites: overlay wins
    for k, v in overlay.sites.items():
        base.sites[k] = v

    # SIM types: overlay wins
    for k, v in overlay.sim_types.items():
        base.sim_types[k] = v

    # FPLMN: overlay wins per country
    for k, v in overlay.fplmn_by_country.items():
        base.fplmn_by_country[k] = v

    # SPN/LI: merge unique
    seen_spn = {s.upper() for s in base.spn_values}
    for s in overlay.spn_values:
        if s.upper() not in seen_spn:
            base.spn_values.append(s)
            seen_spn.add(s.upper())

    seen_li = set(base.li_values)
    for li in overlay.li_values:
        if li not in seen_li:
            base.li_values.append(li)
            seen_li.add(li)

    # Allocations: merge by site code
    for site_code, entries in overlay.allocations.items():
        if site_code not in base.allocations:
            base.allocations[site_code] = []
        base.allocations[site_code].extend(entries)

    # Profile defaults: overlay wins
    if overlay.adm1_empty_cards:
        base.adm1_empty_cards = overlay.adm1_empty_cards
    if overlay.key_method:
        base.key_method = overlay.key_method
    if overlay.key_note:
        base.key_note = overlay.key_note

    # Metadata
    if overlay.title:
        base.title = overlay.title
    if overlay.revision:
        base.revision = overlay.revision

    base.loaded_from.extend(overlay.loaded_from)
    return base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_standard_from_file(path: str) -> Optional[SIMStandard]:
    """Load a sim-standard.json file. Returns None on error."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read SIM standard %s: %s", path, exc)
        return None

    if not isinstance(data, dict):
        logger.warning("SIM standard %s is not a JSON object", path)
        return None

    version = data.get("version", 1)
    if version > SUPPORTED_SCHEMA_VERSION:
        logger.warning(
            "SIM standard %s has schema version %s (supported: %s)",
            path, version, SUPPORTED_SCHEMA_VERSION,
        )

    return _parse_standard(data, path)


def load_standard_from_directory(directory: str) -> Optional[SIMStandard]:
    """Look for sim-standard.json in *directory* and load it."""
    path = os.path.join(directory, STANDARD_FILENAME)
    return load_standard_from_file(path)


def load_standard(directories: list[str]) -> SIMStandard:
    """Load and merge standards from multiple directories.

    Falls back to built-in defaults if no standard file is found.
    Standards from later directories override earlier ones.
    """
    result = _builtin_standard()

    for d in directories:
        overlay = load_standard_from_directory(d)
        if overlay:
            result = _merge_standards(result, overlay)
            logger.info("Loaded SIM standard from %s (rev %s)",
                        d, overlay.revision)

    return result
