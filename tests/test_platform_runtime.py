"""
Tests for the optional platform_runtime adapter.

Four categories:
  1. Linux/Ubuntu-correctness — stub must return correct Ubuntu values.
  2. Phase 4 regression guards — common managers must remain importable
     whether platform_runtime is absent, broken, or returns bad data.
     Tests run in isolated subprocesses to prevent sys.modules pollution.
  3. _find_cli_tool() fallback — must preserve v0.5.50 Ubuntu defaults
     under every hostile platform_runtime condition.
  4. Static guardrail verification — top-level import guardrail catches
     violations and explicitly permits the local optional import pattern.
"""

import os
import subprocess
import sys
import types
import unittest.mock as mock
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _check_top_level_platform_runtime_imports(source: str) -> list:
    """Return (lineno, line) pairs for each top-level platform_runtime import.

    Top-level means indent == 0.  Imports inside function or class bodies
    (indent > 0) are permitted and are not returned.
    """
    violations = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("#", '"""', "'''")):
            continue
        if "import platform_runtime" in line or "from platform_runtime" in line:
            if len(line) - len(stripped) == 0:
                violations.append((lineno, line.rstrip()))
    return violations


def _isdir_for(allowed_paths):
    """Return an os.path.isdir side_effect that is True only for the given paths."""
    abs_allowed = {os.path.abspath(p) for p in allowed_paths}
    return lambda p: os.path.abspath(p) in abs_allowed


def _raise_runtime():
    raise RuntimeError("simulated platform_runtime failure")


# ---------------------------------------------------------------------------
# 1. Ubuntu-correctness tests for platform_runtime
# ---------------------------------------------------------------------------


class TestPlatformRuntimeLinuxDefaults:
    """platform_runtime.py must return correct Linux/Ubuntu values."""

    @pytest.fixture(autouse=True)
    def _force_linux(self):
        import platform_runtime as pr
        with mock.patch.object(pr, "_MACOS", False):
            self.pr = pr
            yield

    def test_pysim_search_dirs_includes_opt_pysim(self):
        dirs = self.pr.pysim_search_dirs()
        assert "/opt/pysim" in dirs, (
            "pysim_search_dirs() must include /opt/pysim (Ubuntu default)"
        )

    def test_pysim_search_dirs_returns_list(self):
        assert isinstance(self.pr.pysim_search_dirs(), list)

    def test_sysmo_search_dirs_includes_opt_sysmo(self):
        dirs = self.pr.sysmo_search_dirs()
        assert "/opt/sysmo-usim-tool" in dirs, (
            "sysmo_search_dirs() must include /opt/sysmo-usim-tool (Ubuntu default)"
        )

    def test_sysmo_search_dirs_returns_list(self):
        assert isinstance(self.pr.sysmo_search_dirs(), list)

    def test_mount_cmd_nfs_returns_linux_command(self):
        cmd = self.pr.mount_cmd_nfs("server:/share", "/mnt/dst")
        assert "nfs" in cmd, "mount_cmd_nfs must specify nfs mount type"
        assert "mount" in cmd[0], "mount_cmd_nfs must start with mount"
        assert "server:/share" in cmd
        assert "/mnt/dst" in cmd

    def test_mount_cmd_nfs_type_flag(self):
        cmd = self.pr.mount_cmd_nfs("server:/share", "/mnt/dst")
        assert "-t" in cmd
        nfs_idx = cmd.index("-t") + 1
        assert cmd[nfs_idx] == "nfs"

    def test_mount_cmd_smb_returns_linux_cifs_command(self):
        cmd = self.pr.mount_cmd_smb("//server/share", "/mnt/dst", ["-o", "vers=3.0"])
        assert "mount" in cmd[0]
        assert "//server/share" in cmd
        assert "/mnt/dst" in cmd

    def test_mount_cmd_smb_type_flag(self):
        cmd = self.pr.mount_cmd_smb("//server/share", "/mnt/dst", [])
        assert "-t" in cmd
        cifs_idx = cmd.index("-t") + 1
        assert cmd[cifs_idx] == "cifs"

    def test_mount_cmd_smb_includes_opts(self):
        opts = ["-o", "credentials=/tmp/creds"]
        cmd = self.pr.mount_cmd_smb("//server/share", "/mnt/dst", opts)
        assert "-o" in cmd
        assert "credentials=/tmp/creds" in cmd

    def test_config_dir_under_home(self):
        d = self.pr.config_dir()
        home = os.path.expanduser("~")
        assert d.startswith(home), (
            f"config_dir() '{d}' must be under home directory '{home}'"
        )

    def test_config_dir_contains_simgui(self):
        d = self.pr.config_dir()
        assert "simgui" in d.lower(), (
            f"config_dir() '{d}' must reference simgui"
        )

    def test_config_dir_returns_str(self):
        assert isinstance(self.pr.config_dir(), str)


