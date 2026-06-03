"""Regression guard: SimGUI.spec hiddenimports completeness and pySim import chain.

test_spec_hiddenimports_contains_required_stdlib — runs on every CI run, no skip.
    Catches missing hiddenimports before the build reaches the target machine.

test_pysim_load_pysim_imports_succeed — runs only when pySim is installed.
    Catches a broken pySim import chain in the dev environment.
"""
import importlib.util
import pathlib
import sys

import pytest

REQUIRED_STDLIB = [
    'abc', 'argparse', 'array', 'ast', 'asyncio', 'base64', 'bdb',
    'binascii', 'bisect', 'bz2', 'calendar', 'cmd', 'code', 'codecs',
    'codeop', 'collections', 'concurrent', 'contextlib', 'contextvars',
    'copy', 'copyreg', 'csv', 'ctypes', 'dataclasses', 'datetime',
    'decimal', 'difflib', 'dis', 'doctest', 'email', 'encodings',
    'enum', 'fcntl', 'fnmatch', 'fractions', 'ftplib', 'functools',
    'genericpath', 'getopt', 'getpass', 'gettext', 'glob', 'grp',
    'gzip', 'hashlib', 'heapq', 'hmac', 'html', 'http', 'importlib',
    'inspect', 'io', 'ipaddress', 'json', 'keyword', 'linecache',
    'locale', 'logging', 'lzma', 'math', 'mimetypes', 'mmap',
    'multiprocessing', 'netrc', 'ntpath', 'nturl2path', 'numbers',
    'opcode', 'operator', 'os', 'pathlib', 'pdb', 'pickle', 'pkgutil',
    'platform', 'plistlib', 'posixpath', 'pprint', 'py_compile',
    'pydoc', 'pydoc_data', 'pyexpat', 'queue', 'quopri', 'random',
    're', 'readline', 'reprlib', 'resource', 'runpy', 'secrets',
    'select', 'selectors', 'shlex', 'shutil', 'signal', 'socket',
    'socketserver', 'ssl', 'stat', 'statistics', 'string', 'struct',
    'subprocess', 'sysconfig', 'tarfile', 'tempfile', 'termios',
    'test', 'textwrap', 'threading', 'tkinter', 'token', 'tokenize',
    'traceback', 'tracemalloc', 'tty', 'types', 'typing', 'unicodedata',
    'unittest', 'urllib', 'warnings', 'weakref', 'webbrowser', 'xml',
    'xmlrpc', 'zipfile', 'zipimport', 'zlib',
]

_SPEC_PATH = pathlib.Path(__file__).resolve().parent.parent / "SimGUI.spec"


def _extract_hiddenimports_text() -> str:
    text = _SPEC_PATH.read_text()
    start = text.index("hiddenimports=[")
    end = text.index("],", start)
    return text[start:end]


def test_spec_hiddenimports_contains_required_stdlib():
    block = _extract_hiddenimports_text()
    missing = [
        mod for mod in REQUIRED_STDLIB
        if f"'{mod}'" not in block
    ]
    assert not missing, (
        "The following modules are missing from SimGUI.spec hiddenimports — "
        "add them to prevent preload failure on target:\n"
        + "\n".join(
            f"  '{mod}' missing from SimGUI.spec hiddenimports — "
            "add it to prevent preload failure on target"
            for mod in missing
        )
    )


def test_pysim_load_pysim_imports_succeed():
    pytest.importorskip("pySim.transport")

    import card_worker_inproc
    from card_worker_inproc import PysimImportError

    card_worker_inproc._pysim_runtime = None

    try:
        card_worker_inproc._load_pysim()
    except PysimImportError as exc:
        pytest.fail(f"_load_pysim() raised PysimImportError: {exc}")
