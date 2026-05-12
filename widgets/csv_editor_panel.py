"""CSV Editor Panel Widget - Table-based CSV editor"""

import logging
import os
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QFileDialog,
    QMessageBox,
)

from managers.csv_manager import SIM_DATA_FILETYPES, CSVManager
from utils import get_browse_initial_dir

logger = logging.getLogger(__name__)


class CSVEditorPanel(QWidget):
    """Panel for editing CSV card configurations"""

    def __init__(self, parent=None, *, state_manager=None, ns_manager=None, **kwargs):
        super().__init__(parent)
        self._csv_manager = CSVManager()
        self._ns_manager = ns_manager
        self.state_manager = state_manager
        self._last_browse_dir: Optional[str] = None
        self._unsaved_changes = False
        self._create_widgets()

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Toolbar
        toolbar_layout = QHBoxLayout()

        load_btn = QPushButton("Load CSV")
        load_btn.clicked.connect(self._on_load_csv)
        toolbar_layout.addWidget(load_btn)

        save_btn = QPushButton("Save CSV")
        save_btn.clicked.connect(self._on_save_csv)
        toolbar_layout.addWidget(save_btn)

        add_btn = QPushButton("Add Row")
        add_btn.clicked.connect(self._on_add_row)
        toolbar_layout.addWidget(add_btn)

        del_btn = QPushButton("Delete Row")
        del_btn.clicked.connect(self._on_delete_row)
        toolbar_layout.addWidget(del_btn)

        val_btn = QPushButton("Validate")
        val_btn.clicked.connect(self._on_validate)
        toolbar_layout.addWidget(val_btn)

        toolbar_layout.addStretch()

        self.count_label = QLabel("0 cards")
        toolbar_layout.addWidget(self.count_label)

        main_layout.addLayout(toolbar_layout)

        # Table widget
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setColumnCount(0)
        self.table.setRowCount(0)
        self.table.itemDoubleClicked.connect(self._on_cell_edited)
        main_layout.addWidget(self.table)

        self._refresh_table()

    @property
    def has_unsaved_changes(self) -> bool:
        return self._unsaved_changes

    def get_csv_manager(self) -> CSVManager:
        return self._csv_manager

    def _refresh_table(self):
        cols = self._csv_manager.columns
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(self._csv_manager.cards))

        for row, card in enumerate(self._csv_manager.cards):
            for col, col_name in enumerate(cols):
                value = card.get(col_name, '')
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)

        self.count_label.setText(f"{self._csv_manager.get_card_count()} cards")

    def _on_load_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        kwargs = {"title": "Load SIM Data File"}
        if init_dir:
            kwargs["directory"] = init_dir
        fp, _ = QFileDialog.getOpenFileName(
            self,
            "Load SIM Data File",
            init_dir or "",
            ";;".join(f"{desc} ({pattern})" for desc, pattern in SIM_DATA_FILETYPES)
        )
        if not fp:
            return
        self._last_browse_dir = os.path.dirname(fp)
        try:
            if self._csv_manager.load_file(fp):
                self._refresh_table()
                self._unsaved_changes = False
                if self._csv_manager.load_warnings:
                    QMessageBox.warning(
                        self, "Missing Fields",
                        "\n".join(self._csv_manager.load_warnings))
            else:
                QMessageBox.critical(
                    self, "Load Error",
                    f"No card data found in {fp}")
        except ValueError as exc:
            QMessageBox.critical(self, "Import Error", str(exc))

    def _on_save_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        fp, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV",
            init_dir or "",
            "CSV files (*.csv);;All files (*.*)"
        )
        if fp:
            if self._csv_manager.save_csv(fp):
                self._unsaved_changes = False
                QMessageBox.information(self, "Save", f"CSV saved to {fp}")
            else:
                QMessageBox.critical(self, "Save Error", "Failed to save CSV file.")

    def _on_add_row(self):
        self._csv_manager.add_card()
        self._refresh_table()
        self._unsaved_changes = True

    def _on_delete_row(self):
        if self.table.currentRow() >= 0:
            idx = self.table.currentRow()
            self._csv_manager.remove_card(idx)
            self._refresh_table()
            self._unsaved_changes = True

    def _on_validate(self):
        errors = self._csv_manager.validate_all()
        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors))
        else:
            QMessageBox.information(self, "Validation", "All rows valid!")

    def _on_cell_edited(self, item):
        col = item.column()
        row = item.row()
        if row < 0 or col < 0:
            return
        col_name = self._csv_manager.columns[col]
        new_val = item.text()
        self._csv_manager.update_card(row, col_name, new_val)
        self._unsaved_changes = True
