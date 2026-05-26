"""Tests for NetworkStorageDialogQt prefill behaviour.

Verifies that the dialog self-populates from the first mounted (or
auto-connect) profile when ns_manager is supplied.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

from dialogs.network_storage_dialog_qt import NetworkStorageDialogQt
from managers.network_storage_manager import StorageProfile

# Ensure a QApplication exists for widget construction
_app = QApplication.instance() or QApplication(sys.argv)


def _make_profile(**kwargs):
    defaults = dict(
        label="NAS SIM",
        protocol="smb",
        server="192.168.131.188",
        share="SIM",
        username="simgui",
        password="s3cr3t",
    )
    defaults.update(kwargs)
    return StorageProfile(**defaults)


def _make_ns_manager(profile, mounted=True):
    """Return a minimal ns_manager mock for the given profile."""
    ns = MagicMock()
    ns.load_profiles.return_value = [profile]
    # Dialog uses is_tracked_as_mounted (non-blocking, UI-thread safe).
    ns.is_tracked_as_mounted.return_value = mounted
    return ns


class TestPrefillFromConnectedProfile:
    """Dialog must show saved config when a connected profile exists."""

    def test_server_prefilled(self):
        p = _make_profile()
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns_manager(p))
        assert dlg.server_input.text() == "192.168.131.188"

    def test_share_prefilled(self):
        p = _make_profile()
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns_manager(p))
        assert dlg.share_input.text() == "SIM"

    def test_username_prefilled(self):
        p = _make_profile()
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns_manager(p))
        assert dlg.username_input.text() == "simgui"

    def test_label_prefilled(self):
        p = _make_profile()
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns_manager(p))
        assert dlg.label_input.text() == "NAS SIM"

    def test_protocol_prefilled(self):
        p = _make_profile(protocol="smb")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns_manager(p))
        assert dlg.protocol_combo.currentText().lower() == "smb"


class TestPasswordFieldIndicatesSavedPassword:
    """Password field must not be blank when a saved password exists."""

    def test_password_field_not_blank(self):
        p = _make_profile(password="s3cr3t")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns_manager(p))
        assert dlg.password_input.text() != ""

    def test_password_field_blank_when_no_password(self):
        p = _make_profile(password="")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns_manager(p))
        assert dlg.password_input.text() == ""

    def test_password_field_is_masked(self):
        from PyQt6.QtWidgets import QLineEdit
        p = _make_profile(password="s3cr3t")
        dlg = NetworkStorageDialogQt(ns_manager=_make_ns_manager(p))
        assert dlg.password_input.echoMode() == QLineEdit.EchoMode.Password


class TestPrefillFallbackToLastUsed:
    """If no profile is mounted, fall back to the last_used profile."""

    def test_falls_back_when_not_mounted(self):
        p = _make_profile(last_used=True)
        ns = _make_ns_manager(p, mounted=False)
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        assert dlg.server_input.text() == "192.168.131.188"

    def test_empty_when_no_last_used_and_not_mounted(self):
        p = _make_profile(last_used=False)
        ns = _make_ns_manager(p, mounted=False)
        dlg = NetworkStorageDialogQt(ns_manager=ns)
        assert dlg.server_input.text() == ""

    def test_empty_when_no_ns_manager(self):
        dlg = NetworkStorageDialogQt(ns_manager=None)
        assert dlg.server_input.text() == ""
