"""
Program SIM Panel — Workflow 2.

Program a single SIM card. Data comes from manual entry or CSV selection.
Card detection is automatic via CardWatcher. When a card is inserted,
fields are auto-populated from the IccidIndex if the card's ICCID is
found in a loaded data file.
"""

import logging
import os
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QFileDialog,
    QMessageBox,
)

from managers.card_manager import CardManager
from managers.csv_manager import CSVManager, SIM_DATA_FILETYPES
from state_manager import StateManager, CardInfo, CardState
from utils import get_browse_initial_dir

logger = logging.getLogger(__name__)

_FORM_FIELDS = [
    ("ICCID", "ICCID", False),
    ("IMSI", "IMSI", True),
    ("Ki", "Ki", False),
    ("OPc", "OPc", False),
    ("ADM1", "ADM1", False),
    ("ACC", "ACC", True),
    ("SPN", "SPN", True),
    ("FPLMN", "FPLMN", True),
]


class ProgramSIMPanel(QWidget):
    """Tab for programming a single SIM card."""

    def __init__(self, parent=None, card_manager: CardManager = None, *,
                 state_manager: Optional[StateManager] = None,
                 last_read_data: Optional[dict] = None,
                 ns_manager=None, card_watcher=None, **kwargs):
        super().__init__(parent)
        self._cm = card_manager
        self.state_manager = state_manager
        self._ns_manager = ns_manager
        self._card_watcher = card_watcher
        self._last_browse_dir: Optional[str] = None
        self._csv = CSVManager()
        self._last_read_data = last_read_data if last_read_data is not None else {}
        self._mode_var = "manual"
        self._field_vars: dict[str, str] = {}
        self._field_entries: dict[str, QLineEdit] = {}
        self._step = 0
        self._original_form_data: dict[str, str] = {}
        self._detected_non_empty: bool = False

        self.on_csv_loaded_callback = None
        self.on_file_browsed_callback = None
        self.on_card_programmed_callback = None

        self._build_ui()

        if self.state_manager:
            self.state_manager.card_info_changed.connect(self._on_card_info_changed)
            self.state_manager.card_state_changed.connect(self._on_card_state_changed)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Mode selection
        mode_layout = QHBoxLayout()
        mode_label = QLabel("Data Source:")
        mode_layout.addWidget(mode_label)

        for mode_name in ["Manual Entry", "From CSV", "From Read Card"]:
            radio = QRadioButton(mode_name)
            mode_layout.addWidget(radio)
            if mode_name == "Manual Entry":
                radio.setChecked(True)
                radio.toggled.connect(lambda checked: self._on_mode_change() if checked else None)
            else:
                radio.toggled.connect(lambda checked: self._on_mode_change() if checked else None)

        mode_layout.addStretch()
        main_layout.addLayout(mode_layout)

        # Splitter: top = form, bottom = CSV table
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top pane
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # Card Data group
        data_group = QGroupBox("Card Data")
        data_layout = QGridLayout(data_group)
        data_layout.setSpacing(6)

        for i, (key, label, _) in enumerate(_FORM_FIELDS):
            label_widget = QLabel(f"{label}:")
            entry = QLineEdit()
            entry.setText("")
            data_layout.addWidget(label_widget, i, 0)
            data_layout.addWidget(entry, i, 1)
            self._field_vars[key] = ""
            self._field_entries[key] = entry

        data_layout.setColumnStretch(1, 1)
        top_layout.addWidget(data_group)

        # Actions group
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)

        self._prog_btn = QPushButton("Program Card")
        self._prog_btn.clicked.connect(self._on_program)
        self._prog_btn.setEnabled(False)
        actions_layout.addWidget(self._prog_btn)

        self._action_status = QPlainTextEdit()
        self._action_status.setPlainText("Insert a SIM card...")
        self._action_status.setReadOnly(True)
        self._action_status.setMaximumHeight(60)
        actions_layout.addWidget(self._action_status)

        top_layout.addWidget(actions_group)

        splitter.addWidget(top_widget)

        # Bottom pane: CSV table
        csv_widget = QWidget()
        csv_layout = QVBoxLayout(csv_widget)
        csv_layout.setContentsMargins(0, 0, 0, 0)

        csv_group = QGroupBox("CSV Selection")
        csv_group_layout = QVBoxLayout(csv_group)

        # CSV path bar
        csv_bar = QHBoxLayout()
        self._csv_path_entry = QLineEdit()
        self._csv_path_entry.setReadOnly(True)
        csv_bar.addWidget(self._csv_path_entry)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse_csv)
        csv_bar.addWidget(browse_btn)

        self._csv_count_lbl = QLabel("")
        csv_bar.addWidget(self._csv_count_lbl)

        csv_group_layout.addLayout(csv_bar)

        # CSV table
        self._card_table = QTableWidget()
        self._card_table.setColumnCount(3)
        self._card_table.setHorizontalHeaderLabels(["ICCID", "IMSI", "ADM1"])
        self._card_table.itemClicked.connect(self._on_card_select)
        csv_group_layout.addWidget(self._card_table)

        csv_layout.addWidget(csv_group)
        splitter.addWidget(csv_widget)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 200])

        main_layout.addWidget(splitter)

    def _on_card_state_changed(self, card_state: CardState):
        if card_state == CardState.NO_CARD:
            self.on_card_removed()

    def _on_card_info_changed(self, card_info: CardInfo):
        pass

    def _set_action_status(self, text: str, style: str = "normal"):
        self._action_status.setPlainText(text)
        # Color codes for status
        if style == "success":
            self._action_status.setStyleSheet("color: #2e7d32;")
        elif style == "warning":
            self._action_status.setStyleSheet("color: #e65100;")
        elif style == "error":
            self._action_status.setStyleSheet("color: #c62828;")
        else:
            self._action_status.setStyleSheet("")

    def _on_mode_change(self):
        mode = self._mode_var
        is_csv = mode == "csv"
        # TODO: implement mode switching logic
        self._reset_step()

    def _reset_step(self):
        if self._detected_non_empty or self._step >= 1:
            self._step = 1
            self._prog_btn.setEnabled(True)
            iccid = self._field_entries["ICCID"].text().strip()
            if iccid:
                self._set_action_status(
                    f"Card detected (ICCID {iccid}) — click Program to continue",
                    "success")
            else:
                self._set_action_status(
                    "Blank card detected — click Program to continue",
                    "success")
        else:
            self._step = 0
            self._prog_btn.setEnabled(False)
            self._set_action_status("Insert a SIM card...")

    def _fields_have_data(self) -> bool:
        for key, _, _ in _FORM_FIELDS:
            if key == "ICCID":
                continue
            if self._field_entries[key].text().strip():
                return True
        return False

    def on_card_detected(self, iccid, card_data=None, file_path=None):
        self._step = 1
        self._prog_btn.setEnabled(True)
        self._detected_non_empty = bool(iccid)

        if card_data:
            for key, _, _ in _FORM_FIELDS:
                val = card_data.get(key, card_data.get(key.upper(), ""))
                if key == "OPc" and not val:
                    val = card_data.get("OPC", "")
                self._field_entries[key].setText(val)
            self._original_form_data = {
                k: self._field_entries[k].text() for k, _, _ in _FORM_FIELDS
            }
            src = os.path.basename(file_path) if file_path else "index"
            self._set_action_status(
                f"Card detected — data loaded from {src}",
                "success")
        elif not iccid and self._fields_have_data():
            self._original_form_data = {}
            self._set_action_status(
                "Blank card detected — ready to program",
                "success")
        else:
            if iccid:
                self._field_entries["ICCID"].setText(iccid)
            self._original_form_data = {}
            if iccid:
                self._set_action_status(
                    f"Card detected (ICCID {iccid}) — not in index, enter data manually",
                    "warning")
            else:
                self._set_action_status(
                    "Blank card detected — select a CSV row or enter data manually",
                    "warning")

        if self._detected_non_empty:
            self._field_entries["ICCID"].setReadOnly(True)
        else:
            self._field_entries["ICCID"].setReadOnly(False)

    def on_card_removed(self):
        self._detected_non_empty = False
        self._step = 0
        self._reset_step()
        self._original_form_data = {}
        for key, _, _ in _FORM_FIELDS:
            self._field_entries[key].setText("")
        self._field_entries["ICCID"].setReadOnly(False)

    def _on_browse_csv(self):
        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        fp, _ = QFileDialog.getOpenFileName(
            self,
            "Open SIM Data File",
            init_dir or "",
            ";;".join(f"{desc} ({pattern})" for desc, pattern in SIM_DATA_FILETYPES)
        )
        if callable(self.on_file_browsed_callback):
            self.on_file_browsed_callback()
        if not fp:
            return
        self._last_browse_dir = os.path.dirname(fp)
        self.load_csv_file(fp)

    def load_csv_file(self, path: str, *, _from_sync: bool = False) -> bool:
        try:
            if not self._csv.load_file(path):
                if not _from_sync:
                    QMessageBox.critical(self, "Error", f"No card data found in {path}")
                return False
        except ValueError as exc:
            if not _from_sync:
                QMessageBox.critical(self, "Import Error", str(exc))
            return False

        self._csv_path_entry.setText(path)
        self._csv_count_lbl.setText(f"({self._csv.get_card_count()} cards)")
        self._refresh_card_table()

        if not _from_sync and self._csv.load_warnings:
            QMessageBox.warning(
                self, "Missing Fields",
                "\n".join(self._csv.load_warnings))

        if not _from_sync and callable(self.on_csv_loaded_callback):
            self.on_csv_loaded_callback(path)
        return True

    def _refresh_card_table(self):
        self._card_table.setRowCount(self._csv.get_card_count())
        for i in range(self._csv.get_card_count()):
            card = self._csv.get_card(i)
            if card:
                iccid_item = QTableWidgetItem(card.get("ICCID", ""))
                imsi_item = QTableWidgetItem(card.get("IMSI", ""))
                adm1_item = QTableWidgetItem(card.get("ADM1", ""))
                self._card_table.setItem(i, 0, iccid_item)
                self._card_table.setItem(i, 1, imsi_item)
                self._card_table.setItem(i, 2, adm1_item)

    def _on_card_select(self):
        current_row = self._card_table.currentRow()
        if current_row < 0:
            return
        card = self._csv.get_card(current_row)
        if not card:
            return
        for key, _, _ in _FORM_FIELDS:
            val = card.get(key, card.get(key.upper(), ""))
            if key == "OPc" and not val:
                val = card.get("OPC", "")
            self._field_entries[key].setText(val)

        if self._step >= 1:
            self._set_action_status(
                "CSV row selected — ready to program",
                "success")
        else:
            self._reset_step()

    def _on_program(self):
        if self._step < 1:
            return
        adm1 = self._field_entries["ADM1"].text().strip()
        if not adm1:
            self._set_action_status("ADM1 is required", "warning")
            return
        expected_iccid = self._field_entries["ICCID"].text().strip() or None
        card_data = {k: self._field_entries[k].text().strip()
                     for k, _, _ in _FORM_FIELDS}

        if self._card_watcher:
            self._card_watcher.pause()
        try:
            ok, msg = self._cm.authenticate(adm1, expected_iccid=expected_iccid)

            if not ok and "DANGER" in msg and "attempt" in msg:
                confirm = QMessageBox.warning(
                    self,
                    "Low ADM1 Attempts",
                    f"{msg}\n\n"
                    "Are you SURE the ADM1 key is correct?\n"
                    "A wrong key will permanently lock this card.\n\n"
                    "Force authentication?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if confirm == QMessageBox.StandardButton.Yes:
                    ok, msg = self._cm.authenticate(
                        adm1, force=True, expected_iccid=expected_iccid)

            if not ok:
                self._set_action_status(msg, "error")
                return

            ok, msg = self._cm.program_card(
                card_data, original_data=self._original_form_data or None)
        finally:
            if self._card_watcher:
                self._card_watcher.resume()

        if ok:
            self._set_action_status(msg, "success")
            if callable(getattr(self, 'on_card_programmed_callback', None)):
                self.on_card_programmed_callback(card_data)
        else:
            self._set_action_status(msg, "error")
