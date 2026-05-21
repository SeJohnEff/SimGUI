"""
Tests for the optional platform_runtime adapter.

Three categories:
  1. Linux/Ubuntu-correctness — the stub must return correct Ubuntu values.
  2. Phase 4 regression guards — common managers must remain importable
     whether platform_runtime is absent, broken, or returns bad data.
     These tests run in isolated subprocesses to prevent sys.modules pollution.
  3. Static analysis — no top-level platform_runtime import in common managers.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# 1. Ubuntu-correctness tests for platform_runtime
# ---------------------------------------------------------------------------


class TestPlatformRuntimeLinuxDefaults:
    """platform_runtime.py must return correct Linux/Ubuntu values."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        import platform_runtime as pr
        self.pr = pr

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
# 3. Static analysis — no top-level platform_runtime import in common managers
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
        path = PROJECT_ROOT / source_file
        source = path.read_text()
        lines = source.splitlines()

        violations = []
        for lineno, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith(("#", '"""', "'''")):
                continue
            if ("import platform_runtime" in line or
                    "from platform_runtime" in line):
                indent = len(line) - len(line.lstrip())
                if indent == 0:
                    violations.append((lineno, line.rstrip()))

        assert not violations, (
            f"{source_file} has top-level platform_runtime import(s) — "
            f"must be local imports only:\n" +
            "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
        )