# ---------------------------------------------------------------------------
# 2. Phase 4 regression guards — subprocess-isolated import tests
#
# Each test spawns a fresh Python interpreter so that sys.modules manipulation
# is fully contained and cannot corrupt the pytest process's module registry.
# ---------------------------------------------------------------------------

_COMMON_MANAGERS = [
    "managers.card_manager",
    "managers.network_storage_manager",
    "managers.card_watcher",
    "state_manager",
]

# Setup code injected before the import attempt in each subprocess scenario.
_SETUP_ABSENT = [
    # Simulate platform_runtime.py not present on the filesystem.
    "sys.modules['platform_runtime'] = None",
]

_SETUP_IMPORT_ERROR = [
    # Simulate platform_runtime.py present but unimportable (e.g. syntax error,
    # missing dependency). None in sys.modules causes ImportError on import.
    "sys.modules['platform_runtime'] = None",
]

_SETUP_INVALID_DATA = [
    # Simulate platform_runtime.py present but returning wrong types from all
    # public functions — guards against managers calling it at import time.
    "import types as _t",
    "_mod = _t.ModuleType('platform_runtime')",
    "_mod.pysim_search_dirs = lambda: None",
    "_mod.sysmo_search_dirs = lambda: 'not-a-list'",
    "_mod.config_dir = lambda: 42",
    "_mod.mount_cmd_nfs = lambda src, dst: None",
    "_mod.mount_cmd_smb = lambda src, dst, opts: {}",
    "sys.modules['platform_runtime'] = _mod",
]


def _run_import_subprocess(setup_lines, module_name):
    """
    Verify that `module_name` can be imported in a fresh Python subprocess
    after the given setup lines have been executed.

    Returns (success: bool, output: str).
    """
    script = "\n".join([
        "import sys, types",
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})",
    ] + setup_lines + [
        "try:",
        f"    import {module_name}",
        "except Exception as exc:",
        "    print(str(exc), file=sys.stderr)",
        "    sys.exit(1)",
    ])
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


@pytest.mark.parametrize("module_name", _COMMON_MANAGERS)
def test_importable_when_platform_runtime_absent(module_name):
    """Manager must be importable when platform_runtime.py does not exist."""
    ok, out = _run_import_subprocess(_SETUP_ABSENT, module_name)
    assert ok, (
        f"{module_name} failed to import with platform_runtime absent:\n{out}"
    )


@pytest.mark.parametrize("module_name", _COMMON_MANAGERS)
def test_importable_when_platform_runtime_raises_import_error(module_name):
    """Manager must be importable when platform_runtime raises ImportError."""
    ok, out = _run_import_subprocess(_SETUP_IMPORT_ERROR, module_name)
    assert ok, (
        f"{module_name} failed to import with platform_runtime raising ImportError:\n{out}"
    )


