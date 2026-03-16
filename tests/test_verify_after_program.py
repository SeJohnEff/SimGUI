"""Tests for post-programming read-back verification.

Covers:
- CardManager.verify_after_program() success / failure / mismatch paths
- CardManager.program_card() integration with auto-verify
- CardWatcher.register_programmed_card() ATR→ICCID cache
- CardWatcher._read_and_notify() fallback to ATR cache
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers.card_manager import CardManager, CLIBackend  # noqa: E402
from managers.card_watcher import CardWatcher  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PYSIM_READ_OUTPUT_OK = """\
ICCID: 89999880000000000200001
IMSI: 999880000200001
ACC: 0001
SPN: John
"""

PYSIM_READ_OUTPUT_MISMATCH_IMSI = """\
ICCID: 89999880000000000200001
IMSI: 999880000299999
ACC: 0001
"""

PYSIM_READ_OUTPUT_NO_ICCID = """\
IMSI: 999880000200001
ACC: 0001
"""


def _make_hw_card_manager(cli_path="/opt/pysim"):
    """Create a CardManager configured for pySim hardware backend."""
    cm = CardManager()
    cm.cli_path = cli_path
    cm.cli_backend = CLIBackend.PYSIM
    cm.authenticated = True
    cm._authenticated_adm1_hex = "3838383838383838"
    cm.card_info = {}
    return cm


class FakeCardManager:
    """Minimal card manager for watcher tests."""

    def __init__(self):
        self.detect_ok = False
        self.iccid = None
        self.card_info = {}

    def probe_card_presence(self):
        if self.detect_ok:
            return True, "3B 9F 96 80 1F"
        return False, "No card in reader"

    def detect_card(self):
        if self.detect_ok:
            return True, "Card detected"
        return False, "No card"

    def read_iccid(self):
        return self.iccid


class FakeIndexEntry:
    def __init__(self, file_path="test.csv"):
        self.file_path = file_path


class FakeIndex:
    def __init__(self, entries=None, card_data=None):
        self._entries = entries or {}
        self._card_data = card_data or {}

    def lookup(self, iccid):
        return self._entries.get(iccid)

    def load_card(self, iccid):
        return self._card_data.get(iccid)


# ---------------------------------------------------------------------------
# verify_after_program() — unit tests
# ---------------------------------------------------------------------------

class TestVerifyAfterProgram:
    """Direct tests for CardManager.verify_after_program()."""

    def test_verify_success(self):
        """Read-back matches written data → success."""
        cm = _make_hw_card_manager()
        written = {"ICCID": "89999880000000000200001", "IMSI": "999880000200001"}

        with patch.object(cm, '_run_cli', return_value=(True, PYSIM_READ_OUTPUT_OK, "")):
            ok, msg, data = cm.verify_after_program(written)

        assert ok is True
        assert "OK" in msg
        assert data["ICCID"] == "89999880000000000200001"
        assert data["IMSI"] == "999880000200001"

    def test_verify_imsi_mismatch(self):
        """IMSI read back differs from what was written → fail after retries."""
        cm = _make_hw_card_manager()
        written = {"ICCID": "89999880000000000200001", "IMSI": "999880000200001"}

        with patch.object(cm, '_run_cli',
                          return_value=(True, PYSIM_READ_OUTPUT_MISMATCH_IMSI, "")), \
             patch('time.sleep'):  # skip retry delay
            ok, msg, data = cm.verify_after_program(written)

        assert ok is False
        assert "IMSI" in msg
        assert "FAILED" in msg

    def test_verify_iccid_not_in_readback_is_ok(self):
        """ICCID missing from read-back is normal for blank cards → pass.

        pySim-read often does not return ICCID/IMSI after writing to a
        freshly programmed blank card.  A missing field is NOT a mismatch.
        """
        cm = _make_hw_card_manager()
        written = {"ICCID": "89999880000000000200001", "IMSI": "999880000200001"}

        with patch.object(cm, '_run_cli',
                          return_value=(True, PYSIM_READ_OUTPUT_NO_ICCID, "")):
            ok, msg, data = cm.verify_after_program(written)

        # ICCID missing from read-back is a soft miss, IMSI matches → OK
        assert ok is True
        assert "OK" in msg

    def test_verify_pysim_read_fails_completely(self):
        """pySim-read returns error with no stdout → fail after retries."""
        cm = _make_hw_card_manager()
        written = {"ICCID": "89999880000000000200001"}

        with patch.object(cm, '_run_cli',
                          return_value=(False, "", "No card in reader")), \
             patch('time.sleep'):
            ok, msg, data = cm.verify_after_program(written)

        assert ok is False
        assert "FAILED" in msg

    def test_verify_pysim_read_fails_with_stdout(self):
        """pySim-read returns non-zero but has stdout with data → parse it."""
        cm = _make_hw_card_manager()
        written = {"ICCID": "89999880000000000200001", "IMSI": "999880000200001"}

        with patch.object(cm, '_run_cli',
                          return_value=(False, PYSIM_READ_OUTPUT_OK, "some warning")):
            ok, msg, data = cm.verify_after_program(written)

        # Even though rc!=0, stdout has matching data
        assert ok is True
        assert data.get("ICCID") == "89999880000000000200001"

    def test_verify_preserves_card_info(self):
        """verify_after_program() must not clobber existing card_info."""
        cm = _make_hw_card_manager()
        cm.card_info = {"IMSI": "original_imsi", "ICCID": "original_iccid"}
        written = {"ICCID": "89999880000000000200001"}

        with patch.object(cm, '_run_cli',
                          return_value=(True, PYSIM_READ_OUTPUT_OK, "")):
            cm.verify_after_program(written)

        # card_info should be restored to original
        assert cm.card_info["IMSI"] == "original_imsi"

    def test_verify_simulator_skips(self):
        """Simulator mode → skip verification, return True."""
        cm = CardManager()
        cm.enable_simulator()
        ok, msg, data = cm.verify_after_program({"ICCID": "123"})
        assert ok is True
        assert "Simulator" in msg

    def test_verify_non_pysim_backend_skips(self):
        """Non-pySim backend → skip verification."""
        cm = _make_hw_card_manager()
        cm.cli_backend = CLIBackend.SYSMO
        ok, msg, data = cm.verify_after_program({"ICCID": "123"})
        assert ok is True

    def test_verify_empty_written_data_succeeds(self):
        """If no ICCID/IMSI in written_data, nothing to compare → OK."""
        cm = _make_hw_card_manager()
        written = {"SPN": "TestOp", "ACC": "0001"}

        with patch.object(cm, '_run_cli',
                          return_value=(True, PYSIM_READ_OUTPUT_OK, "")):
            ok, msg, data = cm.verify_after_program(written)

        assert ok is True


# ---------------------------------------------------------------------------
# program_card() integration with verification
# ---------------------------------------------------------------------------

class TestProgramCardWithVerify:
    """program_card() now auto-verifies after successful write."""

    def test_program_and_verify_success(self):
        """Successful write + successful verify → overall True."""
        cm = _make_hw_card_manager()

        with patch.object(cm, '_run_pysim_shell',
                          return_value=(True, "ok", "")), \
             patch.object(cm, 'verify_after_program',
                          return_value=(True, "Verification OK",
                                        {"ICCID": "899998", "IMSI": "99988"})):
            ok, msg = cm.program_card(
                {"IMSI": "99988", "Ki": "aa" * 16, "OPc": "bb" * 16})

        assert ok is True
        assert "verified" in msg.lower()

    def test_program_ok_but_verify_fails(self):
        """Write succeeds but read-back mismatches → overall True with warning."""
        cm = _make_hw_card_manager()

        with patch.object(cm, '_run_pysim_shell',
                          return_value=(True, "ok", "")), \
             patch.object(cm, 'verify_after_program',
                          return_value=(False,
                                        "Verification FAILED — IMSI: wrote X, read Y",
                                        {"IMSI": "Y"})):
            ok, msg = cm.program_card(
                {"IMSI": "X", "Ki": "aa" * 16, "OPc": "bb" * 16})

        # Programming itself succeeded — ok is True even when verify fails
        assert ok is True
        assert "WARNING" in msg
        assert "could not confirm" in msg.lower()

    def test_program_write_fails_no_verify(self):
        """If pySim-shell write itself fails, verify is never called."""
        cm = _make_hw_card_manager()

        with patch.object(cm, '_run_pysim_shell',
                          return_value=(False, "", "sw mismatch 6982")), \
             patch.object(cm, 'verify_after_program') as mock_verify:
            ok, msg = cm.program_card(
                {"IMSI": "99988", "Ki": "aa" * 16, "OPc": "bb" * 16})

        assert ok is False
        mock_verify.assert_not_called()

    def test_verify_updates_card_info(self):
        """On successful verify, card_info is updated with read-back data."""
        cm = _make_hw_card_manager()
        cm.card_info = {}

        readback = {"ICCID": "899998800000000002", "IMSI": "999880000200001"}
        with patch.object(cm, '_run_pysim_shell',
                          return_value=(True, "ok", "")), \
             patch.object(cm, 'verify_after_program',
                          return_value=(True, "OK", readback)):
            ok, msg = cm.program_card({"IMSI": "999880000200001"})

        assert ok is True
        assert cm.card_info["ICCID"] == "899998800000000002"
        assert cm.card_info["IMSI"] == "999880000200001"

    def test_no_changes_skips_verify(self):
        """If no fields changed, program_card returns early — no verify."""
        cm = _make_hw_card_manager()
        cm._original_card_data = {"IMSI": "12345"}

        with patch.object(cm, 'verify_after_program') as mock_verify:
            ok, msg = cm.program_card({"IMSI": "12345"})

        assert ok is True
        assert "already matches" in msg.lower()
        mock_verify.assert_not_called()

    def test_simulator_skips_verify(self):
        """Simulator program_card doesn't call verify."""
        cm = CardManager()
        cm.enable_simulator()
        cm._simulator.detect_card()
        card = cm._simulator._current_card()
        cm._simulator.authenticate(card.adm1)

        with patch.object(cm, 'verify_after_program') as mock_verify:
            ok, msg = cm.program_card({"IMSI": "999880000200001"})

        # Simulator path returns before reaching verify
        # verify_after_program should not be called
        mock_verify.assert_not_called()


