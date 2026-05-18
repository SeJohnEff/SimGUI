"""Tests for File → Export Artifacts wiring and handler logic.

These tests use AST inspection and unit-level mocking — no display required.
"""

import ast
import csv
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_SRC = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _find_method_body(source: str, class_name: str, method_name: str) -> str:
    """Return the source text of a method body."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    lines = source.splitlines()
                    start = item.lineno - 1
                    end = item.end_lineno
                    return "\n".join(lines[start:end])
    return ""


# ---------------------------------------------------------------------------
# Wiring: menu action is connected (structural check)
# ---------------------------------------------------------------------------

class TestMenuWiring:
    def test_export_artifacts_action_connected(self):
        """Export Artifacts QAction is connected to _on_export_artifacts."""
        assert "_on_export_artifacts" in MAIN_SRC
        assert 'triggered.connect(self._on_export_artifacts)' in MAIN_SRC

    def test_on_card_programmed_callback_wired(self):
        """ProgramSIMPanel.on_card_programmed_callback is set in _build_layout."""
        assert "on_card_programmed_callback = self._on_card_programmed" in MAIN_SRC

    def test_card_programmed_signal_connected_to_auto_artifact(self):
        """state_manager.card_programmed signal is connected to save_card_artifact."""
        assert "card_programmed.connect" in MAIN_SRC
        assert "save_card_artifact" in MAIN_SRC


# ---------------------------------------------------------------------------
# Handler: _on_export_artifacts shows dialog when no programmed card
# ---------------------------------------------------------------------------

class TestExportArtifactsHandler:
    """Unit tests for _on_export_artifacts and _on_card_programmed logic."""

    def _make_app_stub(self):
        """Build a minimal stub that has the same attributes as SimGUIApp."""
        from managers.auto_artifact_manager import AutoArtifactManager, DEFAULT_ARTIFACT_FIELDS
        from datetime import datetime as dt

        # Import the real methods without instantiating SimGUIApp (no display)
        import importlib
        import types

        stub = MagicMock()
        stub._last_programmed_card = None

        # Bind the real methods to stub
        import main as main_mod
        stub._on_card_programmed = types.MethodType(
            main_mod.SimGUIApp._on_card_programmed, stub)
        stub._on_export_artifacts = types.MethodType(
            main_mod.SimGUIApp._on_export_artifacts, stub)
        return stub

    def test_no_programmed_card_shows_information(self):
        """_on_export_artifacts shows info dialog when _last_programmed_card is None."""
        stub = self._make_app_stub()
        stub._last_programmed_card = None

        with patch("main.QMessageBox") as mock_mb:
            stub._on_export_artifacts()

        mock_mb.information.assert_called_once()
        args = mock_mb.information.call_args[0]
        assert "No recently programmed SIM" in args[2]

    def test_no_programmed_card_does_not_open_file_dialog(self):
        """_on_export_artifacts does not open QFileDialog when no card."""
        stub = self._make_app_stub()
        stub._last_programmed_card = None

        with patch("main.QMessageBox"), patch("main.QFileDialog") as mock_fd:
            stub._on_export_artifacts()

        mock_fd.getSaveFileName.assert_not_called()

    def test_on_card_programmed_stores_card_data(self):
        """_on_card_programmed stores card_data in _last_programmed_card."""
        stub = self._make_app_stub()
        stub.state_manager = MagicMock()
        card_data = {"ICCID": "8946001234567890123", "IMSI": "240010123456789"}

        stub._on_card_programmed(card_data)

        assert stub._last_programmed_card == card_data

    def test_on_card_programmed_emits_signal(self):
        """_on_card_programmed calls state_manager.notify_card_programmed."""
        stub = self._make_app_stub()
        stub.state_manager = MagicMock()
        card_data = {"ICCID": "8946001234567890123", "IMSI": "240010123456789"}

        stub._on_card_programmed(card_data)

        stub.state_manager.notify_card_programmed.assert_called_once_with(card_data)

    def test_export_writes_csv_with_iccid(self, tmp_path):
        """_on_export_artifacts writes a CSV containing ICCID when card exists."""
        stub = self._make_app_stub()
        stub._last_programmed_card = {
            "ICCID": "8946001234567890123",
            "IMSI": "240010123456789",
            "Ki": "A" * 32,
            "OPc": "B" * 32,
        }
        output_file = str(tmp_path / "sim_artifact_test.csv")

        with patch("main.QFileDialog") as mock_fd, \
             patch("main.QMessageBox") as mock_mb:
            mock_fd.getSaveFileName.return_value = (output_file, "CSV Files (*.csv)")
            stub._on_export_artifacts()

        assert os.path.isfile(output_file)
        with open(output_file, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["ICCID"] == "8946001234567890123"
        mock_mb.information.assert_called_once()

    def test_export_cancelled_by_user(self):
        """_on_export_artifacts does nothing when file dialog is cancelled."""
        stub = self._make_app_stub()
        stub._last_programmed_card = {"ICCID": "1234", "IMSI": "5678"}

        with patch("main.QFileDialog") as mock_fd, \
             patch("main.QMessageBox") as mock_mb:
            mock_fd.getSaveFileName.return_value = ("", "")
            stub._on_export_artifacts()

        mock_mb.information.assert_not_called()
        mock_mb.warning.assert_not_called()
