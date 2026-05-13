#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Card Status Panel Widget

Shows the current card state.  Card detection is handled automatically
by :class:`CardWatcher` — there is no manual "Detect Card" button.
"""

import os
from typing import Optional

from PyQt6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from state_manager import StateManager, CardInfo


class CardStatusPanel(QGroupBox):
    """Panel showing card detection and status"""

    def __init__(self, parent=None, state_manager: Optional[StateManager] = None, **kwargs):
        super().__init__("Card Status", parent)
        self.state_manager = state_manager
        self.on_detect_callback = None
        self.on_authenticate_callback = None
        self._info_vars = {}
        self._create_widgets()
        self.set_status("waiting", "Insert a SIM card...")

        if self.state_manager:
            self.state_manager.card_info_changed.connect(self._on_card_info_changed)

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Status row
        status_layout = QHBoxLayout()
        status_label = QLabel("Status:")
        status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(status_label)

        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(12, 12)
        status_layout.addWidget(self.status_indicator)

        self.status_label = QLineEdit()
        self.status_label.setReadOnly(True)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()

        main_layout.addLayout(status_layout)

        # Card info grid
        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setColumnStretch(1, 1)

        info_labels = [
            ('Card Type:', 'card_type'),
            ('IMSI:', 'imsi'),
            ('ICCID:', 'iccid'),
            ('ACC:', 'acc'),
            ('SPN:', 'spn'),
            ('FPLMN:', 'fplmn'),
            ('Auth:', 'auth'),
            ('ADM1 Left:', 'adm1_attempts'),
            ('Source:', 'source_file'),
        ]

        for i, (label_text, key) in enumerate(info_labels):
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold;")
            grid.addWidget(label, i, 0)

            entry = QLineEdit()
            entry.setReadOnly(True)
            entry.setText('-')
            grid.addWidget(entry, i, 1)
            self._info_vars[key] = entry

        self._num_info_rows = len(info_labels)
        main_layout.addLayout(grid)

        # Already-programmed indicator
        self._programmed_label = QLabel()
        self._programmed_label.setStyleSheet("color: orange; font-weight: bold;")
        self._programmed_label.setText("⚠ Already programmed (artifact exists)")
        self._programmed_label.hide()
        main_layout.addWidget(self._programmed_label)

        # Authenticate button
        self._auth_btn = QPushButton("Authenticate")
        self._auth_btn.clicked.connect(self._on_authenticate_clicked)
        main_layout.addWidget(self._auth_btn)

        # Blocked indicator
        self._blocked_label = QLabel("⛔ CARD BLOCKED — Cannot be programmed")
        self._blocked_label.setStyleSheet("background-color: #CC0000; color: white; font-weight: bold; padding: 8px;")
        self._blocked_label.hide()
        main_layout.addWidget(self._blocked_label)

        # Simulator info
        self._sim_label = QLabel()
        self._sim_label.setStyleSheet("font-size: 9pt;")
        self._sim_label.hide()
        main_layout.addWidget(self._sim_label)

        main_layout.addStretch()

    def _on_authenticate_clicked(self):
        if self.on_authenticate_callback:
            self.on_authenticate_callback()

    def _on_card_info_changed(self, card_info: CardInfo):
        """Update all labels when CardInfo changes."""
        self.set_card_info(
            card_type=card_info.card_type if card_info.card_type else None,
            imsi=card_info.imsi if card_info.imsi else None,
            iccid=card_info.iccid if card_info.iccid else None,
            acc=card_info.acc if card_info.acc else None,
            spn=card_info.spn if card_info.spn else None,
            fplmn=card_info.fplmn if card_info.fplmn else None,
            source_file=card_info.source_file if card_info.source_file else None,
        )
        self.set_auth_status(card_info.auth_status)
        self.set_programmed_indicator(card_info.already_programmed)

    def set_status(self, state, message=""):
        colors = {
            'waiting': QColor('#FFA500'),
            'detected': QColor('#0078D4'),
            'authenticated': QColor('#107C10'),
            'error': QColor('#E81123'),
            'blocked': QColor('#CC0000'),
        }
        color = colors.get(state, QColor('#CCCCCC'))
        pixmap = self.status_indicator.pixmap()
        if pixmap is None or pixmap.isNull():
            from PyQt6.QtGui import QPixmap
            pixmap = QPixmap(12, 12)
        pixmap.fill(color)
        self.status_indicator.setPixmap(pixmap)
        self.status_label.setText(message)

    def set_card_info(self, card_type=None, imsi=None, iccid=None,
                       acc=None, spn=None, fplmn=None,
                       source_file=None):
        if card_type is not None:
            self._info_vars['card_type'].setText(card_type)
        if imsi is not None:
            self._info_vars['imsi'].setText(imsi)
        if iccid is not None:
            self._info_vars['iccid'].setText(iccid)
        if acc is not None:
            self._info_vars['acc'].setText(acc)
        if spn is not None:
            self._info_vars['spn'].setText(spn)
        if fplmn is not None:
            self._info_vars['fplmn'].setText(fplmn)
        if source_file is not None:
            self._info_vars['source_file'].setText(
                os.path.basename(source_file) if source_file else '-')

    def set_auth_status(self, authenticated):
        self._info_vars['auth'].setText('Yes' if authenticated else 'No')

    def set_adm1_attempts(self, remaining):
        """Update the ADM1 remaining attempts display."""
        if remaining is None:
            self._info_vars['adm1_attempts'].setText('-')
        elif remaining == 0:
            self._info_vars['adm1_attempts'].setText('BLOCKED (0)')
        elif remaining <= 1:
            self._info_vars['adm1_attempts'].setText(f'{remaining} (DANGER!)')
        else:
            self._info_vars['adm1_attempts'].setText(str(remaining))

    def set_blocked_indicator(self, is_blocked):
        """Show or hide the 'CARD BLOCKED' banner."""
        if is_blocked:
            self._blocked_label.show()
        else:
            self._blocked_label.hide()

    def set_programmed_indicator(self, already_programmed):
        """Show or hide the 'already programmed' warning."""
        if already_programmed:
            self._programmed_label.show()
        else:
            self._programmed_label.hide()

    def clear_card_info(self):
        """Reset all info fields to defaults (card removed)."""
        for var in self._info_vars.values():
            var.setText('-')
        self._programmed_label.hide()
        self._blocked_label.hide()

    def set_simulator_info(self, card_index, total_cards):
        """Show or hide the virtual card indicator below the buttons."""
        if card_index is not None and total_cards is not None:
            self._sim_label.setText(f"Virtual card {card_index + 1} of {total_cards}")
            self._sim_label.show()
        else:
            self._sim_label.hide()
