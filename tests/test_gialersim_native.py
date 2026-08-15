"""Tests for native gialersim programming (managers/gialersim.py).

The verified recipe (docs/GIALERSIM_PROGRAMMING.md) is what makes Ki/OPc writes
actually commit on these cards. These tests lock in the invariants that pySim
got wrong and that must never regress:

- **GSM class throughout** — every APDU is CLA=A0.
- **VERIFY ADM is the first command** — no SELECT MF before it (MF is implicit
  after reset), and the fixed family key 84796153 at ref 0x0C is used, NOT the
  CSV ADM1.
- **No DF reselect between steps 2 and 6** — selecting a DF drops the ADM
  security state, so Ki/OPc/algo/ICCID all write while MF is current.
- **Abort on any non-9000** — a 9000 on a Ki write is never treated as success
  in isolation; any step failing raises GialerSimError.
- **Algorithm config (2FE5/2FE6) is written** — the piece pySim omits.
- **card_manager routes GIALERSIM natively**, bypassing pySim entirely.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from managers import gialersim
from managers.gialersim import (
    GialerSimError,
    encode_iccid,
    encode_imsi,
    program_connection,
    swap_nibbles,
)
from managers.card_manager import CardManager, CardType, CLIBackend
from state_manager import ProgramOutcome


# Realistic test vectors.
ICCID = "8946200000000000001"   # 19 digits
IMSI = "240077000000001"        # 15 digits
KI = "0123456789ABCDEF0123456789ABCDEF"
OPC = "FEDCBA9876543210FEDCBA9876543210"


# ---------------------------------------------------------------------------
# Encoding helpers (pure)
# ---------------------------------------------------------------------------

class TestEncoders:

    def test_swap_nibbles_basic(self):
        assert swap_nibbles("1234") == "2143"

    def test_swap_nibbles_is_own_inverse(self):
        assert swap_nibbles(swap_nibbles("89462000abcd")) == "89462000abcd"

    def test_swap_nibbles_rejects_odd_length(self):
        with pytest.raises(ValueError):
            swap_nibbles("123")

    def test_encode_imsi_known_vector(self):
        # parity 9 (odd), swap("9"+IMSI), length-prefixed.
        assert encode_imsi(IMSI) == "082904700700000010"

    def test_encode_imsi_is_9_bytes(self):
        assert len(encode_imsi(IMSI)) == 18  # 9 bytes

    def test_encode_iccid_is_10_bytes_and_f_padded(self):
        enc = encode_iccid(ICCID)
        assert len(enc) == 20  # 10 bytes
        # 19 digits -> odd -> f-padded; the pad nibble is swapped to the front
        # of the last byte.
        assert enc.startswith(swap_nibbles(ICCID[:2]))
        assert "f" in enc

    def test_encode_iccid_roundtrips(self):
        # Swapping back and stripping the pad recovers the ICCID.
        recovered = swap_nibbles(encode_iccid(ICCID)).rstrip("f")
        assert recovered == ICCID

    def test_encoders_reject_non_digits(self):
        with pytest.raises(ValueError):
            encode_iccid("89462000000000ABCDE")
        with pytest.raises(ValueError):
            encode_imsi("24007700000000X")


# ---------------------------------------------------------------------------
# Fake card connection
# ---------------------------------------------------------------------------

class FakeConnection:
    """Records every APDU and emulates GSM-class SELECT/GET RESPONSE/UPDATE.

    SELECT answers 9F<len> (GSM class), so _transmit issues GET RESPONSE.
    UPDATE stores data under the currently-selected fid; READ returns it, so
    ICCID/IMSI read-back matches. ``fail_on`` forces a bad SW for one fid's
    UPDATE to exercise the abort path.
    """

    def __init__(self, fail_on=None, fail_sw=(0x69, 0x82)):
        self.log = []               # list of (apdu_list)
        self.selected = None
        self.store = {}             # fid -> written bytes
        self.fail_on = fail_on
        self.fail_sw = fail_sw

    def transmit(self, apdu):
        self.log.append(list(apdu))
        cla, ins = apdu[0], apdu[1]
        if ins == 0xA4:             # SELECT
            self.selected = bytes(apdu[5:]).hex().upper()
            return [], 0x9F, 0x1B   # trigger GET RESPONSE
        if ins == 0xC0:             # GET RESPONSE
            return [0x62, 0x00], 0x90, 0x00
        if ins == 0x20:             # VERIFY
            return [], 0x90, 0x00
        if ins in (0xD6, 0xDC):     # UPDATE BINARY / UPDATE RECORD
            if self.fail_on is not None and self.selected == self.fail_on:
                return [], self.fail_sw[0], self.fail_sw[1]
            self.store[self.selected] = bytes(apdu[5:])
            return [], 0x90, 0x00
        if ins == 0xB0:             # READ BINARY
            data = self.store.get(self.selected, b"")
            return list(data), 0x90, 0x00
        return [], 0x90, 0x00

    # Convenience views over the recorded log.
    def selects(self):
        return [bytes(a[5:]).hex().upper() for a in self.log if a[1] == 0xA4]


def _run(conn=None, **overrides):
    conn = conn or FakeConnection()
    kwargs = dict(iccid=ICCID, imsi=IMSI, ki=KI, opc=OPC, acc="0001")
    kwargs.update(overrides)
    result = program_connection(conn, **kwargs)
    return conn, result


# ---------------------------------------------------------------------------
# APDU sequence invariants
# ---------------------------------------------------------------------------

class TestSequence:

    def test_all_apdus_are_gsm_class(self):
        conn, _ = _run()
        assert all(a[0] == 0xA0 for a in conn.log), "every APDU must be CLA=A0"

    def test_verify_adm_is_first_command(self):
        conn, _ = _run()
        first = conn.log[0]
        assert first[1] == 0x20, "first APDU must be VERIFY, no SELECT MF before it"
        assert first[3] == 0x0C, "VERIFY must target key reference 0x0C"

    def test_verify_uses_fixed_family_key_not_csv_adm1(self):
        # Even when a different CSV ADM1 is around, VERIFY presents 84796153.
        conn, _ = _run()
        verify = conn.log[0]
        presented = bytes(verify[5:]).decode("ascii")
        assert presented == "84796153"

    def test_no_df_reselect_before_iccid(self):
        # Steps 2-6 run with MF current; the first 3F00/7F20 SELECT must come
        # only after the ICCID (2FE2) write.
        conn, _ = _run()
        sel = conn.selects()
        iccid_idx = sel.index("2FE2")
        before = sel[:iccid_idx + 1]
        assert "3F00" not in before, "must not re-select MF before ICCID write"
        assert "7F20" not in before, "must not descend into DF_GSM before ICCID"

    def test_writes_algorithm_config(self):
        conn, _ = _run()
        sel = conn.selects()
        assert "2FE5" in sel and "2FE6" in sel, "algorithm config must be written"

    def test_key_and_identity_files_written(self):
        conn, _ = _run()
        sel = conn.selects()
        for fid in ("0100", "0200", "0B00", "0001", "6002", "2FE2", "6F07", "6F78"):
            assert fid in sel, f"expected write to {fid}"

    def test_opc_written_with_01_prefix(self):
        conn, _ = _run()
        assert conn.store["6002"] == bytes.fromhex("01" + OPC.lower())

    def test_ki_written_verbatim(self):
        conn, _ = _run()
        assert conn.store["0001"] == bytes.fromhex(KI.lower())

    def test_readback_ok_when_stored(self):
        _, (iccid_ok, imsi_ok) = _run()
        assert iccid_ok is True and imsi_ok is True

    def test_ordering_keys_before_df_descent(self):
        conn, _ = _run()
        sel = conn.selects()
        assert sel.index("0001") < sel.index("2FE2") < sel.index("6F07")


# ---------------------------------------------------------------------------
# Abort-on-failure
# ---------------------------------------------------------------------------

class TestAbort:

    def test_non_9000_on_ki_aborts(self):
        conn = FakeConnection(fail_on="0001")
        with pytest.raises(GialerSimError) as exc:
            _run(conn=conn)
        assert "Ki" in str(exc.value) or "0001" in str(exc.value).upper()

    def test_ki_failure_never_reported_as_success(self):
        # The whole point: a discarded Ki write must surface as an error, not a
        # silent pass. OPc write must not be reached after Ki fails.
        conn = FakeConnection(fail_on="0001")
        with pytest.raises(GialerSimError):
            _run(conn=conn)
        assert "6002" not in conn.store

    def test_non_9000_on_verify_aborts(self):
        conn = FakeConnection()
        conn.transmit = MagicMock(return_value=([], 0x63, 0xC9))  # wrong ADM
        with pytest.raises(GialerSimError):
            program_connection(conn, iccid=ICCID, imsi=IMSI, ki=KI, opc=OPC)

    def test_rejects_bad_lengths(self):
        with pytest.raises(ValueError):
            _run(ki="ABCD")
        with pytest.raises(ValueError):
            _run(imsi="123")
        with pytest.raises(ValueError):
            _run(iccid="123")


# ---------------------------------------------------------------------------
# program_reader: connect is retried (macOS PCSC contention)
# ---------------------------------------------------------------------------

class TestConnectRetry:
    """A fresh SCardConnect can transiently fail right after another part of the
    app released the card. program_reader must retry connect (not the write)."""

    def _install_fake_cardconnection(self, monkeypatch):
        import sys, types
        mod = types.ModuleType("smartcard.CardConnection")

        class CardConnection:
            T0_protocol = 1
            T1_protocol = 2
        mod.CardConnection = CardConnection
        if "smartcard" not in sys.modules:
            monkeypatch.setitem(sys.modules, "smartcard", types.ModuleType("smartcard"))
        monkeypatch.setitem(sys.modules, "smartcard.CardConnection", mod)

    def test_connect_retries_then_succeeds(self, monkeypatch):
        from managers import gialersim
        self._install_fake_cardconnection(monkeypatch)
        monkeypatch.setattr(gialersim.time, "sleep", lambda *_a, **_k: None)

        # Fail the first 3 connect calls (attempt 1: T0+T1, attempt 2: T0),
        # then succeed on attempt 2's T1.
        state = {"fails_left": 3}

        class RetryConn(FakeConnection):
            def connect(self, proto):
                if state["fails_left"] > 0:
                    state["fails_left"] -= 1
                    raise RuntimeError("SCARD_E_SHARING_VIOLATION")

            def disconnect(self):
                pass

            def getATR(self):
                return []

        class FakeReader:
            def createConnection(self):
                return RetryConn()

        ok = gialersim.program_reader(
            FakeReader(), iccid=ICCID, imsi=IMSI, ki=KI, opc=OPC, acc="0001",
            connect_retries=5, retry_delay=0)
        assert ok == (True, True)
        assert state["fails_left"] == 0  # all transient failures consumed

    def test_connect_exhausts_retries_raises_with_real_error(self, monkeypatch):
        from managers import gialersim
        self._install_fake_cardconnection(monkeypatch)
        monkeypatch.setattr(gialersim.time, "sleep", lambda *_a, **_k: None)

        class DeadConn(FakeConnection):
            def connect(self, proto):
                raise RuntimeError("SCARD_E_NO_SMARTCARD")

            def disconnect(self):
                pass

        class FakeReader:
            def createConnection(self):
                return DeadConn()

        with pytest.raises(GialerSimError) as exc:
            gialersim.program_reader(
                FakeReader(), iccid=ICCID, imsi=IMSI, ki=KI, opc=OPC,
                connect_retries=3, retry_delay=0)
        # The real PC/SC error must be surfaced, not a generic message.
        assert "SCARD_E_NO_SMARTCARD" in str(exc.value)


# ---------------------------------------------------------------------------
# card_manager routing (thin adapter)
# ---------------------------------------------------------------------------

def _gialersim_manager():
    cm = CardManager()
    cm.cli_backend = CLIBackend.PYSIM
    cm._venv_python = None
    cm.card_blocked = False
    cm._adm1_remaining_attempts = None
    cm.authenticated = True
    cm._authenticated_adm1_hex = "3838383838383838"
    cm.card_type = CardType.GIALERSIM
    cm._original_card_data = {}          # blank card
    cm._safety_override_acknowledged = True  # skip retry-counter probe
    return cm


class TestRouting:

    def _card_data(self):
        return {"ICCID": ICCID, "IMSI": IMSI, "Ki": KI, "OPc": OPC, "ACC": "0001"}

    def test_gialersim_routes_native_not_pysim(self):
        cm = _gialersim_manager()
        with patch.object(gialersim, "program_reader",
                          return_value=(True, True)) as native, \
             patch("managers.card_manager._init_pyscard", return_value=True), \
             patch("managers.card_manager._smartcard_readers",
                   return_value=[MagicMock()]), \
             patch.object(cm, "_run_pysim_prog") as pysim:
            ok, msg, result = cm.program_card(self._card_data(), original_data={})
        assert ok is True
        native.assert_called_once()
        pysim.assert_not_called()
        # Ki/OPc unverifiable -> pending, not verified.
        assert result.outcome == ProgramOutcome.WRITE_OK_PENDING
        assert "Ki" in result.written_only_fields

    def test_native_forwards_fixed_recipe_fields(self):
        cm = _gialersim_manager()
        with patch.object(gialersim, "program_reader",
                          return_value=(True, True)) as native, \
             patch("managers.card_manager._init_pyscard", return_value=True), \
             patch("managers.card_manager._smartcard_readers",
                   return_value=[MagicMock()]):
            cm.program_card(self._card_data(), original_data={})
        kwargs = native.call_args.kwargs
        assert kwargs["iccid"] == ICCID
        assert kwargs["imsi"] == IMSI
        assert kwargs["ki"] == KI
        assert kwargs["opc"] == OPC

    def test_native_failure_surfaces_write_failed(self):
        cm = _gialersim_manager()
        with patch.object(gialersim, "program_reader",
                          side_effect=GialerSimError("UPDATE Ki failed: SW=6982")), \
             patch("managers.card_manager._init_pyscard", return_value=True), \
             patch("managers.card_manager._smartcard_readers",
                   return_value=[MagicMock()]):
            ok, msg, result = cm.program_card(self._card_data(), original_data={})
        assert ok is False
        assert result.outcome == ProgramOutcome.WRITE_FAILED

    def test_readback_mismatch_surfaces_verification_failed(self):
        cm = _gialersim_manager()
        with patch.object(gialersim, "program_reader",
                          return_value=(False, True)), \
             patch("managers.card_manager._init_pyscard", return_value=True), \
             patch("managers.card_manager._smartcard_readers",
                   return_value=[MagicMock()]):
            ok, msg, result = cm.program_card(self._card_data(), original_data={})
        assert ok is False
        assert result.outcome == ProgramOutcome.WRITE_OK_VERIFICATION_FAILED
        assert "ICCID" in result.failed_fields


# ---------------------------------------------------------------------------
# UI: ADM1 is greyed "Hardcoded" for gialersim (the ADM is a fixed key)
# ---------------------------------------------------------------------------

class TestAdm1GreyOut:
    """gialersim uses a fixed built-in ADM key, so the ADM1 field is disabled.

    Uses the panel's methods bound to a MagicMock stub (the same pattern the
    other program-panel unit tests use) — no QApplication required.
    """

    def _lock_stub(self, card_type):
        import types
        from widgets.program_sim_panel import ProgramSIMPanel, _FORM_FIELDS
        stub = MagicMock()
        stub._cm = MagicMock()
        stub._cm.card_type = card_type
        stub._field_entries = {k: MagicMock() for k, _, _ in _FORM_FIELDS}
        stub._is_gialersim = types.MethodType(ProgramSIMPanel._is_gialersim, stub)
        stub._apply_adm1_card_type_lock = types.MethodType(
            ProgramSIMPanel._apply_adm1_card_type_lock, stub)
        return stub

    def test_gialersim_greys_adm1(self):
        stub = self._lock_stub(CardType.GIALERSIM)
        stub._apply_adm1_card_type_lock()
        adm1 = stub._field_entries["ADM1"]
        adm1.setEnabled.assert_called_with(False)
        adm1.setReadOnly.assert_called_with(True)
        adm1.setPlaceholderText.assert_called_with("Hardcoded")
        adm1.clear.assert_called()

    def test_non_gialersim_restores_adm1(self):
        stub = self._lock_stub(CardType.SJA5)
        stub._apply_adm1_card_type_lock()
        adm1 = stub._field_entries["ADM1"]
        adm1.setEnabled.assert_called_with(True)
        adm1.setReadOnly.assert_called_with(False)
        adm1.setPlaceholderText.assert_called_with("")

    def test_gialersim_disables_and_unchecks_suci(self):
        """SUCI must be forced OFF and disabled for gialersim, keyed on the
        authoritative CardManager enum (not the CardInfo display string, which
        never equals the enum and silently disabled this whole handler)."""
        import types
        from widgets.program_sim_panel import ProgramSIMPanel
        stub = MagicMock()
        stub._cm = MagicMock()
        stub._cm.card_type = CardType.GIALERSIM
        stub._suci_checkbox = MagicMock()
        stub._suci_checkbox.isChecked.return_value = False  # skip the warning dialog
        stub._handle_suci_for_card_type = types.MethodType(
            ProgramSIMPanel._handle_suci_for_card_type, stub)

        stub._handle_suci_for_card_type(MagicMock())

        stub._suci_checkbox.setChecked.assert_called_with(False)
        stub._suci_checkbox.setEnabled.assert_called_with(False)

    def test_on_program_supplies_hardcoded_adm_for_gialersim(self):
        """Empty ADM1 field must NOT abort for gialersim — the fixed family key
        is supplied to authenticate() so the shared gate is satisfied."""
        import types
        from managers.gialersim import ADM_ASCII
        from widgets.program_sim_panel import ProgramSIMPanel, _FORM_FIELDS

        stub = MagicMock()
        stub._cm = MagicMock()
        stub._cm.card_type = CardType.GIALERSIM
        stub._step = 1
        stub._extra_card_data = {}
        stub._original_form_data = {}
        stub._card_watcher = None
        stub._field_entries = {}
        for key, _, _ in _FORM_FIELDS:
            m = MagicMock()
            m.text.return_value = ""          # ADM1 (and all) empty
            stub._field_entries[key] = m
        stub._get_hnet_pubkey = MagicMock(return_value="")
        stub._suci_checkbox = MagicMock()
        stub._suci_checkbox.isChecked.return_value = False
        stub._cm.authenticate.return_value = (True, "OK")
        stub._cm.program_card.return_value = (
            True, "OK",
            __import__("state_manager").ProgramResult(
                outcome=ProgramOutcome.WRITE_OK_PENDING, message="OK"))
        stub._set_action_status = MagicMock()
        stub._set_sticky_result = MagicMock()
        stub._clear_sticky_result = MagicMock()
        stub.on_card_programmed_callback = None
        stub._is_gialersim = types.MethodType(ProgramSIMPanel._is_gialersim, stub)
        stub._on_program = types.MethodType(ProgramSIMPanel._on_program, stub)

        stub._on_program()

        stub._cm.authenticate.assert_called_once()
        assert stub._cm.authenticate.call_args[0][0] == ADM_ASCII
        stub._cm.program_card.assert_called_once()
        # It must not have aborted with the "ADM1 is required" warning.
        for call in stub._set_action_status.call_args_list:
            assert "ADM1 is required" not in call[0][0]