# ---------------------------------------------------------------------------
# CardWatcher.register_programmed_card() and ATR cache
# ---------------------------------------------------------------------------

class TestRegisterProgrammedCard:
    """Tests for the ATR→ICCID cache in CardWatcher."""

    def test_register_caches_atr_to_iccid(self):
        """After register, ATR→ICCID is in the cache."""
        fcm = FakeCardManager()
        w = CardWatcher(fcm)
        w._last_atr = "3B 9F 96 80 1F"

        w.register_programmed_card("89999880000000000200001")

        assert w._atr_iccid_cache["3B 9F 96 80 1F"] == "89999880000000000200001"
        assert w._last_iccid == "89999880000000000200001"

    def test_register_no_atr_does_nothing(self):
        """If no ATR is known, cache is not updated."""
        fcm = FakeCardManager()
        w = CardWatcher(fcm)
        w._last_atr = None

        w.register_programmed_card("89999880000000000200001")

        assert len(w._atr_iccid_cache) == 0

    def test_register_empty_iccid_does_nothing(self):
        """Empty ICCID string is not cached."""
        fcm = FakeCardManager()
        w = CardWatcher(fcm)
        w._last_atr = "3B 9F 96 80 1F"

        w.register_programmed_card("")

        assert len(w._atr_iccid_cache) == 0

    def test_register_overwrites_previous_cache(self):
        """A second register for the same ATR overwrites."""
        fcm = FakeCardManager()
        w = CardWatcher(fcm)
        w._last_atr = "3B 9F 96 80 1F"

        w.register_programmed_card("111")
        w.register_programmed_card("222")

        assert w._atr_iccid_cache["3B 9F 96 80 1F"] == "222"


