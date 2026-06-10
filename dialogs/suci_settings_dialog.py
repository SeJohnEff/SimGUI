#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUCI configuration settings dialog."""

import logging
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QPushButton
)

logger = logging.getLogger(__name__)


class SUCISettingsDialog(QDialog):
    """Modal dialog for SUCI configuration (hnet_pubkey and related settings)."""

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.setWindowTitle("SUCI Configuration")
        self.setModal(True)
        self.setMinimumWidth(500)

        layout = QVBoxLayout()

        # HNET_PUBKEY
        hnet_label = QLabel("Home Network Public Key (hex):")
        self.hnet_input = QLineEdit()
        self.hnet_input.setPlaceholderText("64 hex characters (e.g., 0e6e6e15...)")
        layout.addWidget(hnet_label)
        layout.addWidget(self.hnet_input)

        # Protection scheme
        scheme_label = QLabel("Protection Scheme ID:")
        self.scheme_spin = QSpinBox()
        self.scheme_spin.setMinimum(0)
        self.scheme_spin.setMaximum(255)
        self.scheme_spin.setValue(1)
        layout.addWidget(scheme_label)
        layout.addWidget(self.scheme_spin)

        # Routing indicator
        routing_label = QLabel("Routing Indicator:")
        self.routing_input = QLineEdit()
        self.routing_input.setPlaceholderText("2 hex digits (e.g., 00)")
        self.routing_input.setMaxLength(2)
        layout.addWidget(routing_label)
        layout.addWidget(self.routing_input)

        # Pubkey ID
        pubkey_id_label = QLabel("Public Key Identifier:")
        self.pubkey_id_spin = QSpinBox()
        self.pubkey_id_spin.setMinimum(0)
        self.pubkey_id_spin.setMaximum(255)
        self.pubkey_id_spin.setValue(1)
        layout.addWidget(pubkey_id_label)
        layout.addWidget(self.pubkey_id_spin)

        # Buttons
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Connect signals
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def load_settings(self) -> None:
        """Load current settings from SettingsManager into dialog fields."""
        hnet_pubkey = self.settings_manager.get("suci_hnet_pubkey", "")
        prot_scheme = self.settings_manager.get("suci_prot_scheme", 1)
        routing_ind = self.settings_manager.get("suci_routing_ind", "00")
        pubkey_id = self.settings_manager.get("suci_pubkey_id", 1)

        self.hnet_input.setText(hnet_pubkey)
        self.scheme_spin.setValue(int(prot_scheme) if isinstance(prot_scheme, int) else 1)
        self.routing_input.setText(str(routing_ind))
        self.pubkey_id_spin.setValue(int(pubkey_id) if isinstance(pubkey_id, int) else 1)

    def save_settings(self) -> bool:
        """Save settings from dialog fields to SettingsManager. Returns True if valid."""
        hnet_pubkey = self.hnet_input.text().strip()

        # Validate hex format if provided
        if hnet_pubkey:
            if not all(c in '0123456789abcdefABCDEF' for c in hnet_pubkey):
                logger.error("Invalid hex format in HNET_PUBKEY")
                return False
            if len(hnet_pubkey) != 64:
                logger.warning("HNET_PUBKEY should be 64 hex chars, got %d", len(hnet_pubkey))

        routing_ind = self.routing_input.text().strip().upper()
        if routing_ind:
            if not all(c in '0123456789ABCDEF' for c in routing_ind):
                logger.error("Invalid hex format in routing indicator")
                return False
            if len(routing_ind) != 2:
                logger.warning("Routing indicator should be 2 hex chars, got %d", len(routing_ind))

        # Save to settings
        self.settings_manager.set("suci_hnet_pubkey", hnet_pubkey)
        self.settings_manager.set("suci_prot_scheme", self.scheme_spin.value())
        self.settings_manager.set("suci_routing_ind", routing_ind)
        self.settings_manager.set("suci_pubkey_id", self.pubkey_id_spin.value())
        self.settings_manager.save()

        return True

    def exec(self) -> int:
        """Override exec to load settings before showing dialog."""
        self.load_settings()
        return super().exec()
