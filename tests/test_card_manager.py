"""Tests for managers.card_manager module."""

import json
import textwrap
from unittest.mock import MagicMock

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


class TestWriteSpnViaShell:
    """_write_spn_via_shell builds correct pySim-shell script and handles failures."""

    def _sja5_cm(self, tmp_path):
        """Return a CardManager configured as a non-empty SJA5 card."""
        (tmp_path / 'pySim-shell.py').touch()
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm.card_type = CardType.SJA5
        cm._original_card_data = {'ICCID': '8946001234567890123', 'IMSI': '001010123456789'}
        cm._authenticated_adm1_hex = '3838383838383838'
        return cm

    def test_spn_and_adm1_builds_expected_shell_script(self, tmp_path, monkeypatch):
        """Script contains verify_adm, both EF.SPN selects, update_binary, and read-back."""
        captured_cmds = []
        cm = self._sja5_cm(tmp_path)

        def fake_shell_safe(commands, timeout=30):
            captured_cmds.append(commands)
            return True, "{'spn': 'MyNetwork'}", ''

        monkeypatch.setattr(cm, '_run_pysim_shell_safe', fake_shell_safe)
        ok, msg, verified = cm._write_spn_via_shell('MyNetwork', '3838383838383838')

        assert ok is True
        assert captured_cmds, "pySim-shell was not called"
        script = captured_cmds[0]
        assert 'verify_adm --pin-is-hex 3838383838383838' in script
        assert 'MF/ADF.USIM/EF.SPN' in script
        assert 'MF/DF.GSM/EF.SPN' in script
        assert 'update_binary' in script
        assert 'update_binary_decoded' not in script
        assert 'read_binary_decoded' in script
        assert verified == 'MyNetwork'

    def test_no_adm1_skips_spn_shell_write(self, tmp_path, monkeypatch):
        """_program_via_pysim_prog does not call shell when ADM1 is absent."""
        cm = self._sja5_cm(tmp_path)
        cm._authenticated_adm1_hex = None

        shell_called = []
        monkeypatch.setattr(cm, '_write_spn_via_shell',
                            lambda *a, **kw: shell_called.append(a) or (True, 'SPN written', ''))
        monkeypatch.setattr(cm, '_run_pysim_prog',
                            lambda *a, **kw: (True, '', ''))
        monkeypatch.setattr(cm, 'verify_after_program',
                            lambda *a, **kw: (True, 'OK', {}))

        cm._program_via_pysim_prog({'SPN': 'MyNetwork'})
        assert not shell_called, "Shell should not be called without ADM1"

    def test_shell_failure_means_spn_not_verified(self, tmp_path, monkeypatch):
        """If pySim-shell write fails, SPN does not appear in the verified list."""
        cm = self._sja5_cm(tmp_path)

        monkeypatch.setattr(cm, '_run_pysim_prog',
                            lambda *a, **kw: (True, '', ''))
        monkeypatch.setattr(cm, '_write_spn_via_shell',
                            lambda *a, **kw: (False, 'SPN write via pySim-shell failed', ''))
        monkeypatch.setattr(cm, 'verify_after_program',
                            lambda *a, **kw: (True, 'OK', {'IMSI': '001010123456789'}))

        ok, msg = cm._program_via_pysim_prog({'SPN': 'MyNetwork', 'IMSI': '001010123456789'})
        assert ok is True
        assert 'SPN: write failed' in msg

    def test_readback_spn_match_appears_in_verified(self, tmp_path, monkeypatch):
        """When read-back confirms SPN, it appears in the verified output."""
        cm = self._sja5_cm(tmp_path)

        monkeypatch.setattr(cm, '_run_pysim_prog',
                            lambda *a, **kw: (True, '', ''))
        monkeypatch.setattr(cm, '_write_spn_via_shell',
                            lambda *a, **kw: (True, 'SPN written', 'MyNetwork'))
        monkeypatch.setattr(cm, 'verify_after_program',
                            lambda *a, **kw: (True, 'OK', {}))

        ok, msg = cm._program_via_pysim_prog({'SPN': 'MyNetwork'})
        assert ok is True
        assert 'SPN: verified' in msg

    def _gialersim_cm(self, tmp_path):
        """Return a CardManager configured as a blank gialersim card."""
        (tmp_path / 'pySim-shell.py').touch()
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm.card_type = CardType.GIALERSIM
        cm._original_card_data = {}
        cm._authenticated_adm1_hex = '3838383838383838'
        return cm

    def test_gialersim_with_spn_and_adm1_attempts_shell_write(self, tmp_path, monkeypatch):
        """gialersim card with SPN + ADM1 must attempt shell write, not skip."""
        cm = self._gialersim_cm(tmp_path)
        shell_called = []

        def fake_shell_safe(commands, timeout=30):
            shell_called.append(commands)
            return True, 'OK', ''

        monkeypatch.setattr(cm, '_run_pysim_shell_safe', fake_shell_safe)
        ok, msg, verified = cm._write_spn_via_shell('MyNetwork', '3838383838383838')

        assert shell_called, "pySim-shell was not called for gialersim"
        assert ok is True

    def test_gialersim_shell_failure_reports_spn_not_written(self, tmp_path, monkeypatch):
        """If shell write fails for gialersim, caller reports SPN not written/verified."""
        cm = self._gialersim_cm(tmp_path)

        monkeypatch.setattr(cm, '_run_pysim_prog',
                            lambda *a, **kw: (True, '', ''))
        monkeypatch.setattr(cm, '_write_spn_via_shell',
                            lambda *a, **kw: (False, 'SPN write via pySim-shell failed', ''))
        monkeypatch.setattr(cm, 'verify_after_program',
                            lambda *a, **kw: (True, 'OK', {'IMSI': '001010123456789'}))

        ok, msg = cm._program_via_pysim_prog(
            {'SPN': 'MyNetwork', 'IMSI': '001010123456789'})
        assert ok is True
        assert 'SPN: write failed' in msg