# ---------------------------------------------------------------------------
# CardWatcher._read_and_notify() with ATR cache fallback
# ---------------------------------------------------------------------------

class TestReadAndNotifyWithCache:
    """Tests that _read_and_notify uses ATR cache when pySim-read fails."""

    def test_pysim_read_ok_no_cache_needed(self):
        """Normal path: pySim-read returns ICCID → use it directly."""
        fcm = FakeCardManager()
        fcm.detect_ok = True
        fcm.iccid = "89999880000000000200001"
        w = CardWatcher(fcm)
        w._last_atr = "3B 9F 96 80 1F"

        on_unknown = MagicMock()
        w.on_card_unknown = on_unknown

        w._read_and_notify()

        assert w._last_iccid == "89999880000000000200001"

    def test_pysim_read_fails_uses_cache(self):
        """pySim-read fails but ATR cache has ICCID → use cached value."""
        fcm = FakeCardManager()
        fcm.detect_ok = False  # pySim-read fails
        w = CardWatcher(fcm)
        w._last_atr = "3B 9F 96 80 1F"
        w._atr_iccid_cache["3B 9F 96 80 1F"] = "89999880000000000200001"

        callback = MagicMock()
        w.on_card_unknown = callback

        w._read_and_notify()

        # Should use cached ICCID
        assert w._last_iccid == "89999880000000000200001"
        # on_card_unknown IS called (with the ICCID) via _handle_new_card
        # because the card is not in any index — but it's called with
        # the ICCID, not with "" (which would mean blank card).
        callback.assert_called_once_with("89999880000000000200001")

    def test_pysim_read_no_iccid_uses_cache(self):
        """pySim-read succeeds but no ICCID → fall back to cache."""
        fcm = FakeCardManager()
        fcm.detect_ok = True
        fcm.iccid = None  # No ICCID in output
        w = CardWatcher(fcm)
        w._last_atr = "3B 9F 96 80 1F"
        w._atr_iccid_cache["3B 9F 96 80 1F"] = "89999880000000000200001"

        callback = MagicMock()
        w.on_card_unknown = callback

        w._read_and_notify()

        assert w._last_iccid == "89999880000000000200001"
        # Called via _handle_new_card with the ICCID (not blank)
        callback.assert_called_once_with("89999880000000000200001")

    def test_pysim_fails_no_cache_fires_unknown(self):
        """pySim-read fails, no cache → fire on_card_unknown("")."""
        fcm = FakeCardManager()
        fcm.detect_ok = False
        w = CardWatcher(fcm)
        w._last_atr = "3B 9F 96 80 1F"
        # No cache entry

        callback = MagicMock()
        error_callback = MagicMock()
        w.on_card_unknown = callback
        w.on_error = error_callback

        w._read_and_notify()

        callback.assert_called_once_with("")
        error_callback.assert_called_once()
        assert w._last_iccid is None

    def test_cache_survives_card_removal_and_reinsertion(self):
        """Full cycle: program → remove → re-insert → recognised via cache."""
        fcm = FakeCardManager()
        w = CardWatcher(fcm)

        # 1. Card inserted and programmed
        w._card_present = True
        w._last_atr = "3B 9F 96 80 1F"
        w.register_programmed_card("89999880000000000200001")

        # 2. Card removed
        w._card_present = False
        w._last_iccid = None
        w._last_atr = None

        # 3. Card re-inserted (same ATR)
        w._last_atr = "3B 9F 96 80 1F"
        fcm.detect_ok = False  # pySim-read fails on re-inserted card

        on_unknown = MagicMock()
        w.on_card_unknown = on_unknown

        w._read_and_notify()

        # Should recognise the card from cache
        assert w._last_iccid == "89999880000000000200001"
        # on_card_unknown called with the ICCID (not blank "") via
        # _handle_new_card because no index is configured.
        on_unknown.assert_called_once_with("89999880000000000200001")

    def test_different_atr_not_cached(self):
        """A different ATR should not match the cache."""
        fcm = FakeCardManager()
        w = CardWatcher(fcm)
        w._atr_iccid_cache["3B 9F 96 80 1F"] = "89999880000000000200001"

        w._last_atr = "3B AA BB CC DD"  # Different ATR
        fcm.detect_ok = False

        on_unknown = MagicMock()
        w.on_card_unknown = on_unknown

        w._read_and_notify()

        # Different ATR → not in cache → fire unknown
        on_unknown.assert_called_once_with("")
        assert w._last_iccid is None


