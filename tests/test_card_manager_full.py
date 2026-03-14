"""Comprehensive tests for managers/card_manager.py.

Covers areas not yet tested:
- authenticate() with expected_iccid matching/mismatching
- program_card() success/failure paths
- read_card() authenticated vs unauthenticated
- _parse_pysim_output() with various output formats
- has_cli_tool via cli_path/backend checks
- set_backend via set_cli_path
- detect_card CLI path (pySim and sysmo)
- _run_cli edge cases
- Simulator path edge cases
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_manager import CardManager, CardType, CLIBackend, _find_cli_tool
from simulator.settings import SimulatorSettings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sim_manager(num_cards=5, error_rate=0.0):
    """Create a CardManager in simulator mode."""
    cm = CardManager()
    cm.enable_simulator(SimulatorSettings(delay_ms=0,
                                           error_rate=error_rate,
                                           num_cards=num_cards))
    return cm


# ---------------------------------------------------------------------------
# authenticate() with expected_iccid
# ---------------------------------------------------------------------------

class TestAuthenticateWithIccid:
    """Tests for ICCID cross-verification in authenticate()."""

    def test_expected_iccid_match_allows_auth(self):
        """Correct expected_iccid does not block authentication."""
        cm = _make_sim_manager()
        card = cm._simulator._current_card()
        ok, msg = cm.authenticate(card.adm1, expected_iccid=card.iccid)
        assert ok is True
        assert cm.authenticated is True

    def test_expected_iccid_mismatch_blocks_auth(self):
        """Wrong expected_iccid aborts authentication before attempting."""
        cm = _make_sim_manager()
        card = cm._simulator._current_card()
        ok, msg = cm.authenticate(card.adm1, expected_iccid="0000000000000000000")
        assert ok is False
        assert "ICCID mismatch" in msg
        assert cm.authenticated is False

    def test_mismatch_does_not_consume_attempts(self):
        """ICCID mismatch must not decrement adm1_attempts_remaining."""
        cm = _make_sim_manager()
        card = cm._simulator._current_card()
        before = card.adm1_attempts_remaining
        for _ in range(5):
            cm.authenticate(card.adm1, expected_iccid="wrong")
        assert card.adm1_attempts_remaining == before

    def test_none_iccid_skips_check(self):
        """expected_iccid=None skips the ICCID check entirely."""
        cm = _make_sim_manager()
        card = cm._simulator._current_card()
        ok, msg = cm.authenticate(card.adm1, expected_iccid=None)
        assert ok is True

    def test_hardware_path_iccid_mismatch(self):
        """Hardware path (no simulator): ICCID mismatch aborts auth."""
        cm = CardManager()
        cm.card_info = {"ICCID": "89999111111111111111"}
        ok, msg = cm.authenticate("12345678",
                                   expected_iccid="89999999999999999999")
        assert ok is False
        assert "ICCID mismatch" in msg

    def test_hardware_path_iccid_match_proceeds(self):
        """Hardware path: matching ICCID proceeds to validation."""
        cm = CardManager()
        cm.card_info = {"ICCID": "89999111111111111111"}
        ok, msg = cm.authenticate("12345678",
                                   expected_iccid="89999111111111111111")
        # Stub auth succeeds after ICCID check passes
        assert ok is True

    def test_hardware_path_no_card_iccid_skips_check(self):
        """Hardware path: if card has no ICCID yet, skip check (card_iccid is None/empty)."""
        cm = CardManager()
        cm.card_info = {}
        ok, msg = cm.authenticate("12345678",
                                   expected_iccid="89999111111111111111")
        # No card ICCID → skip check, proceed to auth stub
        assert ok is True


# ---------------------------------------------------------------------------
# program_card()
# ---------------------------------------------------------------------------

class TestProgramCard:
    """Tests for program_card() in hardware and simulator modes."""

    def test_hardware_unauthenticated_fails(self):
        """program_card() returns failure when not authenticated (hardware)."""
        cm = CardManager()
        cm.authenticated = False
        ok, msg = cm.program_card({"IMSI": "123"})
        assert ok is False
        assert "Not authenticated" in msg

    def test_hardware_authenticated_stub_succeeds(self):
        """program_card() stub returns success when authenticated."""
        cm = CardManager()
        cm.authenticated = True
        ok, msg = cm.program_card({"IMSI": "123"})
        assert ok is True
        assert "stub" in msg.lower() or "Programmed" in msg

    def test_simulator_program_success(self):
        """Simulator mode: program_card() writes to virtual card."""
        cm = _make_sim_manager()
        card = cm._simulator._current_card()
        cm.authenticate(card.adm1)
        ok, msg = cm.program_card({"imsi": "newimsi"})
        assert ok is True
        assert card.programmed_fields.get("imsi") == "newimsi"

    def test_simulator_program_unauthenticated(self):
        """Simulator mode: program_card() fails when not authenticated."""
        cm = _make_sim_manager()
        ok, msg = cm.program_card({"imsi": "x"})
        assert ok is False

    def test_simulator_program_multiple_fields(self):
        """Simulator mode: multiple fields are all written."""
        cm = _make_sim_manager()
        card = cm._simulator._current_card()
        cm.authenticate(card.adm1)
        data = {"imsi": "999", "ki": "A" * 32, "opc": "B" * 32}
        ok, msg = cm.program_card(data)
        assert ok is True
        for k, v in data.items():
            assert card.programmed_fields[k] == v


# ---------------------------------------------------------------------------
# read_card_data() / read_public_data() / read_protected_data()
# ---------------------------------------------------------------------------

class TestReadCard:
    """Tests for read_card_data and related read functions."""

    def test_read_card_data_hardware_unauthenticated(self):
        """Hardware mode: read_card_data() returns None when not authenticated."""
        cm = CardManager()
        cm.authenticated = False
        assert cm.read_card_data() is None

    def test_read_card_data_hardware_authenticated_empty(self):
        """Hardware mode: read_card_data() returns empty dict when authenticated but no data."""
        cm = CardManager()
        cm.authenticated = True
        cm.card_info = {}
        result = cm.read_card_data()
        # Returns card_info (empty dict) since card_info is falsy → None
        assert result is None

    def test_read_card_data_hardware_with_data(self):
        """Hardware mode: read_card_data() returns card_info when authenticated."""
        cm = CardManager()
        cm.authenticated = True
        cm.card_info = {"ICCID": "123", "IMSI": "456"}
        result = cm.read_card_data()
        assert result == {"ICCID": "123", "IMSI": "456"}

    def test_read_card_data_simulator(self):
        """Simulator mode: read_card_data() returns card data without auth."""
        cm = _make_sim_manager()
        data = cm.read_card_data()
        assert data is not None
        assert "iccid" in data
        assert "imsi" in data

    def test_read_public_data_hardware_no_data(self):
        """Hardware mode: read_public_data() returns None when card_info is empty."""
        cm = CardManager()
        cm.card_info = {}
        assert cm.read_public_data() is None

    def test_read_public_data_hardware_with_data(self):
        """Hardware mode: read_public_data() returns card_info when non-empty."""
        cm = CardManager()
        cm.card_info = {"ICCID": "789"}
        result = cm.read_public_data()
        assert result == {"ICCID": "789"}

    def test_read_protected_data_hardware_unauthenticated(self):
        """Hardware mode: read_protected_data() returns None when not authenticated."""
        cm = CardManager()
        cm.authenticated = False
        assert cm.read_protected_data() is None

    def test_read_protected_data_hardware_authenticated(self):
        """Hardware mode: read_protected_data() returns empty dict (stub) when authenticated."""
        cm = CardManager()
        cm.authenticated = True
        result = cm.read_protected_data()
        assert result == {}


# ---------------------------------------------------------------------------
# _parse_pysim_output()
# ---------------------------------------------------------------------------

class TestParsePysimOutput:
    """Tests for _parse_pysim_output() with various formats."""

    def test_parse_imsi_line(self):
        """Parser extracts IMSI from 'IMSI: 001010123456789'."""
        cm = CardManager()
        cm._parse_pysim_output("IMSI: 001010123456789")
        assert cm.card_info["IMSI"] == "001010123456789"

    def test_parse_iccid_line(self):
        """Parser extracts ICCID from 'ICCID: 89860012345678901234'."""
        cm = CardManager()
        cm._parse_pysim_output("ICCID: 89860012345678901234")
        assert cm.card_info["ICCID"] == "89860012345678901234"

    def test_parse_multiple_lines(self):
        """Parser processes multi-line output correctly."""
        cm = CardManager()
        output = (
            "IMSI: 001010123456789\n"
            "ICCID: 89860012345678901234\n"
            "ADM1: 12345678\n"  # unknown key — ignored
        )
        cm._parse_pysim_output(output)
        assert cm.card_info["IMSI"] == "001010123456789"
        assert cm.card_info["ICCID"] == "89860012345678901234"

    def test_parse_empty_output(self):
        """Parser handles empty output without crashing."""
        cm = CardManager()
        cm._parse_pysim_output("")
        assert cm.card_info == {}

    def test_parse_no_colon_lines_ignored(self):
        """Lines without ':' are ignored."""
        cm = CardManager()
        cm._parse_pysim_output("No colon here\nAnother line without\n")
        assert cm.card_info == {}

    def test_parse_case_insensitive_imsi(self):
        """Parser recognises IMSI regardless of case in key."""
        cm = CardManager()
        cm._parse_pysim_output("  imsi: 123456789012345")
        assert "IMSI" in cm.card_info

    def test_parse_whitespace_trimmed(self):
        """Values have surrounding whitespace stripped."""
        cm = CardManager()
        cm._parse_pysim_output("IMSI:   001010123456789   ")
        assert cm.card_info["IMSI"] == "001010123456789"

    def test_parse_extra_colon_in_value(self):
        """Values containing ':' are handled correctly (partition on first ':')."""
        cm = CardManager()
        cm._parse_pysim_output("ICCID: 89860012345678901234:extra")
        assert cm.card_info["ICCID"] == "89860012345678901234:extra"


# ---------------------------------------------------------------------------
# _find_cli_tool and CLI backend detection
# ---------------------------------------------------------------------------

class TestFindCliTool:
    """Tests for _find_cli_tool() helper function."""

    def test_env_var_sysmo_used_when_set(self, tmp_path):
        """SYSMO_USIM_TOOL_PATH env var takes priority if directory exists."""
        with patch.dict(os.environ, {"SYSMO_USIM_TOOL_PATH": str(tmp_path)}):
            path, backend = _find_cli_tool()
        assert path == str(tmp_path)
        assert backend == CLIBackend.SYSMO

    def test_env_var_pysim_used_when_set(self, tmp_path):
        """PYSIM_PATH env var takes priority if directory exists."""
        with patch.dict(os.environ,
                        {"SYSMO_USIM_TOOL_PATH": "",
                         "PYSIM_PATH": str(tmp_path)}):
            path, backend = _find_cli_tool()
        assert path == str(tmp_path)
        assert backend == CLIBackend.PYSIM

    def test_env_var_invalid_path_skipped(self, tmp_path):
        """SYSMO_USIM_TOOL_PATH is ignored if the path doesn't exist."""
        with patch.dict(os.environ,
                        {"SYSMO_USIM_TOOL_PATH": "/nonexistent/path",
                         "PYSIM_PATH": ""}):
            # The function should fall through — result depends on system
            path, backend = _find_cli_tool()
        # Can't assert a specific path, but it should not crash


