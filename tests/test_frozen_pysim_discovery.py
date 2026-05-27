"""Phase 2 — frozen-mode pySim discovery and bundled runtime tests.

Covers:
- _find_cli_tool() in frozen mode: bundle found, bundle missing, no ~/pysim fallthrough
- _get_bundled_python(): bundle present, bundle absent, dev mode
- _get_pysim_env(): PYTHONPATH contents in frozen mode, None in dev mode
- CardManager subprocess methods: clear error when bundled Python missing in frozen mode
- Dev mode: PYSIM_PATH env override still works unchanged
"""
import os
import sys
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from managers.card_manager import (
    CardManager,
    CLIBackend,
    _find_cli_tool,
    _get_bundled_python,
    _get_pysim_env,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frozen(monkeypatch, meipass: str) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", meipass, raising=False)


def _clear_frozen(monkeypatch) -> None:
    if hasattr(sys, "frozen"):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
    if hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)


# ---------------------------------------------------------------------------
# _find_cli_tool — frozen mode
# ---------------------------------------------------------------------------

class TestFindCliToolFrozen:
    """_find_cli_tool() contracts in frozen (PyInstaller) mode."""

    def test_frozen_bundle_found_returns_pysim(self, tmp_path, monkeypatch):
        """In frozen mode, returns bundled pySim path when pysim/ dir exists."""
        bundle_pysim = tmp_path / "pysim"
        bundle_pysim.mkdir()
        _make_frozen(monkeypatch, str(tmp_path))
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.delenv("PYSIM_PATH", raising=False)

        path, backend = _find_cli_tool()

        assert path == str(bundle_pysim)
        assert backend == CLIBackend.PYSIM

    def test_frozen_bundle_missing_returns_none(self, tmp_path, monkeypatch):
        """In frozen mode, missing bundled pySim returns (None, NONE)."""
        # tmp_path has no 'pysim' subdir
        _make_frozen(monkeypatch, str(tmp_path))
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.delenv("PYSIM_PATH", raising=False)

        path, backend = _find_cli_tool()

        assert path is None
        assert backend == CLIBackend.NONE

    def test_frozen_bundle_missing_does_not_check_home_pysim(
        self, tmp_path, monkeypatch
    ):
        """In frozen mode, ~/pysim is never consulted even if it would exist."""
        _make_frozen(monkeypatch, str(tmp_path))
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.delenv("PYSIM_PATH", raising=False)

        checked_dirs = []
        original_isdir = os.path.isdir

        def tracking_isdir(p):
            checked_dirs.append(str(p))
            return original_isdir(p)

        monkeypatch.setattr(os.path, "isdir", tracking_isdir)
        _find_cli_tool()

        home_pysim = os.path.expanduser("~/pysim")
        assert home_pysim not in checked_dirs, (
            "~/pysim must never be checked when running frozen"
        )

    def test_frozen_bundle_missing_does_not_check_opt_pysim(
        self, tmp_path, monkeypatch
    ):
        """In frozen mode, /opt/pysim is never checked."""
        _make_frozen(monkeypatch, str(tmp_path))
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.delenv("PYSIM_PATH", raising=False)

        checked_dirs = []
        original_isdir = os.path.isdir

        def tracking_isdir(p):
            checked_dirs.append(str(p))
            return original_isdir(p)

        monkeypatch.setattr(os.path, "isdir", tracking_isdir)
        _find_cli_tool()

        assert "/opt/pysim" not in checked_dirs, (
            "/opt/pysim must never be checked when running frozen"
        )


# ---------------------------------------------------------------------------
# _find_cli_tool — dev mode unaffected
# ---------------------------------------------------------------------------

class TestFindCliToolDevMode:
    """Dev (non-frozen) mode contracts are unchanged."""

    def test_dev_pysim_path_env_used(self, tmp_path, monkeypatch):
        """In dev mode, PYSIM_PATH env override still works."""
        _clear_frozen(monkeypatch)
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.setenv("PYSIM_PATH", str(tmp_path))

        path, backend = _find_cli_tool()

        assert path == str(tmp_path)
        assert backend == CLIBackend.PYSIM

    def test_dev_returns_none_when_no_tool(self, monkeypatch):
        """In dev mode with no tools, returns (None, NONE)."""
        _clear_frozen(monkeypatch)
        monkeypatch.delenv("SYSMO_USIM_TOOL_PATH", raising=False)
        monkeypatch.delenv("PYSIM_PATH", raising=False)
        monkeypatch.setattr(os.path, "isdir", lambda _p: False)

        path, backend = _find_cli_tool()

        assert path is None
        assert backend == CLIBackend.NONE