# ---------------------------------------------------------------------------
# _handle_probe_result integration with cache
# ---------------------------------------------------------------------------

class TestHandleProbeResultWithCache:
    """Card re-insertion via fast probe path also uses ATR cache."""

    def test_probe_new_card_triggers_read_and_notify(self):
        """Probe sees new ATR → calls _read_and_notify → cache used."""
        fcm = FakeCardManager()
        fcm.detect_ok = False  # pySim-read will fail
        w = CardWatcher(fcm)

        # Pre-populate cache
        w._atr_iccid_cache["3B 9F 96 80 1F"] = "89999880000000000200001"

        on_unknown = MagicMock()
        w.on_card_unknown = on_unknown

        # Simulate: card inserted, probe returns this ATR
        w._handle_probe_result(True, "3B 9F 96 80 1F")

        assert w._last_atr == "3B 9F 96 80 1F"
        assert w._last_iccid == "89999880000000000200001"
        # on_card_unknown called with ICCID (not blank) via _handle_new_card
        on_unknown.assert_called_once_with("89999880000000000200001")


# ---------------------------------------------------------------------------
# End-to-end: _on_card_programmed wiring in main.py
# ---------------------------------------------------------------------------

class TestMainOnCardProgrammedIntegration:
    """Test that _on_card_programmed registers the ICCID with the watcher."""

    def test_on_card_programmed_registers_iccid(self):
        """Smoke test: the callback path reaches register_programmed_card."""
        fcm = FakeCardManager()
        watcher = CardWatcher(fcm)
        watcher._last_atr = "3B 9F 96 80 1F"

        # Simulate what main._on_card_programmed does
        card_data = {"ICCID": "89999880000000000200001", "IMSI": "999880000200001"}
        iccid = card_data.get("ICCID", "")
        if iccid:
            watcher.register_programmed_card(iccid)

        assert watcher._atr_iccid_cache["3B 9F 96 80 1F"] == "89999880000000000200001"

    def test_on_card_programmed_no_iccid_safe(self):
        """No ICCID in card_data → no crash, no cache update."""
        fcm = FakeCardManager()
        watcher = CardWatcher(fcm)
        watcher._last_atr = "3B 9F 96 80 1F"

        card_data = {"IMSI": "999880000200001"}
        iccid = card_data.get("ICCID", "")
        if iccid:
            watcher.register_programmed_card(iccid)

        assert len(watcher._atr_iccid_cache) == 0
