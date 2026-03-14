"""Interface contract tests - catch the *category* of bugs, not just instances.

The ``_find_all_field_headers`` bug was code calling a function that
didn't exist.  These tests ensure that:

1. Every module can be imported without error.
2. Every internal method/function call within a module targets something
   that actually exists on the class or in the module's namespace.
3. Every cross-module import resolves.
4. Callback wire-ups reference real attributes.

The strategy uses ``ast`` to statically parse every ``.py`` file and
``importlib`` to dynamically import every module, catching broken
references before any user ever runs the code.
"""

import ast
import importlib
import inspect
import os
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Ensure project root is on sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Directories to skip (not production code)
_SKIP_DIRS = {"__pycache__", "htmlcov", ".git", "debian", "scripts"}


def _iter_py_files():
    """Yield (path, dotted_module_name) for all non-test .py files."""
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            full = Path(root) / fn
            rel = full.relative_to(PROJECT_ROOT)
            # Skip test files - we're testing production code
            if "tests" in rel.parts:
                continue
            # Build dotted module name
            parts = list(rel.with_suffix("").parts)
            module_name = ".".join(parts)
            yield full, module_name


def _iter_test_files():
    """Yield test file paths."""
    test_dir = PROJECT_ROOT / "tests"
    if test_dir.exists():
        for fn in sorted(test_dir.glob("test_*.py")):
            yield fn


# ---------------------------------------------------------------------------
# Test 1: Every module can be imported
# ---------------------------------------------------------------------------

_MODULES = list(_iter_py_files())


@pytest.mark.parametrize("path,module_name", _MODULES,
                         ids=[m for _, m in _MODULES])
def test_module_imports_cleanly(path, module_name):
    """Importing every production module must not raise."""
    # Some modules need tkinter - skip if display unavailable
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        # tkinter unavailable in headless CI is acceptable
        if "tkinter" in str(exc) or "_tkinter" in str(exc):
            pytest.skip(f"Skipped (no display): {exc}")
        raise
    except RuntimeError as exc:
        if "display" in str(exc).lower() or "DISPLAY" in str(exc):
            pytest.skip(f"Skipped (no display): {exc}")
        raise


# ---------------------------------------------------------------------------
# Test 2: Self-method calls resolve (catches the _find_all_field_headers bug)
# ---------------------------------------------------------------------------

# Methods inherited from tkinter/ttk base classes - these are always available
# on widgets and dialogs even though they're not defined in the class body.
_INHERITED_TKINTER_METHODS = {
    # tk.Tk / tk.Toplevel / tk.Widget / ttk.Frame / etc.
    "title", "transient", "grab_set", "grab_release", "configure", "config",
    "destroy", "update_idletasks", "update", "winfo_width", "winfo_height",
    "winfo_exists", "winfo_x", "winfo_y", "winfo_screenwidth",
    "winfo_screenheight", "winfo_toplevel", "winfo_children", "winfo_reqwidth",
    "winfo_reqheight", "geometry", "wait_window", "after", "after_cancel",
    "after_idle", "bind", "unbind", "focus_set", "focus_get",
    "pack", "pack_forget", "grid", "grid_forget", "place", "place_forget",
    "columnconfigure", "rowconfigure", "grid_columnconfigure",
    "grid_rowconfigure", "lift", "lower", "protocol", "resizable",
    "clipboard_clear", "clipboard_append", "clipboard_get",
    "iconphoto", "iconbitmap", "minsize", "maxsize", "withdraw", "deiconify",
    "mainloop", "quit",
}

# Callback attributes set via assignment (self.on_X = ...) that are later
# called as self.on_X() - these are dynamic attributes, not methods.
_KNOWN_CALLBACK_PATTERNS = {"on_progress", "on_card_result",
                            "on_waiting_for_card", "on_completed",
                            "on_csv_loaded_callback",
                            "on_card_programmed_callback",
                            "on_card_detected", "on_card_unknown",
                            "on_card_removed", "on_error"}