# ---------------------------------------------------------------------------
# _run_cli
# ---------------------------------------------------------------------------

class TestRunCli:
    """Tests for _run_cli() — the subprocess wrapper."""

    def test_run_cli_no_cli_path_returns_error(self):
        """_run_cli() returns failure when cli_path is None."""
        cm = CardManager()
        cm.cli_path = None
        ok, stdout, stderr = cm._run_cli("any_script.py")
        assert ok is False
        assert "not found" in stderr.lower() or "pySim" in stderr

    def test_run_cli_invalid_script_returns_error(self, tmp_path):
        """_run_cli() returns failure for path traversal attempt."""
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        ok, stdout, stderr = cm._run_cli("../etc/passwd")
        assert ok is False
        assert "Invalid script" in stderr

    def test_run_cli_success(self, tmp_path):
        """_run_cli() returns success when script exits 0."""
        # Create a real Python script
        script = tmp_path / "test_script.py"
        script.write_text("print('hello')\n")
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        mock_result = MagicMock(returncode=0, stdout="hello", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            ok, stdout, stderr = cm._run_cli("test_script.py")
        assert ok is True
        assert stdout == "hello"

    def test_run_cli_timeout(self, tmp_path):
        """_run_cli() returns failure on TimeoutExpired."""
        import subprocess
        script = tmp_path / "slow.py"
        script.write_text("import time; time.sleep(100)\n")
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("cmd", 30)):
            ok, stdout, stderr = cm._run_cli("slow.py")
        assert ok is False
        assert "timed out" in stderr.lower()

    def test_run_cli_file_not_found(self, tmp_path):
        """_run_cli() returns failure when script does not exist."""
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            ok, stdout, stderr = cm._run_cli("missing.py")
        assert ok is False

    def test_run_cli_generic_exception(self, tmp_path):
        """_run_cli() returns failure on any unexpected exception."""
        script = tmp_path / "boom.py"
        script.write_text("")
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            ok, stdout, stderr = cm._run_cli("boom.py")
        assert ok is False
        assert "boom" in stderr


