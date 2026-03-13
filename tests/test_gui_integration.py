"""GUI integration tests — verify features are actually wired into the GUI.

These tests DON'T need a display or tkinter. They inspect source code
and module structure to confirm that:

1. All SIM data file dialogs include .eml
2. The EML parser is reachable from the code paths that load SIM data
3. Error handling (ValueError from EML parser) is caught in the GUI
"""

import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_source(relative_path: str) -> str:
    """Read a source file from the project."""
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _find_string_in_source(source: str, needle: str) -> bool:
    """Check if a string literal appears in Python source."""
    return needle in source


class _FileDialogVisitor(ast.NodeVisitor):
    """Find all filedialog.askopenfilename calls and extract filetypes."""

    def __init__(self):
        self.dialogs: list[dict] = []  # {lineno, filetypes_str, title}

    def visit_Call(self, node):
        # Look for filedialog.askopenfilename(...)
        if (isinstance(node.func, ast.Attribute)
                and node.func.attr == "askopenfilename"):
            info = {"lineno": node.lineno, "filetypes_str": "", "title": ""}
            for kw in node.keywords:
                if kw.arg == "filetypes":
                    info["filetypes_str"] = ast.dump(kw.value)
                elif kw.arg == "title":
                    if isinstance(kw.value, ast.Constant):
                        info["title"] = kw.value.value
            self.dialogs.append(info)
        self.generic_visit(node)


def _get_file_dialogs(relative_path: str) -> list[dict]:
    """Parse a file and return info about all askopenfilename calls."""
    source = _read_source(relative_path)
    tree = ast.parse(source)
    visitor = _FileDialogVisitor()
    visitor.visit(tree)
    return visitor.dialogs


# ---------------------------------------------------------------------------
# Files that load SIM data and MUST include .eml
# ---------------------------------------------------------------------------

_SIM_DATA_LOADERS = [
    "widgets/csv_editor_panel.py",
    "widgets/batch_program_panel.py",
    "widgets/program_sim_panel.py",
    "widgets/read_sim_panel.py",
    "main.py",
]


# ---------------------------------------------------------------------------
# Test: .eml in file dialog filetypes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filepath", _SIM_DATA_LOADERS)
def test_file_dialog_includes_eml(filepath):
    """Every SIM data file dialog must include *.eml in its filetypes."""
    source = _read_source(filepath)
    if "askopenfilename" not in source:
        pytest.skip(f"{filepath} has no file open dialog")

    # Check that .eml appears in the source near filetypes
    assert ".eml" in source or "SIM_DATA_FILETYPES" in source, (
        f"{filepath} has a file dialog but does not include .eml support. "
        f"Either use SIM_DATA_FILETYPES or add *.eml to filetypes.")


# ---------------------------------------------------------------------------
# Test: SIM_DATA_FILETYPES constant is correct
# ---------------------------------------------------------------------------

def test_sim_data_filetypes_has_eml():
    from managers.csv_manager import SIM_DATA_FILETYPES
    all_patterns = " ".join(pat for _, pat in SIM_DATA_FILETYPES)
    assert "*.eml" in all_patterns


def test_sim_data_filetypes_has_csv():
    from managers.csv_manager import SIM_DATA_FILETYPES
    all_patterns = " ".join(pat for _, pat in SIM_DATA_FILETYPES)
    assert "*.csv" in all_patterns


# ---------------------------------------------------------------------------
# Test: load_file() exists and handles .eml routing
# ---------------------------------------------------------------------------

def test_csv_manager_has_load_file():
    """CSVManager must have load_file() to route CSV vs EML."""
    from managers.csv_manager import CSVManager
    assert hasattr(CSVManager, "load_file")


def test_csv_manager_load_file_routes_eml():
    """load_file() must call the EML parser for .eml files."""
    from managers.csv_manager import CSVManager
    source = _read_source("managers/csv_manager.py")
    # The load_file method must check for .eml extension
    assert ".eml" in source, "CSVManager source doesn't handle .eml files"
    assert "parse_eml_file" in source or "eml_parser" in source, (
        "CSVManager doesn't reference the EML parser")


# ---------------------------------------------------------------------------
# Test: ValueError handling in GUI panels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filepath", [
    "widgets/csv_editor_panel.py",
    "widgets/batch_program_panel.py",
    "widgets/program_sim_panel.py",
    "main.py",
])
def test_valueerror_caught_in_gui(filepath):
    """GUI panels must catch ValueError from EML parser and show a messagebox."""
    source = _read_source(filepath)
    if "load_file" not in source and "load_csv_file" not in source:
        pytest.skip(f"{filepath} doesn't call load_file")
    assert "ValueError" in source, (
        f"{filepath} calls load_file/load_csv_file but doesn't catch ValueError. "
        f"EML parser errors will crash the app.")


# ---------------------------------------------------------------------------
# Test: eml_parser module structure is complete
# ---------------------------------------------------------------------------

def test_eml_parser_has_all_required_functions():
    """Every function called internally must exist."""
    import utils.eml_parser as mod
    required = [
        "parse_eml_file",
        "_get_text_body",
        "_extract_metadata_from_headers",
        "_parse_sysmocom_body",
        "_find_all_field_headers",
        "_read_card_values",
        "_parse_csv_text",
        "_normalise_field_name",
    ]
    for name in required:
        assert hasattr(mod, name), (
            f"utils/eml_parser.py is missing function '{name}'")


# ---------------------------------------------------------------------------
# Test: No hardcoded "*.csv *.txt" without .eml anywhere
# ---------------------------------------------------------------------------

def test_no_hardcoded_csv_only_filetypes():
    """No production file should have hardcoded '*.csv *.txt' without .eml."""
    for filepath in _SIM_DATA_LOADERS:
        source = _read_source(filepath)
        # Find patterns like '"*.csv *.txt"' that don't include .eml
        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            if ("*.csv" in line and "*.txt" in line
                    and "*.eml" not in line
                    and "SIM_DATA_FILETYPES" not in line
                    and "#" not in line.split("*.csv")[0]):  # ignore comments
                pytest.fail(
                    f"{filepath}:{i} has hardcoded CSV-only filetypes: "
                    f"{line.strip()}")
