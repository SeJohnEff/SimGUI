"""Tests for ProgramSIMPanel result display style after programming.

Three cases:
- clean success  → success/green
- ok=True but partial failure in msg → warning/amber
- ok=False → error/red
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from widgets.program_sim_panel import ProgramSIMPanel


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def panel(qapp):
    cm = MagicMock()
    cm.authenticate.return_value = (True, "ADM1 verified")
    p = ProgramSIMPanel(None, cm)
    p._step = 1
    p._field_entries["ADM1"].setText("88888888")
    yield p
    p.deleteLater()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_program(panel, ok, msg):
    """Set program_card return value, capture _set_action_status calls."""
    panel._cm.program_card.return_value = (ok, msg)
    calls = []
    panel._set_action_status = lambda m, s="normal": calls.append((m, s))
    panel._on_program()
    return calls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProgramResultDisplayStyle:

    def test_clean_success_shows_success_style(self, panel):
        msg = "Card programmed — verified: ICCID, IMSI; written: Ki, OPc"
        calls = _run_program(panel, True, msg)
        assert calls, "expected _set_action_status to be called"
        assert calls[-1][1] == "success"

    def test_partial_failure_shows_warning_style(self, panel):
        msg = "Card programmed — verified: ICCID, IMSI; SPN: write failed, not verified"
        calls = _run_program(panel, True, msg)
        assert calls, "expected _set_action_status to be called"
        assert calls[-1][1] == "warning"

    def test_programming_failure_shows_error_style(self, panel):
        calls = _run_program(panel, False, "pySim-prog failed: non-zero exit")
        assert calls, "expected _set_action_status to be called"
        assert calls[-1][1] == "error"
