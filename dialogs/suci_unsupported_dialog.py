#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gialersim SUCI unsupported warning dialog."""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton


class SUCIUnsupportedDialog(QDialog):
    """Dialog warning that gialersim does not support SUCI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("5G SUCI Not Supported")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout()

        label = QLabel(
            "A gialersim card is inserted.\n\n"
            "This card type does not support 5G SUCI.\n\n"
            "SUCI has been disabled."
        )
        layout.addWidget(label)

        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        button_layout.addStretch()
        button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        ok_button.clicked.connect(self.accept)
