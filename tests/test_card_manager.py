"""Tests for managers.card_manager module."""

import textwrap

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
        # 'toolongkey!' is 11 chars — exceeds 8 ASCII and is not 16 hex chars
        ok, msg = card_manager.authenticate('toolongkey!')
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


class TestPcscReaderIndex:
    """Tests for the pcsc_reader_index constructor parameter (S3-B seam)."""

    def test_default_index_is_zero(self):
        cm = CardManager()
        assert cm._pcsc_reader_index == 0

    def test_explicit_zero(self):
        cm = CardManager(pcsc_reader_index=0)
        assert cm._pcsc_reader_index == 0

    def test_non_default_index_stored(self):
        cm = CardManager(pcsc_reader_index=1)
        assert cm._pcsc_reader_index == 1

    def test_invalid_negative_raises(self):
        with pytest.raises(ValueError):
            CardManager(pcsc_reader_index=-1)

    def test_invalid_float_raises(self):
        with pytest.raises((ValueError, TypeError)):
            CardManager(pcsc_reader_index=1.5)  # type: ignore[arg-type]

    def test_invalid_string_raises(self):
        with pytest.raises((ValueError, TypeError)):
            CardManager(pcsc_reader_index="0")  # type: ignore[arg-type]

    def test_positional_arg_not_accepted(self):
        with pytest.raises(TypeError):
            CardManager(1)  # type: ignore[call-arg]

    def test_detect_card_uses_reader_index_0_by_default(self, tmp_path):
        calls_file = tmp_path / "calls.txt"
        script = tmp_path / "pySim-read.py"
        script.write_text(textwrap.dedent(f"""\
            import sys
            with open({str(calls_file)!r}, 'w') as f:
                f.write(' '.join(sys.argv[1:]))
            print("ICCID: 8988211000000123456")
            print("IMSI: 001010000012345")
        """))
        cm = CardManager(pcsc_reader_index=0)
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm.detect_card()
        recorded = calls_file.read_text().strip()
        assert recorded == "-p0", f"Expected -p0, got {recorded!r}"

    def test_detect_card_uses_reader_index_1(self, tmp_path):
        calls_file = tmp_path / "calls.txt"
        script = tmp_path / "pySim-read.py"
        script.write_text(textwrap.dedent(f"""\
            import sys
            with open({str(calls_file)!r}, 'w') as f:
                f.write(' '.join(sys.argv[1:]))
            print("ICCID: 8988211000000123456")
            print("IMSI: 001010000012345")
        """))
        cm = CardManager(pcsc_reader_index=1)
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm.detect_card()
        recorded = calls_file.read_text().strip()
        assert recorded == "-p1", f"Expected -p1, got {recorded!r}"

    def test_pysim_shell_uses_reader_index_1(self, tmp_path, monkeypatch):
        calls_file = tmp_path / "calls.txt"
        script = tmp_path / "pySim-shell.py"
        script.write_text(textwrap.dedent(f"""\
            import sys
            with open({str(calls_file)!r}, 'w') as f:
                f.write(' '.join(sys.argv[1:]))
        """))
        cm = CardManager(pcsc_reader_index=1)
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm.card_type = CardType.SJA5
        cm._run_pysim_shell_impl("3838383838383838", "")
        recorded = calls_file.read_text().strip()
        assert "-p1" in recorded, f"Expected -p1 in args, got {recorded!r}"

    def test_pysim_prog_uses_reader_index_1(self, tmp_path):
        calls_file = tmp_path / "calls.txt"
        script = tmp_path / "pySim-prog.py"
        script.write_text(textwrap.dedent(f"""\
            import sys
            with open({str(calls_file)!r}, 'w') as f:
                f.write(' '.join(sys.argv[1:]))
        """))
        cm = CardManager(pcsc_reader_index=1)
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm.card_type = CardType.SJA5
        cm.authenticated = True
        cm._authenticated_adm1_hex = "3838383838383838"
        cm._run_pysim_prog(
            {"IMSI": "001010000012345", "Ki": "A" * 32, "OPc": "B" * 32},
            adm1_hex="3838383838383838",
        )
        recorded = calls_file.read_text().strip()
        assert "-p1" in recorded, f"Expected -p1 in pySim-prog args, got {recorded!r}"

    def test_probe_card_presence_out_of_range_returns_error(self, monkeypatch):
        import managers.card_manager as cm_mod
        monkeypatch.setattr(cm_mod, "_pyscard_available", True)
        monkeypatch.setattr(cm_mod, "_smartcard_readers", lambda: ["reader0"])
        cm = CardManager(pcsc_reader_index=99)
        ok, reason = cm.probe_card_presence()
        assert ok is False
        assert "99" in reason or "out of range" in reason.lower()

    def test_check_adm1_retry_counter_out_of_range_returns_none(self, monkeypatch):
        import managers.card_manager as cm_mod
        monkeypatch.setattr(cm_mod, "_pyscard_available", True)
        monkeypatch.setattr(cm_mod, "_smartcard_readers", lambda: ["reader0"])
        cm = CardManager(pcsc_reader_index=99)
        result = cm.check_adm1_retry_counter()
        assert result is None


