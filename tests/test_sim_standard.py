"""Tests for managers/sim_standard.py — SIMStandard data classes and loader."""

import json
import os
import pytest

from managers.sim_standard import (
    AllocationEntry,
    PLMNConfig,
    SIMStandard,
    SIMTypeConfig,
    SiteConfig,
    _builtin_standard,
    _merge_standards,
    _parse_standard,
    load_standard,
    load_standard_from_directory,
    load_standard_from_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_json(**overrides) -> dict:
    """Return a minimal valid sim-standard.json dict."""
    data = {
        "version": 1,
        "document": {
            "title": "Test Standard",
            "revision": "1.0",
            "date": "2026-01-01",
            "scope": "Testing",
        },
        "plmns": {
            "99988": {
                "mcc": "999", "mnc": "88", "mnc_length": 2,
                "purpose": "Production", "issuer_id": "988", "status": "active",
            },
        },
        "default_plmn": "99988",
        "sites": {
            "0001": {
                "code": "uk1", "country": "United Kingdom",
                "country_code_e164": "44", "description": "UK DC",
                "status": "active",
            },
        },
        "sim_types": {
            "0": {"name": "USIM", "description": "Standard SIM"},
        },
        "fplmn_by_country": {
            "United Kingdom": ["23415", "23410"],
        },
        "sim_profile_defaults": {
            "li": "EN", "hplmn": "99988",
            "adm1_empty_cards": "3838383838383838",
        },
        "key_generation": {"method": "random", "note": "128-bit random"},
        "spn_values": ["TELEAURA"],
        "li_values": ["EN", "SV"],
        "allocations": {},
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# _builtin_standard
# ---------------------------------------------------------------------------

class TestBuiltinStandard:
    def test_returns_simstandard(self):
        std = _builtin_standard()
        assert isinstance(std, SIMStandard)

    def test_has_plmns(self):
        std = _builtin_standard()
        assert "99988" in std.plmns
        assert "99989" in std.plmns

    def test_has_sites(self):
        std = _builtin_standard()
        assert "0001" in std.sites
        assert std.sites["0001"].code == "uk1"

    def test_has_sim_types(self):
        std = _builtin_standard()
        assert "0" in std.sim_types
        assert "1" in std.sim_types

    def test_has_fplmn_by_country(self):
        std = _builtin_standard()
        assert "United Kingdom" in std.fplmn_by_country
        assert "Sweden" in std.fplmn_by_country

    def test_has_spn_values(self):
        std = _builtin_standard()
        assert len(std.spn_values) > 0

    def test_has_li_values(self):
        std = _builtin_standard()
        assert "EN" in std.li_values

    def test_adm1_empty_cards(self):
        std = _builtin_standard()
        assert std.adm1_empty_cards == "3838383838383838"

    def test_is_not_loaded_from_file(self):
        std = _builtin_standard()
        assert not std.is_loaded

    def test_default_plmn(self):
        std = _builtin_standard()
        assert std.default_plmn == "99988"


# ---------------------------------------------------------------------------
# SIMStandard lookup methods
# ---------------------------------------------------------------------------

class TestSIMStandardLookups:

    @pytest.fixture
    def std(self):
        return _builtin_standard()

    def test_get_site_found(self, std):
        site = std.get_site("0001")
        assert site is not None
        assert site.code == "uk1"

    def test_get_site_missing(self, std):
        assert std.get_site("9999") is None

    def test_get_site_by_code_found(self, std):
        site = std.get_site_by_code("uk1")
        assert site is not None
        assert site.site_id == "0001"

    def test_get_site_by_code_missing(self, std):
        assert std.get_site_by_code("xx9") is None

    def test_get_plmn_found(self, std):
        plmn = std.get_plmn("99988")
        assert plmn is not None
        assert plmn.mcc == "999"

    def test_get_plmn_missing(self, std):
        assert std.get_plmn("00000") is None

    def test_get_default_plmn(self, std):
        plmn = std.get_default_plmn()
        assert plmn is not None
        assert plmn.mcc_mnc == "99988"

    def test_get_fplmn_for_site_found(self, std):
        result = std.get_fplmn_for_site("0001")
        assert "23415" in result
        assert ";" in result

    def test_get_fplmn_for_site_missing(self, std):
        assert std.get_fplmn_for_site("9999") == ""

    def test_get_issuer_id_found(self, std):
        assert std.get_issuer_id("99988") == "988"

    def test_get_issuer_id_missing(self, std):
        assert std.get_issuer_id("00000") == "988"

    def test_get_country_code_found(self, std):
        assert std.get_country_code("0001") == "44"

    def test_get_country_code_missing(self, std):
        assert std.get_country_code("9999") == "00"

    def test_get_active_sites_excludes_reserved(self, std):
        active = std.get_active_sites()
        codes = [s.code for s in active]
        assert "uk1" in codes
        assert "au1" not in codes  # reserved in builtin

    def test_get_active_plmns(self, std):
        active = std.get_active_plmns()
        assert all(p.status == "active" for p in active)
        assert len(active) >= 1

    def test_is_loaded_false_for_builtin(self, std):
        assert std.is_loaded is False

    def test_is_loaded_true_when_loaded_from_set(self, std):
        std.loaded_from = ["/mnt/share/sim-standard.json"]
        assert std.is_loaded is True

    def test_get_next_sequence_no_allocations(self, std):
        assert std.get_next_sequence("uk1", "0") == 1

    def test_get_next_sequence_with_allocation(self, std):
        std.allocations["uk1"] = [
            AllocationEntry("0001", "0", "cust", 1, 500),
            AllocationEntry("0001", "0", "cust", 501, 750),
        ]
        assert std.get_next_sequence("uk1", "0") == 751

    def test_get_next_sequence_filters_by_sim_type(self, std):
        std.allocations["uk1"] = [
            AllocationEntry("0001", "0", "cust", 1, 500),
            AllocationEntry("0001", "1", "cust", 1, 200),
        ]
        assert std.get_next_sequence("uk1", "1") == 201

    def test_get_next_sequence_unknown_site(self, std):
        assert std.get_next_sequence("xx9", "0") == 1


# ---------------------------------------------------------------------------
# _parse_standard
# ---------------------------------------------------------------------------

class TestParseStandard:

    def test_parses_metadata(self):
        data = _minimal_json()
        std = _parse_standard(data, "/tmp/test.json")
        assert std.title == "Test Standard"
        assert std.revision == "1.0"
        assert std.scope == "Testing"

    def test_parses_plmns(self):
        data = _minimal_json()
        std = _parse_standard(data, "/tmp/test.json")
        assert "99988" in std.plmns
        plmn = std.plmns["99988"]
        assert plmn.mcc == "999"
        assert plmn.mnc == "88"
        assert plmn.mnc_length == 2
        assert plmn.issuer_id == "988"

    def test_parses_default_plmn(self):
        std = _parse_standard(_minimal_json(), "/tmp/test.json")
        assert std.default_plmn == "99988"

    def test_parses_sites(self):
        std = _parse_standard(_minimal_json(), "/tmp/test.json")
        assert "0001" in std.sites
        site = std.sites["0001"]
        assert site.code == "uk1"
        assert site.country == "United Kingdom"
        assert site.country_code_e164 == "44"

    def test_parses_sim_types(self):
        std = _parse_standard(_minimal_json(), "/tmp/test.json")
        assert "0" in std.sim_types
        assert std.sim_types["0"].name == "USIM"

    def test_parses_fplmn_as_list(self):
        std = _parse_standard(_minimal_json(), "/tmp/test.json")
        assert std.fplmn_by_country["United Kingdom"] == ["23415", "23410"]

    def test_parses_fplmn_as_semicolon_string(self):
        data = _minimal_json()
        data["fplmn_by_country"] = {"Sweden": "24007;24024;24001"}
        std = _parse_standard(data, "/tmp/test.json")
        assert std.fplmn_by_country["Sweden"] == ["24007", "24024", "24001"]

    def test_parses_profile_defaults(self):
        std = _parse_standard(_minimal_json(), "/tmp/test.json")
        assert std.default_li == "EN"
        assert std.adm1_empty_cards == "3838383838383838"

    def test_parses_key_generation(self):
        std = _parse_standard(_minimal_json(), "/tmp/test.json")
        assert std.key_method == "random"
        assert std.key_note == "128-bit random"

    def test_parses_spn_and_li_values(self):
        std = _parse_standard(_minimal_json(), "/tmp/test.json")
        assert "TELEAURA" in std.spn_values
        assert "EN" in std.li_values

    def test_sets_loaded_from(self):
        std = _parse_standard(_minimal_json(), "/tmp/test.json")
        assert std.loaded_from == ["/tmp/test.json"]

    def test_parses_allocations(self):
        data = _minimal_json()
        data["allocations"] = {
            "uk1": [
                {
                    "site_id": "0001", "sim_type": "0",
                    "customer": "Acme", "range_start": 1, "range_end": 500,
                    "notes": "batch 1",
                },
            ],
        }
        std = _parse_standard(data, "/tmp/test.json")
        assert "uk1" in std.allocations
        entry = std.allocations["uk1"][0]
        assert entry.range_start == 1
        assert entry.range_end == 500
        assert entry.customer == "Acme"

    def test_missing_optional_fields_use_defaults(self):
        data = {"document": {}, "plmns": {}, "sites": {}, "sim_types": {}}
        std = _parse_standard(data, "/tmp/test.json")
        assert std.default_plmn == "99988"
        assert std.key_method == "random"

    def test_multiple_plmns(self):
        data = _minimal_json()
        data["plmns"]["99989"] = {
            "mcc": "999", "mnc": "89", "mnc_length": 2,
            "purpose": "Lab", "issuer_id": "989", "status": "active",
        }
        std = _parse_standard(data, "/tmp/test.json")
        assert "99989" in std.plmns


# ---------------------------------------------------------------------------
# _merge_standards
# ---------------------------------------------------------------------------

class TestMergeStandards:

    def test_overlay_plmn_wins(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.plmns["99988"] = PLMNConfig(
            "99988", "999", "88", 2, "Override", "988", "active"
        )
        result = _merge_standards(base, overlay)
        assert result.plmns["99988"].purpose == "Override"

    def test_overlay_adds_new_plmn(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.plmns["24001"] = PLMNConfig(
            "24001", "240", "01", 2, "Telia SE", "001", "active"
        )
        result = _merge_standards(base, overlay)
        assert "24001" in result.plmns

    def test_overlay_site_wins(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.sites["0001"] = SiteConfig(
            "0001", "uk1", "United Kingdom", "44", "Updated DC", "active"
        )
        result = _merge_standards(base, overlay)
        assert result.sites["0001"].description == "Updated DC"

    def test_overlay_adds_new_site(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.sites["0005"] = SiteConfig(
            "0005", "de1", "Germany", "49", "Frankfurt DC", "active"
        )
        result = _merge_standards(base, overlay)
        assert "0005" in result.sites

    def test_spn_values_merged_deduped(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.spn_values = ["TELEAURA", "NEWCORP"]  # TELEAURA already in base
        result = _merge_standards(base, overlay)
        assert result.spn_values.count("TELEAURA") == 1
        assert "NEWCORP" in result.spn_values

    def test_spn_dedup_is_case_insensitive(self):
        base = _builtin_standard()
        base.spn_values = ["TELEAURA"]
        overlay = SIMStandard()
        overlay.spn_values = ["teleaura"]  # same, different case
        result = _merge_standards(base, overlay)
        assert sum(1 for s in result.spn_values if s.upper() == "TELEAURA") == 1

    def test_li_values_merged_deduped(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.li_values = ["EN", "DE"]
        result = _merge_standards(base, overlay)
        assert result.li_values.count("EN") == 1
        assert "DE" in result.li_values

    def test_allocations_merged_by_site(self):
        base = _builtin_standard()
        base.allocations["uk1"] = [
            AllocationEntry("0001", "0", "Acme", 1, 500),
        ]
        overlay = SIMStandard()
        overlay.allocations["uk1"] = [
            AllocationEntry("0001", "0", "Beta", 501, 1000),
        ]
        result = _merge_standards(base, overlay)
        assert len(result.allocations["uk1"]) == 2

    def test_allocations_new_site_added(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.allocations["se1"] = [
            AllocationEntry("0002", "0", "Acme", 1, 100),
        ]
        result = _merge_standards(base, overlay)
        assert "se1" in result.allocations

    def test_overlay_adm1_wins(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.adm1_empty_cards = "4141414141414141"
        result = _merge_standards(base, overlay)
        assert result.adm1_empty_cards == "4141414141414141"

    def test_overlay_empty_adm1_does_not_overwrite(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.adm1_empty_cards = ""
        result = _merge_standards(base, overlay)
        assert result.adm1_empty_cards == "3838383838383838"

    def test_loaded_from_accumulated(self):
        base = _builtin_standard()
        base.loaded_from = ["/mnt/a/sim-standard.json"]
        overlay = SIMStandard()
        overlay.loaded_from = ["/mnt/b/sim-standard.json"]
        result = _merge_standards(base, overlay)
        assert len(result.loaded_from) == 2

    def test_fplmn_overlay_wins_per_country(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.fplmn_by_country["United Kingdom"] = ["23415"]
        result = _merge_standards(base, overlay)
        assert result.fplmn_by_country["United Kingdom"] == ["23415"]

    def test_overlay_default_plmn_wins(self):
        base = _builtin_standard()
        overlay = SIMStandard()
        overlay.default_plmn = "99989"
        result = _merge_standards(base, overlay)
        assert result.default_plmn == "99989"


# ---------------------------------------------------------------------------
# load_standard_from_file
# ---------------------------------------------------------------------------

class TestLoadStandardFromFile:

    def test_returns_none_for_missing_file(self, tmp_path):
        result = load_standard_from_file(str(tmp_path / "missing.json"))
        assert result is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        f = tmp_path / "sim-standard.json"
        f.write_text("not json {{{")
        assert load_standard_from_file(str(f)) is None

    def test_returns_none_for_non_dict_json(self, tmp_path):
        f = tmp_path / "sim-standard.json"
        f.write_text("[1, 2, 3]")
        assert load_standard_from_file(str(f)) is None

    def test_loads_valid_file(self, tmp_path):
        f = tmp_path / "sim-standard.json"
        f.write_text(json.dumps(_minimal_json()))
        result = load_standard_from_file(str(f))
        assert result is not None
        assert result.title == "Test Standard"
        assert result.loaded_from == [str(f)]

    def test_future_schema_version_still_loads(self, tmp_path):
        data = _minimal_json()
        data["version"] = 99
        f = tmp_path / "sim-standard.json"
        f.write_text(json.dumps(data))
        result = load_standard_from_file(str(f))
        assert result is not None  # warning logged but still parsed


# ---------------------------------------------------------------------------
# load_standard_from_directory
# ---------------------------------------------------------------------------

class TestLoadStandardFromDirectory:

    def test_returns_none_when_no_file(self, tmp_path):
        assert load_standard_from_directory(str(tmp_path)) is None

    def test_loads_when_file_present(self, tmp_path):
        f = tmp_path / "sim-standard.json"
        f.write_text(json.dumps(_minimal_json()))
        result = load_standard_from_directory(str(tmp_path))
        assert result is not None
        assert result.revision == "1.0"


# ---------------------------------------------------------------------------
# load_standard (public API — with merge and fallback)
# ---------------------------------------------------------------------------

class TestLoadStandard:

    def test_returns_builtin_when_no_directories(self):
        std = load_standard([])
        assert isinstance(std, SIMStandard)
        assert "99988" in std.plmns

    def test_returns_builtin_when_directories_have_no_file(self, tmp_path):
        std = load_standard([str(tmp_path)])
        assert "99988" in std.plmns
        assert not std.is_loaded

    def test_loads_from_single_directory(self, tmp_path):
        f = tmp_path / "sim-standard.json"
        f.write_text(json.dumps(_minimal_json()))
        std = load_standard([str(tmp_path)])
        assert std.is_loaded
        assert std.title == "Test Standard"

    def test_merges_multiple_directories(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        data_a = _minimal_json()
        data_a["spn_values"] = ["TELEAURA"]
        (dir_a / "sim-standard.json").write_text(json.dumps(data_a))

        data_b = _minimal_json()
        data_b["spn_values"] = ["NEWCORP"]
        (dir_b / "sim-standard.json").write_text(json.dumps(data_b))

        std = load_standard([str(dir_a), str(dir_b)])
        assert "TELEAURA" in std.spn_values
        assert "NEWCORP" in std.spn_values

    def test_later_directory_overrides_earlier(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        data_a = _minimal_json()
        data_a["document"]["revision"] = "1.0"
        (dir_a / "sim-standard.json").write_text(json.dumps(data_a))

        data_b = _minimal_json()
        data_b["document"]["revision"] = "2.0"
        (dir_b / "sim-standard.json").write_text(json.dumps(data_b))

        std = load_standard([str(dir_a), str(dir_b)])
        assert std.revision == "2.0"

    def test_skips_missing_directory_in_list(self, tmp_path):
        f = tmp_path / "sim-standard.json"
        f.write_text(json.dumps(_minimal_json()))
        std = load_standard(["/nonexistent/path", str(tmp_path)])
        assert std.is_loaded

    def test_loaded_from_tracks_sources(self, tmp_path):
        f = tmp_path / "sim-standard.json"
        f.write_text(json.dumps(_minimal_json()))
        std = load_standard([str(tmp_path)])
        assert str(f) in std.loaded_from
