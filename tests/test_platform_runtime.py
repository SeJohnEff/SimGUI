"""
Tests for the optional platform_runtime adapter.

Two categories:
  1. Linux/Ubuntu-correctness — the stub must return correct Ubuntu values.
  2. Phase 4 regression guards — common managers must remain importable
     whether platform_runtime is absent, broken, or returns bad data.
"""

import importlib
import os
import sys
import types
import unittest.mock as mock
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent


def _fresh_import(module_name: str):
    """Import a module, bypassing the cache (forces a real re-import)."""
    if module_name in sys.modules:
        del sys.modules[module_name]
    return importlib.import_module(module_name)


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
# 2. Phase 4 regression guards — common managers must always be importable
# ---------------------------------------------------------------------------

COMMON_MANAGERS = [
    "managers.card_manager",
    "managers.network_storage_manager",
    "managers.card_watcher",
    "state_manager",
]


def _purge_manager_cache():
    """Remove common manager modules from sys.modules to force re-import."""
    for mod in list(sys.modules.keys()):
        for manager in COMMON_MANAGERS + ["platform_runtime"]:
            if mod == manager or mod.startswith(manager + "."):
                del sys.modules[mod]


class TestCommonManagersImportWithoutPlatformRuntime:
    """Common managers must be importable when platform_runtime.py is absent."""

    def test_card_manager_importable_without_platform_runtime(self):
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": None}):
            import managers.card_manager  # noqa: F401

    def test_network_storage_manager_importable_without_platform_runtime(self):
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": None}):
            import managers.network_storage_manager  # noqa: F401

    def test_card_watcher_importable_without_platform_runtime(self):
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": None}):
            import managers.card_watcher  # noqa: F401

    def test_state_manager_importable_without_platform_runtime(self):
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": None}):
            import state_manager  # noqa: F401


class TestCommonManagersImportWithBrokenPlatformRuntime:
    """Common managers must be importable when platform_runtime raises ImportError."""

    def _make_raising_module(self):
        """Return a fake module whose import raises ImportError on attribute access."""
        # We simulate a module that raises ImportError when imported by
        # inserting a sentinel that causes the import machinery to raise.
        # The simplest way: replace sys.modules entry with None (which causes
        # ImportError on 'import platform_runtime').
        return None  # None in sys.modules → ImportError on import

    def test_card_manager_survives_platform_runtime_import_error(self):
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": None}):
            import managers.card_manager  # noqa: F401

    def test_network_storage_manager_survives_platform_runtime_import_error(self):
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": None}):
            import managers.network_storage_manager  # noqa: F401

    def test_card_watcher_survives_platform_runtime_import_error(self):
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": None}):
            import managers.card_watcher  # noqa: F401

    def test_state_manager_survives_platform_runtime_import_error(self):
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": None}):
            import state_manager  # noqa: F401


class TestCommonManagersImportWithInvalidPlatformRuntime:
    """Common managers must be importable when platform_runtime returns bad/incomplete data."""

    def _make_bad_platform_runtime(self):
        """Create a fake platform_runtime module with functions that return wrong types."""
        mod = types.ModuleType("platform_runtime")
        mod.pysim_search_dirs = lambda: None          # wrong type
        mod.sysmo_search_dirs = lambda: "not-a-list"  # wrong type
        mod.config_dir = lambda: 42                   # wrong type
        mod.mount_cmd_nfs = lambda src, dst: None     # wrong type
        mod.mount_cmd_smb = lambda src, dst, opts: {} # wrong type
        return mod

    def test_card_manager_survives_invalid_platform_runtime(self):
        bad_mod = self._make_bad_platform_runtime()
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": bad_mod}):
            import managers.card_manager  # noqa: F401

    def test_network_storage_manager_survives_invalid_platform_runtime(self):
        bad_mod = self._make_bad_platform_runtime()
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": bad_mod}):
            import managers.network_storage_manager  # noqa: F401

    def test_card_watcher_survives_invalid_platform_runtime(self):
        bad_mod = self._make_bad_platform_runtime()
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": bad_mod}):
            import managers.card_watcher  # noqa: F401

    def test_state_manager_survives_invalid_platform_runtime(self):
        bad_mod = self._make_bad_platform_runtime()
        _purge_manager_cache()
        with mock.patch.dict(sys.modules, {"platform_runtime": bad_mod}):
            import state_manager  # noqa: F401


# ---------------------------------------------------------------------------
# 3. No top-level platform_runtime import in common modules
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

        # Find module-level import lines: any 'import platform_runtime' or
        # 'from platform_runtime import' that is NOT inside a function/class
        # (i.e. indented). A top-level import has no leading whitespace.
        violations = []
        for lineno, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if not stripped.startswith(("#", '"""', "'''")):
                if ("import platform_runtime" in line or
                        "from platform_runtime" in line):
                    # Top-level = line has no leading whitespace (indent == 0)
                    indent = len(line) - len(line.lstrip())
                    if indent == 0:
                        violations.append((lineno, line.rstrip()))

        assert not violations, (
            f"{source_file} has top-level platform_runtime import(s) — "
            f"must be local imports only:\n" +
            "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
        )