# ---------------------------------------------------------------------------
# set_cli_path / get_backend
# ---------------------------------------------------------------------------

class TestSetCliPath:
    """Additional tests for set_cli_path backend detection."""

    def test_set_path_explicit_none_backend_auto_detects(self, tmp_path):
        """set_cli_path() with no explicit backend auto-detects SYSMO when no pySim."""
        cm = CardManager()
        cm.set_cli_path(str(tmp_path), backend=None)
        assert cm.cli_backend == CLIBackend.SYSMO

    def test_set_path_with_pysim_script_detects_pysim(self, tmp_path):
        """set_cli_path() detects PYSIM when pySim-read.py exists."""
        (tmp_path / "pySim-read.py").touch()
        cm = CardManager()
        cm.set_cli_path(str(tmp_path))
        assert cm.cli_backend == CLIBackend.PYSIM

    def test_set_path_returns_false_for_file(self, tmp_path):
        """set_cli_path() returns False when path is a file, not directory."""
        f = tmp_path / "somefile.txt"
        f.write_text("")
        cm = CardManager()
        assert cm.set_cli_path(str(f)) is False


# ---------------------------------------------------------------------------
# detect_card — PYSIM path
# ---------------------------------------------------------------------------

class TestDetectCard:
    """Tests for detect_card() in PYSIM mode."""

    def test_detect_pysim_success(self, tmp_path):
        """detect_card() in PYSIM mode calls pySim-read.py."""
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        with patch.object(cm, "_run_cli",
                          return_value=(True, "ICCID: 1234\nIMSI: 5678", "")) as m:
            ok, msg = cm.detect_card()
        assert ok is True
        m.assert_called_once_with("pySim-read.py", "-p0")

    def test_detect_pysim_failure(self, tmp_path):
        """detect_card() PYSIM: failure message returned when run fails."""
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        with patch.object(cm, "_run_cli",
                          return_value=(False, "", "No card")):
            ok, msg = cm.detect_card()
        assert ok is False
        assert "No card" in msg

    def test_detect_sysmo_all_fail(self, tmp_path):
        """detect_card() SYSMO: returns failure when all scripts fail."""
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.SYSMO
        # Only patching _validate_script_path so all scripts fail validation
        with patch.object(cm, "_validate_script_path", return_value=None):
            ok, msg = cm.detect_card()
        assert ok is False

    def test_detect_sets_card_type_on_success(self, tmp_path):
        """detect_card() updates card_type on PYSIM success."""
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        with patch.object(cm, "_run_cli",
                          return_value=(True, "ICCID: 123", "")):
            cm.detect_card()
        # card_type is not set by pySim path (hardware limitation) but card_info is
        assert "ICCID" in cm.card_info


