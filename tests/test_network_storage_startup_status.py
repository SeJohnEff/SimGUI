"""Tests for network storage startup reachability and UI-thread safety.

Verifies that:
- A saved profile with an unreachable share does not show as connected/green.
- A stale OS mount (is_mounted=True but inaccessible) is not adopted by
  sync_os_mounts().
- A reachable share still shows as connected.
- Opening the Network Storage dialog does not call blocking is_mounted()
  on the UI thread.
"""

import subprocess
import sys
import os

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from managers.network_storage_manager import NetworkStorageManager, StorageProfile


def _make_profile(**kwargs):
    defaults = dict(
        label="NAS SIM",
        protocol="smb",
        server="192.168.1.10",
        share="simdata",
        username="simgui",
        password="secret",
        last_used=True,
    )
    defaults.update(kwargs)
    return StorageProfile(**defaults)


# ---------------------------------------------------------------------------
# reconnect_saved — stale mount detection
# ---------------------------------------------------------------------------

class TestReconnectSavedReachability:
    """reconnect_saved() must not mark inaccessible shares as connected."""

    def test_stale_mount_not_in_active_mounts(self):
        """OS mount present but inaccessible → removed from _active_mounts."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock(return_value=(True, "Already mounted"))
        mgr.verify_mount_accessible = MagicMock(return_value=False)

        mgr.reconnect_saved()

        assert p.label not in mgr._active_mounts

    def test_stale_mount_reported_as_failure(self):
        """Stale mount → reconnect_saved returns ok=False."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock(return_value=(True, "Already mounted"))
        mgr.verify_mount_accessible = MagicMock(return_value=False)

        results = mgr.reconnect_saved()

        assert len(results) == 1
        label, ok, msg = results[0]
        assert label == "NAS SIM"
        assert not ok

    def test_accessible_share_stays_connected(self):
        """Accessible mount → ok=True and label in _active_mounts."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])

        def _mock_mount(prof):
            mgr._active_mounts[prof.label] = prof
            return True, "Mounted"

        mgr.mount = _mock_mount
        mgr.verify_mount_accessible = MagicMock(return_value=True)

        results = mgr.reconnect_saved()

        label, ok, msg = results[0]
        assert ok
        assert p.label in mgr._active_mounts

    def test_mount_failure_skips_verify(self):
        """If mount() fails, verify_mount_accessible is never called."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock(return_value=(False, "Host unreachable"))
        mgr.verify_mount_accessible = MagicMock()

        results = mgr.reconnect_saved()

        label, ok, msg = results[0]
        assert not ok
        mgr.verify_mount_accessible.assert_not_called()

    def test_not_last_used_not_attempted(self):
        """Profiles without last_used=True are never mounted."""
        mgr = NetworkStorageManager()
        p = _make_profile(last_used=False)
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock()

        results = mgr.reconnect_saved()

        assert results == []
        mgr.mount.assert_not_called()

    def test_previously_tracked_stale_mount_removed(self):
        """Even if label was in _active_mounts before, stale detection removes it."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts["NAS SIM"] = p  # simulate leftover from prior call
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.mount = MagicMock(return_value=(True, "Already mounted"))
        mgr.verify_mount_accessible = MagicMock(return_value=False)

        mgr.reconnect_saved()

        assert "NAS SIM" not in mgr._active_mounts


# ---------------------------------------------------------------------------
# sync_os_mounts — stale OS mount detection
# ---------------------------------------------------------------------------

class TestSyncOsMountsReachability:
    """sync_os_mounts() must not adopt stale OS mounts."""

    def test_inaccessible_os_mount_not_adopted(self):
        """OS mount present but inaccessible → not added to _active_mounts."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.is_mounted = MagicMock(return_value=True)
        mgr.verify_mount_accessible = MagicMock(return_value=False)

        mgr.sync_os_mounts()

        assert p.label not in mgr._active_mounts

    def test_accessible_os_mount_adopted(self):
        """OS mount present and accessible → added to _active_mounts."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.is_mounted = MagicMock(return_value=True)
        mgr.verify_mount_accessible = MagicMock(return_value=True)

        mgr.sync_os_mounts()

        assert p.label in mgr._active_mounts

    def test_not_os_mounted_not_checked(self):
        """Profile not in OS mount table → verify_mount_accessible not called."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.is_mounted = MagicMock(return_value=False)
        mgr.verify_mount_accessible = MagicMock()

        mgr.sync_os_mounts()

        mgr.verify_mount_accessible.assert_not_called()
        assert p.label not in mgr._active_mounts

    def test_already_tracked_not_rechecked(self):
        """Profile already in _active_mounts is not re-probed."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts["NAS SIM"] = p
        mgr.load_profiles = MagicMock(return_value=[p])
        mgr.is_mounted = MagicMock()
        mgr.verify_mount_accessible = MagicMock()

        mgr.sync_os_mounts()

        mgr.is_mounted.assert_not_called()
        mgr.verify_mount_accessible.assert_not_called()


# ---------------------------------------------------------------------------
# verify_mount_accessible — subprocess probe with bounded timeout
# ---------------------------------------------------------------------------

class TestVerifyMountAccessible:
    """verify_mount_accessible probes the mount via subprocess with timeout."""

    def test_accessible_mount_returns_true(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = mgr.verify_mount_accessible(p)
        assert result is True

    def test_inaccessible_mount_returns_false(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = mgr.verify_mount_accessible(p)
        assert result is False

    def test_timeout_returns_false(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("/bin/ls", 5)):
            result = mgr.verify_mount_accessible(p)
        assert result is False

    def test_exception_returns_false(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run",
                   side_effect=OSError("broken pipe")):
            result = mgr.verify_mount_accessible(p)
        assert result is False

    def test_uses_bounded_timeout(self):
        """subprocess.run must be called with an explicit timeout kwarg."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            mgr.verify_mount_accessible(p)
        _, kwargs = mock_run.call_args
        assert "timeout" in kwargs
        assert kwargs["timeout"] > 0

    def test_probes_mount_point_path(self):
        """subprocess.run target must include the profile's mount point."""
        mgr = NetworkStorageManager()
        p = _make_profile()
        with patch("managers.network_storage_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            mgr.verify_mount_accessible(p)
        args, _ = mock_run.call_args
        cmd = args[0]
        assert p.mount_point in cmd


# ---------------------------------------------------------------------------
# is_tracked_as_mounted — in-memory check, UI-thread safe
# ---------------------------------------------------------------------------

class TestIsTrackedAsMounted:
    """is_tracked_as_mounted must check _active_mounts only (no filesystem call)."""

    def test_not_tracked_returns_false(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        assert mgr.is_tracked_as_mounted(p) is False

    def test_tracked_returns_true(self):
        mgr = NetworkStorageManager()
        p = _make_profile()
        mgr._active_mounts["NAS SIM"] = p
        assert mgr.is_tracked_as_mounted(p) is True

    def test_different_label_returns_false(self):
        mgr = NetworkStorageManager()
        p1 = _make_profile(label="NAS A")
        p2 = _make_profile(label="NAS B")
        mgr._active_mounts["NAS A"] = p1
        assert mgr.is_tracked_as_mounted(p2) is False


# ---------------------------------------------------------------------------
# Dialog prefill — no blocking is_mounted() on UI thread
# ---------------------------------------------------------------------------

class TestDialogPrefillNoBlockingCall:
    """_prefill_from_saved must use is_tracked_as_mounted, not is_mounted."""

    @pytest.fixture(autouse=True)
    def _ensure_app(self):
        from PyQt6.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication(sys.argv)

    def _make_ns(self, profile, tracked=True):
        ns = MagicMock()
        ns.load_profiles.return_value = [profile]
        ns.is_tracked_as_mounted.return_value = tracked
        return ns

    def test_uses_is_tracked_not_is_mounted(self):
        """is_mounted must not be called when opening the dialog."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        p = _make_profile()
        ns = self._make_ns(p, tracked=True)

        NetworkStorageDialogQt(ns_manager=ns)

        ns.is_tracked_as_mounted.assert_called()
        ns.is_mounted.assert_not_called()

    def test_tracked_profile_prefills_fields(self):
        """When a tracked mount exists, its fields are shown in the form."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        p = _make_profile(server="nas.example.com", share="simdata")
        ns = self._make_ns(p, tracked=True)

        dlg = NetworkStorageDialogQt(ns_manager=ns)

        assert dlg.server_input.text() == "nas.example.com"
        assert dlg.share_input.text() == "simdata"

    def test_untracked_share_falls_back_to_last_used(self):
        """If no tracked mount, fall back to the last_used profile."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        p = _make_profile(server="fallback.host", last_used=True)
        ns = self._make_ns(p, tracked=False)

        dlg = NetworkStorageDialogQt(ns_manager=ns)

        assert dlg.server_input.text() == "fallback.host"
        ns.is_mounted.assert_not_called()

    def test_untracked_no_last_used_leaves_fields_empty(self):
        """No tracked mount, last_used=False → form fields empty."""
        from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt

        p = _make_profile(last_used=False)
        ns = self._make_ns(p, tracked=False)

        dlg = NetworkStorageDialogQt(ns_manager=ns)

        assert dlg.server_input.text() == ""
        ns.is_mounted.assert_not_called()


# ---------------------------------------------------------------------------
# BackgroundStartupWorker — error toast on reconnect failure
# ---------------------------------------------------------------------------

class _FakeNsManager:
    """Minimal ns_manager stub for BackgroundStartupWorker tests."""

    def __init__(self, reconnect_results):
        self._results = reconnect_results
        self._mounts = []

    def reconnect_saved(self):
        return self._results

    def sync_os_mounts(self):
        pass

    def get_active_mount_paths(self):
        return self._mounts


class _FakeIccidIndex:
    def scan_directory(self, path):
        r = MagicMock()
        r.total_cards = 0
        r.files_scanned = 0
        r.files_skipped = 0
        r.errors = []
        return r


class TestStartupWorkerReconnectToast:
    """BackgroundStartupWorker must surface reconnect failures via toast."""

    def _make_worker(self, reconnect_results):
        """Import and instantiate BackgroundStartupWorker with fakes."""
        import main as _main
        ns = _FakeNsManager(reconnect_results)
        idx = _FakeIccidIndex()
        worker = _main.BackgroundStartupWorker(ns, idx, standards_mgr=None)
        return worker

    def test_error_toast_emitted_on_reconnect_failure(self):
        """A failed reconnect must emit an error toast."""
        worker = self._make_worker([("NAS SIM", False, "Mount failed: File exists")])

        toasts = []
        worker.toast_requested.connect(lambda msg, typ, dur: toasts.append((msg, typ, dur)))
        worker.run()

        error_toasts = [(m, t, d) for m, t, d in toasts if t == "error"]
        assert error_toasts, "Expected an error toast but none was emitted"
        assert "NAS SIM" in error_toasts[0][0]

    def test_error_toast_not_emitted_when_all_succeed(self):
        """Successful reconnects must not trigger an error toast."""
        worker = self._make_worker([("NAS SIM", True, "Mounted")])

        toasts = []
        worker.toast_requested.connect(lambda msg, typ, dur: toasts.append((msg, typ, dur)))
        worker.run()

        error_toasts = [t for t in toasts if t[1] == "error"]
        assert error_toasts == []

    def test_success_toast_still_emitted_on_partial_success(self):
        """If some shares succeed and some fail, success toast still fires."""
        worker = self._make_worker([
            ("NAS SIM", True, "Mounted"),
            ("NAS BACKUP", False, "Mount failed: File exists"),
        ])

        toasts = []
        worker.toast_requested.connect(lambda msg, typ, dur: toasts.append((msg, typ, dur)))
        worker.run()

        success_toasts = [t for t in toasts if t[1] == "success"]
        error_toasts = [t for t in toasts if t[1] == "error"]
        assert success_toasts, "Expected success toast for 'NAS SIM'"
        assert error_toasts, "Expected error toast for 'NAS BACKUP'"

    def test_no_toast_when_no_reconnects_attempted(self):
        """Empty results (no last_used profile) → no toasts at all."""
        worker = self._make_worker([])

        toasts = []
        worker.toast_requested.connect(lambda msg, typ, dur: toasts.append((msg, typ, dur)))
        worker.run()

        assert toasts == []


# ---------------------------------------------------------------------------
# sync_os_mounts — Finder/OS mount adoption (macOS)
# ---------------------------------------------------------------------------

class TestSyncOsMountsFinderMount:
    """sync_os_mounts() must adopt verified Finder mounts at non-SimGUI paths."""

    def _make_ns(self, profile):
        ns = NetworkStorageManager()
        ns.load_profiles = MagicMock(return_value=[profile])
        return ns

    def _smb_profile(self):
        return _make_profile(label="NAS SIM", protocol="smb",
                             server="nas.local", share="SIM")

    def test_finder_mount_accessible_is_adopted(self, monkeypatch):
        """Finder mount at /Volumes/SIM (accessible) is adopted into active mounts."""
        p = self._smb_profile()
        ns = self._make_ns(p)
        # SimGUI's own path is not mounted
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        # But _macos_find_smb_mount finds /Volumes/SIM
        monkeypatch.setattr(ns, "_macos_find_smb_mount",
                            lambda prof: "/Volumes/SIM")
        monkeypatch.setattr(ns, "_check_path_accessible",
                            lambda path, timeout=5: True)
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)

        ns.sync_os_mounts()

        assert p.label in ns._active_mounts
        assert ns._actual_mount_paths[p.label] == "/Volumes/SIM"

    def test_finder_mount_inaccessible_is_not_adopted(self, monkeypatch):
        """Finder mount found but inaccessible → not adopted, not green."""
        p = self._smb_profile()
        ns = self._make_ns(p)
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        monkeypatch.setattr(ns, "_macos_find_smb_mount",
                            lambda prof: "/Volumes/SIM")
        monkeypatch.setattr(ns, "_check_path_accessible",
                            lambda path, timeout=5: False)
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)

        ns.sync_os_mounts()

        assert p.label not in ns._active_mounts
        assert p.label not in ns._actual_mount_paths

    def test_no_finder_mount_found_is_not_adopted(self, monkeypatch):
        """If _macos_find_smb_mount returns None, nothing is adopted."""
        p = self._smb_profile()
        ns = self._make_ns(p)
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        monkeypatch.setattr(ns, "_macos_find_smb_mount", lambda prof: None)
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)

        ns.sync_os_mounts()

        assert p.label not in ns._active_mounts

    def test_finder_mount_skipped_on_linux(self, monkeypatch):
        """_macos_find_smb_mount is not called on Linux."""
        p = self._smb_profile()
        ns = self._make_ns(p)
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        find_called = []
        monkeypatch.setattr(ns, "_macos_find_smb_mount",
                            lambda prof: find_called.append(1) or "/Volumes/SIM")
        monkeypatch.setattr("managers.network_storage_manager._MACOS", False)

        ns.sync_os_mounts()

        assert find_called == [], "Should not call _macos_find_smb_mount on Linux"
        assert p.label not in ns._active_mounts

    def test_already_tracked_not_rescanned(self, monkeypatch):
        """Profile already in _active_mounts is skipped entirely."""
        p = self._smb_profile()
        ns = self._make_ns(p)
        ns._active_mounts[p.label] = p  # already tracked
        find_called = []
        monkeypatch.setattr(ns, "_macos_find_smb_mount",
                            lambda prof: find_called.append(1) or "/Volumes/SIM")
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)

        ns.sync_os_mounts()

        assert find_called == []


class TestGetActiveMountPathsActual:
    """get_active_mount_paths() must return actual OS path, not always profile.mount_point."""

    def _smb_profile(self):
        return _make_profile(label="NAS SIM", protocol="smb",
                             server="nas.local", share="SIM")

    def test_returns_actual_path_when_set(self, monkeypatch):
        """/Volumes/SIM is returned instead of /tmp/simgui-mounts/NAS_SIM."""
        p = self._smb_profile()
        ns = NetworkStorageManager()
        ns._active_mounts[p.label] = p
        ns._actual_mount_paths[p.label] = "/Volumes/SIM"
        monkeypatch.setattr(os.path, "ismount",
                            lambda path: path == "/Volumes/SIM")

        paths = ns.get_active_mount_paths()

        assert paths == [("NAS SIM", "/Volumes/SIM")]

    def test_falls_back_to_profile_mount_point_when_no_actual(self, monkeypatch):
        """No _actual_mount_paths entry → profile.mount_point is used."""
        p = self._smb_profile()
        ns = NetworkStorageManager()
        ns._active_mounts[p.label] = p
        expected_mp = p.mount_point
        monkeypatch.setattr(os.path, "ismount",
                            lambda path: path == expected_mp)

        paths = ns.get_active_mount_paths()

        assert paths == [("NAS SIM", expected_mp)]

    def test_inaccessible_actual_path_excluded(self, monkeypatch):
        """/Volumes/SIM unmounted since adoption → not returned."""
        p = self._smb_profile()
        ns = NetworkStorageManager()
        ns._active_mounts[p.label] = p
        ns._actual_mount_paths[p.label] = "/Volumes/SIM"
        monkeypatch.setattr(os.path, "ismount", lambda path: False)

        paths = ns.get_active_mount_paths()

        assert paths == []


class TestMountFileExistsActualPath:
    """mount() 'File exists' must resolve and verify the actual OS mount path."""

    def _profile(self):
        return _make_profile(label="NAS SIM", protocol="smb",
                             server="nas.local", share="SIM")

    def _fail_run(self, stderr="mount_smbfs: mount error: //nas.local/SIM: File exists"):
        import subprocess

        class _R:
            returncode = 1
            stdout = ""

        r = _R()
        r.stderr = stderr

        return lambda *a, **kw: r

    def test_file_exists_uses_finder_path_when_accessible(self, monkeypatch):
        """'File exists' + Finder mount at /Volumes/SIM accessible → True, records actual path."""
        import subprocess

        p = self._profile()
        ns = NetworkStorageManager()
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        monkeypatch.setattr(subprocess, "run", self._fail_run())
        monkeypatch.setattr(ns, "_macos_find_smb_mount",
                            lambda prof: "/Volumes/SIM")
        monkeypatch.setattr(ns, "_check_path_accessible",
                            lambda path, timeout=5: True)
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)

        ok, msg = ns.mount(p)

        assert ok
        assert p.label in ns._active_mounts
        assert ns._actual_mount_paths.get(p.label) == "/Volumes/SIM"
        assert "/Volumes/SIM" in msg

    def test_file_exists_finder_path_inaccessible_returns_failure(self, monkeypatch):
        """'File exists' + /Volumes/SIM found but inaccessible → False, not tracked."""
        import subprocess

        p = self._profile()
        ns = NetworkStorageManager()
        monkeypatch.setattr(os.path, "ismount", lambda mp: False)
        monkeypatch.setattr(subprocess, "run", self._fail_run())
        monkeypatch.setattr(ns, "_macos_find_smb_mount",
                            lambda prof: "/Volumes/SIM")
        monkeypatch.setattr(ns, "_check_path_accessible",
                            lambda path, timeout=5: False)
        monkeypatch.setattr("managers.network_storage_manager._MACOS", True)

        ok, msg = ns.mount(p)

        assert not ok
        assert p.label not in ns._active_mounts
        assert p.label not in ns._actual_mount_paths