@pytest.mark.parametrize("module_name", _COMMON_MANAGERS)
def test_importable_when_platform_runtime_returns_invalid_data(module_name):
    """Manager must be importable when platform_runtime returns wrong types."""
    ok, out = _run_import_subprocess(_SETUP_INVALID_DATA, module_name)
    assert ok, (
        f"{module_name} failed to import with invalid platform_runtime data:\n{out}"
    )


# ---------------------------------------------------------------------------
# 3. _find_cli_tool() fallback behavior
#
# These tests verify that _find_cli_tool() returns the Ubuntu v0.5.50 defaults
# under every hostile platform_runtime condition.
#
# Safety note: mock.patch.dict is used ONLY for sys.modules['platform_runtime']
# and os.environ.  No manager module is evicted from sys.modules, so no
# module-identity corruption can leak into later tests.
# ---------------------------------------------------------------------------

from managers.card_manager import _find_cli_tool, CLIBackend  # noqa: E402


# Clear env vars that would short-circuit the search before platform_runtime.
_NO_CLI_ENV = {"SYSMO_USIM_TOOL_PATH": "", "PYSIM_PATH": ""}


def _call_find_cli_tool(patched_pr, isdir_allowed):
    """Call _find_cli_tool() with platform_runtime and isdir controlled."""
    with mock.patch.dict(sys.modules, {"platform_runtime": patched_pr}):
        with mock.patch.dict(os.environ, _NO_CLI_ENV):
            with mock.patch("os.path.isdir", side_effect=_isdir_for(isdir_allowed)):
                return _find_cli_tool()


class TestFindCliToolFallback:
    """_find_cli_tool() must preserve Ubuntu v0.5.50 defaults under every
    hostile platform_runtime condition."""

    def test_pysim_fallback_when_platform_runtime_absent(self):
        """ImportError from absent platform_runtime → /opt/pysim used."""
        path, backend = _call_find_cli_tool(None, ["/opt/pysim"])
        assert path == "/opt/pysim"
        assert backend == CLIBackend.PYSIM

    def test_sysmo_fallback_when_platform_runtime_absent(self):
        """ImportError from absent platform_runtime → /opt/sysmo-usim-tool used."""
        path, backend = _call_find_cli_tool(None, ["/opt/sysmo-usim-tool"])
        assert path == "/opt/sysmo-usim-tool"
        assert backend == CLIBackend.SYSMO

    def test_pysim_fallback_when_search_dirs_raises(self):
        """Exception from pysim_search_dirs() → /opt/pysim fallback used."""
        bad = types.ModuleType("platform_runtime")
        bad.sysmo_search_dirs = _raise_runtime
        bad.pysim_search_dirs = _raise_runtime
        path, backend = _call_find_cli_tool(bad, ["/opt/pysim"])
        assert path == "/opt/pysim"
        assert backend == CLIBackend.PYSIM

    def test_sysmo_fallback_when_search_dirs_raises(self):
        """Exception from sysmo_search_dirs() → /opt/sysmo-usim-tool fallback used."""
        bad = types.ModuleType("platform_runtime")
        bad.sysmo_search_dirs = _raise_runtime
        bad.pysim_search_dirs = _raise_runtime
        path, backend = _call_find_cli_tool(bad, ["/opt/sysmo-usim-tool"])
        assert path == "/opt/sysmo-usim-tool"
        assert backend == CLIBackend.SYSMO

    def test_pysim_fallback_when_returns_none(self):
        """pysim_search_dirs() returning None → /opt/pysim fallback used."""
        bad = types.ModuleType("platform_runtime")
        bad.sysmo_search_dirs = lambda: None
        bad.pysim_search_dirs = lambda: None
        path, backend = _call_find_cli_tool(bad, ["/opt/pysim"])
        assert path == "/opt/pysim"
        assert backend == CLIBackend.PYSIM

    def test_pysim_fallback_when_returns_string(self):
        """pysim_search_dirs() returning a string → /opt/pysim fallback used."""
        bad = types.ModuleType("platform_runtime")
        bad.sysmo_search_dirs = lambda: "not-a-list"
        bad.pysim_search_dirs = lambda: "not-a-list"
        path, backend = _call_find_cli_tool(bad, ["/opt/pysim"])
        assert path == "/opt/pysim"
        assert backend == CLIBackend.PYSIM

    def test_pysim_fallback_when_returns_empty_list(self):
        """pysim_search_dirs() returning [] → /opt/pysim fallback used."""
        bad = types.ModuleType("platform_runtime")
        bad.sysmo_search_dirs = lambda: []
        bad.pysim_search_dirs = lambda: []
        path, backend = _call_find_cli_tool(bad, ["/opt/pysim"])
        assert path == "/opt/pysim"
        assert backend == CLIBackend.PYSIM

    def test_pysim_custom_dir_used_when_platform_runtime_valid(self):
        """When platform_runtime returns a valid list, those paths are searched."""
        good = types.ModuleType("platform_runtime")
        good.sysmo_search_dirs = lambda: ["/opt/sysmo-usim-tool"]
        good.pysim_search_dirs = lambda: ["/custom/pysim"]
        path, backend = _call_find_cli_tool(good, ["/custom/pysim"])
        assert path == "/custom/pysim"
        assert backend == CLIBackend.PYSIM

    def test_sysmo_custom_dir_used_when_platform_runtime_valid(self):
        """When platform_runtime returns a valid sysmo list, it is searched."""
        good = types.ModuleType("platform_runtime")
        good.sysmo_search_dirs = lambda: ["/custom/sysmo"]
        good.pysim_search_dirs = lambda: ["/opt/pysim"]
        path, backend = _call_find_cli_tool(good, ["/custom/sysmo"])
        assert path == "/custom/sysmo"
        assert backend == CLIBackend.SYSMO


