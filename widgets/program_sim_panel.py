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

from state_manager import ProgramOutcome

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
    QCheckBox,
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
from qt_theme import QtTheme
from state_manager import StateManager, CardInfo, CardState
from utils import get_browse_initial_dir

logger = logging.getLogger(__name__)

SPN_UNSUPPORTED_PLACEHOLDER = "-- not yet implemented --"

_FORM_FIELDS = [
    ("ICCID", "ICCID", False),
    ("IMSI", "IMSI", True),
    ("Ki", "Ki", False),
    ("OPc", "OPc", False),
    ("ADM1", "ADM1", False),
    ("ACC", "ACC", True),
    ("SPN", "SPN", True),
    ("FPLMN", "FPLMN", True),
    ("HNET_PUBKEY", "HNET_PUBKEY (5G SUCI)", True),
]

# Canonical names for all known share/index fields (lowercase key → canonical)
_KNOWN_FIELD_NAMES = {
    'iccid': 'ICCID', 'imsi': 'IMSI', 'old_imsi': 'OLD_IMSI',
    'acc': 'ACC', 'pin1': 'PIN1', 'puk1': 'PUK1',
    'pin2': 'PIN2', 'puk2': 'PUK2',
    'ki': 'Ki', 'opc': 'OPc', 'adm1': 'ADM1', 'adm': 'ADM1',
    'kic1': 'KIC1', 'kid1': 'KID1', 'kik1': 'KIK1',
    'kic2': 'KIC2', 'kid2': 'KID2', 'kik2': 'KIK2',
    'kic3': 'KIC3', 'kid3': 'KID3', 'kik3': 'KIK3',
    'spn': 'SPN', 'fplmn': 'FPLMN', 'suci': 'SUCI', 'hnet_pubkey': 'HNET_PUBKEY',
}

_FORM_FIELD_KEYS = frozenset(k for k, _, _ in _FORM_FIELDS)

# Public fields readable without ADM auth — pre-filled from CardInfo on card read.
# Protected fields (Ki, OPc, ADM1, PIN*, KIC/KID/KIK) are intentionally absent.
_PUBLIC_READ_FIELDS = ("ICCID", "IMSI", "ACC", "SPN", "FPLMN")


def _normalize_card_data(data: dict) -> dict:
    """Normalize card data keys to canonical field names."""
    result = {}
    for k, v in data.items():
        norm = _KNOWN_FIELD_NAMES.get(k.strip().lower(), k.strip().upper())
        result[norm] = v
    return result


