"""
Read SIM Panel — Workflow 1.

Reads all accessible data from an inserted SIM card.
Public fields (ICCID, IMSI, ACC, etc.) are shown without authentication.
Protected fields (Ki, OPc, OTA keys) are revealed after ADM1 auth
and clicking "Read Card".

Detection is handled by the shared Card Status panel (left side).
This widget observes the card manager state — call refresh() after
a detect/mode change from the main window.
"""

from typing import Optional

import csv
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QGroupBox,
    QFileDialog,
    QMessageBox,
    QSizePolicy,
)

from managers.card_manager import CardManager
from state_manager import StateManager, CardInfo, CardState

# Display order and labels for public fields
_PUBLIC_DISPLAY = [
    ("iccid", "ICCID"),
    ("imsi", "IMSI"),
    ("acc", "ACC"),
    ("msisdn", "MSISDN"),
    ("mnc_length", "MNC Length"),
    ("pin1", "PIN1"),
    ("puk1", "PUK1"),
    ("pin2", "PIN2"),
    ("puk2", "PUK2"),
    ("suci_protection_scheme", "SUCI Scheme"),
    ("suci_routing_indicator", "SUCI Routing Ind."),
    ("suci_hn_pubkey", "SUCI HN PubKey"),
]

# Display order and labels for protected fields
_PROTECTED_DISPLAY = [
    ("ki", "Ki"),
    ("opc", "OPc"),
    ("adm1", "ADM1"),
    ("kic1", "KIC1"),
    ("kid1", "KID1"),
    ("kik1", "KIK1"),
    ("kic2", "KIC2"),
    ("kid2", "KID2"),
    ("kik2", "KIK2"),
    ("kic3", "KIC3"),
    ("kid3", "KID3"),
    ("kik3", "KIK3"),
]