# ---------------------------------------------------------------------------
# 4. Static guardrail self-verification
#
# Proves the top-level import prohibition is enforced, and that the local
# optional pattern used in _find_cli_tool() is correctly NOT flagged.
#
# The concern "avoiding the static checker" is addressed here:
# - _collect_module_call_issues() in test_interface_contracts.py flags bare
#   ast.Name calls (e.g. sysmo_search_dirs()) that aren't defined at module
#   scope.  It does NOT flag ast.Attribute calls like _pr.sysmo_search_dirs().
# - This is not a bypass: the checker was designed to catch undefined bare
#   names, not attribute access on imported modules.  Using the module-level
#   import pattern (_pr.func()) is standard Python for locally imported modules.
# - The prohibition that matters — no top-level platform_runtime import — is
#   enforced by _check_top_level_platform_runtime_imports(), tested below.
# ---------------------------------------------------------------------------


class TestStaticGuardrailSelfVerification:
    """The top-level import guardrail must catch violations and must permit
    the local optional import pattern used in _find_cli_tool()."""

    def test_guardrail_catches_top_level_bare_import(self):
        """A bare top-level 'import platform_runtime' is flagged as a violation."""
        source = "import platform_runtime\n\ndef foo(): pass\n"
        violations = _check_top_level_platform_runtime_imports(source)
        assert violations, "Guardrail must flag top-level bare import"
        assert "import platform_runtime" in violations[0][1]

    def test_guardrail_catches_top_level_from_import(self):
        """A top-level 'from platform_runtime import X' is flagged."""
        source = "from platform_runtime import pysim_search_dirs\n\ndef foo(): pass\n"
        violations = _check_top_level_platform_runtime_imports(source)
        assert violations, "Guardrail must flag top-level from-import"
        assert "from platform_runtime" in violations[0][1]

    def test_guardrail_permits_local_import_as_used_in_find_cli_tool(self):
        """The exact pattern used in _find_cli_tool() — local 'import module as _m'
        inside a try block — is not flagged."""
        source = (
            "def _find_cli_tool():\n"
            "    try:\n"
            "        import platform_runtime as _pr\n"
            "        _pr.sysmo_search_dirs()\n"
            "    except Exception:\n"
            "        pass\n"
        )
        violations = _check_top_level_platform_runtime_imports(source)
        assert not violations, (
            f"Local optional import must not be flagged, but got: {violations}"
        )

    def test_guardrail_permits_local_from_import_inside_function(self):
        """A 'from platform_runtime import X' inside a function body is also permitted."""
        source = (
            "def func():\n"
            "    try:\n"
            "        from platform_runtime import pysim_search_dirs\n"
            "        pysim_search_dirs()\n"
            "    except Exception:\n"
            "        pass\n"
        )
        violations = _check_top_level_platform_runtime_imports(source)
        assert not violations, (
            f"Local from-import must not be flagged, but got: {violations}"
        )

    def test_guardrail_finds_no_violations_in_card_manager(self):
        """Running the guardrail against the actual card_manager.py finds no violations."""
        source = (PROJECT_ROOT / "managers/card_manager.py").read_text()
        violations = _check_top_level_platform_runtime_imports(source)
        assert not violations, (
            "card_manager.py has top-level platform_runtime import(s):\n" +
            "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
        )