class ProgramSIMPanel(QWidget):
    """Tab for programming a single SIM card."""

    _READ_KEY_MAP = {
        'iccid': 'ICCID',
        'imsi': 'IMSI',
        'ki': 'Ki',
        'opc': 'OPc',
        'adm1': 'ADM1',
        'acc': 'ACC',
        'spn': 'SPN',
        'fplmn': 'FPLMN',
        'suci': 'SUCI',
    }

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
        self._extra_card_data: dict = {}
        # Sticky result: ICCID key set after a final Program Card action so that
        # card-watcher polls cannot overwrite the result message while the same
        # card is still inserted.  None means no sticky result is active.
        self._sticky_result_iccid: Optional[str] = None

        self.on_csv_loaded_callback = None
        self.on_file_browsed_callback = None
        self.on_card_programmed_callback = None

        self._build_ui()

        if self.state_manager:
            self.state_manager.card_info_changed.connect(self._on_card_info_changed)
            self.state_manager.card_state_changed.connect(self._on_card_state_changed)
            self.state_manager.status_changed.connect(self._on_global_status_changed)
            self._on_card_state_changed(self.state_manager.card_state)
            # Bootstrap: if a card is already detected when the panel is created,
            # populate public fields from the existing CardInfo.
            if self.state_manager.card_info.iccid:
                self._on_card_info_changed(self.state_manager.card_info)

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
            entry.textChanged.connect(self._update_program_btn_state)
            data_layout.addWidget(label_widget, i, 0)
            data_layout.addWidget(entry, i, 1)
            self._field_vars[key] = ""
            self._field_entries[key] = entry

        data_layout.setColumnStretch(1, 1)
        top_layout.addWidget(data_group)

        # Actions group
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)

        prog_btn_layout = QHBoxLayout()
        self._prog_btn = QPushButton("Program Card")
        self._prog_btn.clicked.connect(self._on_program)
        self._prog_btn.setEnabled(False)
        prog_btn_layout.addWidget(self._prog_btn)

        self._suci_checkbox = QCheckBox("Enable 5G SUCI")
        self._suci_checkbox.setChecked(True)
        prog_btn_layout.addWidget(self._suci_checkbox)
        prog_btn_layout.addStretch()
        actions_layout.addLayout(prog_btn_layout)

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
        elif card_state == CardState.ERROR:
            # ERROR is set for no-reader conditions or transient PCSC failures
            # during initial detection.  Only reset to "Insert a SIM card..." if
            # card presence was never established in this session (_step < 1).
            # If we already reached step 1, a transient error is not a card
            # removal — preserve the card-present display.
            if not (self._detected_non_empty or self._step >= 1):
                self.on_card_removed()
        elif card_state == CardState.NOT_POWERED:
            # Card physically present but not readable — keep panel idle.
            # Status text comes from StateManager.status_changed; no local wording.
            self._update_program_btn_state()
        elif card_state in (CardState.DETECTED, CardState.AUTHENTICATED):
            self._detected_non_empty = True
            self._step = 1
            self._update_program_btn_state()
        elif card_state == CardState.BLANK:
            self._detected_non_empty = False
            self._step = 1
            self._update_program_btn_state()

    def _on_global_status_changed(self, text: str) -> None:
        """Mirror global status text when the panel shows no-card/reader prompt.

        _on_card_state_changed runs first (card_state fires before status_text in
        main.py), so _reset_step() may set "Insert a SIM card..." before this slot
        runs.  When _step == 0 we overwrite that with the common mapping text so
        Program SIM and the global status bar always agree.
        """
        if self._step == 0 and not self._detected_non_empty:
            self._set_action_status(text)

    def _on_card_info_changed(self, card_info: CardInfo):
        """Populate public read fields from shared CardInfo; never touch protected fields.

        Only fills form fields that are currently empty so that:
        - CSV/index data loaded by on_card_detected is not overwritten
          (on_card_detected always fires after card_info_changed).
        - Manual user edits made before card insertion are preserved.

        CardInfo sentinel values ("-") are treated as absent.
        """
        if self._sticky_result_iccid is not None:
            incoming = card_info.iccid if (card_info.iccid and card_info.iccid != "(blank)") else ""
            if incoming != self._sticky_result_iccid:
                self._clear_sticky_result()
        self._update_program_btn_state()
        self._handle_suci_for_card_type(card_info)

        if not card_info.iccid:
            return

        info_values: dict[str, str] = {
            "ICCID": card_info.iccid if card_info.iccid != "(blank)" else "",
            "IMSI": card_info.imsi or "",
            "ACC": card_info.acc if card_info.acc not in ("-", "") else "",
            "SPN": SPN_UNSUPPORTED_PLACEHOLDER if (card_info.spn and card_info.spn not in ("-", "")) else "",
            "FPLMN": card_info.fplmn if card_info.fplmn not in ("-", "") else "",
        }

        for field_key in _PUBLIC_READ_FIELDS:
            value = info_values.get(field_key, "")
            if value and field_key in self._field_entries:
                entry = self._field_entries[field_key]
                current = entry.text().strip()
                if not current or current == "-":
                    entry.setText(value)

    def _set_sticky_result(self, iccid: str, text: str, style: str = "normal") -> None:
        """Set a final-action result that survives card-watcher polls for this card."""
        self._sticky_result_iccid = iccid
        self._set_action_status(text, style)

    def _clear_sticky_result(self) -> None:
        self._sticky_result_iccid = None

    def _get_hnet_pubkey(self, form_data: dict) -> str:
        """Get HNET_PUBKEY from form data or settings (canonical source).

        Returns the HNET_PUBKEY value, checking:
        1. Form data (highest priority - user-entered form value)
        2. Settings manager (fallback for SUCI config dialog)
        """
        # Check form first
        hnet_pubkey = form_data.get('HNET_PUBKEY', '').strip()
        if hnet_pubkey:
            return hnet_pubkey

        # Fallback to settings if not in form
        if hasattr(self, '_cm') and self._cm:
            settings_mgr = getattr(self._cm, 'settings_manager', None)
            if settings_mgr:
                return settings_mgr.get('suci_hnet_pubkey', '').strip()

        return ''

    def _handle_suci_for_card_type(self, card_info: CardInfo) -> None:
        """Show SUCI warnings and update UI based on detected card type."""
        from managers.card_manager import CardType
        from dialogs.suci_suggested_dialog import SUCISuggestedDialog
        from dialogs.suci_unsupported_dialog import SUCIUnsupportedDialog

        card_type = card_info.card_type
        suci_checked = self._suci_checkbox.isChecked()

        if card_type == CardType.GIALERSIM:
            # Gialersim doesn't support SUCI
            self._suci_checkbox.setEnabled(False)
            if suci_checked:
                dlg = SUCIUnsupportedDialog(self)
                dlg.exec()
                self._suci_checkbox.setChecked(False)
        elif card_type == CardType.SJA5:
            # SJA5 supports SUCI - suggest if not checked
            self._suci_checkbox.setEnabled(True)
            if not suci_checked:
                dlg = SUCISuggestedDialog(self)
                result = dlg.exec()
                if result == SUCISuggestedDialog.RESULT_CHECK:
                    self._suci_checkbox.setChecked(True)
        else:
            # Other card types - enable SUCI checkbox but don't force
            self._suci_checkbox.setEnabled(True)

    def _set_action_status(self, text: str, style: str = "normal"):
        self._action_status.setPlainText(text)
        # Color codes for status
        if style == "success":
            self._action_status.setStyleSheet(f"color: {QtTheme.get_color('success')};")
        elif style == "warning":
            self._action_status.setStyleSheet(f"color: {QtTheme.get_color('warning')};")
        elif style == "error":
            self._action_status.setStyleSheet(f"color: {QtTheme.get_color('error')};")
        else:
            self._action_status.setStyleSheet("")

    def _on_mode_change(self):
        mode = self._mode_var
        is_csv = mode == "csv"
        # TODO: implement mode switching logic
        self._reset_step()

    def _update_program_btn_state(self):
        """Update Program Card button state based on current card and CSV row state.

        Button is enabled if:
        - A card is detected/readable (DETECTED, AUTHENTICATED, or BLANK state)
        - AND there is form data selected (at least one field populated)
        """
        if not self.state_manager:
            return

        _current = self.state_manager.card_state
        card_detected = _current in (
            CardState.DETECTED, CardState.AUTHENTICATED, CardState.BLANK)
        has_data = self._fields_have_data()
        current_iccid = self._field_entries["ICCID"].text().strip()

        # Preserve sticky result while the same card is still inserted.
        if (self._sticky_result_iccid is not None
                and self._sticky_result_iccid == current_iccid):
            self._prog_btn.setEnabled(card_detected and has_data)
            return

        if card_detected and has_data:
            self._prog_btn.setEnabled(True)
            if current_iccid:
                self._set_action_status(
                    f"Card detected (ICCID {current_iccid}) — click Program to continue",
                    "success")
            else:
                self._set_action_status(
                    "Blank card detected — ready to program",
                    "success")
        else:
            self._prog_btn.setEnabled(False)
            if not card_detected:
                self._set_action_status("Insert a SIM card...")
            else:
                # Card is detected but no form data selected yet
                if current_iccid:
                    self._set_action_status(f"Card detected (ICCID {current_iccid}) — select data to program")
                else:
                    self._set_action_status("Blank card detected — select data or enter form data")

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
        """Check if any form field has data (any field, including ICCID)."""
        for key, _, _ in _FORM_FIELDS:
            if self._field_entries[key].text().strip():
                return True
        return False

    def on_card_detected(self, iccid, card_data=None, file_path=None):
        self._step = 1
        self._prog_btn.setEnabled(True)
        self._detected_non_empty = bool(iccid)

        _preserve_sticky = (
            self._sticky_result_iccid is not None
            and self._sticky_result_iccid == (iccid or "")
        )

        if card_data:
            normalized = _normalize_card_data(card_data)
            for key, _, _ in _FORM_FIELDS:
                val = normalized.get(key, "")
                # Public read fields absent from the CSV keep whatever
                # _on_card_info_changed already set from CardInfo (pySim-read
                # data).  Protected fields (Ki/OPc/ADM1) and CSV-present public
                # fields are always set from the CSV.
                if val or key not in _PUBLIC_READ_FIELDS:
                    display_val = SPN_UNSUPPORTED_PLACEHOLDER if key == "SPN" and val else val
                    self._field_entries[key].setText(display_val)
            # Store full normalized record so non-displayed fields (PIN1/PUK1,
            # KIC/KID/KIK, OLD_IMSI, etc.) pass through to programming.
            # Network-share data is authoritative — it is not overwritten by
            # card-read values from StateManager signals.
            self._extra_card_data = normalized
            # Do NOT capture target form fields as original_data.  The delta
            # baseline must come from CardManager._original_card_data (physical
            # card read-back).  Leaving this empty causes program_card to fall
            # through to the card manager's own baseline.
            self._original_form_data = {}
            src = os.path.basename(file_path) if file_path else "index"
            if not _preserve_sticky:
                self._set_action_status(
                    f"Card detected — data loaded from {src}",
                    "success")
        elif not iccid and self._fields_have_data():
            self._extra_card_data = {}
            self._original_form_data = {}
            if not _preserve_sticky:
                self._set_action_status(
                    "Blank card detected — ready to program",
                    "success")
        else:
            self._extra_card_data = {}
            if iccid:
                self._field_entries["ICCID"].setText(iccid)
            self._original_form_data = {}
            if iccid:
                if not _preserve_sticky:
                    self._set_action_status(
                        f"Card detected (ICCID {iccid}) — not in index, enter data manually",
                        "warning")
            else:
                if not _preserve_sticky:
                    self._set_action_status(
                        "Blank card detected — select a CSV row or enter data manually",
                        "warning")

        if self._detected_non_empty:
            self._field_entries["ICCID"].setReadOnly(True)
        else:
            self._field_entries["ICCID"].setReadOnly(False)

    def on_card_removed(self):
        self._clear_sticky_result()
        self._detected_non_empty = False
        self._step = 0
        self._reset_step()
        self._extra_card_data = {}
        self._original_form_data = {}
        for key, _, _ in _FORM_FIELDS:
            self._field_entries[key].setText("")
        # Keep SUCI enabled by default for the next card
        self._suci_checkbox.setChecked(True)
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
        normalized = _normalize_card_data(card)
        for key, _, _ in _FORM_FIELDS:
            val = normalized.get(key, "")
            display_val = SPN_UNSUPPORTED_PLACEHOLDER if key == "SPN" and val else val
            self._field_entries[key].setText(display_val)
        # Preserve extra fields (PIN1/PUK1, KIC/KID/KIK, etc.) from CSV row
        self._extra_card_data = normalized

        # Update SUCI checkbox from CSV (default to True if not specified)
        suci_val = normalized.get('SUCI', '').lower()
        # If SUCI not in CSV, default to enabled; otherwise use CSV value
        suci_enabled = suci_val in ('true', 'yes', '1', 'enabled') if suci_val else True
        self._suci_checkbox.setChecked(suci_enabled)

        # Auto-fill HNET_PUBKEY from settings if not in CSV
        if not normalized.get('HNET_PUBKEY') and hasattr(self, '_cm') and self._cm:
            settings_mgr = getattr(self._cm, 'settings_manager', None)
            if settings_mgr:
                hnet_pubkey = settings_mgr.get('suci_hnet_pubkey', '')
                if hnet_pubkey:
                    self._extra_card_data['HNET_PUBKEY'] = hnet_pubkey

        # Re-evaluate button state after CSV row is selected
        self._update_program_btn_state()
        if self.state_manager and self.state_manager.card_state in (
                CardState.DETECTED, CardState.AUTHENTICATED, CardState.BLANK):
            self._set_action_status(
                "CSV row selected — ready to program",
                "success")

    def _on_program(self):
        if self._step < 1:
            return
        # Clear any previous sticky result — this is a new explicit action.
        self._clear_sticky_result()
        adm1 = self._field_entries["ADM1"].text().strip()
        if not adm1:
            self._set_action_status("ADM1 is required", "warning")
            return
        expected_iccid = self._field_entries["ICCID"].text().strip() or None
        # Non-displayed share fields (OLD_IMSI, PIN1/PUK1, KIC/KID/KIK, etc.)
        # pass through unchanged; displayed/editable fields always win.
        card_data = {k: v for k, v in self._extra_card_data.items()
                     if k not in _FORM_FIELD_KEYS}
        card_data.update({k: self._field_entries[k].text().strip()
                          for k, _, _ in _FORM_FIELDS})
        card_data.pop('SPN', None)

        # Ensure HNET_PUBKEY from settings is included if not in form (canonical source)
        hnet_pubkey = self._get_hnet_pubkey(card_data)
        if hnet_pubkey:
            card_data['HNET_PUBKEY'] = hnet_pubkey
        # Add SUCI from checkbox
        suci_enabled = False
        if self._suci_checkbox.isChecked():
            card_data['SUCI'] = 'true'
            suci_enabled = True
        else:
            card_data.pop('SUCI', None)

        # Warn if SUCI is enabled but HNET_PUBKEY is empty (check canonical source)
        if suci_enabled:
            hnet_pubkey = self._get_hnet_pubkey(card_data)
            if not hnet_pubkey:
                confirm = QMessageBox.warning(
                    self,
                    "SUCI Configuration Warning",
                    "5G SUCI (Subscription Concealed Identifier) is enabled, "
                    "but the Home Network Public Key (HNET_PUBKEY) is empty.\n\n"
                    "Without HNET_PUBKEY, the card cannot perform SUCI calculations. "
                    "The service will be active but non-functional.\n\n"
                    "Continue anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if confirm != QMessageBox.StandardButton.Yes:
                    self._set_action_status("Programming cancelled", "info")
                    return

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

            ok, msg, result = self._cm.program_card(
                card_data, original_data=self._original_form_data or None)
        finally:
            if self._card_watcher:
                self._card_watcher.resume()

        current_iccid = self._field_entries["ICCID"].text().strip()
        if result.outcome == ProgramOutcome.NO_CHANGES:
            self._set_sticky_result(
                current_iccid,
                "No changes to program — card already matches CSV data")
            return
        if ok:
            clean = result.outcome == ProgramOutcome.WRITE_OK_VERIFIED
            if clean and callable(getattr(self, 'on_card_programmed_callback', None)):
                saved_paths = self.on_card_programmed_callback(card_data, result)
                if saved_paths:
                    msg += f"\nArtifact saved: {saved_paths[0]}"
            self._set_sticky_result(current_iccid, msg, "success" if clean else "warning")
        else:
            self._set_action_status(msg, "error")