class TestEncodeSpnRaw:
    """Unit tests for CardManager._encode_spn_raw and _parse_spn_readback."""

    def test_teleauora_uk_encoding(self):
        """'Teleauora UK' encodes to the expected 34-char hex string."""
        result = CardManager._encode_spn_raw('Teleauora UK')
        expected = '01' + 'Teleauora UK'.encode('ascii').hex() + 'ff' * 4
        assert result == expected
        assert result == '0154656c6561756f726120554bffffffff'

    def test_always_17_bytes(self):
        """Output is always 34 hex chars (17 bytes) regardless of SPN length."""
        for spn in ('', 'A', 'x' * 16, 'x' * 20):
            result = CardManager._encode_spn_raw(spn)
            assert len(result) == 34, f"Expected 34 chars for spn={spn!r}, got {len(result)}"

    def test_short_spn_padded_with_ff(self):
        """Short SPN is padded to 16 bytes with 0xFF."""
        result = CardManager._encode_spn_raw('AB')
        assert result.startswith('01')
        assert result == '01' + '4142' + 'ff' * 14

    def test_long_spn_truncated_to_16_bytes(self):
        """SPN longer than 16 chars is truncated; total still 17 bytes."""
        result = CardManager._encode_spn_raw('x' * 20)
        assert len(result) == 34
        assert result == '01' + '78' * 16

    def test_parse_spn_readback_python_repr(self):
        """Parses SPN from Python dict repr output."""
        stdout = "pySIM> {'rfu': 0, 'hide_in_oplmn': False, 'show_in_hplmn': True, 'spn': 'Teleauora UK'}"
        assert CardManager._parse_spn_readback(stdout) == 'Teleauora UK'

    def test_parse_spn_readback_json_style(self):
        """Parses SPN from JSON-style output."""
        stdout = '{"rfu": 0, "spn": "MyNetwork", "show_in_hplmn": true}'
        assert CardManager._parse_spn_readback(stdout) == 'MyNetwork'

    def test_parse_spn_readback_empty_returns_empty(self):
        """Returns empty string when stdout contains no SPN."""
        assert CardManager._parse_spn_readback('') == ''
        assert CardManager._parse_spn_readback('some random output') == ''
        assert CardManager._parse_spn_readback(None) == ''