# ---------------------------------------------------------------------------
# _get_bundled_python
# ---------------------------------------------------------------------------

def _make_bundle(tmp_path):
    """Return (resources_path, contents_path) for a minimal fake app bundle."""
    contents = tmp_path / "Contents"
    resources = contents / "Resources"
    resources.mkdir(parents=True)
    return resources, contents


def _make_executable(path):
    path.write_text("#!/bin/sh\nexec python3 \"$@\"\n")
    path.chmod(0o755)


class TestGetBundledPython:
    """_get_bundled_python() lookup order: Frameworks first, MacOS/ fallback."""

    def test_dev_mode_returns_none(self, monkeypatch):
        """In dev mode, always returns None."""
        _clear_frozen(monkeypatch)
        assert _get_bundled_python() is None

    # -- Frameworks path (preferred) -----------------------------------------

    def test_frozen_finds_python_in_framework_bin(self, tmp_path, monkeypatch):
        """Finds python3.9 under Frameworks/Python3.framework/Versions/3.9/bin/."""
        resources, contents = _make_bundle(tmp_path)
        fw_bin = (contents / "Frameworks" / "Python3.framework" /
                  "Versions" / "3.9" / "bin")
        fw_bin.mkdir(parents=True)
        python_bin = fw_bin / "python3.9"
        _make_executable(python_bin)

        _make_frozen(monkeypatch, str(resources))

        result = _get_bundled_python()
        assert result == str(python_bin)

    def test_frozen_framework_path_takes_priority_over_macos(self, tmp_path, monkeypatch):
        """Framework bin/ is returned even when MacOS/python3.9 also exists."""
        resources, contents = _make_bundle(tmp_path)

        fw_bin = (contents / "Frameworks" / "Python3.framework" /
                  "Versions" / "3.9" / "bin")
        fw_bin.mkdir(parents=True)
        fw_python = fw_bin / "python3.9"
        _make_executable(fw_python)

        macos = contents / "MacOS"
        macos.mkdir(parents=True)
        macos_python = macos / "python3.9"
        _make_executable(macos_python)

        _make_frozen(monkeypatch, str(resources))

        result = _get_bundled_python()
        assert result == str(fw_python), (
            "Frameworks path must win over MacOS/ path"
        )

    # -- MacOS/ fallback -----------------------------------------------------

    def test_frozen_falls_back_to_macos_python39(self, tmp_path, monkeypatch):
        """Falls back to Contents/MacOS/python3.9 when Frameworks bin/ is absent."""
        resources, contents = _make_bundle(tmp_path)
        macos = contents / "MacOS"
        macos.mkdir(parents=True)
        python_bin = macos / "python3.9"
        _make_executable(python_bin)

        _make_frozen(monkeypatch, str(resources))

        result = _get_bundled_python()
        assert result == str(python_bin)

    def test_frozen_falls_back_to_macos_python3(self, tmp_path, monkeypatch):
        """Falls back to Contents/MacOS/python3 when python3.9 absent."""
        resources, contents = _make_bundle(tmp_path)
        macos = contents / "MacOS"
        macos.mkdir(parents=True)
        python_bin = macos / "python3"
        _make_executable(python_bin)

        _make_frozen(monkeypatch, str(resources))

        result = _get_bundled_python()
        assert result == str(python_bin)

    # -- Nothing found -------------------------------------------------------

    def test_frozen_returns_none_when_no_bundled_python(self, tmp_path, monkeypatch):
        """Returns None when neither Frameworks bin/ nor MacOS/ has a Python."""
        resources, contents = _make_bundle(tmp_path)
        (contents / "MacOS").mkdir(parents=True)
        # No executables created

        _make_frozen(monkeypatch, str(resources))

        result = _get_bundled_python()
        assert result is None

    def test_frozen_does_not_search_external_paths(self, tmp_path, monkeypatch):
        """In frozen mode, external paths like /opt/homebrew are never checked."""
        resources, _contents = _make_bundle(tmp_path)
        _make_frozen(monkeypatch, str(resources))

        checked = []
        original_isfile = os.path.isfile
        original_access = os.access

        def tracking_isfile(p):
            checked.append(str(p))
            return original_isfile(p)

        monkeypatch.setattr(os.path, "isfile", tracking_isfile)

        _get_bundled_python()

        external = [p for p in checked if "/opt/homebrew" in p or "/usr/local" in p]
        assert not external, (
            f"_get_bundled_python must not probe external paths: {external}"
        )