# ---------------------------------------------------------------------------
# 5. No top-level platform_runtime import in common modules (source audit)
# ---------------------------------------------------------------------------


class TestNoTopLevelPlatformRuntimeImport:
    """Prohibition 1: platform_runtime must NOT be imported at module scope
    in any common manager. Any import must be local (inside a function)."""

    @pytest.mark.parametrize("source_file", [
        "managers/card_manager.py",
        "managers/network_storage_manager.py",
        "managers/card_watcher.py",
        "state_manager.py",
    ])
    def test_no_top_level_platform_runtime_import(self, source_file):
        source = (PROJECT_ROOT / source_file).read_text()
        violations = _check_top_level_platform_runtime_imports(source)
        assert not violations, (
            f"{source_file} has top-level platform_runtime import(s) — "
            f"must be local imports only:\n" +
            "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
        )


# ---------------------------------------------------------------------------
# 6. macOS-specific platform_runtime values
#
# Verifies macOS values are correct when _MACOS=True, and that Linux values
# remain unchanged when _MACOS=False (belt-and-suspenders for S2-E).
# ---------------------------------------------------------------------------


class TestPlatformRuntimeMacOSValues:
    """platform_runtime.py must return correct macOS values when _MACOS=True."""

    @pytest.fixture(autouse=True)
    def _force_macos(self):
        import platform_runtime as pr
        with mock.patch.object(pr, "_MACOS", True):
            self.pr = pr
            yield

    def test_pysim_search_dirs_includes_home_pysim(self):
        dirs = self.pr.pysim_search_dirs()
        home = os.path.expanduser("~")
        assert any(d.startswith(home) and "pysim" in d for d in dirs), (
            f"pysim_search_dirs() on macOS must include ~/pysim; got {dirs}"
        )

    def test_pysim_search_dirs_does_not_include_opt_pysim(self):
        dirs = self.pr.pysim_search_dirs()
        assert "/opt/pysim" not in dirs, (
            "pysim_search_dirs() on macOS must not return /opt/pysim "
            "(Ubuntu-only path)"
        )

    def test_pysim_search_dirs_returns_list(self):
        assert isinstance(self.pr.pysim_search_dirs(), list)

    def test_mount_cmd_nfs_returns_absolute_binary_path(self):
        cmd = self.pr.mount_cmd_nfs("server:/share", "/mnt/dst")
        assert cmd, "mount_cmd_nfs() must return a non-empty list on macOS"
        assert os.path.isabs(cmd[0]), (
            f"mount_cmd_nfs()[0] must be an absolute path on macOS; got '{cmd[0]}'"
        )

    def test_mount_cmd_nfs_absolute_path_guard_passes(self):
        """The absolute-path guard in _build_mount_cmd() must pass for macOS NFS."""
        cmd = self.pr.mount_cmd_nfs("server:/share", "/mnt/dst")
        guard = isinstance(cmd, list) and bool(cmd) and os.path.isabs(cmd[0])
        assert guard, (
            "macOS mount_cmd_nfs() must satisfy the absolute-path guard so "
            "platform_runtime hook fires; got cmd={cmd!r}"
        )

    def test_mount_cmd_nfs_contains_nfs_and_addresses(self):
        cmd = self.pr.mount_cmd_nfs("server:/share", "/mnt/dst")
        assert "nfs" in cmd
        assert "server:/share" in cmd
        assert "/mnt/dst" in cmd

    def test_mount_cmd_smb_returns_empty_on_macos(self):
        """macOS mount_cmd_smb() returns [] so the caller's _MACOS branch handles creds."""
        cmd = self.pr.mount_cmd_smb("//server/share", "/mnt/dst", ["-o", "vers=3.0"])
        assert cmd == [], (
            "mount_cmd_smb() on macOS must return [] to defer to the "
            "_MACOS credential-embedding branch; got {cmd!r}"
        )

    def test_mount_cmd_smb_guard_fails_so_macos_branch_runs(self):
        """Empty list fails the absolute-path guard, ensuring _MACOS branch handles SMB."""
        cmd = self.pr.mount_cmd_smb("//server/share", "/mnt/dst", [])
        guard = isinstance(cmd, list) and bool(cmd) and os.path.isabs(cmd[0])
        assert not guard, (
            "macOS mount_cmd_smb() must fail the absolute-path guard so the "
            "_MACOS credential branch runs; guard was True for cmd={cmd!r}"
        )

    def test_config_dir_uses_library_application_support(self):
        d = self.pr.config_dir()
        assert "Library/Application Support" in d, (
            f"config_dir() on macOS must use ~/Library/Application Support; got '{d}'"
        )

    def test_config_dir_contains_simgui(self):
        d = self.pr.config_dir()
        assert "simgui" in d.lower(), (
            f"config_dir() on macOS '{d}' must reference simgui"
        )

    def test_config_dir_under_home(self):
        d = self.pr.config_dir()
        home = os.path.expanduser("~")
        assert d.startswith(home), (
            f"config_dir() on macOS '{d}' must be under home '{home}'"
        )

    def test_config_dir_returns_str(self):
        assert isinstance(self.pr.config_dir(), str)