class TestWriteSpnScript:
    """_write_spn_via_shell script content and failure handling."""

    def _sja5_cm(self, tmp_path):
        (tmp_path / 'pySim-shell.py').touch()
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        cm.card_type = CardType.SJA5
        cm._original_card_data = {'ICCID': '8946001234567890123', 'IMSI': '001010123456789'}
        cm._authenticated_adm1_hex = '3838383838383838'
        return cm

    def test_script_writes_both_ef_spn_targets(self, tmp_path, monkeypatch):
        """Script writes to both MF/ADF.USIM/EF.SPN and MF/DF.GSM/EF.SPN."""
        captured = []
        cm = self._sja5_cm(tmp_path)
        monkeypatch.setattr(cm, '_run_pysim_shell_safe',
                            lambda cmds, timeout=30: captured.append(cmds) or (True, '', ''))
        cm._write_spn_via_shell('Net', '3838383838383838')
        script = captured[0]
        assert 'MF/ADF.USIM/EF.SPN' in script
        assert 'MF/DF.GSM/EF.SPN' in script

    def test_script_has_no_raw_apdu_command(self, tmp_path, monkeypatch):
        """No raw 'apdu' command is ever generated."""
        captured = []
        cm = self._sja5_cm(tmp_path)
        monkeypatch.setattr(cm, '_run_pysim_shell_safe',
                            lambda cmds, timeout=30: captured.append(cmds) or (True, '', ''))
        cm._write_spn_via_shell('Net', '3838383838383838')
        assert 'apdu' not in captured[0]

    def test_script_includes_read_back(self, tmp_path, monkeypatch):
        """Script ends with read_binary_decoded for verification."""
        captured = []
        cm = self._sja5_cm(tmp_path)
        monkeypatch.setattr(cm, '_run_pysim_shell_safe',
                            lambda cmds, timeout=30: captured.append(cmds) or (True, '', ''))
        cm._write_spn_via_shell('Net', '3838383838383838')
        assert 'read_binary_decoded' in captured[0]

    def test_shell_failure_returns_false_empty_verified(self, tmp_path, monkeypatch):
        """Shell failure → (False, msg, '') — write failed, not verified."""
        cm = self._sja5_cm(tmp_path)
        monkeypatch.setattr(cm, '_run_pysim_shell_safe',
                            lambda cmds, timeout=30: (False, 'error output', 'err'))
        ok, msg, verified = cm._write_spn_via_shell('Net', '3838383838383838')
        assert ok is False
        assert verified == ''

    def test_shell_success_readback_empty_not_confirmed(self, tmp_path, monkeypatch):
        """Shell OK but stdout has no SPN → write_ok=True, verified=''."""
        cm = self._sja5_cm(tmp_path)
        monkeypatch.setattr(cm, '_run_pysim_shell_safe',
                            lambda cmds, timeout=30: (True, 'no spn data here', ''))
        ok, msg, verified = cm._write_spn_via_shell('Net', '3838383838383838')
        assert ok is True
        assert verified == ''

    def test_shell_success_readback_matches_spn(self, tmp_path, monkeypatch):
        """Shell OK and stdout contains matching SPN → verified equals requested SPN."""
        cm = self._sja5_cm(tmp_path)
        stdout = "pySIM> {'rfu': 0, 'spn': 'Net'}"
        monkeypatch.setattr(cm, '_run_pysim_shell_safe',
                            lambda cmds, timeout=30: (True, stdout, ''))
        ok, msg, verified = cm._write_spn_via_shell('Net', '3838383838383838')
        assert ok is True
        assert verified == 'Net'

    def test_program_card_spn_written_not_confirmed(self, tmp_path, monkeypatch):
        """Shell ok but read-back empty → 'written but not confirmed' in result."""
        cm = self._sja5_cm(tmp_path)
        monkeypatch.setattr(cm, '_run_pysim_prog',
                            lambda *a, **kw: (True, '', ''))
        monkeypatch.setattr(cm, '_write_spn_via_shell',
                            lambda *a, **kw: (True, 'SPN written', ''))
        monkeypatch.setattr(cm, 'verify_after_program',
                            lambda *a, **kw: (True, 'OK', {}))
        ok, msg = cm._program_via_pysim_prog({'SPN': 'Net'})
        assert ok is True
        assert 'SPN: written but not confirmed' in msg
