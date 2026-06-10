#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SJA5 SUCI support suggestion dialog."""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton


class SUCISuggestedDialog(QDialog):
    """Dialog suggesting SUCI enablement for SJA5 cards."""

    RESULT_CHECK = 1
    RESULT_IGNORE = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("5G SUCI Support Available")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout()

        label = QLabel(
            "An SJA5 card is inserted.\n\n"
            "This card supports 5G SUCI privacy service.\n\n"
            "Do you want to enable SUCI?"
        )
        layout.addWidget(label)

        button_layout = QHBoxLayout()
        check_button = QPushButton("Check")
        ignore_button = QPushButton("Ignore")
        button_layout.addStretch()
        button_layout.addWidget(check_button)
        button_layout.addWidget(ignore_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        check_button.clicked.connect(self.check_action)
        ignore_button.clicked.connect(self.ignore_action)

    def check_action(self) -> None:
        """User chose to enable SUCI."""
        self.done(self.RESULT_CHECK)

    def ignore_action(self) -> None:
        """User chose to ignore the suggestion."""
        self.done(self.RESULT_IGNORE)