class TestPlatformRuntimeLinuxValuesUnchangedByS2E:
    """Belt-and-suspenders: Linux values must be identical after S2-E changes."""

    @pytest.fixture(autouse=True)
    def _force_linux(self):
        import platform_runtime as pr
        with mock.patch.object(pr, "_MACOS", False):
            self.pr = pr
            yield

    def test_pysim_search_dirs_still_opt_pysim(self):
        assert "/opt/pysim" in self.pr.pysim_search_dirs()

    def test_sysmo_search_dirs_still_opt_sysmo(self):
        assert "/opt/sysmo-usim-tool" in self.pr.sysmo_search_dirs()

    def test_config_dir_still_dotconfig(self):
        d = self.pr.config_dir()
        assert ".config/simgui" in d

    def test_mount_cmd_nfs_still_bare_mount(self):
        cmd = self.pr.mount_cmd_nfs("server:/share", "/mnt/dst")
        assert cmd[0] == "mount"
        assert not os.path.isabs(cmd[0]), (
            "Linux NFS mount_cmd_nfs()[0] must be bare 'mount' (relative) so "
            "absolute-path guard fails and existing Linux path runs"
        )

    def test_mount_cmd_smb_still_cifs(self):
        cmd = self.pr.mount_cmd_smb("//server/share", "/mnt/dst", [])
        assert "-t" in cmd
        assert cmd[cmd.index("-t") + 1] == "cifs"
