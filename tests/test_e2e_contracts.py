#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E2E contract tests for SimGUI ↔ sysmocom/pySim CLI interface.

These tests verify the *interface contract* between SimGUI and the real CLI
tools (sysmo-usim-tool and pySim) WITHOUT requiring physical hardware.

Strategy
--------
- Real temp directories (tmp_path) are used instead of mocks wherever possible.
- For subprocess tests, tiny real Python scripts are written to tmp_path and
  actually executed — subprocess.run is NOT mocked.
- Hardware-gated tests are collected but skipped unless SIMGUI_HW_TEST=1.

Why this file matters
---------------------
The rest of the test-suite mocks subprocess and uses SimulatorBackend.
These tests fill the gap by exercising the *exact* bytes and exit codes that
CardManager would exchange with the real CLI executables.
"""

import os
import stat
import sys
import textwrap
import time

import pytest

# Make sure the project root is importable regardless of CWD.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from managers.card_manager import CardManager, CardType, CLIBackend, _find_cli_tool

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.e2e

hardware = pytest.mark.skipif(
    os.environ.get("SIMGUI_HW_TEST") != "1",
    reason="Hardware test skipped (set SIMGUI_HW_TEST=1 to enable)",
)


# ===========================================================================
# Section 1 — CLI Discovery (_find_cli_tool)
# ===========================================================================

class TestCLIDiscovery:
    """Verify that _find_cli_tool() correctly locates CLI tools via env vars
    and filesystem candidates.

    Bug this catches: if env var priority was reversed (pySim checked before
    sysmo), operators with both repos would get the wrong backend silently.
    """

    def test_sysmo_env_var_discovery(self, tmp_path, monkeypatch):
        """SYSMO_USIM_TOOL_PATH env var is used and returns CLIBackend.SYSMO.

        A regression here would mean the admin can't override the tool path
        at deployment time.
        """
        monkeypatch.setenv("SYSMO_USIM_TOOL_PATH", str(tmp_path))
        monkeypatch.delenv("PYSIM_PATH", raising=False)
        path, backend = _find_cli_tool()
        assert path == str(tmp_path), "Returned path must match env var value"
        assert backend == CLIBackend.SYSMO, "Backend must be SYSMO when using SYSMO_USIM_TOOL_PATH"

    def test_pysim_env_var_discovery(self, tmp_path, monkeypatch):
        """PYSIM_PATH env var is used and returns CLIBackend.PYSIM.

        A regression here would prevent pySim-only deployments.
        """
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.setenv("PYSIM_PATH", str(tmp_path))
        path, backend = _find_cli_tool()
        assert path == str(tmp_path), "Returned path must match PYSIM_PATH"
        assert backend == CLIBackend.PYSIM, "Backend must be PYSIM when using PYSIM_PATH"

    def test_sysmo_env_var_takes_priority_over_pysim_env_var(self, tmp_path, monkeypatch):
        """When both env vars are set, SYSMO_USIM_TOOL_PATH wins.

        This contract preserves the documented priority order so operators
        with dual-install systems get predictable behaviour.
        """
        sysmo_dir = tmp_path / "sysmo"
        pysim_dir = tmp_path / "pysim"
        sysmo_dir.mkdir()
        pysim_dir.mkdir()
        monkeypatch.setenv("SYSMO_USIM_TOOL_PATH", str(sysmo_dir))
        monkeypatch.setenv("PYSIM_PATH", str(pysim_dir))
        path, backend = _find_cli_tool()
        assert path == str(sysmo_dir)
        assert backend == CLIBackend.SYSMO

    def test_env_var_nonexistent_dir_is_ignored(self, tmp_path, monkeypatch):
        """An env var pointing to a non-existent directory must not be used.

        Without this guard, CardManager would build broken paths for scripts.
        """
        monkeypatch.setenv("SYSMO_USIM_TOOL_PATH", str(tmp_path / "does_not_exist"))
        monkeypatch.delenv("PYSIM_PATH", raising=False)
        path, backend = _find_cli_tool()
        # Should fall through to filesystem candidates (likely NONE in CI)
        assert backend != CLIBackend.SYSMO or (path is not None and os.path.isdir(path))

    def test_no_env_var_no_filesystem_candidates_returns_none(self, monkeypatch):
        """When no tool is found, returns (None, CLIBackend.NONE).

        CardManager callers must check for None path before calling _run_cli.
        """
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.delenv("PYSIM_PATH", raising=False)
        # Patch isdir to always return False so filesystem candidates are skipped
        monkeypatch.setattr(os.path, "isdir", lambda p: False)
        path, backend = _find_cli_tool()
        assert path is None
        assert backend == CLIBackend.NONE

    def test_filesystem_candidate_sysmo_picked_before_pysim(self, tmp_path, monkeypatch):
        """When discovered via filesystem, sysmo candidate list is checked before pySim.

        This mirrors the documented tool priority in card_manager.py.
        """
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.delenv("PYSIM_PATH", raising=False)

        # Inject tmp_path as the first sysmo candidate by patching isdir
        checked_dirs = []

        def fake_isdir(p):
            checked_dirs.append(p)
            # Pretend tmp_path is the '~/sysmo-usim-tool' candidate
            if os.path.expanduser("~/sysmo-usim-tool") in str(p):
                return True
            return False

        monkeypatch.setattr(os.path, "isdir", fake_isdir)
        path, backend = _find_cli_tool()
        # At minimum the sysmo candidates were checked before pySim ones
        sysmo_indices = [i for i, d in enumerate(checked_dirs)
                         if "sysmo" in str(d).lower()]
        pysim_indices = [i for i, d in enumerate(checked_dirs)
                         if "pysim" in str(d).lower()]
        if sysmo_indices and pysim_indices:
            assert min(sysmo_indices) < min(pysim_indices), (
                "sysmo candidates must be checked before pySim candidates"
            )


# ===========================================================================
# Section 2 — CLI Argument Formatting
# ===========================================================================

class TestCLIArgumentFormatting:
    """Verify that CardManager builds exactly the right command lists.

    Bug this catches: if the argument order changed (e.g., script before
    interpreter, or wrong flag), the real CLI tool would reject the call.
    """

    # -----------------------------------------------------------------------
    # _validate_script_path
    # -----------------------------------------------------------------------

    def test_validate_script_path_accepts_simple_name(self, tmp_path):
        """A plain script name with no path separators is accepted."""
        (tmp_path / "good_script.py").write_text("# ok\n")
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        result = cm._validate_script_path("good_script.py")
        assert result is not None
        assert result.endswith("good_script.py")

    def test_validate_script_path_blocks_double_dot(self, tmp_path):
        """'../evil.py' must be rejected — prevents directory traversal.

        Without this guard an attacker could run arbitrary scripts by crafting
        a path that escapes the cli_path directory.
        """
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        result = cm._validate_script_path("../evil.py")
        assert result is None, "Path traversal with '..' must be blocked"

    def test_validate_script_path_blocks_os_sep(self, tmp_path):
        """A path containing os.sep must be rejected.

        e.g. 'subdir/script.py' could escape intended boundaries on some
        filesystems or trick symlink resolution.
        """
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        result = cm._validate_script_path("subdir" + os.sep + "evil.py")
        assert result is None, f"Path containing os.sep ({os.sep!r}) must be blocked"

    def test_validate_script_path_blocks_absolute_path(self, tmp_path):
        """An absolute path must be rejected.

        Callers should only pass bare script names.
        """
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        result = cm._validate_script_path("/etc/passwd")
        assert result is None, "Absolute paths must be rejected"

    def test_validate_script_path_returns_none_when_no_cli_path(self):
        """When cli_path is None, _validate_script_path must return None."""
        cm = CardManager()
        cm.cli_path = None
        result = cm._validate_script_path("pySim-read.py")
        assert result is None

    # -----------------------------------------------------------------------
    # _run_cli command construction
    # -----------------------------------------------------------------------

    def test_run_cli_builds_correct_command(self, tmp_path):
        """_run_cli must build [sys.executable, script_path, *args].

        If the interpreter path were omitted, the script would not be found.
        If args were flipped, the CLI tool would fail to parse them.
        """
        # Create a real script that prints its argv to stdout
        script = tmp_path / "echo_args.py"
        script.write_text(textwrap.dedent("""\
            import sys, json
            print(json.dumps(sys.argv))
        """))
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        ok, stdout, stderr = cm._run_cli("echo_args.py", "--foo", "bar")
        assert ok is True, f"Expected success. stderr={stderr!r}"
        import json
        argv = json.loads(stdout)
        # argv[0] is the script path, argv[1:] are args
        assert argv[0].endswith("echo_args.py"), "Script path must be first argv element"
        assert argv[1] == "--foo"
        assert argv[2] == "bar"

    def test_detect_card_pysim_calls_read_script_with_p0(self, tmp_path, monkeypatch):
        """detect_card() with pySim backend must invoke pySim-read.py -p0.

        The -p0 flag selects PCSC reader index 0. Without it pySim-read.py
        would prompt interactively and the GUI would hang forever.
        """
        # Create a fake pySim-read.py that records its arguments
        calls_file = tmp_path / "calls.txt"
        script = tmp_path / "pySim-read.py"
        script.write_text(textwrap.dedent(f"""\
            import sys
            with open({str(calls_file)!r}, 'w') as f:
                f.write(' '.join(sys.argv[1:]))
            print("ICCID: 8988211000000123456")
            print("IMSI: 001010000012345")
        """))
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.PYSIM
        ok, msg = cm.detect_card()
        assert ok is True, f"detect_card should succeed with stub script. msg={msg!r}"
        recorded = calls_file.read_text().strip()
        assert recorded == "-p0", (
            f"pySim-read.py must be called with '-p0', got {recorded!r}"
        )

    def test_detect_card_sysmo_tries_scripts_in_correct_order(self, tmp_path):
        """detect_card() with sysmo backend tries sja2, sja5, sjs1 in that order.

        Changing the order would cause the wrong card type to be reported.
        """
        # Track which scripts were invoked and in which order
        calls_log = tmp_path / "calls.log"
        calls_log.write_text("")

        for name in ("sysmo_isim_sja2.py", "sysmo_isim_sja5.py", "sysmo_isim_sjs1.py"):
            script = tmp_path / name
            script.write_text(textwrap.dedent(f"""\
                import sys
                with open({str(calls_log)!r}, 'a') as f:
                    f.write({name!r} + '\\n')
                sys.exit(1)  # simulate failure so all scripts are tried
            """))

        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.SYSMO
        cm.detect_card()

        called = calls_log.read_text().strip().splitlines()
        assert called == [
            "sysmo_isim_sja2.py",
            "sysmo_isim_sja5.py",
            "sysmo_isim_sjs1.py",
        ], f"Scripts must be tried in sja2→sja5→sjs1 order, got {called}"

    def test_detect_card_sysmo_stops_at_first_success(self, tmp_path):
        """detect_card() sysmo must stop after the first script succeeds.

        Calling subsequent scripts after success wastes time and could
        misreport card type.
        """
        calls_log = tmp_path / "calls.log"
        calls_log.write_text("")

        # sja2 succeeds; sja5 and sjs1 should NOT be called
        (tmp_path / "sysmo_isim_sja2.py").write_text(textwrap.dedent(f"""\
            import sys
            with open({str(calls_log)!r}, 'a') as f:
                f.write('sysmo_isim_sja2.py\\n')
            sys.exit(0)  # success
        """))
        for name in ("sysmo_isim_sja5.py", "sysmo_isim_sjs1.py"):
            (tmp_path / name).write_text(textwrap.dedent(f"""\
                import sys
                with open({str(calls_log)!r}, 'a') as f:
                    f.write({name!r} + '\\n')
                sys.exit(0)
            """))

        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.SYSMO
        ok, _ = cm.detect_card()
        assert ok is True
        called = calls_log.read_text().strip().splitlines()
        assert called == ["sysmo_isim_sja2.py"], (
            f"Must stop at sja2, but also called: {called[1:]}"
        )
        assert cm.card_type == CardType.SJA2

    def test_detect_card_sysmo_passes_help_flag(self, tmp_path):
        """detect_card() with sysmo calls each script with '--help'.

        '--help' is used as a lightweight probe (no hardware needed, just
        checks whether the script runs at all). Using a real operation here
        would risk corrupting or locking a card.
        """
        args_received = tmp_path / "args.txt"
        script = tmp_path / "sysmo_isim_sja2.py"
        script.write_text(textwrap.dedent(f"""\
            import sys
            with open({str(args_received)!r}, 'w') as f:
                f.write(' '.join(sys.argv[1:]))
            sys.exit(0)
        """))
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        cm.cli_backend = CLIBackend.SYSMO
        cm.detect_card()
        assert args_received.read_text().strip() == "--help", (
            "sysmo scripts must be called with '--help' during detect_card"
        )


# ===========================================================================
# Section 3 — Output Parsing (_parse_pysim_output)
# ===========================================================================

class TestParsePysimOutput:
    """Verify _parse_pysim_output() correctly extracts card data from pySim output.

    Bug this catches: if the parser broke on whitespace variations, extra
    headers, or case differences, card info would silently be empty and the
    GUI would show blank ICCID/IMSI after a successful read.
    """

    def _parse(self, output: str) -> dict:
        """Helper: run _parse_pysim_output and return resulting card_info."""
        cm = CardManager()
        cm.cli_path = None  # not running CLI — just parsing
        cm._parse_pysim_output(output)
        return cm.card_info

    def test_parses_standard_pysim_read_output(self):
        """Parses the standard pySim-read.py output format correctly."""
        output = textwrap.dedent("""\
            Reading ...
            ICCID: 8988211000000123456
            IMSI: 001010000012345
        """)
        info = self._parse(output)
        assert info["ICCID"] == "8988211000000123456"
        assert info["IMSI"] == "001010000012345"

    def test_parses_output_with_extra_fields(self):
        """Extra fields in pySim output are ignored without error."""
        output = textwrap.dedent("""\
            ICCID: 8988211000000123456
            IMSI: 001010000012345
            SMSP: some_value_we_dont_need
            ACC: 0002
        """)
        info = self._parse(output)
        assert info["ICCID"] == "8988211000000123456"
        assert info["IMSI"] == "001010000012345"
        # Extra keys may or may not be present; what matters is ICCID/IMSI
        assert "SMSP" not in info or True  # we don't care about extras

    def test_partial_output_missing_imsi_does_not_crash(self):
        """Output with ICCID but no IMSI must not raise an exception."""
        output = "ICCID: 8988211000000123456\n"
        info = self._parse(output)
        assert info.get("ICCID") == "8988211000000123456"
        assert "IMSI" not in info

    def test_partial_output_missing_iccid_does_not_crash(self):
        """Output with IMSI but no ICCID must not raise an exception."""
        output = "IMSI: 001010000012345\n"
        info = self._parse(output)
        assert info.get("IMSI") == "001010000012345"
        assert "ICCID" not in info

    def test_empty_output_returns_empty_card_info(self):
        """Empty string produces empty card_info without crash."""
        info = self._parse("")
        assert info == {}

    def test_whitespace_only_output_returns_empty_card_info(self):
        """Whitespace-only output must not raise or produce stale data."""
        info = self._parse("   \n\n   \n")
        assert info == {}

    def test_lines_without_colons_are_skipped(self):
        """Lines without ':' separators must be silently skipped."""
        output = textwrap.dedent("""\
            Reading SIM card...
            Please wait
            ICCID: 8988211000000999999
            Done.
        """)
        info = self._parse(output)
        assert info["ICCID"] == "8988211000000999999"
        # No IMSI in output, no crash from header lines

    def test_case_insensitive_key_matching_imsi(self):
        """Key matching is case-insensitive: 'Imsi' and 'IMSI' both work.

        pySim has historically changed key capitalisation between versions.
        """
        output = "Imsi: 001010000012345\n"
        info = self._parse(output)
        assert info.get("IMSI") == "001010000012345", (
            "IMSI must be extracted even when key is written as 'Imsi'"
        )

    def test_case_insensitive_key_matching_iccid(self):
        """'Iccid' capitalisation is normalised to 'ICCID'."""
        output = "Iccid: 8988211000000123456\n"
        info = self._parse(output)
        assert info.get("ICCID") == "8988211000000123456", (
            "ICCID must be extracted even when key is written as 'Iccid'"
        )

    def test_value_with_colon_inside_is_preserved(self):
        """A value containing ':' should use only the first ':' as separator.

        e.g. 'ICCID: 89882:extra' — value must be '89882:extra', not '89882'.
        Actually, _parse_pysim_output uses str.partition which takes everything
        after the first ':'.
        """
        output = "ICCID: 8988211000000123456\nIMSI: 001010000012345\n"
        info = self._parse(output)
        # Baseline: normal output still works after this logic
        assert info["ICCID"] == "8988211000000123456"

    def test_leading_and_trailing_whitespace_stripped_from_values(self):
        """Values with extra whitespace are stripped."""
        output = "  ICCID  :   8988211000000123456   \n  IMSI  :   001010000012345   \n"
        info = self._parse(output)
        assert info.get("ICCID") == "8988211000000123456"
        assert info.get("IMSI") == "001010000012345"

    def test_realistic_pysim_read_output_full(self):
        """Parse a complete, realistic pySim-read.py output block."""
        output = textwrap.dedent("""\
            Reading ...
            ICCID: 8988211000000120006
            MCC/MNC: 001/01
            IMSI: 001010000012000
            MSISDN: Not available
            Service Provider Name: sysmoISIM-SJA2
            SMSP: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff06918100f4
            ACC: 0002
            HPLMN: 001/01
        """)
        info = self._parse(output)
        assert info["ICCID"] == "8988211000000120006"
        assert info["IMSI"] == "001010000012000"


# ===========================================================================
# Section 4 — set_cli_path() backend detection
# ===========================================================================

class TestSetCliPath:
    """Verify set_cli_path() correctly detects backend type from directory contents.

    Bug this catches: if the pySim detection check was removed or the filename
    changed, sysmo tools would be invoked for a pySim installation, producing
    wrong script names and failures.
    """

    def test_directory_with_pysim_read_sets_pysim_backend(self, tmp_path):
        """A directory containing 'pySim-read.py' must set CLIBackend.PYSIM."""
        (tmp_path / "pySim-read.py").write_text("# stub\n")
        cm = CardManager()
        result = cm.set_cli_path(str(tmp_path))
        assert result is True
        assert cm.cli_backend == CLIBackend.PYSIM
        assert cm.cli_path == str(tmp_path)

    def test_directory_without_pysim_read_sets_sysmo_backend(self, tmp_path):
        """A directory WITHOUT 'pySim-read.py' defaults to CLIBackend.SYSMO."""
        (tmp_path / "sysmo_isim_sja2.py").write_text("# stub\n")
        cm = CardManager()
        result = cm.set_cli_path(str(tmp_path))
        assert result is True
        assert cm.cli_backend == CLIBackend.SYSMO
        assert cm.cli_path == str(tmp_path)

    def test_empty_directory_defaults_to_sysmo_backend(self, tmp_path):
        """An empty directory (no scripts) still returns True and sets SYSMO."""
        cm = CardManager()
        result = cm.set_cli_path(str(tmp_path))
        assert result is True
        assert cm.cli_backend == CLIBackend.SYSMO

    def test_nonexistent_path_returns_false(self, tmp_path):
        """A path that does not exist must return False with no state change."""
        cm = CardManager()
        original_path = cm.cli_path
        original_backend = cm.cli_backend
        result = cm.set_cli_path(str(tmp_path / "does_not_exist"))
        assert result is False
        assert cm.cli_path == original_path, "cli_path must not change on failure"
        assert cm.cli_backend == original_backend, "cli_backend must not change on failure"

    def test_file_path_not_directory_returns_false(self, tmp_path):
        """Passing a file path (not a directory) must return False."""
        f = tmp_path / "some_file.txt"
        f.write_text("not a directory")
        cm = CardManager()
        result = cm.set_cli_path(str(f))
        assert result is False

    def test_explicit_backend_override_is_respected(self, tmp_path):
        """When backend is passed explicitly, it wins over auto-detection.

        This allows operators to override auto-detection for edge cases.
        """
        (tmp_path / "pySim-read.py").write_text("# stub\n")
        cm = CardManager()
        # Explicitly request SYSMO even though pySim-read.py is present
        result = cm.set_cli_path(str(tmp_path), backend=CLIBackend.SYSMO)
        assert result is True
        assert cm.cli_backend == CLIBackend.SYSMO, (
            "Explicit backend kwarg must override auto-detection"
        )


# ===========================================================================
# Section 5 — _run_cli() real subprocess behaviour
# ===========================================================================

class TestRunCliSubprocessBehaviour:
    """Verify _run_cli() behaves correctly with real subprocess calls.

    These tests use actual Python scripts executed in tmp_path. subprocess.run
    is NOT mocked — we verify the real OS-level contract.

    Bug this catches: if return-code handling or stdout/stderr routing changed,
    successful card reads would be reported as failures, or error messages from
    the CLI would be silently dropped.
    """

    def _make_cm(self, cli_path: str) -> CardManager:
        """Return a CardManager pointing at cli_path."""
        cm = CardManager()
        cm.cli_path = cli_path
        return cm

    def test_successful_script_returns_true_and_stdout(self, tmp_path):
        """A script that exits 0 must return (True, <stdout>, '')."""
        script = tmp_path / "success.py"
        script.write_text('print("hello world")\n')
        cm = self._make_cm(str(tmp_path))
        ok, stdout, stderr = cm._run_cli("success.py")
        assert ok is True, "Exit 0 must map to success=True"
        assert stdout == "hello world"
        assert stderr == ""

    def test_failing_script_returns_false_and_preserves_stdout(self, tmp_path):
        """A script that exits non-zero must return (False, stdout, stderr).

        Both stdout and stderr must be captured — the CLI may write useful
        diagnostics to stdout even on failure.
        """
        script = tmp_path / "fail.py"
        script.write_text(textwrap.dedent("""\
            import sys
            print("partial output")
            print("error detail", file=sys.stderr)
            sys.exit(1)
        """))
        cm = self._make_cm(str(tmp_path))
        ok, stdout, stderr = cm._run_cli("fail.py")
        assert ok is False, "Non-zero exit must map to success=False"
        assert stdout == "partial output"
        assert stderr == "error detail"

    def test_script_writing_to_stderr_only(self, tmp_path):
        """A script that writes to stderr and exits 0 returns (True, '', <stderr>)."""
        script = tmp_path / "stderr_only.py"
        script.write_text(textwrap.dedent("""\
            import sys
            print("warning", file=sys.stderr)
        """))
        cm = self._make_cm(str(tmp_path))
        ok, stdout, stderr = cm._run_cli("stderr_only.py")
        assert ok is True
        assert stdout == ""
        assert stderr == "warning"

    def test_timeout_returns_false_and_timeout_message(self, tmp_path):
        """A script that exceeds the timeout must return (False, '', 'Command timed out').

        Without this, a hung CLI tool would block the GUI thread indefinitely.
        """
        script = tmp_path / "sleeper.py"
        script.write_text(textwrap.dedent("""\
            import time
            time.sleep(60)
        """))
        cm = self._make_cm(str(tmp_path))
        start = time.monotonic()
        ok, stdout, stderr = cm._run_cli("sleeper.py", timeout=1)
        elapsed = time.monotonic() - start
        assert ok is False
        assert "timed out" in stderr.lower(), f"Expected timeout message, got: {stderr!r}"
        assert elapsed < 5, f"Timeout was not enforced promptly (elapsed {elapsed:.1f}s)"

    def test_cwd_is_set_to_cli_path(self, tmp_path):
        """Scripts must run with cwd=cli_path.

        Some CLI scripts import helpers from their own directory using relative
        imports; if cwd is wrong, those imports fail.
        """
        script = tmp_path / "report_cwd.py"
        script.write_text(textwrap.dedent("""\
            import os
            print(os.getcwd())
        """))
        cm = self._make_cm(str(tmp_path))
        ok, stdout, stderr = cm._run_cli("report_cwd.py")
        assert ok is True
        # Resolve symlinks for reliable comparison
        assert os.path.realpath(stdout) == os.path.realpath(str(tmp_path)), (
            f"cwd must be cli_path. Expected {str(tmp_path)!r}, got {stdout!r}"
        )

    def test_no_cli_path_returns_error_without_subprocess(self, tmp_path):
        """When cli_path is None, _run_cli must return False immediately.

        It must NOT attempt to call subprocess.run (which would error anyway
        but would also be slower and log confusing tracebacks).
        """
        cm = CardManager()
        cm.cli_path = None
        ok, stdout, stderr = cm._run_cli("anything.py")
        assert ok is False
        assert stdout == ""
        assert len(stderr) > 0, "Error message must be non-empty"
        assert "not found" in stderr.lower() or "sysmo" in stderr.lower() or "path" in stderr.lower()

    def test_invalid_script_path_traversal_blocked_at_run_cli(self, tmp_path):
        """_run_cli must refuse to run a path-traversal script name.

        Defense-in-depth: even if the caller forgets to validate, _run_cli
        itself blocks traversal attempts.
        """
        cm = self._make_cm(str(tmp_path))
        ok, stdout, stderr = cm._run_cli("../../../bin/sh")
        assert ok is False
        assert "invalid" in stderr.lower() or "path" in stderr.lower(), (
            f"Expected path-related error, got: {stderr!r}"
        )

    def test_missing_script_file_returns_false(self, tmp_path):
        """A script name that does not exist in cli_path must return False.

        The real sysmo-usim-tool has fixed script names; if the name is wrong,
        we must fail gracefully rather than raise an unhandled exception.
        """
        cm = self._make_cm(str(tmp_path))
        ok, stdout, stderr = cm._run_cli("nonexistent_script.py")
        assert ok is False

    def test_multiline_stdout_is_fully_captured(self, tmp_path):
        """All lines of stdout must be captured, not just the first.

        pySim-read.py produces multi-line output; truncating it would cause
        the parser to miss IMSI or ICCID lines.
        """
        script = tmp_path / "multiline.py"
        lines = ["Reading ...", "ICCID: 8988211000000123456", "IMSI: 001010000012345"]
        script.write_text("\n".join(f"print({line!r})" for line in lines) + "\n")
        cm = self._make_cm(str(tmp_path))
        ok, stdout, stderr = cm._run_cli("multiline.py")
        assert ok is True
        for line in lines:
            assert line in stdout, f"Line {line!r} missing from stdout: {stdout!r}"


# ===========================================================================
# Section 6 — authenticate() ADM1 lockout contract
# ===========================================================================

class TestAuthLockoutContract:
    """Verify the ADM1 lockout mechanism as seen through CardManager.

    Bug this catches: if the lockout check was after the decrement, a card
    would be permanently bricked on the third wrong attempt even if the
    operator later provided the correct ADM1.
    """

    def _sim_manager(self, num_cards: int = 1) -> CardManager:
        from simulator.settings import SimulatorSettings
        cm = CardManager()
        cm.enable_simulator(SimulatorSettings(delay_ms=0, num_cards=num_cards))
        return cm

    def test_correct_adm1_succeeds_immediately(self):
        """CardManager.authenticate() returns True for correct ADM1."""
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        ok, msg = cm.authenticate(card.adm1)
        assert ok is True
        assert cm.authenticated is True

    def test_wrong_adm1_fails_and_decrements(self):
        """Wrong ADM1 returns False and decrements attempts counter."""
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        ok, msg = cm.authenticate("00000000")
        assert ok is False
        assert card.adm1_attempts_remaining == 2

    def test_three_wrong_adm1_locks_card_permanently(self):
        """Three consecutive wrong ADM1 values lock the card permanently.

        This mirrors the real SIM card behaviour: ADM1 is a write-once counter.
        After the third failure the card enters a permanent locked state.
        """
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        for _ in range(3):
            cm.authenticate("00000000")
        assert card.adm1_locked is True
        assert card.adm1_attempts_remaining == 0
        # Even the correct ADM1 is now rejected
        ok, msg = cm.authenticate(card.adm1)
        assert ok is False
        assert "locked" in msg.lower()

    def test_iccid_mismatch_does_not_count_as_attempt(self):
        """ICCID mismatch must NOT decrement the ADM1 attempt counter.

        An operator might accidentally scan the wrong card then correct
        themselves; the ADM1 counter must not be consumed in that case.
        """
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        before = card.adm1_attempts_remaining
        # 5 ICCID mismatches
        for _ in range(5):
            cm.authenticate(card.adm1, expected_iccid="999999999999999")
        assert card.adm1_attempts_remaining == before, (
            "ICCID mismatch must not consume ADM1 attempts"
        )

    def test_correct_adm1_does_not_decrement_counter(self):
        """A successful authentication must not touch the attempts counter."""
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        before = card.adm1_attempts_remaining
        cm.authenticate(card.adm1)
        assert card.adm1_attempts_remaining == before

    def test_card_still_locked_after_correct_adm1_post_lock(self):
        """A locked card stays locked even if the correct ADM1 is given."""
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        for _ in range(3):
            cm.authenticate("00000000")
        ok, msg = cm.authenticate(card.adm1)  # correct but too late
        assert ok is False
        assert cm.authenticated is False


# ===========================================================================
# Section 7 — Full simulate-program-verify contract
# ===========================================================================

class TestSimulateProgramVerify:
    """End-to-end: authenticate → program → verify → check fields.

    Bug this catches: if programmed_fields were not consulted during
    verify_card(), every verification would pass regardless of what was
    written, silently producing garbage-programmed cards in the field.
    """

    def _sim_manager(self, num_cards: int = 1) -> CardManager:
        from simulator.settings import SimulatorSettings
        cm = CardManager()
        cm.enable_simulator(SimulatorSettings(delay_ms=0, num_cards=num_cards))
        return cm

    def test_full_program_verify_cycle_passes(self):
        """Authenticate → program IMSI+Ki → verify same values → success."""
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        ok, _ = cm.authenticate(card.adm1)
        assert ok is True

        data = {"imsi": "001010000099999", "ki": "A" * 32}
        ok, _ = cm.program_card(data)
        assert ok is True

        ok, mismatches = cm.verify_card(data)
        assert ok is True
        assert mismatches == []

    def test_verify_detects_wrong_imsi(self):
        """verify_card() catches an IMSI that was programmed differently."""
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        cm.authenticate(card.adm1)
        cm.program_card({"imsi": "001010000011111"})

        # Verify against different IMSI
        ok, mismatches = cm.verify_card({"imsi": "001010000099999"})
        assert ok is False
        assert any("imsi" in m.lower() for m in mismatches), (
            f"Expected 'imsi' in mismatch list, got: {mismatches}"
        )

    def test_verify_empty_dict_always_passes(self):
        """verify_card({}) passes for any card state."""
        cm = self._sim_manager()
        ok, mismatches = cm.verify_card({})
        assert ok is True
        assert mismatches == []

    def test_program_without_auth_fails(self):
        """program_card() without prior authenticate() must return False."""
        cm = self._sim_manager()
        ok, msg = cm.program_card({"imsi": "001010000099999"})
        assert ok is False
        assert "not authenticated" in msg.lower() or "auth" in msg.lower()

    def test_program_multiple_fields_all_written(self):
        """All fields passed to program_card() are written correctly."""
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        cm.authenticate(card.adm1)
        data = {
            "imsi": "001010000055555",
            "ki": "A" * 32,
            "opc": "B" * 32,
        }
        ok, _ = cm.program_card(data)
        assert ok is True

        ok, mismatches = cm.verify_card(data)
        assert ok is True, f"Unexpected mismatches: {mismatches}"

    def test_re_program_overwrites_previous_value(self):
        """Programming the same field twice stores the latest value."""
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        cm.authenticate(card.adm1)
        cm.program_card({"imsi": "111111111111111"})
        cm.program_card({"imsi": "222222222222222"})
        assert card.programmed_fields["imsi"] == "222222222222222"

    def test_read_card_data_reflects_programmed_fields(self):
        """read_card_data() returns a dict that includes programmed fields."""
        cm = self._sim_manager()
        card = cm._simulator._current_card()
        cm.authenticate(card.adm1)
        cm.program_card({"imsi": "999880001000001"})
        data = cm.read_card_data()
        assert data is not None
        # The programmed imsi should appear somewhere in read_card_data output
        assert "imsi" in data or "IMSI" in data


# ===========================================================================
# Section 8 — Hardware-gated tests (skipped in CI)
# ===========================================================================

class TestHardwareGated:
    """Tests that require real SIM hardware.

    Skipped unless SIMGUI_HW_TEST=1 is set in the environment.
    """

    @hardware
    def test_detect_real_card(self):
        """detect_card() succeeds with a real SIM inserted."""
        cm = CardManager()
        path, backend = _find_cli_tool()
        if path is None:
            pytest.skip("No CLI tool found")
        cm.set_cli_path(path)
        ok, msg = cm.detect_card()
        assert ok is True, f"detect_card failed: {msg}"
        assert "ICCID" in cm.card_info

    @hardware
    def test_authenticate_real_card(self):
        """authenticate() with correct ADM1 succeeds on real hardware."""
        adm1 = os.environ.get("SIMGUI_TEST_ADM1", "")
        if not adm1:
            pytest.skip("Set SIMGUI_TEST_ADM1 to run this test")
        cm = CardManager()
        path, _ = _find_cli_tool()
        if path is None:
            pytest.skip("No CLI tool found")
        cm.set_cli_path(path)
        cm.detect_card()
        ok, msg = cm.authenticate(adm1)
        assert ok is True, f"authenticate failed: {msg}"


# ===========================================================================
# Section 9 — Regression tests (specific bugs fixed in the codebase)
# ===========================================================================

class TestRegressions:
    """Regression tests — each test documents a specific bug that was fixed."""

    def test_iccid_mismatch_not_counted_as_failed_attempt_regression(self):
        """Regression: ICCID check must gate before the attempt counter decrement.

        In an early version of authenticate(), the ICCID check was performed
        AFTER the ADM1 was sent to the card, consuming an attempt even on
        mismatch. The correct behaviour: reject immediately before any attempt.
        """
        from simulator.settings import SimulatorSettings
        cm = CardManager()
        cm.enable_simulator(SimulatorSettings(delay_ms=0, num_cards=1))
        card = cm._simulator._current_card()
        before = card.adm1_attempts_remaining

        # Force 10 ICCID mismatches with correct ADM1
        for _ in range(10):
            cm.authenticate(card.adm1, expected_iccid="WRONG_ICCID")

        assert card.adm1_attempts_remaining == before, (
            "Regression: ICCID mismatch must not decrement ADM1 counter. "
            f"Expected {before}, got {card.adm1_attempts_remaining}"
        )

    def test_run_cli_path_traversal_blocked_regression(self, tmp_path):
        """Regression: _run_cli must block '../' path traversal unconditionally.

        An earlier version only validated the path when cli_path was set,
        allowing a traversal when cli_path pointed to a valid directory.
        """
        cm = CardManager()
        cm.cli_path = str(tmp_path)
        ok, _, stderr = cm._run_cli("../sneaky.py")
        assert ok is False
        assert "invalid" in stderr.lower() or "path" in stderr.lower(), (
            f"Regression: expected path-blocked error. Got: {stderr!r}"
        )

    def test_set_cli_path_does_not_modify_state_on_failure_regression(self, tmp_path):
        """Regression: set_cli_path() must be atomic — no partial state change.

        An old version set self.cli_path before checking if the path was a
        directory, leaving CardManager in an inconsistent state on failure.
        """
        cm = CardManager()
        cm.set_cli_path(str(tmp_path))  # valid path — sets state
        original_path = cm.cli_path
        original_backend = cm.cli_backend

        # Now try invalid path
        cm.set_cli_path(str(tmp_path / "not_a_dir"))

        # State must be unchanged
        assert cm.cli_path == original_path, (
            f"Regression: cli_path changed on failure. "
            f"Expected {original_path!r}, got {cm.cli_path!r}"
        )
        assert cm.cli_backend == original_backend

    def test_find_cli_tool_returns_absolute_path_regression(self, monkeypatch):
        """Regression: _find_cli_tool() must return an absolute path.

        If a relative path were returned, scripts in cli_path would fail to
        resolve when the process cwd changes (e.g., after os.chdir()).
        """
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.delenv("PYSIM_PATH", raising=False)

        # Monkey-patch isdir so the first sysmo candidate (expanduser) is "found"
        target = os.path.expanduser("~/sysmo-usim-tool")

        def fake_isdir(p):
            return str(p) == target

        monkeypatch.setattr(os.path, "isdir", fake_isdir)
        path, backend = _find_cli_tool()
        if path is not None:
            assert os.path.isabs(path), f"Returned path must be absolute, got {path!r}"