class TestPySimVenvInterpreter:
    """pySim subprocesses use _venv_python when present, sys.executable otherwise."""

    def _mock_subprocess(self, monkeypatch):
        """Patch subprocess.run in card_manager and return captured call list."""
        import managers.card_manager as cm_mod
        from unittest.mock import MagicMock
        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            r = MagicMock()
            r.returncode = 0
            r.stdout = ''
            r.stderr = ''
            return r

        monkeypatch.setattr(cm_mod.subprocess, 'run', fake_run)
        return captured

    # --- _find_venv_python unit tests ---

    def test_find_venv_python_returns_path_when_present(self, tmp_path):
        from managers.card_manager import _find_venv_python
        venv_python = tmp_path / '.venv' / 'bin' / 'python'
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text('#!/bin/sh\nexec python3 "$@"\n')
        venv_python.chmod(0o755)
        assert _find_venv_python(str(tmp_path)) == str(venv_python)

    def test_find_venv_python_returns_none_when_absent(self, tmp_path):
        from managers.card_manager import _find_venv_python
        assert _find_venv_python(str(tmp_path)) is None

    def test_find_venv_python_returns_none_when_not_executable(self, tmp_path):
        from managers.card_manager import _find_venv_python
        venv_python = tmp_path / '.venv' / 'bin' / 'python'
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text('#!/bin/sh\n')
        venv_python.chmod(0o644)
        assert _find_venv_python(str(tmp_path)) is None

    # --- subprocess invocation tests ---

    def test_run_cli_uses_venv_python_when_set(self, tmp_path, monkeypatch):
        captured = self._mock_subprocess(monkeypatch)
        (tmp_path / 'pySim-read.py').touch()
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/fake/venv/bin/python'
        cm._run_cli('pySim-read.py', '-p0')
        assert len(captured) == 1
        assert captured[0][0] == '/fake/venv/bin/python'

    def test_run_cli_falls_back_to_sys_executable_when_no_venv(self, tmp_path, monkeypatch):
        import sys
        captured = self._mock_subprocess(monkeypatch)
        (tmp_path / 'pySim-read.py').touch()
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = None
        cm._run_cli('pySim-read.py', '-p0')
        assert len(captured) == 1
        assert captured[0][0] == sys.executable

    def test_run_pysim_shell_impl_uses_venv_python_when_set(self, tmp_path, monkeypatch):
        captured = self._mock_subprocess(monkeypatch)
        (tmp_path / 'pySim-shell.py').touch()
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/fake/venv/bin/python'
        cm.card_type = CardType.SJA5
        cm._run_pysim_shell_impl(adm1_hex=None, commands='')
        assert len(captured) == 1
        assert captured[0][0] == '/fake/venv/bin/python'

    def test_run_pysim_prog_uses_venv_python_when_set(self, tmp_path, monkeypatch):
        captured = self._mock_subprocess(monkeypatch)
        (tmp_path / 'pySim-prog.py').touch()
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = '/fake/venv/bin/python'
        cm.card_type = CardType.GIALERSIM
        cm._run_pysim_prog(
            {'IMSI': '999880001000001', 'Ki': 'A' * 32, 'OPc': 'B' * 32},
            adm1_hex='3838383838383838',
        )
        assert len(captured) == 1
        assert captured[0][0] == '/fake/venv/bin/python'
