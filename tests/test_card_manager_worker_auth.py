"""Tests for CardManager.authenticate() worker branch (Phase 3D)."""

import pytest
from unittest.mock import MagicMock, patch


def _make_manager():
    """Return a CardManager with worker client attached and basic state set."""
    from managers.card_manager import CardManager, CardType
    mgr = CardManager.__new__(CardManager)
    # Minimal init — replicate only what authenticate() needs
    mgr._worker_client = None
    mgr._current_session_id = None
    mgr._current_card_gen = None
    mgr.card_blocked = False
    mgr._adm1_remaining_attempts = None
    mgr._authenticated_adm1_hex = None
    mgr.authenticated = False
    mgr._safety_override_acknowledged = False
    mgr._original_card_data = {"ICCID": "1234567890123456789", "IMSI": "240010123456789"}
    mgr.card_type = CardType.SJA5
    mgr.card_info = {"ICCID": "1234567890123456789"}
    mgr.cli_backend = __import__("managers.card_manager", fromlist=["CLIBackend"]).CLIBackend.PYSIM
    return mgr


def _attach_worker(mgr, result):
    """Attach a mock worker client that returns result from authenticate()."""
    from card_worker_client import AuthResult
    client = MagicMock()
    client.authenticate.return_value = result
    mgr._worker_client = client
    mgr._current_session_id = "sess-abc"
    mgr._current_card_gen = 1
    return client


def _auth_result(**kw):
    from card_worker_client import AuthResult
    return AuthResult(**kw)


# ---------------------------------------------------------------------------
# 1. Success non-deferred — sets authenticated and adm1_hex
# ---------------------------------------------------------------------------
def test_success_non_deferred():
    mgr = _make_manager()
    _attach_worker(mgr, _auth_result(ok=True, deferred=False))
    ok, msg = mgr.authenticate("88888888")
    assert ok is True
    assert mgr.authenticated is True
    assert mgr._authenticated_adm1_hex is not None
    assert "successful" in msg.lower()


# ---------------------------------------------------------------------------
# 2. Success deferred — sets authenticated and returns stored/deferred message
# ---------------------------------------------------------------------------
def test_success_deferred():
    mgr = _make_manager()
    _attach_worker(mgr, _auth_result(ok=True, deferred=True))
    ok, msg = mgr.authenticate("88888888")
    assert ok is True
    assert mgr.authenticated is True
    assert mgr._authenticated_adm1_hex is not None
    assert "stored" in msg.lower() or "programming" in msg.lower()


# ---------------------------------------------------------------------------
# 3. AUTH_FAILED — returns False, does NOT call _run_pysim_shell_safe
# ---------------------------------------------------------------------------
def test_auth_failed_no_native_fallback():
    mgr = _make_manager()
    client = _attach_worker(mgr, _auth_result(ok=False, error="AUTH_FAILED"))
    with patch.object(mgr.__class__, "_run_pysim_shell_safe") as shell_mock:
        ok, msg = mgr.authenticate("88888888")
    assert ok is False
    assert "wrong" in msg.lower() or "failed" in msg.lower()
    shell_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 4. CARD_BLOCKED — sets card_blocked and _adm1_remaining_attempts=0
# ---------------------------------------------------------------------------
def test_card_blocked_sets_state():
    mgr = _make_manager()
    _attach_worker(mgr, _auth_result(ok=False, error="CARD_BLOCKED"))
    ok, msg = mgr.authenticate("88888888")
    assert ok is False
    assert mgr.card_blocked is True
    assert mgr._adm1_remaining_attempts == 0
    assert "locked" in msg.lower()


# ---------------------------------------------------------------------------
# 5. STALE_SESSION — clears session ids
# ---------------------------------------------------------------------------
def test_stale_session_clears_session():
    mgr = _make_manager()
    _attach_worker(mgr, _auth_result(ok=False, error="STALE_SESSION"))
    ok, msg = mgr.authenticate("88888888")
    assert ok is False
    assert mgr._current_session_id is None
    assert mgr._current_card_gen is None


# ---------------------------------------------------------------------------
# 6. WORKER_DEAD — does NOT clear _worker_client, does NOT call native path
# ---------------------------------------------------------------------------
def test_worker_dead_no_clear_no_native():
    mgr = _make_manager()
    client = _attach_worker(mgr, _auth_result(ok=False, error="WORKER_DEAD"))
    with patch.object(mgr.__class__, "_run_pysim_shell_safe") as shell_mock:
        ok, msg = mgr.authenticate("88888888")
    assert ok is False
    assert mgr._worker_client is client  # not cleared
    shell_mock.assert_not_called()
    assert "worker" in msg.lower() or "died" in msg.lower() or "restart" in msg.lower()


# ---------------------------------------------------------------------------
# 7. NO_PROFILE — returns False
# ---------------------------------------------------------------------------
def test_no_profile_returns_false():
    mgr = _make_manager()
    _attach_worker(mgr, _auth_result(ok=False, error="NO_PROFILE"))
    ok, msg = mgr.authenticate("88888888")
    assert ok is False
    assert "profile" in msg.lower() or "detect" in msg.lower()


# ---------------------------------------------------------------------------
# 8. TRANSPORT_ERROR — returns False
# ---------------------------------------------------------------------------
def test_transport_error_returns_false():
    mgr = _make_manager()
    _attach_worker(mgr, _auth_result(ok=False, error="TRANSPORT_ERROR"))
    ok, msg = mgr.authenticate("88888888")
    assert ok is False
    assert "transport" in msg.lower() or "reader" in msg.lower()


# ---------------------------------------------------------------------------
# 9. Missing session — returns False without calling native path
# ---------------------------------------------------------------------------
def test_missing_session_no_native():
    mgr = _make_manager()
    from card_worker_client import AuthResult
    client = MagicMock()
    mgr._worker_client = client
    mgr._current_session_id = None   # session not ready
    mgr._current_card_gen = None
    with patch.object(mgr.__class__, "_run_pysim_shell_safe") as shell_mock:
        ok, msg = mgr.authenticate("88888888")
    assert ok is False
    assert "session" in msg.lower() or "not ready" in msg.lower() or "re-detect" in msg.lower()
    client.authenticate.assert_not_called()
    shell_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 10. card_blocked pre-check fires before worker call
# ---------------------------------------------------------------------------
def test_card_blocked_precheck_before_worker():
    mgr = _make_manager()
    client = _attach_worker(mgr, _auth_result(ok=True, deferred=False))
    mgr.card_blocked = True
    ok, msg = mgr.authenticate("88888888")
    assert ok is False
    assert "locked" in msg.lower()
    client.authenticate.assert_not_called()


# ---------------------------------------------------------------------------
# 11. Bad ADM1 validation fires before worker call
# ---------------------------------------------------------------------------
def test_bad_adm1_before_worker():
    mgr = _make_manager()
    client = _attach_worker(mgr, _auth_result(ok=True, deferred=False))
    ok, msg = mgr.authenticate("BADKEY!!!")
    assert ok is False
    client.authenticate.assert_not_called()


# ---------------------------------------------------------------------------
# 12. expected_iccid does NOT read ICCID via PCSC in worker mode
# ---------------------------------------------------------------------------
def test_expected_iccid_no_pcsc_read_in_worker_mode():
    mgr = _make_manager()
    _attach_worker(mgr, _auth_result(ok=True, deferred=False))
    with patch.object(mgr.__class__, "read_iccid") as riccid_mock:
        ok, msg = mgr.authenticate("88888888", expected_iccid="1234567890123456789")
    assert ok is True
    # read_iccid should NOT be called in worker mode
    riccid_mock.assert_not_called()
