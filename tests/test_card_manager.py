"""Tests for managers.card_manager module."""

import pytest

from managers.card_manager import CardManager, CardType, CLIBackend


class TestCardManagerInit:
    def test_initial_state(self, card_manager):
        assert card_manager.card_type == CardType.UNKNOWN
        assert card_manager.authenticated is False
        assert card_manager.card_info == {}

    def test_cli_backend_detected(self, card_manager):
        # In test env, no CLI tool is expected
        assert card_manager.cli_backend in (
            CLIBackend.NONE, CLIBackend.SYSMO, CLIBackend.PYSIM)


class TestCardManagerDetect:
    def test_detect_without_cli(self, card_manager):
        card_manager.cli_path = None
        card_manager.cli_backend = CLIBackend.NONE
        ok, msg = card_manager.detect_card()
        assert ok is False
        assert 'not found' in msg.lower() or 'no cli' in msg.lower()


class TestCardManagerAuth:
    def test_authenticate_invalid_adm1(self, card_manager):
        ok, msg = card_manager.authenticate('bad')
        assert ok is False

    def test_authenticate_no_backend_fails(self, card_manager):
        """Without a CLI backend, valid ADM1 should still fail."""
        card_manager.cli_backend = CLIBackend.NONE
        ok, msg = card_manager.authenticate('12345678')
        assert ok is False
        assert 'not supported' in msg.lower()

    def test_authenticate_empty_adm1_passes_validation(self, card_manager):
        """Empty ADM1 passes validate_adm1 (field is optional in validation)."""
        # With no backend, empty ADM1 goes through validation
        # but fails on backend check
        card_manager.cli_backend = CLIBackend.NONE
        ok, msg = card_manager.authenticate('')
        assert ok is False

    def test_authenticate_iccid_mismatch(self, card_manager):
        """ICCID cross-check prevents auth when card doesn't match."""
        card_manager.card_info = {'ICCID': '89440000000000000001'}
        ok, msg = card_manager.authenticate(
            '12345678', expected_iccid='89440000000000000099')
        assert ok is False
        assert 'mismatch' in msg.lower()


class TestCardManagerOperations:
    def test_read_card_unauthenticated(self, card_manager):
        assert card_manager.read_card_data() is None

    def test_program_card_unauthenticated(self, card_manager):
        ok, msg = card_manager.program_card({})
        assert ok is False

    def test_disconnect(self, card_manager):
        card_manager.authenticated = True
        card_manager.card_type = CardType.SJA2
        card_manager.disconnect()
        assert card_manager.authenticated is False
        assert card_manager.card_type == CardType.UNKNOWN

    def test_get_remaining_attempts(self, card_manager):
        # Returns None when unknown
        assert card_manager.get_remaining_attempts() is None


class TestValidateScriptPath:
    def test_rejects_path_traversal(self, card_manager):
        card_manager.cli_path = '/tmp/fake'
        assert card_manager._validate_script_path('../etc/passwd') is None

    def test_rejects_absolute_path(self, card_manager):
        card_manager.cli_path = '/tmp/fake'
        assert card_manager._validate_script_path('/etc/passwd') is None

    def test_rejects_none_cli_path(self, card_manager):
        card_manager.cli_path = None
        assert card_manager._validate_script_path('script.py') is None


class TestSetCliPath:
    def test_set_valid_path(self, card_manager, tmp_path):
        assert card_manager.set_cli_path(str(tmp_path))
        assert card_manager.cli_path == str(tmp_path)

    def test_set_invalid_path(self, card_manager):
        assert card_manager.set_cli_path('/nonexistent/path') is False

    def test_set_path_detects_pysim(self, card_manager, tmp_path):
        (tmp_path / 'pySim-read.py').touch()
        card_manager.set_cli_path(str(tmp_path))
        assert card_manager.cli_backend == CLIBackend.PYSIM

    def test_set_path_defaults_sysmo(self, card_manager, tmp_path):
        card_manager.set_cli_path(str(tmp_path))
        assert card_manager.cli_backend == CLIBackend.SYSMO

    def test_set_path_explicit_backend(self, card_manager, tmp_path):
        card_manager.set_cli_path(str(tmp_path), backend=CLIBackend.PYSIM)
        assert card_manager.cli_backend == CLIBackend.PYSIM