class ReadSIMPanel(QWidget):
    """Tab that guides the user through reading a SIM card."""

    def __init__(self, parent, card_manager: CardManager, *,
                 state_manager: Optional[StateManager] = None,
                 last_read_data: Optional[dict] = None,
                 ns_manager=None, card_watcher=None, **kwargs):
        super().__init__(parent)
        self._cm = card_manager
        self.state_manager = state_manager
        self._ns_manager = ns_manager
        self._card_watcher = card_watcher
        self._last_browse_dir: Optional[str] = None
        self._last_read_data = last_read_data if last_read_data is not None else {}
        self._public_data: dict = {}
        self._protected_data: dict = {}
        self._detected_iccid: str = ""
        self._authenticated: bool = False

        self._pub_fields: dict[str, QLineEdit] = {}
        self._prot_fields: dict[str, QLineEdit] = {}

        self._build_ui()

        if self.state_manager:
            self.state_manager.card_info_changed.connect(self._on_card_info_changed)
            self.state_manager.card_state_changed.connect(self._on_card_state_changed)

    # ---- UI construction -----------------------------------------------

    def _build_ui(self):
        """Build the main UI layout."""
        main_layout = QGridLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        row = 0

        # --- Public Fields section ---
        pub_group = QGroupBox("Public Fields (no auth required)")
        pub_layout = QGridLayout(pub_group)
        pub_layout.setSpacing(4)
        pub_layout.setContentsMargins(2, 2, 2, 2)

        for i, (key, label) in enumerate(_PUBLIC_DISPLAY):
            grid_row, col = divmod(i, 2)
            label_widget = QLabel(f"{label}:")
            label_widget.setMinimumWidth(60)
            value_field = QLineEdit()
            value_field.setText("-")
            value_field.setReadOnly(True)
            value_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            value_field.setMinimumWidth(120)

            pub_layout.addWidget(label_widget, grid_row, col * 2)
            pub_layout.addWidget(value_field, grid_row, col * 2 + 1)
            self._pub_fields[key] = value_field

        pub_layout.setColumnStretch(1, 1)
        pub_layout.setColumnStretch(3, 1)
        main_layout.addWidget(pub_group, row, 0)

        # --- Authentication section ---
        auth_group = QGroupBox("Authentication")
        auth_layout_outer = QVBoxLayout(auth_group)
        auth_layout_outer.setSpacing(2)
        auth_layout_outer.setContentsMargins(2, 2, 2, 2)

        auth_input_layout = QGridLayout()
        auth_input_layout.setSpacing(4)

        auth_label = QLabel("ADM1:")
        auth_label.setMinimumWidth(40)
        self._adm1_field = QLineEdit()
        self._adm1_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._adm1_field.setMinimumWidth(150)
        self._auth_btn = QPushButton("Authenticate")
        self._auth_btn.clicked.connect(self._on_authenticate)
        self._auth_btn.setMinimumWidth(110)
        self._auth_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        auth_input_layout.addWidget(auth_label, 0, 0)
        auth_input_layout.addWidget(self._adm1_field, 0, 1)
        auth_input_layout.addWidget(self._auth_btn, 0, 2)

        self._csv_adm_btn = QPushButton("Load ADM1 from CSV...")
        self._csv_adm_btn.clicked.connect(self._on_load_adm1_csv)
        self._csv_adm_btn.setMinimumWidth(150)
        self._csv_adm_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        auth_input_layout.addWidget(self._csv_adm_btn, 0, 3)

        auth_input_layout.setColumnStretch(1, 1)
        auth_input_layout.setColumnStretch(2, 0)
        auth_input_layout.setColumnStretch(3, 1)
        auth_layout_outer.addLayout(auth_input_layout)

        self._auth_status = QLabel("Enter ADM1 to authenticate")
        self._auth_status.setStyleSheet("font-size: 9pt; color: #666;")
        auth_layout_outer.addWidget(self._auth_status)

        main_layout.addWidget(auth_group, row, 1)

        row += 1

        # --- Protected Fields section ---
        prot_group = QGroupBox("Protected Fields (requires ADM1)")
        prot_layout_outer = QVBoxLayout(prot_group)
        prot_layout_outer.setSpacing(4)
        prot_layout_outer.setContentsMargins(2, 2, 2, 2)

        prot_top = QHBoxLayout()
        self._read_btn = QPushButton("Read Card")
        self._read_btn.clicked.connect(self._on_read_card)
        self._read_btn.setEnabled(False)
        self._read_status = QLabel("Authenticate first")

        prot_top.addWidget(self._read_btn)
        prot_top.addWidget(self._read_status)
        prot_top.addStretch()
        prot_layout_outer.addLayout(prot_top)

        prot_grid = QGridLayout()
        prot_grid.setSpacing(4)

        for i, (key, label) in enumerate(_PROTECTED_DISPLAY):
            grid_row, col = divmod(i, 3)
            label_widget = QLabel(f"{label}:")
            label_widget.setMinimumWidth(50)
            value_field = QLineEdit()
            value_field.setText("-")
            value_field.setReadOnly(True)
            value_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            value_field.setMinimumWidth(100)

            prot_grid.addWidget(label_widget, grid_row, col * 2)
            prot_grid.addWidget(value_field, grid_row, col * 2 + 1)
            self._prot_fields[key] = value_field

        prot_grid.setColumnStretch(1, 1)
        prot_grid.setColumnStretch(3, 1)
        prot_grid.setColumnStretch(5, 1)
        prot_layout_outer.addLayout(prot_grid)
        main_layout.addWidget(prot_group, row, 0, 1, 2)

        row += 1

        # --- Bottom action buttons ---
        btn_layout = QHBoxLayout()
        self._copy_btn = QPushButton("Copy All to Clipboard")
        self._copy_btn.clicked.connect(self._on_copy)
        self._export_btn = QPushButton("Export to CSV...")
        self._export_btn.clicked.connect(self._on_export)

        btn_layout.addWidget(self._copy_btn)
        btn_layout.addWidget(self._export_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout, row, 0, 1, 2)

    def _on_card_state_changed(self, card_state: CardState):
        """Signal handler for card state changes."""
        if card_state == CardState.NO_CARD:
            self.refresh()

    def _on_card_info_changed(self, card_info: CardInfo):
        """Signal handler for card info changes."""
        pass

    # ---- public interface (called by main.py) --------------------------

    def refresh(self):
        """Update public fields from the current card manager state.

        Call this after a card detect or mode change from the main window.
        """
        # Reset auth / protected state when card changes
        self._authenticated = False
        self._read_btn.setEnabled(False)
        self._read_status.setText("Authenticate first")
        self._protected_data = {}
        for field in self._prot_fields.values():
            field.setText("-")

        # Read public data
        raw = self._cm.read_public_data()
        if raw:
            # Normalise keys to lowercase so they match _PUBLIC_DISPLAY.
            # card_info uses uppercase ("ICCID") but the display map uses
            # lowercase ("iccid").
            pub = {k.lower(): v for k, v in raw.items()}
            self._public_data = pub
            self._detected_iccid = pub.get("iccid", "")
            for key, field in self._pub_fields.items():
                val = pub.get(key, "")
                field.setText(val if val else "-")
            # Store public data in shared state for Program SIM tab
            self._update_shared_read_data()
        else:
            self._public_data = {}
            self._detected_iccid = ""
            for field in self._pub_fields.values():
                field.setText("-")
            # Clear shared state when no card
            self._last_read_data.clear()

    # ---- actions -------------------------------------------------------

    def _on_authenticate(self):
        adm1 = self._adm1_field.text().strip()
        if not adm1:
            self._auth_status.setText("Please enter ADM1")
            return
        if not self._detected_iccid:
            self._auth_status.setText(
                "No card detected — use Detect Card in the left panel")
            return

        expected_iccid = self._detected_iccid or None

        # Pause the card watcher so its probes don't interfere with
        # the VERIFY APDU that authenticate() sends to the card.
        if self._card_watcher:
            self._card_watcher.pause()
        try:
            ok, msg = self._cm.authenticate(
                adm1, expected_iccid=expected_iccid)

            # If auth was refused due to low retry counter, offer a
            # force-override so the operator can still proceed.
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
                        adm1, force=True,
                        expected_iccid=expected_iccid)
        finally:
            if self._card_watcher:
                self._card_watcher.resume()

        if ok:
            self._auth_status.setText(msg)
            self._authenticated = True
            self._read_btn.setEnabled(True)
            self._read_status.setText("Ready to read")
        else:
            self._auth_status.setText(msg)
            self._authenticated = False
            self._read_btn.setEnabled(False)
            if "ICCID mismatch" in msg:
                QMessageBox.warning(self, "ICCID Mismatch", msg)

    def _on_load_adm1_csv(self):
        if not self._detected_iccid:
            QMessageBox.information(
                self,
                "Detect First",
                "Please detect a card first (via Card Status panel) "
                "so the ICCID is known.")
            return
        from managers.csv_manager import SIM_DATA_FILETYPES
        from utils import get_browse_initial_dir

        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ADM1 Data File",
            init_dir or "",
            ";;".join(f"{desc} ({pattern})" for desc, pattern in SIM_DATA_FILETYPES))
        if not path:
            return
        self._last_browse_dir = os.path.dirname(path)
        adm1 = self._lookup_adm1_in_file(path, self._detected_iccid)
        if adm1:
            self._adm1_field.setText(adm1)
            self._auth_status.setText(
                "ADM1 loaded from CSV (matched ICCID)")
        else:
            self._auth_status.setText(
                "No matching ICCID found in CSV")

    @staticmethod
    def _lookup_adm1_in_file(path: str, iccid: str) -> str:
        """Search *path* (CSV or EML) for a row whose ICCID matches, return its ADM1."""
        try:
            if path.lower().endswith(".eml"):
                from utils.eml_parser import parse_eml_file
                cards, _ = parse_eml_file(path)
                for card in cards:
                    if card.get("ICCID", "").strip() == iccid:
                        return card.get("ADM1", "").strip()
            else:
                with open(path, "r", newline="", encoding="utf-8-sig") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        if row.get("ICCID", "").strip() == iccid:
                            return row.get("ADM1", "").strip()
        except Exception:
            pass
        return ""

    def _on_read_card(self):
        """Read protected fields from the card after authentication."""
        if not self._authenticated:
            self._read_status.setText("Not authenticated")
            return
        data = self._cm.read_protected_data()
        if data is None:
            self._read_status.setText("Failed to read card data")
            return
        self._protected_data = data
        self._read_status.setText(
            f"Read {len(data)} protected field(s)")
        for key, field in self._prot_fields.items():
            val = data.get(key, "")
            field.setText(val if val else "-")
        # Update shared state with protected fields
        self._update_shared_read_data()

    def _update_shared_read_data(self):
        """Merge public + protected data into the shared last_read_data dict."""
        self._last_read_data.clear()
        self._last_read_data.update(self._public_data)
        self._last_read_data.update(self._protected_data)

    def _on_copy(self):
        combined = {}
        combined.update(self._public_data)
        combined.update(self._protected_data)
        if not combined:
            return
        lines = [f"{k.upper()}: {v}" for k, v in combined.items()]
        text = "\n".join(lines)
        from PyQt6.QtGui import QClipboard
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

    def _on_export(self):
        combined = {}
        combined.update(self._public_data)
        combined.update(self._protected_data)
        if not combined:
            return
        from utils import get_browse_initial_dir

        init_dir = get_browse_initial_dir(self._ns_manager, self._last_browse_dir)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Card Data",
            init_dir or "",
            "CSV files (*.csv);;All files (*.*)")
        if not path:
            return
        try:
            keys = list(combined.keys())
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=keys)
                writer.writeheader()
                writer.writerow(combined)
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
