"""Tests for managers.standards_manager."""

import json
import os

import pytest

from managers.standards_manager import STANDARDS_FILENAME, StandardsManager


@pytest.fixture
def tmp_share(tmp_path):
    """Create a temporary directory simulating a mounted share."""
    return str(tmp_path)


def _write_standards(directory, data):
    """Helper — write standards.json into *directory*."""
    path = os.path.join(directory, STANDARDS_FILENAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    return path


# ---- Basic loading ----------------------------------------------------------

class TestLoading:

    def test_load_valid_file(self, tmp_share):
        _write_standards(tmp_share, {
            "version": 1,
            "spn": ["BOLIDEN", "FISKARHEDEN"],
            "li": ["EN", "SV"],
        })
        mgr = StandardsManager()
        assert mgr.load_from_directory(tmp_share) is True
        assert mgr.has_standards is True
        assert mgr.spn_values == ["BOLIDEN", "FISKARHEDEN"]
        assert mgr.li_values == ["EN", "SV"]

    def test_load_no_file(self, tmp_share):
        mgr = StandardsManager()
        assert mgr.load_from_directory(tmp_share) is False
        assert mgr.has_standards is False
        assert mgr.spn_values == []

    def test_load_invalid_json(self, tmp_share):
        path = os.path.join(tmp_share, STANDARDS_FILENAME)
        with open(path, "w") as fh:
            fh.write("NOT JSON {{{")
        mgr = StandardsManager()
        assert mgr.load_from_directory(tmp_share) is False
        assert mgr.has_standards is False

    def test_load_non_dict_json(self, tmp_share):
        """A valid JSON file that is not an object."""
        path = os.path.join(tmp_share, STANDARDS_FILENAME)
        with open(path, "w") as fh:
            json.dump(["a", "b"], fh)
        mgr = StandardsManager()
        assert mgr.load_from_directory(tmp_share) is False

    def test_load_missing_fields_gives_empty_lists(self, tmp_share):
        """A valid object but without spn/li keys."""
        _write_standards(tmp_share, {"version": 1})
        mgr = StandardsManager()
        assert mgr.load_from_directory(tmp_share) is True
        assert mgr.spn_values == []
        assert mgr.li_values == []
        assert mgr.has_standards is True  # file was loaded

    def test_load_non_string_values_filtered(self, tmp_share):
        """Non-string items in the list are ignored."""
        _write_standards(tmp_share, {
            "version": 1,
            "spn": ["OK", 123, None, "", "  ", "ALSO_OK"],
        })
        mgr = StandardsManager()
        mgr.load_from_directory(tmp_share)
        assert mgr.spn_values == ["OK", "ALSO_OK"]

    def test_load_future_version_warns_but_loads(self, tmp_share):
        """Version > supported is loaded with unknown keys ignored."""
        _write_standards(tmp_share, {
            "version": 99,
            "spn": ["TEST"],
            "unknown_future_key": [1, 2, 3],
        })
        mgr = StandardsManager()
        assert mgr.load_from_directory(tmp_share) is True
        assert mgr.spn_values == ["TEST"]


# ---- Merging ----------------------------------------------------------------

class TestMerging:

    def test_merge_two_shares(self, tmp_path):
        share_a = str(tmp_path / "share_a")
        share_b = str(tmp_path / "share_b")
        os.makedirs(share_a)
        os.makedirs(share_b)

        _write_standards(share_a, {
            "version": 1,
            "spn": ["BOLIDEN", "FISKARHEDEN"],
            "li": ["EN"],
        })
        _write_standards(share_b, {
            "version": 1,
            "spn": ["TELEAURA", "BOLIDEN"],  # BOLIDEN is duplicate
            "li": ["SV", "EN"],              # EN is duplicate
        })

        mgr = StandardsManager()
        mgr.load_from_directory(share_a)
        mgr.load_from_directory(share_b)

        assert mgr.spn_values == ["BOLIDEN", "FISKARHEDEN", "TELEAURA"]
        assert mgr.li_values == ["EN", "SV"]
        assert len(mgr.loaded_paths) == 2

    def test_dedup_is_case_exact(self, tmp_path):
        """'BOLIDEN' and 'Boliden' are different entries (case-exact dedup)."""
        share = str(tmp_path / "share")
        os.makedirs(share)
        _write_standards(share, {
            "version": 1,
            "spn": ["BOLIDEN", "Boliden"],
        })
        mgr = StandardsManager()
        mgr.load_from_directory(share)
        assert mgr.spn_values == ["BOLIDEN", "Boliden"]


# ---- Clear / Reload --------------------------------------------------------

class TestClearReload:

    def test_clear(self, tmp_share):
        _write_standards(tmp_share, {
            "version": 1, "spn": ["A"], "li": ["EN"],
        })
        mgr = StandardsManager()
        mgr.load_from_directory(tmp_share)
        assert mgr.has_standards is True

        mgr.clear()
        assert mgr.has_standards is False
        assert mgr.spn_values == []
        assert mgr.li_values == []
        assert mgr.loaded_paths == []

    def test_reload_from_directories(self, tmp_path):
        share = str(tmp_path / "share")
        os.makedirs(share)
        _write_standards(share, {
            "version": 1, "spn": ["X"], "li": ["FI"],
        })

        mgr = StandardsManager()
        mgr.load_from_directory(share)
        assert mgr.spn_values == ["X"]

        # Reload with empty list -> clears
        mgr.reload_from_directories([])
        assert mgr.has_standards is False

        # Reload with the share again
        count = mgr.reload_from_directories([share])
        assert count == 1
        assert mgr.spn_values == ["X"]

    def test_reload_skips_missing_dirs(self, tmp_path):
        share = str(tmp_path / "share")
        os.makedirs(share)
        _write_standards(share, {"version": 1, "spn": ["A"]})

        mgr = StandardsManager()
        count = mgr.reload_from_directories([
            str(tmp_path / "no_such_dir"),
            share,
            str(tmp_path / "also_missing"),
        ])
        assert count == 1
        assert mgr.spn_values == ["A"]


# ---- Validation -------------------------------------------------------------

class TestValidation:

    def test_is_valid_spn(self, tmp_share):
        _write_standards(tmp_share, {
            "version": 1, "spn": ["BOLIDEN", "FISKARHEDEN"],
        })
        mgr = StandardsManager()
        mgr.load_from_directory(tmp_share)

        assert mgr.is_valid_spn("BOLIDEN") is True
        assert mgr.is_valid_spn("boliden") is False  # case-exact
        assert mgr.is_valid_spn("UNKNOWN") is False

    def test_is_valid_li(self, tmp_share):
        _write_standards(tmp_share, {
            "version": 1, "li": ["EN", "SV"],
        })
        mgr = StandardsManager()
        mgr.load_from_directory(tmp_share)

        assert mgr.is_valid_li("EN") is True
        assert mgr.is_valid_li("en") is False
        assert mgr.is_valid_li("DE") is False


# ---- Suggestions ------------------------------------------------------------

class TestSuggestions:

    def test_suggest_spn_case_insensitive(self, tmp_share):
        _write_standards(tmp_share, {
            "version": 1, "spn": ["BOLIDEN"],
        })
        mgr = StandardsManager()
        mgr.load_from_directory(tmp_share)

        assert mgr.suggest_spn("boliden") == "BOLIDEN"
        assert mgr.suggest_spn("Boliden") == "BOLIDEN"
        assert mgr.suggest_spn("BOLIDEN") == "BOLIDEN"
        assert mgr.suggest_spn("böliden") is None  # ö != o

    def test_suggest_li_case_insensitive(self, tmp_share):
        _write_standards(tmp_share, {
            "version": 1, "li": ["EN", "SV"],
        })
        mgr = StandardsManager()
        mgr.load_from_directory(tmp_share)

        assert mgr.suggest_li("en") == "EN"
        assert mgr.suggest_li("sv") == "SV"
        assert mgr.suggest_li("de") is None

    def test_suggest_returns_none_when_no_standards(self):
        mgr = StandardsManager()
        assert mgr.suggest_spn("anything") is None
        assert mgr.suggest_li("EN") is None


# ---- Template creation ------------------------------------------------------

class TestTemplate:

    def test_create_template_default(self, tmp_path):
        path = str(tmp_path / STANDARDS_FILENAME)
        StandardsManager.create_template(path)

        with open(path, "r") as fh:
            data = json.load(fh)
        assert data["version"] == 1
        assert "EXAMPLE_PROVIDER" in data["spn"]
        assert "EN" in data["li"]

    def test_create_template_custom(self, tmp_path):
        path = str(tmp_path / STANDARDS_FILENAME)
        StandardsManager.create_template(
            path, spn=["A", "B"], li=["SV", "FI"])

        with open(path, "r") as fh:
            data = json.load(fh)
        assert data["spn"] == ["A", "B"]
        assert data["li"] == ["SV", "FI"]

    def test_created_template_is_loadable(self, tmp_path):
        StandardsManager.create_template(
            str(tmp_path / STANDARDS_FILENAME),
            spn=["BOLIDEN"], li=["EN"])

        mgr = StandardsManager()
        assert mgr.load_from_directory(str(tmp_path)) is True
        assert mgr.spn_values == ["BOLIDEN"]


# ---- Properties return copies -----------------------------------------------

class TestImmutability:

    def test_spn_values_returns_copy(self, tmp_share):
        _write_standards(tmp_share, {"version": 1, "spn": ["A", "B"]})
        mgr = StandardsManager()
        mgr.load_from_directory(tmp_share)

        vals = mgr.spn_values
        vals.append("C")
        assert mgr.spn_values == ["A", "B"]  # unchanged

    def test_loaded_paths_returns_copy(self, tmp_share):
        _write_standards(tmp_share, {"version": 1, "spn": ["A"]})
        mgr = StandardsManager()
        mgr.load_from_directory(tmp_share)

        paths = mgr.loaded_paths
        paths.clear()
        assert len(mgr.loaded_paths) == 1  # unchanged


# ---- Unicode / edge cases ---------------------------------------------------

class TestUnicode:

    def test_unicode_spn_values(self, tmp_share):
        """SPN with non-ASCII characters."""
        _write_standards(tmp_share, {
            "version": 1,
            "spn": ["BÖLIDEN", "MALMÖ ENERGI"],
        })
        mgr = StandardsManager()
        mgr.load_from_directory(tmp_share)
        assert mgr.spn_values == ["BÖLIDEN", "MALMÖ ENERGI"]
        assert mgr.is_valid_spn("BÖLIDEN") is True
        assert mgr.is_valid_spn("BOLIDEN") is False

    def test_empty_file(self, tmp_share):
        """Empty JSON object is valid but has no values."""
        _write_standards(tmp_share, {})
        mgr = StandardsManager()
        assert mgr.load_from_directory(tmp_share) is True
        assert mgr.has_standards is True
        assert mgr.spn_values == []

    def test_nonexistent_directory(self):
        mgr = StandardsManager()
        assert mgr.load_from_directory("/no/such/path") is False
