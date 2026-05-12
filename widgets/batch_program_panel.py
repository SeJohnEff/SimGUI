"""
Batch Program Panel — Workflow 3.

Program multiple SIM cards sequentially.
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
    QComboBox,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QRadioButton,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QFileDialog,
    QMessageBox,
)

from managers.batch_manager import BatchManager
from managers.card_manager import CardManager
from managers.csv_manager import CSVManager, SIM_DATA_FILETYPES
from managers.settings_manager import SettingsManager
from utils import get_browse_initial_dir
from utils.iccid_utils import (
    FPLMN_BY_COUNTRY,
    ISSUER_IDS,
    SIM_TYPES,
    SITE_REGISTER,
    generate_iccid,
    generate_imsi,
    get_fplmn_for_site,
)

logger = logging.getLogger(__name__)


def apply_imsi_override(cards: list[dict[str, str]], imsi_base: str,
                        start_seq: int = 1) -> list[dict[str, str]]:
    """Return copies of *cards* with IMSI replaced by base + 5-digit seq.

    Args:
        cards: List of card data dicts.
        imsi_base: First 10 digits of the IMSI (MCC+MNC + SSSS + T).
        start_seq: Sequence number for the first card (default 1).

    Returns:
        New list of card dicts — ICCID and all other fields are untouched.
    """
    result: list[dict[str, str]] = []
    for i, card in enumerate(cards):
        new_card = dict(card)
        new_card["IMSI"] = f"{imsi_base}{(start_seq + i):05d}"
        result.append(new_card)
    return result


def apply_range_filter(cards: list[dict[str, str]], start: int,
                       count: int) -> list[dict[str, str]]:
    """Return a slice of *cards* using 1-based *start* and *count*.

    Args:
        cards: Full list of card data dicts.
        start: 1-based start row.
        count: Number of cards to include.

    Returns:
        Sublist (shallow copies of dicts).
    """
    idx = max(start - 1, 0)
    return [dict(c) for c in cards[idx:idx + count]]


class BatchProgramPanel(QWidget):
    """Tab for batch-programming multiple SIM cards."""

    def __init__(self, parent=None, card_manager: CardManager = None,
                 settings: SettingsManager = None, *,
                 state_manager=None,
                 ns_manager=None, card_watcher=None,
                 iccid_index=None, auto_artifact_manager=None, **kwargs):
        super().__init__(parent)
        self._cm = card_manager
        self._settings = settings
        self.state_manager = state_manager
        self._ns_manager = ns_manager
        self._iccid_index = iccid_index
        self._auto_artifact = auto_artifact_manager
        self._last_browse_dir: Optional[str] = None
        self._batch_mgr = BatchManager(card_manager, card_watcher=card_watcher)
        self._csv = CSVManager()
        self._all_csv_cards: list[dict[str, str]] = []
        self._preview_data: list[dict[str, str]] = []
        self._source_var = "generate"
        self._standards_mgr = None

        self.on_csv_loaded_callback = None
        self.on_file_browsed_callback = None

        self._batch_mgr.on_progress = self._on_progress
        self._batch_mgr.on_card_result = self._on_card_result
        self._batch_mgr.on_waiting_for_card = self._on_waiting_for_card
        self._batch_mgr.on_completed = self._on_batch_completed

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Source selection
        source_layout = QHBoxLayout()
        source_label = QLabel("Data Source:")
        source_layout.addWidget(source_label)

        for source_name in ["Load CSV", "Generate Sequence"]:
            radio = QRadioButton(source_name)
            source_layout.addWidget(radio)
            if source_name == "Generate Sequence":
                radio.setChecked(True)
                radio.toggled.connect(lambda checked: self._on_source_change() if checked else None)
            else:
                radio.toggled.connect(lambda checked: self._on_source_change() if checked else None)

        source_layout.addStretch()
        main_layout.addLayout(source_layout)

        # CSV section
        csv_group = QGroupBox("CSV File")
        csv_layout = QVBoxLayout(csv_group)

        csv_bar = QHBoxLayout()
        self._csv_path_entry = QLineEdit()
        self._csv_path_entry.setReadOnly(True)
        csv_bar.addWidget(self._csv_path_entry)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse_csv)
        csv_bar.addWidget(browse_btn)

        self._csv_count_lbl = QLabel("")
        csv_bar.addWidget(self._csv_count_lbl)
        csv_layout.addLayout(csv_bar)

        main_layout.addWidget(csv_group)

        # Generate section
        gen_group = QGroupBox("Batch Template")
        gen_layout = QGridLayout(gen_group)
        gen_layout.setSpacing(6)

        row = 0
        gen_layout.addWidget(QLabel("MCC+MNC:"), row, 0)
        self._mcc_mnc_entry = QLineEdit()
        gen_layout.addWidget(self._mcc_mnc_entry, row, 1)
        row += 1

        gen_layout.addWidget(QLabel("Count:"), row, 0)
        self._count_spin = QSpinBox()
        self._count_spin.setMinimum(1)
        self._count_spin.setMaximum(100000)
        self._count_spin.setValue(20)
        gen_layout.addWidget(self._count_spin, row, 1)
        row += 1

        gen_layout.addWidget(QLabel("SPN:"), row, 0)
        self._spn_combo = QComboBox()
        gen_layout.addWidget(self._spn_combo, row, 1)
        row += 1

        gen_layout.addWidget(QLabel("FPLMN:"), row, 0)
        self._fplmn_entry = QLineEdit()
        gen_layout.addWidget(self._fplmn_entry, row, 1)

        main_layout.addWidget(gen_group)

        # Preview section
        preview_group = QGroupBox("Batch Preview")
        preview_layout = QVBoxLayout(preview_group)

        self._preview_table = QTableWidget()
        self._preview_table.setColumnCount(6)
        self._preview_table.setHorizontalHeaderLabels(["IMSI", "ICCID", "Site Code", "SPN", "FPLMN", "ADM1"])
        self._preview_table.setMaximumHeight(200)
        preview_layout.addWidget(self._preview_table)

        preview_btn = QPushButton("Preview Batch")
        preview_btn.clicked.connect(self._on_preview)
        preview_layout.addWidget(preview_btn)

        main_layout.addWidget(preview_group)

        # Execution section
        exec_group = QGroupBox("Batch Execution")
        exec_layout = QVBoxLayout(exec_group)

        btn_layout = QHBoxLayout()
        self._start_btn = QPushButton("Start Batch")
        self._start_btn.clicked.connect(self._on_start)
        btn_layout.addWidget(self._start_btn)

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setEnabled(False)
        self._pause_btn.clicked.connect(self._on_pause)
        btn_layout.addWidget(self._pause_btn)

        self._skip_btn = QPushButton("Skip Card")
        self._skip_btn.setEnabled(False)
        self._skip_btn.clicked.connect(self._on_skip)
        btn_layout.addWidget(self._skip_btn)

        self._abort_btn = QPushButton("Abort Batch")
        self._abort_btn.setEnabled(False)
        self._abort_btn.clicked.connect(self._on_abort)
        btn_layout.addWidget(self._abort_btn)

        btn_layout.addStretch()
        exec_layout.addLayout(btn_layout)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        exec_layout.addWidget(self._progress_bar)

        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(150)
        exec_layout.addWidget(self._log_text)

        main_layout.addWidget(exec_group)
        main_layout.addStretch()

    def _on_source_change(self):
        pass

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
        self._all_csv_cards = [self._csv.get_card(i) for i in range(self._csv.get_card_count())]

        if not _from_sync and self._csv.load_warnings:
            QMessageBox.warning(self, "Missing Fields", "\n".join(self._csv.load_warnings))

        if not _from_sync and callable(self.on_csv_loaded_callback):
            self.on_csv_loaded_callback(path)
        return True

    def set_standards_manager(self, mgr) -> None:
        self._standards_mgr = mgr
        self.refresh_standards()

    def refresh_standards(self) -> None:
        if self._standards_mgr and self._standards_mgr.has_standards:
            self._spn_combo.clear()
            self._spn_combo.addItems(self._standards_mgr.spn_values)

    def _on_preview(self):
        self._preview_data = []

    def _on_start(self):
        if not self._preview_data:
            self._on_preview()
        if not self._preview_data:
            QMessageBox.warning(self, "No Data", "No cards to program")
            return
        self._batch_mgr.start(self._preview_data)
        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._skip_btn.setEnabled(True)
        self._abort_btn.setEnabled(True)

    def _on_pause(self):
        self._batch_mgr.pause()

    def _on_skip(self):
        self._batch_mgr.skip_card()

    def _on_abort(self):
        self._batch_mgr.stop()

    def _on_progress(self, current, total, label):
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)

    def _on_card_result(self, iccid, ok, msg):
        status = "✓" if ok else "✗"
        self._log_text.appendPlainText(f"{status} {iccid}: {msg}")

    def _on_waiting_for_card(self):
        self._log_text.appendPlainText("Waiting for card insertion...")

    def _on_batch_completed(self, total, succeeded, failed):
        self._log_text.appendPlainText(f"\nBatch complete: {succeeded}/{total} succeeded, {failed} failed")
        self._start_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._skip_btn.setEnabled(False)
        self._abort_btn.setEnabled(False)

    def _on_export_results(self):
        pass