# ---------------------------------------------------------------------------
# _get_pysim_env
# ---------------------------------------------------------------------------

class TestGetPySimEnv:
    """_get_pysim_env() returns correct PYTHONPATH in frozen mode."""

    def test_dev_mode_returns_none(self, monkeypatch):
        """In dev mode, returns None (no env override needed)."""
        _clear_frozen(monkeypatch)
        assert _get_pysim_env() is None

    def test_frozen_returns_pythonpath_with_both_dirs(self, tmp_path, monkeypatch):
        """In frozen mode, PYTHONPATH contains pysim/ and pysim-site-packages/."""
        pysim_dir = tmp_path / "pysim"
        site_pkgs = tmp_path / "pysim-site-packages"
        pysim_dir.mkdir()
        site_pkgs.mkdir()
        _make_frozen(monkeypatch, str(tmp_path))

        env = _get_pysim_env()

        assert env is not None
        pythonpath = env.get("PYTHONPATH", "")
        assert str(pysim_dir) in pythonpath
        assert str(site_pkgs) in pythonpath

    def test_frozen_pysim_dir_precedes_site_packages(self, tmp_path, monkeypatch):
        """pySim scripts dir must appear before site-packages in PYTHONPATH."""
        pysim_dir = tmp_path / "pysim"
        site_pkgs = tmp_path / "pysim-site-packages"
        pysim_dir.mkdir()
        site_pkgs.mkdir()
        _make_frozen(monkeypatch, str(tmp_path))

        env = _get_pysim_env()
        assert env is not None

        paths = [p for p in env["PYTHONPATH"].split(os.pathsep) if p]
        pysim_idx = next(i for i, p in enumerate(paths) if str(pysim_dir) in p)
        site_idx = next(i for i, p in enumerate(paths) if str(site_pkgs) in p)
        assert pysim_idx < site_idx

    def test_frozen_preserves_existing_env_vars(self, tmp_path, monkeypatch):
        """All other environment variables are preserved in the returned dict."""
        (tmp_path / "pysim").mkdir()
        _make_frozen(monkeypatch, str(tmp_path))
        monkeypatch.setenv("SIMGUI_TEST_SENTINEL", "sentinel_value")

        env = _get_pysim_env()

        assert env is not None
        assert env.get("SIMGUI_TEST_SENTINEL") == "sentinel_value"

    def test_frozen_returns_none_when_no_pysim_dirs(self, tmp_path, monkeypatch):
        """Returns None when neither pysim/ nor pysim-site-packages/ exist."""
        # tmp_path has neither subdirectory
        _make_frozen(monkeypatch, str(tmp_path))

        result = _get_pysim_env()
        assert result is None


# ---------------------------------------------------------------------------
# CardManager: clear error when bundled Python missing in frozen mode
# ---------------------------------------------------------------------------

