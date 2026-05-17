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
            self.state_manager.error_occurred.connect(self._on_error_occurred)

    def _create_widgets(self):
        main_layout = QGridLayout(self)
        main_layout.setSpacing(2)
        main_layout.setContentsMargins(2, 2, 2, 2)

        row = 0

        # Status row (cols 0-5)
        status_label = QLabel("Status:")
        status_label.setStyleSheet("font-weight: bold; min-width: 50px;")
        main_layout.addWidget(status_label, row, 0)

        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(16, 16)
        self.status_indicator.setStyleSheet("border-radius: 8px;")
        main_layout.addWidget(self.status_indicator, row, 1)

        self.status_label = QLabel()
        self.status_label.setStyleSheet("padding: 1px; margin-left: 2px;")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(16)
        main_layout.addWidget(self.status_label, row, 2, 1, 2)

        row += 1

        # Card info in 3 visual columns (label-value pairs horizontally arranged)
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

        items_per_col = 5
        for i, (label_text, key) in enumerate(info_labels):
            visual_col = i // items_per_col
            visual_row = i % items_per_col

            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold;")
            main_layout.addWidget(label, row + visual_row, visual_col * 2)

            entry = QLineEdit()
            entry.setReadOnly(True)
            entry.setText('Not available')
            entry.setStyleSheet("color: #808080;")
            main_layout.addWidget(entry, row + visual_row, visual_col * 2 + 1)
            self._info_vars[key] = entry

        row += 5

        # Already-programmed indicator
        self._programmed_label = QLabel()
        self._programmed_label.setStyleSheet("color: orange; font-weight: bold;")
        self._programmed_label.setText("⚠ Already programmed (artifact exists)")
        self._programmed_label.hide()
        main_layout.addWidget(self._programmed_label, row, 0, 1, 4)

        row += 1

        # Authenticate button
        self._auth_btn = QPushButton("Authenticate")
        self._auth_btn.clicked.connect(self._on_authenticate_clicked)
        main_layout.addWidget(self._auth_btn, row, 0, 1, 2)

        row += 1

        # Blocked indicator
        self._blocked_label = QLabel("⛔ CARD BLOCKED — Cannot be programmed")
        self._blocked_label.setStyleSheet("background-color: #CC0000; color: white; font-weight: bold; padding: 4px;")
        self._blocked_label.hide()
        main_layout.addWidget(self._blocked_label, row, 0, 1, 4)

        row += 1

        # Simulator info
        self._sim_label = QLabel()
        self._sim_label.setStyleSheet("font-size: 9pt;")
        self._sim_label.hide()
        main_layout.addWidget(self._sim_label, row, 0, 1, 4)

        # Column stretches for value fields
        main_layout.setColumnStretch(1, 1)
        main_layout.setColumnStretch(3, 1)

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

    def _on_error_occurred(self, message: str):
        """Handle error messages, distinguishing no-reader from other errors."""
        if "reader" in message.lower():
            self.set_status("no_reader", message)
            self.clear_card_info()
        else:
            self.set_status("error", message)

    def set_status(self, state, message=""):
        status_messages = {
            'waiting': 'Waiting for card insertion',
            'no_reader': 'No card reader detected',
            'reading': 'Reading card data...',
            'detected': 'Card detected',
            'authenticated': 'Card authenticated',
            'error': 'Error reading card',
            'blocked': 'Card blocked - cannot program',
        }
        colors = {
            'waiting': '#FFA500',
            'no_reader': '#999999',
            'reading': '#0078D4',
            'detected': '#0078D4',
            'authenticated': '#107C10',
            'error': '#E81123',
            'blocked': '#CC0000',
        }
        color = colors.get(state, '#CCCCCC')
        self.status_indicator.setStyleSheet(f"border-radius: 8px; background-color: {color};")
        display_message = message or status_messages.get(state, 'Unknown state')
        self.status_label.setText(display_message)

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
            self._info_vars['adm1_attempts'].setText('Not available')
        elif remaining == 0:
            self._info_vars['adm1_attempts'].setText('⛔ BLOCKED (0)')
        elif remaining <= 1:
            self._info_vars['adm1_attempts'].setText(f'⚠ {remaining} (DANGER!)')
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
            var.setText('Not available')
        self._programmed_label.hide()
        self._blocked_label.hide()

    def set_simulator_info(self, card_index, total_cards):
        """Show or hide the virtual card indicator below the buttons."""
        if card_index is not None and total_cards is not None:
            self._sim_label.setText(f"Virtual card {card_index + 1} of {total_cards}")
            self._sim_label.show()
        else:
            self._sim_label.hide()
