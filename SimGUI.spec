# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for SimGUI macOS .app bundle

import sys
import os

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[os.getcwd()],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        # GITHASH is written by build-macos-app.sh before PyInstaller runs.
        # Conditional so a bare `pyinstaller SimGUI.spec` still works without it.
        *([('GITHASH', '.')] if os.path.exists('GITHASH') else []),
        # pySim scripts + package staged by build-macos-app.sh into pysim-bundle/.
        # Conditional so a bare `pyinstaller SimGUI.spec` still works without them.
        *([('pysim-bundle', 'pysim')] if os.path.exists('pysim-bundle') else []),
        # pySim runtime site-packages staged by build-macos-app.sh.
        *([('pysim-site-packages', 'pysim-site-packages')]
          if os.path.exists('pysim-site-packages') else []),
    ],
    hiddenimports=[
        'smartcard', 'smartcard.scard', 'smartcard.scard._scard',
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
        'textwrap', 'threading', 'tkinter', 'token', 'tokenize',
        'traceback', 'tracemalloc', 'tty', 'types', 'typing', 'unicodedata',
        'unittest', 'urllib', 'warnings', 'weakref', 'webbrowser', 'xml',
        'xmlrpc', 'zipfile', 'zipimport', 'zlib',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SimGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX to avoid bytecode issues
    upx_exclude=[],
    console=False,  # No console window on macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SimGUI',
)

app = BUNDLE(
    coll,
    name='SimGUI.app',
    icon=None,  # Set icon path if available: 'assets/icon.icns'
    bundle_identifier='com.fiskarheden.simgui',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
    },
)