class TestFrozenMissingBundledPythonError:
    """Subprocess methods surface a clear error when bundled Python is absent."""

    _ERROR_FRAGMENT = "Bundled pySim runtime incomplete"

    def _make_frozen_cm(self, tmp_path, monkeypatch):
        """Build a CardManager with cli_path set and _bundled_python=None."""
        pysim_dir = tmp_path / "pysim"
        pysim_dir.mkdir()
        site_pkgs = tmp_path / "pysim-site-packages"
        site_pkgs.mkdir()

        _make_frozen(monkeypatch, str(tmp_path))

        # Create a fake script so _validate_script_path succeeds
        fake_read = pysim_dir / "pySim-read.py"
        fake_read.write_text("# stub\n")
        fake_shell = pysim_dir / "pySim-shell.py"
        fake_shell.write_text("# stub\n")
        fake_prog = pysim_dir / "pySim-prog.py"
        fake_prog.write_text("# stub\n")

        cm = CardManager.__new__(CardManager)
        cm.cli_path = str(pysim_dir)
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = None
        cm._bundled_python = None   # simulate: bundle present but no Python yet
        cm._pcsc_reader_index = 0
        cm.card_type = __import__('managers.card_manager', fromlist=['CardType']).CardType.UNKNOWN
        return cm

    def test_run_cli_returns_clear_error(self, tmp_path, monkeypatch):
        """_run_cli returns 'Bundled pySim runtime incomplete' when bundled Python absent."""
        cm = self._make_frozen_cm(tmp_path, monkeypatch)
        ok, _stdout, stderr = cm._run_cli("pySim-read.py")
        assert ok is False
        assert self._ERROR_FRAGMENT in stderr

    def test_run_pysim_shell_impl_returns_clear_error(self, tmp_path, monkeypatch):
        """_run_pysim_shell_impl returns clear error when bundled Python absent."""
        cm = self._make_frozen_cm(tmp_path, monkeypatch)
        ok, _stdout, stderr = cm._run_pysim_shell_impl(adm1_hex=None, commands="")
        assert ok is False
        assert self._ERROR_FRAGMENT in stderr

    def test_run_pysim_prog_returns_clear_error(self, tmp_path, monkeypatch):
        """_run_pysim_prog returns clear error when bundled Python absent."""
        cm = self._make_frozen_cm(tmp_path, monkeypatch)
        ok, _stdout, stderr = cm._run_pysim_prog({}, adm1_hex="3838383838383838")
        assert ok is False
        assert self._ERROR_FRAGMENT in stderr


# ---------------------------------------------------------------------------
# CardManager: subprocess env in frozen mode with bundled Python
# ---------------------------------------------------------------------------

class TestFrozenSubprocessEnvPassthrough:
    """When bundled Python exists, subprocess.run receives pySim env."""

    def test_run_cli_passes_pythonpath_env(self, tmp_path, monkeypatch):
        """In frozen mode with bundled Python, subprocess.run gets PYTHONPATH."""
        # Lay out a realistic app bundle structure under tmp_path:
        #   Contents/
        #     Frameworks/Python3.framework/Versions/3.9/bin/python3.9  ← interpreter
        #     Resources/               ← sys._MEIPASS
        #       pysim/pySim-read.py    ← bundled pySim scripts
        #       pysim-site-packages/   ← bundled site-packages
        resources, contents = _make_bundle(tmp_path)
        fw_bin = (contents / "Frameworks" / "Python3.framework" /
                  "Versions" / "3.9" / "bin")
        fw_bin.mkdir(parents=True)
        bundled_py = fw_bin / "python3.9"
        _make_executable(bundled_py)

        # pySim dirs must be under MEIPASS so _get_pysim_env finds them
        pysim_dir = resources / "pysim"
        site_pkgs = resources / "pysim-site-packages"
        pysim_dir.mkdir()
        site_pkgs.mkdir()
        (pysim_dir / "pySim-read.py").write_text("# stub\n")

        _make_frozen(monkeypatch, str(resources))

        cm = CardManager.__new__(CardManager)
        cm.cli_path = str(pysim_dir)
        cm.cli_backend = CLIBackend.PYSIM
        cm._venv_python = None
        cm._bundled_python = str(bundled_py)
        cm._pcsc_reader_index = 0

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["kwargs"] = kwargs
            captured["cmd"] = cmd
            return MagicMock(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        cm._run_cli("pySim-read.py")

        env = captured.get("kwargs", {}).get("env")
        assert env is not None, "env kwarg must be passed to subprocess.run in frozen mode"
        pythonpath = env.get("PYTHONPATH", "")
        assert str(pysim_dir) in pythonpath, "pysim dir must be in PYTHONPATH"
        assert str(site_pkgs) in pythonpath, "site-packages must be in PYTHONPATH"
