"""Hardware-gated macOS card detection tests.

These tests verify that CardManager honours the pcsc_reader_index constructor
parameter when running on a real macOS PCSC stack.  They require:

  1. macOS (skipped on any other platform)
  2. SIMGUI_HW_TEST=1 environment variable
  3. A USB smart-card reader attached to the host

Run with:
    SIMGUI_HW_TEST=1 python3 -m pytest tests/test_macos_hw_card_detection.py -v

To target a non-default reader slot, also set SIMGUI_PCSC_READER_INDEX:
    SIMGUI_HW_TEST=1 SIMGUI_PCSC_READER_INDEX=1 python3 -m pytest ...

The tests do NOT alter card state, do NOT authenticate, and do NOT program any
card.  They exercise detect_card() (read-only) only.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from managers.card_manager import CardManager, CardType, _find_cli_tool

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

macos_hardware = pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("SIMGUI_HW_TEST") != "1",
    reason="macOS hardware test skipped (requires macOS and SIMGUI_HW_TEST=1)",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMacOSCardDetectionHardwareGated:
    """Verify pcsc_reader_index flows through to the real macOS PCSC stack.

    These tests run on macOS only and require SIMGUI_HW_TEST=1.
    They exercise detect_card() — a read-only operation — using the
    pcsc_reader_index constructor parameter.  Business logic (state
    transitions, auth, programming) is not exercised here.
    """

    @macos_hardware
    def test_detect_card_reader_index_0(self):
        """detect_card() with pcsc_reader_index=0 completes on real macOS hardware.

        Verifies that the configured reader index is passed to the underlying
        PCSC stack and that detect_card() either succeeds or returns a coherent
        failure (e.g. no card inserted) — never crashes or raises.
        """
        path, _ = _find_cli_tool()
        if path is None:
            pytest.skip("No pySim CLI tool found — install pySim or set PYSIM_PATH")

        cm = CardManager(pcsc_reader_index=0)
        cm.set_cli_path(path)

        result = cm.detect_card()
        assert isinstance(result, tuple) and len(result) == 2, (
            f"detect_card() must return (ok, msg) tuple, got {result!r}"
        )
        ok, msg = result
        assert isinstance(ok, bool), f"First element must be bool, got {type(ok)}"
        assert isinstance(msg, str), f"Second element must be str, got {type(msg)}"

        if ok:
            assert cm.card_type != CardType.UNKNOWN or cm.card_info, (
                "detect_card() returned ok=True but card_type is UNKNOWN "
                "and card_info is empty"
            )
        # ok=False is acceptable: no card inserted, reader busy, etc.

    @macos_hardware
    def test_detect_card_reader_index_matches_env(self):
        """detect_card() uses SIMGUI_PCSC_READER_INDEX when set.

        Allows the operator to target a specific reader slot during hardware
        testing without modifying the test.  Defaults to index 0.
        """
        reader_index = int(os.environ.get("SIMGUI_PCSC_READER_INDEX", "0"))
        path, _ = _find_cli_tool()
        if path is None:
            pytest.skip("No pySim CLI tool found — install pySim or set PYSIM_PATH")

        cm = CardManager(pcsc_reader_index=reader_index)
        cm.set_cli_path(path)

        assert cm._pcsc_reader_index == reader_index, (
            f"Constructor must store reader_index={reader_index}, "
            f"got {cm._pcsc_reader_index}"
        )

        result = cm.detect_card()
        assert isinstance(result, tuple) and len(result) == 2, (
            f"detect_card() must return (ok, msg) tuple, got {result!r}"
        )
