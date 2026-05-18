#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Network Storage Dialog (PyQt6) — Configure SMB/NFS shares.

Simple dialog for configuring and mounting network storage shares.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QComboBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt

from managers.network_storage_manager import StorageProfile, NetworkStorageManager


class NetworkStorageDialogQt(QDialog):
    """PyQt6 dialog for configuring network storage."""

    def __init__(self, parent=None, ns_manager: NetworkStorageManager = None):
        super().__init__(parent)
        self.setWindowTitle("Network Storage")
        self.resize(500, 500)
        self.ns_manager = ns_manager
        self._profiles = ns_manager.load_profiles() if ns_manager else []
        self._current_profile = None
        self._build_ui()
        self._refresh_saved_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Saved servers section
        saved_label = QLabel("Saved Servers:")
        layout.addWidget(saved_label)

        saved_layout = QHBoxLayout()
        self.saved_combo = QComboBox()
        self.saved_combo.currentIndexChanged.connect(self._on_saved_select)
        saved_layout.addWidget(self.saved_combo)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._on_remove_server)
        saved_layout.addWidget(self.remove_btn)

        layout.addLayout(saved_layout)

        # Form grid
        form = QGridLayout()
        form.setSpacing(8)

        # Protocol
        form.addWidget(QLabel("Protocol:"), 0, 0)
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["SMB", "NFS"])
        form.addWidget(self.protocol_combo, 0, 1)

        # Server / Host
        form.addWidget(QLabel("Server / Host:"), 1, 0)
        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("nas.local or 192.168.1.10")
        form.addWidget(self.server_input, 1, 1)

        # Share / Export
        form.addWidget(QLabel("Share / Export:"), 2, 0)
        self.share_input = QLineEdit()
        self.share_input.setPlaceholderText("share_name or /export/path")
        form.addWidget(self.share_input, 2, 1)

        # Username (SMB only)
        form.addWidget(QLabel("Username:"), 3, 0)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Optional")
        form.addWidget(self.username_input, 3, 1)

        # Password (SMB only)
        form.addWidget(QLabel("Password:"), 4, 0)
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Optional")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addWidget(self.password_input, 4, 1)

        # Label / Name
        form.addWidget(QLabel("Label:"), 5, 0)
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("e.g., SIM Data NAS")
        form.addWidget(self.label_input, 5, 1)

        layout.addLayout(form)

        # Auto-connect checkbox
        self.auto_connect = QCheckBox("Auto-connect on startup")
        layout.addWidget(self.auto_connect)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._on_test)
        button_layout.addWidget(self.test_btn)

        self.connect_btn = QPushButton("Connect & Save")
        self.connect_btn.clicked.connect(self._on_connect)
        button_layout.addWidget(self.connect_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

    def _on_test(self):
        """Test the connection without saving."""
        if not self.ns_manager:
            QMessageBox.warning(self, "Error", "Network Storage Manager not available")
            return

        profile = self._build_profile()
        if not profile:
            return

        ok, msg = self.ns_manager.test_connection(profile)
        if ok:
            QMessageBox.information(self, "Success", f"Connection successful:\n{msg}")
        else:
            QMessageBox.warning(self, "Connection Failed", msg)

    def _on_connect(self):
        """Save and mount the share."""
        if not self.ns_manager:
            QMessageBox.warning(self, "Error", "Network Storage Manager not available")
            return

        profile = self._build_profile()
        if not profile:
            return

        # Mount the profile
        ok, msg = self.ns_manager.mount(profile)
        if ok:
            # Save the profile
            profiles = self.ns_manager.load_profiles()
            # Check if label already exists and update or append
            idx = next((i for i, p in enumerate(profiles) if p.label == profile.label), -1)
            if idx >= 0:
                profiles[idx] = profile
            else:
                profiles.append(profile)
            self.ns_manager.save_profiles(profiles)
            self._profiles = profiles
            self._refresh_saved_list()
            QMessageBox.information(self, "Success", f"Share mounted and saved:\n{msg}")
            self.accept()
        else:
            QMessageBox.warning(self, "Mount Failed", msg)

    def _refresh_saved_list(self):
        """Reload saved servers list in the combobox."""
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem("— New Connection —", None)
        for p in self._profiles:
            self.saved_combo.addItem(p.label, p)
        self.saved_combo.blockSignals(False)
        if not self._profiles:
            self.remove_btn.setEnabled(False)

    def _on_saved_select(self, index: int):
        """Load the selected saved server into the form."""
        profile = self.saved_combo.currentData()
        if profile is None:
            self._clear_form()
            self._current_profile = None
            self.remove_btn.setEnabled(False)
        else:
            self._load_profile(profile)
            self._current_profile = profile
            self.remove_btn.setEnabled(True)

    def _load_profile(self, profile: StorageProfile):
        """Populate form fields from a saved profile."""
        self.protocol_combo.setCurrentText(profile.protocol.upper())
        self.server_input.setText(profile.server)
        self.share_input.setText(profile.share)
        self.username_input.setText(profile.username)
        self.password_input.setText(profile.password or "")
        self.label_input.setText(profile.label)
        self.auto_connect.setChecked(profile.auto_connect)

    def _clear_form(self):
        """Clear all form fields."""
        self.protocol_combo.setCurrentIndex(0)
        self.server_input.clear()
        self.share_input.clear()
        self.username_input.clear()
        self.password_input.clear()
        self.label_input.clear()
        self.auto_connect.setChecked(False)

    def _on_remove_server(self):
        """Remove the selected saved server."""
        if self._current_profile is None:
            QMessageBox.warning(self, "Error", "No server selected")
            return

        reply = QMessageBox.question(
            self, "Remove Server",
            f"Remove '{self._current_profile.label}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self._profiles = [p for p in self._profiles if p.label != self._current_profile.label]
            if self.ns_manager:
                self.ns_manager.save_profiles(self._profiles)
            self._refresh_saved_list()
            self._clear_form()
            self._current_profile = None

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
            auto_connect=self.auto_connect.isChecked(),
        )
        return profile