class _SelfCallVisitor(ast.NodeVisitor):
    """Find all ``self.method_name(...)`` calls in a class body."""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []  # (method_name, lineno)

    def visit_Call(self, node: ast.Call):
        if (isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"):
            name = node.func.attr
            # Skip known inherited tkinter methods and callback patterns
            if (name not in _INHERITED_TKINTER_METHODS
                    and name not in _KNOWN_CALLBACK_PATTERNS):
                self.calls.append((name, node.lineno))
        self.generic_visit(node)


class _ModuleCallVisitor(ast.NodeVisitor):
    """Find all module-level function calls like ``_find_all_field_headers(...)``."""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []  # (func_name, lineno)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            self.calls.append((node.func.id, node.lineno))
        self.generic_visit(node)


def _get_class_methods(cls_node: ast.ClassDef) -> set[str]:
    """Extract method/attribute names defined in a class body."""
    names = set()
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(item.name)
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif isinstance(target, ast.Attribute):
                    names.add(target.attr)
    return names


def _get_module_level_names(tree: ast.Module) -> set[str]:
    """Extract all names defined at module level."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    # Add builtins - __builtins__ can be a dict or a module depending on context
    import builtins as _builtins_mod
    names.update(dir(_builtins_mod))
    return names


def _collect_self_call_issues():
    """Return list of (file, class, method_call, lineno) for unresolved self calls."""
    issues = []
    for path, _ in _MODULES:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            defined = _get_class_methods(node)
            # Also gather from parent classes within the same file
            # (crude but covers single-file inheritance)
            visitor = _SelfCallVisitor()
            visitor.visit(node)
            for method_name, lineno in visitor.calls:
                # Skip dunder and property access (not necessarily methods)
                if method_name.startswith("__") and method_name.endswith("__"):
                    continue
                # It's either defined in this class OR it's an attribute
                # set in __init__ (also in 'defined').  If not found, flag it.
                if method_name not in defined:
                    # Check if it's set via self.X = ... in any method
                    found_as_attr = False
                    for item in ast.walk(node):
                        if (isinstance(item, ast.Assign)
                                and any(
                                    isinstance(t, ast.Attribute)
                                    and isinstance(t.value, ast.Name)
                                    and t.value.id == "self"
                                    and t.attr == method_name
                                    for t in item.targets)):
                            found_as_attr = True
                            break
                    if not found_as_attr:
                        issues.append((
                            str(path.relative_to(PROJECT_ROOT)),
                            node.name,
                            method_name,
                            lineno,
                        ))
    return issues


def _collect_module_call_issues():
    """Return list of (file, func_call, lineno) for unresolved module-level calls."""
    issues = []
    for path, _ in _MODULES:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        module_names = _get_module_level_names(tree)
        # Collect calls that are NOT inside a class
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visitor = _ModuleCallVisitor()
                visitor.visit(node)
                for func_name, lineno in visitor.calls:
                    if func_name not in module_names:
                        issues.append((
                            str(path.relative_to(PROJECT_ROOT)),
                            func_name,
                            lineno,
                        ))
    return issues


_SELF_ISSUES = _collect_self_call_issues()
_MODULE_ISSUES = _collect_module_call_issues()


def test_no_unresolved_self_calls():
    """Every self.method() call must reference a method/attribute that exists.

    This is the test that would have caught the _find_all_field_headers bug.
    """
    if _SELF_ISSUES:
        msg = "Unresolved self.method() calls found:\n"
        for file, cls, method, lineno in _SELF_ISSUES:
            msg += f"  {file}:{lineno} - {cls}.{method}()\n"
        pytest.fail(msg)


def test_no_unresolved_module_calls():
    """Every module-level function call must target something defined or imported."""
    if _MODULE_ISSUES:
        msg = "Unresolved module-level function calls found:\n"
        for file, func, lineno in _MODULE_ISSUES:
            msg += f"  {file}:{lineno} - {func}()\n"
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 3: Cross-module imports - every 'from X import Y' resolves
# ---------------------------------------------------------------------------

def _collect_import_statements():
    """Return list of (file, module, names) for all from-imports."""
    imports = []
    for path, _ in _MODULES:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [a.name for a in node.names]
                imports.append((
                    str(path.relative_to(PROJECT_ROOT)),
                    node.module,
                    names,
                    node.lineno,
                ))
    return imports


_IMPORTS = _collect_import_statements()


@pytest.mark.parametrize(
    "file,module,names,lineno", _IMPORTS,
    ids=[f"{f}:{m}:{ln}" for f, m, _, ln in _IMPORTS]
)
def test_from_import_resolves(file, module, names, lineno):
    """Every 'from X import Y' in production code must resolve."""
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        if "tkinter" in str(exc) or "_tkinter" in str(exc):
            pytest.skip(f"Skipped (no display): {exc}")
        # pyscard (smartcard) is an optional dependency available only
        # inside the pySim venv on real hardware.  The import is
        # guarded by try/except at runtime, so missing here is fine.
        if "smartcard" in str(exc):
            pytest.skip(f"Skipped (optional dep): {exc}")
        pytest.fail(f"{file}:{lineno} - cannot import module '{module}': {exc}")
    except RuntimeError as exc:
        if "display" in str(exc).lower():
            pytest.skip(f"Skipped (no display): {exc}")
        raise
    for name in names:
        if name == "*":
            continue
        if not hasattr(mod, name):
            pytest.fail(
                f"{file}:{lineno} - 'from {module} import {name}' - "
                f"'{name}' does not exist in module '{module}'")


# ---------------------------------------------------------------------------
# Test 4: Public API smoke - every public function is at least callable
# ---------------------------------------------------------------------------

def test_eml_parser_public_api():
    """The EML parser's public function must be callable without crashing on import."""
    from utils.eml_parser import parse_eml_file
    assert callable(parse_eml_file)


def test_csv_manager_load_file_exists():
    """CSVManager.load_file() must exist (it's the unified entry point)."""
    from managers.csv_manager import CSVManager
    mgr = CSVManager()
    assert hasattr(mgr, "load_file")
    assert callable(mgr.load_file)


def test_csv_manager_load_csv_exists():
    """CSVManager.load_csv() must still exist (backward compat)."""
    from managers.csv_manager import CSVManager
    mgr = CSVManager()
    assert hasattr(mgr, "load_csv")
    assert callable(mgr.load_csv)


def test_sim_data_filetypes_includes_eml():
    """The shared filetypes constant must include .eml."""
    from managers.csv_manager import SIM_DATA_FILETYPES
    all_patterns = " ".join(pat for _, pat in SIM_DATA_FILETYPES)
    assert "*.eml" in all_patterns, (
        f"SIM_DATA_FILETYPES missing *.eml: {SIM_DATA_FILETYPES}")