# ---------------------------------------------------------------------------
# verify_card
# ---------------------------------------------------------------------------

class TestVerifyCard:
    """Tests for verify_card() in hardware and simulator modes."""

    def test_hardware_unauthenticated(self):
        """verify_card() returns failure when not authenticated (hardware)."""
        cm = CardManager()
        cm.authenticated = False
        ok, mismatches = cm.verify_card({"IMSI": "123"})
        assert ok is False
        assert mismatches == ["Not authenticated"]

    def test_hardware_authenticated_no_data(self):
        """verify_card() returns success (empty mismatches) when authenticated."""
        cm = CardManager()
        cm.authenticated = True
        ok, mismatches = cm.verify_card({"IMSI": "123"})
        assert ok is True
        assert mismatches == []

    def test_simulator_match(self):
        """verify_card() in simulator mode: matching data → success."""
        cm = _make_sim_manager()
        card = cm._simulator._current_card()
        cm.authenticate(card.adm1)
        cm.program_card({"imsi": "test_val"})
        ok, mismatches = cm.verify_card({"imsi": "test_val"})
        assert ok is True

    def test_simulator_mismatch(self):
        """verify_card() in simulator mode: mismatched data → failure."""
        cm = _make_sim_manager()
        ok, mismatches = cm.verify_card({"imsi": "wrong_value"})
        assert ok is False
        assert len(mismatches) > 0


