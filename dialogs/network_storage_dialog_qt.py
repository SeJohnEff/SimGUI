#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Network Storage Dialog (PyQt6) — Configure SMB/NFS shares.

Simple dialog for configuring and mounting network storage shares.
"""

import logging

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from managers.network_storage_manager import StorageProfile, NetworkStorageManager

logger = logging.getLogger(__name__)


class _MountWorker(QThread):
    """Run mount in a background thread so the UI stays responsive."""

    result_ready = pyqtSignal(bool, str)

    def __init__(self, ns_manager, profile):
        super().__init__()
        self._ns_manager = ns_manager
        self._profile = profile

    def run(self):
        ok, msg = self._ns_manager.mount(self._profile)
        print(f"[MOUNT-WORKER] ok={ok} msg={msg!r}")
        self.result_ready.emit(ok, msg)


class _TestConnectionWorker(QThread):
    """Run test_connection in a background thread so the UI stays responsive."""

    result_ready = pyqtSignal(bool, str)

    def __init__(self, ns_manager, profile):
        super().__init__()
        self._ns_manager = ns_manager
        self._profile = profile

    def run(self):
        ok, msg = self._ns_manager.test_connection(self._profile)
        self.result_ready.emit(ok, msg)


class NetworkStorageDialogQt(QDialog):
    """PyQt6 dialog for configuring network storage."""

    def __init__(self, parent=None, ns_manager: NetworkStorageManager = None):
        super().__init__(parent)
        self.setWindowTitle("Network Storage")
        self.resize(500, 350)
        # WindowModal prevents macOS from moving the dialog to a secondary
        # monitor when the user switches away and back to SimGUI.
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.ns_manager = ns_manager
        # Label of the profile currently loaded from the combo; used as
        # exclude_label for uniqueness validation so re-saving the same
        # profile under the same label is allowed.
        self._editing_label: str = None
        # Guard: True while _populate() is filling form fields programmatically.
        # _on_form_edited() ignores changes made during prefill so it does not
        # incorrectly clear the Saved selection the moment it is applied.
        self._prefilling_profile: bool = False
        self._mount_worker: _MountWorker = None
        self._mount_profile: StorageProfile = None
        self._build_ui()
        self._prefill_from_saved()
        # Connect form-edit detection AFTER prefill so the initial programmatic
        # field population does not trigger the clearing logic.
        self._connect_form_edit_signals()

    def showEvent(self, event):
        super().showEvent(event)
        # Center over parent window so the dialog always appears on the same
        # screen as SimGUI, regardless of which monitor the app is on.
        if self.parent():
            pg = self.parent().frameGeometry()
            self.move(
                pg.center().x() - self.width() // 2,
                pg.center().y() - self.height() // 2,
            )

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Form grid
        form = QGridLayout()
        form.setSpacing(8)

        # Saved-profile selector (row 0) — UI-only field population, no network ops
        form.addWidget(QLabel("Saved:"), 0, 0)
        self.profiles_combo = QComboBox()
        self._saved_profiles: list = []
        self._load_saved_profiles_combo()
        self.profiles_combo.currentIndexChanged.connect(self._on_profile_selected)
        form.addWidget(self.profiles_combo, 0, 1)

        # Protocol
        form.addWidget(QLabel("Protocol:"), 1, 0)
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["SMB", "NFS"])
        form.addWidget(self.protocol_combo, 1, 1)

        # Server / Host
        form.addWidget(QLabel("Server / Host:"), 2, 0)
        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("nas.local or 192.168.1.10")
        form.addWidget(self.server_input, 2, 1)

        # Share / Export
        form.addWidget(QLabel("Share / Export:"), 3, 0)
        self.share_input = QLineEdit()
        self.share_input.setPlaceholderText("share_name or /export/path")
        form.addWidget(self.share_input, 3, 1)

        # Username (SMB only)
        form.addWidget(QLabel("Username:"), 4, 0)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Optional")
        form.addWidget(self.username_input, 4, 1)

        # Password (SMB only)
        form.addWidget(QLabel("Password:"), 5, 0)
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Optional")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addWidget(self.password_input, 5, 1)

        # Label / Name
        form.addWidget(QLabel("Label:"), 6, 0)
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("e.g., SIM Data NAS")
        form.addWidget(self.label_input, 6, 1)

        layout.addLayout(form)

        # Buttons
        button_layout = QHBoxLayout()

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.clicked.connect(self._on_disconnect)
        button_layout.addWidget(self.disconnect_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._on_delete)
        button_layout.addWidget(self.delete_btn)

        button_layout.addStretch()

        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._on_test)
        button_layout.addWidget(self.test_btn)

        self.connect_btn = QPushButton("Save & Connect")
        self.connect_btn.clicked.connect(self._on_connect)
        button_layout.addWidget(self.connect_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

    def _load_saved_profiles_combo(self) -> None:
        """Populate the saved-profiles dropdown from the manager (UI-only, no I/O)."""
        self.profiles_combo.blockSignals(True)
        self.profiles_combo.clear()
        self.profiles_combo.addItem("— Select saved profile —")
        self._saved_profiles = []
        if self.ns_manager:
            for p in self.ns_manager.load_profiles()[:5]:
                self._saved_profiles.append(p)
                entry = p.label or f"{p.server}/{p.share}"
                self.profiles_combo.addItem(entry)
        self.profiles_combo.blockSignals(False)

    def _on_profile_selected(self, idx: int) -> None:
        """Populate form fields from the chosen saved profile (UI-only, no network ops)."""
        if idx <= 0 or idx > len(self._saved_profiles):
            self._editing_label = None
            self.delete_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(False)
            return
        profile = self._saved_profiles[idx - 1]
        self._editing_label = profile.label
        self.delete_btn.setEnabled(True)
        active = bool(self.ns_manager and self.ns_manager.is_tracked_as_mounted(profile))
        self.disconnect_btn.setEnabled(active)
        self._populate(profile)

    def _prefill_from_saved(self):
        """Populate form fields from the mounted or last-used profile."""
        if not self.ns_manager:
            return
        profiles = self.ns_manager.load_profiles()
        # Prefer a profile that is verified mounted (in-memory check only —
        # avoids blocking stat() on stale mounts on the UI thread).
        for p in profiles:
            if self.ns_manager.is_tracked_as_mounted(p):
                self._editing_label = p.label
                self.delete_btn.setEnabled(True)
                self.disconnect_btn.setEnabled(True)
                self._populate(p)
                self._select_profile_in_combo(p)
                return
        # Fall back to the last-used profile
        for p in profiles:
            if p.last_used:
                self._editing_label = p.label
                self.delete_btn.setEnabled(True)
                self.disconnect_btn.setEnabled(False)
                self._populate(p)
                self._select_profile_in_combo(p)
                return

    def _select_profile_in_combo(self, profile: "StorageProfile") -> None:
        """Sync the saved-profiles combo to show *profile* as selected."""
        for i, p in enumerate(self._saved_profiles):
            if p.label == profile.label:
                self.profiles_combo.blockSignals(True)
                self.profiles_combo.setCurrentIndex(i + 1)
                self.profiles_combo.blockSignals(False)
                break

    def _populate(self, profile: "StorageProfile") -> None:
        """Fill all form fields from *profile*.

        Sets _prefilling_profile so that _on_form_edited() ignores the
        textChanged / currentIndexChanged signals emitted during fill.
        """
        self._prefilling_profile = True
        try:
            idx = self.protocol_combo.findText(profile.protocol.upper())
            if idx >= 0:
                self.protocol_combo.setCurrentIndex(idx)
            self.server_input.setText(profile.server)
            self.share_input.setText(profile.share)
            self.username_input.setText(profile.username)
            if profile.password:
                self.password_input.setText(profile.password)
            self.label_input.setText(profile.label)
        finally:
            self._prefilling_profile = False

    def _connect_form_edit_signals(self) -> None:
        """Wire every profile-defining field to _on_form_edited().

        Must be called AFTER _prefill_from_saved() so the initial programmatic
        fill does not trigger the clearing logic.
        """
        for widget in (
            self.server_input,
            self.share_input,
            self.username_input,
            self.password_input,
            self.label_input,
        ):
            widget.textChanged.connect(self._on_form_edited)
        self.protocol_combo.currentIndexChanged.connect(self._on_form_edited)

    def _on_form_edited(self, *_args) -> None:
        """Called when the user edits any profile-defining field.

        The visible form is the source of truth for Test/Save operations.
        Once the user changes a field, the Saved dropdown no longer describes
        the form content, so the selection is cleared and _editing_label is
        reset.  Delete and Disconnect are disabled because they would otherwise
        silently operate on the previously-selected saved profile, which may
        differ from what the form now shows.

        Ignored during programmatic prefill (_prefilling_profile=True).
        """
        if self._prefilling_profile:
            return
        # Return the Saved combo to the "no selection" placeholder.
        self.profiles_combo.blockSignals(True)
        self.profiles_combo.setCurrentIndex(0)
        self.profiles_combo.blockSignals(False)
        # Discard stale saved-profile identity.
        self._editing_label = None
        # Profile-bound actions no longer have a target.
        self.delete_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)

    def _on_test(self):
        """Validate fields then start a background connectivity test."""
        if not self.ns_manager:
            QMessageBox.warning(self, "Error", "Network Storage Manager not available")
            return

        profile = self._build_profile()
        if not profile:
            return

        logger.info(
            "Test Connection: label=%r server=%r share=%r username=%r protocol=%r",
            profile.label, profile.server, profile.share,
            profile.username, profile.protocol,
        )

        valid, err = self.ns_manager.validate_label_unique(
            profile.label, exclude_label=self._editing_label)
        if not valid:
            QMessageBox.warning(self, "Label Error", err)
            return

        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testing…")
        self.connect_btn.setEnabled(False)

        self._test_worker = _TestConnectionWorker(self.ns_manager, profile)
        self._test_worker.result_ready.connect(self._on_test_result)
        self._test_worker.finished.connect(self._on_test_worker_done)
        self._test_worker.start()

    def _on_test_worker_done(self) -> None:
        """Release the worker reference once the thread has exited."""
        self._test_worker = None

    def _on_test_result(self, ok: bool, msg: str) -> None:
        """Slot: called by worker when test_connection completes."""
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test Connection")
        self.connect_btn.setEnabled(True)
        if ok:
            QMessageBox.information(self, "Success", f"Connection successful:\n{msg}")
        else:
            QMessageBox.warning(self, "Connection Failed", msg)

    def _on_connect(self):
        """Validate then mount the share in a background thread."""
        if not self.ns_manager:
            QMessageBox.warning(self, "Error", "Network Storage Manager not available")
            return

        profile = self._build_profile()
        if not profile:
            return

        valid, err = self.ns_manager.validate_label_unique(
            profile.label, exclude_label=self._editing_label)
        if not valid:
            QMessageBox.warning(self, "Label Error", err)
            return

        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Connecting…")
        self.test_btn.setEnabled(False)

        self._mount_profile = profile
        self._mount_worker = _MountWorker(self.ns_manager, profile)
        self._mount_worker.result_ready.connect(self._on_mount_result)
        self._mount_worker.finished.connect(self._on_mount_worker_done)
        self._mount_worker.start()
        print("[MOUNT] background mount started")

    def _on_mount_worker_done(self) -> None:
        """Release the worker reference once the thread has exited."""
        self._mount_worker = None

    def _on_mount_result(self, ok: bool, msg: str) -> None:
        """Slot: called by _MountWorker when mount completes."""
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Save & Connect")
        self.test_btn.setEnabled(True)
        if ok:
            # Save the profile — update in-place if label exists, else append
            profiles = self.ns_manager.load_profiles()
            idx = next((i for i, p in enumerate(profiles)
                        if p.label == self._mount_profile.label), -1)
            if idx >= 0:
                profiles[idx] = self._mount_profile
            else:
                profiles.append(self._mount_profile)
            self.ns_manager.save_profiles(profiles)
            self.ns_manager.mark_last_used(self._mount_profile.label)
            QMessageBox.information(self, "Success", f"Share mounted and saved:\n{msg}")
            self.accept()
        else:
            QMessageBox.warning(self, "Mount Failed", msg)

    def _on_disconnect(self):
        """Disconnect the currently selected profile.

        Looks the profile up from the saved list (not the form) so that
        unsaved form edits do not affect which share gets unmounted.
        On success — including the stale-tracking case where the OS mount
        is already gone — the disconnect button is disabled.  The dialog
        stays open so the user can reconnect, reconfigure, or delete.
        """
        if not self.ns_manager or not self._editing_label:
            return
        profile = next(
            (p for p in self._saved_profiles if p.label == self._editing_label),
            None,
        )
        if profile is None:
            QMessageBox.warning(self, "Disconnect", "No saved profile selected.")
            return
        ok, msg = self.ns_manager.unmount(profile)
        if ok:
            self.disconnect_btn.setEnabled(False)
            QMessageBox.information(self, "Disconnected", msg)
        else:
            QMessageBox.warning(self, "Disconnect Failed", msg)

    def _on_delete(self):
        """Delete the currently selected saved profile."""
        if not self.ns_manager or not self._editing_label:
            return
        ok, msg = self.ns_manager.delete_profile(self._editing_label)
        if ok:
            self._editing_label = None
            self.delete_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(False)
            self._load_saved_profiles_combo()
            QMessageBox.information(self, "Deleted", msg)
        else:
            QMessageBox.warning(self, "Cannot Delete", msg)

    def _build_profile(self) -> StorageProfile:
        """Build a StorageProfile from form inputs."""
        server = self.server_input.text().strip()
        share = self.share_input.text().strip()
        label = self.label_input.text().strip()

        if not server or not share:
            QMessageBox.warning(self, "Missing Fields", "Server and Share are required")
            return None

        if not label:
            label = f"{share} on {server}"

        protocol = self.protocol_combo.currentText().lower()

        profile = StorageProfile(
            label=label,
            protocol=protocol,
            server=server,
            share=share,
            username=self.username_input.text().strip(),
            password=self.password_input.text() if protocol == "smb" else "",
        )
        return profile
