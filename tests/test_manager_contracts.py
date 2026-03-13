"""Contract tests — verify that every method/attribute called on managers
actually exists on the target class.

This catches the class of bug where a widget calls `self._cm.foo()` but
`CardManager` has no method `foo`.  The tests are AST-based and run
without tkinter or a display.
"""

import ast
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# AST visitor: extract `self.<field>.<method_or_attr>` references
# ---------------------------------------------------------------------------

class _ManagerCallVisitor(ast.NodeVisitor):
    """Find all `self.<field_name>.<attr>` references in a class."""

    def __init__(self, field_names: set[str]):
        self.field_names = field_names
        self.refs: list[tuple[int, str, str]] = []  # (lineno, field, attr)

    def visit_Attribute(self, node):
        # Match self.<field>.<attr>
        if (isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr in self.field_names):
            self.refs.append((node.lineno, node.value.attr, node.attr))
        self.generic_visit(node)


def _extract_manager_refs(filepath: str,
                          field_names: set[str]) -> list[tuple[int, str, str]]:
    """Parse *filepath* and return all self.<field>.<attr> references."""
    source = (PROJECT_ROOT / filepath).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=filepath)
    visitor = _ManagerCallVisitor(field_names)
    visitor.visit(tree)
    return visitor.refs


# ---------------------------------------------------------------------------
# CardManager contract
# ---------------------------------------------------------------------------

# Map from field name used in widgets → the class it should be
_CARD_MANAGER_FIELDS = {"_cm", "_card_manager"}

# Files that use CardManager
_CM_FILES = [
    "widgets/read_sim_panel.py",
    "widgets/program_sim_panel.py",
    "widgets/batch_program_panel.py",
    "main.py",
]


def _get_card_manager_public_api() -> set[str]:
    """Return all public and semi-public attributes of CardManager."""
    from managers.card_manager import CardManager
    cm = CardManager()
    return {name for name in dir(cm) if not name.startswith("__")}


@pytest.mark.parametrize("filepath", _CM_FILES)
def test_card_manager_contract(filepath):
    """Every self._cm.<X> / self._card_manager.<X> must exist on CardManager."""
    api = _get_card_manager_public_api()
    refs = _extract_manager_refs(filepath, _CARD_MANAGER_FIELDS)
    missing = []
    for lineno, field, attr in refs:
        if attr not in api:
            missing.append(f"  line {lineno}: self.{field}.{attr}")
    assert not missing, (
        f"{filepath} references CardManager methods/attributes that don't exist:\n"
        + "\n".join(missing)
    )


# ---------------------------------------------------------------------------
# NetworkStorageManager contract
# ---------------------------------------------------------------------------

_NS_MANAGER_FIELDS = {"_ns_manager"}

_NS_FILES = [
    "widgets/read_sim_panel.py",
    "widgets/csv_editor_panel.py",
    "widgets/program_sim_panel.py",
    "widgets/batch_program_panel.py",
    "main.py",
]


def _get_ns_manager_public_api() -> set[str]:
    from managers.network_storage_manager import NetworkStorageManager
    from managers.settings_manager import SettingsManager
    ns = NetworkStorageManager(SettingsManager())
    return {name for name in dir(ns) if not name.startswith("__")}


@pytest.mark.parametrize("filepath", _NS_FILES)
def test_ns_manager_contract(filepath):
    """Every self._ns_manager.<X> must exist on NetworkStorageManager."""
    api = _get_ns_manager_public_api()
    refs = _extract_manager_refs(filepath, _NS_MANAGER_FIELDS)
    missing = []
    for lineno, field, attr in refs:
        if attr not in api:
            missing.append(f"  line {lineno}: self.{field}.{attr}")
    assert not missing, (
        f"{filepath} references NetworkStorageManager methods that don't exist:\n"
        + "\n".join(missing)
    )


# ---------------------------------------------------------------------------
# CSVManager contract
# ---------------------------------------------------------------------------

_CSV_MANAGER_FIELDS = {"_csv"}

_CSV_FILES = [
    "widgets/csv_editor_panel.py",
    "widgets/program_sim_panel.py",
    "widgets/batch_program_panel.py",
]


def _get_csv_manager_public_api() -> set[str]:
    from managers.csv_manager import CSVManager
    cm = CSVManager()
    return {name for name in dir(cm) if not name.startswith("__")}


@pytest.mark.parametrize("filepath", _CSV_FILES)
def test_csv_manager_contract(filepath):
    """Every self._csv.<X> must exist on CSVManager."""
    api = _get_csv_manager_public_api()
    refs = _extract_manager_refs(filepath, _CSV_MANAGER_FIELDS)
    missing = []
    for lineno, field, attr in refs:
        if attr not in api:
            missing.append(f"  line {lineno}: self.{field}.{attr}")
    assert not missing, (
        f"{filepath} references CSVManager methods that don't exist:\n"
        + "\n".join(missing)
    )


# ---------------------------------------------------------------------------
# BatchManager contract
# ---------------------------------------------------------------------------

_BATCH_MANAGER_FIELDS = {"_batch_mgr"}


def _get_batch_manager_public_api() -> set[str]:
    from managers.batch_manager import BatchManager
    from managers.card_manager import CardManager
    bm = BatchManager(CardManager())
    return {name for name in dir(bm) if not name.startswith("__")}


def test_batch_manager_contract():
    """Every self._batch_mgr.<X> must exist on BatchManager."""
    api = _get_batch_manager_public_api()
    refs = _extract_manager_refs(
        "widgets/batch_program_panel.py", _BATCH_MANAGER_FIELDS)
    missing = []
    for lineno, field, attr in refs:
        if attr not in api:
            missing.append(f"  line {lineno}: self.{field}.{attr}")
    assert not missing, (
        "batch_program_panel.py references BatchManager methods that don't exist:\n"
        + "\n".join(missing)
    )