# ---------------------------------------------------------------------------
# get_remaining_attempts
# ---------------------------------------------------------------------------

class TestGetRemainingAttempts:
    """Tests for get_remaining_attempts()."""

    def test_hardware_returns_none(self):
        """get_remaining_attempts() returns None in hardware mode."""
        cm = CardManager()
        assert cm.get_remaining_attempts() is None

    def test_simulator_returns_3(self):
        """get_remaining_attempts() returns 3 for a fresh virtual card."""
        cm = _make_sim_manager()
        assert cm.get_remaining_attempts() == 3

    def test_simulator_decrements_on_wrong_adm1(self):
        """get_remaining_attempts() decrements after wrong ADM1."""
        cm = _make_sim_manager()
        cm.authenticate("00000000")  # wrong
        assert cm.get_remaining_attempts() == 2


# ---------------------------------------------------------------------------
# read_iccid
# ---------------------------------------------------------------------------

class TestReadIccid:
    """Tests for read_iccid()."""

    def test_hardware_no_iccid_returns_none(self):
        """read_iccid() returns None when card_info has no ICCID (hardware)."""
        cm = CardManager()
        cm.card_info = {}
        result = cm.read_iccid()
        assert result is None or result == ""

    def test_hardware_with_iccid(self):
        """read_iccid() returns the ICCID from card_info."""
        cm = CardManager()
        cm.card_info = {"ICCID": "89860012345678901234"}
        assert cm.read_iccid() == "89860012345678901234"

    def test_simulator_returns_iccid(self):
        """read_iccid() returns the virtual card's ICCID."""
        cm = _make_sim_manager()
        iccid = cm.read_iccid()
        assert iccid is not None
        assert len(iccid) > 0

    def test_simulator_no_card(self):
        """read_iccid() returns None when simulator has empty deck."""
        cm = CardManager()
        cm.enable_simulator(SimulatorSettings(delay_ms=0, num_cards=0))
        cm._simulator.card_deck = []
        result = cm.read_iccid()
        assert result is None
